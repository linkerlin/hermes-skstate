"""Deterministic MCP tool surface. No LLM client is imported here."""

from __future__ import annotations

from typing import Any

from skstate.instrument import TOOL_NAMES, live_instrument
from skstate.journal import append_event, tail_events
from skstate.paths import display_data_dir
from skstate.skills_index import list_skills, load_skill
from skstate.state import (
    AmbiguousRunError,
    StateError,
    active_summary,
    commit_observation,
    commit_step,
    context_view,
    create_run,
    finish_run,
    load_run,
)


def _ok(payload: dict[str, Any], next_action: str) -> dict[str, Any]:
    body = {"ok": True, "llm_api": False, "next_action": next_action}
    body.update(payload)
    return body


def _err(message: str, next_action: str = "retry") -> dict[str, Any]:
    return {"ok": False, "llm_api": False, "error": message, "next_action": next_action}


def _err_state(exc: StateError, default_next: str) -> dict[str, Any]:
    """A missing run points at run_start; ambiguous runs ask for a retry."""
    if isinstance(exc, AmbiguousRunError):
        return _err(str(exc), "retry")
    return _err(str(exc), default_next)


def snapshot() -> dict[str, Any]:
    return {"active_run": active_summary(), "tool_count": len(TOOL_NAMES)}


def skstate_boot() -> dict[str, Any]:
    # The runtime records the session itself. boot_once stays empty so the
    # host goes straight to the user's task.
    append_event("session_start", {"source": "skstate_boot"})
    return _ok(
        {
            "instrument_prompt": live_instrument(),
            "boot_once": [],
            "active_run": active_summary(),
            "tools": list(TOOL_NAMES),
        },
        "follow_boot_once_then_user_task",
    )


def skstate_skills_list(query: str = "", limit: int = 50) -> dict[str, Any]:
    rows = list_skills(query=query, limit=limit)
    return _ok({"skills": rows, "count": len(rows)}, "pick_skill_or_continue")


def skstate_skill_view(name: str) -> dict[str, Any]:
    try:
        skill = load_skill(name)
    except FileNotFoundError as exc:
        return _err(str(exc), "skstate_skills_list")
    except ValueError as exc:
        return _err(f"技能文件解析失败：{exc}；用 skstate skill check {name} 查看", "skstate_skills_list")
    procedure = skill["procedure"]
    return _ok(
        {
            "name": skill["name"],
            "description": skill["description"],
            "path": skill["path"],
            "schema": skill["schema"],
            "schema_open": not bool(skill["schema"]),
            "procedure": procedure[:24_000],
            "procedure_truncated": len(procedure) > 24_000,
        },
        "skstate_run_start",
    )


def skstate_run_start(skill: str, task: str = "") -> dict[str, Any]:
    try:
        loaded = load_skill(skill)
    except FileNotFoundError as exc:
        return _err(str(exc), "skstate_skills_list")
    except ValueError as exc:
        return _err(f"技能文件解析失败：{exc}；用 skstate skill check {skill} 查看", "skstate_skills_list")
    run = create_run(
        skill=loaded["name"],
        skill_path=loaded["path"],
        procedure=loaded["procedure"],
        schema=loaded["schema"],
        task=task.strip(),
    )
    return _ok({"context": context_view(run)}, "reason_then_skstate_step")


def skstate_context(run_id: str = "") -> dict[str, Any]:
    try:
        run = load_run(run_id or None)
    except StateError as exc:
        return _err_state(exc, "skstate_run_start")
    action = "stop_and_report" if run.get("status") != "active" else "reason_then_skstate_step"
    return _ok({"context": context_view(run)}, action)


def skstate_step(state_patch: Any = None, action: str = "", run_id: str = "") -> dict[str, Any]:
    try:
        run = commit_step(run_id or None, state_patch if state_patch is not None else {}, action)
    except StateError as exc:
        return _err(str(exc), "retry")
    return _ok(
        {
            "action": action.strip(),
            "context": context_view(run),
            "discard_reasoning": True,
        },
        "execute_action_then_skstate_observe",
    )


def skstate_observe(observation: str, run_id: str = "") -> dict[str, Any]:
    try:
        run = commit_observation(run_id or None, observation)
    except StateError as exc:
        return _err(str(exc), "retry")
    return _ok(
        {
            "context": context_view(run),
            "observation_truncated": bool(run.get("observation_truncated")),
        },
        "reason_then_skstate_step",
    )


def skstate_finish(summary: str = "", run_id: str = "") -> dict[str, Any]:
    try:
        run = finish_run(run_id or None, summary)
    except StateError as exc:
        return _err_state(exc, "stop_and_report")
    return _ok({"context": context_view(run), "summary": run.get("summary") or ""}, "stop_and_report")


def skstate_hooks(
    action: str = "status",
    platform: str = "",
    project_dir: str = "",
    force: bool = False,
) -> dict[str, Any]:
    from skstate.hooks.setup import hooks_status, install_hooks, uninstall_hooks

    if action == "status":
        return _ok(hooks_status(project_dir or "."), "continue")
    if platform not in {"opencode", "codex"}:
        return _err("platform must be opencode or codex")
    if not project_dir:
        return _err("project_dir is required for install and uninstall")
    try:
        if action == "install":
            result = install_hooks(platform, project_dir, force=force)
        elif action == "uninstall":
            result = uninstall_hooks(platform, project_dir)
        else:
            return _err("action must be status, install, or uninstall")
    except ValueError as exc:
        return _err(str(exc))
    return _ok(result, "continue")


def skstate_hook_event(event: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if event not in {"session_start", "session_end", "signal"}:
        return _err("event must be session_start, session_end, or signal")
    record = append_event(event, payload or {})
    return _ok({"recorded": record}, "continue")


def skstate_status() -> dict[str, Any]:
    return _ok(
        {
            "data_dir": display_data_dir(),
            "active_run": active_summary(),
            "tools": list(TOOL_NAMES),
            "recent_hooks": tail_events(5),
        },
        "continue",
    )


def skstate_audit(run_id: str = "", limit: int = 20) -> dict[str, Any]:
    try:
        run = load_run(run_id or None)
    except StateError as exc:
        return _err_state(exc, "stop_and_report")
    audit = list(run.get("audit") or [])[-max(1, min(int(limit or 20), 30)) :]
    return _ok(
        {
            "run_id": run["id"],
            "note": "审计轨迹。正常执行不要把它送回下一步。",
            "audit": audit,
        },
        "stop_and_report" if run.get("status") != "active" else "reason_then_skstate_step",
    )
