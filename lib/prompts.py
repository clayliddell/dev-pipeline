"""Prompt builders for each agent in the pipeline."""


def build_pm_prompt(
    task: dict,
    code_standard: str,
    architecture: str,
    phase_file: str,
    fs_tree: str,
) -> str:
    task_id = task["id"]
    title = task["content"]
    description = task.get("description", "")
    exit_criteria = task.get("exitCriteria", [])

    criteria_text = "\n".join(f"- {c}" for c in exit_criteria)

    return f"""## Task
ID: {task_id}
Title: {title}
Description: {description}
Exit Criteria:
{criteria_text}

## Phase Context
{phase_file}

## Current Filesystem
{fs_tree}

## Project Architecture
{architecture}

## Code Standard
{code_standard}

---

Produce a detailed plan that includes:
1. A step-by-step implementation breakdown
2. The exact file paths that need to be created or modified
3. How each exit criterion will be satisfied
4. Any risks or dependencies to watch out for

Be specific. Reference real file paths from the filesystem and real rules from the architecture/code standard."""


def build_swe_prompt(pm_output: str) -> str:
    return f"""## Implementation Plan
{pm_output}

---

Implement the plan exactly as described. When finished, stage and commit all changes with a descriptive commit message. Output "DONE" when complete."""


def build_cr_prompt(
    git_diff: str,
    task: dict,
    architecture: str,
    code_standard: str,
    phase_file: str,
    fs_tree: str,
) -> str:
    task_id = task["id"]
    title = task["content"]
    description = task.get("description", "")
    exit_criteria = task.get("exitCriteria", [])

    criteria_text = "\n".join(f"- {c}" for c in exit_criteria)

    return f"""## Task
ID: {task_id}
Title: {title}
Description: {description}
Exit Criteria:
{criteria_text}

## Project Architecture
{architecture}

## Code Standard
{code_standard}

## Phase Context
{phase_file}

## Current Filesystem
{fs_tree}

## Git Diff
```diff
{git_diff}
```

---

For each issue found, provide:
1. The file and line number
2. What the issue is
3. A concrete fix or suggestion

Group your feedback by severity: critical, major, minor. If the code looks good, say so explicitly."""


def build_cr_eval_prompt(cr_feedback: str) -> str:
    return f"""You've been tasked with reviewing the following code review feedback for a third-party.
## Code Review Feedback
{cr_feedback}
---
Before applying any suggestions, ensure all tests are passing.

For each suggestion:
1. Evaluate whether it is accurate and correct
2. If accurate and good: apply the fix using your tools
3. If inaccurate or a matter of preference without clear benefit: skip it

After suggestions are applied, ensure all tests are passing.

When finished, output a summary of what you applied and what you skipped with brief reasoning. Output "DONE" when complete."""


def build_sanity_prompt(task: dict, git_diff: str) -> str:
    task_id = task["id"]
    title = task["content"]
    description = task.get("description", "")
    exit_criteria = task.get("exitCriteria", [])

    criteria_text = "\n".join(f"- {c}" for c in exit_criteria)

    return f"""You are a Sanity Check agent. Evaluate whether the git diff below fulfills the task's exit criteria without introducing major regressions.

## Task
ID: {task_id}
Title: {title}
Description: {description}
Exit Criteria:
{criteria_text}

## Git Diff
```diff
{git_diff}
```

---

Does the git diff fulfill the exit criteria and not introduce major regressions? Answer yes or no with brief reasoning and only answer yes if you are at least 75% confident."""
