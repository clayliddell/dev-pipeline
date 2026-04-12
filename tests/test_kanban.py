"""Unit tests for pipeline.kanban."""

import json
import pytest

from kanban import Kanban, STATUSES


class TestLoad:
    def test_load_sets_meta_defaults(self, kanban_file):
        kb = Kanban(kanban_file)
        data = kb.load()
        assert data["meta"]["current_phase"] == "phase-1"
        assert data["meta"]["current_task"] is None

    def test_load_normalizes_legacy_statuses(self, tmp_path, sample_kanban_data):
        sample_kanban_data["phases"][0]["components"][0]["tasks"][0]["status"] = (
            "project_manager"
        )
        sample_kanban_data["phases"][0]["components"][0]["tasks"][1]["status"] = (
            "code_review"
        )
        path = tmp_path / "kanban.json"
        path.write_text(json.dumps(sample_kanban_data, indent=2))

        kb = Kanban(path)
        kb.load()

        assert kb._get_task("phase-1.comp-a.task-1")[2]["status"] == "project_manager"
        assert kb._get_task("phase-1.comp-a.task-2")[2]["status"] == "code_review"

    def test_load_normalizes_legacy_exit_criteria_status(self, tmp_path, sample_kanban_data):
        sample_kanban_data["phases"][0]["components"][0]["tasks"][0]["status"] = (
            "exit_criteria_met"
        )
        sample_kanban_data["phases"][0]["components"][0]["tasks"][0]["resume"] = {
            "exit_criteria_met": {"input": "old input", "confirmed": True}
        }
        path = tmp_path / "kanban.json"
        path.write_text(json.dumps(sample_kanban_data, indent=2))

        kb = Kanban(path)
        kb.load()

        assert kb._get_task("phase-1.comp-a.task-1")[2]["status"] == "exit_criteria_met"
        assert (
            kb._get_task("phase-1.comp-a.task-1")[2]["resume"]["exit_criteria_met"]
            == {"input": "old input", "confirmed": True}
        )

    def test_data_lazy_loads(self, kanban_file):
        kb = Kanban(kanban_file)
        assert kb._data == {}
        _ = kb.data
        assert kb._data != {}


class TestStatusQueries:
    def test_is_task_unblocked_no_blockers(self, kanban_file):
        kb = Kanban(kanban_file)
        kb.load()
        task = kb._get_task("phase-1.comp-a.task-1")[2]
        assert kb.is_task_unblocked(task) is True

    def test_is_task_unblocked_with_pending_blocker(self, kanban_file):
        kb = Kanban(kanban_file)
        kb.load()
        task = kb._get_task("phase-1.comp-a.task-2")[2]
        assert kb.is_task_unblocked(task) is False

    def test_is_task_unblocked_after_blocker_done(self, kanban_file):
        kb = Kanban(kanban_file)
        kb.load()
        kb.set_status("phase-1.comp-a.task-1", "done")
        task = kb._get_task("phase-1.comp-a.task-2")[2]
        assert kb.is_task_unblocked(task) is True

    def test_get_phase_tasks(self, kanban_file):
        kb = Kanban(kanban_file)
        kb.load()
        tasks = kb.get_phase_tasks("phase-1")
        assert len(tasks) == 2

    def test_get_phase_tasks_filtered(self, kanban_file):
        kb = Kanban(kanban_file)
        kb.load()
        kb.set_status("phase-1.comp-a.task-1", "done")
        todo = kb.get_phase_tasks("phase-1", status="todo")
        assert len(todo) == 1
        assert todo[0]["id"] == "phase-1.comp-a.task-2"

    def test_is_phase_complete_false(self, kanban_file):
        kb = Kanban(kanban_file)
        kb.load()
        assert kb.is_phase_complete("phase-1") is False

    def test_is_phase_complete_true(self, kanban_file):
        kb = Kanban(kanban_file)
        kb.load()
        kb.set_status("phase-1.comp-a.task-1", "done")
        kb.set_status("phase-1.comp-a.task-2", "done")
        assert kb.is_phase_complete("phase-1") is True


