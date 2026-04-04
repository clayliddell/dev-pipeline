"""Git operations helper for the pipeline."""

from pathlib import Path
import subprocess


class GitRebaseError(Exception):
    pass


def _run(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=check,
    )


def _current_head(repo: Path) -> str:
    result = _run(["git", "rev-parse", "HEAD"], repo)
    return result.stdout.strip()


def _stash_worktree(repo: Path) -> str:
    _run(["git", "stash", "push", "-u", "-m", "dev-pipeline auto-stash"], repo)
    return "stash@{0}"


def _restore_worktree(repo: Path, head: str) -> None:
    _run(["git", "reset", "--hard", head], repo)
    _run(["git", "clean", "-fd"], repo)


def _apply_stash(repo: Path, stash_ref: str) -> None:
    _run(["git", "stash", "apply", "--index", stash_ref], repo)


def fetch_or_pull_base(
    repo: Path,
    remote: str = "origin",
    base_branch: str = "main",
) -> None:
    if current_branch(repo) == base_branch:
        _run(["git", "pull", remote, base_branch], repo)
    else:
        _run(["git", "fetch", remote, f"{base_branch}:{base_branch}"], repo)


def rebase_base(
    repo: Path,
    base_branch: str = "main",
) -> None:
    has_uncommitted_changes = has_changes(repo)
    original_head = _current_head(repo)
    stash_ref: str | None = None

    if has_uncommitted_changes:
        stash_ref = _stash_worktree(repo)

    curr_branch = current_branch(repo)

    try:
        _run(["git", "rebase", base_branch], repo)
    except subprocess.CalledProcessError:
        _run(["git", "rebase", "--abort"], repo, check=False)
        if stash_ref:
            _apply_stash(repo, stash_ref)
            _run(["git", "stash", "drop", stash_ref], repo)
        raise GitRebaseError(
            f'Unable to rebase "{base_branch}" due to conflicts with committed changes on {curr_branch}.'
        ) from None

    if not stash_ref:
        return

    try:
        _apply_stash(repo, stash_ref)
    except subprocess.CalledProcessError:
        _restore_worktree(repo, original_head)
        _apply_stash(repo, stash_ref)
        _run(["git", "stash", "drop", stash_ref], repo)
        raise GitRebaseError(
            f'Unable to rebase changes from "{base_branch}" due to conflicts with uncommitted changes on {curr_branch}.'
        ) from None

    _run(["git", "stash", "drop", stash_ref], repo)


def branch_exists(repo: Path, branch_name: str) -> bool:
    result = _run(["git", "branch", "--list", branch_name], repo, check=False)
    return bool(result.stdout.strip())


def current_branch(repo: Path) -> str:
    result = _run(["git", "branch", "--show-current"], repo)
    return result.stdout.strip()


def create_or_checkout_branch(repo: Path, branch: str, source_branch: str) -> None:
    if branch_exists(repo, branch):
        _run(["git", "checkout", branch], repo)
    else:
        _run(["git", "checkout", "-b", branch, source_branch], repo)


def get_diff(repo: Path, base: str = "main") -> str:
    result = _run(["git", "diff", f"{base}...HEAD"], repo)
    return result.stdout


def get_file_tree(repo: Path, max_depth: int = 4, max_entries: int = 200) -> str:
    result = _run(
        ["find", ".", "-maxdepth", str(max_depth), "-not", "-path", "*/.git/*"],
        repo,
    )
    lines = result.stdout.strip().splitlines()[:max_entries]
    return "\n".join(lines)


def stage_and_commit(repo: Path, message: str) -> None:
    _run(["git", "add", "-A"], repo)
    _run(["git", "commit", "-m", message], repo)


def merge_branch(repo: Path, branch: str, target: str = "main") -> None:
    _run(["git", "checkout", target], repo)
    _run(["git", "merge", "--no-ff", "-m", f"Merge {branch}", branch], repo)


def push(repo: Path, remote: str = "origin", branch: str = "main") -> None:
    _run(["git", "push", remote, branch], repo)


def has_changes(repo: Path) -> bool:
    result = _run(["git", "status", "--porcelain"], repo)
    return bool(result.stdout.strip())


def commit_uncommitted_changes(repo: Path, message: str) -> bool:
    if not has_changes(repo):
        return False
    stage_and_commit(repo, message)
    return True
