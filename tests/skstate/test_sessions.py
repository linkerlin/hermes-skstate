"""Two IDE sessions in one project: run resolution, locks, hook commands."""

from __future__ import annotations

import json
import os
from pathlib import Path

from skstate import surface
from skstate.hooks import common as hook_common
from skstate.hooks.setup import install_hooks, uninstall_hooks
from skstate.state import get_active_run_id


def test_omitted_run_id_needs_exactly_one_active_run():
    first = surface.skstate_run_start("scratch", task="任务 A " + "x" * 120)["context"]["run_id"]
    second = surface.skstate_run_start("scratch", task="任务 B")["context"]["run_id"]

    ambiguous = surface.skstate_step({"note": 1}, "写一点")
    assert ambiguous["ok"] is False
    assert ambiguous["next_action"] == "retry"
    assert first in ambiguous["error"]
    assert second in ambiguous["error"]
    assert "任务 A" in ambiguous["error"]
    assert "任务 B" in ambiguous["error"]
    assert "x" * 60 in ambiguous["error"]
    assert "x" * 90 not in ambiguous["error"]

    assert surface.skstate_context()["next_action"] == "retry"
    assert surface.skstate_audit()["next_action"] == "retry"
    assert surface.skstate_finish("done")["next_action"] == "retry"

    stepped_a = surface.skstate_step({"alpha": 1}, "写 A", run_id=first)
    stepped_b = surface.skstate_step({"beta": 2}, "写 B", run_id=second)
    assert stepped_a["context"]["state"] == {"alpha": 1}
    assert stepped_b["context"]["state"] == {"beta": 2}

    finished = surface.skstate_finish("done", run_id=first)
    assert finished["ok"] is True
    assert get_active_run_id() == second

    resolved = surface.skstate_step({"beta": 3}, "再写")
    assert resolved["context"]["run_id"] == second
    assert resolved["context"]["state"] == {"beta": 3}

    by_id = surface.skstate_context(first)
    assert by_id["ok"] is True
    assert by_id["context"]["status"] == "finished"
    assert surface.skstate_audit(first)["audit"]


def test_concurrent_steps_with_run_id_keep_every_key():
    import threading

    run_id = surface.skstate_run_start("scratch", task="并发")["context"]["run_id"]
    failures: list[str] = []

    def worker(key: str, base: int) -> None:
        for offset in range(5):
            result = surface.skstate_step({key: base + offset}, f"写 {key}", run_id=run_id)
            if not result["ok"]:
                failures.append(result.get("error", ""))

    threads = [
        threading.Thread(target=worker, args=("alpha", 1)),
        threading.Thread(target=worker, args=("beta", 100)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == []
    run_file = Path(os.environ["SKSTATE_HOME"]) / "runs" / f"{run_id}.json"
    data = json.loads(run_file.read_text(encoding="utf-8"))
    assert data["state"] == {"alpha": 5, "beta": 104}
    assert data["step"] == 10


def test_hook_commands_follow_the_installation_fixture(monkeypatch):
    prefix = Path(hook_common.sys.prefix).resolve()

    monkeypatch.setattr(
        hook_common.shutil, "which", lambda name: str(prefix / "Scripts" / "skstate.exe")
    )
    assert hook_common.hook_command_parts("session_start") == [
        str(prefix / "Scripts" / "skstate.exe"),
        "hook",
        "session-start",
    ]
    assert hook_common.hook_command_parts("session_end")[1:] == ["hook", "session-end"]

    monkeypatch.setattr(hook_common.shutil, "which", lambda name: "C:\\other\\skstate.exe")
    parts = hook_common.hook_command_parts("session_start")
    assert parts[0] == hook_common.sys.executable
    assert parts[1:] == ["-m", "skstate", "hook", "session-start"]

    monkeypatch.setattr(hook_common.shutil, "which", lambda name: None)
    assert hook_common.hook_command_parts("session_start")[1:] == [
        "-m",
        "skstate",
        "hook",
        "session-start",
    ]


def test_installed_hooks_use_the_subcommand_form():
    project = Path(os.environ["SKSTATE_PROJECT"])
    install_hooks("codex", project)
    hooks_path = project / ".codex" / "hooks.json"
    hooks_text = hooks_path.read_text(encoding="utf-8")
    assert "hook session-start" in hooks_text
    assert "hook session-end" in hooks_text

    install_hooks("opencode", project)
    plugin_text = (project / ".opencode" / "plugin" / "skstate.js").read_text(encoding="utf-8")
    assert '"hook"' in plugin_text
    assert "session-start" in plugin_text

    uninstall_hooks("codex", project)
    uninstall_hooks("opencode", project)
    remaining = hooks_path.read_text(encoding="utf-8") if hooks_path.exists() else ""
    assert "hook session" not in remaining
    assert not (project / ".opencode" / "plugin" / "skstate.js").exists()


def test_status_lists_every_active_run(capsys):
    from skstate.__main__ import main

    first = surface.skstate_run_start("scratch", task="任务 A")["context"]["run_id"]
    second = surface.skstate_run_start("scratch", task="任务 B")["context"]["run_id"]
    main(["status"])
    out = capsys.readouterr().out
    assert "活动 run：" in out
    assert first in out and second in out
    assert "任务 A" in out and "任务 B" in out
