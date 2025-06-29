# 文件: gui/main_window.py
# 描述: 应用的主窗口，负责UI的整体布局和用户交互逻辑。

import asyncio
import json
import math
import os
import socket
import threading
import time
from typing import Any, Dict, List, Optional
import toml

import websockets
from PySide6.QtCore import QCoreApplication, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QFont, QIcon
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox,
                               QDialog, QFileDialog, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMenu,
                               QMessageBox, QProgressDialog, QPushButton,
                               QStackedWidget, QStatusBar, QStyle,
                               QTableWidget, QTableWidgetItem, QTextEdit,
                               QVBoxLayout, QWidget)

from .api_client import ApiClient, UploadStreamer
from .app_controller import AppController
from .settings_window import SettingsWindow
from core.config_loader import get_config, load_config, CONFIG_PATH


class WebSocketClientThread(QThread):
    """
    一个专门用于处理 WebSocket 连接的 QThread。

    它在独立的事件循环中运行，以避免阻塞主UI线程，
    并实现了可靠的停止机制。
    """
    message_received = Signal(str, str)

    def __init__(self, uri: str, source: str):
        super().__init__()
        self.uri = uri
        self.source = source
        self._is_running = True
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.task: Optional[asyncio.Task] = None

    async def listen(self):
        """主异步循环，负责连接、接收消息和重连。"""
        while self._is_running:
            try:
                connect_kwargs = {
                    "open_timeout": 5,
                    "close_timeout": 5
                }
                async with websockets.connect(self.uri, **connect_kwargs) as ws:
                    print(f"WebSocket ({self.source}) 已连接到 {self.uri}")
                    self.message_received.emit(
                        json.dumps({"event": f"ws_{self.source}_connected"}),
                        self.source
                    )
                    while self._is_running:
                        try:
                            message = await asyncio.wait_for(ws.recv(), timeout=1.0)
                            self.message_received.emit(message, self.source)
                        except asyncio.TimeoutError:
                            await asyncio.sleep(0.1)
                        except websockets.exceptions.ConnectionClosed:
                            if self._is_running:
                                print(f"WebSocket ({self.source}) 连接已关闭。")
                            break
            except asyncio.CancelledError:
                break
            except Exception as e:
                if self._is_running:
                    print(
                        f"WebSocket ({self.source}) 连接错误: {e}。5秒后重连..."
                    )
                    self.message_received.emit(
                        json.dumps({"event": f"ws_{self.source}_disconnected"}),
                        self.source
                    )
                    for _ in range(50):
                        if not self._is_running:
                            break
                        await asyncio.sleep(0.1)

    def run(self):
        """QThread 的入口点，设置并运行 asyncio 事件循环。"""
        try:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.task = self.loop.create_task(self.listen())
            self.loop.run_until_complete(self.task)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            if self._is_running:
                print(f"WebSocket ({self.source}) 线程发生意外错误: {e}")
        finally:
            if self.loop and self.loop.is_running():
                self.loop.stop()
            if self.loop and not self.loop.is_closed():
                self.loop.close()
            print(f"WebSocket ({self.source}) 线程已干净地终止。")

    def stop(self):
        """请求并等待线程的可靠停止。"""
        if not self.isRunning():
            return

        print(f"正在请求停止 WebSocket ({self.source}) 线程...")
        self._is_running = False

        if self.loop and self.task and not self.task.done():
            self.loop.call_soon_threadsafe(self.task.cancel)

        if not self.wait(2000):
            print(f"警告: WebSocket ({self.source}) 线程超时，强制终止。")
            self.terminate()


