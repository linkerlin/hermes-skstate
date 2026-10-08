"""Data and project paths for the skstate runtime.

State lives under ``SKSTATE_HOME`` when that variable is set, otherwise
``<project>/.skstate``. The project is ``SKSTATE_PROJECT`` or the process
working directory. Nothing here reads a Hermes home directory.
"""

from __future__ import annotations

import os
from pathlib import Path


def project_dir() -> Path:
    raw = os.environ.get("SKSTATE_PROJECT", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.cwd().resolve()


def data_dir() -> Path:
    raw = os.environ.get("SKSTATE_HOME", "").strip()
    path = Path(raw).expanduser() if raw else project_dir() / ".skstate"
    return path


def display_data_dir() -> str:
    raw = os.environ.get("SKSTATE_HOME", "").strip()
    if raw:
        return str(Path(raw).expanduser())
    return str(project_dir() / ".skstate")
