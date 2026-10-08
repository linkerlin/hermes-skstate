"""Skill authoring: templates, checks, the packaged example."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from skstate import surface
from skstate.examples import EXAMPLE_NAME
from skstate.skill_cmd import check_skill_file, create_skill, format_check


def _project() -> Path:
    return Path(os.environ["SKSTATE_PROJECT"])


def test_skill_new_template_round_trips(capsys):
    from skstate.__main__ import main

    project = _project()
    main(["skill", "new", "my-skill", "--project-dir", str(project)])
    out = capsys.readouterr().out
    assert "my-skill" in out

    target = project / "skills" / "my-skill" / "SKILL.md"
    assert target.exists()
    checked = check_skill_file(target)
    assert checked["ok"] is True
    assert checked["name"] == "my-skill"
    assert checked["schema"] == {"step": "string"}
    assert checked["schema_open"] is False

    viewed = surface.skstate_skill_view("my-skill")
    assert viewed["ok"] is True
    assert viewed["schema"] == {"step": "string"}

    with pytest.raises(SystemExit) as exc:
        main(["skill", "new", "my-skill", "--project-dir", str(project)])
    assert exc.value.code == 1
    with pytest.raises(ValueError, match="字母、数字"):
        create_skill("bad name", project)


def test_check_reports_unsupported_yaml_only_without_pyyaml(monkeypatch):
    project = _project()
    target = project / "skills" / "blocky" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text(
        "---\n"
        "name: blocky\n"
        "description: |\n"
        "  多行说明\n"
        "metadata:\n"
        "  skstate:\n"
        "    state_schema:\n"
        "      note: string\n"
        "---\n"
        "正文\n",
        encoding="utf-8",
    )

    checked = check_skill_file(target)
    assert checked["ok"] is True
    assert checked["schema"] == {"note": "string"}

    monkeypatch.setitem(sys.modules, "yaml", None)
    checked = check_skill_file(target)
    assert checked["ok"] is False
    assert "第 3 行" in checked["problems"][0]
    assert "块标量" in checked["problems"][0]
    assert "check 未通过" in format_check(checked)


def test_check_hints_when_schema_lives_under_hermes():
    project = _project()
    target = project / "skills" / "legacy" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text(
        "---\n"
        "name: legacy\n"
        "metadata:\n"
        "  hermes:\n"
        "    state_schema:\n"
        "      note: string\n"
        "---\n"
        "正文\n",
        encoding="utf-8",
    )
    checked = check_skill_file(target)
    assert checked["ok"] is True
    assert checked["schema"] == {"note": "string"}
    assert checked["schema_location"] == "hermes"
    assert "metadata.skstate.state_schema" in format_check(checked)


def test_setup_example_copies_shelf_demo(capsys):
    from skstate.__main__ import main

    project = _project()
    main(["setup", "--platform", "opencode", "--project-dir", str(project)])
    capsys.readouterr()
    assert not (project / "skills").exists()

    main(["setup", "--example", "--project-dir", str(project)])
    result = json.loads(capsys.readouterr().out)
    assert result["example"].endswith(f"shelf-demo{os.sep}SKILL.md")

    listed = surface.skstate_skills_list()
    assert listed["count"] == 1
    assert listed["skills"][0]["name"] == EXAMPLE_NAME

    checked = check_skill_file(project / "skills" / EXAMPLE_NAME / "SKILL.md")
    assert checked["ok"] is True
    assert checked["schema"] == {"shelf": "string", "qty": "number", "pinned": "string"}
    assert checked["schema_open"] is False

    viewed = surface.skstate_skill_view(EXAMPLE_NAME)
    assert viewed["schema"] == {"shelf": "string", "qty": "number", "pinned": "string"}
    assert viewed["schema_open"] is False

    again = check_skill_file(project / "skills" / EXAMPLE_NAME / "SKILL.md")
    assert again["schema"] == checked["schema"]


def test_skill_view_flags_an_open_schema():
    project = _project()
    target = project / "skills" / "open-note" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("---\nname: open-note\ndescription: 记一笔\n---\n记它\n", encoding="utf-8")
    viewed = surface.skstate_skill_view("open-note")
    assert viewed["ok"] is True
    assert viewed["schema"] == {}
    assert viewed["schema_open"] is True


def test_broken_yaml_fails_loud_but_list_survives(capsys):
    from skstate.__main__ import main

    project = _project()
    target = project / "skills" / "broken" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("---\nname: [unclosed\n---\n正文\n", encoding="utf-8")

    viewed = surface.skstate_skill_view("broken")
    assert viewed["ok"] is False
    assert "解析失败" in viewed["error"]
    assert "skill check" in viewed["error"]

    started = surface.skstate_run_start("broken", task="t")
    assert started["ok"] is False

    listed = surface.skstate_skills_list()
    assert listed["ok"] is True
    assert any(row["name"] == "broken" for row in listed["skills"])

    checked = check_skill_file(target)
    assert checked["ok"] is False

    with pytest.raises(SystemExit) as exc:
        main(["skill", "check", "broken"])
    assert exc.value.code == 1
    assert "解析失败" in capsys.readouterr().out


def test_instrument_carries_the_pinned_rule():
    from skstate.instrument import build_instrument_prompt, live_instrument

    sentence = "以后还要用到的事实必须写进 state 的字段（例如 `pinned`），不要指望它留在旧观察里。"
    assert sentence in live_instrument()
    root = Path(build_instrument_prompt.__code__.co_filename).parent
    assert sentence in (root / "instrument.py").read_text(encoding="utf-8")
    assert sentence not in (root / "hooks" / "common.py").read_text(encoding="utf-8")
    assert sentence not in (root / "examples.py").read_text(encoding="utf-8")
