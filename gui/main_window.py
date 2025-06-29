# 文件: gui/main_window.py (完整修复版)
import os
import socket
import json
import copy
import asyncio
import websockets
import threading
import time
import math
from PySide6.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QListWidget, QTableWidget,
                               QAbstractItemView, QHeaderView, QListWidgetItem, QTableWidgetItem,
                               QMenu, QMessageBox, QFileDialog, QPushButton, QLineEdit, QProgressDialog,
                               QGroupBox, QLabel, QComboBox, QTextEdit, QStatusBar, QStyle, QStackedWidget)
from PySide6.QtCore import QTimer, Qt, QThread, Signal
from PySide6.QtGui import QAction, QIcon, QFont
from typing import Optional
from .api_client import ApiClient, UploadStreamer
from .settings_window import SettingsWindow
from .app_controller import AppController
from core.config_loader import load_config, get_config


# --- 【核心修复】重写 WebSocketClientThread 以实现可靠的线程停止 ---
class WebSocketClientThread(QThread):
    message_received = Signal(str, str)

    def __init__(self, uri: str, source: str):
        super().__init__()
        self.uri = uri
        self.source = source
        self._is_running = True
        self.loop = None
        self.task = None

    async def listen(self):
        while self._is_running:
            try:
                # 增加连接和关闭超时，防止长时间阻塞
                async with websockets.connect(self.uri, open_timeout=5, close_timeout=5) as websocket:
                    print(f"WebSocket ({self.source}) 已连接到 {self.uri}")
                    self.message_received.emit(json.dumps({"event": f"ws_{self.source}_connected"}), self.source)
                    while self._is_running:
                        try:
                            message = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                            self.message_received.emit(message, self.source)
                        except asyncio.TimeoutError:
                            # 超时是正常的，它让我们有机会检查 self._is_running 标志位
                            await asyncio.sleep(0.1)
                        except websockets.exceptions.ConnectionClosed:
                            if self._is_running:
                                print(f"WebSocket ({self.source}) 连接已关闭。")
                            break  # 中断内层循环，将尝试重连
            except asyncio.CancelledError:
                # 这是我们主动停止线程时预期的异常，直接退出循环
                break
            except Exception as e:
                if self._is_running:
                    print(f"WebSocket ({self.source}) 连接错误: {e}。 5秒后重连...")
                    self.message_received.emit(json.dumps({"event": f"ws_{self.source}_disconnected"}), self.source)
                    # 在重连等待期间也检查停止标志
                    for _ in range(50):
                        if not self._is_running: break
                        await asyncio.sleep(0.1)

    def run(self):
        try:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.task = self.loop.create_task(self.listen())
            self.loop.run_until_complete(self.task)
        except asyncio.CancelledError:
            # 任务被取消是正常的停止流程，安静地处理
            pass
        except Exception as e:
            if self._is_running:
                print(f"WebSocket ({self.source}) 线程发生意外错误: {e}")
        finally:
            if self.loop.is_running():
                self.loop.stop()
            self.loop.close()
            print(f"WebSocket ({self.source}) 线程已干净地终止。")

    def stop(self):
        if not self.isRunning():
            return

        print(f"正在请求停止 WebSocket ({self.source}) 线程...")
        self._is_running = False

        if self.loop and self.task and not self.task.done():
            # 使用线程安全的方式请求取消 asyncio 任务
            self.loop.call_soon_threadsafe(self.task.cancel)

        # 等待线程真正执行完毕
        if not self.wait(2000):  # 等待最多2秒
            print(f"警告: WebSocket ({self.source}) 线程在超时后仍在运行。将强制终止。")
            self.terminate()  # 作为最后手段


