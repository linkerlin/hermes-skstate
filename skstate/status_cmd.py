"""``skstate status``: a human-readable Chinese summary.

The MCP tool ``skstate_status`` keeps returning JSON. This module builds the
terminal view: project root, data dir, skill count, active run, whether each
IDE is wired up, instrument size, and the launch command to paste.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from skstate.hooks.setup import hooks_status
from skstate.instrument import INSTRUMENT_LIMIT, TOOL_NAMES, live_instrument
from skstate.mcp_config import codex_mcp_installed, opencode_mcp_installed, resolve_command
from skstate.paths import display_data_dir, project_dir
from skstate.skills_index import list_skills
from skstate.state import active_summaries


def status_report() -> dict[str, Any]:
    project = project_dir()
    hooks = hooks_status(project)
    data_path = Path(display_data_dir())
    runs = active_summaries() if data_path.exists() else []
    instrument = live_instrument()
    return {
        "project_dir": str(project),
        "data_dir": display_data_dir(),
        "skills": len(list_skills()),
        "active_runs": runs,
        "opencode": {
            "mcp": opencode_mcp_installed(project),
            "hooks": bool(hooks["opencode"]["installed"]),
        },
        "codex": {
            "mcp": codex_mcp_installed(project),
            "hooks": bool(hooks["codex"]["installed"]),
        },
        "instrument_chars": len(instrument),
        "tool_count": len(TOOL_NAMES),
        "launch_command": " ".join(resolve_command()),
    }


def _platform_text(flags: dict[str, bool]) -> str:
    parts = []
    parts.append("MCP 已配置" if flags["mcp"] else "MCP 未配置")
    parts.append("钩子已装" if flags["hooks"] else "钩子未装")
    return "，".join(parts)


def format_status(report: dict[str, Any]) -> str:
    runs = report.get("active_runs") or []
    if not runs:
        run_lines = ["活动 run：无"]
    else:
        run_lines = ["活动 run："]
        for run in runs:
            skill = run.get("skill") or "scratch"
            task = run.get("task") or ""
            run_lines.append(
                f"  - {run.get('id')}（技能 {skill}，第 {run.get('step') or 0} 步，task {task}）"
            )
    tail = []
    if report["instrument_chars"] > INSTRUMENT_LIMIT:
        tail.append("文书较长；若宿主截断 instructions，以 skstate_boot 的返回为准。")
    return "\n".join(
        [
            "skstate 状态",
            f"项目根：{report['project_dir']}",
            f"数据目录：{report['data_dir']}",
            f"技能数量：{report['skills']}",
            *run_lines,
            f"OpenCode：{_platform_text(report['opencode'])}",
            f"Codex：{_platform_text(report['codex'])}",
            f"文书字符数：{report['instrument_chars']}",
            f"建议的启动命令：{report['launch_command']}",
            *tail,
        ]
    )
