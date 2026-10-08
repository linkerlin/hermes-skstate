"""Session-start hook. Stdout is the same instrument the MCP server injects.

stdin: optional JSON payload from the IDE.
stdout: JSON the host can splice into the session. Nothing else is printed.
"""

from __future__ import annotations

import json
import sys

from skstate.instrument import live_instrument
from skstate.journal import append_event


def build_stdout(payload: dict) -> dict:
    append_event("session_start", payload)
    text = live_instrument()
    return {
        "additionalContext": text,
        "hookSpecificOutput": {"additionalContext": text},
    }


def main() -> None:
    raw = sys.stdin.read()
    payload: dict = {}
    if raw.strip():
        try:
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                payload = loaded
        except json.JSONDecodeError:
            payload = {"raw": raw[:500]}
    json.dump(build_stdout(payload), sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
