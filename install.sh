#!/usr/bin/env bash
# install.sh — install skstate as a Hermes local plugin tool (idempotent).
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
PLUGIN="$HERMES_HOME/plugins/hermes_local_tools"
SKILL_DST="$HERMES_HOME/skills/devops/skstate-skill-runtime"

echo "[skstate] HERMES_HOME=$HERMES_HOME"

# 1. plugin dir + tool file
mkdir -p "$PLUGIN"
cp -f "$SRC_DIR/skstate_tool.py" "$PLUGIN/skstate_tool.py"
echo "[skstate] copied skstate_tool.py -> $PLUGIN/"

# 2. wire into plugin __init__.py (create scaffold if absent)
INIT="$PLUGIN/__init__.py"
if [ ! -f "$INIT" ]; then
  cat > "$INIT" <<'EOF'
"""hermes_local_tools — update-surviving native tools for Hermes."""
from __future__ import annotations

_TOOL_MODULES = []
for _m in list(_TOOL_MODULES):
    try:
        __import__(f"{__name__}.{_m}")
    except Exception as _e:
        print(f"[hermes_local_tools] WARNING: failed to import {_m}: {_e}")

_TOOLS = []

def register(ctx) -> None:
    from tools.registry import registry
    for name, toolset in _TOOLS:
        entry = registry.get_entry(name)
        if entry is None:
            continue
        ctx.register_tool(
            name=name, toolset=toolset, schema=entry.schema,
            handler=entry.handler, check_fn=entry.check_fn,
            is_async=entry.is_async, emoji=entry.emoji or "",
        )
EOF
  echo "[skstate] created plugin scaffold $INIT"
fi

if ! grep -q '"skstate_tool"' "$INIT"; then
  # add module to _TOOL_MODULES
  python3 - "$INIT" <<'PY'
import sys, re
p = sys.argv[1]
src = open(p).read()
if '"skstate_tool"' not in src:
    m = re.search(r'(_TOOL_MODULES\s*=\s*\[)(.*?)(\])', src, re.S)
    if m:
        src = src[:m.end(2)] + '\n    "skstate_tool",' + src[m.end(2):]
        open(p, "w").write(src)
        print("[skstate] added skstate_tool to _TOOL_MODULES")
    else:
        print("[skstate] WARNING: _TOOL_MODULES not found; add manually")
PY
fi

if ! grep -q '("skstate", "skstate")' "$INIT"; then
  python3 - "$INIT" <<'PY'
import sys, re
p = sys.argv[1]
src = open(p).read()
if '("skstate", "skstate")' not in src:
    m = re.search(r'(_TOOLS\s*=\s*\[)(.*?)(\])', src, re.S)
    if m:
        src = src[:m.end(2)] + '\n    ("skstate", "skstate"),' + src[m.end(2):]
        open(p, "w").write(src)
        print('[skstate] added ("skstate","skstate") to _TOOLS')
    else:
        print("[skstate] WARNING: _TOOLS not found; add manually")
PY
fi

# 3. skill (optional — skip silently if not present in repo)
if [ -d "$SRC_DIR/skill" ]; then
  mkdir -p "$SKILL_DST"
  cp -f "$SRC_DIR/skill/"* "$SKILL_DST/" 2>/dev/null || true
  echo "[skstate] skill installed -> $SKILL_DST"
fi

echo "[skstate] done. Restart the Hermes gateway, then verify:"
echo "  skstate action=status"
