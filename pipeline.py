"""CLI entry point for the pipeline."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess

from dataclasses import dataclass

from kanban import Kanban
from lib import (
    AgentRunResult,
    current_branch,
    has_changes,
    check_agent_success,
    commit_uncommitted_changes,
    create_or_checkout_branch,
    get_diff,
    get_file_tree,
    merge_branch,
    fetch_or_pull_base,
    push,
    rebase_base,
    run_agent,
    success_response_found,
    build_pm_prompt,
    build_swe_prompt,
    build_cr_prompt,
    build_cr_eval_prompt,
    build_sanity_prompt,
)
from lib.jsonlog import close_json_log, log_json, setup_json_log
from lib.tui import (
    TerminalBlock,
    print_block,
    setup_log,
    close_log,
)


class PipelineError(Exception):
    pass


@dataclass(slots=True)
class PipelineConfig:
    local_repo_path: Path
    kanban_path: Path
    docs_path: Path
    base_branch: str = "main"
    remote_name: str = "origin"
    opencode_config_path: Path = Path("opencode.json")
    max_tree_depth: int = 4
    max_tree_entries: int = 200
    loop_until_phase_complete: bool = True
    dry_run: bool = False
    log_path: Path | None = None
    json_log_path: Path | None = None
    step_by_step: bool = False
    ssh_host: str | None = None
    ssh_repo_path: Path | None = None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the dev-pipeline")

    parser.add_argument(
        "--local-repo-path",
        required=True,
        help="Path to the project git repository",
    )
    parser.add_argument(
        "--kanban-path",
        default=None,
        help="Path to kanban.json (default: <local-repo-path>/env/kanban.json)",
    )
    parser.add_argument(
        "--docs-path",
        default=None,
        help="Path to the project documents folder (default: <local-repo-path>/docs)",
    )
    parser.add_argument(
        "--base-branch",
        default="main",
        help="Upstream branch to use when changes are pushed. (default: main)"
    )
    parser.add_argument(
        "--remote-name",
        default="origin",
        help="Upstream remote to use when changes are pushed. (default: origin)"
    )
    parser.add_argument(
        "--single-task",
        action="store_true",
        help="Process only one task instead of looping until the phase completes (default: False)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run in dry-run mode with mock agents (default: False)"
    )
    parser.add_argument(
        "--log",
        default=None,
        help="Path to log file (captures all pipeline output)",
    )
    parser.add_argument(
        "--logging-json",
        default=None,
        help="Path to JSONL log file (captures pipeline and OpenCode events)",
    )
    parser.add_argument(
        "--step",
        action="store_true",
        help="Pause before each step and wait for [c] to continue (default: False)",
    )
    parser.add_argument(
        "--ssh-host",
        default=None,
        help="ssh host name you want to run opencode commands on",
    )
    parser.add_argument(
        "--ssh-repo-path",
        default=None,
        help="""Path to the project git repository
                (USE " AROUND ARGUMENT TO PREVENT PREMATURE SHELL EXPANSION)""",
    )
    parser.add_argument(
        "--opencode-config-path",
        default="opencode.json",
        help="""Project-relative or absolute path to opencode config
                If path starts with '/', absolute is assumed; otherwise, relative

                (Ex: 'relative/path/to/opencode.json' ->
                       '/path/to/project/relative/path/to/opencode.json'
                     '/absolute/path/to/opencode.json' ->
                       '/absolute/path/to/opencode.json')

                (default: "opencode.json")"""
    )
    args = parser.parse_args(argv)

    # check conditional args
    if args.ssh_host and not args.ssh_repo_path:
        parser.error("ssh_repo_path required when ssh_host flag is used")
    if args.ssh_repo_path and not args.ssh_host:
        parser.error("ssh_host required when ssh_repo_path flag is used")

    return args

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


def log_pipeline_event(event: str, **fields) -> None:
    log_json(f"pipeline.{event}", **fields)


