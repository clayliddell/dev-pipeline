"""Agent runner — wraps `opencode run` with block output."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import threading

import tiktoken

from lib.jsonlog import log_json
from lib.tui import TerminalBlock, print_block


SUCCESS_CHECK_PROMPT = {
    "default": (
        "Was the agent able to perform the requested task successfully?"
        " Respond 'yes' or 'no'"
    ),
    "project-manager": (
        "Was the agent able to create an implementation plan?"
        " Respond 'yes' or 'no'"
    ),
    "software-engineer": (
        "Was the agent able to implement the requested changes?"
        " Respond 'yes' or 'no'"
    ),
    "code-reviewer": (
        "Did the agent review the code?"
        " Respond 'yes' or 'no'"
    ),
    "cr-evaler": (
        "Did the agent evaluate the code review?"
        " Respond 'yes' or 'no'"
    ),
    "sanity-checker": (
        "Did the agent confirm the git diff fulfilled the exit criteria?"
        " Respond 'yes' or 'no'"
    ),
}

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

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
) -> list[str]:
    opencode_command = "/home/agent/.opencode/bin/opencode"
    cmd = [
        opencode_command,
        "run",
        prompt,
        "--agent",
        agent,
        "--thinking",
        "--format",
        "json",
    ]
    return cmd

def _normalize_opencode_fragment(fragment: str) -> str:
    """Strip PTY control sequences so wrapped JSON can be reassembled."""
    return ANSI_ESCAPE_RE.sub("", fragment).replace("\r", "")


def _build_ssh_remote_command(
    cmd: list[str], project_dir: Path, opencode_config_path: Path
) -> str:
    """Build a shell command for remote execution over SSH."""
    opencode_cmd = shlex.join(
        [
            "env",
            "TERM=dumb",
            "COLUMNS=512",
            "LINES=200",
            f"OPENCODE_CONFIG={opencode_config_path}",
            "stdbuf",
            "-oL",
            "-eL",
            *cmd,
        ]
    )
    return f"cd {shlex.quote(str(project_dir))} && {opencode_cmd}"


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
    ssh_host: str | None,
) -> AgentRunResult:

    log_json(
        "opencode.command.start",
        agent=agent,
        agent_name=agent_name,
        task_id=task_id,
        step_num=step_num,
        step_title=step_title,
        command=cmd,
        project_dir=project_dir,
        opencode_config_path=opencode_config_path,
    )

    if ssh_host:
        ssh_cmd = _build_ssh_remote_command(cmd, project_dir, opencode_config_path)
        final_cmd = f"bash -c {shlex.quote(ssh_cmd)}"
        proc = subprocess.Popen([
            "ssh",
            "-T", "-n",
            "-o", "ForwardAgent=no",
            "-o", "ForwardX11=no",
            "-o", "ForwardX11Trusted=no",
            "-o", "AddKeysToAgent=no",
            "-o", "PermitLocalCommand=no",
            "-o", "StrictHostKeyChecking=yes",
            "-o", "ConnectTimeout=10",
            ssh_host, final_cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    else:
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
        pending_json = ""

        def flush_buffer() -> None:
            nonlocal current_type, buffered_parts
            if current_type and buffered_parts:
                full = "\n".join(buffered_parts)
                block_type = "THINKING" if current_type == "reasoning" else "RESPONSE"
                print_block(TerminalBlock(block_type, full, title_prefix=prefix))
            current_type = None
            buffered_parts = []

        def emit_raw_output(line: str) -> None:
            log_json(
                "opencode.raw_output",
                agent=agent,
                agent_name=agent_name,
                task_id=task_id,
                step_num=step_num,
                step_title=step_title,
                line=line,
            )
            print_block(
                TerminalBlock(
                    "INFO",
                    line,
                    subtitle="raw output",
                    title_prefix=prefix,
                )
            )

        for fragment in proc.stdout:
            fragment = _normalize_opencode_fragment(fragment)
            if not fragment.strip():
                continue

            pending_json += fragment.strip("\n")

            try:
                event = json.loads(pending_json)
            except json.JSONDecodeError:
                if pending_json.lstrip().startswith("{"):
                    continue
                emit_raw_output(pending_json.strip())
                pending_json = ""
                continue

            pending_json = ""

            session_id = event.get("sessionID") or session_id
            etype = event.get("type", "")
            part = event.get("part", {})
            text = part.get("text", "")

            log_json(
                "opencode.event",
                agent=agent,
                agent_name=agent_name,
                task_id=task_id,
                step_num=step_num,
                step_title=step_title,
                session_id=session_id,
                event_type=etype,
                raw_event=event,
            )

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

        if pending_json.strip():
            emit_raw_output(pending_json.strip())

        flush_buffer()

    reader = threading.Thread(target=read_output)
    reader.start()
    reader.join()

    proc.wait()

    stderr = proc.stderr.read() if proc.stderr else ""
    if stderr:
        log_json(
            "opencode.stderr",
            agent=agent,
            agent_name=agent_name,
            task_id=task_id,
            step_num=step_num,
            step_title=step_title,
            session_id=session_id,
            stderr=stderr,
        )
        print_block(
            TerminalBlock("INFO", stderr, subtitle="stderr", title_prefix=prefix)
        )

    if proc.returncode != 0:
        log_json(
            "opencode.exit_error",
            agent=agent,
            agent_name=agent_name,
            task_id=task_id,
            step_num=step_num,
            step_title=step_title,
            session_id=session_id,
            returncode=proc.returncode,
            stderr=stderr,
        )
        raise RuntimeError(
            f"Agent '{agent}' exited with code {proc.returncode}\nstderr: {stderr}"
        )

    log_json(
        "opencode.command.complete",
        agent=agent,
        agent_name=agent_name,
        task_id=task_id,
        step_num=step_num,
        step_title=step_title,
        session_id=session_id,
        response_length=len("\n".join(part for part in response_parts if part)),
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
    ssh_host: str | None = None,
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
        ssh_host,
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
    ssh_host: str | None = None,
) -> AgentRunResult:
    """Ask the same session whether its just-completed task was successful."""
    # build prompt
    prompt = SUCCESS_CHECK_PROMPT.get(
        agent, SUCCESS_CHECK_PROMPT["default"])
    prompt += f"\n\nAgent Response:\n{prior_result.response}"
    # call agent
    cmd = _build_opencode_command(prompt, agent="success-checker")
    return _run_opencode_command(
        cmd,
        prompt,
        project_dir,
        opencode_config_path,
        "success-checker",
        f"{agent_name} Success Check",
        task_id,
        step_num,
        step_title,
        ssh_host,
    )
