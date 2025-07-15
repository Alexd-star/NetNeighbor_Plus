"""
连接管理控制器，处理设备连接和通信
"""

import json
import threading
from typing import Dict, Any, Optional, Callable

from PySide6.QtCore import QTimer, QObject, Signal, QThread, Qt
from PySide6.QtWidgets import QApplication

from gui.api_client import ApiClient
from gui.models.connection_model import ConnectionModel
from gui.models.log_model import LogModel
from gui.models.share_model import RemoteShareModel
from gui.websocket_client import WebSocketClientThread


class ConnectionThread(QThread):
    """一个专门用于后台网络连接的QThread工作线程。"""

    # 定义信号: 成功时发射客户端和共享列表，失败时发射错误信息
    connection_successful = Signal(ApiClient, list)
    connection_failed = Signal(str)

    def __init__(self, base_url: str, parent=None):
        super().__init__(parent)
        self.base_url = base_url
        self.api_client = ApiClient(self.base_url)

    def run(self):
        """线程的执行体：进行网络请求并根据结果发射信号。"""
        try:
            # 首先测试连接是否可用
            if not self.api_client.get_ping():
                raise ConnectionError("设备无响应，请检查网络连接。")

            # 获取共享列表
            shares = self.api_client.get_shares()

            if shares is not None:
                # 成功，发射成功信号
                self.connection_successful.emit(self.api_client, shares)
            else:
                # API返回None，说明是超时或连接错误
                raise ConnectionError("无法获取共享列表，设备无响应或超时。")
        except Exception as e:
            # 任何其他异常，发射失败信号
            self.connection_failed.emit(str(e))