def mock_run_agent(
    prompt: str,
    project_dir: Path,
    opencode_config_path: Path,
    agent: str = "default",
    **kwargs,
) -> AgentRunResult:
    """Dry-run stub — prints a summary and returns canned agent output."""
    task_id = kwargs.get("task_id", "")
    step_num = kwargs.get("step_num", 0)
    step_title = kwargs.get("step_title", "")
    prefix = f"{task_id} - Step {step_num}: {step_title}" if task_id else ""

    preview = prompt[:120].replace("\n", " ")
    print_block(
        TerminalBlock(
            "AGENT",
            f"[DRY-RUN] Agent: {agent}\nPrompt: {preview}...",
            subtitle="dry-run",
            title_prefix=prefix,
        )
    )

    return AgentRunResult(
        response="Dry-run: mock agent completed.",
        session_id=f"dry-run-{agent}",
    )


def mock_check_agent_success(
    project_dir: Path,
    opencode_config_path: Path,
    *,
    agent: str,
    agent_name: str,
    prior_result: AgentRunResult,
    task_id: str = "",
    step_num: int = 0,
    step_title: str = "",
    ssh_host: str | None = None,
) -> AgentRunResult:
    return AgentRunResult(response="yes", session_id=prior_result.session_id)


def ensure_agent_succeeded(
    project_dir: Path,
    opencode_config_path: Path,
    *,
    agent: str,
    agent_name: str,
    result: AgentRunResult,
    task_id: str,
    step_num: int,
    step_title: str,
    success_check_fn,
    ssh_host: str | None = None,
) -> str:
    success_result = success_check_fn(
        project_dir,
        opencode_config_path,
        agent=agent,
        agent_name=agent_name,
        prior_result=result,
        task_id=task_id,
        step_num=step_num,
        step_title=f"{step_title} Success Check",
        ssh_host=ssh_host,
    )
    if not success_response_found(success_result.response):
        raise PipelineError(
            f"Agent '{agent_name}' did not confirm success.\n"
            f"Follow-up response was:\n{success_result.response[:500]}"
        )
    return result.response


