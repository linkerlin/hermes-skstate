"""
skstate — SKILL.state runtime (arXiv 2608.26263): Scalable Long-Horizon Agent Skills

State-transition skill execution as alternative to append-only conversation:
each step builds the prompt as (P, Sigma_t, O_t) — skill spec, the CURRENT
structured state, latest observation — the model answers with a JSON
{reasoning, state_update, action}, and the runtime deterministically validates
+ merges the state patch (null => delete) then executes the action. Reasoning
is discarded every step, giving bounded O(1) prompt, O(T) cumulative tokens.

Actions:
  run     execute one skill (warehouse | ctfbash) on backend
          (deepseek | nvidia | openrouter | mock); run echo yields the loop
          narrative + done + cost summary.
  demo    WITH/WITHOUT measurement: same warehouse instance on the ReAct
          history baseline vs the SKILL.state loop across a horizon list.
  status  backend key presence + brief config summary.

Deterministic "mock" backend runs the whole runtime (validator + null-delete
merge + action/observe loop) with no network, for auditability.

Backends are OpenAI-compatible /chat/completions called through stdlib urllib.
Keys come from process env (DEEPSEEK_API_KEY / NVIDIA_API_KEY /
OPENROUTER_API_KEY), loaded by the Hermes gateway from .env.

Author: lesterppo
"""
from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

_CAP = 9000  # inline cap for tool responses
_LIVE = {
    "deepseek": "https://api.deepseek.com/chat/completions",
    "nvidia": "https://integrate.api.nvidia.com/v1/chat/completions",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
}
_MODEL = {
    "deepseek": "deepseek-chat",
    "nvidia": "meta/llama-3.1-70b-instruct",
    "openrouter": "deepseek/deepseek-chat:free",
}
# per-backend completion budget: reasoning models (kimi-k3, nemotron) burn the
# budget on CoT before content arrives; NVIDIA free tier is request-limited not
# token-billed, so give it headroom.
_MAXTOK = {"deepseek": 700, "nvidia": 3000, "openrouter": 900}
_BACKENDS = ("mock", "deepseek", "nvidia", "openrouter")
_ACTIONS = ("run", "demo", "status")


def _key(bk: str) -> Optional[str]:
    envmap = {"deepseek": "DEEPSEEK_API_KEY", "nvidia": "NVIDIA_API_KEY",
              "openrouter": "OPENROUTER_API_KEY"}
    return os.environ.get(envmap[bk])


def _model(bk: str, model: Optional[str]) -> str:
    m = (model or "").strip()
    return m or _MODEL[bk]


def _completions(bk: str, model: str, messages) -> str:
    key = _key(bk)
    if not key:
        raise RuntimeError(f"{bk}: no API key in env")
    body = json.dumps({"model": model, "messages": messages,
                       "temperature": 0.0, "max_tokens": _MAXTOK[bk]}).encode()
    # bounded retry ladder for transient failures: 429 (rate limit), 5xx,
    # RemoteDisconnected / timeout (NIM free tier drops long requests)
    last_err: Optional[Exception] = None
    for attempt in range(4):
        req = urllib.request.Request(
            _LIVE[bk], data=body,
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=200) as r:
                return json.loads(r.read().decode())["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                last_err = e
                time.sleep(3.0 * (attempt + 1))
                continue
            raise                      # 4xx (401/403/404/410) = config, fail fast
        except Exception as e:         # RemoteDisconnected, timeout, reset
            last_err = e
            time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"{bk}: transient failures after retries: {last_err}")


# ---------------------------------------------------------------------------
# State primitives (paper Sec 3.2)
# ---------------------------------------------------------------------------
def validate_patch(obj: Any) -> Optional[dict]:
    if not isinstance(obj, dict):
        return None
    try:
        return json.loads(json.dumps(obj))
    except (TypeError, ValueError):
        return None


def merge_state(base: dict, patch: Optional[dict]) -> dict:
    """x or-null: additive/overwrite + null=>delete; returns a new dict."""
    out = dict(base)
    for k, v in (patch or {}).items():
        if v is None:
            out.pop(k, None)
        else:
            out[k] = v
    return out


def first_json_obj(text: str) -> Optional[dict]:
    i = text.find("{")
    if i < 0:
        return None
    depth = in_str = esc = 0
    for j in range(i, len(text)):
        c = text[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[i:j + 1])
                    except json.JSONDecodeError:
                        return None
    return None


