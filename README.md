# hermes-skstate

**SKILL.state long-horizon agent-skill runtime for [Hermes Agent](https://github.com/NousResearch/hermes-agent)** — a native Hermes tool implementing the state-transition execution architecture from [arXiv:2608.26263](https://arxiv.org/abs/2608.26263) (*SKILL.state: Scalable Long-Horizon Agent Skills*).

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org)
[![arXiv](https://img.shields.io/badge/arXiv-2608.26263-b31b1b.svg)](https://arxiv.org/abs/2608.26263)
[![Hermes Agent plugin](https://img.shields.io/badge/Hermes%20Agent-plugin-green.svg)](https://hermes-agent.nousresearch.com/docs)
![topics](https://img.shields.io/badge/topics-skill--state_%7C_execution--state_%7C_state--transition_%7C_agent--runtime-informational)

## What it does

Replaces append-only conversation with **explicit structured execution state**. At every step the model receives only:

```
A_t = (P, Σ_t, O_t)     skill spec + current state + latest observation
```

and returns a JSON triple:

```
(R_t, ΔΣ_t, a_t)        reasoning (discarded) + state patch + action
```

The runtime **deterministically validates** the patch, merges it with null-deletion semantics (`{"key": null}` deletes), executes the action, and feeds the action's outcome forward as the next observation. Reasoning is discarded every step.

**Result: bounded O(1) prompt, O(T) cumulative tokens, noise-resilient long-horizon execution.**

## Verified results (live LLM calls)

| Model | Backend | Warehouse | avg prompt (state) | avg prompt (ReAct) |
|---|---|---|---|---|
| `minimax/minimax-m3:free` | OpenRouter | done, 7 steps | **215 tok** | 326+ tok |
| `nvidia/nemotron-3-super-120b-a12b:free` | OpenRouter | done, 6 steps | **212 tok** | 324+ tok |
| `google/gemma-4-31b-it` | NVIDIA NIM | done, 6 steps | **212 tok** | 324 tok |
| `deepseek-chat` | DeepSeek | done, 7 steps | **213 tok** | 325 tok |

Flat prompt across horizons on every model — the architecture is model-agnostic. CTF sandbox: `gemma-4-31b-it` solved in 3 steps. JSON rollback-retry path proven live (1 rollback on nemotron-3-super).

## Tool API

| Action | Purpose |
|---|---|
| `run` | Execute one skill loop. `env`=`warehouse`\|`ctfbash`, `backend`=`mock`\|`deepseek`\|`nvidia`\|`openrouter`, optional `react`, `max_steps`, `seed`, `noisy`, `model`. |
| `demo` | Run the same env under state **and** ReAct across `horizons`; side-by-side token/accuracy table. |
| `status` | Which backends have keys, defaults. |

Environments:
- **warehouse** — deterministic Store/Ship/Move/Wait inventory domain (SkillExecBench Env 1 clone); goal: raise shelves 0..5 to ≥25 under pool conservation.
- **ctfbash** — sandboxed bash in a fresh temp dir (destructive host commands refused); find the `ctf*` token file, echo it verbatim, halt.

`mock` backend = deterministic golden policy, fully offline — exercises the whole runtime (validator, null-delete merge, action/observe loop) with zero network. The paper runs temperature 0; mock gives reproducible audits.

## Install

```bash
git clone https://github.com/lesterppo/hermes-skstate.git
cd hermes-skstate && ./install.sh
# restart Hermes gateway, then:
#   skstate action=status
```

`install.sh` copies `skstate_tool.py` into `~/.hermes/plugins/hermes_local_tools/` and appends the wiring (`_TOOL_MODULES` + `_TOOLS`) to that plugin's `__init__.py`. If you don't have the `hermes_local_tools` plugin yet, it creates the minimal scaffold. See `AGENTS.md` for the full registration contract.

## Configuration

API keys via environment (Hermes loads `.env` automatically):

```
DEEPSEEK_API_KEY      # api.deepseek.com
NVIDIA_API_KEY        # integrate.api.nvidia.com (NIM)
OPENROUTER_API_KEY    # openrouter.ai — use ":free" model slugs
```

No key? `backend=mock` works fully offline.

## Design notes

- **State ownership lives in the runtime, not the model.** Malformed model output can never corrupt Σ — invalid patches trigger the rollback-retry cycle (paper §7).
- **O_t feed-forward is the critical invariant.** The action's outcome string becomes the next prompt's latest observation. Feeding anything else (e.g. a static handshake) breaks state-mode execution — the model never sees its own command results.
- **Transport hardening.** 4-attempt retry ladder (429/5xx backoff, transient disconnect retry, 4xx fail-fast) + per-backend completion budgets (reasoning models need headroom or their CoT eats `max_tokens` and content comes back null).
- **Zero dependencies.** Stdlib `urllib` for completions; no SDK required.

## Skills

This repo ships with the Hermes skill `skstate-skill-runtime` (category devops) — install it via `./install.sh` as well; it documents the live-verified behavior, pitfalls, and the O_t feed-forward invariant for future sessions.

## License

MIT
