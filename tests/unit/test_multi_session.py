"""多會話隔離測試

驗證多個 Cursor session 並發調用 interactive_feedback 時互不覆蓋：
- 不同 MCP session 的會話各自獨立，回饋正確路由回各自的調用方
- 同一 MCP session 重入時替換舊會話（保留原有狀態機語義）
- 未提供 mcp_session_id 時退回原單一活躍會話行為
- 路由路由層（頁面 / API / WebSocket）按 session 參數正確路由
"""

import asyncio

import pytest

from mcp_feedback_enhanced.web.main import WebUIManager
from tests.fixtures.test_data import TestData


class TestMultiSessionIsolation:
    """多 MCP session 隔離測試"""

    def test_different_mcp_sessions_create_independent_sessions(
        self, web_ui_manager: WebUIManager, test_project_dir
    ):
        """不同 MCP session 各自創建獨立會話，互不替換"""
        session_id_1 = web_ui_manager.create_session(
            str(test_project_dir), "會話一", "mcp-session-aaa"
        )
        session_id_2 = web_ui_manager.create_session(
            str(test_project_dir), "會話二", "mcp-session-bbb"
        )

        assert session_id_1 != session_id_2
        assert len(web_ui_manager.sessions) == 2
        assert web_ui_manager.mcp_session_map["mcp-session-aaa"] == session_id_1
        assert web_ui_manager.mcp_session_map["mcp-session-bbb"] == session_id_2

        # 兩個會話都保持可等待狀態（第一個未被第二個破壞）
        session_1 = web_ui_manager.get_session(session_id_1)
        assert session_1 is not None
        assert session_1.summary == "會話一"
        assert not session_1.feedback_completed.is_set()

    async def test_concurrent_feedback_routed_to_correct_caller(
        self, web_ui_manager: WebUIManager, test_project_dir
    ):
        """並發等待回饋時，各會話的提交只喚醒自己的調用方"""
        session_id_1 = web_ui_manager.create_session(
            str(test_project_dir), "會話一", "mcp-session-aaa"
        )
        session_id_2 = web_ui_manager.create_session(
            str(test_project_dir), "會話二", "mcp-session-bbb"
        )
        session_1 = web_ui_manager.get_session(session_id_1)
        session_2 = web_ui_manager.get_session(session_id_2)

        async def wait_and_submit(session, text):
            task = asyncio.create_task(session.wait_for_feedback(10))
            await asyncio.sleep(0.05)
            await session.submit_feedback(text, [], {})
            return await task

        result_1, result_2 = await asyncio.gather(
            wait_and_submit(session_1, "回饋一"),
            wait_and_submit(session_2, "回饋二"),
        )

        # 核心隔離斷言：結果不串擾
        assert result_1["interactive_feedback"] == "回饋一"
        assert result_2["interactive_feedback"] == "回饋二"

    def test_same_mcp_session_reentry_replaces_old_session(
        self, web_ui_manager: WebUIManager, test_project_dir
    ):
        """同一 MCP session 重入：替換舊會話（保留原有狀態機語義），其他會話不受影響"""
        session_id_1 = web_ui_manager.create_session(
            str(test_project_dir), "第一次調用", "mcp-session-aaa"
        )
        other_session_id = web_ui_manager.create_session(
            str(test_project_dir), "另一個會話", "mcp-session-bbb"
        )

        session_id_1_new = web_ui_manager.create_session(
            str(test_project_dir), "重入調用", "mcp-session-aaa"
        )

        # 映射指向新會話
        assert web_ui_manager.mcp_session_map["mcp-session-aaa"] == session_id_1_new

        # 舊會話仍在字典中（用於 API 獲取）；資源已被 _cleanup_sync 清理，
        # 狀態保持 waiting（原有狀態機僅對已提交會話推進狀態）
        old_session = web_ui_manager.get_session(session_id_1)
        assert old_session is not None
        assert old_session.summary == "第一次調用"

        # 其他 MCP session 的會話不受影響
        other_session = web_ui_manager.get_session(other_session_id)
        assert other_session.summary == "另一個會話"
        assert not other_session.feedback_completed.is_set()

    def test_no_mcp_session_id_falls_back_to_legacy_behavior(
        self, web_ui_manager: WebUIManager, test_project_dir
    ):
        """未提供 mcp_session_id 時退回原單一活躍會話行為（替換 current_session）"""
        first = web_ui_manager.create_session(str(test_project_dir), "第一個")
        second = web_ui_manager.create_session(str(test_project_dir), "第二個")

        assert web_ui_manager.get_current_session().session_id == second
        assert first != second


