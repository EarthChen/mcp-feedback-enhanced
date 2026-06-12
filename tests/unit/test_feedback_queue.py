"""
反馈队列功能单元测试

测试：
- WebFeedbackSession 的队列基础设施（enqueue_feedback, drain_feedback_queue）
- _assemble_feedback_items 对 queued_items 的处理
- 提示词附件（NEW TASK、反馈提醒、上下文刷新）在多条队列项目中的行为
"""

import asyncio

import pytest
from mcp.types import TextContent

from mcp_feedback_enhanced.server import (
    _assemble_feedback_items,
)


# ---------------------------------------------------------------------------
# 测试：队列基础设施
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFeedbackQueueInfrastructure:
    """测试 WebFeedbackSession 的队列方法。"""

    def test_enqueue_feedback_adds_to_queue(self):
        """enqueue_feedback 应将项目添加到 feedback_queue。"""
        from mcp_feedback_enhanced.web.models.feedback_session import WebFeedbackSession

        session = WebFeedbackSession(
            session_id="test-queue-1",
            project_directory="/tmp",
            summary="test",
        )
        session.websocket = None

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                session.enqueue_feedback("反馈1", [], {}, False)
            )
        finally:
            loop.close()

        assert len(session.feedback_queue) == 1
        assert session.feedback_queue[0]["interactive_feedback"] == "反馈1"
        assert session.feedback_queue[0]["clear_context"] is False

    def test_drain_feedback_queue_returns_all_and_clears(self):
        """drain_feedback_queue 应返回所有项目并清空队列。"""
        from mcp_feedback_enhanced.web.models.feedback_session import WebFeedbackSession

        session = WebFeedbackSession(
            session_id="test-queue-2",
            project_directory="/tmp",
            summary="test",
        )
        session.websocket = None

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(session.enqueue_feedback("反馈A", [], {}, False))
            loop.run_until_complete(session.enqueue_feedback("反馈B", [], {}, True))
        finally:
            loop.close()

        items = session.drain_feedback_queue()

        assert len(items) == 2
        assert items[0]["interactive_feedback"] == "反馈A"
        assert items[1]["interactive_feedback"] == "反馈B"
        assert items[1]["clear_context"] is True
        assert len(session.feedback_queue) == 0

    def test_drain_feedback_queue_empty_returns_empty_list(self):
        """空队列的 drain_feedback_queue 应返回空列表。"""
        from mcp_feedback_enhanced.web.models.feedback_session import WebFeedbackSession

        session = WebFeedbackSession(
            session_id="test-queue-3",
            project_directory="/tmp",
            summary="test",
        )

        items = session.drain_feedback_queue()

        assert items == []

    def test_multiple_enqueue_preserves_order(self):
        """多次 enqueue 应保持顺序。"""
        from mcp_feedback_enhanced.web.models.feedback_session import WebFeedbackSession

        session = WebFeedbackSession(
            session_id="test-queue-4",
            project_directory="/tmp",
            summary="test",
        )
        session.websocket = None

        loop = asyncio.new_event_loop()
        try:
            for i in range(5):
                loop.run_until_complete(
                    session.enqueue_feedback(f"反馈{i}", [], {}, False)
                )
        finally:
            loop.close()

        items = session.drain_feedback_queue()

        assert len(items) == 5
        for i in range(5):
            assert items[i]["interactive_feedback"] == f"反馈{i}"


# ---------------------------------------------------------------------------
# 测试：_assemble_feedback_items 无 queued_items（原有行为不变）
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAssemblyWithoutQueue:
    """测试无队列时的组装行为（回归保护）。"""

    def test_single_item_no_queue_original_behavior(self):
        """无 queued_items 时，应走原有单条逻辑。"""
        result = {
            "interactive_feedback": "普通反馈",
            "images": [],
            "settings": {},
            "clear_context": False,
        }

        items = _assemble_feedback_items(result)

        assert len(items) >= 1
        assert "普通反馈" in items[0].text