def run_pipeline(config: PipelineConfig, kanban: Kanban) -> None:
    """Main pipeline orchestration — the 10-step loop from README.md."""

    log_pipeline_event(
        "start",
        local_repo_path=config.local_repo_path,
        kanban_path=config.kanban_path,
        docs_path=config.docs_path,
        base_branch=config.base_branch,
        remote_name=config.remote_name,
        dry_run=config.dry_run,
        loop_until_phase_complete=config.loop_until_phase_complete,
        step_by_step=config.step_by_step,
        ssh_host=config.ssh_host,
        ssh_repo_path=config.ssh_repo_path,
    )

    agent_fn = mock_run_agent if config.dry_run else run_agent
    success_check_fn = (
        mock_check_agent_success if config.dry_run else check_agent_success
    )
    # local path to perform git commands on
    git_repo_path = config.local_repo_path
    # project path to perform all other commands on
    project_repo_path = config.ssh_repo_path or config.local_repo_path
    opencode_config_path = config.opencode_config_path

    while True:
        # ── 1. Pick up task ────────────────────────────────────────
        task = kanban.pickup_next()
        if task is None:
            log_pipeline_event("no_tasks_available")
            print("[pipeline] No unblocked tasks available. Done.")
            return
        kanban.save()
        task_id = task["id"]
        step = 0

        log_pipeline_event(
            "task.picked_up",
            task_id=task_id,
            task=task,
        )

        print_block(
            TerminalBlock(
                "INFO",
                f"Task: {task_id}\n{task['content']}",
                subtitle="picked up",
                title_prefix=task_id,
            )
        )

        def pause(step_title: str):
            """Pause before a step if --step is enabled."""
            if not config.step_by_step:
                return
            input("Press Enter to continue...")

        # ── Resolve context ────────────────────────────────────────
        phase_file_path = resolve_phase_file(config, kanban)
        log_pipeline_event(
            "phase.resolved",
            task_id=task_id,
            phase=kanban.data["meta"]["current_phase"],
            phase_file=phase_file_path,
        )
        code_standard = read_file(config.docs_path / "CODE-STANDARD.md")
        architecture = read_file(config.docs_path / "ARCHITECTURE.md")
        phase_content = read_file(phase_file_path)
        fs_tree = get_file_tree(
            config.local_repo_path,
            config.max_tree_depth,
            config.max_tree_entries,
        )

        # ── 2. Git setup ──────────────────────────────────────────
        step = 2
        log_pipeline_event(
            "step.start", task_id=task_id, step_num=step, step_title="Git Setup"
        )
        pause("Git Setup")
        feature_branch = f"feature/{task_id}"
        curr_branch = current_branch(git_repo_path)
        if not config.dry_run:
            # if were on a feature branch with uncommitted changes, and it's not the feature
            # we're currently working on, then raise a PipelineError
            if has_changes(git_repo_path) and curr_branch != feature_branch:
                raise PipelineError(
                    f"Uncommited changes on current feature branch '{curr_branch}' and "
                    f"current feature branch not matching current kanban task '{task_id}'."
                ) from None
            fetch_or_pull_base(
                git_repo_path, config.remote_name, config.base_branch
            )

        if curr_branch != feature_branch:
            create_or_checkout_branch(git_repo_path, feature_branch, config.base_branch)

        if not config.dry_run:
            rebase_base(git_repo_path, config.base_branch)

        log_pipeline_event(
            "branch.created",
            task_id=task_id,
            branch=feature_branch,
            step_num=step,
            step_title="Git Setup",
        )
        print_block(
            TerminalBlock(
                "INFO",
                f"Branch: {feature_branch}",
                subtitle="created",
                title_prefix=f"{task_id} - Step {step}: Git Setup",
            )
        )
        log_pipeline_event(
            "step.complete",
            task_id=task_id,
            step_num=step,
            step_title="Git Setup",
            branch=feature_branch,
        )

        # ── 3. PM Agent (no tool use) ─────────────────────────────
        step = 3
        log_pipeline_event(
            "step.start", task_id=task_id, step_num=step, step_title="Project Manager"
        )
        pause("Project Manager")
        pm_prompt = build_pm_prompt(
            task, code_standard, architecture, phase_content, fs_tree
        )
        pm_output = agent_fn(
            pm_prompt,
            project_repo_path,
            opencode_config_path,
            agent="project-manager",
            agent_name="Project Manager",
            task_id=task_id,
            step_num=step,
            step_title="Project Manager",
            ssh_host=config.ssh_host,
        )
        pm_message = ensure_agent_succeeded(
            project_repo_path,
            opencode_config_path,
            agent="project-manager",
            agent_name="Project Manager",
            result=pm_output,
            task_id=task_id,
            step_num=step,
            step_title="Project Manager",
            ssh_host=config.ssh_host,
            success_check_fn=success_check_fn,
        )
        log_pipeline_event(
            "step.complete",
            task_id=task_id,
            step_num=step,
            step_title="Project Manager",
        )

        # ── 4. SWE Agent (tool use) ───────────────────────────────
        step = 4
        log_pipeline_event(
            "step.start", task_id=task_id, step_num=step, step_title="Software Engineer"
        )
        pause("Software Engineer")
        swe_prompt = build_swe_prompt(pm_message)
        swe_output = agent_fn(
            swe_prompt,
            project_repo_path,
            opencode_config_path,
            agent="software-engineer",
            agent_name="Software Engineer",
            task_id=task_id,
            step_num=step,
            step_title="Software Engineer",
            ssh_host=config.ssh_host,
        )
        ensure_agent_succeeded(
            project_repo_path,
            opencode_config_path,
            agent="software-engineer",
            agent_name="Software Engineer",
            result=swe_output,
            task_id=task_id,
            step_num=step,
            step_title="Software Engineer",
            ssh_host=config.ssh_host,
            success_check_fn=success_check_fn,
        )
        log_pipeline_event(
            "step.complete",
            task_id=task_id,
            step_num=step,
            step_title="Software Engineer",
        )

        # ── 5. Move to review ─────────────────────────────────────
        step = 5
        log_pipeline_event(
            "step.start", task_id=task_id, step_num=step, step_title="Move to Review"
        )
        pause("Move to Review")
        kanban.set_status(task_id, "in_review")
        kanban.save()
        log_pipeline_event(
            "status.updated",
            task_id=task_id,
            status="in_review",
            step_num=step,
            step_title="Move to Review",
        )
        print_block(
            TerminalBlock(
                "INFO",
                "Status: in_review",
                subtitle="kanban updated",
                title_prefix=f"{task_id} - Step {step}: Move to Review",
            )
        )
        log_pipeline_event(
            "step.complete", task_id=task_id, step_num=step, step_title="Move to Review"
        )

        # ── 6. CR Agent (no tool use) ─────────────────────────────
        step = 6
        log_pipeline_event(
            "step.start", task_id=task_id, step_num=step, step_title="Code Review"
        )
        pause("Code Review")
        diff = get_diff(git_repo_path, config.base_branch)
        cr_prompt = build_cr_prompt(
            diff, task, architecture, code_standard, phase_content, fs_tree
        )
        cr_output = agent_fn(
            cr_prompt,
            project_repo_path,
            opencode_config_path,
            agent="code-reviewer",
            agent_name="Code Reviewer",
            task_id=task_id,
            step_num=step,
            step_title="Code Review",
            ssh_host=config.ssh_host,
        )
        cr_message = ensure_agent_succeeded(
            project_repo_path,
            opencode_config_path,
            agent="code-reviewer",
            agent_name="Code Reviewer",
            result=cr_output,
            task_id=task_id,
            step_num=step,
            step_title="Code Review",
            ssh_host=config.ssh_host,
            success_check_fn=success_check_fn,
        )
        log_pipeline_event(
            "step.complete", task_id=task_id, step_num=step, step_title="Code Review"
        )

        # ── 7. CR Eval Agent (tool use) ───────────────────────────
        step = 7
        log_pipeline_event(
            "step.start",
            task_id=task_id,
            step_num=step,
            step_title="Code Review Evaluation",
        )
        pause("Code Review Evaluation")
        cr_eval_prompt = build_cr_eval_prompt(cr_message)
        cr_eval_output = agent_fn(
            cr_eval_prompt,
            project_repo_path,
            opencode_config_path,
            agent="cr-evaler",
            agent_name="Code Review Evaluator",
            task_id=task_id,
            step_num=step,
            step_title="Code Review Evaluation",
            ssh_host=config.ssh_host,
        )
        ensure_agent_succeeded(
            project_repo_path,
            opencode_config_path,
            agent="cr-evaler",
            agent_name="Code Review Evaluator",
            result=cr_eval_output,
            task_id=task_id,
            step_num=step,
            step_title="Code Review Evaluation",
            ssh_host=config.ssh_host,
            success_check_fn=success_check_fn,
        )
        log_pipeline_event(
            "step.complete",
            task_id=task_id,
            step_num=step,
            step_title="Code Review Evaluation",
        )

        # ── 8. Sanity Check Agent (no tool use) ───────────────────
        step = 8
        log_pipeline_event(
            "step.start", task_id=task_id, step_num=step, step_title="Sanity Check"
        )
        pause("Sanity Check")
        diff = get_diff(git_repo_path, config.base_branch)
        sanity_prompt = build_sanity_prompt(task, diff)
        sanity_output = agent_fn(
            sanity_prompt,
            project_repo_path,
            opencode_config_path,
            agent="sanity-checker",
            agent_name="Sanity Check",
            task_id=task_id,
            step_num=step,
            step_title="Sanity Check",
            ssh_host=config.ssh_host,
        )
        ensure_agent_succeeded(
            project_repo_path,
            opencode_config_path,
            agent="sanity-checker",
            agent_name="Sanity Check",
            result=sanity_output,
            task_id=task_id,
            step_num=step,
            step_title="Sanity Check",
            ssh_host=config.ssh_host,
            success_check_fn=success_check_fn,
        )
        log_pipeline_event(
            "step.complete", task_id=task_id, step_num=step, step_title="Sanity Check"
        )

        # ── 9. Commit, merge and mark done ────────────────────────
        step = 9
        log_pipeline_event(
            "step.start",
            task_id=task_id,
            step_num=step,
            step_title="Commit, Merge & Push",
        )
        pause("Commit, Merge & Push")
        if not config.dry_run:
            commit_uncommitted_changes(git_repo_path, task["content"])
            merge_branch(git_repo_path, feature_branch, config.base_branch)
            push(git_repo_path, config.remote_name, config.base_branch)
        kanban.set_status(task_id, "done")
        kanban.save()
        log_pipeline_event(
            "status.updated",
            task_id=task_id,
            status="done",
            step_num=step,
            step_title="Commit, Merge & Push",
        )
        print_block(
            TerminalBlock(
                "INFO",
                "Task completed and merged.",
                subtitle="done",
                title_prefix=f"{task_id} - Step {step}: Commit, Merge & Push",
            )
        )
        log_pipeline_event(
            "step.complete",
            task_id=task_id,
            step_num=step,
            step_title="Commit, Merge & Push",
        )

        # ── 10. Check phase completion ────────────────────────────
        if not config.loop_until_phase_complete:
            log_pipeline_event("exit.single_task", task_id=task_id)
            print("[pipeline] Single-task mode. Done.")
            return

        current_phase = kanban.data["meta"]["current_phase"]
        if kanban.is_phase_complete(current_phase):
            log_pipeline_event("exit.phase_complete", phase=current_phase)
            print(f"[pipeline] Phase '{current_phase}' is complete. Done.")
            return

