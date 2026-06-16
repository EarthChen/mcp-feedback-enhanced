"""
端口管理器測試模組

測試 PortManager 類的各項功能，包括：
- 端口可用性檢測
- 進程查找和清理
- 增強端口查找
"""

import socket
import time
from unittest.mock import patch

import psutil
import pytest
from unittest.mock import MagicMock

# 移除手動路徑操作，讓 mypy 和 pytest 使用正確的模組解析
from mcp_feedback_enhanced.web.utils.port_manager import PortManager


class TestPortManager:
    """端口管理器測試類"""

    def test_is_port_available_free_port(self):
        """測試檢測空閒端口"""
        # 找一個肯定空閒的端口
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            free_port = s.getsockname()[1]

        # 測試該端口是否被檢測為可用
        assert PortManager.is_port_available("127.0.0.1", free_port) is True

    def test_is_port_available_occupied_port(self):
        """測試檢測被占用的端口"""
        # 創建一個占用端口的 socket
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind(("127.0.0.1", 0))
        occupied_port = server_socket.getsockname()[1]
        server_socket.listen(1)

        try:
            # 測試該端口是否被檢測為不可用
            assert PortManager.is_port_available("127.0.0.1", occupied_port) is False
        finally:
            server_socket.close()

    def test_find_free_port_enhanced_preferred_available(self):
        """測試當偏好端口可用時的行為"""
        # 找一個空閒端口作為偏好端口
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            preferred_port = s.getsockname()[1]

        # 測試是否返回偏好端口
        result_port = PortManager.find_free_port_enhanced(
            preferred_port=preferred_port, auto_cleanup=False
        )
        assert result_port == preferred_port

    def test_find_free_port_enhanced_preferred_occupied(self):
        """測試當偏好端口被占用時的行為"""
        # 創建一個占用端口的 socket
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind(("127.0.0.1", 0))
        occupied_port = server_socket.getsockname()[1]
        server_socket.listen(1)

        try:
            # 測試是否返回其他可用端口
            result_port = PortManager.find_free_port_enhanced(
                preferred_port=occupied_port, auto_cleanup=False
            )
            assert result_port != occupied_port
            assert result_port > occupied_port  # 應該向上查找

            # 驗證返回的端口確實可用
            assert PortManager.is_port_available("127.0.0.1", result_port) is True
        finally:
            server_socket.close()

    def test_find_process_using_port_no_process(self):
        """測試查找沒有進程占用的端口"""
        # 找一個空閒端口
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            free_port = s.getsockname()[1]

        # 測試是否正確返回 None
        result = PortManager.find_process_using_port(free_port)
        assert result is None

    def test_find_process_using_port_with_process(self):
        """測試查找有進程占用的端口"""
        # 創建一個簡單的測試服務器
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind(("127.0.0.1", 0))
        test_port = server_socket.getsockname()[1]
        server_socket.listen(1)

        try:
            # 測試是否能找到進程信息
            result = PortManager.find_process_using_port(test_port)

            if result:  # 如果找到了進程（在某些環境下可能找不到）
                assert isinstance(result, dict)
                assert "pid" in result
                assert "ppid" in result
                assert "name" in result
                assert "cmdline" in result
                assert isinstance(result["pid"], int)
                assert result["pid"] > 0
                assert isinstance(result["ppid"], int)
        finally:
            server_socket.close()

    def test_get_port_status_available(self):
        """測試獲取可用端口的狀態"""
        # 找一個空閒端口
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            free_port = s.getsockname()[1]

        status = PortManager.get_port_status(free_port)

        assert status["port"] == free_port
        assert status["host"] == "127.0.0.1"
        assert status["available"] is True
        assert status["process"] is None
        assert status["error"] is None

    def test_get_port_status_occupied(self):
        """測試獲取被占用端口的狀態"""
        # 創建一個占用端口的 socket
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind(("127.0.0.1", 0))
        occupied_port = server_socket.getsockname()[1]
        server_socket.listen(1)

        try:
            status = PortManager.get_port_status(occupied_port)

            assert status["port"] == occupied_port
            assert status["host"] == "127.0.0.1"
            assert status["available"] is False
            # process 可能為 None（取決於系統權限）
            assert status["error"] is None
        finally:
            server_socket.close()

    def test_list_listening_ports(self):
        """測試列出監聽端口"""
        # 創建幾個測試服務器
        servers = []
        test_ports = []

        try:
            for i in range(2):
                server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server_socket.bind(("127.0.0.1", 0))
                port = server_socket.getsockname()[1]
                server_socket.listen(1)

                servers.append(server_socket)
                test_ports.append(port)

            # 測試列出監聽端口
            min_port = min(test_ports) - 10
            max_port = max(test_ports) + 10

            listening_ports = PortManager.list_listening_ports(min_port, max_port)

            # 驗證結果
            assert isinstance(listening_ports, list)

            # 檢查我們的測試端口是否在列表中
            found_ports = [p["port"] for p in listening_ports]
            for test_port in test_ports:
                if test_port in found_ports:
                    # 找到了我們的端口，驗證信息完整性
                    port_info = next(
                        p for p in listening_ports if p["port"] == test_port
                    )
                    assert "host" in port_info
                    assert "pid" in port_info
                    assert "process_name" in port_info
                    assert "cmdline" in port_info

        finally:
            # 清理測試服務器
            for server in servers:
                server.close()

    # === _is_orphan_process 直接測試 ===

    def test_is_orphan_process_ppid_zero_not_orphan(self):
        """ppid=0（缺省值/未知）不應被判定為孤兒，避免誤殺活躍進程"""
        # ppid=0 表示無法獲取父進程信息，應保守返回 False（不殺）
        result = PortManager._is_orphan_process(ppid=0)
        assert result is False

    def test_is_orphan_process_ppid_negative_not_orphan(self):
        """ppid<0（異常值）不應被判定為孤兒"""
        result = PortManager._is_orphan_process(ppid=-1)
        assert result is False

    @patch("mcp_feedback_enhanced.web.utils.port_manager.psutil.Process")
    def test_is_orphan_process_ppid_one_orphan(self, mock_process):
        """ppid=1（init/systemd 收養）應被判定為孤兒"""
        mock_process.side_effect = psutil.NoSuchProcess(1)
        result = PortManager._is_orphan_process(ppid=1)
        assert result is True

    @patch("mcp_feedback_enhanced.web.utils.port_manager.psutil.Process")
    def test_is_orphan_process_parent_dead(self, mock_process):
        """父進程已退出（NoSuchProcess）→ 孤兒"""
        mock_process.side_effect = psutil.NoSuchProcess(999)
        result = PortManager._is_orphan_process(ppid=999)
        assert result is True

    @patch("mcp_feedback_enhanced.web.utils.port_manager.psutil.Process")
    def test_is_orphan_process_parent_alive(self, mock_process):
        """父進程仍存活 → 非孤兒"""
        mock_process.return_value = MagicMock()
        result = PortManager._is_orphan_process(ppid=100)
        assert result is False

    @patch("mcp_feedback_enhanced.web.utils.port_manager.psutil.Process")
    def test_is_orphan_process_parent_access_denied(self, mock_process):
        """無權限訪問父進程 → 非孤兒（保守策略）"""
        mock_process.side_effect = psutil.AccessDenied(100)
        result = PortManager._is_orphan_process(ppid=100)
        assert result is False

    # === _should_cleanup_process 測試 ===

    @patch("mcp_feedback_enhanced.web.utils.port_manager.psutil.Process")
    def test_should_cleanup_process_mcp_orphan(self, mock_process):
        """測試孤兒 MCP 進程應被清理（父進程已退出）"""
        mock_process.side_effect = psutil.NoSuchProcess(999)
        process_info = {
            "pid": 1234,
            "ppid": 999,  # 父進程已不存在
            "name": "python.exe",
            "cmdline": "python -m mcp-feedback-enhanced test --web",
            "create_time": time.time(),
            "status": "running",
        }

        result = PortManager._should_cleanup_process(process_info)
        assert result is True

    @patch("mcp_feedback_enhanced.web.utils.port_manager.psutil.Process")
    def test_should_cleanup_process_mcp_active(self, mock_process):
        """測試活躍 MCP 進程不應被清理（父進程仍存活）"""
        mock_process.return_value = MagicMock()  # 父進程存在
        process_info = {
            "pid": 1234,
            "ppid": 100,  # 父進程仍存活
            "name": "python.exe",
            "cmdline": "python -m mcp-feedback-enhanced test --web",
            "create_time": time.time(),
            "status": "running",
        }

        result = PortManager._should_cleanup_process(process_info)
        assert result is False

    def test_should_cleanup_process_mcp_missing_ppid(self):
        """缺少 ppid 字段時不應誤判為孤兒（保守策略，不殺）"""
        process_info = {
            "pid": 1234,
            # 故意不含 ppid
            "name": "python.exe",
            "cmdline": "python -m mcp-feedback-enhanced test --web",
            "create_time": time.time(),
            "status": "running",
        }

        result = PortManager._should_cleanup_process(process_info)
        assert result is False

    @patch("mcp_feedback_enhanced.web.utils.port_manager.psutil.Process")
    def test_should_cleanup_process_other_process(self, mock_process):
        """測試是否應該清理其他進程"""
        # 模擬其他進程
        process_info = {
            "pid": 5678,
            "name": "chrome.exe",
            "cmdline": "chrome --new-window",
            "create_time": time.time(),
            "status": "running",
        }

        result = PortManager._should_cleanup_process(process_info)
        assert result is False

    def test_find_free_port_enhanced_max_attempts(self):
        """測試最大嘗試次數限制"""
        # 這個測試比較難實現，因為需要占用大量連續端口
        # 我們只測試參數是否正確傳遞
        try:
            result = PortManager.find_free_port_enhanced(
                preferred_port=65000,  # 使用高端口減少衝突
                auto_cleanup=False,
                max_attempts=10,
            )
            assert isinstance(result, int)
            assert 65000 <= result <= 65535
        except RuntimeError:
            # 如果真的找不到端口，這也是正常的
            pass


if __name__ == "__main__":
    # 運行測試
    pytest.main([__file__, "-v"])