def parse_output(raw: str) -> Optional[tuple[str, Optional[dict], str]]:
    d = first_json_obj(raw or "")
    if not isinstance(d, dict):
        return None
    return (str(d.get("reasoning") or "")[:1400],
            validate_patch(d.get("state_update")),
            str(d.get("action") or "").strip())


# ---------------------------------------------------------------------------
# Environments
# ---------------------------------------------------------------------------
SYSTEM = ("You run a long-horizon procedural skill by keeping explicit state.\n"
          "Each step you see ONLY current state + latest observation. Commit\n"
          "durable facts to state_update as you learn them.\n"
          "Output ONE JSON object exactly (no fences/prose):\n"
          '{"reasoning":"2-4 sentences of within-step thought",\n'
          ' "state_update":{"key":"value","to_delete":null, ...},\n'
          ' "action":"one environment action string"}\n'
          "state_update may be {}. null value deletes a state key.\n"
          "Issue action \"halt\" once the goal is met.")


def warehouse_setup(seed=7, shelf_fill=10):
    w = {"stock": {}, "pool": 150, "n_ships": 0}
    rnd = random.Random(seed)
    for i in range(shelf_fill):
        w["stock"][i] = rnd.randint(4, 26)
    for i in range(shelf_fill, 200):
        if rnd.random() < 0.3:
            w["stock"][i] = rnd.randint(1, 9)
    return w


WH_SPEC = ("SKILL: Warehouse inventory. Raise stock of shelves 0..5 to >=25\n"
           "each, then halt. Draw from pool via 'store', replenish pool only\n"
           "if needed. ACTIONS: store <i> <q> | ship <i> <q> | move <s> <d> <q> | wait.")


def warehouse_done(st: dict, truth) -> bool:
    return all(truth["stock"].get(i, 0) >= 25 for i in range(6))


def ctf_setup(flag="ctfTHE7SECRET9"):
    # clean older ctfbash sandboxes so grep/find over /tmp can't collide with a
    # flag from a prior run — each live test sees only its own secret.
    for older in Path(tempfile.gettempdir()).glob("skctf_*"):
        try:
            shutil.rmtree(older)
        except OSError:
            pass
    cwd = tempfile.mkdtemp(prefix="skctf_")
    p = Path(cwd)
    (p / "a" / "b").mkdir(parents=True)
    (p / "a" / "b" / "flag.txt").write_text(flag)
    (p / "notes.md").write_text("unrelated notes")
    return cwd


