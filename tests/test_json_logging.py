"""Tests for structured JSON logging."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

from kanban import Kanban
from lib.agents import AgentRunResult, _run_opencode_command
from lib.jsonlog import close_json_log, setup_json_log
from pipeline import PipelineConfig, parse_args, run_pipeline


class FakeProcess:
    def __init__(self, stdout_lines: list[str], stderr: str = "", returncode: int = 0):
        self.stdout = iter(stdout_lines)
        self.stderr = io.StringIO(stderr)
        self.returncode = returncode

    def wait(self) -> int:
        return self.returncode


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def test_parse_args_accepts_json_log_path():
    args = parse_args([
        "--local-repo-path",
        "/tmp/project",
        "--logging-json",
        "events.jsonl",
    ])
    assert args.logging_json == "events.jsonl"


def test_pipeline_writes_json_events(project_tree, tmp_path):
    log_path = tmp_path / "pipeline.jsonl"
    setup_json_log(log_path)
    try:
        config = PipelineConfig(
            local_repo_path=project_tree,
            kanban_path=project_tree / "env" / "kanban.json",
            docs_path=project_tree / "docs",
            base_branch="main",
            remote_name="origin",
            loop_until_phase_complete=False,
            dry_run=True,
            json_log_path=log_path,
        )
        kanban = Kanban(config.kanban_path)
        kanban.load()

        run_pipeline(config, kanban)
    finally:
        close_json_log()

    events = _read_jsonl(log_path)
    names = [event["event"] for event in events]

    assert "pipeline.start" in names
    assert "pipeline.task.picked_up" in names
    assert "pipeline.step.start" in names
    assert "pipeline.step.complete" in names
    assert "pipeline.status.updated" in names
    assert "pipeline.exit.single_task" in names


def test_opencode_json_events_are_logged(project_tree, tmp_path, monkeypatch):
    log_path = tmp_path / "opencode.jsonl"
    setup_json_log(log_path)
    monkeypatch.setattr("lib.agents.print_block", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "lib.agents.subprocess.Popen",
        lambda *args, **kwargs: FakeProcess(
            [
                json.dumps(
                    {
                        "sessionID": "session-1",
                        "type": "reasoning",
                        "part": {"text": "thinking"},
                    }
                )
                + "\n",
                "raw line\n",
                json.dumps(
                    {
                        "sessionID": "session-1",
                        "type": "text",
                        "part": {"text": "done"},
                    }
                )
                + "\n",
            ],
            stderr="stderr text",
            returncode=0,
        ),
    )
    try:
        result = _run_opencode_command(
            ["opencode", "run", "prompt"],
            "prompt",
            project_tree,
            project_tree / "agents.opencode.jsonc",
            agent="project-manager",
            agent_name="Project Manager",
            task_id="task-1",
            step_num=3,
            step_title="Project Manager",
            ssh_host=None,
        )
    finally:
        close_json_log()

    assert isinstance(result, AgentRunResult)
    assert result.response == "done"
    assert result.session_id == "session-1"

    events = _read_jsonl(log_path)
    names = [event["event"] for event in events]

    assert "opencode.command.start" in names
    assert "opencode.event" in names
    assert "opencode.raw_output" in names
    assert "opencode.stderr" in names
    assert "opencode.command.complete" in names

    parsed = next(event for event in events if event["event"] == "opencode.event")
    assert parsed["event_type"] == "reasoning"
    assert parsed["raw_event"]["part"]["text"] == "thinking"


def test_opencode_ssh_uses_script_wrapped_non_pty_invocation(project_tree, monkeypatch):
    captured: dict[str, Any] = {}

    def fake_popen(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeProcess([], stderr="", returncode=0)

    monkeypatch.setattr("lib.agents.print_block", lambda *args, **kwargs: None)
    monkeypatch.setattr("lib.agents.subprocess.Popen", fake_popen)

    _run_opencode_command(
        ["/home/agent/.opencode/bin/opencode", "run", "prompt text", "--format", "json"],
        "prompt text",
        Path("/remote/repo with spaces"),
        Path("/tmp/local/agents.opencode.jsonc"),
        agent="project-manager",
        agent_name="Project Manager",
        task_id="task-1",
        step_num=3,
        step_title="Project Manager",
        ssh_host="agentvm",
    )

    ssh_argv = captured["args"][0]
    assert ssh_argv[:5] == ["ssh", "-T", "-n", "agentvm", "bash"]
    assert ssh_argv[5] == "-lc"
    assert "cd '/remote/repo with spaces' &&" in ssh_argv[6]
    assert "if command -v script >/dev/null 2>&1; then" in ssh_argv[6]
    assert "script -qefc" in ssh_argv[6]
    assert "TERM=dumb" in ssh_argv[6]
    assert "COLUMNS=512" in ssh_argv[6]
    assert "LINES=200" in ssh_argv[6]
    assert "OPENCODE_CONFIG=" in ssh_argv[6]
    assert "agents.opencode.jsonc" in ssh_argv[6]
    assert "stdbuf -oL -eL" in ssh_argv[6]
    assert "/home/agent/.opencode/bin/opencode run 'prompt text' --format json" in ssh_argv[6]

    assert captured["kwargs"]["stdout"] is not None
    assert captured["kwargs"]["stderr"] is not None
    assert captured["kwargs"]["text"] is True


def test_opencode_pty_wrapped_json_is_reassembled(project_tree, tmp_path, monkeypatch):
    log_path = tmp_path / "opencode-pty.jsonl"
    setup_json_log(log_path)
    monkeypatch.setattr("lib.agents.print_block", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "lib.agents.subprocess.Popen",
        lambda *args, **kwargs: FakeProcess(
            [
                '\x1b[35m{"sessionID":"session-1",' + "\n",
                '"type":"text","part":{"text":"done"}}\r\n',
            ],
            stderr="",
            returncode=0,
        ),
    )

    try:
        result = _run_opencode_command(
            ["opencode", "run", "prompt"],
            "prompt",
            project_tree,
            project_tree / "agents.opencode.jsonc",
            agent="project-manager",
            agent_name="Project Manager",
            task_id="task-1",
            step_num=3,
            step_title="Project Manager",
            ssh_host=None,
        )
    finally:
        close_json_log()

    assert result.response == "done"
    assert result.session_id == "session-1"
