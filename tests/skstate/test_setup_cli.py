"""``skstate setup``, ``skstate status``, and the bare-serve hint."""

from __future__ import annotations

import json
import os
from pathlib import Path

from skstate.__main__ import main


def _project() -> Path:
    return Path(os.environ["SKSTATE_PROJECT"])


def test_setup_opencode_writes_mcp_entry_and_keeps_it(capsys):
    project = _project()
    (project / ".git").mkdir()
    main(["setup", "--platform", "opencode", "--project-dir", str(project)])
    result = json.loads(capsys.readouterr().out)
    assert result["platform"] == "opencode"
    assert result["mcp"]["changed"] is True

    config = json.loads((project / "opencode.json").read_text(encoding="utf-8"))
    entry = config["mcp"]["skstate"]
    assert entry["type"] == "local"
    assert entry["cwd"] == str(project.resolve())
    assert entry["environment"]["SKSTATE_PROJECT"] == str(project.resolve())
    assert entry["command"]
    assert (project / ".opencode" / "plugin" / "skstate.js").exists()
    assert (project / ".opencode" / "plugins" / "skstate.js").exists()

    gitignore = (project / ".gitignore").read_text(encoding="utf-8")
    assert "# skstate begin" in gitignore
    assert ".skstate/" in gitignore

    before = (project / "opencode.json").read_text(encoding="utf-8")
    main(["setup", "--platform", "opencode", "--project-dir", str(project)])
    again = json.loads(capsys.readouterr().out)
    assert again["mcp"]["kept_existing"] is True
    assert (project / "opencode.json").read_text(encoding="utf-8") == before
    assert (project / ".gitignore").read_text(encoding="utf-8").count("# skstate begin") == 1

    main(["setup", "--platform", "opencode", "--project-dir", str(project), "--force"])
    forced = json.loads(capsys.readouterr().out)
    assert forced["mcp"]["changed"] is True
    assert forced["mcp"]["kept_existing"] is False


def test_setup_opencode_uses_v2_layout_when_mcp_servers_exists(capsys):
    project = _project()
    (project / "opencode.json").write_text(
        json.dumps({"$schema": "https://opencode.ai/config.json", "mcp": {"servers": {}}}),
        encoding="utf-8",
    )
    main(["setup", "--platform", "opencode", "--project-dir", str(project)])
    result = json.loads(capsys.readouterr().out)
    assert result["mcp"]["layout"] == "mcp.servers"
    config = json.loads((project / "opencode.json").read_text(encoding="utf-8"))
    assert "skstate" in config["mcp"]["servers"]
    assert "skstate" not in config["mcp"]


def test_setup_codex_merges_config_and_keeps_user_flags(capsys):
    project = _project()
    codex_dir = project / ".codex"
    codex_dir.mkdir()
    (codex_dir / "config.toml").write_text("[features]\ncodex_hooks = true\n", encoding="utf-8")
    main(["setup", "--platform", "codex", "--project-dir", str(project)])
    result = json.loads(capsys.readouterr().out)
    assert result["platform"] == "codex"
    assert any("受信任" in note for note in result["notes"])

    text = (codex_dir / "config.toml").read_text(encoding="utf-8")
    assert "[mcp_servers.skstate]" in text
    assert f'SKSTATE_PROJECT = {json.dumps(str(project.resolve()), ensure_ascii=False)}' in text
    assert text.count("codex_hooks") == 1
    assert (codex_dir / "hooks.json").exists()

    before = text
    main(["setup", "--platform", "codex", "--project-dir", str(project)])
    again = json.loads(capsys.readouterr().out)
    assert again["mcp"]["kept_existing"] is True
    text = (codex_dir / "config.toml").read_text(encoding="utf-8")
    assert text == before
    assert text.count("[mcp_servers.skstate]") == 1

    main(["setup", "--platform", "codex", "--project-dir", str(project), "--uninstall"])
    json.loads(capsys.readouterr().out)
    final = (codex_dir / "config.toml").read_text(encoding="utf-8")
    assert "[mcp_servers.skstate]" not in final
    assert "# skstate mcp begin" not in final
    assert "codex_hooks = true" in final
    hooks_path = codex_dir / "hooks.json"
    hooks_text = hooks_path.read_text(encoding="utf-8") if hooks_path.exists() else ""
    assert "skstate.hooks" not in hooks_text


def test_uninstall_removes_what_setup_wrote(capsys):
    project = _project()
    main(["setup", "--platform", "opencode", "--project-dir", str(project)])
    capsys.readouterr()
    main(["setup", "--platform", "opencode", "--project-dir", str(project), "--uninstall"])
    result = json.loads(capsys.readouterr().out)
    assert result["mcp"]["changed"] is True
    config = json.loads((project / "opencode.json").read_text(encoding="utf-8"))
    assert "skstate" not in config.get("mcp", {})
    assert not (project / ".opencode" / "plugin" / "skstate.js").exists()
    assert not (project / ".opencode" / "plugins" / "skstate.js").exists()


def test_uninstall_keeps_a_hand_written_skstate_entry(capsys):
    project = _project()
    payload = {"mcp": {"skstate": {"type": "local", "command": ["skstate"]}}}
    (project / "opencode.json").write_text(json.dumps(payload), encoding="utf-8")
    main(["setup", "--platform", "opencode", "--project-dir", str(project), "--uninstall"])
    result = json.loads(capsys.readouterr().out)
    assert result["mcp"]["changed"] is False
    assert "保留" in result["mcp"]["note"]
    config = json.loads((project / "opencode.json").read_text(encoding="utf-8"))
    assert "skstate" in config["mcp"]


def test_status_prints_a_chinese_summary(capsys):
    project = _project()
    main(["setup", "--platform", "opencode", "--project-dir", str(project)])
    capsys.readouterr()

    from skstate import surface

    surface.skstate_run_start("scratch", task="记一件事")
    main(["status"])
    out = capsys.readouterr().out
    assert out.startswith("skstate 状态")
    assert f"项目根：{project.resolve()}" in out
    assert "数据目录：" in out
    assert "技能数量：0" in out
    assert "活动 run：" in out and "scratch" in out
    assert "OpenCode：MCP 已配置，钩子已装" in out
    assert "Codex：MCP 未配置，钩子未装" in out
    assert "文书字符数：" in out
    assert "建议的启动命令：" in out
    assert not out.lstrip().startswith("{")


def test_bare_skstate_only_hints_on_a_tty(capsys, monkeypatch):
    import skstate.mcp_server as mcp_server

    calls: list[bool] = []
    monkeypatch.setattr(mcp_server, "run_server", lambda verbose=False: calls.append(True))

    class _Tty:
        def isatty(self) -> bool:
            return True

    class _Pipe:
        def isatty(self) -> bool:
            return False

    monkeypatch.setattr("sys.stdin", _Tty())
    main([])
    err = capsys.readouterr().err
    assert "skstate status" in err
    assert "skstate setup" in err
    assert calls == [True]

    monkeypatch.setattr("sys.stdin", _Pipe())
    main([])
    assert capsys.readouterr().err == ""
    assert calls == [True, True]


def test_setup_requires_a_platform(capsys):
    try:
        main(["setup", "--project-dir", str(_project())])
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover - argparse always exits here
        raise AssertionError("setup without --platform must exit")
