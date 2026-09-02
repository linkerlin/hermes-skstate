---
name: skstate-skill-runtime
description: Run/test the skstate SKILL.state Hermes skill runtime tool.
license: MIT
---

# skstate — SKILL.state skill runtime tool

Hermes-native tool in `hermes_local_tools` plugin (toolset `skstate`). Implements
arXiv 2608.26263: skill execution = explicit state transitions, not append-only
conversation. Each step the prompt is only (skill spec P, current struct state
Sigma_t, latest observation O_t). Model returns JSON
`{reasoning, state_update, action}`; runtime validates + merges null-deletion patch
(value null deletes the key — `merge_state`), executes the action, discards
reasoning. Result: bounded O(1) prompt, O(T) cumulative tokens, better noise and
state-recovery resilience.

## Actions

- `run` `env=warehouse|ctfbash` `backend=mock|deepseek|nvidia|openrouter`
  `[react, max_steps, seed, noisy]` — one execution loop. Returns
  ok/done/steps/final_state/avg+cum prompt token estimates and `steps_log`
  (last action+outcome pairs — very useful for debugging a model's behaviour).
  `react=true` runs the ReAct (append full transcript) baseline.
- `demo` — run the same env under state and react across `horizons`; side-by-side
  token-accuracy table (paper Table 1 analogue).
- `status` — which backends are keyed in env + defaults.

Envs:
- `warehouse`: deterministic Store/Ship/Move inventory over many shelves; goal is to
  raise shelves 0..5 all to >=25 using a shared pool (conservation).
- `ctfbash`: sandboxed bash in a fresh 0700 temp dir; find the file whose contents
  starts `ctf...`, echo it (env returns `flag matched`), then `halt`. Refuses
  destructive host commands.

`mock` = deterministic golden policy in-process (offline; exercises the whole
runtime, validator and merge). Live backends are OpenAI-compatible
`/chat/completions` via stdlib urllib — no third-party dependency.

## Multi-model verification (live, Sep 2026)

Proven working backends+models:
- `openrouter` + `minimax/minimax-m3:free` — warehouse done, 7 steps, avgP 215, ~2s/call (fastest stable path).
- `openrouter` + `nvidia/nemotron-3-super-120b-a12b:free` — done, 6 steps, avgP 212; 1 real rollback (JSON retry) fired live.
- `nvidia` + `google/gemma-4-31b-it` — warehouse done, 6 steps, avgP 212; CTF solved in 3 steps; react avgP 324 vs state 212.
- `deepseek` + `deepseek-chat` — done, 7 steps, avgP 213 (original live validation).

SKILL.state's flat ~212-215 token prompt holds on every working model vs react 324+ — architecture is model-agnostic.

Dead/blocked models (catalog drift, NOT tool bugs): all NIM `meta/llama-*` + `qwen` = 410 EOL; `mistral-large-2`, `nemotron-ultra-253b` = per-account 404; `deepseek-v4-flash-0731` NIM = read timeout; OR `glm-5.2:free` = upstream 429; `inkling:free` = 403 agentic-harness-only.

## Transport hardening (do not regress)

`_completions` has a 4-attempt retry ladder: 429/5xx backoff 3s*(n+1); transient RemoteDisconnected/timeout 2s*(n+1); 4xx fail-fast. `_MAXTOK` per backend: deepseek 700 / openrouter 900 / nvidia 3000 — max_tokens 700 starves reasoning models (kimi-k3 returns null content when CoT eats the budget). NIM free tier stalls minutes at night; worst case ~14 min/step — a per-step wall-clock deadline would harden further. OpenRouter used ~39/50 daily free calls in the matrix run.

## Verified behaviour (live DeepSeek, Sep 2026)

Warehouse horizons {6,10,16}: SKILL.state avg prompt FLAT ~213 tokens (7-step
solve) while ReAct averages ~326-361 and grows with the transcript. Both reach
done (state 7 steps vs react 6). At short horizons state is slightly slower per
LLM turn (larger structured-state blob per call) but token-total is lower and, at
long horizons (paper T>=50), savings + accuracy retention grow because the prompt
never accumulates. `noisy=15` syslog clutter per turn: stateful still solves.

ctfbash discovery shows the core invariant: in state mode the model must write
what it learns (hypotheses/active_files/working_dir) into `state_update` the same
step it learns it, else it re-explores — prior reasoning is gone. That is the
intended SKILL.state behaviour, not a bug.

## Pitfalls / lessons (from reliability audit)

- **Feed the action outcome forward as O_t.** In the state loop keep
  `obs = action_outcome` at the loop tail. An earlier version re-sent the static
  env handshake every step, so the model never saw its own command results and
  looped `ls -la`; ReAct (which replays the transcript) still solved CTF in 5
  steps while state mode floundered. The single most important runtime invariant.
- DeepSeek-chat may truncate an echoed token (drop its `ctf` prefix). Spec must
  say "echo the token verbatim"; ctfbash `max_steps` defaults to 22.
- NVIDIA NIM catalog drifts (410 EOL) and per-account 404s are common — probe
  `/v1/models` before assuming a model exists; never gate availability on one model.
- Sandbox cross-run bleed: older `skctf_*` dirs stay under /tmp, so a grep over
  /tmp can pick up a stale run's flag. `ctf_setup` rmtree's prior `skctf_*` each
  run so a live test only sees its own secret.
- Validation: empty/no-arg handler returns {"ok":false,"err":"no-args"}; unknown
  env/backend/action each rejected; malformed patches -> validate_patch None;
  null-deletion merge unit-verified.

## Files

- `~/.hermes/plugins/hermes_local_tools/skstate_tool.py` (single module; module-level
  `registry.register`).
- Wired in `__init__.py` `_TOOL_MODULES` + `_TOOLS` (`skstate`/`skstate`);
  plugin `plugin.yaml` >= v2.8.0.
- Public repo: https://github.com/lesterppo/hermes-skstate
