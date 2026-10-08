"""skstate runtime: one instrument, state math, tools, and IDE hooks."""

from __future__ import annotations

import ast
import asyncio
import json
import os
from pathlib import Path

import pytest

from skstate.frontmatter import parse_frontmatter, schema_from_frontmatter
from skstate.hooks import session_start
from skstate.hooks.common import assert_project_dir
from skstate.hooks.setup import hooks_status, install_hooks, uninstall_hooks
from skstate.instrument import TOOL_NAMES, live_instrument
from skstate import surface
from skstate.state import apply_patch, validate_state

_BANNED_ROOTS = {
    "hermes_constants",
    "hermes_state",
    "hermes_cli",
    "tools",
    "agent",
    "run_agent",
    "openai",
    "anthropic",
    "cron",
}

_SKILL = """---
name: shelf-demo
description: shelf fixture
metadata:
  skstate:
    state_schema:
      shelf: string
      qty: number
---
Put the item on the shelf.
"""


def _write_skill(name: str, text: str) -> None:
    root = Path(os.environ["SKSTATE_PROJECT"]) / "skills" / name
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(text, encoding="utf-8")


def test_frontmatter_reads_skstate_schema():
    frontmatter, body = parse_frontmatter(_SKILL)
    assert body == "Put the item on the shelf."
    assert schema_from_frontmatter(frontmatter) == {"shelf": "string", "qty": "number"}


def test_patch_merges_and_null_deletes():
    merged = apply_patch(
        {"shelf": "a", "nested": {"qty": 1, "note": "keep"}, "gone": True},
        {"shelf": "b", "nested": {"qty": None, "bin": 3}, "gone": None},
    )
    assert merged == {"shelf": "b", "nested": {"note": "keep", "bin": 3}}


def test_schema_rejects_unknown_key_and_bool_as_number():
    schema = {"shelf": "string", "qty": "number"}
    validate_state({"shelf": "a", "qty": 2}, schema)
    with pytest.raises(ValueError, match="extra"):
        validate_state({"shelf": "a", "extra": 1}, schema)
    with pytest.raises(ValueError, match="qty"):
        validate_state({"qty": True}, schema)


def test_run_keeps_task_outside_state_and_only_latest_observation():
    _write_skill("shelf-demo", _SKILL)
    listed = surface.skstate_skills_list("shelf")
    assert listed["count"] == 1
    assert listed["next_action"] == "pick_skill_or_continue"

    started = surface.skstate_run_start("shelf-demo", task="ship item 7")
    assert started["ok"] is True
    assert started["llm_api"] is False
    assert started["next_action"] == "reason_then_skstate_step"
    run_id = started["context"]["run_id"]
    assert started["context"]["task"] == "ship item 7"
    assert started["context"]["state"] == {}
    assert started["context"]["observation"] is None
    assert "reasoning" not in started["context"]

    home = Path(os.environ["SKSTATE_HOME"])
    run_file = home / "runs" / f"{run_id}.json"
    assert run_file.exists()
    assert ".hermes" not in str(run_file)

    rejected = surface.skstate_step({"shelf": "s1", "extra": 1}, "store")
    assert rejected["ok"] is False
    assert rejected["next_action"] == "retry"
    assert surface.skstate_context()["context"]["state"] == {}
    assert json.loads(run_file.read_text(encoding="utf-8"))["state"] == {}

    not_object = surface.skstate_step(["nope"], "bad")
    assert not_object["ok"] is False
    assert json.loads(run_file.read_text(encoding="utf-8"))["state"] == {}

    stepped = surface.skstate_step({"shelf": "s1", "qty": 2}, "store item on s1")
    assert stepped["ok"] is True
    assert stepped["next_action"] == "execute_action_then_skstate_observe"
    assert stepped["context"]["state"] == {"shelf": "s1", "qty": 2}
    assert stepped["discard_reasoning"] is True

    surface.skstate_observe("stored on s1")
    replaced = surface.skstate_observe("customer took it")
    assert replaced["context"]["observation"] == "customer took it"
    assert "stored on s1" not in json.dumps(replaced["context"])

    deleted = surface.skstate_step({"qty": None}, "clear qty")
    assert deleted["context"]["state"] == {"shelf": "s1"}

    finished = surface.skstate_finish("done")
    assert finished["next_action"] == "stop_and_report"
    assert surface.skstate_context(run_id)["context"]["status"] == "finished"
    assert surface.skstate_context()["ok"] is False
    assert surface.skstate_audit(run_id)["audit"]


