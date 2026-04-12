"""Kanban board management for kanban.json task tracking."""

import json
from pathlib import Path
from typing import Optional

# Ordered Kanban Swimlanes
SWIMLANES = {
    "todo": "To Do",
    "project_manager": "Project Manager",
    "software_engineer": "Software Engineer",
    "code_review": "Code Review",
    "code_review_eval": "Code Review Eval",
    "exit_criteria_met": "Exit Criteria Met Check",
    "finalization": "Finalization",
    "done": "Done",
}
STATUSES = list(SWIMLANES.keys())
ACTIVE_STATUSES = [status for status in STATUSES if status not in {"todo", "done"}]
RESUME_PRIORITY = ACTIVE_STATUSES[::-1]


class Kanban:
    """Kanban board interface for managing kanban.json tasks."""

    def __init__(self, path: str | Path = "kanban.json"):
        self.path = Path(path)
        self._data: dict = {}

    def load(self) -> dict:
        """Load kanban.json from disk."""
        with open(self.path) as f:
            self._data = json.load(f)
        # Ensure meta fields exist
        self._data.setdefault("meta", {})
        self._data["meta"].setdefault("current_phase", self._data["phases"][0]["id"])
        self._data["meta"].setdefault("current_task", None)
        for phase in self._data.get("phases", []):
            for comp in phase.get("components", []):
                for task in comp.get("tasks", []):
                    task["status"] = task.get("status", "todo")
                    if not isinstance(task.get("resume"), dict):
                        task.pop("resume", None)
                        continue
                    resume = task["resume"]
                    for stage, payload in list(resume.items()):
                        if not isinstance(payload, dict):
                            resume.pop(stage, None)
                            continue
                        payload.setdefault("confirmed", False)

        current_task = self._data["meta"].get("current_task")
        if current_task:
            result = self._get_task(current_task)
            if result is None or result[2].get("status") == "done":
                self._data["meta"]["current_task"] = None
        return self._data

    def save(self) -> None:
        """Write current state back to disk."""
        if not self._data:
            raise RuntimeError("No data loaded. Call load() first.")
        with open(self.path, "w") as f:
            json.dump(self._data, f, indent=2)

    @property
    def data(self) -> dict:
        if not self._data:
            self.load()
        return self._data

    # ── Iteration helpers ──────────────────────────────────────────

    def _all_tasks(self):
        """Yield (phase, component, task) triples for every task."""
        for phase in self.data["phases"]:
            for comp in phase["components"]:
                for task in comp["tasks"]:
                    yield phase, comp, task

    def _task_resume(self, task: dict) -> dict:
        return task.setdefault("resume", {})

    def _task_is_active(self, task: dict) -> bool:
        return task.get("status", "todo") in ACTIVE_STATUSES

    def _get_task(self, task_id: str) -> Optional[tuple]:
        """Return (phase, component, task) for a given task id, or None."""
        for phase, comp, task in self._all_tasks():
            if task["id"] == task_id:
                return phase, comp, task
        return None

    def _current_phase(self) -> dict:
        phase_id = self.data["meta"]["current_phase"]
        for phase in self.data["phases"]:
            if phase["id"] == phase_id:
                return phase
        return self.data["phases"][0]

    # ── Status queries ─────────────────────────────────────────────

    def is_task_unblocked(self, task: dict) -> bool:
        """A task is unblocked when every blocker has status 'done'."""
        for blocker_id in task.get("blockedBy", []):
            result = self._get_task(blocker_id)
            if result is None:
                continue  # unknown blocker – treat as resolved
            _, _, blocker = result
            if blocker["status"] != "done":
                return False
        return True

    def get_swimlanes(self) -> dict[str, list[dict]]:
        """Return tasks grouped by status."""
        lanes: dict[str, list[dict]] = {s: [] for s in STATUSES}
        for _, _, task in self._all_tasks():
            status = task.get("status", "todo")
            if status not in lanes:
                lanes[status] = []
            lanes[status].append(task)
        return lanes

    def get_phase_tasks(
        self, phase_id: str, status: Optional[str] = None
    ) -> list[dict]:
        """Return tasks for a phase, optionally filtered by status."""
        tasks = []
        for phase, _, task in self._all_tasks():
            if phase["id"] == phase_id:
                if status is None or task["status"] == status:
                    tasks.append(task)
        return tasks

    def is_phase_complete(self, phase_id: str) -> bool:
        """Phase is complete when every task is 'done'."""
        tasks = self.get_phase_tasks(phase_id)
        return bool(tasks) and all(t["status"] == "done" for t in tasks)

    # ── Mutations ──────────────────────────────────────────────────

    def set_status(self, task_id: str, status: str) -> dict:
        """Move a task to the given status."""
        if status not in STATUSES:
            raise ValueError(f"Invalid status '{status}'. Must be one of {STATUSES}")
        result = self._get_task(task_id)
        if result is None:
            raise KeyError(f"Task '{task_id}' not found")
        _, _, task = result
        previous_status = task.get("status", "todo")
        current = self.data["meta"].get("current_task")

        if status in ACTIVE_STATUSES:
            if current and current != task_id:
                cur = self._get_task(current)
                if cur and self._task_is_active(cur[2]):
                    raise RuntimeError(
                        f"Task '{current}' is already active. "
                        "Complete or move it first."
                    )
            if previous_status == "todo" or previous_status == status:
                self.data["meta"]["current_task"] = task_id
            elif self.data["meta"].get("current_task") == task_id:
                self.data["meta"]["current_task"] = None
        else:
            if self.data["meta"].get("current_task") == task_id:
                self.data["meta"]["current_task"] = None

        task["status"] = status
        if status == "done":
            task.pop("resume", None)
        return task

    def pickup_next(self, exclude_task_ids: Optional[set[str]] = None) -> Optional[dict]:
        """Pick the next resumable task, then the next unblocked todo task."""
        exclude_task_ids = exclude_task_ids or set()
        meta = self.data["meta"]

        # If something is already active, return it.
        if meta.get("current_task") and meta["current_task"] not in exclude_task_ids:
            result = self._get_task(meta["current_task"])
            if result and result[2]["status"] != "done":
                meta["current_phase"] = result[0]["id"]
                return result[2]
            meta["current_task"] = None

        # Prefer resumable work before fresh todo items.
        for status in RESUME_PRIORITY:
            for phase, _, task in self._all_tasks():
                if task["id"] in exclude_task_ids:
                    continue
                if task.get("status", "todo") == status:
                    meta["current_phase"] = phase["id"]
                    return self.set_status(task["id"], status)

        # Walk phases forward until we find work or run out
        for phase in self.data["phases"]:
            pid = phase["id"]
            if self.is_phase_complete(pid):
                continue

            meta["current_phase"] = pid

            # Find first unblocked task in this phase
            for _, _, task in self._all_tasks():
                if task["id"] in exclude_task_ids:
                    continue
                if task["status"] == "todo" and self.is_task_unblocked(task):
                    return self.set_status(task["id"], "project_manager")

            # Phase has pending work but everything is blocked
            return None

        return None  # All phases complete

    def complete_current(self) -> Optional[dict]:
        """Mark the current task as done and auto-advance."""
        meta = self.data["meta"]
        current_id = meta.get("current_task")
        if not current_id:
            return None
        self.set_status(current_id, "done")
        return self.pickup_next()

    def review_current(self) -> Optional[dict]:
        """Move the current task to code review and auto-advance."""
        meta = self.data["meta"]
        current_id = meta.get("current_task")
        if not current_id:
            return None
        self.set_status(current_id, "code_review")
        return self.pickup_next(exclude_task_ids={current_id})

    def get_resume_payload(self, task_id: str, stage: Optional[str] = None) -> dict | None:
        result = self._get_task(task_id)
        if result is None:
            raise KeyError(f"Task '{task_id}' not found")
        resume = result[2].get("resume", {})
        if stage is None:
            return resume
        return resume.get(stage)

    def set_resume_payload(
        self,
        task_id: str,
        stage: str,
        input_text: str,
        output: str | None = None,
        confirmed: bool = False,
    ) -> dict:
        result = self._get_task(task_id)
        if result is None:
            raise KeyError(f"Task '{task_id}' not found")
        task = result[2]
        resume = self._task_resume(task)
        payload: dict = {
            "input": input_text,
            "confirmed": confirmed,
        }
        if output is not None:
            payload["output"] = output
        resume[stage] = payload
        return payload

    def clear_resume_payload(self, task_id: str) -> None:
        result = self._get_task(task_id)
        if result is None:
            raise KeyError(f"Task '{task_id}' not found")
        result[2].pop("resume", None)

    # ── Progress / visualization ───────────────────────────────────

    def get_progress(self) -> dict:
        """Return overall and per-phase progress counters."""
        phases = []
        total = done = 0
        current_task_status = None
        current_task = self.data["meta"].get("current_task")
        if current_task:
            result = self._get_task(current_task)
            if result:
                current_task_status = result[2].get("status")
        for phase in self.data["phases"]:
            p_total = p_done = 0
            for comp in phase["components"]:
                for task in comp["tasks"]:
                    p_total += 1
                    if task["status"] == "done":
                        p_done += 1
            total += p_total
            done += p_done
            phases.append(
                {
                    "id": phase["id"],
                    "name": phase["name"],
                    "total": p_total,
                    "done": p_done,
                    "pct": round(100 * p_done / p_total) if p_total else 0,
                }
            )
        return {
            "total": total,
            "done": done,
            "pct": round(100 * done / total) if total else 0,
            "phases": phases,
            "current_phase": self.data["meta"]["current_phase"],
            "current_task": self.data["meta"].get("current_task"),
            "current_task_status": current_task_status,
        }

    def visualize(self) -> str:
        """Return a text-based kanban + progress visualization."""
        lines: list[str] = []
        lanes = self.get_swimlanes()
        prog = self.get_progress()

        # ── Header ─────────────────────────────────────────────────
        lines.append("=" * 72)
        lines.append("  AGENTVM  ·  KANBAN BOARD")
        lines.append("=" * 72)
        lines.append(
            f"  Progress: {prog['done']}/{prog['total']} tasks ({prog['pct']}%)"
        )
        current_task = prog["current_task"]
        current_task_status = prog.get("current_task_status")
        current_task_text = "—"
        if current_task:
            current_task_text = current_task
            if current_task_status:
                current_task_text = f"{current_task} ({current_task_status})"
        lines.append(f"  Current phase: {prog['current_phase']}  │  Current task: {current_task_text}")
        lines.append("─" * 72)

        # ── Swim lanes ─────────────────────────────────────────────
        for status in STATUSES:
            label = SWIMLANES[status]
            tasks = lanes.get(status, [])
            lines.append(f"\n  ▸ {label}  ({len(tasks)})")
            if not tasks:
                lines.append("    (empty)")
            else:
                for t in tasks:
                    active = " ◄ current" if t["id"] == prog["current_task"] else ""
                    blocked = "" if self.is_task_unblocked(t) else " 🔒"
                    lines.append(f"    • {t['id']}{active}{blocked}")
        lines.append("")

        # ── Per-phase progress bar ─────────────────────────────────
        lines.append("─" * 72)
        lines.append("  PHASE PROGRESS")
        lines.append("─" * 72)
        bar_width = 30
        for p in prog["phases"]:
            filled = round(bar_width * p["done"] / p["total"]) if p["total"] else 0
            bar = "█" * filled + "░" * (bar_width - filled)
            marker = " ◄ current" if p["id"] == prog["current_phase"] else ""
            lines.append(f"  {p['name']:<50} [{bar}] {p['pct']:>3}%{marker}")
        lines.append("=" * 72)
        return "\n".join(lines)


