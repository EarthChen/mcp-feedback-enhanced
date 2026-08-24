"""會話↔標籤頁一一對應測試

驗證多 session 場景下，每個會話的刷新通知只發到「自己的」標籤頁：
- 多 session 並發建立時，每個會話的初始化通知（new_session_created）都應送達各自標籤頁，不被覆蓋
- 單 session 多次呼叫（mcp_session_id 跨呼叫不穩定）時，永遠復用同一個標籤頁，不開新視窗

回歸背景：原本 _pending_session_update 是單一全域變數，多 session 並發建立會互相覆蓋，
導致先建立的會話標籤頁收不到 new_session_created 而綁定錯誤；且 active_tabs 從未寫入，
單 session 在 mcp_session_id 不穩定時無法復用同一標籤頁，每輪都開新視窗。
"""

from fastapi.testclient import TestClient

from mcp_feedback_enhanced.web.main import WebUIManager


class TestTabCorrespondence:
    def test_concurrent_sessions_each_get_init_notification(
        self, web_ui_manager: WebUIManager, test_project_dir
    ):
        """兩個 session 在各自標籤頁連線前就建立，每個標籤頁都應收到自己的 new_session_created"""
        sess_a = web_ui_manager.create_session(str(test_project_dir), "會話A", "mcp-a")
        sess_b = web_ui_manager.create_session(str(test_project_dir), "會話B", "mcp-b")

        client = TestClient(web_ui_manager.app)

        with client.websocket_connect(f"/ws?session={sess_a}") as ws_a:
            assert ws_a.receive_json()["type"] == "connection_established"
            # A 的標籤頁應收到屬於 A 的初始化通知
            # 修復前：單一全域 pending 被 B 覆蓋，A 只收到 status_update
            init = ws_a.receive_json()
            assert init["type"] == "session_updated"
            assert init["action"] == "new_session_created"
            assert init["session_info"]["session_id"] == sess_a

        with client.websocket_connect(f"/ws?session={sess_b}") as ws_b:
            assert ws_b.receive_json()["type"] == "connection_established"
            init = ws_b.receive_json()
            assert init["type"] == "session_updated"
            assert init["action"] == "new_session_created"
            assert init["session_info"]["session_id"] == sess_b

    def test_single_session_reuses_one_tab_across_calls(
        self, web_ui_manager: WebUIManager, test_project_dir
    ):
        """單 session 多次呼叫（mcp_session_id 每次不同，模擬不穩定）時，永遠復用同一標籤頁"""
        sess_a = web_ui_manager.create_session(
            str(test_project_dir), "第一次", "mcp-unstable-1"
        )
        client = TestClient(web_ui_manager.app)

        with client.websocket_connect(f"/ws?session={sess_a}") as ws:
            assert ws.receive_json()["type"] == "connection_established"
            ws_a = web_ui_manager.get_session(sess_a).websocket
            assert ws_a is not None

            # 同 agent 再次呼叫，但 mcp_session_id 變了（不穩定）
            sess_b = web_ui_manager.create_session(
                str(test_project_dir), "第二次", "mcp-unstable-2"
            )
            ws_b = web_ui_manager.get_session(sess_b).websocket
            # 修復前：sess_b.websocket 為 None（開新視窗）；修復後：復用同一標籤頁
            assert ws_b is ws_a