# ---------------------------------------------------------------------------
# 测试：_assemble_feedback_items 多条队列项目
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAssemblyWithQueue:
    """测试有队列时的组装行为。"""

    def test_multiple_items_each_assembled_independently(self):
        """多条队列项目应各自独立组装为 TextContent。"""
        result = {
            "interactive_feedback": "第一条反馈",
            "images": [],
            "settings": {},
            "clear_context": False,
            "queued_items": [
                {"interactive_feedback": "第二条反馈", "images": [], "settings": {}},
                {"interactive_feedback": "第三条反馈", "images": [], "settings": {}},
            ],
        }

        items = _assemble_feedback_items(result)

        feedback_texts = [item.text for item in items if isinstance(item, TextContent)]
        assert any("第一条反馈" in t for t in feedback_texts)
        assert any("第二条反馈" in t for t in feedback_texts)
        assert any("第三条反馈" in t for t in feedback_texts)

    def test_new_task_appears_once_with_queued_items(self):
        """任意项目有 clear_context 时，NEW TASK 指令应只出现一次。"""
        result = {
            "interactive_feedback": "第一条",
            "images": [],
            "settings": {},
            "clear_context": False,
            "queued_items": [
                {"interactive_feedback": "第二条", "images": [], "settings": {}, "clear_context": True},
            ],
        }

        items = _assemble_feedback_items(result)

        new_task_count = sum(
            1 for item in items
            if isinstance(item, TextContent) and item.text.startswith("[NEW TASK]")
        )
        assert new_task_count == 1

    def test_new_task_at_position_zero(self):
        """NEW TASK 指令应在索引 0。"""
        result = {
            "interactive_feedback": "第一条",
            "images": [],
            "settings": {},
            "clear_context": True,
            "queued_items": [
                {"interactive_feedback": "第二条", "images": [], "settings": {}},
            ],
        }

        items = _assemble_feedback_items(result)

        assert items[0].text.startswith("[NEW TASK]")

    def test_feedback_reminder_appears_once_at_end(self):
        """反馈提醒应只出现一次，在最后。"""
        result = {
            "interactive_feedback": "第一条",
            "images": [],
            "settings": {},
            "clear_context": False,
            "queued_items": [
                {"interactive_feedback": "第二条", "images": [], "settings": {}},
                {"interactive_feedback": "第三条", "images": [], "settings": {}},
            ],
        }

        items = _assemble_feedback_items(result)

        reminder_count = sum(
            1 for item in items
            if isinstance(item, TextContent) and item.text.startswith("[IMPORTANT]")
        )
        assert reminder_count == 1

        # Feedback reminder should come after all feedback texts
        reminder_idx = next(
            i for i, item in enumerate(items)
            if isinstance(item, TextContent) and item.text.startswith("[IMPORTANT]")
        )
        feedback_indices = [
            i for i, item in enumerate(items)
            if isinstance(item, TextContent)
            and ("第一条" in item.text or "第二条" in item.text or "第三条" in item.text)
            and not item.text.startswith("[")
        ]
        assert all(idx < reminder_idx for idx in feedback_indices)

    def test_context_refresh_skipped_when_any_clear_context(self):
        """任意项目有 clear_context 时，上下文刷新提醒应被跳过。"""
        result = {
            "interactive_feedback": "第一条",
            "images": [],
            "settings": {"contextRefreshEnabled": True},
            "clear_context": False,
            "queued_items": [
                {"interactive_feedback": "第二条", "images": [], "settings": {}, "clear_context": True},
            ],
        }

        items = _assemble_feedback_items(result)

        context_refresh_count = sum(
            1 for item in items
            if isinstance(item, TextContent) and "[CONTEXT REFRESH" in item.text
        )
        assert context_refresh_count == 0

    def test_context_refresh_present_when_no_clear_context(self):
        """无 clear_context 时，上下文刷新提醒应出现一次。"""
        result = {
            "interactive_feedback": "第一条",
            "images": [],
            "settings": {"contextRefreshEnabled": True},
            "clear_context": False,
            "queued_items": [
                {"interactive_feedback": "第二条", "images": [], "settings": {}},
            ],
        }

        items = _assemble_feedback_items(result)

        context_refresh_count = sum(
            1 for item in items
            if isinstance(item, TextContent) and "[CONTEXT REFRESH" in item.text
        )
        assert context_refresh_count == 1

    def test_empty_queued_items_falls_back_to_single_mode(self):
        """queued_items 为空列表时，应走单条逻辑。"""
        result = {
            "interactive_feedback": "普通反馈",
            "images": [],
            "settings": {},
            "clear_context": False,
            "queued_items": [],
        }

        items = _assemble_feedback_items(result)

        assert len(items) >= 1
        assert "普通反馈" in items[0].text

    def test_order_feedback_before_global_prompts(self):
        """项目顺序：反馈文字在前，全局提示词在后。"""
        result = {
            "interactive_feedback": "第一条",
            "images": [],
            "settings": {},
            "clear_context": False,
            "queued_items": [
                {"interactive_feedback": "第二条", "images": [], "settings": {}},
            ],
        }

        items = _assemble_feedback_items(result)

        reminder_idx = None
        for i, item in enumerate(items):
            if isinstance(item, TextContent) and item.text.startswith("[IMPORTANT]"):
                reminder_idx = i
                break

        feedback_indices = [
            i for i, item in enumerate(items)
            if isinstance(item, TextContent)
            and ("第一条" in item.text or "第二条" in item.text)
            and not item.text.startswith("[")
        ]
        if reminder_idx is not None and feedback_indices:
            assert max(feedback_indices) < reminder_idx
