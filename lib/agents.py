"""Agent runner — wraps `opencode run` with real-time output streaming."""

import json
import re
from pathlib import Path
import subprocess
import sys
import tiktoken

# Define term color codes
AGENT = "\033[38;2;255;255;0m"
PROMPT = "\033[91m"
THINKING = "\033[95m"
INFO = "\033[38;2;255;255;0m"
RESPONSE = "\033[36m"
RESET = "\033[0m"  # Always reset after coloring


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
) -> str:
    """Run an opencode agent and stream output to terminal.

    Args:
        prompt: The prompt to send to the agent.
        project_dir: Working directory (the project repo root).
        agent: Name of the pre-configured opencode agent to use.

    Returns:
        Full captured output from the agent.
    """
    cmd = [
        f"OPENCODE_CONFIG={opencode_config_path}",
        "opencode",
        "run",
        prompt,
        "--agent",
        agent,
        "--thinking",
        "--format",
        "json",
    ]

    prompt_len = count_tokens(prompt)

    print(f"\n{'─' * 60}")
    print(f"{AGENT}[AGENT]\n{agent_name}\n[/AGENT]{RESET}")
    print(f"{'─' * 60}")
    print(f"{PROMPT}[PROMPT:{prompt_len}]\n{prompt}\n[/PROMPT:{prompt_len}]{RESET}")
    print(f"{'─' * 60}")

    proc = subprocess.Popen(
        cmd,
        cwd=str(project_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    response_parts: list[str] = []

    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue

        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
            continue

        etype = event.get("type", "")
        part = event.get("part", {})
        text = part.get("text", "")

        if etype == "reasoning" and text:
            print(f"{THINKING}[THINKING]\n{text}\n[\\THINKING]{RESET}\n", flush=True)
        elif etype == "text" and text:
            print(f"{RESPONSE}[RESPONSE]\n{text}\n[\\RESPONSE]{RESET}\n", flush=True)
            response_parts.append(text)
        elif text:
            print(f"{INFO}[INFO:{etype}]\n{text}\n[\\INFO:{etype}]{RESET}\n", flush=True)

    proc.wait()

    stderr = proc.stderr.read() if proc.stderr else ""
    if stderr:
        print(stderr, file=sys.stderr)

    if proc.returncode != 0:
        raise RuntimeError(
            f"Agent '{agent}' exited with code {proc.returncode}\nstderr: {stderr}"
        )

    full_output = "".join(response_parts)

    print(f"{'─' * 60}")
    print(f"  Agent {agent} complete")
    print(f"{'─' * 60}\n")

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
