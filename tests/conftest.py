"""Shared test fixtures."""

import json
import subprocess
from pathlib import Path

import pytest


def _init_git_repo(repo: Path, with_remote: bool = False) -> Path | None:
    """Initialize a git repo with user config and initial commit.

    If with_remote, also creates a bare local remote and adds it as origin.
    Returns the remote path if created, else None.
    """
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "README.md").write_text("hello")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True
    )

    remote_path = None
    if with_remote:
        remote_path = repo.parent / "remote.git"
        subprocess.run(
            ["git", "init", "--bare", str(remote_path)], check=True, capture_output=True
        )
        subprocess.run(
            ["git", "remote", "add", "origin", str(remote_path)],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "push", "-u", "origin", "main"],
            cwd=repo,
            check=True,
            capture_output=True,
        )

    return remote_path


@pytest.fixture()
def sample_kanban_data():
    """Minimal kanban board with one phase, one component, two tasks."""
    return {
        "phases": [
            {
                "id": "phase-1",
                "name": "Phase 1",
                "components": [
                    {
                        "id": "phase-1.comp-a",
                        "name": "Component A",
                        "tasks": [
                            {
                                "id": "phase-1.comp-a.task-1",
                                "content": "Task 1",
                                "status": "todo",
                                "priority": "high",
                                "blockedBy": [],
                                "description": "First task",
                                "exitCriteria": ["Criterion 1"],
                            },
                            {
                                "id": "phase-1.comp-a.task-2",
                                "content": "Task 2",
                                "status": "todo",
                                "priority": "medium",
                                "blockedBy": ["phase-1.comp-a.task-1"],
                                "description": "Second task, blocked by task-1",
                                "exitCriteria": ["Criterion 2"],
                            },
                        ],
                    }
                ],
            }
        ],
        "meta": {
            "current_phase": "phase-1",
            "current_task": None,
        },
    }


@pytest.fixture()
def kanban_file(tmp_path, sample_kanban_data):
    """Write sample kanban to a temp file and return its path."""
    path = tmp_path / "kanban.json"
    path.write_text(json.dumps(sample_kanban_data, indent=2))
    return path


@pytest.fixture()
def git_repo(tmp_path):
    """Create a temp git repo with an initial commit on main and a local bare remote."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo, with_remote=True)
    return repo


@pytest.fixture()
def project_tree(tmp_path):
    """Create a minimal project tree matching the pipeline's expected layout."""
    proj = tmp_path / "project"
    proj.mkdir()
    # git init + remote
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=proj, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=proj,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=proj,
        check=True,
        capture_output=True,
    )
    # docs
    docs = proj / "docs"
    docs.mkdir()
    (docs / "CODE-STANDARD.md").write_text("# Code Standard\nLint everything.")
    (docs / "ARCHITECTURE.md").write_text("# Architecture\nFeature-isolated layout.")
    phases = docs / "phases"
    phases.mkdir()
    (phases / "PHASE-1.md").write_text("# Phase 1\nDo the things.")
    # env
    env = proj / "env"
    env.mkdir()
    kanban_data = {
        "phases": [
            {
                "id": "phase-1",
                "name": "Phase 1",
                "components": [
                    {
                        "id": "phase-1.comp-a",
                        "name": "Component A",
                        "tasks": [
                            {
                                "id": "phase-1.comp-a.task-1",
                                "content": "Implement foo",
                                "status": "todo",
                                "priority": "high",
                                "blockedBy": [],
                                "description": "Implement the foo module",
                                "exitCriteria": ["foo works"],
                            }
                        ],
                    }
                ],
            }
        ],
        "meta": {"current_phase": "phase-1", "current_task": None},
    }
    (env / "kanban.json").write_text(json.dumps(kanban_data, indent=2))
    # initial commit
    subprocess.run(["git", "add", "."], cwd=proj, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=proj, check=True, capture_output=True
    )
    # bare remote
    remote_path = proj.parent / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", str(remote_path)], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "remote", "add", "origin", str(remote_path)],
        cwd=proj,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "push", "-u", "origin", "main"],
        cwd=proj,
        check=True,
        capture_output=True,
    )
    return proj
