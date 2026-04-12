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

Be specific. Reference real file paths from the filesystem and real rules from the architecture/code standard.

IMPORTANT: It is very important that -
1/ You DO NOT use tool calls to evaluate the project.
2/ You DO NOT try to implement the plan that you create. You are creating this plan for a Software Engineer coding agent to implement.

Please respond with a detailed implementation plan."""


def build_swe_prompt(
    pm_output: str,
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

## Implementation Plan
{pm_output}

---

Implement the plan exactly as described.

Before you finish, make sure that:
1. The task exit criteria are 100% satisfied.
2. The code changes satisfy the project's ARCHITECTURE and CODE-STANDARD requirements.
3. The project's pre-commit hook passes.
4. All changes are staged and committed with a descriptive commit message.

Output "DONE" when complete."""


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


def build_cr_eval_prompt(
    cr_feedback: str,
    task: dict,
    architecture: str,
    code_standard: str,
    phase_file: str,
    fs_tree: str,
    git_diff: str,
) -> str:
    task_id = task["id"]
    title = task["content"]
    description = task.get("description", "")
    exit_criteria = task.get("exitCriteria", [])

    criteria_text = "\n".join(f"- {c}" for c in exit_criteria)

    return f"""You've been tasked with reviewing the following code review feedback and implementing only the useful suggestions.

## Task
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

## Code Review Feedback
{cr_feedback}
---
Before applying any suggestions, make sure the task exit criteria are 100% met and the code changes satisfy the project's ARCHITECTURE and CODE-STANDARD requirements.
Before applying any suggestions, ensure all tests are passing.

For each suggestion:
1. Evaluate whether it is accurate and correct
2. If accurate and good: apply the fix using your tools
3. If inaccurate or a matter of preference without clear benefit: skip it

After suggestions are applied, ensure all tests are passing, the pre-commit hook passes, and all changes are committed.

When finished, output a summary of what you applied and what you skipped with brief reasoning. Output "DONE" when complete."""


def build_exit_criteria_met_prompt(task: dict, git_diff: str) -> str:
    task_id = task["id"]
    title = task["content"]
    description = task.get("description", "")
    exit_criteria = task.get("exitCriteria", [])

    criteria_text = "\n".join(f"- {c}" for c in exit_criteria)

    return f"""You are the Exit Criteria Met Check agent. Evaluate whether the git diff below fulfills the task's exit criteria without introducing major regressions.

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


def build_exit_criteria_met_followup_prompt() -> str:
    return (
        "Provide a detailed checklist that will need to be completed in order to "
        "resolve this task. Keep in mind, this checklist should be detailed enough "
        "for a coding agent to understand what changes need to be implemented."
    )


def build_fulfill_exit_criteria_prompt(
    task: dict,
    architecture: str,
    code_standard: str,
    phase_file: str,
    fs_tree: str,
    git_diff: str,
    exit_criteria_feedback: str,
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

## Exit Criteria Feedback
{exit_criteria_feedback}

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

You are the Fulfill Exit Criteria agent. Implement the checklist above so the task exit criteria are 100% met. Ensure the code changes satisfy the project's ARCHITECTURE and CODE-STANDARD requirements, the pre-commit hook passes, and all changes are committed when you are done. Output "DONE" when complete."""
