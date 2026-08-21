"""Scan agent skill directories and expose skill metadata.

Skills follow the Agent Skills open standard: a folder containing ``SKILL.md``
with YAML frontmatter. The skill's identity (and the Cursor invocation name)
is the folder name that contains ``SKILL.md``.

This module only reads lightweight metadata. The full ``SKILL.md`` content is
read lazily by the caller when a skill is actually invoked (see
``server.create_feedback_text``), so triggering a skill does not require
Cursor's internal skill UI.
"""
from __future__ import annotations

import os
from pathlib import Path


# Standard skill directories (Cursor / Claude / Codex compatible).
SKILL_DIRS = [
    ".agents/skills",
    ".cursor/skills",
    "~/.agents/skills",
    "~/.cursor/skills",
    ".claude/skills",
    ".codex/skills",
    "~/.claude/skills",
    "~/.codex/skills",
]


def _parse_frontmatter(path: str) -> dict:
    """Extract simple ``key: value`` frontmatter from a SKILL.md file."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    fields: dict = {}
    for line in text[3:end].splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key:
            fields[key] = value
    return fields


def scan_skill_directories() -> list[dict]:
    """Return discovered skills as ``{name, path, description, argument_hint}``."""
    skills: list[dict] = []
    seen: set[str] = set()
    for raw_dir in SKILL_DIRS:
        base = Path(os.path.expanduser(raw_dir))
        if not base.is_dir():
            continue
        for skill_md in sorted(base.rglob("SKILL.md")):
            path = str(skill_md)
            if path in seen:
                continue
            seen.add(path)
            name = skill_md.parent.name
            fm = _parse_frontmatter(path)
            skills.append(
                {
                    "name": name,
                    "path": path,
                    "description": fm.get("description", ""),
                    # The frontmatter `name` must match the folder name.
                    "declared_name": fm.get("name", ""),
                    "argument_hint": fm.get("argument-hint", "")
                    or fm.get("argument_hint", ""),
                }
            )
    return skills
