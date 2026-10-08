"""SKILL.state store.

Each run keeps an immutable procedure, a schema-checked mutable state, and
only the latest observation. Older observations and reasoning are not
returned to the host. The user task sits on the run, outside Σ.

Omitting ``run_id`` resolves to the single active run. Two active runs mean
the caller must pass ``run_id``. Each run file is read, merged, and written
back under one lock, so concurrent sessions do not lose each other's merges.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from skstate.paths import data_dir

if os.name == "nt":
    import msvcrt
else:
    import fcntl

PROTOCOL = "skill.state/1"
MAX_PATCH_BYTES = 64_000
MAX_OBSERVATION_CHARS = 16_000
MAX_PROCEDURE_CHARS = 24_000
MAX_AUDIT = 30
_TYPE_NAMES = {
    "string": str,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


class StateError(ValueError):
    """A patch or observation the runtime refuses to commit."""


class AmbiguousRunError(StateError):
    """Several runs are active and the caller must pass ``run_id``."""


LOCK_TIMEOUT = 5.0
LOCK_POLL = 0.05

_THREAD_LOCKS: dict[str, "threading.Lock"] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


def _thread_lock(run_id: str) -> "threading.Lock":
    with _THREAD_LOCKS_GUARD:
        lock = _THREAD_LOCKS.get(run_id)
        if lock is None:
            lock = threading.Lock()
            _THREAD_LOCKS[run_id] = lock
        return lock


def runs_dir() -> Path:
    path = data_dir() / "runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_path(run_id: str) -> Path:
    if not run_id or not run_id.replace("-", "").isalnum():
        raise StateError("run id 不合法")
    return runs_dir() / f"{run_id}.json"


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def active_run_path() -> Path:
    return data_dir() / "active_run.txt"


@contextlib.contextmanager
def run_lock(run_id: str) -> Iterator[None]:
    """Serialise read-merge-write on one run file across processes."""
    thread_lock = _thread_lock(run_id)
    thread_lock.acquire()
    lock_path = runs_dir() / f"{run_id}.lock"
    handle = lock_path.open("a+")
    acquired = False
    deadline = time.monotonic() + LOCK_TIMEOUT
    try:
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise StateError(f"run 正被其他会话写入，稍后重试：{run_id}")
                time.sleep(LOCK_POLL)
        yield
    finally:
        if acquired:
            with contextlib.suppress(OSError):
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
        thread_lock.release()


def set_active_run(run_id: str | None) -> None:
    path = active_run_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not run_id:
        if path.exists():
            path.unlink()
        return
    path.write_text(run_id, encoding="utf-8")


def get_active_run_id() -> str | None:
    path = active_run_path()
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None


def active_summary() -> dict[str, Any] | None:
    run_id = get_active_run_id()
    if not run_id:
        return None
    try:
        run = load_run(run_id)
    except StateError:
        return {"id": run_id, "missing": True}
    return {
        "id": run["id"],
        "skill": run.get("skill") or "",
        "step": run.get("step") or 0,
        "status": run.get("status") or "active",
    }


def apply_patch(state: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Dictionary merge. JSON null deletes a key. Nested objects merge."""
    if not isinstance(state, dict):
        raise StateError("state 必须是对象")
    if not isinstance(patch, dict):
        raise StateError("state_patch 必须是对象")
    merged = copy.deepcopy(state)
    _merge(merged, patch)
    return merged


