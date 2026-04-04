"""Unit tests for pipeline.git."""

import subprocess
from pathlib import Path

from lib.git import (
    branch_exists,
    commit_uncommitted_changes,
    get_diff,
    get_file_tree,
    stage_and_commit,
    has_changes,
)


def _make_remote_commit(remote_path: Path, filename: str, content: str, message: str) -> None:
    clone_path = remote_path.parent / "remote-worktree"
    subprocess.run(
        ["git", "clone", "--branch", "main", "--single-branch", str(remote_path), str(clone_path)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=clone_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=clone_path,
        check=True,
        capture_output=True,
    )
    (clone_path / filename).write_text(content)
    subprocess.run(
        ["git", "add", filename],
        cwd=clone_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=clone_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "push", "origin", "main"],
        cwd=clone_path,
        check=True,
        capture_output=True,
    )


class TestBranchExists:
    def test_existing_branch(self, git_repo):
        assert branch_exists(git_repo, "main") is True

    def test_nonexistent_branch(self, git_repo):
        assert branch_exists(git_repo, "no-such-branch") is False


class TestDiff:
    def test_empty_diff_on_clean_main(self, git_repo):
        diff = get_diff(git_repo, "main")
        assert diff == ""


class TestFileTree:
    def test_returns_entries(self, git_repo):
        tree = get_file_tree(git_repo, max_depth=2, max_entries=10)
        assert "README.md" in tree


class TestStageAndCommit:
    def test_commits_changes(self, git_repo):
        (git_repo / "new.txt").write_text("data")
        stage_and_commit(git_repo, "add new.txt")
        result = has_changes(git_repo)
        assert result is False


class TestCommitUncommittedChanges:
    def test_commits_dirty_repo_with_message(self, git_repo):
        (git_repo / "dirty.txt").write_text("wip")

        committed = commit_uncommitted_changes(git_repo, "kanban task title")

        assert committed is True
        assert has_changes(git_repo) is False

        result = subprocess.run(
            ["git", "log", "-1", "--pretty=%s"],
            cwd=git_repo,
            check=True,
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == "kanban task title"

    def test_noop_on_clean_repo(self, git_repo):
        committed = commit_uncommitted_changes(git_repo, "kanban task title")

        assert committed is False
        assert has_changes(git_repo) is False


class TestHasChanges:
    def test_clean_repo(self, git_repo):
        assert has_changes(git_repo) is False

    def test_dirty_repo(self, git_repo):
        (git_repo / "dirty.txt").write_text("wip")
        assert has_changes(git_repo) is True
