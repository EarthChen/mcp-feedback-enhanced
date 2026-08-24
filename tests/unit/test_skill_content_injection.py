#!/usr/bin/env python3
"""測試 create_feedback_text 的技能內容注入安全與容量邊界。

Seam: server.create_feedback_text 的技能注入行為
背景：G3 已實現按 path 讀取 SKILL.md 全文注入回傳文本，但存在兩個缺口：
  1. 路徑僅做 isfile 檢查——客戶端可提交任意檔案路徑，造成任意檔案讀取；
  2. 內容無大小上限——超大 SKILL.md 會撐爆 AI 上下文。
"""

import os
import textwrap

import pytest

from mcp_feedback_enhanced.server import create_feedback_text
from mcp_feedback_enhanced.skills import (
    SKILL_CONTENT_MAX_CHARS,
    parse_skills_from_text,
    scan_skill_directories,
)


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """偽造 HOME，使 ~/.agents/skills 指向臨時目錄。"""
    home = tmp_path / "home"
    skills = home / ".agents" / "skills"
    (skills / "demo").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    return home


def _make_skill(home, name="demo", body="執行步驟：先審查再修改。"):
    path = home / ".agents" / "skills" / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        textwrap.dedent(
            f"""\
            ---
            name: {name}
            description: 測試技能
            ---

            {body}
            """
        ),
        encoding="utf-8",
    )
    return path


def _base(skills=None, **extra):
    data = {"interactive_feedback": "hi", "command_logs": "", "images": []}
    if skills is not None:
        data["skills"] = skills
    data.update(extra)
    return data


def test_valid_skill_injected_with_frontmatter_and_body(fake_home):
    """合法技能目錄下的 SKILL.md 應全文注入（含 frontmatter）。"""
    path = _make_skill(fake_home)
    text = create_feedback_text(
        _base([{"name": "demo", "path": str(path), "args": ""}])
    )
    assert "=== Skill: demo ===" in text
    assert "description: 測試技能" in text
    assert "執行步驟：先審查再修改。" in text


def test_existing_file_outside_skill_dirs_rejected(fake_home, tmp_path):
    """存在於磁碟但不在技能目錄內的檔案不得注入（防任意檔案讀取）。"""
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP_SECRET", encoding="utf-8")
    text = create_feedback_text(
        _base([{"name": "evil", "path": str(secret), "args": ""}])
    )
    assert "=== Skill:" not in text
    assert "TOP_SECRET" not in text


def test_symlinked_skill_injected_per_convention(fake_home):
    """技能目錄內的軟連結技能應被注入（掃描跟隨軟連結是本倉庫約定）。

    安全基準是服務端掃描清單：掃描已跟隨軟連結並按真實路徑去重，
    因此出現在清單內的軟連結技能視為合法安裝。
    """
    target = fake_home / "outside.md"
    target.write_text("LINKED_CONTENT", encoding="utf-8")
    link = fake_home / ".agents" / "skills" / "linked" / "SKILL.md"
    link.parent.mkdir(parents=True)
    link.symlink_to(target)
    assert any(
        s["name"] == "linked" for s in scan_skill_directories()
    ), "前置條件：軟連結技能必須出現在掃描清單中"
    text = create_feedback_text(
        _base([{"name": "linked", "path": str(link), "args": ""}])
    )
    assert "=== Skill: linked ===" in text
    assert "LINKED_CONTENT" in text


def test_project_level_skill_allowed_with_project_dir(fake_home, tmp_path):
    """專案級 .agents/skills 下的技能在提供 project_directory 時應被允許。"""
    proj = tmp_path / "proj"
    path = proj / ".agents" / "skills" / "projskill"
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text("專案級內容", encoding="utf-8")
    text = create_feedback_text(
        _base(
            [{"name": "projskill", "path": str(path / "SKILL.md"), "args": ""}],
            project_directory=str(proj),
        )
    )
    assert "=== Skill: projskill ===" in text
    assert "專案級內容" in text


def test_project_level_skill_rejected_without_project_dir(fake_home, tmp_path):
    """未提供 project_directory 時，專案級技能路徑不得注入。"""
    proj = tmp_path / "proj"
    path = proj / ".agents" / "skills" / "projskill"
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text("專案級內容", encoding="utf-8")
    text = create_feedback_text(
        _base(
            [{"name": "projskill", "path": str(path / "SKILL.md"), "args": ""}]
        )
    )
    assert "專案級內容" not in text


def test_oversized_skill_content_truncated_with_marker(fake_home):
    """超過上限的 SKILL.md 應截斷並附標註，避免撐爆 AI 上下文。"""
    path = _make_skill(fake_home, name="big", body="X" * (SKILL_CONTENT_MAX_CHARS + 100))
    text = create_feedback_text(_base([{"name": "big", "path": str(path)}]))
    assert "已截斷" in text, "截斷後必須有明確標註"
    skill_section = text.split("=== Skill: big ===", 1)[1]
    assert len(skill_section) < SKILL_CONTENT_MAX_CHARS + 500


def test_skill_parsed_from_feedback_text_when_skills_field_missing(fake_home):
    """前端未附帶 skills 時，服務端應從 interactive_feedback 兜底解析。"""
    path = _make_skill(fake_home, name="demo", body="兜底注入內容")
    text = create_feedback_text(
        {
            "interactive_feedback": "/demo 請執行這個技能",
            "command_logs": "",
            "images": [],
        }
    )
    assert "=== Skill: demo ===" in text
    assert str(path) in text
    assert "兜底注入內容" in text


def test_multiple_skills_on_same_line_parsed_with_split_args(fake_home):
    """同一行多個 skill 時，args 應在下一個 skill 前截斷。"""
    path_a = _make_skill(fake_home, name="alpha", body="ALPHA_BODY")
    path_b = _make_skill(fake_home, name="beta", body="BETA_BODY")
    parsed = parse_skills_from_text("/alpha first args /beta second args")
    assert [p["name"] for p in parsed] == ["alpha", "beta"]
    assert parsed[0]["args"] == "first args"
    assert parsed[1]["args"] == "second args"
    text = create_feedback_text(
        {
            "interactive_feedback": "/alpha first args /beta second args",
            "command_logs": "",
            "images": [],
        }
    )
    assert "=== Skill: alpha ===" in text
    assert "=== Skill: beta ===" in text
    assert "Arguments: first args" in text
    assert "Arguments: second args" in text
    assert "ALPHA_BODY" in text
    assert "BETA_BODY" in text
    assert str(path_a) in text
    assert str(path_b) in text