CTF_SPEC = ("SKILL: sandboxed shell rooted at an absolute temp dir you can pwd.\n"
            "Search for a file whose content begins 'ctf'. When cat shows the\n"
            "token, echo it VERBATIM and complete, e.g. type the whole token\n"
            "exactly as printed. Track cwd/visited dirs in active_files so you\n"
            "don't re-walk; use absolute paths where helpful. Then 'halt'.\n"
            "ls/find/cat/grep allowed.")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def run_skill(env, backend, react, max_steps, seed, model, noisy=0):
    """One envelope: builds env truth + state, loops Algorithm 1. Returns dict."""
    system = [{"role": "system", "content": SYSTEM},
              {"role": "system", "content": "SPEC\n===\n" +
               (WH_SPEC if env == "warehouse" else CTF_SPEC)}]

    if env == "warehouse":
        truth = warehouse_setup(seed)
        state = {"pool": truth["pool"], "n_ships": 0}
        for i in range(6):
            state[f"s{i}"] = truth["stock"].get(i, 0)
        def _obs():
            return ("authoritative: " + " ".join(f"s{i}={truth['stock'].get(i,0)}"
                                                 for i in range(6))
                    + f" | pool={truth['pool']}")
        def _apply(a):
            toks = (a or "").split()
            if not toks:
                return "no-op"
            op = toks[0].lower()
            try:
                if op == "wait":
                    return "idle"
                if op == "halt":
                    return "halted"
                if op == "store":
                    i, q = int(toks[1]), int(toks[2])
                    if q > truth["pool"]:
                        return f"cannot store {q}: pool only {truth['pool']}"
                    truth["stock"][i] = truth["stock"].get(i, 0) + q
                    truth["pool"] -= q
                    return f"stored {q} on {i}; s{i}={truth['stock'][i]} pool={truth['pool']}"
                if op == "ship":
                    i, q = int(toks[1]), int(toks[2])
                    if truth["stock"].get(i, 0) < q:
                        return f"INSUFFICIENT s{i}={truth['stock'].get(i,0)}"
                    truth["stock"][i] -= q
                    truth["pool"] += q
                    truth["n_ships"] += q
                    return f"shipped {q} from {i}; s{i}={truth['stock'][i]} pool={truth['pool']}"
                if op == "move":
                    i, j, q = int(toks[1]), int(toks[2]), int(toks[3])
                    if truth["stock"].get(i, 0) < q:
                        return f"cannot move {q}: s{i}={truth['stock'].get(i,0)}"
                    truth["stock"][i] -= q
                    truth["stock"][j] = truth["stock"].get(j, 0) + q
                    return f"moved {q} {i}->{j}"
                return f"unknown op {op}"
            except (ValueError, IndexError):
                return f"malformed action '{a}'"
        def _done(st):
            return warehouse_done(st, truth)
    else:  # ctfbash
        cwd = ctf_setup()
        flag = "ctfTHE7SECRET9"
        state = {"hypotheses": [], "active_files": [], "token": None,
                 "cool_found": False}
        def _obs():
            n = len(list(Path(cwd).rglob("*")))
            return f"shell in {cwd}; {n} file(s). goal: echo the ctf* token, then halt."
        def _apply(a):
            a = (a or "").strip()
            low = a.lower()
            if not a:
                return "no-op"
            if low.startswith("rm -rf /") or ":(){" in low or ">/dev/sd" in low:
                return "REFUSED destructive host command"
            if a == "halt":
                return "HALTED"
            if a.startswith("echo "):
                if flag in a:
                    state["token"] = flag
                    state["cool_found"] = True
                    return f"flag matched: {flag}"
                return f"echo ok (no match for {a[5:]!r})"
            try:
                p = subprocess.run(a, shell=True, cwd=cwd, capture_output=True,
                                   text=True, timeout=15)
                return ((p.stdout or "") + (p.stderr or ""))[:2000] or "(no output)"
            except subprocess.TimeoutExpired:
                return "command timed out"
            except Exception as e:
                return f"shell error: {e}"
        def _done(st):
            return bool(st.get("cool_found") or st.get("token"))

    transcript = []            # react baseline accumulation
    total_prompt_chars = 0
    calls = 0
    reasoning_trace = []
    steps_log = []
    steps = 0
    outcome = ""
    halted = False
    t0 = time.time()
    rollbacks = 0
    # O_t : the latest observation. Step 1 = env handshake; afterwards it is the
    # previous action outcome (set before the loop tail), never the whole history.
    obs = _obs()  # from the env branch above (warehouse or ctfbash)

    for step in range(1, max_steps + 1):
        if _done(state) or halted:
            break
        if noisy:                       # paper Exp 2: unrelated telemetry clutter
            pad = "\n".join(f"[syslog] fan={40+(step+i)%13} load={(step+i)%9}.4"
                            for i in range(noisy))
            fed_obs = pad + "\n" + obs
        else:
            fed_obs = obs
        # obs carries the latest observation (step 1 = env handshake; then the
        # previous action outcome, set just before the loop tail below)
        if react:
            msgs = list(system) + list(transcript) + [{"role": "user", "content": fed_obs}]
        else:
            msgs = list(system) + [{"role": "user",
                                    "content": "CURRENT STATE:\n"
                                    + json.dumps(state, ensure_ascii=False)
                                    + "\n\nLATEST OBSERVATION:\n" + fed_obs}]
        total_prompt_chars += sum(len(m["content"]) for m in msgs)
        calls += 1

        # inference
        if backend == "mock":
            if env == "warehouse":
                # deterministic golden policy, mirroring world into state
                action = None
                patch = {}
                for i in range(6):
                    cur = truth["stock"].get(i, 0)
                    if cur < 25:
                        draw = min(25 - cur, truth["pool"], 25)
                        action = f"store {i} {draw}"
                        # represent postcondition so agent-state == world
                        nxt = cur + draw
                        patch = {f"s{i}": nxt}
                        break
                if action is None:
                    action = "halt"
                    patch = {}
                reasoning = f"mock: {action}"
            else:
                # scan tree, cat candidates; echo token when found
                action = "find . -type f"
                patch = {"hypotheses": ["tree scan"], "active_files": []}
                reasoning = "mock discover"
                if not state.get("scanned"):
                    action = "find . -type f -print"
                    patch = {"scanned": True,
                             "hypotheses": ["tree scan"]}
        else:
            raw = _completions(backend, _model(backend, model), msgs)
            parsed = parse_output(raw)
            while parsed is None and rollbacks < 2:
                rollbacks += 1
                # ask to re-emit pure JSON (rollback-retry, paper Sec 7)
                raw = _completions(
                    backend, _model(backend, model),
                    msgs + [{"role": "assistant", "content": raw},
                            {"role": "user",
                             "content": "Output was invalid JSON. Re-emit ONLY the "
                                        "contract JSON with state_update + action."}])
                parsed = parse_output(raw)
            if parsed is None:
                return {"ok": False, "err": "model returned invalid JSON after retries",
                        "step": step, "rollbacks": rollbacks,
                        "backend": backend, "env": env}
            reasoning, patch, action = parsed

        reasoning_trace.append(reasoning[:200])

        if action == "halt":
            state = merge_state(state, patch)
            halted = True
            outcome = "halted"
        else:
            outcome = _apply(action)
            state = merge_state(state, patch)

        if react:
            transcript.append(
                {"role": "assistant",
                 "content": json.dumps({"reasoning": reasoning, "action": action})})
            transcript.append({"role": "user", "content": outcome})
        # SKILL.state discards reasoning_trace per step (we only keep for demo)

        steps += 1
        steps_log.append({"a": action[:120], "o": outcome[:120]})
        obs = outcome  # the action result is the next turn's latest observation

    done_ok = _done(state)
    return {
        "ok": True, "env": env, "backend": backend, "react": react,
        "steps": steps, "max_steps": max_steps, "done": bool(done_ok),
        "halted": halted, "rollbacks": rollbacks,
        "final_state": state,
        "steps_log": steps_log[-16:],
        "n_prompt_calls": calls,
        "avg_prompt_chars": total_prompt_chars // max(1, calls),
        "avg_prompt_est_tokens": total_prompt_chars // max(1, calls) // 4,
        "cum_prompt_chars": total_prompt_chars,
        "cum_prompt_est_tokens": total_prompt_chars // 4,
        "elapsed_s": round(time.time() - t0, 2),
        "model": backend if backend == "mock" else _model(backend, model),
    }


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------
def act_run(a: dict) -> dict:
    env = (a.get("env") or "warehouse").strip().lower()
    if env not in ("warehouse", "ctfbash"):
        return {"error": f"unknown env {env!r} (warehouse|ctfbash)"}
    backend = (a.get("backend") or "mock").strip().lower()
    if backend not in _BACKENDS:
        return {"error": f"unknown backend {backend!r} ({','.join(_BACKENDS)})"}
    max_steps = max(1, int(a.get("max_steps", 12) or 12))
    if env == "ctfbash" and max_steps == 12:
        max_steps = 22   # discovery needs room even when the model re-explores
    seed = int(a.get("seed", 7) or 7)
    return run_skill(env, backend, bool(a.get("react")), max_steps,
                     seed, a.get("model"), int(a.get("noisy", 0) or 0))


