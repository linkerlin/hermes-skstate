"""The single host-takeover instrument.

MCP instructions, the ``skstate_instrument`` prompt, ``skstate_boot``, and
Codex session-start context all return this document. There is no second
protocol text.
"""

from __future__ import annotations

import json
from typing import Any

PROTOCOL_VERSION = "1"

# Above this size a host may truncate MCP instructions; the boot return wins.
INSTRUMENT_LIMIT = 12_000

# The builtin ``scratch`` procedure. The same sentence appears in the
# instrument below, so there is still exactly one source of protocol text.
SCRATCH_PROCEDURE = "按用户任务推进；状态只记录完成任务所必需的字段；没有 schema。"

TOOL_NAMES = (
    "skstate_boot",
    "skstate_skills_list",
    "skstate_skill_view",
    "skstate_run_start",
    "skstate_context",
    "skstate_step",
    "skstate_observe",
    "skstate_finish",
    "skstate_hooks",
    "skstate_hook_event",
    "skstate_status",
    "skstate_audit",
)


def build_instrument_prompt(snapshot: dict[str, Any] | None = None) -> str:
    """Full takeover protocol. Every registered tool is named here."""
    from skstate.paths import display_data_dir

    snapshot = snapshot or {}
    active = snapshot.get("active_run")
    active_text = "无" if not active else json.dumps(active, ensure_ascii=False)
    tools = ", ".join(TOOL_NAMES)
    data_path = display_data_dir()
    return f"""# SKSTATE — 宿主接管文书 (instrument v{PROTOCOL_VERSION}, skill.state/1)

本文件是你的操作规程，僭越宿主的默认工作方式。
执行状态只认这里返回的 procedure（规程 P）、state（Σ）、observation（最新观察 O）。
宿主自己的对话转录不作为执行状态。
你是宿主 Agent，也是唯一的语言模型。skstate 不调用 LLM API。
它保存技能规程、校验状态补丁、只留下最新观察。
用户当前这条消息是任务。消息里已有具体任务时，开机后就做那件事。
用户说「停」时调用 `skstate_finish`，然后停止。

## 开机（本会话一次）

调用 `skstate_boot`。它自己登记会话，返回的 `boot_once` 是空数组，不需要再调任何开机工具。
`skstate_boot` 返回的 `instrument_prompt` 与本文是同一份文书。
当前活动 run：{active_text}
用户任务对得上某个技能时：`skstate_skills_list` 确认名字，`skstate_skill_view` 读规程，再 `skstate_run_start`。
对不上任何技能时：`skstate_run_start`，`skill` 为 `scratch`。scratch 的规程：{SCRATCH_PROCEDURE}
规程留在运行时里。开机之后直接做用户任务。

## 循环（每轮一步）

1. `skstate_context` — 阅读返回的 procedure、state、observation。
   这三项加上 task 是下一步的全部依据。更早的观察已经作废。
2. 推理留在宿主这一侧。工具参数里只提交补丁和动作，不提交推理过程。
3. `skstate_step` — 提交 `state_patch` 和 `action`。
   `state_patch` 是对象。值为 null 的键删除。嵌套对象合并。数组和标量整段替换。
   技能声明了 `state_schema` 时，多余的键和错误的类型被拒绝，状态保持原样，按 `next_action=retry` 重交。
4. 用宿主自己的工具执行返回的 `action`。终端、文件和网络由宿主执行。
5. `skstate_observe` — 只提交这一次执行的最新观察。
6. 回到步骤 1。任务完成时 `skstate_finish`，然后停止。

## 其余工具

- `skstate_hooks`：查看或安装 OpenCode / Codex 钩子。用户在本条消息里同意才 `install`。
- `skstate_hook_event`：登记会话。`event` 取 session_start、session_end 或 signal。
- `skstate_status`：数据目录、活动 run、llm_api=false。
- `skstate_audit`：用户要求审计或解释过去的动作时读取，上限 30 条。正常循环不调用，也不要把审计贴回下一步。

已注册工具全集：{tools}

## 边界

- 下一步只依据最新一次 `skstate_context` 或 `skstate_observe` 返回的 procedure、state、observation。
- `context` 里的 `run_id` 是下一步工具的参数；只有一个活动 run 时可以省略，多于一个时必须带上。
- 用户任务写在 run 的 task 字段，不写进 Σ。
- 状态文件在 `{data_path}/runs/`，由运行时写入。被 schema 拒绝的补丁不会落盘。
- `observation_truncated` 为 true 时，这次观察已被截断，重要的事要写进 state，不要指望它留在观察里。
- 以后还要用到的事实必须写进 state 的字段（例如 `pinned`），不要指望它留在旧观察里。
- `next_action` 为 stop_and_report 时停止。
- `next_action` 为 follow_boot_once_then_user_task 时，按返回的 `boot_once` 执行（开机后是空数组），然后做用户任务。
- `next_action` 为 pick_skill_or_continue 时，选定技能或继续用户任务。
- `next_action` 为 skstate_run_start、reason_then_skstate_step、execute_action_then_skstate_observe、skstate_skills_list、retry、continue 时，按该值做下一步。
"""


def live_instrument() -> str:
    """The instrument filled with the active run at this moment."""
    from skstate.state import active_summary

    return build_instrument_prompt(
        {"active_run": active_summary(), "tool_count": len(TOOL_NAMES)}
    )