# ── CLI convenience ─────────────────────────────────────────────────


def main():
    """Simple CLI for the kanban board."""
    import argparse

    parser = argparse.ArgumentParser(description="Kanban board CLI")
    parser.add_argument(
        "-f", "--file", default="kanban.json", help="Path to kanban.json file"
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="show",
        choices=["show", "pickup", "done", "review", "status"],
        help="Command to run (default: show)",
    )
    parser.add_argument("args", nargs="*", help="Additional arguments for the command")
    ns = parser.parse_args()

    kb = Kanban(ns.file)
    kb.load()

    cmd = ns.command

    if cmd == "show":
        print(kb.visualize())
    elif cmd == "pickup":
        task = kb.pickup_next()
        kb.save()
        if task:
            print(f"Picked up: {task['id']}")
        else:
            print("No unblocked tasks available.")
    elif cmd == "done":
        task = kb.complete_current()
        kb.save()
        print("Marked done.")
        if task:
            print(f"Next: {task['id']}")
        else:
            print("No more tasks.")
    elif cmd == "review":
        task = kb.review_current()
        kb.save()
        print("Moved to code review.")
        if task:
            print(f"Next: {task['id']}")
        else:
            print("No more tasks.")
    elif cmd == "status":
        if len(ns.args) < 2:
            parser.error("status requires <id> and <status> arguments")
        task_id = ns.args[0]
        new_status = ns.args[1]
        kb.set_status(task_id, new_status)
        kb.save()
        print(f"Set {task_id} → {new_status}")


if __name__ == "__main__":
    main()
