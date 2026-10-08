"""Write the skstate MCP server entry into a project's IDE config.

OpenCode reads ``opencode.json`` at the project root. A file that already
nests servers under ``mcp.servers`` gets the v2 shape; anything else gets the
v1 shape (servers directly under ``mcp``). Codex reads ``.codex/config.toml``
with a ``[mcp_servers.skstate]`` table.

Uninstall only removes entries this module recognises as its own: the JSON
entry must carry ``SKSTATE_PROJECT`` in its environment, and the TOML table
must sit inside the ``# skstate mcp`` marker pair.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

SERVER_NAME = "skstate"

CODEX_BEGIN = "# skstate mcp begin"
CODEX_END = "# skstate mcp end"
CODEX_HEADER = "[mcp_servers.skstate]"

GITIGNORE_BEGIN = "# skstate begin"
GITIGNORE_END = "# skstate end"
GITIGNORE_RULE = ".skstate/"


def resolve_command() -> list[str]:
    """The server command as resolved right now."""
    executable = shutil.which("skstate")
    if executable:
        return [executable]
    return [sys.executable, "-m", "skstate"]


def server_entry(project: Path) -> dict[str, Any]:
    return {
        "type": "local",
        "command": resolve_command(),
        "cwd": str(project),
        "environment": {"SKSTATE_PROJECT": str(project)},
        "enabled": True,
    }


def is_managed_entry(entry: Any) -> bool:
    """True when the entry was written by ``skstate setup``."""
    if not isinstance(entry, dict):
        return False
    env = entry.get("environment")
    if not isinstance(env, dict) or "SKSTATE_PROJECT" not in env:
        return False
    command = entry.get("command")
    if isinstance(command, str):
        return "skstate" in command
    if isinstance(command, list):
        return any("skstate" in str(part) for part in command)
    return False


def _read_json(path: Path) -> tuple[dict[str, Any], bool]:
    if not path.exists():
        return {}, False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return data, True


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _opencode_servers(config: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Return the layout name and the dict that holds server entries."""
    mcp = config.get("mcp")
    if isinstance(mcp, dict):
        nested = mcp.get("servers")
        if isinstance(nested, dict):
            return "mcp.servers", nested
        return "mcp", mcp
    return "mcp", {}


def install_opencode(project: Path, force: bool = False) -> dict[str, Any]:
    path = project / "opencode.json"
    config, _existed = _read_json(path)
    layout, servers = _opencode_servers(config)
    entry = server_entry(project)
    result: dict[str, Any] = {
        "platform": "opencode",
        "config": str(path),
        "layout": layout,
        "command": entry["command"],
    }
    if SERVER_NAME in servers and not force:
        result["changed"] = False
        result["kept_existing"] = True
        result["note"] = "opencode.json 已有 skstate 项，保持原内容；用 --force 覆盖"
        return result
    servers[SERVER_NAME] = entry
    if layout == "mcp.servers":
        if not isinstance(config.get("mcp"), dict):
            config["mcp"] = {}
        config["mcp"]["servers"] = servers
    else:
        config["mcp"] = servers
    _write_json(path, config)
    result["changed"] = True
    result["kept_existing"] = False
    return result


def uninstall_opencode(project: Path) -> dict[str, Any]:
    path = project / "opencode.json"
    if not path.exists():
        return {"platform": "opencode", "changed": False, "note": "opencode.json 不存在"}
    config, _existed = _read_json(path)
    layout, servers = _opencode_servers(config)
    existing = servers.get(SERVER_NAME)
    if existing is None:
        return {"platform": "opencode", "changed": False}
    if not is_managed_entry(existing):
        return {
            "platform": "opencode",
            "changed": False,
            "note": "skstate 项不是 skstate setup 写的，保留",
        }
    del servers[SERVER_NAME]
    if not servers:
        if layout == "mcp.servers":
            mcp = config.get("mcp")
            if isinstance(mcp, dict):
                mcp.pop("servers", None)
                if not mcp:
                    config.pop("mcp", None)
        else:
            config.pop("mcp", None)
    _write_json(path, config)
    return {"platform": "opencode", "changed": True}


def opencode_mcp_installed(project: Path) -> bool:
    path = project / "opencode.json"
    try:
        config, _existed = _read_json(path)
    except ValueError:
        return False
    _layout, servers = _opencode_servers(config)
    return SERVER_NAME in servers


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def codex_section(project: Path) -> str:
    parts = resolve_command()
    command, args = parts[0], parts[1:]
    lines = [
        CODEX_BEGIN,
        CODEX_HEADER,
        f"command = {_toml_string(command)}",
        f"args = [{', '.join(_toml_string(part) for part in args)}]",
        f"cwd = {_toml_string(str(project))}",
        "",
        "[mcp_servers.skstate.env]",
        f"SKSTATE_PROJECT = {_toml_string(str(project))}",
        CODEX_END,
    ]
    return "\n".join(lines)