class WorkerThread(QThread):
    """用于执行耗时文件传输任务（下载/上传）的通用工作线程。"""
    progress = Signal(int)
    finished = Signal(str)
    error = Signal(str)
    # 【多文件下载】为批量任务新增信号
    file_finished = Signal(str)
    all_finished = Signal()

    def __init__(self, task_type: str, **kwargs):
        super().__init__()
        self.task_type = task_type
        self.kwargs = kwargs

    def run(self):
        """根据任务类型分派到具体的执行函数。"""
        try:
            task_map = {
                "download_multiple": self._run_download_multiple,
                "upload_multiple": self._run_upload_multiple,
            }
            task_func = task_map.get(self.task_type)
            if task_func:
                task_func()
            else:
                self.error.emit(f"未知的任务类型: {self.task_type}")
        except Exception as e:
            self.error.emit(str(e))

    def _run_download_multiple(self):
        """执行批量HTTP下载。"""
        items_to_download = self.kwargs['items']
        save_dir = self.kwargs['save_dir']
        peer_client = self.kwargs['peer_client']
        share_name = self.kwargs['share_name']
        active_path_stack = self.kwargs['path_stack']
        total_items = len(items_to_download)

        for i, item_info in enumerate(items_to_download):
            file_name = item_info['name']
            relative_path = "/".join(active_path_stack + [file_name])
            save_path = os.path.join(save_dir, file_name)

            try:
                with peer_client.download_file_stream(share_name, relative_path) as resp:
                    resp.raise_for_status()
                    total_size = int(resp.headers.get('content-length', 0))
                    dl_size = 0
                    with open(save_path, "wb") as f:
                        for chunk in resp.iter_bytes(chunk_size=8192):
                            f.write(chunk)
                            dl_size += len(chunk)

                    self.file_finished.emit(f"({i + 1}/{total_items}) 文件 '{file_name}' 下载完成。")
            except Exception as e:
                self.error.emit(f"下载 '{file_name}' 失败: {e}")
                continue  # 继续下载下一个文件

        self.all_finished.emit()

    def _run_upload_multiple(self):
        """执行批量文件上传。"""
        local_files = self.kwargs['local_files']
        peer_client = self.kwargs['peer_client']
        share_name = self.kwargs['share_name']
        dest_path = self.kwargs['dest_path']
        total_items = len(local_files)

        for i, file_path in enumerate(local_files):
            file_name = os.path.basename(file_path)
            try:
                with UploadStreamer(file_path) as uploader:
                    peer_client.upload_file_stream(share_name, dest_path, uploader)
                self.file_finished.emit(f"({i + 1}/{total_items}) 文件 '{file_name}' 上传成功。")
            except Exception as e:
                self.error.emit(f"上传 '{file_name}' 失败: {e}")
                continue

        self.all_finished.emit()


