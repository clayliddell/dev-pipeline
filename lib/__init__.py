"""Pipeline lib package."""

from .git import (
    checkout_main_and_pull,
    create_branch,
    current_branch,
    delete_branch,
    get_diff,
    get_file_tree,
    stage_and_commit,
    merge_branch,
    push,
    has_changes,
)
from .agents import run_agent, parse_agent_response
from .prompts import (
    build_pm_prompt,
    build_swe_prompt,
    build_cr_prompt,
    build_cr_eval_prompt,
    build_sanity_prompt,
)

__all__ = [
    "checkout_main_and_pull",
    "create_branch",
    "get_diff",
    "get_file_tree",
    "stage_and_commit",
    "merge_branch",
    "push",
    "has_changes",
    "run_agent",
    "parse_agent_response",
    "build_pm_prompt",
    "build_swe_prompt",
    "build_cr_prompt",
    "build_cr_eval_prompt",
    "build_sanity_prompt",
]
