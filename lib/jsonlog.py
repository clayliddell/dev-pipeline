"""Structured JSONL logging for pipeline events."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_json_log_lock = threading.Lock()
_json_log_file = None


def _json_default(value: Any) -> str:
    if isinstance(value, Path):
        return str(value)
    return str(value)


def setup_json_log(path: Path) -> None:
    """Open the JSONL log file."""
    global _json_log_file
    _json_log_file = open(path, "w", encoding="utf-8")


def close_json_log() -> None:
    """Close the JSONL log file if open."""
    global _json_log_file
    if _json_log_file and hasattr(_json_log_file, "close"):
        _json_log_file.close()
    _json_log_file = None


def log_json(event: str, **fields: Any) -> None:
    """Write one structured JSON event as a JSON line."""
    if _json_log_file is None:
        return

    record: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
    }
    record.update(fields)

    with _json_log_lock:
        json.dump(record, _json_log_file, ensure_ascii=False, default=_json_default)
        _json_log_file.write("\n")
        _json_log_file.flush()