class ConnectionPresenter(QObject):
    """连接Presenter，管理设备连接和WebSocket"""

    connection_successful = Signal(ApiClient, list)  # 连接成功信号
    connection_failed = Signal(str)  # 连接失败信号

    def __init__(
        self,
        connection_model: ConnectionModel,
        share_model: RemoteShareModel,
        log_model: LogModel,
    ):
        super().__init__()
        self.connection_model = connection_model
        self.share_model = share_model
        self.log_model = log_model

        self.ws_local_thread = None
        self.ws_remote_thread = None
        self.connection_thread = None

        # 回调函数
        self._on_websocket_message_callback = None

    def connect_to_device(self, service_name: str, device_data: Dict[str, Any]):
        """连接到设备"""
        # 检查是否有线程正在运行
        if self.connection_thread and self.connection_thread.isRunning():
            return

        display_name = service_name.split("._netneighbor._tcp.local.")[0]
        address = device_data.get("address")
        port = device_data.get("port")

        if not address or not port:
            self.connection_failed.emit(f"设备 {display_name} 的地址或端口无效")
            return

        base_url = f"http://{address}:{port}"

        # 设置连接状态
        self.connection_model.set_connection_state("connecting")

        # 显示等待光标
        QApplication.setOverrideCursor(Qt.WaitCursor)

        # 使用ConnectionThread进行连接
        self.connection_thread = ConnectionThread(base_url)
        self.connection_thread.connection_successful.connect(
            lambda client, shares: self._on_connection_successful(
                client, shares, display_name, service_name, device_data
            )
        )
        self.connection_thread.connection_failed.connect(
            lambda error_msg: self._on_connection_failed(error_msg, display_name)
        )

        # 线程结束后清理
        self.connection_thread.finished.connect(self._on_connection_thread_finished)
        self.connection_thread.finished.connect(self.connection_thread.deleteLater)

        self.connection_thread.start()

    def _on_connection_thread_finished(self):
        """当连接线程结束后，安全地清除对它的引用。"""
        self.connection_thread = None

    def _on_connection_successful(
        self,
        client: ApiClient,
        shares: list,
        display_name: str,
        service_name: str,
        device_data: Dict[str, Any],
    ):
        """连接成功处理"""
        # 恢复光标
        QApplication.restoreOverrideCursor()

        # 设置活动客户端
        self.connection_model.set_active_peer_client(
            client, display_name, device_data.get("address")
        )

        # 设置远程共享
        self.share_model.set_shares(shares)

        # 启动WebSocket连接
        self._setup_websocket(client.base_url)

        # 测量延迟
        self.connection_model.measure_ping()

        # 发射连接成功信号
        self.connection_successful.emit(client, shares)

    def _on_connection_failed(self, error_message: str, display_name: str):
        """连接失败处理"""
        # 恢复光标
        QApplication.restoreOverrideCursor()

        self.log_model.add_log(f"连接到 {display_name} 失败: {error_message}", "❌")

        # 设置连接状态
        self.connection_model.set_connection_state("disconnected")

        # 发射连接失败信号
        self.connection_failed.emit(f"连接到 {display_name} 失败: {error_message}")

    def _setup_websocket(self, base_url: str):
        """设置WebSocket连接"""
        # 停止已有的远程WebSocket线程
        if self.ws_remote_thread and self.ws_remote_thread.isRunning():
            self.ws_remote_thread.stop()

        # 启动新的WebSocket连接
        ws_uri = f"ws://{base_url.split('//')[1]}/ws/events"
        self.ws_remote_thread = WebSocketClientThread(ws_uri, "remote")
        self.ws_remote_thread.message_received.connect(self._handle_websocket_message)
        self.ws_remote_thread.start()

    def setup_local_websocket(self, port: int):
        """设置本地WebSocket连接"""
        try:
            print(f"设置本地WebSocket连接，端口: {port}")

            # 停止已有的本地WebSocket线程
            if self.ws_local_thread and self.ws_local_thread.isRunning():
                print("停止现有的WebSocket连接")
                self.ws_local_thread.stop()
                self.ws_local_thread.wait(2000)  # 等待最多2秒

            ws_uri = f"ws://127.0.0.1:{port}/ws/events"
            print(f"创建WebSocket连接: {ws_uri}")

            self.ws_local_thread = WebSocketClientThread(ws_uri, "local")
            self.ws_local_thread.message_received.connect(
                self._handle_websocket_message
            )
            self.ws_local_thread.start()

            print("WebSocket线程已启动")

        except Exception as e:
            print(f"设置本地WebSocket连接失败: {e}")
            import traceback

            traceback.print_exc()

    def _write_debug_log(self, message):
        """写入调试日志到文件"""
        try:
            import os
            import datetime

            log_file = os.path.join(os.path.expanduser("~"), "netneighbor_debug.log")
            with open(log_file, "a", encoding="utf-8") as f:
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"[{timestamp}] ConnectionPresenter: {message}\n")
                f.flush()
        except:
            pass  # 忽略日志写入错误

    def _handle_websocket_message(self, message: str, source: str):
        """处理WebSocket消息"""
        try:
            data = json.loads(message)
            event = data.get("event")

            print(f"WebSocket消息: {event} (来源: {source})")
            self._write_debug_log(f"收到WebSocket消息: {event} (来源: {source})")

            # 处理连接和断开事件
            if event == "ws_local_connected":
                self.log_model.add_log("已连接到本地WebSocket服务", "🔌")
                print("本地WebSocket连接成功")
                self._write_debug_log("✅ 本地WebSocket连接成功")
            elif event == "ws_remote_connected":
                self.log_model.add_log("已连接到远程WebSocket服务", "🔌")
                print("远程WebSocket连接成功")
                self._write_debug_log("✅ 远程WebSocket连接成功")
            elif event == "ws_local_disconnected":
                self.log_model.add_log("本地WebSocket连接已断开", "🔌")
                print("本地WebSocket连接断开")
                self._write_debug_log("❌ 本地WebSocket连接断开")
            elif event == "ws_remote_disconnected":
                self.log_model.add_log("远程WebSocket连接已断开", "🔌")
                print("远程WebSocket连接断开")
                self._write_debug_log("❌ 远程WebSocket连接断开")
            elif event == "ws_local_failed":
                self.log_model.add_log("本地WebSocket连接失败", "❌")
                print("本地WebSocket连接失败")
                self._write_debug_log("❌ 本地WebSocket连接失败")
            elif event == "ws_remote_failed":
                self.log_model.add_log("远程WebSocket连接失败", "❌")
                print("远程WebSocket连接失败")
                self._write_debug_log("❌ 远程WebSocket连接失败")

            # 转发消息给回调函数
            if self._on_websocket_message_callback:
                self._on_websocket_message_callback(data, event, source)
        except json.JSONDecodeError as e:
            error_msg = f"WebSocket消息解析失败: {e}, 消息: {message}"
            print(error_msg)
            self._write_debug_log(error_msg)
        except Exception as e:
            error_msg = f"处理WebSocket消息时出错: {e}"
            print(error_msg)
            self._write_debug_log(error_msg)
            import traceback

            traceback_str = traceback.format_exc()
            print(traceback_str)
            self._write_debug_log(f"WebSocket消息处理异常堆栈: {traceback_str}")

    def disconnect_device(self):
        """断开设备连接"""
        # 停止WebSocket线程
        if self.ws_remote_thread and self.ws_remote_thread.isRunning():
            self.ws_remote_thread.stop()
            self.ws_remote_thread = None

        # 清除活动客户端
        self.connection_model.set_active_peer_client(None)

        # 清除远程共享
        self.share_model.clear()

    def stop_all_connections(self):
        """停止所有连接"""
        # 停止WebSocket线程
        if self.ws_local_thread and self.ws_local_thread.isRunning():
            self.ws_local_thread.stop()
            self.ws_local_thread = None

        if self.ws_remote_thread and self.ws_remote_thread.isRunning():
            self.ws_remote_thread.stop()
            self.ws_remote_thread = None

    def on_websocket_message(
        self, callback: Callable[[Dict[str, Any], str, str], None]
    ):
        """设置WebSocket消息回调"""
        self._on_websocket_message_callback = callback
