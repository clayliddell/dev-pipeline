"""Agent runner — wraps `opencode run` with block output."""

import json
import os
import re
import threading
from pathlib import Path
import subprocess
import tiktoken

from lib.tui import TerminalBlock, print_block


def count_tokens(prompt):
    """Count prompt tokens"""
    enc = tiktoken.encoding_for_model("gpt-4o")
    return len(enc.encode(prompt))


def run_agent(
    prompt: str,
    project_dir: Path,
    opencode_config_path: Path,
    agent: str = "default",
    agent_name: str = "Default Agent",
    task_id: str = "",
    step_num: int = 0,
    step_title: str = "",
) -> str:
    """Run an opencode agent and print block output.

    Args:
        prompt: The prompt to send to the agent.
        project_dir: Working directory (the project repo root).
        opencode_config_path: Path to opencode config file.
        agent: Name of the pre-configured opencode agent to use.
        agent_name: Display name for the agent.
        task_id: Task identifier for block title prefix.
        step_num: Step number for block title prefix.
        step_title: Step title for block title prefix.

    Returns:
        Full captured response text from the agent.

    Raises:
        RuntimeError: If the agent process fails or returns invalid output.
    """
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

    last_text_content: str = ""
    prefix = f"{task_id} - Step {step_num}: {step_title}" if task_id else ""

    prompt_len = count_tokens(prompt)
    print_block(
        TerminalBlock(
            "AGENT", agent_name, subtitle=f"agent: {agent}", title_prefix=prefix
        )
    )
    print_block(
        TerminalBlock(
            "PROMPT", prompt, subtitle=f"{prompt_len} tokens", title_prefix=prefix
        )
    )

    def read_output():
        nonlocal last_text_content
        assert proc.stdout is not None

        current_type = None
        buffered_parts: list[str] = []

        def flush_buffer():
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
                        "INFO", line, subtitle="raw output", title_prefix=prefix
                    )
                )
                continue

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
            elif etype == "text":
                if current_type != "text":
                    flush_buffer()
                    current_type = "text"
                buffered_parts.append(text)
                last_text_content = text
            else:
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

    full_output = last_text_content
    print_block(TerminalBlock("INFO", f"Agent {agent} complete", title_prefix=prefix))

    return full_output


def parse_agent_response(output: str) -> dict:
    """Extract the JSON response object from agent output.

    Looks for a JSON object matching {"task_success": ..., "message": "..."}
    anywhere in the output text.

    Returns:
        dict with keys "task_success" (bool) and "message" (str).

    Raises:
        ValueError: if no valid JSON response object is found.
    """
    pattern = (
        r'\{\s*"task_success"\s*:\s*(true|false)\s*,\s*"message"\s*:\s*"(.*?)"\s*\}'
    )
    match = re.search(pattern, output, re.DOTALL)
    if not match:
        raise ValueError(
            "Agent did not return a valid {task_success, message} JSON response.\n"
            f"Output was:\n{output[:500]}"
        )
    task_success = match.group(1) == "true"
    message = match.group(2)
    return {"task_success": task_success, "message": message}
