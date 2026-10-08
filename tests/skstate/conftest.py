"""Keep skstate tests off the real home directory and the repo checkout."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_skstate(tmp_path, monkeypatch):
    home = tmp_path / "skstate-home"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("SKSTATE_HOME", str(home))
    monkeypatch.setenv("SKSTATE_PROJECT", str(project))
    monkeypatch.delenv("SKSTATE_SKILLS", raising=False)
    monkeypatch.chdir(project)
    return home, project
