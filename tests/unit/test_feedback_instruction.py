"""
反馈指令组装逻辑单元测试

测试 _assemble_feedback_items 函数的行为：
- clear_context=True 时 [NEW TASK] 指令应作为独立 TextContent 项目插入索引 0
- 不应与用户反馈文本拼接在一起

同时测试工具名称一致性和默认提醒文本。
"""

import pytest
from mcp.types import TextContent

from mcp_feedback_enhanced.server import (
    _DEFAULT_REMINDER_TEXT,
    _assemble_feedback_items,
    _get_context_refresh_reminder,
    _get_feedback_reminder,
    _get_new_task_instruction,
)


# ---------------------------------------------------------------------------
# 测试：clear_context=True 时 NEW TASK 指令应为独立项目
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestClearContextAssembly:
    """测试 clear_context 模式下反馈项目的组装行为。"""

    def test_clear_context_with_user_feedback_separate_items(self):
        """clear_context=True 且有用户反馈时：
        - 索引 0 应为独立的 NEW TASK 指令
        - 索引 1 应为用户反馈
        - NEW TASK 指令文本不应包含用户反馈内容
        """
        result = {
            "interactive_feedback": "请帮我重构这个函数",
            "clear_context": True,
        }

        items = _assemble_feedback_items(result)

        # 至少有 2 个项目：NEW TASK 指令 + 用户反馈
        assert len(items) >= 2

        # 索引 0 应为 NEW TASK 指令
        new_task_item = items[0]
        assert isinstance(new_task_item, TextContent)
        assert new_task_item.text.startswith("[NEW TASK]")

        # NEW TASK 指令不应包含用户反馈文本
        assert "请帮我重构这个函数" not in new_task_item.text

        # 索引 1 应为用户反馈
        feedback_item = items[1]
        assert isinstance(feedback_item, TextContent)
        assert "请帮我重构这个函数" in feedback_item.text

    def test_clear_context_with_empty_feedback(self):
        """clear_context=True 且无用户反馈时：
        - NEW TASK 指令应为第一个项目
        - 列表应至少有 1 个项目
        """
        result = {
            "interactive_feedback": "",
            "clear_context": True,
        }

        items = _assemble_feedback_items(result)

        assert len(items) >= 1

        # 第一个项目应为 NEW TASK 指令
        first_item = items[0]
        assert isinstance(first_item, TextContent)
        assert first_item.text.startswith("[NEW TASK]")

    def test_clear_context_with_no_feedback_key(self):
        """clear_context=True 且 result 中没有 interactive_feedback 键时：
        - NEW TASK 指令应为第一个项目
        - 应有默认的空反馈占位符
        """
        result = {
            "clear_context": True,
        }

        items = _assemble_feedback_items(result)

        assert len(items) >= 2

        # 第一个项目应为 NEW TASK 指令
        first_item = items[0]
        assert isinstance(first_item, TextContent)
        assert first_item.text.startswith("[NEW TASK]")

        # 应包含默认占位符
        placeholder_found = any(
            "用戶未提供任何回饋內容" in item.text
            for item in items
            if isinstance(item, TextContent)
        )
        assert placeholder_found

    def test_clear_context_new_task_not_concatenated_with_separator(self):
        """验证 NEW TASK 指令不会与用户反馈通过 '\\n\\n---\\n' 拼接。

        这是当前 bug 的回归测试：旧代码将 NEW TASK 和用户反馈拼接为一个项目，
        使用 '\\n\\n---\\n' 分隔。正确行为应为两个独立项目。
        """
        result = {
            "interactive_feedback": "这是用户反馈",
            "clear_context": True,
        }

        items = _assemble_feedback_items(result)

        # 索引 0 的文本不应包含分隔符
        assert "\n\n---\n" not in items[0].text

        # 索引 0 不应同时包含 NEW TASK 指令和用户反馈
        first_text = items[0].text
        assert first_text.startswith("[NEW TASK]")
        assert "这是用户反馈" not in first_text


# ---------------------------------------------------------------------------
# 测试：clear_context=False（正常提交）
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNormalSubmitAssembly:
    """测试正常提交（非 clear_context）模式下反馈项目的组装行为。"""

    def test_normal_submit_no_new_task_instruction(self):
        """clear_context=False 时，不应有以 [NEW TASK] 开头的独立指令项目。"""
        result = {
            "interactive_feedback": "这是一条普通反馈",
            "clear_context": False,
        }

        items = _assemble_feedback_items(result)

        # 不应有任何项目以 [NEW TASK] 开头
        for item in items:
            assert isinstance(item, TextContent)
            assert not item.text.startswith("[NEW TASK]")

    def test_normal_submit_first_item_is_feedback(self):
        """clear_context=False 时，第一个项目应为用户反馈。"""
        result = {
            "interactive_feedback": "这是一条普通反馈",
            "clear_context": False,
        }

        items = _assemble_feedback_items(result)

        assert len(items) >= 1
        first_item = items[0]
        assert isinstance(first_item, TextContent)
        assert "这是一条普通反馈" in first_item.text