def resolve_opencode_config_path(unresolved_opencode_config_path: str,
                                 local_repo_path: Path,
                                 ssh_repo_path: Path | None) -> Path:
    """Resolve relative path to opencode config.

    If config path does not begin with '/', assume path is relative and
      resolve.

    Ex:
    'relative/path/to/opencode.json' ->
      '/path/to/project/relative/path/to/opencode.json'
    '/absolute/path/to/opencode.json' ->
      '/absolute/path/to/opencode.json'
    """
    opencode_config_path = Path(unresolved_opencode_config_path)
    if not unresolved_opencode_config_path.startswith('/'):
        if ssh_repo_path:
            opencode_config_path = ssh_repo_path / opencode_config_path
        else:
            opencode_config_path = local_repo_path / opencode_config_path

    return opencode_config_path

def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    local_repo_path = Path(args.local_repo_path).expanduser().resolve()
    kanban_path = (
        Path(args.kanban_path).expanduser().resolve()
        if args.kanban_path
        else local_repo_path / "env" / "kanban.json"
    )
    docs_path = (
        Path(args.docs_path).expanduser().resolve()
        if args.docs_path
        else local_repo_path / "docs"
    )

    ssh_repo_path = subprocess.run(
        ["ssh", args.ssh_host, "readlink", "-e", args.ssh_repo_path],
        capture_output=True,
        text=True,
        check=True,
    )
    ssh_repo_path = ssh_repo_path.stdout.strip("\r\n")
    ssh_repo_path = Path(ssh_repo_path)

    opencode_config_path = resolve_opencode_config_path(
        args.opencode_config_path,
        local_repo_path,
        ssh_repo_path
    )

    config = PipelineConfig(
        local_repo_path=local_repo_path,
        docs_path=docs_path,
        kanban_path=kanban_path,
        base_branch=args.base_branch,
        remote_name=args.remote_name,
        loop_until_phase_complete=not args.single_task,
        dry_run=args.dry_run,
        log_path=Path(args.log).resolve() if args.log else None,
        json_log_path=Path(args.logging_json).expanduser().resolve()
        if args.logging_json
        else None,
        step_by_step=args.step,
        ssh_host=args.ssh_host,
        ssh_repo_path=Path(ssh_repo_path),
        opencode_config_path=Path(opencode_config_path),
    )

    try:
        if config.log_path:
            setup_log(config.log_path)
        if config.json_log_path:
            setup_json_log(config.json_log_path)

        kanban = Kanban(config.kanban_path)
        kanban.load()

        log_pipeline_event(
            "configured",
            local_repo_path=config.local_repo_path,
            ssh_host=config.ssh_host,
            ssh_repo_path=config.ssh_repo_path,
            kanban_path=config.kanban_path,
            docs_path=config.docs_path,
            base_branch=config.base_branch,
            remote_name=config.remote_name,
            log_path=config.log_path,
            json_log_path=config.json_log_path,
        )

        run_pipeline(config, kanban)
    except PipelineError as exc:
        log_pipeline_event(
            "error",
            error_type="PipelineError",
            message=str(exc),
        )
        print_block(
            TerminalBlock(
                "ERROR",
                str(exc),
                subtitle="pipeline halted",
            )
        )
        raise SystemExit(1) from None
    finally:
        close_log()
        close_json_log()


if __name__ == "__main__":
    main()
