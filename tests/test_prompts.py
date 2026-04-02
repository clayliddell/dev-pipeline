"""Unit tests for pipeline.prompts."""

import pytest

from lib.prompts import (
    build_pm_prompt,
    build_swe_prompt,
    build_cr_prompt,
    build_cr_eval_prompt,
    build_sanity_prompt,
)
from lib.agents import parse_agent_response


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
    def test_contains_json_format_instruction(self):
        p = build_sanity_prompt(SAMPLE_TASK, "some diff")
        assert '"task_success"' in p
        assert '"message"' in p

    def test_contains_exit_criteria(self):
        p = build_sanity_prompt(SAMPLE_TASK, "some diff")
        assert "foo works" in p


class TestAllPromptsContainJsonFormat:
    def test_pm_prompt_has_json_format(self):
        p = build_pm_prompt(SAMPLE_TASK, "std", "arch", "phase", "tree")
        assert '"task_success"' in p

    def test_swe_prompt_has_json_format(self):
        p = build_swe_prompt("plan")
        assert '"task_success"' in p

    def test_cr_prompt_has_json_format(self):
        p = build_cr_prompt("diff", SAMPLE_TASK, "arch", "std", "phase", "tree")
        assert '"task_success"' in p

    def test_cr_eval_prompt_has_json_format(self):
        p = build_cr_eval_prompt("feedback")
        assert '"task_success"' in p


class TestParseAgentResponse:
    def test_valid_success(self):
        out = parse_agent_response('{"task_success": true, "message": "All good"}')
        assert out["task_success"] is True
        assert out["message"] == "All good"

    def test_valid_failure(self):
        out = parse_agent_response('{"task_success": false, "message": "Broke"}')
        assert out["task_success"] is False
        assert out["message"] == "Broke"

    def test_json_embedded_in_text(self):
        text = 'Some reasoning here.\n\n{"task_success": true, "message": "Done"}'
        out = parse_agent_response(text)
        assert out["task_success"] is True

    def test_missing_json_raises(self):
        with pytest.raises(ValueError, match="valid"):
            parse_agent_response("no json here")