class TestMutations:
    def test_set_status(self, kanban_file):
        kb = Kanban(kanban_file)
        kb.load()
        task = kb.set_status("phase-1.comp-a.task-1", "project_manager")
        assert task["status"] == "project_manager"
        assert kb.data["meta"]["current_task"] == "phase-1.comp-a.task-1"

    def test_set_status_invalid(self, kanban_file):
        kb = Kanban(kanban_file)
        kb.load()
        with pytest.raises(ValueError, match="Invalid status"):
            kb.set_status("phase-1.comp-a.task-1", "bogus")

    def test_set_status_unknown_task(self, kanban_file):
        kb = Kanban(kanban_file)
        kb.load()
        with pytest.raises(KeyError):
            kb.set_status("does.not.exist", "done")

    def test_set_status_enforces_single_active_task(self, kanban_file):
        kb = Kanban(kanban_file)
        kb.load()
        kb.set_status("phase-1.comp-a.task-1", "project_manager")
        with pytest.raises(RuntimeError, match="already active"):
            kb.set_status("phase-1.comp-a.task-2", "software_engineer")

    def test_pickup_next_returns_first_unblocked(self, kanban_file):
        kb = Kanban(kanban_file)
        kb.load()
        task = kb.pickup_next()
        assert task is not None
        assert task["id"] == "phase-1.comp-a.task-1"
        assert task["status"] == "project_manager"

    def test_pickup_next_skips_blocked(self, kanban_file):
        kb = Kanban(kanban_file)
        kb.load()
        kb.set_status("phase-1.comp-a.task-1", "done")
        task = kb.pickup_next()
        assert task is not None
        assert task["id"] == "phase-1.comp-a.task-2"
        assert task["status"] == "project_manager"

    def test_pickup_next_returns_none_when_all_blocked(self, sample_kanban_data):
        """Both tasks blocked — nothing to pick up."""
        sample_kanban_data["phases"][0]["components"][0]["tasks"][0]["blockedBy"] = [
            "some-unknown"
        ]
        import tempfile, pathlib

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sample_kanban_data, f)
            path = pathlib.Path(f.name)
        kb = Kanban(path)
        kb.load()
        # task-1 blocked by unknown (treated as resolved), task-2 blocked by task-1
        task = kb.pickup_next()
        assert task["id"] == "phase-1.comp-a.task-1"

    def test_complete_current(self, kanban_file):
        kb = Kanban(kanban_file)
        kb.load()
        kb.pickup_next()
        next_task = kb.complete_current()
        assert next_task is not None
        assert next_task["id"] == "phase-1.comp-a.task-2"
        assert next_task["status"] == "project_manager"

    def test_review_current(self, kanban_file):
        kb = Kanban(kanban_file)
        kb.load()
        kb.pickup_next()
        next_task = kb.review_current()
        # task-2 is still blocked (task-1 is code_review, not done)
        assert next_task is None
        assert kb._get_task("phase-1.comp-a.task-1")[2]["status"] == "code_review"

    def test_resume_payload_roundtrip(self, kanban_file):
        kb = Kanban(kanban_file)
        kb.load()
        kb.set_resume_payload(
            "phase-1.comp-a.task-1",
            "project_manager",
            "plan input",
            output="plan output",
            confirmed=True,
        )
        kb.save()

        kb2 = Kanban(kanban_file)
        kb2.load()
        payload = kb2.get_resume_payload("phase-1.comp-a.task-1", "project_manager")

        assert payload is not None
        assert payload["input"] == "plan input"
        assert payload["output"] == "plan output"
        assert payload["confirmed"] is True

    def test_done_clears_resume_payload(self, kanban_file):
        kb = Kanban(kanban_file)
        kb.load()
        kb.set_resume_payload(
            "phase-1.comp-a.task-1",
            "project_manager",
            "plan input",
            output="plan output",
            confirmed=True,
        )
        kb.set_status("phase-1.comp-a.task-1", "done")

        assert "resume" not in kb._get_task("phase-1.comp-a.task-1")[2]


class TestProgress:
    def test_get_progress(self, kanban_file):
        kb = Kanban(kanban_file)
        kb.load()
        p = kb.get_progress()
        assert p["total"] == 2
        assert p["done"] == 0
        assert p["pct"] == 0

    def test_visualize_returns_string(self, kanban_file):
        kb = Kanban(kanban_file)
        kb.load()
        v = kb.visualize()
        assert "KANBAN BOARD" in v
        assert "phase-1.comp-a.task-1" in v


class TestSave:
    def test_save_roundtrip(self, kanban_file, tmp_path):
        kb = Kanban(kanban_file)
        kb.load()
        kb.set_status("phase-1.comp-a.task-1", "done")
        kb.save()

        kb2 = Kanban(kanban_file)
        kb2.load()
        assert kb2._get_task("phase-1.comp-a.task-1")[2]["status"] == "done"

    def test_save_raises_without_load(self, tmp_path):
        kb = Kanban(tmp_path / "nope.json")
        with pytest.raises(RuntimeError, match="No data loaded"):
            kb.save()
