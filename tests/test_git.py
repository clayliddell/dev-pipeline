"""Unit tests for pipeline.git."""

from pathlib import Path

import pytest

from lib.git import (
    checkout_main_and_pull,
    branch_exists,
    delete_branch,
    create_branch,
    get_diff,
    get_file_tree,
    stage_and_commit,
    has_changes,
    merge_branch,
)


class TestBranchExists:
    def test_existing_branch(self, git_repo):
        assert branch_exists(git_repo, "main") is True

    def test_nonexistent_branch(self, git_repo):
        assert branch_exists(git_repo, "no-such-branch") is False


class TestCreateBranch:
    def test_creates_new_branch(self, git_repo):
        create_branch(git_repo, "feature/test")
        assert branch_exists(git_repo, "feature/test") is True

    def test_deletes_existing_branch(self, git_repo):
        create_branch(git_repo, "feature/test")
        checkout_main_and_pull(git_repo, remote="origin")
        create_branch(git_repo, "feature/test")
        assert branch_exists(git_repo, "feature/test") is True

    def test_branch_with_dots_in_name(self, git_repo):
        create_branch(git_repo, "feature/phase-1.comp-a.task-1")
        assert branch_exists(git_repo, "feature/phase-1.comp-a.task-1") is True


class TestDeleteBranch:
    def test_delete(self, git_repo):
        create_branch(git_repo, "temp-branch")
        delete_branch(git_repo, "temp-branch")
        assert branch_exists(git_repo, "temp-branch") is False


class TestDiff:
    def test_empty_diff_on_clean_main(self, git_repo):
        diff = get_diff(git_repo, "main")
        assert diff == ""

    def test_diff_after_change(self, git_repo):
        create_branch(git_repo, "feature/change")
        (git_repo / "newfile.txt").write_text("hello")
        stage_and_commit(git_repo, "add file")
        # Check diff while still on feature branch
        diff = get_diff(git_repo, "main")
        assert "newfile.txt" in diff


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


class TestHasChanges:
    def test_clean_repo(self, git_repo):
        assert has_changes(git_repo) is False

    def test_dirty_repo(self, git_repo):
        (git_repo / "dirty.txt").write_text("wip")
        assert has_changes(git_repo) is True