def act_demo(a: dict) -> dict:
    """Replication of Table 1: same warehouse instance run under ReAct vs
    SKILL.state for a list of horizons, showing score + prompt + token."""
    backend = (a.get("backend") or "mock").strip().lower()
    if backend not in _BACKENDS:
        return {"error": f"unknown backend {backend!r}"}
    horizons = a.get("horizons")
    if horizons is None:
        horizons = [5, 8, 10]   # deterministic short demo set
    elif isinstance(horizons, str):
        horizons = [int(x) for x in str(horizons).replace(",", " ").split() if x.strip()]
    try:
        horizons = [int(h) for h in horizons]
    except (ValueError, TypeError):
        return {"error": "horizons must be ints/list"}
    env = (a.get("env") or "warehouse").strip().lower()
    seed = int(a.get("seed", 7) or 7)
    rows = []
    for h in horizons:
        r_react = run_skill(env, backend, True, h, seed, a.get("model"), 0)
        r_state = run_skill(env, backend, False, h, seed, a.get("model"), 0)
        rows.append({
            "horizon": h,
            "react": {"done": r_react["done"],
                      "avg_prompt_est_tokens": r_react["avg_prompt_est_tokens"],
                      "cum_est_tokens": r_react["cum_prompt_est_tokens"]},
            "skstate": {"done": r_state["done"],
                        "avg_prompt_est_tokens": r_state["avg_prompt_est_tokens"],
                        "cum_est_tokens": r_state["cum_prompt_est_tokens"]},
        })
    return {"ok": True, "backend": backend, "env": env, "seed": seed,
            "rows": rows, "note": "est tokens = chars//4 snapshot"}


