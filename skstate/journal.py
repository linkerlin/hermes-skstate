"""Append-only hook journal. Not part of the execution prompt."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from skstate.paths import data_dir


def events_path():
    return data_dir() / "hook_events.jsonl"


def append_event(event: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "payload": payload or {},
    }
    path = events_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
    return record


def tail_events(limit: int = 20) -> list[dict[str, Any]]:
    path = events_path()
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    records: list[dict[str, Any]] = []
    for line in lines[-max(1, limit) :]:
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            records.append(item)
    return records
