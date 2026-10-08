"""Shared path and JSON helpers for IDE hook installers."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

MANAGED_FLAG = "_skstate_managed"
HOOK_MODULE_MARK = "skstate.hooks"
HOOK_EVENT_MARK = "skstate hook session-"


def _installed_console_script() -> str | None:
    """A ``skstate`` on PATH that belongs to the current Python install."""
    found = shutil.which("skstate")
    if not found:
        return None
    try:
        resolved = Path(found).resolve()
        prefix = Path(sys.prefix).resolve()
    except OSError:
        return None
    if resolved == prefix or prefix in resolved.parents:
        return found
    return None


def hook_command_parts(event: str) -> list[str]:
    """argv for ``skstate hook session-start`` / ``session-end``."""
    subcommand = "session-start" if event == "session_start" else "session-end"
    executable = _installed_console_script()
    if executable:
        return [executable, "hook", subcommand]
    return [sys.executable, "-m", "skstate", "hook", subcommand]


def hook_command_string(event: str) -> str:
    parts = hook_command_parts(event)
    if " " in parts[0]:
        parts[0] = f'"{parts[0]}"'
    return " ".join(parts)


def is_our_hook_command(command: str) -> bool:
    return HOOK_MODULE_MARK in command or HOOK_EVENT_MARK in command


def assert_project_dir(project_dir: str | Path) -> Path:
    root = Path(project_dir).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"project dir does not exist: {root}")
    if root == Path(root.anchor):
        raise ValueError("refusing to install hooks at the filesystem root")
    return root


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def merge_hooks(path: Path, incoming: dict[str, Any]) -> None:
    current = read_json(path)
    hooks = current.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
    new_hooks = incoming.get("hooks") or {}
    for event, entries in new_hooks.items():
        existing = hooks.get(event)
        if not isinstance(existing, list):
            existing = []
        commands = {
            item.get("command")
            for item in existing
            if isinstance(item, dict) and isinstance(item.get("command"), str)
        }
        for entry in entries:
            if isinstance(entry, dict) and entry.get("command") not in commands:
                existing.append(entry)
        hooks[event] = existing
    current["hooks"] = hooks
    current[MANAGED_FLAG] = True
    write_json(path, current)


def strip_our_hooks(path: Path) -> bool:
    if not path.exists():
        return False
    data = read_json(path)
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return False
    changed = False
    for event in list(hooks):
        entries = hooks[event]
        if not isinstance(entries, list):
            continue
        kept = []
        for item in entries:
            command = item.get("command") if isinstance(item, dict) else ""
            if isinstance(command, str) and is_our_hook_command(command):
                changed = True
                continue
            kept.append(item)
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)
            changed = True
    if not hooks:
        data.pop("hooks", None)
    data.pop(MANAGED_FLAG, None)
    if changed:
        if data:
            write_json(path, data)
        else:
            path.unlink(missing_ok=True)
    return changed