def test_legacy_hermes_metadata_schema_still_loads():
    _write_skill(
        "legacy-shelf",
        """---
name: legacy-shelf
metadata:
  hermes:
    state_schema:
      shelf: string
---
legacy procedure
""",
    )
    viewed = surface.skstate_skill_view("legacy-shelf")
    assert viewed["ok"] is True
    assert viewed["schema"] == {"shelf": "string"}
    assert viewed["next_action"] == "skstate_run_start"
    missing = surface.skstate_skill_view("../secret")
    assert missing["ok"] is False
    assert missing["next_action"] == "skstate_skills_list"


def test_open_schema_accepts_new_keys():
    _write_skill("open-note", "---\nname: open-note\n---\nnote it\n")
    started = surface.skstate_run_start("open-note", task="remember")
    stepped = surface.skstate_step({"note": "a"}, "write note")
    assert started["ok"] is True
    assert stepped["context"]["state"] == {"note": "a"}
    assert stepped["context"]["task"] == "remember"


def test_one_instrument_names_every_tool_and_is_the_mcp_instructions():
    text = live_instrument()
    for name in TOOL_NAMES:
        assert name in text
    assert "standing_instructions" not in Path(live_instrument.__code__.co_filename).read_text(encoding="utf-8")
    assert "逐项调用" not in text
    from skstate.instrument import SCRATCH_PROCEDURE

    assert SCRATCH_PROCEDURE in text
    assert "`skill` 为 `scratch`" in text
    boot = surface.skstate_boot()
    assert boot["instrument_prompt"] == live_instrument()
    assert boot["next_action"] == "follow_boot_once_then_user_task"
    assert boot["boot_once"] == []
    journal = (Path(os.environ["SKSTATE_HOME"]) / "hook_events.jsonl").read_text(encoding="utf-8")
    assert '"source": "skstate_boot"' in journal

    from skstate.mcp_server import create_server

    server = create_server()
    assert server.name == "skstate"
    assert server.instructions == live_instrument()
    tools = asyncio.run(server.list_tools())
    assert sorted(tool.name for tool in tools) == sorted(TOOL_NAMES)
    prompts = asyncio.run(server.list_prompts())
    assert any(prompt.name == "skstate_instrument" for prompt in prompts)
    rendered = asyncio.run(server.get_prompt("skstate_instrument"))
    payload = rendered.model_dump() if hasattr(rendered, "model_dump") else rendered
    assert live_instrument() in _flatten(payload)


