"""The package example skill: ``shelf-demo``.

``skstate setup --example`` copies it to ``<project>/skills/shelf-demo/SKILL.md``.
The ``pinned`` field demonstrates the boundary rule from the instrument:
facts you will need again go into state, never into a kept observation.
"""

from __future__ import annotations

from pathlib import Path

EXAMPLE_NAME = "shelf-demo"

SHELF_DEMO_SKILL = """---
name: shelf-demo
description: 示例技能——把货品放上货架，并把以后还要用到的事实写进 state。
metadata:
  skstate:
    state_schema:
      shelf: string
      qty: number
      pinned: string
---

# 货架示例

1. 何时改哪些字段：shelf 记货架位置，qty 记数量，pinned 记以后还要用到的事实。
2. 动作由宿主执行：skstate_step 返回 action 后，用宿主自己的工具执行它，再 skstate_observe。
3. 结束时调用 skstate_finish。

pinned 字段演示一条边界：观察只有最新一条，旧观察会被替换。
以后还要用到的事实写进 state 的字段，不要指望它留在旧观察里。
"""


def copy_example(project_dir: str | Path, force: bool = False) -> Path:
    root = Path(project_dir).expanduser().resolve()
    target = root / "skills" / EXAMPLE_NAME / "SKILL.md"
    if target.exists() and not force:
        raise FileExistsError(f"已存在：{target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(SHELF_DEMO_SKILL, encoding="utf-8")
    return target
