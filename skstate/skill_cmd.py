"""``skstate skill new`` and ``skstate skill check`` for skill authors.

``new`` writes a template a host can already run. ``check`` prints what the
runtime will actually read — name, description, schema — and refuses to
pretend a schema is empty when the file uses YAML the subset parser cannot
read while PyYAML is unavailable.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from skstate.frontmatter import (
    FrontmatterError,
    find_unsupported_lines,
    parse_frontmatter,
    parse_frontmatter_strict,
    schema_from_frontmatter,
    schema_location,
    yaml_available,
)
from skstate.skills_index import iter_skill_files, load_skill

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*$")

SKILL_TEMPLATE = """---
name: {name}
description: 一句话说明这个技能什么时候用
metadata:
  skstate:
    state_schema:
      step: string
---

1. 何时改哪些字段：每一步只把当前进度写进 state 的 step 字段。
2. 动作由宿主执行：skstate_step 返回 action 后，用宿主自己的工具执行它，再 skstate_observe。
3. 结束时调用 skstate_finish。
"""


def create_skill(name: str, project_dir: str | Path, force: bool = False) -> Path:
    clean = (name or "").strip()
    if not NAME_RE.match(clean):
        raise ValueError("技能名只允许字母、数字和连字符")
    root = Path(project_dir).expanduser().resolve()
    target = root / "skills" / clean / "SKILL.md"
    if target.exists() and not force:
        raise FileExistsError(f"已存在：{target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(SKILL_TEMPLATE.format(name=clean), encoding="utf-8")
    return target


def check_skill_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    result: dict[str, Any] = {"path": str(path), "ok": True, "problems": []}
    if yaml_available():
        try:
            frontmatter, _body = parse_frontmatter_strict(text)
        except FrontmatterError as exc:
            where = f"第 {exc.line} 行：" if exc.line else ""
            result["ok"] = False
            result["problems"].append(f"{where}{exc}")
            return result
    else:
        bad = find_unsupported_lines(text)
        if bad:
            result["ok"] = False
            result["problems"] = [
                f"第 {line} 行：不支持的 YAML 结构（{label}）；装 PyYAML 或改写成子集"
                for line, label in bad
            ]
            return result
        frontmatter, _body = parse_frontmatter(text)
    result["name"] = str(frontmatter.get("name") or path.parent.name)
    result["description"] = str(frontmatter.get("description") or "").strip()
    result["schema"] = schema_from_frontmatter(frontmatter)
    result["schema_open"] = not bool(result["schema"])
    result["schema_location"] = schema_location(frontmatter)
    return result


def check_skills(name: str = "") -> list[dict[str, Any]]:
    if name:
        target = name.strip()
        direct = [
            path
            for path in iter_skill_files()
            if path.parent.name == target or path.parent.name.casefold() == target.casefold()
        ]
        if direct:
            return [check_skill_file(path) for path in direct]
        skill = load_skill(name)
        path = skill["path"]
        if path == "<builtin>":
            raise FileNotFoundError("scratch 是内置规程，没有技能文件")
        return [check_skill_file(Path(path))]
    return [check_skill_file(path) for path in iter_skill_files()]


def format_check(result: dict[str, Any]) -> str:
    lines = [f"技能文件：{result['path']}"]
    if not result["ok"]:
        lines.extend(f"  {problem}" for problem in result["problems"])
        lines.append("check 未通过。")
        return "\n".join(lines)
    lines.append(f"name：{result['name']}")
    lines.append(f"description：{result['description'] or '（空）'}")
    lines.append(f"schema：{json.dumps(result['schema'], ensure_ascii=False) if result['schema'] else '（空）'}")
    if result["schema_open"]:
        lines.append("schema 为空，运行时会把它当成开放对象。")
    if result["schema_location"] == "hermes":
        lines.append("schema 在 metadata.hermes.state_schema；请改到 metadata.skstate.state_schema。")
    lines.append("check 通过。")
    return "\n".join(lines)
