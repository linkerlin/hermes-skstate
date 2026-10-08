"""Dispatch hook install for OpenCode and Codex."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from skstate.hooks import codex, opencode


def install_hooks(platform: str, project_dir: str | Path, force: bool = False) -> dict[str, Any]:
    if platform == "opencode":
        return opencode.install(project_dir, force=force)
    if platform == "codex":
        return codex.install(project_dir, force=force)
    raise ValueError("platform must be opencode or codex")


def uninstall_hooks(platform: str, project_dir: str | Path) -> dict[str, Any]:
    if platform == "opencode":
        return opencode.uninstall(project_dir)
    if platform == "codex":
        return codex.uninstall(project_dir)
    raise ValueError("platform must be opencode or codex")


def hooks_status(project_dir: str | Path) -> dict[str, Any]:
    return {
        "opencode": opencode.status(project_dir),
        "codex": codex.status(project_dir),
    }
