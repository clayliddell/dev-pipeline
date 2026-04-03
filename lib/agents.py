"""Agent runner — wraps `opencode run` with block output."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import threading

import tiktoken

from lib.tui import TerminalBlock, print_block


SUCCESS_CHECK_PROMPT = (
    "If the task you were asked to perform was completed successfully,"
    " please respond 'yes'; otherwise, respond 'no'."
)

SUCCESS_SANITY_CHECK_PROMPT = (
    "Based only on your last response, did the git diff fulfill the exit"
    " criteria? 'yes' or 'no'"
)

@dataclass(slots=True)
class AgentRunResult:
    response: str
    session_id: str | None = None


def count_tokens(prompt: str) -> int:
    """Count prompt tokens."""
    enc = tiktoken.encoding_for_model("gpt-4o")
    return len(enc.encode(prompt))


def _build_opencode_command(
    prompt: str,
    *,
    agent: str,
    session_id: str | None = None,
    continue_last_session: bool = False,
) -> list[str]:
    cmd = [
        "opencode",
        "run",
        prompt,
        "--agent",
        agent,
        "--thinking",
        "--format",
        "json",
    ]
    if session_id:
        cmd.extend(["--session", session_id])
    elif continue_last_session:
        cmd.append("--continue")
    return cmd


def _run_opencode_command(
    cmd: list[str],
    prompt: str,
    project_dir: Path,
    opencode_config_path: Path,
    agent: str,
    agent_name: str,
    task_id: str,
    step_num: int,
    step_title: str,
) -> AgentRunResult:
    env = os.environ.copy()
    env["OPENCODE_CONFIG"] = str(opencode_config_path)

    proc = subprocess.Popen(
        cmd,
        cwd=str(project_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    response_parts: list[str] = []
    session_id: str | None = None
    prefix = f"{task_id} - Step {step_num}: {step_title}" if task_id else ""

    print_block(
        TerminalBlock(
            "AGENT",
            agent_name,
            subtitle=f"agent: {agent}",
            title_prefix=prefix,
        )
    )
    print_block(
        TerminalBlock(
            "PROMPT",
            prompt,
            subtitle=f"{count_tokens(prompt)} tokens",
            title_prefix=prefix,
        )
    )

    def read_output() -> None:
        nonlocal session_id
        assert proc.stdout is not None

        current_type = None
        buffered_parts: list[str] = []

        def flush_buffer() -> None:
            nonlocal current_type, buffered_parts
            if current_type and buffered_parts:
                full = "\n".join(buffered_parts)
                block_type = "THINKING" if current_type == "reasoning" else "RESPONSE"
                print_block(TerminalBlock(block_type, full, title_prefix=prefix))
            current_type = None
            buffered_parts = []

        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue

            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                print_block(
                    TerminalBlock(
                        "INFO",
                        line,
                        subtitle="raw output",
                        title_prefix=prefix,
                    )
                )
                continue

            session_id = event.get("sessionID") or session_id
            etype = event.get("type", "")
            part = event.get("part", {})
            text = part.get("text", "")

            if not text:
                continue

            if etype == "reasoning":
                if current_type != "reasoning":
                    flush_buffer()
                    current_type = "reasoning"
                buffered_parts.append(text)
                continue

            if etype == "text":
                if current_type != "text":
                    flush_buffer()
                    current_type = "text"
                buffered_parts.append(text)
                response_parts.append(text)
                continue

            flush_buffer()
            print_block(
                TerminalBlock("INFO", text, subtitle=etype, title_prefix=prefix)
            )

        flush_buffer()

    reader = threading.Thread(target=read_output)
    reader.start()
    reader.join()

    proc.wait()

    stderr = proc.stderr.read() if proc.stderr else ""
    if stderr:
        print_block(
            TerminalBlock("INFO", stderr, subtitle="stderr", title_prefix=prefix)
        )

    if proc.returncode != 0:
        raise RuntimeError(
            f"Agent '{agent}' exited with code {proc.returncode}\nstderr: {stderr}"
        )

    print_block(TerminalBlock("INFO", f"Agent {agent} complete", title_prefix=prefix))
    return AgentRunResult(
        response="\n".join(part for part in response_parts if part),
        session_id=session_id,
    )


def run_agent(
    prompt: str,
    project_dir: Path,
    opencode_config_path: Path,
    agent: str = "default",
    agent_name: str = "Default Agent",
    task_id: str = "",
    step_num: int = 0,
    step_title: str = "",
) -> AgentRunResult:
    """Run an opencode agent and print block output."""
    cmd = _build_opencode_command(prompt, agent=agent)
    return _run_opencode_command(
        cmd,
        prompt,
        project_dir,
        opencode_config_path,
        agent,
        agent_name,
        task_id,
        step_num,
        step_title,
    )


def success_response_found(output: str) -> bool:
    """Return True when the response contains a case-insensitive yes."""
    return re.search(r"\byes\b", output, re.IGNORECASE) is not None


def check_agent_success(
    project_dir: Path,
    opencode_config_path: Path,
    *,
    agent: str,
    agent_name: str,
    prior_result: AgentRunResult,
    task_id: str = "",
    step_num: int = 0,
    step_title: str = "",
) -> AgentRunResult:
    """Ask the same session whether its just-completed task was successful."""
    cmd = _build_opencode_command(
        SUCCESS_SANITY_CHECK_PROMPT if agent_name == "sanity-checker" else SUCCESS_CHECK_PROMPT,
        agent=agent,
        session_id=prior_result.session_id,
        continue_last_session=prior_result.session_id is None,
    )
    return _run_opencode_command(
        cmd,
        SUCCESS_CHECK_PROMPT,
        project_dir,
        opencode_config_path,
        agent,
        f"{agent_name} Success Check",
        task_id,
        step_num,
        step_title,
    )
