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


# 預設掃描用戶級 agents 與 cursor 目錄；專案級目錄由呼叫方傳入 project_dir。


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


def scan_skill_directories(project_dir: str | None = None) -> list[dict]:
    """發現並返回技能列表 ``{name, path, description, argument_hint}``。

    預設掃描用戶級目錄 ``~/.agents/skills`` 與 ``~/.cursor/skills``；
    若提供 project_dir，額外掃描專案級 ``.agents/skills`` 與 ``.cursor/skills``。
    掃描跟隨軟連接（技能常以軟連接形式放入技能目錄），並按 SKILL.md 真實路徑去重。
    """
    dirs = ["~/.agents/skills", "~/.cursor/skills"]
    if project_dir:
        proj = os.path.abspath(os.path.expanduser(project_dir))
        dirs += [
            os.path.join(proj, ".agents", "skills"),
            os.path.join(proj, ".cursor", "skills"),
        ]

    skills: list[dict] = []
    seen_real: set[str] = set()
    for raw in dirs:
        base = Path(os.path.expanduser(raw))
        if not base.exists():
            continue
        base = base.resolve()
        for root, subdirs, files in os.walk(str(base), followlinks=True):
            real_root = os.path.realpath(root)
            if real_root in seen_real:
                subdirs[:] = []  # 避免軟連接環導致無限遞歸
                continue
            seen_real.add(real_root)
            if "SKILL.md" in files:
                path = os.path.join(root, "SKILL.md")
                real_path = os.path.realpath(path)
                if real_path in seen_real:
                    continue
                seen_real.add(real_path)
                name = os.path.basename(os.path.dirname(path))
                fm = _parse_frontmatter(path)
                skills.append(
                    {
                        "name": name,
                        "path": path,
                        "description": fm.get("description", ""),
                        "declared_name": fm.get("name", ""),
                        "argument_hint": fm.get("argument-hint", "")
                        or fm.get("argument_hint", ""),
                    }
                )
    skills.sort(key=lambda s: s["name"])
    return skills
