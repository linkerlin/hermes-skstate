# AGENTS.md — Instructions for AI Coding Agents

You found this repo. It is an **AI-agent-native Hermes plugin**: a single-file
native tool (`skstate_tool.py`) implementing the SKILL.state runtime from
arXiv:2608.26263. Everything here is designed so an LLM agent can install,
verify, and drive it with minimal tokens.

## What this tool does

`skstate` executes long-horizon procedural skills as explicit state transitions
instead of append-only conversation. Each step:

1. Runtime builds prompt = (skill spec, current JSON state, latest observation).
2. Model returns `{"reasoning": "...", "state_update": {...}, "action": "..."}`.
3. Runtime validates `state_update` (must be a JSON object), merges with
   null-deletion semantics (`"key": null` removes the key), executes `action`.
4. The action outcome becomes the next step's observation. Reasoning is discarded.

## How to invoke (inside Hermes)

```
skstate action=run env=warehouse backend=mock
skstate action=run env=ctfbash backend=openrouter model=minimax/minimax-m3:free max_steps=22
skstate action=run env=warehouse backend=deepseek react=true     # ReAct baseline
skstate action=demo backend=deepseek horizons="6 10 16"          # token table
skstate action=status
```

Return shape: `{"ok":true,"done":...,"steps":...,"final_state":{...},
"avg_prompt_est_tokens":...,"cum_prompt_est_tokens":...,"steps_log":[...]}`.

Errors are structured: `{"ok":false,"err":"no-args"}`, unknown env/backend →
`{"error":"unknown env ..."}`. `avg_prompt_est_tokens` flat across horizons = the
O(1) property working; ReAct (`react=true`) grows linearly.

## Environments & backends

- `warehouse` — deterministic inventory sim (goal: shelves 0..5 ≥ 25, shared pool).
- `ctfbash` — sandboxed bash in a fresh temp dir; find + echo a `ctf*` token.
  Destructive host commands are refused by the runtime, not the model.
- Backends: `mock` (offline golden policy — always works), `deepseek`, `nvidia`,
  `openrouter` (env: `DEEPSEEK_API_KEY`, `NVIDIA_API_KEY`, `OPENROUTER_API_KEY`).

Verified live (see README table): `minimax/minimax-m3:free` and
`nvidia/nemotron-3-super-120b-a12b:free` on OpenRouter; `google/gemma-4-31b-it`
on NVIDIA NIM; `deepseek-chat` on DeepSeek. OpenRouter `:free` slugs are the
stable free path. NVIDIA NIM free tier stalls minutes at night — the retry
ladder absorbs it, but expect slow wall-clock.

## Install / wiring contract

`./install.sh` does the right thing idempotently:

1. Copies `skstate_tool.py` → `~/.hermes/plugins/hermes_local_tools/`.
2. Appends `"skstate_tool"` to `_TOOL_MODULES` and `("skstate", "skstate")` to
   `_TOOLS` in that plugin's `__init__.py` (creates a minimal plugin scaffold
   if absent).
3. Copies the `skstate-skill-runtime` skill into `~/.hermes/skills/devops/`.

Manual wiring = two edits in the plugin `__init__.py`:

```python
_TOOL_MODULES = [..., "skstate_tool"]          # module import fires registry.register
_TOOLS = [..., ("skstate", "skstate")]          # (tool name, toolset name)
```

Then restart the Hermes gateway (plugin discovery is process-load-time).

The tool file self-registers at import via `registry.register(...)` — FLAT schema
format (`{"name", "description", "parameters"}` at top level). Do NOT pre-wrap in
`{"type":"function","function":{...}}`; the registry adds that wrapper itself
(double-wrapping breaks dispatch).

## Key invariants (break these and the runtime breaks)

1. **O_t feed-forward**: `obs = action_outcome` at the loop tail. Never send a
   static handshake after step 1 — the model must see its own command results.
2. **State ownership**: patches pass `validate_patch` → `merge_state`; the model
   can never corrupt state (rollback-retry on invalid JSON, max 2 retries).
3. **Reasoning is discarded** every step — that is the O(1) prompt mechanism,
   not a bug. The model must commit durable facts into `state_update` in the
   same step it learns them, or they are gone.
4. **Transport**: retry ladder in `_completions` (429/5xx/transient retry ×4,
   4xx fail-fast) + `_MAXTOK` per backend (reasoning models null out if the
   budget is too small — their CoT eats the completion budget).

## Verification checklist for another agent

```bash
python3 -c "import ast; ast.parse(open('skstate_tool.py').read())"          # parse
python3 skstate_tool.py  # (module import w/ hermes paths) — or run:
python3 - <<'PY'
import importlib.util, sys
sys.path.insert(0, '/path/to/hermes-agent')   # provides tools.registry + hermes_constants
spec = importlib.util.spec_from_file_location("sk", "skstate_tool.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
r = m.act_run({"env":"warehouse","backend":"mock","max_steps":10})
assert r["done"] and r["steps"] == 6           # golden policy finishes in 6
assert "no-args" in m.skstate_handler({})      # validation
print("OK")
PY
```

Then one live call: `skstate action=run env=warehouse backend=openrouter
model=minimax/minimax-m3:free` → expect `done:true` in ≤8 steps.

## Privacy

No secrets, no personal paths, no emails in this repo. Keys live in env/`.env`
only. The code contains no home-directory paths (uses env-resolved Hermes home).