class TestMultiSessionRoutes:
    """路由層按 session 參數路由的測試"""

    def test_index_with_session_param_renders_that_session(
        self, web_ui_manager: WebUIManager, test_project_dir
    ):
        from fastapi.testclient import TestClient

        session_id_1 = web_ui_manager.create_session(
            str(test_project_dir), "獨特摘要甲", "mcp-1"
        )
        web_ui_manager.create_session(str(test_project_dir), "獨特摘要乙", "mcp-2")

        client = TestClient(web_ui_manager.app)
        response = client.get(f"/?session={session_id_1}")

        assert response.status_code == 200
        assert "獨特摘要甲" in response.text
        assert "獨特摘要乙" not in response.text

    def test_index_without_session_param_shows_picker(
        self, web_ui_manager: WebUIManager, test_project_dir
    ):
        from fastapi.testclient import TestClient

        web_ui_manager.create_session(str(test_project_dir), "摘要", "mcp-1")

        client = TestClient(web_ui_manager.app)
        response = client.get("/")

        assert response.status_code == 200
        # 選擇頁而非直接渲染某個會話
        assert "picker-container" in response.text

    def test_index_with_unknown_session_shows_waiting_page(
        self, web_ui_manager: WebUIManager, test_project_dir
    ):
        from fastapi.testclient import TestClient

        web_ui_manager.create_session(str(test_project_dir), "摘要", "mcp-1")

        client = TestClient(web_ui_manager.app)
        response = client.get("/?session=nonexistent-id")

        assert response.status_code == 200
        assert "MCP Feedback Enhanced" in response.text

    def test_current_session_api_accepts_session_id(
        self, web_ui_manager: WebUIManager, test_project_dir
    ):
        from fastapi.testclient import TestClient

        session_id_1 = web_ui_manager.create_session(
            str(test_project_dir), "目標會話", "mcp-1"
        )
        web_ui_manager.create_session(str(test_project_dir), "後來的會話", "mcp-2")

        client = TestClient(web_ui_manager.app)

        # 指定 session_id → 返回該會話
        data = client.get(f"/api/current-session?session_id={session_id_1}").json()
        assert data["summary"] == "目標會話"

        # 無參數 → 回退最近建立的會話（向後兼容）
        data = client.get("/api/current-session").json()
        assert data["summary"] == "後來的會話"

    def test_websocket_binds_to_specified_session(
        self, web_ui_manager: WebUIManager, test_project_dir
    ):
        from fastapi.testclient import TestClient

        session_id_1 = web_ui_manager.create_session(
            str(test_project_dir), "WS 會話一", "mcp-1"
        )
        session_id_2 = web_ui_manager.create_session(
            str(test_project_dir), "WS 會話二", "mcp-2"
        )

        client = TestClient(web_ui_manager.app)

        # 清除待發送標記，讓連接確認消息序列確定（connection_established → status_update）
        web_ui_manager._pending_session_updates = set()

        with client.websocket_connect(f"/ws?session={session_id_1}") as ws:
            # 連接確認消息
            first_message = ws.receive_json()
            assert first_message["type"] == "connection_established"

            # 連接綁定到 session 1，而非全局 current_session（session 2）
            assert web_ui_manager.get_session(session_id_1).websocket is not None
            assert web_ui_manager.get_session(session_id_2).websocket is None

            # 消息路由到綁定的會話
            ws.send_json({"type": "get_status"})
            status_message = ws.receive_json()
            assert status_message["type"] == "status_update"
            assert status_message["status_info"]["session_id"] == session_id_1

    def test_websocket_submit_routes_to_transferred_session(
        self, web_ui_manager: WebUIManager, test_project_dir
    ):
        """回歸測試：持久化標籤頁的 WebSocket 在新 MCP 調用轉移連接後，
        回饋必須路由到「新會話」而非被轉移走的「舊會話」。

        否則首次回饋會被送錯會話而對新會話「失效」，必須刷新頁面重連才生效。
        """
        from fastapi.testclient import TestClient

        mcp_id = "mcp-reentry"
        session_id_1 = web_ui_manager.create_session(
            str(test_project_dir), "舊會話", mcp_id
        )
        client = TestClient(web_ui_manager.app)
        web_ui_manager._pending_session_updates = set()

        with client.websocket_connect(f"/ws?session={session_id_1}") as ws:
            # 握手確認
            assert ws.receive_json()["type"] == "connection_established"

            # 新 MCP 調用：同 mcp session 重入，舊連接被轉移到新會話
            session_id_2 = web_ui_manager.create_session(
                str(test_project_dir), "新會話", mcp_id
            )
            assert web_ui_manager.get_current_session().session_id == session_id_2
            # 轉移後同一條 WS 現由新會話擁有
            assert web_ui_manager.get_session(session_id_2).websocket is not None

            # 通過同一條 WS 提交回饋（模擬用戶在持久化標籤頁點擊提交）
            ws.send_json({
                "type": "submit_feedback",
                "feedback": "來自持久化標籤頁的回饋",
                "images": [],
                "settings": {},
                "clear_context": False,
            })

            # 服務端應回送 FEEDBACK_SUBMITTED 通知（先清空握手遺留的 status_update）
            notification = None
            for _ in range(5):
                msg = ws.receive_json()
                if msg.get("type") == "notification":
                    notification = msg
                    break
            assert notification is not None

            # 關鍵斷言：回饋喚醒的是「新會話」，而非被轉移走的舊會話
            new_session = web_ui_manager.get_session(session_id_2)
            old_session = web_ui_manager.get_session(session_id_1)
            assert new_session.feedback_completed.is_set()
            assert not old_session.feedback_completed.is_set()
            assert new_session.feedback_result == "來自持久化標籤頁的回饋"