class MainWindow(QMainWindow):
    """应用主窗口类，聚合所有UI和核心交互逻辑。"""

    def __init__(self, controller: AppController):
        super().__init__()
        self.controller = controller
        self.my_ip = self._get_my_ip()
        self.api_client: Optional[ApiClient] = None
        self.online_devices_data: Dict[str, Any] = {}
        self.active_peer_client: Optional[ApiClient] = None
        self.active_path_stack: List[str] = []
        self.worker_thread: Optional[WorkerThread] = None
        self.ws_local_thread: Optional[WebSocketClientThread] = None
        self.ws_remote_thread: Optional[WebSocketClientThread] = None
        self.progress_dialog: Optional[QProgressDialog] = None

        self._setup_window()
        self._load_icons()
        self._setup_ui()
        self.update_my_shares_list()
        self.controller.device_info_updated.connect(
            self.update_local_status_display
        )

    def post_init_setup(self):
        print("后端服务已就绪, UI开始进行网络初始化...")
        base_url = f"http://{self.my_ip}:{self.controller.port}"
        self.api_client = ApiClient(base_url)
        self._setup_timers()
        self._setup_websocket()
        self.update_local_status_display()
        self.update_device_list()

    def _get_my_ip(self) -> str:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"

    def _load_icons(self):
        style = self.style()
        self.folder_icon = style.standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        self.file_icon = style.standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        self.back_icon = style.standardIcon(QStyle.StandardPixmap.SP_ArrowLeft)
        self.upload_icon = style.standardIcon(QStyle.StandardPixmap.SP_ArrowUp)
        self.download_icon = style.standardIcon(QStyle.StandardPixmap.SP_ArrowDown)
        self.settings_icon = style.standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
        self.help_icon = style.standardIcon(QStyle.StandardPixmap.SP_DialogHelpButton)
        self.device_icon = style.standardIcon(QStyle.StandardPixmap.SP_DriveNetIcon)

    def _setup_window(self):
        self.setWindowTitle("邻里+ (NetNeighbor Plus)")
        self.setGeometry(100, 100, 1200, 700)
        self.setWindowIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        try:
            center_point = self.screen().availableGeometry().center()
            frame_geometry = self.frameGeometry()
            frame_geometry.moveCenter(center_point)
            self.move(frame_geometry.topLeft())
        except AttributeError:
            self.setGeometry(100, 100, 1200, 700)

    def _setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        self._create_menu_bar()
        self._create_status_box(main_layout)
        self._create_main_panels(main_layout)
        self._create_status_bar()

    def _create_menu_bar(self):
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("文件")
        settings_action = QAction(self.settings_icon, "设置...", self)
        settings_action.triggered.connect(self.open_settings)
        file_menu.addAction(settings_action)
        help_menu = menu_bar.addMenu("帮助")
        about_action = QAction(self.help_icon, "关于...", self)
        about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(about_action)

    def _create_status_box(self, parent_layout: QVBoxLayout):
        my_status_box = QGroupBox("本机状态")
        my_status_box.setObjectName("StatusGroupBox")
        my_status_layout = QHBoxLayout(my_status_box)
        self.device_name_label = QLabel("设备名: 正在检测...")
        self.device_type_label = QLabel("类型: 未知")
        my_ip_label = QLabel(f"IP地址: {self.my_ip}:{self.controller.port}")
        my_status_layout.addWidget(self.device_name_label)
        my_status_layout.addSpacing(20)
        my_status_layout.addWidget(self.device_type_label)
        my_status_layout.addStretch()
        my_status_layout.addWidget(my_ip_label)
        parent_layout.addWidget(my_status_box)

    def _create_main_panels(self, parent_layout: QVBoxLayout):
        interaction_layout = QHBoxLayout()
        left_panel = self._create_left_panel()
        interaction_layout.addWidget(left_panel)
        self.right_stack = QStackedWidget()
        self.welcome_page = self._create_welcome_page()
        self.file_browser_page = self._create_file_browser_page()
        self.right_stack.addWidget(self.welcome_page)
        self.right_stack.addWidget(self.file_browser_page)
        interaction_layout.addWidget(self.right_stack, stretch=1)
        parent_layout.addLayout(interaction_layout, stretch=1)
        self.right_stack.setCurrentWidget(self.welcome_page)

    def _create_left_panel(self) -> QWidget:
        left_panel_widget = QWidget()
        left_panel_layout = QVBoxLayout(left_panel_widget)
        left_panel_widget.setFixedWidth(280)
        left_panel_layout.setContentsMargins(0, 10, 0, 0)
        left_panel_layout.addWidget(QLabel("<h4>在线设备</h4>"))
        self.device_list_widget = QListWidget()
        self.device_list_widget.itemClicked.connect(self.handle_device_click)
        # 【功能4】移除虚线框
        self.device_list_widget.setStyleSheet("QListWidget::item:focus { border: none; outline: none; }")
        left_panel_layout.addWidget(self.device_list_widget, stretch=3)
        my_shares_header_layout = QHBoxLayout()
        my_shares_header_layout.addWidget(QLabel("<h4>本机共享</h4>"))
        my_shares_header_layout.addStretch()
        self.manage_shares_button = QPushButton("管理...")
        self.manage_shares_button.clicked.connect(self.open_settings)
        my_shares_header_layout.addWidget(self.manage_shares_button)
        left_panel_layout.addLayout(my_shares_header_layout)
        self.my_shares_list_widget = QListWidget()
        self.my_shares_list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.my_shares_list_widget.customContextMenuRequested.connect(self.show_my_shares_context_menu)
        # 【功能4】移除虚线框
        self.my_shares_list_widget.setStyleSheet("QListWidget::item:focus { border: none; outline: none; }")
        left_panel_layout.addWidget(self.my_shares_list_widget, stretch=2)
        left_panel_layout.addWidget(QLabel("<h4>事件日志</h4>"))
        self.log_text_edit = QTextEdit()
        self.log_text_edit.setReadOnly(True)
        left_panel_layout.addWidget(self.log_text_edit, stretch=2)
        return left_panel_widget

    def _create_file_browser_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 0, 0)
        toolbar_layout = QHBoxLayout()
        self.share_selector_combo = QComboBox()
        self.share_selector_combo.currentIndexChanged.connect(self.handle_share_selection_change)
        self.back_button = QPushButton(self.back_icon, "返回")
        self.back_button.clicked.connect(self.go_back_directory)
        self.current_path_label = QLineEdit("/")
        self.current_path_label.setReadOnly(True)
        self.upload_button = QPushButton(self.upload_icon, "上传")
        self.upload_button.clicked.connect(self.handle_upload_action)
        toolbar_layout.addWidget(self.share_selector_combo)
        toolbar_layout.addWidget(self.back_button)
        toolbar_layout.addWidget(QLabel("当前路径:"))
        toolbar_layout.addWidget(self.current_path_label, stretch=1)
        toolbar_layout.addWidget(self.upload_button)
        layout.addLayout(toolbar_layout)
        self.file_table_widget = QTableWidget()
        self.file_table_widget.setColumnCount(3)
        self.file_table_widget.setHorizontalHeaderLabels(["文件名", "类型", "大小"])
        # 【功能3】允许多选
        self.file_table_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.file_table_widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        # 【功能2】修复表头拉伸问题
        header = self.file_table_widget.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.file_table_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.file_table_widget.customContextMenuRequested.connect(self.show_file_context_menu)
        self.file_table_widget.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.file_table_widget.setAlternatingRowColors(True)
        self.file_table_widget.setShowGrid(False)
        self.file_table_widget.verticalHeader().setVisible(False)
        layout.addWidget(self.file_table_widget)
        return page

    def _create_welcome_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_label = QLabel("欢迎使用 邻里+")
        font = QFont()
        font.setPointSize(24)
        font.setBold(True)
        welcome_label.setFont(font)
        layout.addStretch()
        layout.addWidget(welcome_label)
        layout.addSpacing(20)
        layout.addWidget(QLabel("<b>第1步:</b> 从左侧列表中选择一个在线设备"))
        layout.addSpacing(10)
        layout.addWidget(QLabel("<b>第2步:</b> 选择该设备的共享文件夹即可开始浏览"))
        layout.addStretch()
        return page

    def _create_status_bar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar_label = QLabel("正在初始化...")
        self.status_bar.addWidget(self.status_bar_label, 1)

    def update_local_status_display(self):
        device_name = self.controller.device_name
        self.device_name_label.setText(f"<b>设备名:</b> {device_name}")
        device_type = self.controller.device_properties.get('dev_type', '未知')
        self.device_type_label.setText(f"<b>类型:</b> {device_type}")

    def show_my_shares_context_menu(self, pos):
        """【功能5】显示本机共享列表的右键上下文菜单，增加权限设置。"""
        item = self.my_shares_list_widget.itemAt(pos)
        if not item or item.text() == "无共享文件夹":
            return

        share_name = item.text().split(' (')[0]
        all_shares = load_config(force_reload=True).get('shares', [])
        target_share = next((s for s in all_shares if s.get("name") == share_name), None)
        if not target_share:
            return

        menu = QMenu()
        permissions_menu = menu.addMenu("设置权限")

        current_perms = target_share.get("permissions", [])

        # 下载权限
        download_action = QAction("可下载", self, checkable=True)
        download_action.setChecked("download" in current_perms)
        download_action.toggled.connect(
            lambda checked: self._handle_local_share_permission_change(share_name, "download", checked)
        )
        permissions_menu.addAction(download_action)

        # 上传权限
        upload_action = QAction("可上传", self, checkable=True)
        upload_action.setChecked("upload" in current_perms)
        upload_action.toggled.connect(
            lambda checked: self._handle_local_share_permission_change(share_name, "upload", checked)
        )
        permissions_menu.addAction(upload_action)

        menu.addSeparator()

        remove_action = QAction("移除此共享", self)
        remove_action.triggered.connect(lambda: self.remove_local_share(share_name))
        menu.addAction(remove_action)

        menu.exec(self.my_shares_list_widget.mapToGlobal(pos))

    def _handle_local_share_permission_change(self, share_name: str, perm: str, checked: bool):
        """【功能5】处理右键菜单中的权限变更。"""
        config = load_config(force_reload=True)
        if not config: return

        for share in config.get("shares", []):
            if share.get("name") == share_name:
                if "permissions" not in share:
                    share["permissions"] = ["read"]

                # 添加或移除权限
                if checked and perm not in share["permissions"]:
                    share["permissions"].append(perm)
                elif not checked and perm in share["permissions"]:
                    share["permissions"].remove(perm)

                break

        try:
            with open(CONFIG_PATH, "w", encoding='utf-8') as f:
                toml.dump(config, f)

            # 立即应用更改
            self.controller.running_config = config
            self.update_my_shares_list()
            if self.api_client:
                self.api_client.notify_shares_changed()
            self.add_log_message(f"共享 '{share_name}' 的权限已更新。", "🔧")

        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法保存配置文件: {e}")

    def remove_local_share(self, share_name_to_remove: str):
        reply = QMessageBox.question(self, "确认移除", f"确定要停止共享 '{share_name_to_remove}' 吗？")
        if reply == QMessageBox.StandardButton.No: return
        config = get_config()
        config['shares'] = [s for s in config.get("shares", []) if s.get("name") != share_name_to_remove]
        try:
            with open(CONFIG_PATH, "w", encoding='utf-8') as f:
                toml.dump(config, f)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法保存配置文件: {e}")
            return
        self.controller.running_config = load_config(force_reload=True)
        self.update_my_shares_list()
        self.controller.restart_file_watcher()
        if self.api_client: self.api_client.notify_shares_changed()
        self.add_log_message(f"已停止共享: {share_name_to_remove}", "️")

    def _setup_timers(self):
        self.peer_update_timer = QTimer(self)
        self.peer_update_timer.timeout.connect(self.update_device_list)
        self.peer_update_timer.start(5000)

    def _setup_websocket(self):
        ws_local_uri = f"ws://127.0.0.1:{self.controller.port}/ws/events"
        self.ws_local_thread = WebSocketClientThread(ws_local_uri, 'local')
        self.ws_local_thread.message_received.connect(self.handle_websocket_message)
        self.ws_local_thread.start()

    def open_settings(self):
        dialog = SettingsWindow(self.controller, self)
        if dialog.exec():
            self.controller.running_config = load_config(force_reload=True)
            self.update_my_shares_list()
            self.controller.restart_file_watcher()
            if self.api_client: self.api_client.notify_shares_changed()
            self.add_log_message("配置已更新。", "⚙️")
            QMessageBox.information(self, "设置已保存", "设置已成功保存。")

    def show_about_dialog(self):
        QMessageBox.about(self, "关于 邻里+", "<b>邻里+ (NetNeighbor Plus)</b><br><br>" "版本: 1.9.0 (Feature Pack)")

    def add_log_message(self, message: str, icon: str = "ℹ️"):
        timestamp = time.strftime('%H:%M:%S')
        self.log_text_edit.append(f"{icon} [{timestamp}] {message}")

    def handle_websocket_message(self, message: str, source: str):
        try:
            data = json.loads(message)
            event = data.get("event")
            if source == 'local':
                if event == "ws_local_connected":
                    self.add_log_message("已连接到本机事件服务。", "✅")
                elif event == "peer_online":
                    self.add_log_message(f"设备上线: {data.get('name')}", "🟢"); self.update_device_list()
                elif event == "peer_offline":
                    self.add_log_message(f"设备下线: {data.get('name')}", "🔴"); self.update_device_list()
            elif source == 'remote':
                if event == "ws_remote_connected":
                    self.add_log_message("已连接到远程设备。", "🔗")
                elif event == "shares_updated":
                    self.add_log_message(f"设备 {data.get('device_name')} 的共享列表已更新。", "🔄")
                    if self.device_list_widget.currentItem() and self.active_peer_client:
                        self.handle_device_click(self.device_list_widget.currentItem(), force_refresh=True)
                elif event == "refresh_files":
                    self.add_log_message("远程文件系统变更，自动刷新...", "🔄");
                    self.refresh_current_file_view()
        except json.JSONDecodeError:
            pass

    def _format_size(self, size_bytes: int) -> str:
        if size_bytes <= 0: return ""
        size_name = ("B", "KB", "MB", "GB", "TB");
        i = int(math.floor(math.log(size_bytes, 1024)))
        power = math.pow(1024, i);
        size = round(size_bytes / power, 2)
        return f"{size} {size_name[i]}"

    def show_file_context_menu(self, pos):
        """【功能3】处理多选下载的右键菜单。"""
        selected_items = self.file_table_widget.selectedItems()
        if not selected_items: return

        # 只处理文件，忽略文件夹
        files_selected = any(self.file_table_widget.item(item.row(), 1).text() == '文件' for item in selected_items)
        if not files_selected: return

        menu = QMenu()
        download_action = QAction("下载选中项", self)
        download_action.triggered.connect(self.handle_download_action)
        menu.addAction(download_action)
        menu.exec(self.file_table_widget.mapToGlobal(pos))

    def handle_download_action(self):
        """【功能3】处理批量下载。"""
        selected_rows = sorted(list(set(item.row() for item in self.file_table_widget.selectedItems())))
        if not selected_rows: return

        items_to_download = []
        for row in selected_rows:
            if self.file_table_widget.item(row, 1).text() == '文件':
                items_to_download.append({'name': self.file_table_widget.item(row, 0).text()})

        if not items_to_download: return

        save_dir = QFileDialog.getExistingDirectory(self, "选择保存下载文件的文件夹", os.path.expanduser("~"))
        if not save_dir: return

        task_args = {
            'items': items_to_download,
            'save_dir': save_dir,
            'peer_client': self.active_peer_client,
            'share_name': self.share_selector_combo.currentText(),
            'path_stack': self.active_path_stack,
        }
        self.start_worker_thread("download_multiple", "正在批量下载...", task_args)

    def handle_upload_action(self):
        """【功能3】处理批量上传。"""
        local_files, _ = QFileDialog.getOpenFileNames(self, "选择要上传的文件")
        if not local_files: return

        self.add_log_message(f"开始上传 {len(local_files)} 个文件...", "⬆️")
        task_args = {
            'local_files': local_files,
            'peer_client': self.active_peer_client,
            'share_name': self.share_selector_combo.currentText(),
            'dest_path': "/".join(self.active_path_stack),
        }
        self.start_worker_thread("upload_multiple", "正在批量上传...", task_args)

    def start_worker_thread(self, task_type: str, progress_title: str, kwargs: dict):
        if self.worker_thread and self.worker_thread.isRunning():
            QMessageBox.warning(self, "任务正在进行", "已有文件在传输中。")
            return

        # 【功能3】改造进度对话框以适应批量任务
        self.progress_dialog = QProgressDialog(self)
        self.progress_dialog.setWindowTitle(progress_title)
        self.progress_dialog.setLabelText("准备开始...")
        self.progress_dialog.setRange(0, 0)  # 设置为不确定模式
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)

        self.worker_thread = WorkerThread(task_type, **kwargs)
        # self.worker_thread.progress.connect(self.progress_dialog.setValue) # 暂时不用
        self.worker_thread.file_finished.connect(self.on_worker_file_finished)
        self.worker_thread.all_finished.connect(self.on_worker_all_finished)
        self.worker_thread.error.connect(self.on_worker_error)
        self.progress_dialog.canceled.connect(self.worker_thread.terminate)

        self.worker_thread.start()
        self.progress_dialog.show()

    def on_worker_file_finished(self, message: str):
        """批量任务中，单个文件完成时的回调。"""
        self.log_text_edit.append(f"✅ {message}")
        self.progress_dialog.setLabelText(message)

    def on_worker_all_finished(self):
        """批量任务全部完成时的回调。"""
        if self.progress_dialog: self.progress_dialog.close()
        QMessageBox.information(self, "任务完成", "所有文件传输已完成。")
        self.add_log_message("所有文件传输已完成。", "🎉")
        self.refresh_current_file_view()
        self.worker_thread = None

    def on_worker_error(self, error_message: str):
        title = "传输错误";
        friendly_message = f"发生未知错误: {error_message}"
        error_lower = error_message.lower()
        if "403" in error_lower or "permission denied" in error_lower:
            title = "权限不足"
            if "download" in error_lower:
                friendly_message = "操作失败：对方未授予“下载”权限。"
            elif "upload" in error_lower:
                friendly_message = "操作失败：对方未授予“上传”权限。"
            else:
                friendly_message = "操作失败：对方未授予相应操作权限。"
        elif "404" in error_lower or "not found" in error_lower:
            title = "未找到文件";
            friendly_message = "操作失败：文件或文件夹在对方设备上已不存在。"
        elif "connectionrefusederror" in error_lower or "timed out" in error_lower:
            title = "连接失败";
            friendly_message = "无法连接到对方设备，请检查网络。"

        self.log_text_edit.append(f"❌ {friendly_message}")
        if self.progress_dialog and self.progress_dialog.isVisible():
            self.progress_dialog.setLabelText(f"错误: {friendly_message}")
            time.sleep(2)  # 让用户看到错误
        else:
            QMessageBox.critical(self, title, friendly_message)

    def on_item_double_clicked(self, item: QTableWidgetItem):
        row = self.file_table_widget.row(item)
        if self.file_table_widget.item(row, 1).text() == "文件夹":
            self.active_path_stack.append(item.text())
            self.refresh_current_file_view()

    def go_back_directory(self):
        if self.active_path_stack:
            self.active_path_stack.pop()
            self.refresh_current_file_view()

    def refresh_current_file_view(self):
        if not self.active_peer_client or not self.share_selector_combo.currentText(): return
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
            my_service_name = f"{self.controller.service_name}._netneighbor._tcp.local."
            new_online_data = {name: data for name, data in peers.items() if name != my_service_name}

        # 【功能1】修复状态栏文本
        if len(new_online_data) > 0:
            self.status_bar_label.setText(f"发现 {len(new_online_data)} 个在线设备。")
        else:
            self.status_bar_label.setText("就绪. 正在扫描局域网设备...")

        current_names = set(self.online_devices_data.keys())
        new_names = set(new_online_data.keys())
        self.online_devices_data = new_online_data
        to_add, to_remove = new_names - current_names, current_names - new_names

        for i in range(self.device_list_widget.count() - 1, -1, -1):
            item = self.device_list_widget.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) in to_remove: self.device_list_widget.takeItem(i)

        for name in sorted(list(to_add)):
            data = self.online_devices_data[name]
            display_name = name.split('._netneighbor._tcp.local.')[0]
            dev_type = data.get("properties", {}).get("dev_type", "未知")
            list_item = QListWidgetItem(f"{display_name}  类型: {dev_type}")
            list_item.setIcon(self.device_icon)
            list_item.setData(Qt.ItemDataRole.UserRole, name)
            self.device_list_widget.addItem(list_item)

    def clear_active_peer_view(self):
        self.active_peer_client = None
        if self.ws_remote_thread and self.ws_remote_thread.isRunning():
            self.ws_remote_thread.stop()
        self.ws_remote_thread = None
        self.share_selector_combo.clear()
        self.file_table_widget.setRowCount(0)
        self.right_stack.setCurrentWidget(self.welcome_page)

    def handle_device_click(self, clicked_item: QListWidgetItem, force_refresh: bool = False):
        if not clicked_item: return
        service_name = clicked_item.data(Qt.ItemDataRole.UserRole)
        device_data = self.online_devices_data.get(service_name)
        if not device_data: return
        self.right_stack.setCurrentWidget(self.file_browser_page)
        new_base_url = f"http://{device_data['address']}:{device_data['port']}"
        if not force_refresh or not self.active_peer_client or self.active_peer_client.base_url != new_base_url:
            self.active_peer_client = ApiClient(new_base_url)
            self.measure_ping(self.active_peer_client, service_name.split('.')[0])
            if self.ws_remote_thread and self.ws_remote_thread.isRunning():
                self.ws_remote_thread.stop()
            ws_remote_uri = f"ws://{device_data['address']}:{device_data['port']}/ws/events"
            self.ws_remote_thread = WebSocketClientThread(ws_remote_uri, 'remote')
            self.ws_remote_thread.message_received.connect(self.handle_websocket_message)
            self.ws_remote_thread.start()

        current_share_name = self.share_selector_combo.currentText()
        self.share_selector_combo.blockSignals(True);
        self.share_selector_combo.clear()
        shares = self.active_peer_client.get_shares()
        new_share_names = [s['name'] for s in shares] if shares else []
        if new_share_names: self.share_selector_combo.addItems(new_share_names)
        if current_share_name and current_share_name in new_share_names:
            self.share_selector_combo.setCurrentText(current_share_name)
        self.share_selector_combo.blockSignals(False)
        self.handle_share_selection_change(self.share_selector_combo.currentIndex())

    def handle_share_selection_change(self, index: int):
        if index == -1: self.update_file_table(None); return
        self.active_path_stack = []
        self.refresh_current_file_view()

    def measure_ping(self, client: ApiClient, name: str):
        def do_ping():
            start_time = time.perf_counter()
            if client.get_ping():
                delay = int((time.perf_counter() - start_time) * 1000)
                self.status_bar_label.setText(f"已连接到 {name} | 延迟: {delay}ms")

        threading.Thread(target=do_ping, daemon=True).start()

    def update_file_table(self, files: Optional[List[Dict[str, Any]]]):
        self.file_table_widget.setRowCount(0)
        if files is None: return
        files.sort(key=lambda x: (not x['is_dir'], x['name'].lower()))
        self.file_table_widget.setRowCount(len(files))
        for row, file_info in enumerate(files):
            name_item = QTableWidgetItem(file_info['name'])
            name_item.setIcon(self.folder_icon if file_info['is_dir'] else self.file_icon)
            type_item = QTableWidgetItem("文件夹" if file_info['is_dir'] else "文件")
            size_item = QTableWidgetItem(self._format_size(file_info['size']))
            size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.file_table_widget.setItem(row, 0, name_item)
            self.file_table_widget.setItem(row, 1, type_item)
            self.file_table_widget.setItem(row, 2, size_item)

    def closeEvent(self, event):
        if self.worker_thread and self.worker_thread.isRunning():
            reply = QMessageBox.question(self, "退出确认", "有文件正在传输，确定要强制退出吗？")
            if reply == QMessageBox.StandardButton.No:
                event.ignore(); return
            else:
                self.worker_thread.terminate()
        print("应用正在关闭，开始清理线程...")
        if self.ws_local_thread: self.ws_local_thread.stop()
        if self.ws_remote_thread: self.ws_remote_thread.stop()
        self.controller.stop_all_services()
        print("所有服务和线程已请求停止。应用退出。")
        event.accept()

    def update_my_shares_list(self):
        self.my_shares_list_widget.clear()
        shares = load_config(force_reload=True).get("shares", [])
        if not shares:
            item = QListWidgetItem("无共享文件夹")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.my_shares_list_widget.addItem(item)
            return
        for share in shares:
            name = share.get('name', '未命名共享')
            permissions = share.get("permissions", [])
            perm_parts = []
            if "read" in permissions: perm_parts.append("可读")
            if "download" in permissions: perm_parts.append("可下载")
            if "upload" in permissions: perm_parts.append("可上传")
            perm_text = "/".join(perm_parts) if perm_parts else "无权限"
            display_text = f"{name} ({perm_text})"
            item = QListWidgetItem(display_text)
            item.setToolTip(share.get('path'))
            item.setIcon(self.folder_icon)
            self.my_shares_list_widget.addItem(item)