# ---------------------------------------------------------------------------
# 测试：clear_context=True 且有图片
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestClearContextWithImages:
    """测试 clear_context 模式下包含图片的组装行为。"""

    def test_clear_context_with_images_order(self):
        """clear_context=True 且有图片时，项目顺序应为：
        [0] NEW TASK 指令
        [1] 反馈文字
        [2+] 图片
        """
        import base64
        import struct
        import zlib

        def _make_tiny_png() -> bytes:
            header = b"\x89PNG\r\n\x1a\n"
            ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
            ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF
            ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)
            raw = zlib.compress(b"\x00\xff\x00\x00")
            idat_crc = zlib.crc32(b"IDAT" + raw) & 0xFFFFFFFF
            idat = struct.pack(">I", len(raw)) + b"IDAT" + raw + struct.pack(">I", idat_crc)
            iend_crc = zlib.crc32(b"IEND") & 0xFFFFFFFF
            iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)
            return header + ihdr + idat + iend

        png_bytes = _make_tiny_png()
        b64_str = base64.b64encode(png_bytes).decode("ascii")

        result = {
            "interactive_feedback": "请看这张图片",
            "images": [
                {"data": b64_str, "mimeType": "image/png"},
            ],
            "clear_context": True,
        }

        items = _assemble_feedback_items(result)

        # 至少有 3 个项目：NEW TASK + 反馈文字 + 图片
        assert len(items) >= 3

        # 索引 0：NEW TASK 指令
        assert isinstance(items[0], TextContent)
        assert items[0].text.startswith("[NEW TASK]")

        # 索引 1：反馈文字
        assert isinstance(items[1], TextContent)
        assert "请看这张图片" in items[1].text


# ---------------------------------------------------------------------------
# 测试：工具名称一致性和默认提醒文本
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestToolNameConsistency:
    """测试工具名称在默认文本中的一致性。"""

    def test_default_reminder_text_references_interactive_feedback(self):
        """默认提醒文本应引用 'interactive_feedback' 工具名称。"""
        assert "interactive_feedback" in _DEFAULT_REMINDER_TEXT

    def test_default_reminder_text_does_not_reference_old_name(self):
        """默认提醒文本不应引用旧的工具名称 'mcp-feedback-pro'。"""
        assert "mcp-feedback-pro" not in _DEFAULT_REMINDER_TEXT

    def test_default_reminder_text_contains_new_task_hint(self):
        """默认提醒文本应包含 [NEW TASK] 相关提示。"""
        assert "[NEW TASK]" in _DEFAULT_REMINDER_TEXT


# ---------------------------------------------------------------------------
# 测试：_get_new_task_instruction 辅助函数
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetNewTaskInstruction:
    """测试 _get_new_task_instruction 辅助函数。"""

    def test_returns_default_instruction(self):
        """无自定义设置时，应返回默认 NEW TASK 指令。"""
        result: dict = {}
        instruction = _get_new_task_instruction(result)
        assert instruction.startswith("[NEW TASK]")

    def test_returns_custom_instruction(self):
        """有自定义 newTaskInstructionText 时，应返回自定义文本。"""
        result = {
            "settings": {
                "newTaskInstructionText": "自定义新任务指令",
            },
        }
        instruction = _get_new_task_instruction(result)
        assert instruction == "自定义新任务指令"

    def test_ignores_empty_custom_text(self):
        """自定义文本为空字符串时，应回退到默认指令。"""
        result = {
            "settings": {
                "newTaskInstructionText": "   ",
            },
        }
        instruction = _get_new_task_instruction(result)
        assert instruction.startswith("[NEW TASK]")


# ---------------------------------------------------------------------------
# 测试：_get_feedback_reminder 辅助函数
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetFeedbackReminder:
    """测试 _get_feedback_reminder 辅助函数。"""

    def test_returns_default_when_enabled(self):
        """无自定义设置且提醒启用时，应返回默认提醒文本。"""
        result: dict = {}
        reminder = _get_feedback_reminder(result)
        assert reminder is not None
        assert "interactive_feedback" in reminder

    def test_returns_none_when_disabled(self):
        """提醒禁用时，应返回 None。"""
        result = {
            "settings": {
                "feedbackReminderEnabled": False,
            },
        }
        reminder = _get_feedback_reminder(result)
        assert reminder is None

    def test_returns_custom_text(self):
        """有自定义提醒文本时，应返回自定义文本。"""
        result = {
            "settings": {
                "feedbackReminderText": "自定义提醒内容",
            },
        }
        reminder = _get_feedback_reminder(result)
        assert reminder == "自定义提醒内容"
