"""E2E dry-run tests for the full pipeline."""

import json
from pathlib import Path

import pytest

import pipeline

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
)
from lib.git import GitRebaseError

from pipeline import PipelineConfig, PipelineError, run_pipeline, resolve_phase_file


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
        assert "resume" not in task[2]

    def test_resumes_software_engineer_from_cached_pm_output(self, project_tree, monkeypatch):
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
        kanban.set_status("phase-1.comp-a.task-1", "software_engineer")
        kanban.set_resume_payload(
            "phase-1.comp-a.task-1",
            "project_manager",
            "cached pm input",
            output="cached plan output",
            confirmed=True,
        )
        kanban.save()

        captured: dict[str, str] = {}
        events: list[str] = []

        def fake_build_swe_prompt(pm_output: str, *args) -> str:
            captured["pm_output"] = pm_output
            return "swe prompt"

        monkeypatch.setattr("pipeline.build_swe_prompt", fake_build_swe_prompt)

        run_pipeline(config, kanban)

        assert captured["pm_output"] == "cached plan output"
        assert kanban._get_task("phase-1.comp-a.task-1")[2]["status"] == "done"

    def test_software_engineer_success_check_uses_diff_and_task_prompt(
        self, project_tree, monkeypatch
    ):
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
        kanban.set_status("phase-1.comp-a.task-1", "software_engineer")
        kanban.set_resume_payload(
            "phase-1.comp-a.task-1",
            "project_manager",
            "cached pm input",
            output="cached plan output",
            confirmed=True,
        )
        kanban.save()

        captured: dict[str, str] = {}
        events: list[str] = []

        def fake_build_swe_prompt(pm_output: str, *args) -> str:
            captured["pm_output"] = pm_output
            return "swe prompt from pm output"

        def fake_mock_run_agent(prompt, project_dir, opencode_config_path, agent="default", **kwargs):
            events.append("agent")
            if agent == "exit-criteria-met":
                return pipeline.AgentRunResult(response="yes", session_id=None)
            return pipeline.AgentRunResult(response="swe output", session_id=None)

        def fake_get_diff(repo_path, base_branch):
            events.append("diff")
            assert "agent" in events
            captured["base_branch"] = base_branch
            return "+implemented change"

        def fake_mock_check_agent_success(
            project_dir,
            opencode_config_path,
            *,
            agent,
            agent_name,
            prior_result,
            evaluation_context=None,
            task_id="",
            step_num=0,
            step_title="",
            ssh_host=None,
        ):
            events.append("success")
            if agent == "software-engineer":
                captured["evaluation_context"] = evaluation_context or ""
            return pipeline.AgentRunResult(response="yes", session_id=None)

        monkeypatch.setattr("pipeline.build_swe_prompt", fake_build_swe_prompt)
        monkeypatch.setattr("pipeline.mock_run_agent", fake_mock_run_agent)
        monkeypatch.setattr("pipeline.get_diff", fake_get_diff)
        monkeypatch.setattr("pipeline.mock_check_agent_success", fake_mock_check_agent_success)

        run_pipeline(config, kanban)

        assert captured["pm_output"] == "cached plan output"
        assert captured["base_branch"] == "main"
        assert events[:3] == ["agent", "diff", "success"]
        assert "<Task Prompt>\nswe prompt from pm output</Task Prompt>" in captured["evaluation_context"]
        assert "<Git Diff vs main>+implemented change</Git Diff vs main>" in captured["evaluation_context"]
        assert kanban._get_task("phase-1.comp-a.task-1")[2]["status"] == "done"

    def test_resumes_code_review_eval_without_rerunning_earlier_stages(
        self, project_tree, monkeypatch
    ):
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
        kanban.set_status("phase-1.comp-a.task-1", "code_review_eval")
        kanban.set_resume_payload(
            "phase-1.comp-a.task-1",
            "project_manager",
            "cached pm input",
            output="cached plan output",
            confirmed=True,
        )
        kanban.set_resume_payload(
            "phase-1.comp-a.task-1",
            "code_review",
            "cached cr input",
            output="cached review output",
            confirmed=True,
        )
        kanban.save()

        agents_called: list[str] = []
        cr_eval_inputs: dict[str, str] = {}

        def fake_build_cr_eval_prompt(cr_output: str, *args) -> str:
            cr_eval_inputs["cr_output"] = cr_output
            return "cr eval prompt"

        def fake_mock_run_agent(prompt, project_dir, opencode_config_path, agent="default", **kwargs):
            agents_called.append(agent)
            if agent == "exit-criteria-met":
                return pipeline.AgentRunResult(response="yes", session_id=None)
            return pipeline.AgentRunResult(response="Dry-run: mock agent completed.", session_id=None)

        monkeypatch.setattr("pipeline.build_cr_eval_prompt", fake_build_cr_eval_prompt)
        monkeypatch.setattr("pipeline.mock_run_agent", fake_mock_run_agent)

        run_pipeline(config, kanban)

        assert cr_eval_inputs["cr_output"] == "cached review output"
        assert agents_called == ["cr-evaler", "exit-criteria-met"]
        assert kanban._get_task("phase-1.comp-a.task-1")[2]["status"] == "done"

    def test_exit_criteria_no_triggers_checklist_and_fulfillment(
        self, project_tree, monkeypatch
    ):
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
        kanban.set_status("phase-1.comp-a.task-1", "exit_criteria_met")
        kanban.set_resume_payload(
            "phase-1.comp-a.task-1",
            "project_manager",
            "cached pm input",
            output="cached plan output",
            confirmed=True,
        )
        kanban.set_resume_payload(
            "phase-1.comp-a.task-1",
            "code_review",
            "cached cr input",
            output="cached review output",
            confirmed=True,
        )
        kanban.save()

        calls: list[tuple[str, str | None]] = []
        exit_criteria_calls = {"count": 0}

        def fake_run_agent(prompt, project_dir, opencode_config_path, agent="default", **kwargs):
            calls.append((agent, kwargs.get("session_id")))
            if agent == "exit-criteria-met" and prompt.startswith("Provide a detailed checklist"):
                return pipeline.AgentRunResult(response="- add missing guard", session_id="sess-1")
            if agent == "exit-criteria-met":
                exit_criteria_calls["count"] += 1
                if exit_criteria_calls["count"] == 1:
                    return pipeline.AgentRunResult(response="no", session_id="sess-1")
                return pipeline.AgentRunResult(response="yes", session_id=kwargs.get("session_id"))
            return pipeline.AgentRunResult(response="yes", session_id=kwargs.get("session_id"))

        monkeypatch.setattr("pipeline.mock_run_agent", fake_run_agent)

        run_pipeline(config, kanban)

        assert calls[0] == ("exit-criteria-met", None)
        assert calls[1] == ("exit-criteria-met", "sess-1")
        assert calls[2][0] == "software-engineer"
        assert calls[3] == ("exit-criteria-met", None)
        assert kanban._get_task("phase-1.comp-a.task-1")[2]["status"] == "done"

    def test_failed_stage_keeps_input_and_reruns_from_start(self, project_tree, monkeypatch):
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
        kanban.set_resume_payload(
            "phase-1.comp-a.task-1",
            "project_manager",
            "cached pm input",
        )
        kanban.save()

        captured_prompts: list[str] = []
        success_calls = {"count": 0}

        def fake_build_pm_prompt(*args, **kwargs):
            return "fresh pm input"

        def fake_mock_run_agent(prompt, project_dir, opencode_config_path, agent="default", **kwargs):
            if agent == "project-manager":
                captured_prompts.append(prompt)
            if agent == "exit-criteria-met":
                return pipeline.AgentRunResult(response="yes", session_id=None)
            return pipeline.AgentRunResult(response="Draft plan", session_id=None)

        def fake_mock_check_agent_success(
            project_dir,
            opencode_config_path,
            *,
            agent,
            agent_name,
            prior_result,
            evaluation_context=None,
            task_id="",
            step_num=0,
            step_title="",
            ssh_host=None,
        ):
            success_calls["count"] += 1
            if agent == "project-manager" and success_calls["count"] == 1:
                return pipeline.AgentRunResult(response="no", session_id=None)
            return pipeline.AgentRunResult(response="yes", session_id=None)

        monkeypatch.setattr("pipeline.build_pm_prompt", fake_build_pm_prompt)
        monkeypatch.setattr("pipeline.mock_run_agent", fake_mock_run_agent)
        monkeypatch.setattr("pipeline.mock_check_agent_success", fake_mock_check_agent_success)

        with pytest.raises(PipelineError, match="did not confirm success"):
            run_pipeline(config, kanban)

        payload = kanban.get_resume_payload("phase-1.comp-a.task-1", "project_manager")
        assert payload is not None
        assert payload["input"] == "cached pm input"
        assert "output" not in payload
        assert payload["confirmed"] is False
        assert kanban._get_task("phase-1.comp-a.task-1")[2]["status"] == "project_manager"

        run_pipeline(config, kanban)

        assert captured_prompts[:2] == ["cached pm input", "cached pm input"]
        assert kanban._get_task("phase-1.comp-a.task-1")[2]["status"] == "done"
        assert "resume" not in kanban._get_task("phase-1.comp-a.task-1")[2]

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


class TestGitSetupFailures:
    def test_rebase_conflict_is_reported_as_pipeline_error(self, project_tree, monkeypatch):
        config = PipelineConfig(
            local_repo_path=project_tree,
            kanban_path=project_tree / "env" / "kanban.json",
            docs_path=project_tree / "docs",
            base_branch="main",
            remote_name="origin",
            loop_until_phase_complete=False,
            dry_run=False,
        )
        kanban = Kanban(config.kanban_path)
        kanban.load()

        def raise_rebase(*args, **kwargs):
            raise GitRebaseError("rebase failed")

        monkeypatch.setattr("pipeline.has_changes", lambda *args, **kwargs: False)
        monkeypatch.setattr("pipeline.fetch_or_pull_base", lambda *args, **kwargs: None)
        monkeypatch.setattr("pipeline.create_or_checkout_branch", lambda *args, **kwargs: None)
        monkeypatch.setattr("pipeline.rebase_base", raise_rebase)

        with pytest.raises(PipelineError, match="rebase failed"):
            run_pipeline(config, kanban)

        assert kanban._get_task("phase-1.comp-a.task-1")[2]["status"] == "project_manager"


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