class WorkerThread(QThread):
    progress = Signal(int)
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, task_type, **kwargs):
        super().__init__()
        self.task_type, self.kwargs = task_type, kwargs

    def run(self):
        try:
            if self.task_type == "download_http":
                self._run_download_http()
            elif self.task_type == "download_tcp":
                self._run_download_tcp()
            elif self.task_type == "upload":
                self._run_upload()
            else:
                self.error.emit(f"未知的任务类型: {self.task_type}")
        except Exception as e:
            self.error.emit(str(e))

    def _run_download_http(self):
        peer_client, share_name, remote_path, save_path = self.kwargs['peer_client'], self.kwargs['share_name'], \
                                                          self.kwargs['remote_path'], self.kwargs['save_path']
        with peer_client.download_file_stream(share_name, remote_path) as response:
            response.raise_for_status();
            total_size, downloaded_size = int(response.headers.get('content-length', 0)), 0
            with open(save_path, "wb") as f:
                for chunk in response.iter_bytes(chunk_size=8192):
                    f.write(chunk)
                    downloaded_size += len(chunk)
                    if total_size > 0:
                        self.progress.emit(int((downloaded_size / total_size) * 100))
        self.finished.emit(f"文件 '{os.path.basename(save_path)}' (HTTP) 下载完成！")

    def _run_download_tcp(self):
        tcp_host, tcp_port, header, save_path = self.kwargs['tcp_host'], self.kwargs['tcp_port'], self.kwargs['header'], \
                                                self.kwargs['save_path']
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((tcp_host, tcp_port));
            s.sendall(json.dumps(header).encode('utf-8'))
            response_header_data = s.recv(1024)
            if not response_header_data:
                raise ConnectionError("服务器未响应头信息")
            response_header = json.loads(response_header_data.decode('utf-8'))
            if response_header.get("status") != "ok":
                raise ConnectionError(f"服务器错误: {response_header.get('message')}")
            total_size = response_header.get("size", 0)
            s.sendall(b'ready')
            downloaded_size = 0
            with open(save_path, 'wb') as f:
                while downloaded_size < total_size:
                    chunk = s.recv(64 * 1024)
                    if not chunk: break
                    f.write(chunk)
                    downloaded_size += len(chunk)
                    if total_size > 0:
                        self.progress.emit(int((downloaded_size / total_size) * 100))
        self.finished.emit(f"文件 '{os.path.basename(save_path)}' (TCP高速) 下载完成！")

    def _run_upload(self):
        peer_client, share_name, dest_path, local_file_path = self.kwargs['peer_client'], self.kwargs['share_name'], \
                                                              self.kwargs['dest_path'], self.kwargs['local_file_path']
        last_emitted_progress = -1

        def progress_callback(p):
            nonlocal last_emitted_progress
            if p > last_emitted_progress:
                self.progress.emit(p)
                last_emitted_progress = p

        with UploadStreamer(local_file_path, progress_callback=progress_callback) as uploader:
            peer_client.upload_file_stream(share_name, dest_path, uploader)
        self.finished.emit(f"文件 '{os.path.basename(local_file_path)}' 上传成功！")


