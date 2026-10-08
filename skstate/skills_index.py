"""Read SKILL.md files for the skstate runtime.

Roots are ``SKSTATE_SKILLS`` (``os.pathsep``-separated), ``<project>/skills``,
and ``<data_dir>/skills``. The Hermes checkout is not scanned.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from skstate.frontmatter import (
    parse_frontmatter,
    schema_from_frontmatter,
    split_frontmatter,
)
from skstate.instrument import SCRATCH_PROCEDURE
from skstate.paths import data_dir, project_dir

BUILTIN_SCRATCH = "scratch"


def scratch_skill() -> dict[str, Any]:
    """The builtin procedure used when no skill file matches the task."""
    return {
        "name": BUILTIN_SCRATCH,
        "description": "内置规程：没有技能时按用户任务推进。",
        "path": "<builtin>",
        "procedure": SCRATCH_PROCEDURE,
        "schema": {},
    }


def skill_roots() -> list[Path]:
    roots: list[Path] = []
    extra = os.environ.get("SKSTATE_SKILLS", "").strip()
    if extra:
        for part in extra.split(os.pathsep):
            if part.strip():
                roots.append(Path(part.strip()).expanduser())
    roots.append(project_dir() / "skills")
    roots.append(data_dir() / "skills")
    unique: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        try:
            resolved = root.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(root)
    return unique


def iter_skill_files() -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    for root in skill_roots():
        if not root.exists():
            continue
        for skill_md in root.rglob("SKILL.md"):
            if any(part in {"index-cache", "node_modules", ".git"} for part in skill_md.parts):
                continue
            try:
                resolved = skill_md.resolve()
            except OSError:
                continue
            if resolved in seen:
                continue
            seen.add(resolved)
            found.append(skill_md)
    return found


def _summary(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        frontmatter, body = parse_frontmatter(text)
    except ValueError:
        # One broken skill file must not break the whole listing.
        frontmatter, body = {}, (split_frontmatter(text) or ("", text, 0))[1]
    name = str(frontmatter.get("name") or path.parent.name)
    description = str(frontmatter.get("description") or "").strip()
    if not description:
        for line in body.splitlines():
            if line.strip():
                description = line.strip()[:240]
                break
    return {
        "name": name,
        "description": description[:400],
        "path": str(path),
        "has_state_schema": bool(schema_from_frontmatter(frontmatter)),
    }


def list_skills(query: str = "", limit: int = 50) -> list[dict[str, Any]]:
    needle = query.strip().casefold()
    rows = [_summary(path) for path in iter_skill_files()]
    if needle:
        rows = [
            row
            for row in rows
            if needle in row["name"].casefold() or needle in row["description"].casefold()
        ]
    rows.sort(key=lambda row: row["name"].casefold())
    return rows[: max(1, min(int(limit or 50), 200))]


def load_skill(name: str) -> dict[str, Any]:
    target = (name or "").strip().replace("\\", "/")
    if not target or ".." in target.split("/"):
        raise FileNotFoundError("技能名为空或不安全")
    files = iter_skill_files()
    matches = [
        path
        for path in files
        if path.parent.name == target or path.parent.name.casefold() == target.casefold()
    ]
    if not matches:
        lowered = target.casefold()
        for path in files:
            try:
                frontmatter, _body = parse_frontmatter(path.read_text(encoding="utf-8"))
            except ValueError:
                continue
            skill_name = str(frontmatter.get("name") or path.parent.name)
            if target in {skill_name, str(path)} or skill_name.casefold() == lowered:
                matches.append(path)
                break
    if not matches:
        if target.casefold() == BUILTIN_SCRATCH:
            return scratch_skill()
        raise FileNotFoundError(f"技能不存在：{name}")
    path = matches[0]
    frontmatter, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    return {
        "name": str(frontmatter.get("name") or path.parent.name),
        "description": str(frontmatter.get("description") or ""),
        "path": str(path),
        "procedure": body,
        "schema": schema_from_frontmatter(frontmatter),
    }
