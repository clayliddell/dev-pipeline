"""E2E dry-run tests for the full pipeline."""

import json
from pathlib import Path

from kanban import Kanban
from lib import (
    create_or_checkout_branch,
    get_diff,
)
from lib import (
    build_pm_prompt,
    build_swe_prompt,
    build_cr_prompt,
    build_cr_eval_prompt,
    build_sanity_prompt,
)

from pipeline import PipelineConfig, run_pipeline, resolve_phase_file


class TestDryRunSingleTask:
    """Run the full pipeline in dry-run/single-task mode against a temp project."""

    def test_completes_without_error(self, project_tree):
        config = PipelineConfig(
            local_repo_path=project_tree,
            kanban_path=project_tree / "env" / "kanban.json",
            docs_path=project_tree / "docs",
            base_branch="main",
            remote_name="origin",
            loop_until_phase_complete=False,
            dry_run=True,
        )
        kanban = Kanban(config.kanban_path)
        kanban.load()

        run_pipeline(config, kanban)

        # Task should be marked done
        task = kanban._get_task("phase-1.comp-a.task-1")
        assert task is not None
        assert task[2]["status"] == "done"

    def test_phase_file_resolved(self, project_tree):
        config = PipelineConfig(
            local_repo_path=project_tree,
            kanban_path=project_tree / "env" / "kanban.json",
            docs_path=project_tree / "docs",
            base_branch="main",
        )
        kanban = Kanban(config.kanban_path)
        kanban.load()
        path = resolve_phase_file(config, kanban)
        assert path.name == "PHASE-1.md"
        assert path.exists()


class TestDryRunBranchHandling:
    """Verify branch create/delete works in dry-run context."""
    pass


class TestDryRunEndToEnd:
    """Full E2E: run pipeline, verify kanban state, then run again and hit no tasks."""

    def test_loop_exits_when_no_tasks(self, project_tree):
        config = PipelineConfig(
            local_repo_path=project_tree,
            kanban_path=project_tree / "env" / "kanban.json",
            docs_path=project_tree / "docs",
            base_branch="main",
            loop_until_phase_complete=True,
            dry_run=True,
        )
        kanban = Kanban(config.kanban_path)
        kanban.load()

        # First run: completes the one task
        run_pipeline(config, kanban)
        assert kanban._get_task("phase-1.comp-a.task-1")[2]["status"] == "done"

        # Second run: nothing to do
        run_pipeline(config, kanban)
        # Should return without error

    def test_kanban_persists_across_reload(self, project_tree):
        config = PipelineConfig(
            local_repo_path=project_tree,
            kanban_path=project_tree / "env" / "kanban.json",
            docs_path=project_tree / "docs",
            base_branch="main",
            loop_until_phase_complete=False,
            dry_run=True,
        )
        kanban = Kanban(config.kanban_path)
        kanban.load()
        run_pipeline(config, kanban)

        # Reload from disk
        kanban2 = Kanban(config.kanban_path)
        kanban2.load()
        assert kanban2._get_task("phase-1.comp-a.task-1")[2]["status"] == "done"
