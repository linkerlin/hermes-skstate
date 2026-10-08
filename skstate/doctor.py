"""``skstate doctor``: is this install ready to wire into an IDE?

Read-only checks: the MCP package, the data dir, project/cwd consistency,
skill count, whether the hook command can actually run here, and the size of
the instrument. Exit code 1 when a check fails.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from typing import Any

from skstate.frontmatter import yaml_available
from skstate.hooks.common import hook_command_parts
from skstate.instrument import INSTRUMENT_LIMIT, live_instrument
from skstate.paths import data_dir, display_data_dir, project_dir
from skstate.skills_index import list_skills

_TRUNCATION_ADVICE = "若宿主截断 instructions，以 skstate_boot 的返回为准"


def _probe_hook_command(parts: list[str]) -> tuple[bool, str]:
    if parts[1:3] == ["-m", "skstate"]:
        command = [parts[0], "-c", "import skstate"]
    else:
        command = [parts[0], "status"]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=20,
            cwd=str(project_dir()),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if completed.returncode == 0:
        return True, " ".join(command)
    return False, (completed.stderr or completed.stdout or "").strip()[-200:]


def doctor_report() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    mcp_ok = importlib.util.find_spec("mcp") is not None
    checks.append(
        {
            "name": "mcp 包",
            "ok": mcp_ok,
            "detail": "可导入" if mcp_ok else "pip install -r requirements-skstate.txt",
        }
    )

    yaml_ok = yaml_available()
    checks.append(
        {
            "name": "PyYAML",
            "ok": True,
            "warning": not yaml_ok,
            "detail": "可导入，frontmatter 按完整 YAML 读"
            if yaml_ok
            else "不可导入，frontmatter 用内置子集",
        }
    )

    try:
        directory = data_dir()
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".doctor-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        checks.append({"name": "数据目录", "ok": True, "detail": f"{display_data_dir()}（可写）"})
    except OSError as exc:
        checks.append({"name": "数据目录", "ok": False, "detail": f"{display_data_dir()}（不可写：{exc}）"})

    project = project_dir()
    cwd = Path.cwd().resolve()
    consistent = project == cwd
    checks.append(
        {
            "name": "SKSTATE_PROJECT",
            "ok": True,
            "warning": not consistent,
            "detail": f"与当前目录一致（{project}）"
            if consistent
            else f"与当前目录不一致：SKSTATE_PROJECT={project}，cwd={cwd}",
        }
    )

    checks.append({"name": "技能数量", "ok": True, "detail": str(len(list_skills()))})

    parts = hook_command_parts("session_start")
    probe_ok, probe_detail = _probe_hook_command(parts)
    checks.append(
        {
            "name": "钩子命令",
            "ok": probe_ok,
            "detail": f"{' '.join(parts)}：{'可以运行' if probe_ok else probe_detail}",
        }
    )

    instrument = live_instrument()
    size_ok = len(instrument) <= INSTRUMENT_LIMIT
    detail = f"{len(instrument)} 字符"
    if not size_ok:
        detail += f"；{_TRUNCATION_ADVICE}"
    checks.append({"name": "文书字符数", "ok": True, "warning": not size_ok, "detail": detail})

    failures = [check for check in checks if not check["ok"]]
    return {
        "ok": not failures,
        "checks": checks,
        "failures": len(failures),
    }


def format_doctor(report: dict[str, Any]) -> str:
    lines = ["skstate 体检"]
    for check in report["checks"]:
        if not check["ok"]:
            mark = "[✗]"
        elif check.get("warning"):
            mark = "[!]"
        else:
            mark = "[✓]"
        lines.append(f"{mark} {check['name']}：{check['detail']}")
    if report["ok"]:
        warnings = sum(1 for check in report["checks"] if check.get("warning"))
        lines.append(f"结论：可以接入。{f'（{warnings} 项提醒）' if warnings else ''}")
    else:
        lines.append(f"结论：有 {report['failures']} 项需要处理。")
    return "\n".join(lines)
