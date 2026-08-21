#!/usr/bin/env python3
"""Skill 触发 e2e 测试（G3：agent 直接执行 SKILL.md 内容）。

覆盖端到端链路：
  1. GET /api/skills 返回可用技能
  2. 通过 WebSocket submit_feedback 携带 skills
  3. feedback_session 透传 skills 到 wait_for_feedback 结果
  4. server._assemble_feedback_items -> create_feedback_text 把 SKILL.md 全文注入回传文本
"""
import asyncio

import aiohttp
import pytest

from mcp_feedback_enhanced.skills import scan_skill_directories
from mcp_feedback_enhanced.server import _assemble_feedback_items, create_feedback_text


def _pick_real_skill() -> dict:
    """从标准 skill 目录中挑一个真实存在的 SKILL.md。"""
    skills = scan_skill_directories()
    assert skills, "环境中未发现任何可用 skill，无法执行 e2e"
    target = next((s for s in skills if s.get("path")), None)
    assert target, "没有带 path 的 skill"
    with open(target["path"], encoding="utf-8") as f:
        target = dict(target, content=f.read())
    return target


def _join_text(items) -> str:
    return "\n".join(it.text for it in items if getattr(it, "type", None) == "text")


@pytest.mark.asyncio
async def test_skill_e2e_via_websocket(web_ui_manager, test_project_dir):
    target = _pick_real_skill()

    web_ui_manager.create_session(str(test_project_dir), "e2e skill test")
    web_ui_manager.start_server()
    await asyncio.sleep(3)

    base = f"http://{web_ui_manager.host}:{web_ui_manager.port}"

    # 1) GET /api/skills 返回扫描到的真实技能
    async with aiohttp.ClientSession() as http:
        async with http.get(f"{base}/api/skills") as r:
            assert r.status == 200
            data = await r.json()
            assert isinstance(data, list) and data, "GET /api/skills 应返回非空列表"
            assert any(d["name"] == target["name"] for d in data)

    # 2) WebSocket 提交 feedback + skills（模拟前端选择技能并带参数）
    ws_url = f"ws://{web_ui_manager.host}:{web_ui_manager.port}/ws"
    session = web_ui_manager.get_current_session()
    async with aiohttp.ClientSession() as http:
        async with http.ws_connect(ws_url) as ws:
            msg = await asyncio.wait_for(ws.receive(), timeout=5)
            assert msg.type == aiohttp.WSMsgType.TEXT
            assert msg.json()["type"] == "connection_established"
            await ws.send_json(
                {
                    "type": "submit_feedback",
                    "feedback": f"請執行 /{target['name']} arg1",
                    "skills": [{"name": target["name"], "path": target["path"], "args": "arg1"}],
                    "clear_context": False,
                }
            )

    # 3) wait_for_feedback 原样透传 skills
    result = await asyncio.wait_for(session.wait_for_feedback(timeout=5), timeout=6)
    assert result["skills"] == [
        {"name": target["name"], "path": target["path"], "args": "arg1"}
    ], "skills 应原样透传"

    # 4) 装配文本包含 SKILL.md 全文（G3 保证 agent 一定能拿到并执行）
    items = _assemble_feedback_items(result)
    full_text = _join_text(items)
    assert f"=== Skill: {target['name']} ===" in full_text
    assert "Arguments: arg1" in full_text
    assert target["content"] in full_text, "SKILL.md 全文应被注入回传文本"


@pytest.mark.asyncio
async def test_skill_e2e_invalid_path_skipped(web_ui_manager, test_project_dir):
    """无效 path 的技能应被安全跳过：不抛异常、不注入。"""
    web_ui_manager.create_session(str(test_project_dir), "e2e invalid skill")
    web_ui_manager.start_server()
    await asyncio.sleep(3)

    session = web_ui_manager.get_current_session()
    async with aiohttp.ClientSession() as http:
        async with http.ws_connect(
            f"ws://{web_ui_manager.host}:{web_ui_manager.port}/ws"
        ) as ws:
            msg = await asyncio.wait_for(ws.receive(), timeout=5)
            assert msg.json()["type"] == "connection_established"
            await ws.send_json(
                {
                    "type": "submit_feedback",
                    "feedback": "普通反馈，无技能",
                    "skills": [{"name": "nope", "path": "/no/such/file/SKILL.md", "args": ""}],
                    "clear_context": False,
                }
            )

    result = await asyncio.wait_for(session.wait_for_feedback(timeout=5), timeout=6)
    full_text = _join_text(_assemble_feedback_items(result))
    assert "=== Skill:" not in full_text, "无效 path 不应注入技能"


def test_skill_injection_edge_cases():
    """create_feedback_text 边界：无 skills / 不存在的 path 均不报错、不注入。"""
    base = {"interactive_feedback": "hi", "command_logs": "", "images": []}
    assert "=== Skill:" not in create_feedback_text(base)
    missing = dict(base, skills=[{"name": "x", "path": "/no/such/SKILL.md", "args": ""}])
    assert "=== Skill:" not in create_feedback_text(missing)