def test_package_does_not_import_hermes_or_an_llm():
    root = Path(__file__).resolve().parents[2] / "skstate"
    for path in root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "get_hermes_home" not in source
        assert "HERMES_HOME" not in source
        assert "hermes_memory" not in source
        tree = ast.parse(source)
        for node in ast.walk(tree):
            modules: set[str] = set()
            if isinstance(node, ast.Import):
                modules = {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = {node.module}
            else:
                continue
            roots = {name.split(".")[0] for name in modules}
            overlap = roots & _BANNED_ROOTS
            assert not overlap, (path.name, overlap)


def test_hooks_install_under_the_project_and_uninstall_only_our_commands():
    project = Path(os.environ["SKSTATE_PROJECT"])
    (project / "AGENTS.md").write_text("# Project\n", encoding="utf-8")
    missing = project / "nope"
    with pytest.raises(ValueError, match="does not exist"):
        assert_project_dir(missing)
    with pytest.raises(ValueError, match="filesystem root"):
        assert_project_dir(Path(project.anchor))
    refused = surface.skstate_hooks("install", "opencode", str(missing))
    assert refused["ok"] is False

    installed = install_hooks("opencode", project)
    again = install_hooks("opencode", project)
    assert installed["platform"] == "opencode"
    assert again["skipped_existing"] is True
    plugin = project / ".opencode" / "plugin" / "skstate.js"
    other = project / ".opencode" / "plugins" / "skstate.js"
    assert plugin.exists() and other.exists()
    plugin_text = plugin.read_text(encoding="utf-8")
    assert "hook" in plugin_text
    assert "session-start" in plugin_text
    assert "skstate_context" in plugin_text
    assert "hermes-host" not in plugin_text
    assert "_skstate_managed: true" in plugin_text
    assert (project / "AGENTS.md").read_text(encoding="utf-8") == "# Project\n"

    codex = install_hooks("codex", project)
    hooks_path = project / ".codex" / "hooks.json"
    hooks_text = hooks_path.read_text(encoding="utf-8")
    assert "hook session-start" in hooks_text
    assert hooks_text.count("hook session-start") == 1
    assert "codex_hooks = true  # skstate" in (project / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert codex["platform"] == "codex"

    data = json.loads(hooks_text)
    data["hooks"]["Stop"].append({"type": "command", "command": "echo keep-me"})
    hooks_path.write_text(json.dumps(data), encoding="utf-8")

    status = hooks_status(project)
    assert status["opencode"]["installed"] is True
    assert status["codex"]["installed"] is True
    uninstall_hooks("opencode", project)
    uninstall_hooks("codex", project)
    assert hooks_status(project)["opencode"]["installed"] is False
    assert hooks_status(project)["codex"]["installed"] is False
    remaining = hooks_path.read_text(encoding="utf-8")
    assert "echo keep-me" in remaining
    assert "skstate.hooks" not in remaining
    assert "hook session" not in remaining
    assert (project / "AGENTS.md").read_text(encoding="utf-8") == "# Project\n"


def test_hooks_install_creates_no_agents_md():
    project = Path(os.environ["SKSTATE_PROJECT"])
    assert not (project / "AGENTS.md").exists()
    install_hooks("opencode", project)
    install_hooks("codex", project)
    assert not (project / "AGENTS.md").exists()
    uninstall_hooks("opencode", project)
    uninstall_hooks("codex", project)
    assert "codex_hooks = true  # skstate" not in (project / ".codex" / "config.toml").read_text(encoding="utf-8")


def test_user_codex_feature_flag_is_left_in_place():
    project = Path(os.environ["SKSTATE_PROJECT"])
    codex_dir = project / ".codex"
    codex_dir.mkdir()
    (codex_dir / "config.toml").write_text("[features]\ncodex_hooks = true\n", encoding="utf-8")
    install_hooks("codex", project)
    text = (codex_dir / "config.toml").read_text(encoding="utf-8")
    assert text.count("codex_hooks") == 1
    assert "# skstate" not in text
    uninstall_hooks("codex", project)
    assert "codex_hooks = true" in (codex_dir / "config.toml").read_text(encoding="utf-8")


def test_session_start_emits_the_instrument():
    payload = session_start.build_stdout({"session_id": "s1"})
    assert payload["additionalContext"] == live_instrument()
    assert payload["hookSpecificOutput"]["additionalContext"] == payload["additionalContext"]
    for name in TOOL_NAMES:
        assert name in payload["additionalContext"]
    journal = Path(os.environ["SKSTATE_HOME"]) / "hook_events.jsonl"
    assert "session_start" in journal.read_text(encoding="utf-8")


def test_hooks_help_exits_clean():
    from skstate.__main__ import main

    with pytest.raises(SystemExit) as exc:
        main(["hooks", "--help"])
    assert exc.value.code == 0


def test_scratch_builtin_runs_without_any_skill():
    from skstate.instrument import SCRATCH_PROCEDURE

    listed = surface.skstate_skills_list()
    assert listed["count"] == 0

    viewed = surface.skstate_skill_view("scratch")
    assert viewed["ok"] is True
    assert viewed["procedure"] == SCRATCH_PROCEDURE

    started = surface.skstate_run_start("scratch", task="记一件事")
    assert started["ok"] is True
    context = started["context"]
    assert context["skill"] == "scratch"
    assert context["state"] == {}
    assert context["task"] == "记一件事"
    assert "记一件事" not in json.dumps(context["state"])
    assert context["procedure"]["text"] == SCRATCH_PROCEDURE
    assert context["procedure"]["truncated"] is False

    stepped = surface.skstate_step({"note": "小事"}, "记下来")
    assert stepped["ok"] is True
    assert stepped["context"]["state"] == {"note": "小事"}


def test_observation_truncation_is_visible():
    surface.skstate_run_start("scratch", task="记一件事")
    long_text = "很长的观察" * 5000
    observed = surface.skstate_observe(long_text)
    assert observed["ok"] is True
    assert observed["observation_truncated"] is True
    assert observed["context"]["observation_truncated"] is True
    assert len(observed["context"]["observation"]) == 16000
    surfaced = surface.skstate_context()["context"]
    assert surfaced["observation_truncated"] is True

    short = surface.skstate_observe("短观察")
    assert short["observation_truncated"] is False
    assert short["context"]["observation_truncated"] is False


def test_state_errors_are_chinese_and_keep_field_names():
    _write_skill("shelf-cn", _SKILL)
    started = surface.skstate_run_start("shelf-cn", task="t")
    assert started["ok"] is True

    rejected = surface.skstate_step({"shelf": "a", "extra": 1}, "store")
    assert rejected["ok"] is False
    assert "extra" in rejected["error"]
    assert "未知的 state 键" in rejected["error"]

    wrong = surface.skstate_step({"qty": True}, "store")
    assert wrong["ok"] is False
    assert "qty" in wrong["error"]
    assert "必须是" in wrong["error"]

    no_action = surface.skstate_step({"shelf": "a"}, "")
    assert no_action["ok"] is False
    assert "action" in no_action["error"]


def _flatten(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "\n".join(_flatten(item) for item in value.values())
    if isinstance(value, list):
        return "\n".join(_flatten(item) for item in value)
    return ""
