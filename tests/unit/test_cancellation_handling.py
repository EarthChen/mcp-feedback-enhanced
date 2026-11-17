#!/usr/bin/env python3
"""
取消處理測試

背景：Cursor 停止按鈕會取消 MCP 請求，但本 MCP 服務端不感知取消：
- `_launch_with_progress` 用 asyncio.shield 包住等待任務，取消信號無法傳播
- MCP SDK / FastMCP 均未註冊 notifications/cancelled 處理器
導致：點擊停止後會話持續等待整個 timeout（默認 600s），心跳照發，
超時後遲到響應喚醒 agent 觸發重試。

Seam：
1. `_launch_with_progress` 外層取消 → 內層等待任務被終止（無孤兒任務）
2. 取消通知處理器 → 對應等待任務被取消、會話被清理
3. 超時路徑返回「請勿自動重試」語義文本且不追加 reminder
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.types import CancelledNotification, CancelledNotificationParams

from mcp_feedback_enhanced.server import (
    _INFLIGHT_FEEDBACK_TASKS,
    _handle_cancelled_notification,
    _interactive_feedback_impl,
    _launch_with_progress,
)


class TestOuterCancellationPropagation:
    """Seam 1：外層任務取消應終止內層等待任務（不產生孤兒任務）"""

    @pytest.mark.asyncio
    async def test_outer_cancel_cancels_inner_wait_task(self):
        """外層協程被取消時，launch_web_feedback_ui 任務必須被一併取消。

        回歸背景：asyncio.shield 使 Cursor 停止後等待任務繼續存活至 timeout，
        會話、uvicorn、心跳循環全部殘留。
        """
        launch_cancelled = asyncio.Event()

        async def slow_launch(*args, **kwargs):
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                launch_cancelled.set()
                raise
            return {}

        mock_ctx = MagicMock()
        mock_ctx.report_progress = AsyncMock()
        mock_ctx.debug = AsyncMock()

        with patch(
            "mcp_feedback_enhanced.server.launch_web_feedback_ui",
            side_effect=slow_launch,
        ):
            task = asyncio.create_task(
                _launch_with_progress(
                    ctx=mock_ctx,
                    project_dir="/tmp",
                    summary="test",
                    timeout=60,
                )
            )
            await asyncio.sleep(0.2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        # 內層任務必須已收到取消，而非成為孤兒繼續等待 30s
        assert launch_cancelled.is_set(), (
            "外層取消後內層等待任務仍在運行（孤兒任務），服務端將空等至 timeout 才結束"
        )


class TestCancelledNotificationHandling:
    """Seam 2：notifications/cancelled 應終止對應等待任務並清理會話。

    回歸背景：MCP SDK / FastMCP 均不處理取消通知，Cursor 停止按鈕後
    服務端等待任務與心跳持續運行至 timeout。
    """

    @pytest.mark.asyncio
    async def test_cancelled_notification_terminates_wait_and_cleans_session(
        self, web_ui_manager, test_project_dir
    ):
        session_id = web_ui_manager.create_session(
            str(test_project_dir), "取消測試", "mcp-ctx-1"
        )
        session = web_ui_manager.get_session(session_id)

        mock_ctx = MagicMock()
        mock_ctx.request_id = "42"
        mock_ctx.session_id = "mcp-ctx-1"
        mock_ctx.report_progress = AsyncMock()
        mock_ctx.debug = AsyncMock()

        async def slow_launch(*args, **kwargs):
            await asyncio.sleep(30)
            return {}

        with (
            patch(
                "mcp_feedback_enhanced.server.launch_web_feedback_ui",
                side_effect=slow_launch,
            ),
            patch(
                "mcp_feedback_enhanced.web.main.get_web_ui_manager",
                return_value=web_ui_manager,
            ),
        ):
            task = asyncio.create_task(
                _launch_with_progress(
                    ctx=mock_ctx,
                    project_dir="/tmp",
                    summary="t",
                    timeout=60,
                    mcp_session_id="mcp-ctx-1",
                )
            )
            await asyncio.sleep(0.2)

            # 前置：任務已註冊，可供取消通知定位
            assert "42" in _INFLIGHT_FEEDBACK_TASKS

            # 模擬 Cursor 停止按鈕發出的取消通知
            notification = CancelledNotification(
                method="notifications/cancelled",
                params={"requestId": 42, "reason": "user pressed stop"},
            )
            await _handle_cancelled_notification(notification)

            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=5)

        # 會話必須被終止清理，而非繼續等待至 timeout
        assert session.feedback_completed.is_set(), (
            "取消通知後會話仍在等待反饋（應立即清理終止）"
        )
        assert session.is_terminal(), f"會話應進入終態，實際: {session.status.value}"

        # 清理註冊表
        assert "42" not in _INFLIGHT_FEEDBACK_TASKS

    @pytest.mark.asyncio
    async def test_client_sent_cancelled_notification_end_to_end(self):
        """端到端：客戶端顯式發送 notifications/cancelled 時，等待應立即終止。

        注意：mcp SDK 客戶端在請求任務被 cancel 時不會自動發送取消通知
        （send_request 無取消分支），此測試顯式發送以驗證服務端 wiring。
        """
        launch_cancelled = asyncio.Event()

        async def slow_launch(*args, **kwargs):
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                launch_cancelled.set()
                raise
            return {}

        mock_ctx = MagicMock()
        mock_ctx.request_id = "99"
        mock_ctx.session_id = "mcp-ctx-e2e"
        mock_ctx.report_progress = AsyncMock()
        mock_ctx.debug = AsyncMock()

        with patch(
            "mcp_feedback_enhanced.server.launch_web_feedback_ui",
            side_effect=slow_launch,
        ):
            task = asyncio.create_task(
                _launch_with_progress(
                    ctx=mock_ctx, project_dir="/tmp", summary="t", timeout=60
                )
            )
            await asyncio.sleep(0.2)

            # 直接注入通知（繞過傳輸層，模擬規範合規客戶端的取消通知）
            await _handle_cancelled_notification(
                CancelledNotification(
                    method="notifications/cancelled",
                    params=CancelledNotificationParams(requestId=99),
                )
            )

            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=5)

        assert launch_cancelled.is_set()


class TestTimeoutResultSemantics:
    """Seam 3：超時返回必須明確「會話已關閉、勿自動重試」，且不追加 reminder。

    回歸背景：超時 TimeoutError 被 except Exception 捕獲後包裝成
    「❌ 系統錯誤」普通文本，agent 視為正常返回並依 usage rules 再次調用。
    """

    @pytest.mark.asyncio
    async def test_timeout_returns_no_retry_text_without_reminder(self):
        async def timeout_launch(*args, **kwargs):
            raise TimeoutError("等待用戶回饋超時")

        mock_ctx = MagicMock()
        mock_ctx.report_progress = AsyncMock()
        mock_ctx.debug = AsyncMock()
        mock_ctx.request_id = "7"
        mock_ctx.session_id = "mcp-ctx-2"

        with patch(
            "mcp_feedback_enhanced.server.launch_web_feedback_ui",
            side_effect=timeout_launch,
        ):
            result = await _interactive_feedback_impl(
                project_directory="/tmp",
                summary="t",
                timeout=10,
                ctx=mock_ctx,
            )

        text = "\n".join(item.text for item in result if hasattr(item, "text"))
        assert "超時" in text or "timeout" in text.lower(), (
            f"超時文本未說明超時: {text!r}"
        )
        assert "重試" in text or "retry" in text.lower(), (
            f"超時文本未明確告知不要自動重試: {text!r}"
        )
        assert "MUST call" not in text, "超時路徑不得追加強制再次調用的 reminder"
