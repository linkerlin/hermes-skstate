"""Stdio MCP server. Its instructions are the takeover instrument.

The server does not create an LLM client. Logs go to stderr.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from skstate.instrument import TOOL_NAMES, live_instrument
from skstate import surface

logger = logging.getLogger("skstate")


def _dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def create_server():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError(
            'MCP server requires the mcp package. Install with: pip install "mcp>=1.2,<2"'
        ) from exc

    mcp = FastMCP("skstate", instructions=live_instrument())

    @mcp.tool(name="skstate_boot")
    def skstate_boot() -> str:
        """返回与 MCP instructions 相同的接管文书，并给出 boot_once。"""
        return _dump(surface.skstate_boot())

    @mcp.tool(name="skstate_skills_list")
    def skstate_skills_list(query: str = "", limit: int = 50) -> str:
        """列出技能名和简介。不返回完整规程。"""
        return _dump(surface.skstate_skills_list(query=query, limit=limit))

    @mcp.tool(name="skstate_skill_view")
    def skstate_skill_view(name: str) -> str:
        """读取一份技能的规程和可选的 state_schema。"""
        return _dump(surface.skstate_skill_view(name))

    @mcp.tool(name="skstate_run_start")
    def skstate_run_start(skill: str, task: str = "") -> str:
        """把技能绑定为不可变规程，并打开执行状态。task 存在 run 上，不写入 Σ。"""
        return _dump(surface.skstate_run_start(skill, task=task))

    @mcp.tool(name="skstate_context")
    def skstate_context(run_id: str = "") -> str:
        """只返回规程、当前状态和最新观察。"""
        return _dump(surface.skstate_context(run_id))

    @mcp.tool(name="skstate_step")
    def skstate_step(action: str, state_patch: dict[str, Any] | None = None, run_id: str = "") -> str:
        """校验状态补丁，合并后返回要执行的 action。拒绝的补丁不落盘。"""
        return _dump(surface.skstate_step(state_patch or {}, action, run_id))

    @mcp.tool(name="skstate_observe")
    def skstate_observe(observation: str, run_id: str = "") -> str:
        """用这一次的观察替换上一次。更早的观察不再返回。"""
        return _dump(surface.skstate_observe(observation, run_id))

    @mcp.tool(name="skstate_finish")
    def skstate_finish(summary: str = "", run_id: str = "") -> str:
        """结束 run。用户说「停」时调用。"""
        return _dump(surface.skstate_finish(summary, run_id))

    @mcp.tool(name="skstate_hooks")
    def skstate_hooks(
        action: str = "status",
        platform: str = "",
        project_dir: str = "",
        force: bool = False,
    ) -> str:
        """查看、安装或卸载 OpenCode 与 Codex 的会话钩子。"""
        return _dump(surface.skstate_hooks(action, platform, project_dir, force))

    @mcp.tool(name="skstate_hook_event")
    def skstate_hook_event(event: str, payload: dict[str, Any] | None = None) -> str:
        """登记 session_start、session_end 或 signal。"""
        return _dump(surface.skstate_hook_event(event, payload))

    @mcp.tool(name="skstate_status")
    def skstate_status() -> str:
        """返回数据目录、活动 run，以及 llm_api=false。"""
        return _dump(surface.skstate_status())

    @mcp.tool(name="skstate_audit")
    def skstate_audit(run_id: str = "", limit: int = 20) -> str:
        """读取有上限的动作日志。用户要求历史时才调用。"""
        return _dump(surface.skstate_audit(run_id, limit))

    @mcp.prompt(name="skstate_instrument")
    def skstate_instrument() -> str:
        """与 MCP instructions 相同的接管文书。"""
        return live_instrument()

    if len(set(TOOL_NAMES)) != len(TOOL_NAMES):
        raise RuntimeError("duplicate tool names")
    return mcp


def run_server(verbose: bool = False) -> None:
    """Start the takeover server on stdio. Logs go to stderr."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        stream=sys.stderr,
    )
    try:
        server = create_server()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    server.run(transport="stdio")
