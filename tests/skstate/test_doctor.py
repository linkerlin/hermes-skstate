"""Doctor checks and the instrument size guard."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from skstate.__main__ import main


def _repo_root() -> str:
    return str(Path(__file__).resolve().parents[2])


def test_boot_section_stays_in_the_first_1500_chars():
    from skstate.instrument import live_instrument

    head = live_instrument()[:1500]
    assert "skstate_boot" in head
    assert "用户当前这条消息是任务" in head


def test_doctor_passes_with_the_repo_on_the_path(monkeypatch, capsys):
    monkeypatch.setenv("PYTHONPATH", _repo_root())
    main(["doctor"])
    out = capsys.readouterr().out
    assert "skstate 体检" in out
    assert "mcp 包" in out
    assert "钩子命令" in out
    assert "文书字符数" in out
    assert "结论：可以接入" in out


def test_doctor_fails_without_the_mcp_package(monkeypatch, capsys):
    import skstate.doctor as doctor

    class _Util:
        @staticmethod
        def find_spec(name: str):
            return None

    class _Importlib:
        util = _Util()

    monkeypatch.setattr(doctor, "importlib", _Importlib())
    monkeypatch.setenv("PYTHONPATH", _repo_root())
    with pytest.raises(SystemExit) as exc:
        main(["doctor"])
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "pip install -r requirements-skstate.txt" in out
    assert "结论：有 1 项需要处理" in out


def test_doctor_warns_when_project_and_cwd_differ(monkeypatch, capsys):
    monkeypatch.setenv("PYTHONPATH", _repo_root())
    home = Path(os.environ["SKSTATE_HOME"])
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SKSTATE_PROJECT", str(home))
    main(["doctor"])
    out = capsys.readouterr().out
    assert "与当前目录不一致" in out
    assert "结论：可以接入" in out


def test_status_advises_when_the_instrument_is_long(monkeypatch, capsys):
    import skstate.status_cmd as status_cmd

    monkeypatch.setattr(status_cmd, "live_instrument", lambda: "x" * 20_000)
    monkeypatch.setattr(status_cmd, "INSTRUMENT_LIMIT", 12_000)
    main(["status"])
    out = capsys.readouterr().out
    assert "文书字符数：20000" in out
    assert "以 skstate_boot 的返回为准" in out