class MainWindow(QMainWindow):
    def __init__(self, controller: AppController):
        super().__init__()
        self.controller = controller
        self.config_data = self.controller.running_config
        self.my_ip = self.get_my_ip()
        self.api_client = None
        self.online_devices_data = {}
        self.active_peer_client = None
        self.active_path_stack = []
        self.worker_thread = None
        self.ws_local_thread = None
        self.ws_remote_thread = None

        self.setup_window()
        self.load_icons()
        self.setup_ui()
        self.update_my_shares_list()
        self.controller.device_info_updated.connect(self.update_local_status_display)

    def post_init_setup(self):
        print("后端服务已就绪, UI开始进行网络初始化...")
        self.api_client = ApiClient(f"http://{self.my_ip}:{self.controller.port}")
        self.setup_timers()
        self.setup_websocket()
        self.status_bar_label.setText("就绪. 正在扫描局域网设备...")
        self.update_local_status_display()
        self.update_device_list()

    def get_my_ip(self):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80));
                return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"

    def load_icons(self):
        self.folder_icon = self.style().standardIcon(QStyle.SP_DirIcon)
        self.file_icon = self.style().standardIcon(QStyle.SP_FileIcon)
        self.back_icon = self.style().standardIcon(QStyle.SP_ArrowLeft)
        self.upload_icon = self.style().standardIcon(QStyle.SP_ArrowUp)
        self.download_icon = self.style().standardIcon(QStyle.SP_ArrowDown)
        self.settings_icon = self.style().standardIcon(QStyle.SP_FileDialogDetailedView)
        self.help_icon = self.style().standardIcon(QStyle.SP_DialogHelpButton)

    def setup_window(self):
        self.setWindowTitle("邻里+ (NetNeighbor Plus)");
        self.setGeometry(100, 100, 1200, 700)
        self.setWindowIcon(self.style().standardIcon(QStyle.SP_ComputerIcon))
        self.resize(1200, 700)
        try:
            center_point = self.screen().availableGeometry().center()
            frame_geometry = self.frameGeometry()
            frame_geometry.moveCenter(center_point)
            self.move(frame_geometry.topLeft())
        except AttributeError:
            self.setGeometry(100, 100, 1200, 700)

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("文件")
        settings_action = QAction(self.settings_icon, "设置...", self)
        settings_action.triggered.connect(self.open_settings)
        file_menu.addAction(settings_action)

        help_menu = menu_bar.addMenu("帮助")
        about_action = QAction(self.help_icon, "关于...", self)
        about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(about_action)

        my_status_box = QGroupBox("本机状态")
        my_status_box.setObjectName("StatusGroupBox")
        my_status_layout = QHBoxLayout(my_status_box)

        self.device_name_label = QLabel("设备名: 正在检测...")
        self.device_name_label.setToolTip("当前设备的网络名称")
        self.device_type_label = QLabel("类型: 未知")
        self.device_type_label.setToolTip("根据操作系统判断的设备类型")
        my_ip_label = QLabel(f"IP地址: {self.my_ip}:{self.controller.port}")

        my_status_layout.addWidget(self.device_name_label)
        my_status_layout.addSpacing(20)
        my_status_layout.addWidget(self.device_type_label)
        my_status_layout.addStretch()
        my_status_layout.addWidget(my_ip_label)
        main_layout.addWidget(my_status_box)

        interaction_layout = QHBoxLayout()
        main_layout.addLayout(interaction_layout, stretch=1)

        left_panel_widget = QWidget()
        left_panel_layout = QVBoxLayout(left_panel_widget)
        left_panel_widget.setFixedWidth(280)
        left_panel_layout.setContentsMargins(0, 10, 0, 0)

        left_panel_layout.addWidget(QLabel("<h4>在线设备</h4>"))
        self.device_list_widget = QListWidget()
        self.device_list_widget.itemClicked.connect(self.handle_device_click)
        left_panel_layout.addWidget(self.device_list_widget, stretch=3)

        my_shares_header_layout = QHBoxLayout()
        my_shares_header_layout.addWidget(QLabel("<h4>本机共享</h4>"))
        my_shares_header_layout.addStretch()
        self.manage_shares_button = QPushButton("管理...")
        self.manage_shares_button.setToolTip("添加、移除或修改本机共享文件夹")
        self.manage_shares_button.clicked.connect(self.open_settings)
        self.manage_shares_button.setObjectName("ManageButton")
        my_shares_header_layout.addWidget(self.manage_shares_button)
        left_panel_layout.addLayout(my_shares_header_layout)

        self.my_shares_list_widget = QListWidget()
        self.my_shares_list_widget.setToolTip("右键点击可移除共享")
        self.my_shares_list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.my_shares_list_widget.customContextMenuRequested.connect(self.show_my_shares_context_menu)
        left_panel_layout.addWidget(self.my_shares_list_widget, stretch=2)

        left_panel_layout.addWidget(QLabel("<h4>事件日志</h4>"))
        self.log_text_edit = QTextEdit()
        self.log_text_edit.setReadOnly(True)
        left_panel_layout.addWidget(self.log_text_edit, stretch=2)
        interaction_layout.addWidget(left_panel_widget)

        self.right_stack = QStackedWidget()
        interaction_layout.addWidget(self.right_stack, stretch=1)

        self.welcome_page = self.create_welcome_page()
        self.file_browser_page = QWidget()
        right_layout = QVBoxLayout(self.file_browser_page)
        right_layout.setContentsMargins(10, 10, 0, 0)
        self.right_stack.addWidget(self.welcome_page)
        self.right_stack.addWidget(self.file_browser_page)

        toolbar_layout = QHBoxLayout()
        self.share_selector_combo = QComboBox()
        self.share_selector_combo.setPlaceholderText("第2步: 选择共享")
        self.share_selector_combo.setMinimumWidth(200)
        self.share_selector_combo.currentIndexChanged.connect(self.handle_share_selection_change)

        self.back_button = QPushButton(self.back_icon, "返回")
        self.back_button.clicked.connect(self.go_back_directory)
        self.current_path_label = QLineEdit("/")
        self.current_path_label.setReadOnly(True)
        self.current_path_label.setObjectName("PathLabel")

        self.upload_button = QPushButton(self.upload_icon, "上传到当前目录")
        self.upload_button.clicked.connect(self.handle_upload_action)

        toolbar_layout.addWidget(self.share_selector_combo)
        toolbar_layout.addWidget(self.back_button)
        toolbar_layout.addWidget(QLabel("当前路径:"))
        toolbar_layout.addWidget(self.current_path_label, stretch=1)
        toolbar_layout.addWidget(self.upload_button)
        right_layout.addLayout(toolbar_layout)

        self.file_table_widget = QTableWidget()
        self.file_table_widget.setColumnCount(3)
        self.file_table_widget.setHorizontalHeaderLabels(["文件名", "类型", "大小"])
        self.file_table_widget.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.file_table_widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.file_table_widget.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.file_table_widget.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.file_table_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.file_table_widget.customContextMenuRequested.connect(self.show_file_context_menu)
        self.file_table_widget.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.file_table_widget.setAlternatingRowColors(True)
        self.file_table_widget.setShowGrid(False)
        self.file_table_widget.verticalHeader().setVisible(False)
        right_layout.addWidget(self.file_table_widget)

        self.right_stack.setCurrentWidget(self.welcome_page)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar_label = QLabel("正在初始化...")
        self.status_bar.addWidget(self.status_bar_label, 1)

    def update_local_status_display(self):
        print("UI接到通知，正在更新本机状态显示...")
        device_name = self.controller.device_name
        self.device_name_label.setText(f"<b>设备名:</b> {device_name}")
        device_type = self.controller.device_properties.get('dev_type', '未知')
        self.device_type_label.setText(f"<b>类型:</b> {device_type}")
        self.device_type_label.setToolTip(
            f"操作系统: {self.controller.device_properties.get('os', 'N/A')}\n用户名: {self.controller.device_properties.get('user', 'N/A')}")

    def create_welcome_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignCenter)
        welcome_label = QLabel("欢迎使用 邻里+")
        font = QFont();
        font.setPointSize(24);
        font.setBold(True)
        welcome_label.setFont(font)
        welcome_label.setAlignment(Qt.AlignCenter)
        step1_label = QLabel("<b>第1步:</b> 从左侧列表中选择一个在线设备")
        step1_label.setAlignment(Qt.AlignCenter)
        step2_label = QLabel("<b>第2步:</b> 选择该设备的共享文件夹即可开始浏览")
        step2_label.setAlignment(Qt.AlignCenter)
        layout.addStretch()
        layout.addWidget(welcome_label)
        layout.addSpacing(20)
        layout.addWidget(step1_label)
        layout.addSpacing(10)
        layout.addWidget(step2_label)
        layout.addStretch()
        return page

    def show_my_shares_context_menu(self, pos):
        item = self.my_shares_list_widget.itemAt(pos)
        if not item or item.text() == "无共享文件夹":
            return
        share_name = item.text().split(' (')[0]
        menu = QMenu()
        remove_action = QAction(self.style().standardIcon(QStyle.SP_DialogCancelButton), "移除此共享", self)
        remove_action.triggered.connect(lambda: self.remove_local_share(share_name))
        menu.addAction(remove_action)
        menu.exec(self.my_shares_list_widget.mapToGlobal(pos))

    def remove_local_share(self, share_name_to_remove):
        reply = QMessageBox.question(self, "确认移除",
                                     f"你确定要停止共享 '{share_name_to_remove}' 吗？\n此操作不会删除你的文件。",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.No:
            return

        current_shares = get_config().get("shares", [])
        new_shares = [s for s in current_shares if s.get("name") != share_name_to_remove]
        config = get_config()
        config['shares'] = new_shares
        from core.config_loader import CONFIG_PATH
        import toml
        try:
            with open(CONFIG_PATH, "w", encoding='utf-8') as f:
                toml.dump(config, f)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法保存配置文件: {e}")
            return

        self.config_data = load_config(force_reload=True)
        self.controller.running_config = self.config_data
        self.update_my_shares_list()
        self.controller.restart_file_watcher()
        if self.api_client:
            self.api_client.notify_shares_changed()
        self.add_log_message(f"已停止共享: {share_name_to_remove}", "️")

    def setup_timers(self):
        self.peer_update_timer = QTimer(self)
        self.peer_update_timer.timeout.connect(self.update_device_list)
        self.peer_update_timer.start(5000)

    def setup_websocket(self):
        ws_local_uri = f"ws://127.0.0.1:{self.controller.port}/ws/events"
        self.ws_local_thread = WebSocketClientThread(ws_local_uri, 'local')
        self.ws_local_thread.message_received.connect(self.handle_websocket_message)
        self.ws_local_thread.start()

    def open_settings(self):
        dialog = SettingsWindow(self.controller, self)
        if dialog.exec():
            self.config_data = load_config(force_reload=True)
            if not self.config_data:
                QMessageBox.critical(self, "错误", "重新加载配置文件失败，请检查文件格式或重启应用。")
                return

            self.controller.running_config = self.config_data
            new_name_from_file = self.config_data.get("service", {}).get("name", "未知设备")
            self.device_name_label.setText(f"<b>设备名 (下次启动生效):</b> {new_name_from_file}")

            self.update_my_shares_list()
            self.controller.restart_file_watcher()

            if self.api_client:
                self.api_client.notify_shares_changed()

            self.add_log_message("配置已更新，并已通知网络。", "⚙️")
            QMessageBox.information(self, "设置已保存", "设置已成功保存。\n共享文件夹的更改已立即生效。")

    def show_about_dialog(self):
        QMessageBox.about(self, "关于 邻里+",
                          "<b>邻里+ (NetNeighbor Plus)</b><br><br>"
                          "一个基于 Python 和 PySide6 的局域网文件共享工具。<br>"
                          "旨在提供一个简单、轻量、跨平台的本地网络文件传输解决方案。<br><br>"
                          "版本: 1.5.0 (Crash Fix)")

    def add_log_message(self, message: str, icon: str = "ℹ️"):
        from datetime import datetime
        timestamp = datetime.now().strftime('%H:%M:%S')
        self.log_text_edit.append(f"{icon} [{timestamp}] {message}")

    def handle_websocket_message(self, message: str, source: str):
        try:
            data = json.loads(message)
            event = data.get("event")

            if source == 'local':
                if event == "ws_local_connected":
                    self.add_log_message("已连接到本机事件服务。", "✅")
                elif event == "peer_online":
                    self.add_log_message(f"设备已上线: {data.get('name')}", "🟢"); self.update_device_list()
                elif event == "peer_offline":
                    self.add_log_message(f"设备已下线: {data.get('name')}", "🔴"); self.update_device_list()
            elif source == 'remote':
                if event == "ws_remote_connected":
                    self.add_log_message("已连接到远程设备事件服务。", "🔗")
                elif event == "shares_updated":
                    device_name = data.get("device_name")
                    self.add_log_message(f"收到通知：设备 {device_name} 的共享列表已更新。", "🔄")
                    if self.device_list_widget.currentItem():
                        self.handle_device_click(self.device_list_widget.currentItem(), force_refresh=True)
                elif event == "refresh_files":
                    self.add_log_message("当前查看的设备文件系统变更，自动刷新...", "🔄")
                    self.refresh_current_file_view()
        except json.JSONDecodeError:
            print(f"收到无法解析的WebSocket消息 ({source}): {message}")

    def format_size(self, size_bytes):
        if size_bytes <= 0: return ""
        size_name = ("B", "KB", "MB", "GB", "TB")
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {size_name[i]}"

    def show_file_context_menu(self, pos):
        if not self.active_peer_client or not self.device_list_widget.currentItem(): return
        selected_items = self.file_table_widget.selectedItems()
        if not selected_items: return
        selected_row = self.file_table_widget.row(selected_items[0])
        item_type = self.file_table_widget.item(selected_row, 1).text()
        if item_type == "文件夹": return
        menu = QMenu()
        download_action = QAction(self.download_icon, "下载", self)
        download_action.triggered.connect(self.handle_download_action)
        menu.addAction(download_action)
        menu.exec(self.file_table_widget.mapToGlobal(pos))

    def handle_download_action(self):
        selected_row = self.file_table_widget.currentRow()
        if selected_row < 0: return
        file_name = self.file_table_widget.item(selected_row, 0).text()
        remote_file_path = "/".join(self.active_path_stack + [file_name])
        save_path, _ = QFileDialog.getSaveFileName(self, "保存文件", os.path.join(os.path.expanduser('~'), file_name))
        if not save_path: return
        task_args = {'peer_client': self.active_peer_client, 'share_name': self.share_selector_combo.currentText(),
                     'remote_path': remote_file_path, 'save_path': save_path}
        self.start_worker_thread("download_http", "正在下载...", task_args)

    def handle_upload_action(self):
        local_file_path, _ = QFileDialog.getOpenFileName(self, "选择要上传的文件")
        if not local_file_path: return
        self.add_log_message(f"开始上传文件: {os.path.basename(local_file_path)}", "⬆️")
        task_args = {'peer_client': self.active_peer_client,
                     'share_name': self.share_selector_combo.currentText(),
                     'dest_path': "/".join(self.active_path_stack),
                     'local_file_path': local_file_path}
        self.start_worker_thread("upload", "正在上传...", task_args)

    def start_worker_thread(self, task_type, progress_title, kwargs):
        if self.worker_thread and self.worker_thread.isRunning():
            QMessageBox.warning(self, "任务正在进行", "当前已有文件在传输中，请等待完成后再试。")
            return
        self.progress_dialog = QProgressDialog(progress_title, "取消", 0, 100, self)
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.setAutoClose(False)
        self.progress_dialog.setAutoReset(False)
        self.worker_thread = WorkerThread(task_type, **kwargs)
        self.worker_thread.progress.connect(self.progress_dialog.setValue)
        self.worker_thread.finished.connect(self.on_worker_finished)
        self.worker_thread.error.connect(self.on_worker_error)
        self.progress_dialog.canceled.connect(self.worker_thread.terminate)
        self.worker_thread.start()
        self.progress_dialog.show()

    def on_worker_finished(self, message):
        self.progress_dialog.setValue(100)
        self.progress_dialog.close()
        QMessageBox.information(self, "传输成功", message)
        self.add_log_message(message, "✅")
        self.refresh_current_file_view()
        self.worker_thread = None

    def on_worker_error(self, error_message):
        self.progress_dialog.close()
        QMessageBox.critical(self, "传输错误", f"发生错误: {error_message}")
        self.add_log_message(f"传输错误: {error_message}", "❌")
        self.worker_thread = None

    def on_item_double_clicked(self, item: QTableWidgetItem):
        selected_row = self.file_table_widget.row(item)
        if self.file_table_widget.item(selected_row, 1).text() == "文件夹":
            folder_name = self.file_table_widget.item(selected_row, 0).text()
            self.active_path_stack.append(folder_name)
            self.refresh_current_file_view()

    def go_back_directory(self):
        if self.active_path_stack:
            self.active_path_stack.pop()
            self.refresh_current_file_view()

    def refresh_current_file_view(self):
        if not self.active_peer_client or not self.share_selector_combo.currentText():
            self.update_file_table(None)
            return
        current_path = "/" + "/".join(self.active_path_stack)
        self.current_path_label.setText(current_path)
        self.back_button.setEnabled(bool(self.active_path_stack))
        files = self.active_peer_client.get_files(self.share_selector_combo.currentText(), current_path)
        self.update_file_table(files)

    def update_device_list(self):
        if not self.api_client: return
        peers = self.api_client.get_peers()
        new_online_data = {}
        if peers:
            my_full_service_name = f"{self.controller.service_name}._netneighbor._tcp.local."
            new_online_data = {name: data for name, data in peers.items() if name != my_full_service_name}

        current_service_names = set(self.online_devices_data.keys())
        new_service_names = set(new_online_data.keys())
        self.online_devices_data = new_online_data
        self.status_bar_label.setText(f"发现 {len(self.online_devices_data)} 个在线设备。")

        to_add = new_service_names - current_service_names
        to_remove = current_service_names - new_service_names

        for i in range(self.device_list_widget.count() - 1, -1, -1):
            item = self.device_list_widget.item(i)
            if item and item.data(100) in to_remove:
                self.device_list_widget.takeItem(i)

        for service_name in sorted(list(to_add)):
            data = self.online_devices_data[service_name]
            display_name = service_name.split('._netneighbor._tcp.local.')[0]
            dev_type = data.get("properties", {}).get("dev_type", "未知设备")
            list_item = QListWidgetItem(f"{display_name}  类型：{dev_type}")
            list_item.setIcon(self.style().standardIcon(QStyle.SP_DriveNetIcon))
            list_item.setData(100, service_name)
            self.device_list_widget.addItem(list_item)

    def clear_active_peer_view(self):
        self.active_peer_client = None
        if self.ws_remote_thread and self.ws_remote_thread.isRunning():
            self.ws_remote_thread.stop()
        self.ws_remote_thread = None
        self.share_selector_combo.clear()
        self.share_selector_combo.setEnabled(False)
        self.file_table_widget.setRowCount(0)
        self.upload_button.setEnabled(False)
        self.back_button.setEnabled(False)
        self.right_stack.setCurrentWidget(self.welcome_page)
        self.status_bar_label.setText("就绪")

    def handle_device_click(self, clicked_item: QListWidgetItem, force_refresh: bool = False):
        if clicked_item is None: return
        service_name = clicked_item.data(100)
        device_data = self.online_devices_data.get(service_name)
        if not device_data: return

        self.right_stack.setCurrentWidget(self.file_browser_page)
        new_base_url = f"http://{device_data['address']}:{device_data['port']}"

        # --- 【核心修复】确保旧线程被可靠地停止和清理 ---
        if self.ws_remote_thread and self.ws_remote_thread.isRunning():
            self.ws_remote_thread.stop()  # 调用新的、健壮的 stop 方法

        ws_remote_uri = f"ws://{device_data['address']}:{device_data['port']}/ws/events"
        self.ws_remote_thread = WebSocketClientThread(ws_remote_uri, 'remote')
        self.ws_remote_thread.message_received.connect(self.handle_websocket_message)
        self.ws_remote_thread.start()

        self.active_path_stack = []
        self.active_peer_client = ApiClient(new_base_url)
        self.add_log_message(f"已连接到设备: {clicked_item.text().splitlines()[0]}", "🔌")
        self.measure_ping(self.active_peer_client, service_name.split('.')[0])

        self.share_selector_combo.blockSignals(True)
        self.share_selector_combo.clear()
        shares = self.active_peer_client.get_shares()
        if shares:
            self.share_selector_combo.addItems([s['name'] for s in shares])
            self.share_selector_combo.setEnabled(True)
            self.upload_button.setEnabled(True)
        else:
            self.share_selector_combo.setEnabled(False)
            self.upload_button.setEnabled(False)
            self.update_file_table(None)
        self.share_selector_combo.blockSignals(False)

        if self.share_selector_combo.count() > 0:
            self.handle_share_selection_change(0)

    def handle_share_selection_change(self, index):
        if index == -1:
            self.update_file_table(None)
            return
        self.active_path_stack = []
        self.refresh_current_file_view()

    def measure_ping(self, client: ApiClient, name: str):
        def do_ping():
            start_time = time.perf_counter()
            if client.get_ping():
                delay = int((time.perf_counter() - start_time) * 1000)
                self.status_bar_label.setText(f"已连接到 {name} | 延迟: {delay}ms")
            else:
                self.status_bar_label.setText(f"无法 Ping 通 {name}")

        threading.Thread(target=do_ping, daemon=True).start()

    def update_file_table(self, files: Optional[list]):
        self.file_table_widget.setRowCount(0)
        if files is None: return

        files.sort(key=lambda x: (not x['is_dir'], x['name'].lower()))
        self.file_table_widget.setRowCount(len(files))

        for row, file_info in enumerate(files):
            name_item = QTableWidgetItem(file_info['name'])
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            name_item.setIcon(self.folder_icon if file_info['is_dir'] else self.file_icon)

            type_item = QTableWidgetItem("文件夹" if file_info['is_dir'] else "文件")
            type_item.setFlags(type_item.flags() & ~Qt.ItemIsEditable)

            size_item = QTableWidgetItem(self.format_size(file_info['size']))
            size_item.setFlags(size_item.flags() & ~Qt.ItemIsEditable)
            size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

            self.file_table_widget.setItem(row, 0, name_item)
            self.file_table_widget.setItem(row, 1, type_item)
            self.file_table_widget.setItem(row, 2, size_item)

    def closeEvent(self, event):
        if self.worker_thread and self.worker_thread.isRunning():
            reply = QMessageBox.question(self, "退出确认", "有文件正在传输中，确定要强制退出吗？",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No:
                event.ignore()
                return
            else:
                self.worker_thread.terminate()

        print("应用正在关闭，开始清理线程...")

        # --- 【核心修复】在关闭时也使用可靠的停止方法 ---
        if self.ws_local_thread: self.ws_local_thread.stop()
        if self.ws_remote_thread: self.ws_remote_thread.stop()

        self.controller.stop_all_services()
        print("所有服务和线程已请求停止。应用退出。")
        event.accept()

    def update_my_shares_list(self):
        self.my_shares_list_widget.clear()
        shares = self.config_data.get("shares", [])
        if not shares:
            item = QListWidgetItem("无共享文件夹")
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            self.my_shares_list_widget.addItem(item)
            return

        for share in shares:
            name = share.get('name', '未命名共享')
            permissions = "可读/写" if "upload" in share.get("permissions", []) else "只读"
            item = QListWidgetItem(f"{name} ({permissions})")
            item.setToolTip(share.get('path'))
            item.setIcon(self.folder_icon)
            self.my_shares_list_widget.addItem(item)