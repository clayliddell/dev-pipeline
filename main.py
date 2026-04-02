"""CLI entry point for the pipeline."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dataclasses import dataclass

from pipeline import (
    Kanban,
    checkout_main_and_pull,
    create_branch,
    get_diff,
    get_file_tree,
    merge_branch,
    push,
    run_agent,
    parse_agent_response,
    build_pm_prompt,
    build_swe_prompt,
    build_cr_prompt,
    build_cr_eval_prompt,
    build_sanity_prompt,
)


class PipelineError(Exception):
    pass


@dataclass(slots=True)
class PipelineConfig:
    project_repo: Path
    kanban_path: Path
    docs_path: Path
    base_branch: str = "main"
    remote_name: str = "origin"
    max_tree_depth: int = 4
    max_tree_entries: int = 200
    loop_until_phase_complete: bool = True
    dry_run: bool = False


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the dev-pipeline")
    parser.add_argument(
        "--project-repo",
        default=os.path.expanduser("~/dev/agentvm"),
        help="Path to the project git repository",
    )
    parser.add_argument(
        "--kanban-path",
        default=None,
        help="Path to kanban.json (default: <project-repo>/env/kanban.json)",
    )
    parser.add_argument(
        "--docs-path",
        default=None,
        help="Path to the project documents folder (default: <project-repo>/docs)",
    )
    parser.add_argument("--base-branch", default="main")
    parser.add_argument("--remote-name", default="origin")
    parser.add_argument(
        "--single-task",
        action="store_true",
        help="Process only one task instead of looping until the phase completes",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Run in dry-run mode with mock agents"
    )
    return parser.parse_args(argv)


def resolve_phase_file(config: PipelineConfig, kanban: Kanban) -> Path:
    """Map kanban meta.current_phase (e.g. 'phase-1') to docs/phases/PHASE-1.md."""
    phase_id = kanban.data["meta"]["current_phase"]
    parts = phase_id.split("-")
    if len(parts) == 2 and parts[1].isdigit():
        filename = f"PHASE-{parts[1]}.md"
    else:
        filename = f"{phase_id.upper()}.md"
    path = config.docs_path / "phases" / filename
    if not path.exists():
        raise PipelineError(f"Phase file not found: {path}")
    return path


def read_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def mock_run_agent(
    prompt: str, project_dir: Path, opencode_config_path: Path, agent: str = "default", **kwargs
) -> str:
    """Dry-run stub — prints a summary and returns canned JSON output."""
    preview = prompt[:120].replace("\n", " ")
    print(f"\n{'─' * 60}")
    print(f"  [DRY-RUN] Agent: {agent}")
    print(f"  [PROMPT]: {preview}...")
    print(f"{'─' * 60}")

    if agent == "sanity":
        return '{"task_success": true, "message": "Dry-run: all criteria assumed met."}'
    if agent == "swe":
        return '{"task_success": true, "message": "Implementation complete."}'
    if agent == "cr-eval":
        return '{"task_success": true, "message": "Dry-run: no changes applied."}'
    return '{"task_success": true, "message": "Dry-run: mock agent completed."}'


def validate_agent_response(output: str, agent_name: str) -> str:
    """Parse agent output, halt pipeline on task_success=false.

    Returns the message string on success.
    """
    try:
        result = parse_agent_response(output)
    except ValueError as exc:
        raise PipelineError(
            f"Agent '{agent_name}' returned invalid response format.\n{exc}"
        ) from exc

    if not result["task_success"]:
        raise PipelineError(
            f"Agent '{agent_name}' reported failure: {result['message']}"
        )

    return result["message"]


def run_pipeline(config: PipelineConfig, kanban: Kanban) -> None:
    """Main pipeline orchestration — the 10-step loop from README.md."""

    agent_fn = mock_run_agent if config.dry_run else run_agent
    opencode_config_path = Path("agents.opencode.json").resolve()

    while True:
        # ── 1. Pick up task ────────────────────────────────────────
        task = kanban.pickup_next()
        if task is None:
            print("[pipeline] No unblocked tasks available. Done.")
            return
        kanban.save()
        print(f"\n[pipeline] Picked up task: {task['id']} — {task['content']}")

        # ── Resolve context ────────────────────────────────────────
        phase_file_path = resolve_phase_file(config, kanban)

        code_standard = read_file(config.docs_path / "CODE-STANDARD.md")
        architecture = read_file(config.docs_path / "ARCHITECTURE.md")
        phase_content = read_file(phase_file_path)
        fs_tree = get_file_tree(
            config.project_repo, config.max_tree_depth, config.max_tree_entries
        )

        # ── 2. Git setup ──────────────────────────────────────────
        if not config.dry_run:
            checkout_main_and_pull(config.project_repo, config.remote_name)
        branch = f"feature/{task['id']}"
        create_branch(config.project_repo, branch)

        # ── 3. PM Agent (no tool use) ─────────────────────────────
        pm_prompt = build_pm_prompt(
            task, code_standard, architecture, phase_content, fs_tree
        )
        pm_output = agent_fn(
            pm_prompt,
            config.project_repo,
            opencode_config_path,
            agent="project-manager",
            agent_name="Project Manager",
        )
        pm_message = validate_agent_response(pm_output, "Project Manager")

        # ── 4. SWE Agent (tool use) ───────────────────────────────
        swe_prompt = build_swe_prompt(pm_message)
        swe_output = agent_fn(
            swe_prompt,
            config.project_repo,
            opencode_config_path,
            agent="software-engineer",
            agent_name="Software Engineer",
        )
        validate_agent_response(swe_output, "Software Engineer")

        # ── 5. Move to review ─────────────────────────────────────
        kanban.set_status(task["id"], "in_review")
        kanban.save()

        # ── 6. CR Agent (no tool use) ─────────────────────────────
        diff = get_diff(config.project_repo, config.base_branch)
        cr_prompt = build_cr_prompt(
            diff, task, architecture, code_standard, phase_content, fs_tree
        )
        cr_output = agent_fn(
            cr_prompt,
            config.project_repo,
            opencode_config_path,
            agent="code-reviewer",
            agent_name="Code Reviewer",
        )
        cr_message = validate_agent_response(cr_output, "Code Reviewer")

        # ── 7. CR Eval Agent (tool use) ───────────────────────────
        cr_eval_prompt = build_cr_eval_prompt(cr_message)
        cr_eval_output = agent_fn(
            cr_eval_prompt,
            config.project_repo,
            opencode_config_path,
            agent="cr-evaler",
            agent_name="Code Review Evaluator",
        )
        validate_agent_response(cr_eval_output, "Code Review Evaluator")

        # ── 8. Sanity Check Agent (no tool use) ───────────────────
        diff = get_diff(config.project_repo, config.base_branch)
        sanity_prompt = build_sanity_prompt(task, diff)
        sanity_output = agent_fn(
            sanity_prompt,
            config.project_repo,
            opencode_config_path,
            agent="sanity-checker",
            agent_name="Sanity Check",
        )
        validate_agent_response(sanity_output, "Sanity Check")

        # ── 9. Merge and mark done ────────────────────────────────
        if not config.dry_run:
            merge_branch(config.project_repo, branch, config.base_branch)
            push(config.project_repo, config.remote_name, config.base_branch)
        kanban.set_status(task["id"], "done")
        kanban.save()
        print(f"[pipeline] Task {task['id']} completed and merged.")

        # ── 10. Check phase completion ────────────────────────────
        if not config.loop_until_phase_complete:
            print("[pipeline] Single-task mode. Done.")
            return

        current_phase = kanban.data["meta"]["current_phase"]
        if kanban.is_phase_complete(current_phase):
            print(f"[pipeline] Phase '{current_phase}' is complete. Done.")
            return


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    project_repo = Path(args.project_repo).expanduser().resolve()
    kanban_path = (
        Path(args.kanban_path).expanduser().resolve()
        if args.kanban_path
        else project_repo / "env" / "kanban.json"
    )
    docs_path = (
        Path(args.docs_path).expanduser().resolve()
        if args.docs_path
        else project_repo / "docs"
    )

    config = PipelineConfig(
        project_repo=project_repo,
        docs_path=docs_path,
        kanban_path=kanban_path,
        base_branch=args.base_branch,
        remote_name=args.remote_name,
        loop_until_phase_complete=not args.single_task,
        dry_run=args.dry_run,
    )

    kanban = Kanban(config.kanban_path)
    kanban.load()

    try:
        run_pipeline(config, kanban)
    except PipelineError as exc:
        print(f"\n[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
