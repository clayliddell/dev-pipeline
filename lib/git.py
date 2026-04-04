"""Git operations helper for the pipeline."""

from pathlib import Path
import subprocess


def _run(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=check,
    )


def checkout_main_and_pull(repo: Path, remote: str = "origin") -> None:
    _run(["git", "checkout", "main"], repo)
    _run(["git", "pull", remote, "main"], repo)


def branch_exists(repo: Path, branch_name: str) -> bool:
    result = _run(["git", "branch", "--list", branch_name], repo, check=False)
    return bool(result.stdout.strip())


def current_branch(repo: Path) -> str:
    result = _run(["git", "branch", "--show-current"], repo)
    return result.stdout.strip()


def delete_branch(repo: Path, branch_name: str) -> None:
    if current_branch(repo) == branch_name:
        _run(["git", "checkout", "main"], repo)
    _run(["git", "branch", "-D", branch_name], repo)


def create_branch(repo: Path, branch_name: str) -> None:
    if branch_exists(repo, branch_name):
        delete_branch(repo, branch_name)
    _run(["git", "checkout", "-b", branch_name], repo)


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
