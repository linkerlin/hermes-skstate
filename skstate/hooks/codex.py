"""Install Codex command hooks under `<project>/.codex`."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from skstate.hooks.common import (
    HOOK_EVENT_MARK,
    HOOK_MODULE_MARK,
    assert_project_dir,
    hook_command_string,
    merge_hooks,
    strip_our_hooks,
)

_FEATURE_LINE = "codex_hooks = true  # skstate"


def build_hooks_json() -> dict[str, Any]:
    return {
        "hooks": {
            "SessionStart": [
                {
                    "type": "command",
                    "command": hook_command_string("session_start"),
                    "timeout": 5,
                }
            ],
            "Stop": [
                {
                    "type": "command",
                    "command": hook_command_string("session_end"),
                    "timeout": 8,
                }
            ],
        }
    }


def _enable_feature(codex_dir: Path) -> bool:
    path = codex_dir / "config.toml"
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    if _FEATURE_LINE in content or re.search(r"(?im)^\s*codex_hooks\s*=\s*true\b", content):
        if _FEATURE_LINE not in content and "codex_hooks" in content:
            return False
        if _FEATURE_LINE in content:
            return False
    if re.search(r"(?m)^\[features\]\s*$", content):
        content = re.sub(
            r"(?m)^\[features\]\s*$",
            "[features]\n" + _FEATURE_LINE,
            content,
            count=1,
        )
    else:
        if content and not content.endswith("\n"):
            content += "\n"
        content += ("\n" if content else "") + "[features]\n" + _FEATURE_LINE + "\n"
    path.write_text(content, encoding="utf-8")
    return True


def _disable_feature(codex_dir: Path) -> bool:
    path = codex_dir / "config.toml"
    if not path.exists():
        return False
    content = path.read_text(encoding="utf-8")
    if _FEATURE_LINE not in content:
        return False
    content = content.replace(_FEATURE_LINE + "\n", "").replace(_FEATURE_LINE, "")
    content = re.sub(r"(?m)^\[features\]\s*\n(?=\s*\[|\s*$)", "", content)
    path.write_text(content, encoding="utf-8")
    return True


def install(project_dir: str | Path, force: bool = False) -> dict[str, Any]:
    root = assert_project_dir(project_dir)
    codex_dir = root / ".codex"
    codex_dir.mkdir(parents=True, exist_ok=True)
    hooks_path = codex_dir / "hooks.json"
    if force and hooks_path.exists():
        strip_our_hooks(hooks_path)
    merge_hooks(hooks_path, build_hooks_json())
    feature_changed = _enable_feature(codex_dir)
    return {
        "platform": "codex",
        "project_dir": str(root),
        "hooks": str(hooks_path),
        "feature_enabled": feature_changed,
    }


def uninstall(project_dir: str | Path) -> dict[str, Any]:
    root = assert_project_dir(project_dir)
    codex_dir = root / ".codex"
    removed = strip_our_hooks(codex_dir / "hooks.json")
    feature_removed = _disable_feature(codex_dir)
    return {
        "platform": "codex",
        "removed_hooks": removed,
        "feature_removed": feature_removed,
    }


def status(project_dir: str | Path) -> dict[str, Any]:
    root = Path(project_dir).expanduser().resolve()
    hooks_path = root / ".codex" / "hooks.json"
    installed = False
    if hooks_path.exists():
        text = hooks_path.read_text(encoding="utf-8")
        installed = HOOK_MODULE_MARK in text or HOOK_EVENT_MARK in text
    return {"platform": "codex", "installed": installed, "hooks": str(hooks_path)}
