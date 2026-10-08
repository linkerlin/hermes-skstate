"""``skstate setup`` / ``--uninstall`` for one project and one platform.

Setup writes the MCP server entry, installs the session hooks under the same
project, and adds the gitignore rule. Teardown removes only what setup marks
as its own.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from skstate.hooks.common import assert_project_dir
from skstate.hooks.setup import install_hooks, uninstall_hooks
from skstate.mcp_config import (
    ensure_gitignore,
    install_codex,
    install_opencode,
    remove_gitignore,
    uninstall_codex,
    uninstall_opencode,
)

_PLATFORMS = ("opencode", "codex")
_TRUST_NOTE = "项目级 .codex/config.toml 只在受信任的项目中生效"


def setup_project(platform: str, project_dir: str | Path, force: bool = False) -> dict[str, Any]:
    root = assert_project_dir(project_dir)
    if platform not in _PLATFORMS:
        raise ValueError("platform must be opencode or codex")
    mcp = install_opencode(root, force=force) if platform == "opencode" else install_codex(root, force=force)
    hooks = install_hooks(platform, root, force=force)
    gitignore = ensure_gitignore(root)
    notes = [mcp["note"]] if mcp.get("note") else []
    if platform == "codex":
        notes.append(_TRUST_NOTE)
    return {
        "platform": platform,
        "project_dir": str(root),
        "mcp": mcp,
        "hooks": hooks,
        "gitignore": gitignore,
        "notes": notes,
        "next": "在 IDE 里打开这个项目，新会话的第一条消息给出具体任务",
    }


def teardown_project(platform: str, project_dir: str | Path) -> dict[str, Any]:
    root = assert_project_dir(project_dir)
    if platform not in _PLATFORMS:
        raise ValueError("platform must be opencode or codex")
    mcp = uninstall_opencode(root) if platform == "opencode" else uninstall_codex(root)
    hooks = uninstall_hooks(platform, root)
    gitignore = remove_gitignore(root)
    notes = [mcp["note"]] if mcp.get("note") else []
    return {
        "platform": platform,
        "project_dir": str(root),
        "mcp": mcp,
        "hooks": hooks,
        "gitignore": gitignore,
        "notes": notes,
    }
