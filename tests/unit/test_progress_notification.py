#!/usr/bin/env python3
"""
測試 interactive_feedback 在等待用戶回饋期間發送 progress notification

Seam: interactive_feedback 工具函數的 progress reporting 行為
驗證: 在等待期間，定期調用 ctx.report_progress() 來重置 Cursor 的 idle timeout
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_progress_notification_sent_during_wait():
    """interactive_feedback 在等待用戶回饋期間應定期發送 progress notification"""
    from mcp_feedback_enhanced.server import _interactive_feedback_impl

    mock_ctx = MagicMock()
    mock_ctx.report_progress = AsyncMock()

    fake_result = {
        "interactive_feedback": "test feedback",
        "command_logs": "",
        "images": [],
        "settings": {},
    }

    async def short_delay_launch(*args, **kwargs):
        await asyncio.sleep(1.5)
        return fake_result

    with patch(
        "mcp_feedback_enhanced.server.launch_web_feedback_ui",
        side_effect=short_delay_launch,
    ):
        with patch(
            "mcp_feedback_enhanced.server.PROGRESS_INTERVAL_SECONDS", 1
        ):
            result = await _interactive_feedback_impl(
                project_directory="/tmp/test",
                summary="test summary",
                timeout=10,
                ctx=mock_ctx,
            )

    assert mock_ctx.report_progress.call_count >= 1, (
        f"Expected at least 1 progress call, got {mock_ctx.report_progress.call_count}"
    )


@pytest.mark.asyncio
async def test_progress_notification_with_delayed_feedback():
    """當用戶反饋延遲時，progress notification 應被多次發送"""
    from mcp_feedback_enhanced.server import _interactive_feedback_impl

    mock_ctx = MagicMock()
    mock_ctx.report_progress = AsyncMock()

    fake_result = {
        "interactive_feedback": "delayed feedback",
        "command_logs": "",
        "images": [],
        "settings": {},
    }

    async def delayed_launch(*args, **kwargs):
        await asyncio.sleep(3)
        return fake_result

    with patch(
        "mcp_feedback_enhanced.server.launch_web_feedback_ui",
        side_effect=delayed_launch,
    ):
        with patch(
            "mcp_feedback_enhanced.server.PROGRESS_INTERVAL_SECONDS", 1
        ):
            result = await _interactive_feedback_impl(
                project_directory="/tmp/test",
                summary="test summary",
                timeout=10,
                ctx=mock_ctx,
            )

    assert mock_ctx.report_progress.call_count >= 2, (
        f"Expected at least 2 progress calls, got {mock_ctx.report_progress.call_count}"
    )


@pytest.mark.asyncio
async def test_no_progress_when_ctx_is_none():
    """當 ctx 為 None 時，不應報錯（向後兼容）"""
    from mcp_feedback_enhanced.server import _interactive_feedback_impl

    fake_result = {
        "interactive_feedback": "test",
        "command_logs": "",
        "images": [],
        "settings": {},
    }

    with patch(
        "mcp_feedback_enhanced.server.launch_web_feedback_ui",
        return_value=fake_result,
    ):
        result = await _interactive_feedback_impl(
            project_directory="/tmp/test",
            summary="test",
            timeout=10,
            ctx=None,
        )

    assert result is not None


@pytest.mark.asyncio
async def test_progress_stops_after_feedback_received():
    """收到用戶回饋後，progress notification 應停止"""
    from mcp_feedback_enhanced.server import _interactive_feedback_impl

    mock_ctx = MagicMock()
    mock_ctx.report_progress = AsyncMock()

    fake_result = {
        "interactive_feedback": "quick feedback",
        "command_logs": "",
        "images": [],
        "settings": {},
    }

    async def quick_launch(*args, **kwargs):
        await asyncio.sleep(0.5)
        return fake_result

    with patch(
        "mcp_feedback_enhanced.server.launch_web_feedback_ui",
        side_effect=quick_launch,
    ):
        with patch(
            "mcp_feedback_enhanced.server.PROGRESS_INTERVAL_SECONDS", 1
        ):
            result = await _interactive_feedback_impl(
                project_directory="/tmp/test",
                summary="test",
                timeout=10,
                ctx=mock_ctx,
            )

    initial_count = mock_ctx.report_progress.call_count
    await asyncio.sleep(2)
    final_count = mock_ctx.report_progress.call_count

    assert final_count == initial_count, (
        f"Progress should stop after feedback received. "
        f"Initial: {initial_count}, Final: {final_count}"
    )