def _merge(base: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if not isinstance(key, str) or not key:
            raise StateError("state 的键必须是非空字符串")
        if value is None:
            base.pop(key, None)
            continue
        current = base.get(key)
        if isinstance(value, dict) and isinstance(current, dict):
            _merge(current, value)
            continue
        base[key] = copy.deepcopy(value)


def _expect_type(value: Any, expected: str) -> bool:
    if expected == "any":
        return True
    python_type = _TYPE_NAMES.get(expected)
    if python_type is None:
        raise StateError(f"schema 类型未知：{expected}")
    if expected == "number" and isinstance(value, bool):
        return False
    return isinstance(value, python_type)


def validate_state(state: dict[str, Any], schema: dict[str, Any] | None) -> None:
    if not schema:
        return
    if not isinstance(schema, dict):
        raise StateError("state schema 必须是对象")
    unknown = sorted(set(state) - set(schema))
    if unknown:
        raise StateError("未知的 state 键：" + ", ".join(unknown))
    for key, spec in schema.items():
        if key not in state:
            continue
        expected = spec if isinstance(spec, str) else ""
        if isinstance(spec, dict):
            expected = str(spec.get("type") or "any")
        if not expected:
            raise StateError(f"schema 里的 {key} 缺少 type")
        if not _expect_type(state[key], expected):
            raise StateError(f"{key} 必须是 {expected}")


def _public_procedure(procedure: str) -> dict[str, Any]:
    digest = hashlib.sha256(procedure.encode("utf-8")).hexdigest()
    if len(procedure) <= MAX_PROCEDURE_CHARS:
        return {"text": procedure, "sha256": digest, "truncated": False}
    return {
        "text": procedure[:MAX_PROCEDURE_CHARS],
        "sha256": digest,
        "truncated": True,
    }


def context_view(run: dict[str, Any]) -> dict[str, Any]:
    """The only execution context a host should condition on."""
    return {
        "protocol": PROTOCOL,
        "run_id": run["id"],
        "skill": run.get("skill") or "",
        "task": run.get("task") or "",
        "procedure": _public_procedure(str(run.get("procedure") or "")),
        "state": copy.deepcopy(run.get("state") or {}),
        "observation": run.get("observation"),
        "observation_truncated": bool(run.get("observation_truncated")),
        "step": run.get("step") or 0,
        "status": run.get("status") or "active",
    }


def create_run(
    *,
    skill: str,
    skill_path: str,
    procedure: str,
    schema: dict[str, Any] | None,
    task: str = "",
) -> dict[str, Any]:
    run_id = uuid.uuid4().hex[:12]
    schema = schema or {}
    state: dict[str, Any] = {}
    validate_state(state, schema)
    run = {
        "id": run_id,
        "skill": skill,
        "skill_path": skill_path,
        "procedure": procedure,
        "schema": schema,
        "task": task,
        "state": state,
        "observation": None,
        "observation_truncated": False,
        "status": "active",
        "step": 0,
        "audit": [],
        "created_at": _now(),
        "updated_at": _now(),
    }
    _atomic_write(_run_path(run_id), run)
    set_active_run(run_id)
    return run


def list_active_runs() -> list[dict[str, Any]]:
    """Every run file whose status is still ``active``."""
    directory = runs_dir()
    rows: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data.get("status") == "active":
            rows.append(data)
    return rows


def active_summaries() -> list[dict[str, Any]]:
    return [
        {
            "id": row.get("id"),
            "skill": row.get("skill") or "",
            "task": str(row.get("task") or "")[:80],
            "step": row.get("step") or 0,
            "status": row.get("status") or "active",
        }
        for row in list_active_runs()
    ]


def _resolve_run_id(run_id: str | None) -> str:
    """Explicit id wins. Otherwise exactly one active run may be implied."""
    explicit = (run_id or "").strip()
    if explicit:
        return explicit
    rows = list_active_runs()
    if len(rows) == 1:
        return str(rows[0].get("id") or "")
    if not rows:
        raise StateError("没有活动 run；先调用 skstate_run_start")
    options = "；".join(
        f"{row.get('id')}（技能 {row.get('skill') or 'scratch'}，task {str(row.get('task') or '')[:80]}）"
        for row in rows
    )
    raise AmbiguousRunError(f"有多个活动 run，重试时带上 run_id：{options}")


def load_run(run_id: str | None = None) -> dict[str, Any]:
    chosen = _resolve_run_id(run_id)
    if not chosen:
        raise StateError("没有活动 run；先调用 skstate_run_start")
    path = _run_path(chosen)
    if not path.exists():
        raise StateError(f"run 不存在：{chosen}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise StateError("run 文件损坏")
    return data


def save_run(run: dict[str, Any]) -> None:
    run["updated_at"] = _now()
    _atomic_write(_run_path(run["id"]), run)


def _audit(run: dict[str, Any], kind: str, **fields: Any) -> None:
    entry = {"step": run.get("step") or 0, "kind": kind, "ts": _now()}
    entry.update(fields)
    audit = list(run.get("audit") or [])
    audit.append(entry)
    run["audit"] = audit[-MAX_AUDIT:]


def commit_step(run_id: str | None, patch: Any, action: str) -> dict[str, Any]:
    if not isinstance(action, str) or not action.strip():
        raise StateError("action 必填")
    if isinstance(patch, str):
        if not patch.strip():
            patch = {}
        else:
            try:
                patch = json.loads(patch)
            except json.JSONDecodeError as exc:
                raise StateError(f"state_patch 不是合法 JSON：{exc}") from exc
    if patch is None:
        patch = {}
    encoded = json.dumps(patch, ensure_ascii=False)
    if len(encoded.encode("utf-8")) > MAX_PATCH_BYTES:
        raise StateError("state_patch 超过 64KB")
    chosen = _resolve_run_id(run_id)
    with run_lock(chosen):
        run = load_run(chosen)
        if run.get("status") != "active":
            raise StateError("run 已结束")
        proposed = apply_patch(run.get("state") or {}, patch)
        validate_state(proposed, run.get("schema") or {})
        run["state"] = proposed
        run["step"] = int(run.get("step") or 0) + 1
        _audit(
            run,
            "step",
            action=action.strip()[:500],
            patch_keys=sorted(patch) if isinstance(patch, dict) else [],
        )
        save_run(run)
    return run


def commit_observation(run_id: str | None, observation: str) -> dict[str, Any]:
    if not isinstance(observation, str) or not observation.strip():
        raise StateError("observation 必填")
    text = observation
    truncated = False
    if len(text) > MAX_OBSERVATION_CHARS:
        text = text[:MAX_OBSERVATION_CHARS]
        truncated = True
    chosen = _resolve_run_id(run_id)
    with run_lock(chosen):
        run = load_run(chosen)
        if run.get("status") != "active":
            raise StateError("run 已结束")
        run["observation"] = text
        run["observation_truncated"] = truncated
        _audit(run, "observe", observation_preview=text[:200], truncated=truncated)
        save_run(run)
    return run


def finish_run(run_id: str | None, summary: str = "") -> dict[str, Any]:
    chosen = _resolve_run_id(run_id)
    with run_lock(chosen):
        run = load_run(chosen)
        run["status"] = "finished"
        run["summary"] = (summary or "")[:2000]
        _audit(run, "finish", summary=run["summary"][:200])
        save_run(run)
    if get_active_run_id() == run["id"]:
        set_active_run(None)
    return run
