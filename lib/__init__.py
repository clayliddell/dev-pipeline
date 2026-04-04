"""Pipeline lib package."""

from .git import (
    rebase_base,
    create_or_checkout_branch,
    current_branch,
    commit_uncommitted_changes,
    get_diff,
    get_file_tree,
    stage_and_commit,
    merge_branch,
    fetch_or_pull_base,
    push,
    has_changes,
)
from .agents import (
    AgentRunResult,
    check_agent_success,
    run_agent,
    success_response_found,
)
from .prompts import (
    build_pm_prompt,
    build_swe_prompt,
    build_cr_prompt,
    build_cr_eval_prompt,
    build_sanity_prompt,
)

__all__ = [
    "create_or_checkout_branch",
    "get_diff",
    "get_file_tree",
    "stage_and_commit",
    "commit_uncommitted_changes",
    "merge_branch",
    "push",
    "has_changes",
    "AgentRunResult",
    "run_agent",
    "check_agent_success",
    "success_response_found",
    "build_pm_prompt",
    "build_swe_prompt",
    "build_cr_prompt",
    "build_cr_eval_prompt",
    "build_sanity_prompt",
]
