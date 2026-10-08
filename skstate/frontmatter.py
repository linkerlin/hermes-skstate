"""A small nested-YAML subset for SKILL.md frontmatter.

Supports mappings, indentation, scalars, and simple lists. When PyYAML is
importable the runtime reads frontmatter with it, so skills may use the full
YAML grammar. Without PyYAML, skills must stay inside this subset; the
``skstate skill check`` command reports the exact lines that fall outside it
(block scalars, anchors, flow collections) instead of silently dropping the
schema.
"""

from __future__ import annotations

import re
from typing import Any


class FrontmatterError(ValueError):
    """The frontmatter could not be parsed."""

    def __init__(self, message: str, line: int | None = None):
        super().__init__(message)
        self.line = line


def yaml_available() -> bool:
    try:
        import yaml  # noqa: F401
    except ImportError:
        return False
    return True


def split_frontmatter(text: str) -> tuple[str, str, int] | None:
    """Return (raw yaml, body, first yaml line number) or None."""
    if not text.startswith("---"):
        return None
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        return None
    raw = "\n".join(lines[1:end])
    body = "\n".join(lines[end + 1 :]).strip()
    return raw, body, 2


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    split = split_frontmatter(text)
    if split is None:
        return {}, text.strip()
    raw, body, start = split
    data = _load_yaml(raw, start)
    if data is None:
        data = _parse_block(raw.splitlines(), _min_indent(raw.splitlines()))
    return data, body


def _yaml_error(exc: Exception, start: int) -> FrontmatterError:
    line = getattr(exc, "problem_mark", None)
    number = start + getattr(line, "line", 0) if line is not None else None
    return FrontmatterError(f"YAML 解析失败：{exc}", line=number)


def _load_yaml(raw: str, start: int) -> dict[str, Any] | None:
    """Parse with PyYAML when it is importable.

    Returns None only when PyYAML is unavailable (fall back to the subset).
    Bad YAML raises FrontmatterError instead of being silently misread.
    """
    try:
        import yaml
    except ImportError:
        return None
    try:
        data = yaml.safe_load(raw)
    except Exception as exc:
        raise _yaml_error(exc, start) from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise FrontmatterError("frontmatter 顶层必须是映射")
    return data


def parse_frontmatter_strict(text: str) -> tuple[dict[str, Any], str]:
    """Parse with PyYAML and report failures with their line. Used by check."""
    split = split_frontmatter(text)
    if split is None:
        return {}, text.strip()
    raw, body, start = split
    if not yaml_available():
        raise FrontmatterError("PyYAML 不可用")
    return _load_yaml(raw, start) or {}, body


_UNSUPPORTED = (
    (re.compile(r":\s*[|>][+-]?\d*\s*(#.*)?$"), "块标量 | 或 >"),
    (re.compile(r"(?:^|[\s:\[,{,&])&\w"), "锚点 &"),
    (re.compile(r"(?:^|[\s:\[,{])\*\w"), "别名 *"),
    (re.compile(r":\s*\{"), "流式映射 {}"),
    (re.compile(r":\s*\["), "流式序列 []"),
)


def find_unsupported_lines(text: str) -> list[tuple[int, str]]:
    """Absolute 1-based lines of frontmatter the subset parser cannot read."""
    split = split_frontmatter(text)
    if split is None:
        return []
    raw, _body, start = split
    bad: list[tuple[int, str]] = []
    for offset, line in enumerate(raw.splitlines()):
        for pattern, label in _UNSUPPORTED:
            if pattern.search(line):
                bad.append((start + offset, label))
                break
    return bad


def schema_from_frontmatter(frontmatter: dict[str, Any]) -> dict[str, Any]:
    """Read a state schema from the skill file.

    Preferred key: ``metadata.skstate.state_schema``.
    Also accepted: a top-level ``state_schema``, then ``metadata.hermes.state_schema``
    so older skill files still load.
    """
    if not isinstance(frontmatter, dict):
        return {}
    top = frontmatter.get("state_schema")
    if isinstance(top, dict):
        return top
    metadata = frontmatter.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    for key in ("skstate", "hermes"):
        block = metadata.get(key)
        if isinstance(block, dict) and isinstance(block.get("state_schema"), dict):
            return block["state_schema"]
    return {}


def schema_location(frontmatter: dict[str, Any]) -> str:
    """Where the schema was read from: ``skstate``, ``hermes``, ``top`` or ``""``."""
    if not isinstance(frontmatter, dict):
        return ""
    if isinstance(frontmatter.get("state_schema"), dict):
        return "top"
    metadata = frontmatter.get("metadata")
    if not isinstance(metadata, dict):
        return ""
    for key in ("skstate", "hermes"):
        block = metadata.get(key)
        if isinstance(block, dict) and isinstance(block.get("state_schema"), dict):
            return key
    return ""


def _indent(line: str) -> int:
    count = 0
    for char in line:
        if char == " ":
            count += 1
        elif char == "\t":
            count += 2
        else:
            break
    return count


def _min_indent(lines: list[str]) -> int:
    indents = [
        _indent(line)
        for line in lines
        if line.strip() and not line.lstrip().startswith("#")
    ]
    return min(indents) if indents else 0


def _strip_comment(text: str) -> str:
    if text[:1] in {"'", '"'}:
        return text
    if " #" in text:
        return text.split(" #", 1)[0].rstrip()
    return text


def _scalar(text: str) -> Any:
    text = _strip_comment(text).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    lowered = text.casefold()
    if lowered in {"null", "~", ""}:
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d+", text):
        return float(text)
    return text


def _blank_or_comment(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


def _parse_block(lines: list[str], base_indent: int) -> dict[str, Any]:
    result: dict[str, Any] = {}
    index = 0
    while index < len(lines):
        raw = lines[index]
        if _blank_or_comment(raw):
            index += 1
            continue
        indent = _indent(raw)
        if indent < base_indent:
            break
        if indent > base_indent:
            index += 1
            continue
        stripped = raw.strip()
        if stripped.startswith("- ") or ":" not in stripped:
            index += 1
            continue
        key, _, rest = stripped.partition(":")
        key = key.strip()
        rest = rest.strip()
        if rest in {"", "|", ">"}:
            block: list[str] = []
            nxt = index + 1
            while nxt < len(lines):
                candidate = lines[nxt]
                if _blank_or_comment(candidate):
                    block.append(candidate)
                    nxt += 1
                    continue
                if _indent(candidate) <= base_indent:
                    break
                block.append(candidate)
                nxt += 1
            while block and _blank_or_comment(block[0]):
                block.pop(0)
            while block and _blank_or_comment(block[-1]):
                block.pop()
            if not block:
                result[key] = None
            elif _is_list(block):
                result[key] = _parse_list(block)
            elif _is_mapping(block):
                result[key] = _parse_block(block, _min_indent(block))
            else:
                result[key] = "\n".join(line.strip() for line in block if line.strip())
            index = nxt
            continue
        result[key] = _scalar(rest)
        index += 1
    return result


def _is_mapping(lines: list[str]) -> bool:
    for line in lines:
        if _blank_or_comment(line):
            continue
        stripped = line.strip()
        return ":" in stripped and not stripped.startswith("- ")
    return False


def _is_list(lines: list[str]) -> bool:
    for line in lines:
        if _blank_or_comment(line):
            continue
        return line.strip().startswith("- ")
    return False


def _parse_list(lines: list[str]) -> list[Any]:
    items: list[Any] = []
    for line in lines:
        if _blank_or_comment(line):
            continue
        stripped = line.strip()
        if stripped.startswith("- "):
            items.append(_scalar(stripped[2:].strip()))
    return items