def act_status(a: dict) -> dict:
    info = {
        "enabled": True,
        "backends": {b: bool(_key(b)) if b != "mock" else True for b in _BACKENDS},
        "any_live": any(_key(b) for b in ("deepseek", "nvidia", "openrouter")),
        "default_model": {b: m for b, m in _MODEL.items()},
        "note": "mock backend = deterministic golden policy (paper temp 0.0); " 
                "live backends use env API keys.",
    }
    return {"ok": True, **info}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
def skstate_handler(args: dict, **kw):
    if not args:
        return json.dumps({"ok": False, "err": "no-args"}, ensure_ascii=False)
    action = (args.get("action") or "run").strip().lower()
    if action not in _ACTIONS:
        return json.dumps({"ok": False, "err": "bad-action",
                           "msg": f"unknown action {action!r}"}, ensure_ascii=False)
    try:
        if action == "run":
            res = act_run(args)
        elif action == "demo":
            res = act_demo(args)
        else:
            res = act_status(args)
    except Exception as e:
        return json.dumps({"ok": False, "err": "handler-exception",
                           "msg": f"{type(e).__name__}: {e}"}, ensure_ascii=False)
    return json.dumps(res, ensure_ascii=False)


from tools.registry import registry

SKSTATE_SCHEMA: dict[str, Any] = {
    "name": "skstate",
    "description": "SKILL.state long-horizon agent-skill runtime (arXiv 2608.26263). "
                   "Replaces append-only conversation with an explicit state loop: "
                   "prompt = (skill spec, current state, latest observation); model "
                   "returns {reasoning, state_update, action}; runtime validates+merges "
                   "the patch and executes the action. run a warehouse or sandbox-shell "
                   "skill on a backend and read back done + cost; demo measures "
                   "ReAct-vs-state token savings across horizons.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string", "enum": list(_ACTIONS),
                "description": "run (default): execute a skill; demo: Table-1-style "
                               "with/without token+accuracy across horizons; "
                               "status: backend keys/config.",
            },
            "env": {
                "type": "string", "enum": ["warehouse", "ctfbash"],
                "description": "Skill environment. warehouse = deterministic "
                               "inventory (goal: shelves 0..5 to >=25, pool "
                               "conservation). ctfbash = sandboxed shell (find a "
                               "ctf* token file).",
            },
            "backend": {
                "type": "string", "enum": list(_BACKENDS),
                "description": "model backend: deepseek (DeepSeek API), nvidia "
                               "(NVIDIA NIM), openrouter, or mock (deterministic "
                               "golden policy, offline/auditable).",
            },
            "model": {"type": "string",
                      "description": "optional model override for the backend "
                                     "(default: backend-specific)."},
            "react": {
                "type": "boolean",
                "description": "run the ReAct (append-full-history) baseline "
                               "instead of the stateful loop, for comparison.",
            },
            "max_steps": {
                "type": "integer",
                "description": "max execution steps (default 12).",
            },
            "horizons": {
                "type": "string",
                "description": "demo only: comma/space list of horizons "
                               "(default '5 8 10').",
            },
            "seed": {"type": "integer",
                     "description": "deterministic seed for warehouse truth."},
            "noisy": {
                "type": "integer",
                "description": "(reserved) per-step distractor-event count for "
                               "noise-robustness probing.",
            },
        },
        "required": [],
    },
}

registry.register(
    name="skstate",
    toolset="skstate",
    schema=SKSTATE_SCHEMA,
    handler=lambda args, **kw: skstate_handler(args, **kw),
    check_fn=lambda: True,
    emoji="\U0001f9ca",  # jellyfish — stateful
    max_result_size_chars=40000,
)
