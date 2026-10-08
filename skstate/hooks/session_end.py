"""Session-end hook. Records the event and prints an empty JSON object."""

from __future__ import annotations

import json
import sys

from skstate.journal import append_event


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
    append_event("session_end", payload)
    json.dump({}, sys.stdout)


if __name__ == "__main__":
    main()
