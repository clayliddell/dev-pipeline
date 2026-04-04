"""Unit tests for pipeline prompts and agent success helpers."""

from pathlib import Path

import pytest

from lib.agents import (
    AgentRunResult,
    _build_ssh_remote_command,
    _build_opencode_command,
    _normalize_opencode_fragment,
    _remote_opencode_config_path,
    success_response_found,
)
from lib.prompts import (
    build_cr_eval_prompt,
    build_cr_prompt,
    build_pm_prompt,
    build_sanity_prompt,
    build_swe_prompt,
)
from pipeline import PipelineError, ensure_agent_succeeded


SAMPLE_TASK = {
    "id": "phase-1.comp-a.task-1",
    "content": "Implement foo",
    "description": "Implement the foo module",
    "exitCriteria": ["foo works", "bar tested"],
}


class TestBuildPmPrompt:
    def test_contains_task_id(self):
        p = build_pm_prompt(SAMPLE_TASK, "std", "arch", "phase", "tree")
        assert "phase-1.comp-a.task-1" in p

    def test_contains_exit_criteria(self):
        p = build_pm_prompt(SAMPLE_TASK, "std", "arch", "phase", "tree")
        assert "foo works" in p
        assert "bar tested" in p

    def test_contains_all_inputs(self):
        p = build_pm_prompt(
            SAMPLE_TASK, "CODE_STD", "ARCH_DOC", "PHASE_DOC", "FILE_TREE"
        )
        assert "CODE_STD" in p
        assert "ARCH_DOC" in p
        assert "PHASE_DOC" in p
        assert "FILE_TREE" in p


class TestBuildSwePrompt:
    def test_contains_plan(self):
        p = build_swe_prompt("do X then Y")
        assert "do X then Y" in p
        assert "DONE" in p


class TestBuildCrPrompt:
    def test_contains_diff(self):
        p = build_cr_prompt(
            "diff --git a/b", SAMPLE_TASK, "arch", "std", "phase", "tree"
        )
        assert "diff --git a/b" in p

    def test_contains_task_fields(self):
        p = build_cr_prompt("diff", SAMPLE_TASK, "arch", "std", "phase", "tree")
        assert "Implement foo" in p
        assert "foo works" in p


class TestBuildCrEvalPrompt:
    def test_contains_feedback(self):
        p = build_cr_eval_prompt("Fix line 42: missing error check")
        assert "Fix line 42" in p
        assert "DONE" in p


class TestBuildSanityPrompt:
    def test_requests_yes_or_no(self):
        p = build_sanity_prompt(SAMPLE_TASK, "some diff")
        assert "Answer yes or no" in p

    def test_contains_exit_criteria(self):
        p = build_sanity_prompt(SAMPLE_TASK, "some diff")
        assert "foo works" in p


class TestPromptsDoNotRequireJson:
    def test_pm_prompt_has_no_json_contract(self):
        p = build_pm_prompt(SAMPLE_TASK, "std", "arch", "phase", "tree")
        assert '"task_success"' not in p

    def test_swe_prompt_has_no_json_contract(self):
        p = build_swe_prompt("plan")
        assert '"task_success"' not in p

    def test_cr_prompt_has_no_json_contract(self):
        p = build_cr_prompt("diff", SAMPLE_TASK, "arch", "std", "phase", "tree")
        assert '"task_success"' not in p

    def test_cr_eval_prompt_has_no_json_contract(self):
        p = build_cr_eval_prompt("feedback")
        assert '"task_success"' not in p


class TestSuccessResponseFound:
    def test_matches_yes_case_insensitively(self):
        assert success_response_found("Yes") is True

    def test_requires_whole_word(self):
        assert success_response_found("yesterday") is False

    def test_matches_yes_with_extra_text(self):
        assert success_response_found("yes, the task succeeded") is True


class TestBuildOpencodeCommand:
    def test_preserves_prompt_text_without_shell_quoting(self):
        prompt = "hello 'quoted' world"
        cmd = _build_opencode_command(prompt, agent="project-manager")

        assert cmd[2] == prompt

    def test_uses_session_id_when_present(self):
        cmd = _build_opencode_command(
            "hello", agent="project-manager", session_id="ses-1"
        )

        assert "--session" in cmd
        assert "ses-1" in cmd
        assert "--continue" not in cmd

    def test_falls_back_to_continue_without_session_id(self):
        cmd = _build_opencode_command(
            "hello",
            agent="project-manager",
            continue_last_session=True,
        )

        assert "--continue" in cmd


class TestRemoteOpencodeConfigPath:
    def test_maps_config_file_into_remote_project_dir(self):
        remote_path = _remote_opencode_config_path(
            Path("/remote/repo"), Path("/local/repo/agents.opencode.jsonc")
        )

        assert remote_path == "/remote/repo/agents.opencode.jsonc"


class TestNormalizeOpencodeFragment:
    def test_strips_ansi_and_carriage_returns(self):
        fragment = '\x1b[31m{"type":"text","part":{"text":"hi"}}\r\n'

        assert _normalize_opencode_fragment(fragment) == '{"type":"text","part":{"text":"hi"}}\n'


class TestBuildSshRemoteCommand:
    def test_quotes_project_dir_and_wraps_opencode_with_script(self):
        ssh_cmd = _build_ssh_remote_command(
            ["/home/agent/.opencode/bin/opencode", "run", "prompt text", "--format", "json"],
            Path("/remote/repo with spaces"),
            Path("/tmp/local/agents.opencode.jsonc"),
        )

        assert ssh_cmd.startswith("cd '/remote/repo with spaces' && if command -v script >/dev/null 2>&1; then ")
        assert "script -qefc" in ssh_cmd
        assert "TERM=dumb" in ssh_cmd
        assert "COLUMNS=512" in ssh_cmd
        assert "LINES=200" in ssh_cmd
        assert "OPENCODE_CONFIG=" in ssh_cmd
        assert "agents.opencode.jsonc" in ssh_cmd
        assert "/home/agent/.opencode/bin/opencode run 'prompt text' --format json" in ssh_cmd


class TestEnsureAgentSucceeded:
    def test_returns_original_response_when_followup_says_yes(self, tmp_path: Path):
        def fake_success_check(*args, **kwargs):
            return AgentRunResult(response="YES", session_id="abc")

        result = ensure_agent_succeeded(
            tmp_path,
            tmp_path / "agents.opencode.jsonc",
            agent="project-manager",
            agent_name="Project Manager",
            result=AgentRunResult(response="plan output", session_id="abc"),
            task_id="task-1",
            step_num=3,
            step_title="Project Manager",
            success_check_fn=fake_success_check,
        )

        assert result == "plan output"

    def test_raises_when_followup_does_not_say_yes(self, tmp_path: Path):
        def fake_success_check(*args, **kwargs):
            return AgentRunResult(response="no", session_id="abc")

        with pytest.raises(PipelineError, match="did not confirm success"):
            ensure_agent_succeeded(
                tmp_path,
                tmp_path / "agents.opencode.jsonc",
                agent="project-manager",
                agent_name="Project Manager",
                result=AgentRunResult(response="plan output", session_id="abc"),
                task_id="task-1",
                step_num=3,
                step_title="Project Manager",
                success_check_fn=fake_success_check,
            )