def _find_codex_span(text: str) -> tuple[int, int] | None:
    """Byte span of the skstate table: marker pair first, then the header."""
    begin = re.search(rf"(?m)^{re.escape(CODEX_BEGIN)}\s*$", text)
    if begin:
        end = re.search(rf"(?m)^{re.escape(CODEX_END)}\s*$", text[begin.end() :])
        if end:
            stop = begin.end() + end.end()
            return begin.start(), stop
    header = re.search(rf"(?m)^{re.escape(CODEX_HEADER)}\s*$", text)
    if not header:
        return None
    # The table runs until the next table header that is not ours
    # (``[mcp_servers.skstate.env]`` continues the same entry).
    rest = re.search(r"(?m)^\[(?!mcp_servers\.skstate(?:\.|\]))", text[header.end() :])
    stop = header.end() + rest.start() if rest else len(text)
    return header.start(), stop


def install_codex(project: Path, force: bool = False) -> dict[str, Any]:
    path = project / ".codex" / "config.toml"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    span = _find_codex_span(text)
    result: dict[str, Any] = {
        "platform": "codex",
        "config": str(path),
        "command": resolve_command(),
    }
    if span is not None and not force:
        result["changed"] = False
        result["kept_existing"] = True
        result["note"] = ".codex/config.toml 已有 skstate 项，保持原内容；用 --force 覆盖"
        return result
    section = codex_section(project)
    if span is not None:
        merged = text[: span[0]] + section + text[span[1] :]
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        merged = text + ("\n" if text else "") + section + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(merged, encoding="utf-8")
    result["changed"] = True
    result["kept_existing"] = False
    return result


def uninstall_codex(project: Path) -> dict[str, Any]:
    path = project / ".codex" / "config.toml"
    if not path.exists():
        return {"platform": "codex", "changed": False, "note": ".codex/config.toml 不存在"}
    text = path.read_text(encoding="utf-8")
    begin = re.search(rf"(?m)^{re.escape(CODEX_BEGIN)}\s*$", text)
    if begin:
        end = re.search(rf"(?m)^{re.escape(CODEX_END)}\s*$", text[begin.end() :])
        if end:
            stop = begin.end() + end.end()
            trimmed = (text[: begin.start()] + text[stop:]).rstrip() + "\n"
            path.write_text(trimmed, encoding="utf-8")
            return {"platform": "codex", "changed": True}
    header = re.search(rf"(?m)^{re.escape(CODEX_HEADER)}\s*$", text)
    if header:
        return {
            "platform": "codex",
            "changed": False,
            "note": "skstate 项不在 skstate 标记里，保留",
        }
    return {"platform": "codex", "changed": False}


def codex_mcp_installed(project: Path) -> bool:
    path = project / ".codex" / "config.toml"
    if not path.exists():
        return False
    return _find_codex_span(path.read_text(encoding="utf-8")) is not None


def _is_git_repo(project: Path) -> bool:
    for candidate in (project, *project.parents):
        if (candidate / ".git").exists():
            return True
    return False


def _gitignore_has_rule(text: str) -> bool:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped in {GITIGNORE_RULE, GITIGNORE_RULE.rstrip("/"), "/" + GITIGNORE_RULE}:
            return True
    return False


def ensure_gitignore(project: Path) -> dict[str, Any]:
    """Add the marked ``.skstate/`` rule when the project sits in a git repo."""
    if not _is_git_repo(project):
        return {"changed": False, "reason": "不在 git 仓库里"}
    path = project / ".gitignore"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if GITIGNORE_BEGIN in text:
        return {"changed": False, "path": str(path), "reason": "已有 skstate 标记段"}
    if _gitignore_has_rule(text):
        return {"changed": False, "path": str(path), "reason": "已有 .skstate/ 忽略规则"}
    if text and not text.endswith("\n"):
        text += "\n"
    block = f"{GITIGNORE_BEGIN}\n{GITIGNORE_RULE}\n{GITIGNORE_END}\n"
    path.write_text(text + ("\n" if text else "") + block, encoding="utf-8")
    return {"changed": True, "path": str(path)}


def remove_gitignore(project: Path) -> dict[str, Any]:
    path = project / ".gitignore"
    if not path.exists():
        return {"changed": False, "reason": ".gitignore 不存在"}
    text = path.read_text(encoding="utf-8")
    begin = re.search(rf"(?m)^{re.escape(GITIGNORE_BEGIN)}\s*$", text)
    if not begin:
        return {"changed": False, "reason": "没有 skstate 标记段"}
    end = re.search(rf"(?m)^{re.escape(GITIGNORE_END)}\s*$", text[begin.end() :])
    if not end:
        return {"changed": False, "reason": "skstate 标记段不完整"}
    stop = begin.end() + end.end()
    trimmed = (text[: begin.start()] + text[stop:]).rstrip() + ("\n" if text[: begin.start()].strip() else "")
    path.write_text(trimmed, encoding="utf-8")
    return {"changed": True, "path": str(path)}
