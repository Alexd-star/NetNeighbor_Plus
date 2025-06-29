# 文件: gui/main_window.py (完整无省略最终版)
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
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QDialog,
                               QFileDialog, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMenu,
                               QMessageBox, QProgressDialog, QPushButton,
                               QStackedWidget, QStatusBar, QStyle,
                               QTableWidget, QTableWidgetItem, QTextEdit,
                               QVBoxLayout, QWidget, QComboBox)

from .api_client import ApiClient, UploadStreamer
from .app_controller import AppController
from .settings_window import SettingsWindow
from core.config_loader import get_config, load_config, CONFIG_PATH


class WebSocketClientThread(QThread):
    """
    用于在后台处理WebSocket连接的线程。
    它会持续监听来自服务器的消息，并通过信号(message_received)将消息发送给主线程。
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
        """异步监听WebSocket消息的核心循环。"""
        while self._is_running:
            try:
                # 设置连接超时，防止长时间无响应
                connect_kwargs = {"open_timeout": 5, "close_timeout": 5}
                async with websockets.connect(self.uri, **connect_kwargs) as ws:
                    print(f"WebSocket ({self.source}) 已连接到 {self.uri}")
                    self.message_received.emit(
                        json.dumps({"event": f"ws_{self.source}_connected"}),
                        self.source
                    )
                    while self._is_running:
                        try:
                            # 设置接收超时，允许线程在没有消息时也能响应停止信号
                            msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                            self.message_received.emit(msg, self.source)
                        except asyncio.TimeoutError:
                            # 超时是正常的，继续检查是否需要停止
                            await asyncio.sleep(0.1)
                        except websockets.exceptions.ConnectionClosed:
                            if self._is_running:
                                print(f"WebSocket ({self.source}) 连接已关闭。")
                            break
            except asyncio.CancelledError:
                # 任务被取消，正常退出
                break
            except Exception as e:
                # 其他连接错误，等待后重试
                if self._is_running:
                    print(f"WebSocket ({self.source}) 连接错误: {e}。5秒后重连...")
                    self.message_received.emit(
                        json.dumps({"event": f"ws_{self.source}_disconnected"}),
                        self.source
                    )
                    # 非阻塞式等待，允许快速响应停止信号
                    for _ in range(50):
                        if not self._is_running:
                            break
                        await asyncio.sleep(0.1)

    def run(self):
        """QThread的入口点，设置并运行asyncio事件循环。"""
        try:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.task = self.loop.create_task(self.listen())
            self.loop.run_until_complete(self.task)
        except asyncio.CancelledError:
            pass
        finally:
            # 清理事件循环
            if self.loop and self.loop.is_running():
                self.loop.stop()
            if self.loop and not self.loop.is_closed():
                self.loop.close()
            print(f"WebSocket ({self.source}) 线程已干净地终止。")

    def stop(self):
        """从外部请求停止线程。"""
        if not self.isRunning():
            return
        print(f"正在请求停止 WebSocket ({self.source}) 线程...")
        self._is_running = False
        # 在事件循环中安全地取消任务
        if self.loop and self.task and not self.task.done():
            self.loop.call_soon_threadsafe(self.task.cancel)
        # 等待线程自然结束，如果超时则强制终止
        if not self.wait(2000):
            print(f"警告: WebSocket ({self.source}) 线程超时，强制终止。")
            self.terminate()


class WorkerThread(QThread):
    """
    通用工作线程，处理所有耗时文件/文件夹传输任务。
    """
    progress = Signal(int)
    file_finished = Signal(str)
    all_finished = Signal()
    error = Signal(str)
    progress_text_update = Signal(str)

    def __init__(self, tasks: List[Dict]):
        super().__init__()
        self.tasks = tasks
        self.has_errors = False
        self._is_running = True

    def run(self):
        """线程主执行函数，按顺序处理任务列表。"""
        total_tasks = len(self.tasks)
        for i, task in enumerate(self.tasks):
            if not self._is_running:
                self.error.emit("任务被用户取消。")
                break

            self.progress_text_update.emit(f"({i + 1}/{total_tasks}) 正在处理: {task.get('name', 'N/A')}")

            try:
                task_type = task.get("type")
                if task_type == "download_file":
                    self._run_download_file(task)
                elif task_type == "download_folder":
                    self._run_download_folder(task)
                elif task_type == "upload_folder":
                    self._run_upload_folder(task)
                elif task_type == "upload_file":
                    self._run_upload_file(task)
                else:
                    raise ValueError(f"未知的任务类型: {task_type}")
            except Exception as e:
                # 对用户主动取消的操作进行特定处理，避免显示为错误
                if isinstance(e, InterruptedError):
                    self.error.emit(f"任务 '{task.get('name')}' 已被用户取消。")
                else:
                    self.error.emit(f"处理 '{task.get('name')}' 时出错: {e}")
                self.has_errors = True
                continue

        if not self.has_errors and self._is_running:
            self.all_finished.emit()

    def stop(self):
        """外部调用的停止方法。"""
        self._is_running = False

    def _run_download_file(self, task_info):
        """下载单个文件的具体实现。"""
        p_client = task_info['peer_client']
        s_name = task_info['share_name']
        r_path = task_info['remote_path']
        save_p = task_info['save_path']
        file_name = os.path.basename(save_p)

        with p_client.download_file_stream(s_name, r_path) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get('content-length', 0))
            dl_size = 0
            with open(save_p, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=8192):
                    if not self._is_running:
                        raise InterruptedError("Download cancelled")
                    f.write(chunk)
                    dl_size += len(chunk)
                    if total > 0:
                        self.progress.emit(int((dl_size / total) * 100))
        self.file_finished.emit(f"文件 '{file_name}' 下载完成！")

    def _run_download_folder(self, task_info):
        """下载文件夹为ZIP的具体实现。"""
        p_client = task_info['peer_client']
        s_name = task_info['share_name']
        r_path = task_info['remote_path']
        save_p = task_info['save_path']
        folder_name = task_info['name']

        self.progress_text_update.emit(f"服务器正在准备文件夹 '{folder_name}'...")

        with p_client.download_folder_stream(s_name, r_path) as resp:
            self.progress_text_update.emit(f"开始下载 '{folder_name}.zip'...")
            resp.raise_for_status()
            total = int(resp.headers.get('content-length', 0))
            dl_size = 0
            with open(save_p, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=8192):
                    if not self._is_running:
                        raise InterruptedError("Download cancelled")
                    f.write(chunk)
                    dl_size += len(chunk)
                    if total > 0:
                        self.progress.emit(int((dl_size / total) * 100))
        self.file_finished.emit(f"文件夹 '{folder_name}' 已成功下载为 '{os.path.basename(save_p)}'！")

    def _run_upload_folder(self, task_info):
        """上传整个文件夹的具体实现。"""
        local_folder_path = task_info['local_path']
        p_client = task_info['peer_client']
        s_name = task_info['share_name']
        base_dest_path = task_info['dest_path']
        folder_name = os.path.basename(local_folder_path)

        root_remote_path = os.path.join(base_dest_path, folder_name).replace('\\', '/')
        p_client.create_directory(s_name, root_remote_path)
        self.file_finished.emit(f"在远程创建目录: {root_remote_path}")

        files_to_upload = []
        for root, dirs, files in os.walk(local_folder_path):
            if not self._is_running: raise InterruptedError("Upload cancelled")

            rel_path = os.path.relpath(root, local_folder_path)
            for d in dirs:
                remote_dir_path = os.path.join(root_remote_path, rel_path, d).replace('\\', '/')
                p_client.create_directory(s_name, remote_dir_path)

            for f in files:
                remote_dest_folder = os.path.normpath(os.path.join(root_remote_path, rel_path)).replace('\\', '/')
                files_to_upload.append({
                    'local_file': os.path.join(root, f),
                    'remote_dest': remote_dest_folder
                })

        total_files = len(files_to_upload)
        for i, file_task in enumerate(files_to_upload):
            if not self._is_running: raise InterruptedError("Upload cancelled")

            local_file = file_task['local_file']
            remote_dest = file_task['remote_dest']
            file_name = os.path.basename(local_file)

            self.progress_text_update.emit(f"上传文件 ({i + 1}/{total_files}): {file_name}")
            self.progress.emit(0)

            def progress_callback(p):
                self.progress.emit(p)

            with UploadStreamer(local_file, progress_callback=progress_callback) as uploader:
                p_client.upload_file_stream(s_name, remote_dest, uploader)
            self.file_finished.emit(f"文件 '{file_name}' 上传成功。")

    def _run_upload_file(self, task_info):
        """上传单个文件的具体实现。"""
        local_path = task_info['local_path']
        p_client = task_info['peer_client']
        s_name = task_info['share_name']
        dest = task_info['dest_path']
        file_name = os.path.basename(local_path)

        def progress_callback(p): self.progress.emit(p)

        with UploadStreamer(local_path, progress_callback=progress_callback) as uploader:
            p_client.upload_file_stream(s_name, dest, uploader)
        self.file_finished.emit(f"文件 '{file_name}' 上传成功。")


class MainWindow(QMainWindow):
    """应用主窗口类，包含所有UI元素和交互逻辑。"""

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
        self.controller.device_info_updated.connect(self.update_local_status_display)

    def post_init_setup(self):
        """在后台服务启动后进行网络相关的初始化。"""
        self.add_log_message("后端服务已就绪, UI开始进行网络初始化...")
        base_url = f"http://{self.my_ip}:{self.controller.port}"
        self.api_client = ApiClient(base_url)
        self._setup_timers()
        self._setup_websocket()
        self.update_local_status_display()
        self.update_device_list()

    def _get_my_ip(self) -> str:
        """获取本机的局域网IP地址。"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"

    def _load_icons(self):
        """加载所有需要的图标资源。"""
        style = self.style()
        self.folder_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        self.file_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        self.upload_folder_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder)
        self.upload_file_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogToParent)
        self.back_icon = style.standardIcon(QStyle.StandardPixmap.SP_ArrowLeft)
        self.upload_icon = style.standardIcon(QStyle.StandardPixmap.SP_ArrowUp)
        self.download_icon = style.standardIcon(QStyle.StandardPixmap.SP_ArrowDown)
        self.settings_icon = style.standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
        self.help_icon = style.standardIcon(QStyle.StandardPixmap.SP_DialogHelpButton)
        self.device_icon = style.standardIcon(QStyle.StandardPixmap.SP_DriveNetIcon)

    def _setup_window(self):
        """设置主窗口的基本属性。"""
        self.setWindowTitle("邻里+ (NetNeighbor Plus)")
        self.setGeometry(100, 100, 1200, 700)
        self.setWindowIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        try:
            center = self.screen().availableGeometry().center()
            frame = self.frameGeometry()
            frame.moveCenter(center)
            self.move(frame.topLeft())
        except AttributeError:
            # 兼容一些无法获取屏幕信息的环境
            self.setGeometry(100, 100, 1200, 700)

    def _setup_ui(self):
        """创建并组装所有UI组件。"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        self._create_menu_bar()
        self._create_status_box(main_layout)
        self._create_main_panels(main_layout)
        self._create_status_bar()

    def _create_menu_bar(self):
        """创建顶部菜单栏。"""
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
        """创建顶部显示本机状态的区域。"""
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
        """创建主交互区，包含左侧面板和右侧堆叠窗口。"""
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
        """创建左侧面板，包含设备列表、本机共享和日志。"""
        left_panel_widget = QWidget()
        left_panel_layout = QVBoxLayout(left_panel_widget)
        left_panel_widget.setFixedWidth(280)
        left_panel_layout.setContentsMargins(0, 10, 0, 0)
        left_panel_layout.addWidget(QLabel("<h4>在线设备</h4>"))
        self.device_list_widget = QListWidget()
        self.device_list_widget.itemClicked.connect(self.handle_device_click)
        self.device_list_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
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
        self.my_shares_list_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        left_panel_layout.addWidget(self.my_shares_list_widget, stretch=2)
        left_panel_layout.addWidget(QLabel("<h4>事件日志</h4>"))
        self.log_text_edit = QTextEdit()
        self.log_text_edit.setReadOnly(True)
        left_panel_layout.addWidget(self.log_text_edit, stretch=2)
        return left_panel_widget

    def _create_file_browser_page(self) -> QWidget:
        """创建右侧的文件浏览页面。"""
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
        upload_menu = QMenu(self)
        upload_files_action = QAction(self.upload_file_icon, "上传文件...", self)
        upload_files_action.triggered.connect(lambda: self.handle_upload_action(is_folder=False))
        upload_folder_action = QAction(self.upload_folder_icon, "上传文件夹...", self)
        upload_folder_action.triggered.connect(lambda: self.handle_upload_action(is_folder=True))
        upload_menu.addAction(upload_files_action)
        upload_menu.addAction(upload_folder_action)
        self.upload_button.setMenu(upload_menu)

        toolbar_layout.addWidget(self.share_selector_combo)
        toolbar_layout.addWidget(self.back_button)
        toolbar_layout.addWidget(QLabel("当前路径:"))
        toolbar_layout.addWidget(self.current_path_label, stretch=1)
        toolbar_layout.addWidget(self.upload_button)
        layout.addLayout(toolbar_layout)

        self.file_table_widget = QTableWidget()
        self.file_table_widget.setColumnCount(4)
        self.file_table_widget.setHorizontalHeaderLabels(["", "文件名", "类型", "大小"])
        self.file_table_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.file_table_widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.file_table_widget.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.file_table_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.file_table_widget.customContextMenuRequested.connect(self.show_file_context_menu)
        self.file_table_widget.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.file_table_widget.setAlternatingRowColors(True)
        self.file_table_widget.setShowGrid(False)
        self.file_table_widget.verticalHeader().setVisible(False)
        self.file_table_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout.addWidget(self.file_table_widget)
        return page

    def _create_welcome_page(self) -> QWidget:
        """创建右侧的欢迎页面。"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_label = QLabel("欢迎使用 邻里+")
        font = QFont();
        font.setPointSize(24);
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
        """创建底部状态栏。"""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar_label = QLabel("正在初始化...")
        self.status_bar.addWidget(self.status_bar_label, 1)

    def update_local_status_display(self):
        """当控制器信息更新时，刷新UI上的本机状态。"""
        device_name = self.controller.device_name
        self.device_name_label.setText(f"<b>设备名:</b> {device_name}")
        device_type = self.controller.device_properties.get('dev_type', '未知')
        self.device_type_label.setText(f"<b>类型:</b> {device_type}")

    def show_my_shares_context_menu(self, pos):
        """显示本机共享列表的右键菜单。"""
        item = self.my_shares_list_widget.itemAt(pos)
        if not item or item.text() == "无共享文件夹": return
        share_name = item.text().split(' (')[0]
        all_shares = load_config(force_reload=True).get('shares', [])
        target_share = next((s for s in all_shares if s.get("name") == share_name), None)
        if not target_share: return
        menu = QMenu();
        permissions_menu = menu.addMenu("设置权限")
        current_perms = target_share.get("permissions", [])
        dl_action = QAction("可下载", self, checkable=True)
        dl_action.setChecked("download" in current_perms)
        dl_action.toggled.connect(
            lambda checked: self._handle_local_share_permission_change(share_name, "download", checked))
        permissions_menu.addAction(dl_action)
        ul_action = QAction("可上传", self, checkable=True)
        ul_action.setChecked("upload" in current_perms)
        ul_action.toggled.connect(
            lambda checked: self._handle_local_share_permission_change(share_name, "upload", checked))
        permissions_menu.addAction(ul_action)
        menu.addSeparator()
        remove_action = QAction("移除此共享", self)
        remove_action.triggered.connect(lambda: self.remove_local_share(share_name))
        menu.addAction(remove_action)
        menu.exec(self.my_shares_list_widget.mapToGlobal(pos))

    def _handle_local_share_permission_change(self, share_name: str, perm: str, checked: bool):
        """处理本机共享权限的更改。"""
        config = load_config(force_reload=True)
        if not config: return
        for share in config.get("shares", []):
            if share.get("name") == share_name:
                if "permissions" not in share: share["permissions"] = ["read"]
                if checked and perm not in share["permissions"]:
                    share["permissions"].append(perm)
                elif not checked and perm in share["permissions"]:
                    share["permissions"].remove(perm)
                break
        try:
            with open(CONFIG_PATH, "w", encoding='utf-8') as f:
                toml.dump(config, f)
            self.controller.running_config = config
            self.update_my_shares_list()
            if self.api_client: self.api_client.notify_shares_changed()
            self.add_log_message(f"共享 '{share_name}' 的权限已更新。", "🔧")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法保存配置文件: {e}")

    def remove_local_share(self, share_name_to_remove: str):
        """从配置中移除一个本机共享。"""
        reply = QMessageBox.question(self, "确认移除", f"确定要停止共享 '{share_name_to_remove}' 吗？",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
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
        """设置用于轮询设备列表的定时器。"""
        self.peer_update_timer = QTimer(self)
        self.peer_update_timer.timeout.connect(self.update_device_list)
        self.peer_update_timer.start(5000)

    def _setup_websocket(self):
        """初始化连接到本机的WebSocket客户端。"""
        ws_uri = f"ws://127.0.0.1:{self.controller.port}/ws/events"
        self.ws_local_thread = WebSocketClientThread(ws_uri, 'local')
        self.ws_local_thread.message_received.connect(self.handle_websocket_message)
        self.ws_local_thread.start()

    def open_settings(self):
        """打开设置窗口。"""
        dialog = SettingsWindow(self.controller, self)
        if dialog.exec():
            self.controller.running_config = load_config(force_reload=True)
            self.update_my_shares_list()
            self.controller.restart_file_watcher()
            if self.api_client: self.api_client.notify_shares_changed()
            self.add_log_message("配置已更新。", "⚙️")
            QMessageBox.information(self, "设置已保存", "设置已成功保存。", QMessageBox.Ok)

    def show_about_dialog(self):
        """显示关于对话框。"""
        QMessageBox.about(self, "关于 邻里+", "<b>邻里+ (NetNeighbor Plus)</b><br><br>版本: 3.2.0 (Full-Featured)")

    def add_log_message(self, message: str, icon: str = "ℹ️"):
        """向日志窗口添加一条带时间戳和图标的消息。"""
        timestamp = time.strftime('%H:%M:%S')
        self.log_text_edit.append(f"{icon} [{timestamp}] {message}")

    def handle_websocket_message(self, message: str, source: str):
        """处理来自WebSocket的消息。"""
        try:
            data = json.loads(message)
            event = data.get("event")
            if event and event.startswith("ws_"):
                # 处理连接/断开事件
                if "connected" in event:
                    self.add_log_message(f"WebSocket ({source}) 已连接。", "🔗")
                else:
                    self.add_log_message(f"WebSocket ({source}) 已断开。", "🔌")
            elif source == 'local':
                # 处理来自本机服务的事件
                if event == "peer_online":
                    self.add_log_message(f"设备上线: {data.get('name')}", "🟢");
                    self.update_device_list()
                elif event == "peer_offline":
                    self.add_log_message(f"设备下线: {data.get('name')}", "🔴");
                    self.update_device_list()
            elif source == 'remote':
                # 处理来自远程设备的事件
                if event == "shares_updated":
                    self.add_log_message(f"设备 {data.get('device_name')} 共享已更新。", "🔄")
                    if self.device_list_widget.currentItem() and self.active_peer_client:
                        self.handle_device_click(self.device_list_widget.currentItem(), force_refresh=True)
                elif event == "refresh_files":
                    self.add_log_message("远程文件变更，延时刷新...", "🔄")
                    QTimer.singleShot(500, self.refresh_current_file_view)
        except json.JSONDecodeError:
            pass

    def _format_size(self, size_bytes: int) -> str:
        """将字节大小格式化为人类可读的字符串。"""
        if size_bytes <= 0: return ""
        if size_bytes < 1024: return f"{size_bytes} B"
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i);
        s = round(size_bytes / p, 2)
        return f"{s} {('KB', 'MB', 'GB', 'TB')[i - 1]}"

    def show_file_context_menu(self, pos):
        """显示文件列表的右键菜单。"""
        selected_items = self.file_table_widget.selectedItems()
        if not selected_items: return

        menu = QMenu()
        download_action = QAction(self.download_icon, "下载选中项", self)
        download_action.triggered.connect(self.handle_download_action)
        menu.addAction(download_action)
        menu.exec(self.file_table_widget.mapToGlobal(pos))

    def _get_items_to_process(self) -> List[Dict[str, Any]]:
        """获取用户想要处理的项目(勾选优先于选中)。"""
        items = []
        processed_rows = set()

        for row in range(self.file_table_widget.rowCount()):
            check_item = self.file_table_widget.item(row, 0)
            if check_item and check_item.checkState() == Qt.CheckState.Checked:
                name_item = self.file_table_widget.item(row, 1)
                type_item = self.file_table_widget.item(row, 2)
                if name_item and type_item:
                    items.append({
                        'name': name_item.text(),
                        'is_dir': type_item.text() == '文件夹'
                    })
                    processed_rows.add(row)

        if not items:
            selected_rows = sorted(list(set(item.row() for item in self.file_table_widget.selectedItems())))
            for row in selected_rows:
                if row not in processed_rows:
                    name_item = self.file_table_widget.item(row, 1)
                    type_item = self.file_table_widget.item(row, 2)
                    if name_item and type_item:
                        items.append({
                            'name': name_item.text(),
                            'is_dir': type_item.text() == '文件夹'
                        })
        return items

    def handle_download_action(self):
        """处理下载按钮或右键菜单的点击事件。"""
        items_to_download = self._get_items_to_process()
        if not items_to_download:
            QMessageBox.information(self, "提示", "请先勾选或选中要下载的文件/文件夹。", QMessageBox.Ok)
            return

        save_dir = QFileDialog.getExistingDirectory(self, "选择保存下载内容的位置")
        if not save_dir: return

        tasks = []
        for item in items_to_download:
            remote_path = "/".join(self.active_path_stack + [item['name']])

            if item['is_dir']:
                save_path = os.path.join(save_dir, f"{item['name']}.zip")
                tasks.append({
                    "type": "download_folder", "name": item['name'],
                    "peer_client": self.active_peer_client, "share_name": self.share_selector_combo.currentText(),
                    "remote_path": remote_path, "save_path": save_path,
                })
            else:
                save_path = os.path.join(save_dir, item['name'])
                tasks.append({
                    "type": "download_file", "name": item['name'],
                    "peer_client": self.active_peer_client, "share_name": self.share_selector_combo.currentText(),
                    "remote_path": remote_path, "save_path": save_path,
                })

        if tasks:
            self.start_worker_thread("下载任务", tasks)

    def handle_upload_action(self, is_folder: bool):
        """处理上传菜单的点击事件。"""
        dest_path = "/".join(self.active_path_stack)

        if is_folder:
            local_path = QFileDialog.getExistingDirectory(self, "选择要上传的文件夹")
            if not local_path: return
            task = {
                "type": "upload_folder", "name": os.path.basename(local_path),
                "local_path": local_path, "peer_client": self.active_peer_client,
                "share_name": self.share_selector_combo.currentText(), "dest_path": dest_path
            }
            self.start_worker_thread(f"正在上传文件夹: {task['name']}", [task])

        else:
            local_files, _ = QFileDialog.getOpenFileNames(self, "选择要上传的文件 (可多选)")
            if not local_files: return
            tasks = []
            for file_path in local_files:
                tasks.append({
                    "type": "upload_file", "name": os.path.basename(file_path),
                    "local_path": file_path, "peer_client": self.active_peer_client,
                    "share_name": self.share_selector_combo.currentText(), "dest_path": dest_path
                })
            if tasks:
                self.start_worker_thread("正在上传文件...", tasks)

    def start_worker_thread(self, progress_title: str, tasks: List[Dict]):
        """启动工作线程并显示进度对话框。"""
        if self.worker_thread and self.worker_thread.isRunning():
            QMessageBox.warning(self, "任务正在进行", "已有文件在传输中，请稍后重试。", QMessageBox.Ok)
            return

        self.progress_dialog = QProgressDialog(self)
        self.progress_dialog.setWindowTitle(progress_title)
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setLabelText("准备开始...")



        is_single_download_task = len(tasks) == 1 and tasks[0]['type'] in ['download_file', 'download_folder']
        if is_single_download_task:
            self.progress_dialog.setRange(0, 100)
        else:
            self.progress_dialog.setRange(0, 0)  # 不确定模式

        self.worker_thread = WorkerThread(tasks)
        self.worker_thread.progress.connect(self.progress_dialog.setValue)
        self.worker_thread.progress_text_update.connect(self.progress_dialog.setLabelText)
        self.worker_thread.file_finished.connect(self.on_worker_file_finished)
        self.worker_thread.all_finished.connect(self.on_worker_all_finished)
        self.worker_thread.error.connect(self.on_worker_error)
        self.progress_dialog.canceled.connect(self.worker_thread.stop)

        self.worker_thread.start()
        self.progress_dialog.show()

    def on_worker_file_finished(self, message: str):
        """当工作线程完成一个文件时调用的槽函数。"""
        self.add_log_message(message, "✅")

    def on_worker_all_finished(self):
        """当工作线程完成所有任务时调用的槽函数。"""
        if self.progress_dialog: self.progress_dialog.close()
        if self.worker_thread and not self.worker_thread.has_errors:
            QMessageBox.information(self, "任务完成", "所有传输任务已成功完成。", QMessageBox.Ok)
            self.add_log_message("所有传输任务已完成。", "🎉")

        self.refresh_current_file_view()
        self.worker_thread = None

    def on_worker_error(self, error_message: str):
        """当工作线程发生错误时调用的槽函数。"""
        title = "传输错误"
        friendly_message = f"发生错误: {error_message}"
        error_lower = str(error_message).lower()

        if "403" in error_lower or "permission denied" in error_lower:
            title = "权限不足"
            friendly_message = "操作失败：对方未授予相应权限。"
        elif "404" in error_lower or "not found" in error_lower:
            title = "未找到"
            friendly_message = "操作失败：文件或文件夹在对方设备上已不存在。"
        elif "connectionrefusederror" in error_lower or "timed out" in error_lower:
            title = "连接失败"
            friendly_message = "无法连接到对方设备，请检查网络。"
        elif "cancelled" in error_lower:
            title = "任务取消"
            friendly_message = "任务已被用户取消。"

        self.add_log_message(friendly_message, "❌")
        if "cancelled" not in error_lower:
            QMessageBox.critical(self, title, friendly_message, QMessageBox.Ok)

        if self.progress_dialog and self.progress_dialog.isVisible():
            self.progress_dialog.close()
        self.worker_thread = None

    def on_item_double_clicked(self, item: QTableWidgetItem):
        """处理文件列表中的双击事件（进入文件夹）。"""
        if item.column() == 0: return
        row = self.file_table_widget.row(item)
        if self.file_table_widget.item(row, 2).text() == "文件夹":
            folder_name = self.file_table_widget.item(row, 1).text()
            self.active_path_stack.append(folder_name)
            self.refresh_current_file_view()

    def go_back_directory(self):
        """返回上一级目录。"""
        if self.active_path_stack:
            self.active_path_stack.pop()
            self.refresh_current_file_view()

    def refresh_current_file_view(self):
        """刷新当前的文件列表视图。"""
        if not self.active_peer_client or not self.share_selector_combo.currentText(): return
        current_path = "/" + "/".join(self.active_path_stack)
        self.current_path_label.setText(current_path)
        self.back_button.setEnabled(bool(self.active_path_stack))
        files = self.active_peer_client.get_files(self.share_selector_combo.currentText(), current_path)
        self.update_file_table(files)

    def update_device_list(self):
        """定时更新在线设备列表。"""
        if not self.api_client: return
        peers = self.api_client.get_peers()
        new_online_data = {}
        if peers:
            my_name = f"{self.controller.service_name}._netneighbor._tcp.local."
            new_online_data = {n: d for n, d in peers.items() if n != my_name}

        count = len(new_online_data)
        if not self.active_peer_client:
            self.status_bar_label.setText(f"发现 {count} 个在线设备。" if count > 0 else "就绪. 正在扫描局域网设备...")

        if self.active_peer_client:
            current_peer_name = next((name for name, data in self.online_devices_data.items() if
                                      self.active_peer_client.base_url.startswith(
                                          f"http://{data['address']}:{data['port']}")), None)
            if current_peer_name and current_peer_name not in new_online_data:
                self.add_log_message(f"已连接的设备 {current_peer_name.split('.')[0]} 已下线。", "🔌")
                self.clear_active_peer_view()

        current_names = set(self.online_devices_data.keys())
        new_names = set(new_online_data.keys())
        self.online_devices_data = new_online_data
        to_add, to_remove = new_names - current_names, current_names - new_names

        for i in range(self.device_list_widget.count() - 1, -1, -1):
            item = self.device_list_widget.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) in to_remove: self.device_list_widget.takeItem(i)

        for name in sorted(list(to_add)):
            data = self.online_devices_data[name]
            display = name.split('._netneighbor._tcp.local.')[0]
            dev_type = data.get("properties", {}).get("dev_type", "未知")
            item = QListWidgetItem(f"{display}\n类型: {dev_type}")
            item.setIcon(self.device_icon)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.device_list_widget.addItem(item)

    def clear_active_peer_view(self):
        """当远程设备断开时，清空右侧视图。"""
        self.active_peer_client = None
        if self.ws_remote_thread and self.ws_remote_thread.isRunning():
            self.ws_remote_thread.stop()
        self.ws_remote_thread = None
        self.share_selector_combo.clear()
        self.file_table_widget.setRowCount(0)
        self.active_path_stack = []
        self.current_path_label.setText("/")
        self.right_stack.setCurrentWidget(self.welcome_page)

    def handle_device_click(self, clicked_item: QListWidgetItem, force_refresh: bool = False):
        """处理对设备列表的点击事件。"""
        if not clicked_item: return
        service_name = clicked_item.data(Qt.ItemDataRole.UserRole)
        device_data = self.online_devices_data.get(service_name)
        if not device_data: return
        self.right_stack.setCurrentWidget(self.file_browser_page)
        new_base_url = f"http://{device_data['address']}:{device_data['port']}"

        is_new_device = not self.active_peer_client or self.active_peer_client.base_url != new_base_url

        if force_refresh or is_new_device:
            self.active_peer_client = ApiClient(new_base_url)
            if is_new_device:
                self.add_log_message(f"已连接到设备: {service_name.split('.')[0]}", "🔌")
                self.measure_ping(self.active_peer_client, service_name.split('.')[0])
                if self.ws_remote_thread and self.ws_remote_thread.isRunning(): self.ws_remote_thread.stop()
                ws_uri = f"ws://{device_data['address']}:{device_data['port']}/ws/events"
                self.ws_remote_thread = WebSocketClientThread(ws_uri, 'remote')
                self.ws_remote_thread.message_received.connect(self.handle_websocket_message)
                self.ws_remote_thread.start()

            current_share = self.share_selector_combo.currentText()
            self.share_selector_combo.blockSignals(True)
            self.share_selector_combo.clear()
            shares = self.active_peer_client.get_shares()
            share_names = [s['name'] for s in shares] if shares else []
            if share_names: self.share_selector_combo.addItems(share_names)

            if current_share and current_share in share_names and not is_new_device:
                self.share_selector_combo.setCurrentText(current_share)

            self.share_selector_combo.blockSignals(False)

            if is_new_device or self.share_selector_combo.currentText() != current_share:
                self.handle_share_selection_change(self.share_selector_combo.currentIndex())

    def handle_share_selection_change(self, index: int):
        """处理共享文件夹下拉框的选择变化。"""
        has_shares = index > -1
        self.upload_button.setEnabled(has_shares)
        if not has_shares:
            self.update_file_table(None)
            return

        self.active_path_stack = []
        self.refresh_current_file_view()

    def measure_ping(self, client: ApiClient, name: str):
        """在后台测量与远程设备的延迟。"""

        def do_ping():
            start = time.perf_counter()
            if client.get_ping():
                delay = int((time.perf_counter() - start) * 1000)
                self.status_bar_label.setText(f"已连接到 {name} | 延迟: {delay}ms")

        threading.Thread(target=do_ping, daemon=True).start()

    def update_file_table(self, files: Optional[List[Dict[str, Any]]]):
        """根据API返回的数据更新文件列表。"""
        self.file_table_widget.setRowCount(0)
        has_shares = self.share_selector_combo.count() > 0
        self.upload_button.setEnabled(has_shares)

        if files is None: return

        files.sort(key=lambda x: (not x['is_dir'], x['name'].lower()))
        self.file_table_widget.setRowCount(len(files))
        for row, file_info in enumerate(files):
            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            check_item.setCheckState(Qt.CheckState.Unchecked)

            name_item = QTableWidgetItem(file_info['name'])
            name_item.setIcon(self.folder_icon if file_info['is_dir'] else self.file_icon)

            type_item = QTableWidgetItem("文件夹" if file_info['is_dir'] else "文件")
            size_item = QTableWidgetItem(self._format_size(file_info['size']))
            size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            for item in [name_item, type_item, size_item]:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            self.file_table_widget.setItem(row, 0, check_item)
            self.file_table_widget.setItem(row, 1, name_item)
            self.file_table_widget.setItem(row, 2, type_item)
            self.file_table_widget.setItem(row, 3, size_item)

    def closeEvent(self, event):
        """处理窗口关闭事件，确保所有后台线程都安全退出。"""
        if self.worker_thread and self.worker_thread.isRunning():
            reply = QMessageBox.question(self, "退出确认", "有文件正在传输，确定要强制退出吗？",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                event.ignore();
                return
            else:
                self.worker_thread.stop()
        self.add_log_message("应用正在关闭...", "👋")
        if self.ws_local_thread: self.ws_local_thread.stop()
        if self.ws_remote_thread: self.ws_remote_thread.stop()
        self.controller.stop_all_services()
        self.add_log_message("所有服务和线程已停止。应用退出。", "👋")
        event.accept()

    def update_my_shares_list(self):
        """从配置文件加载并更新本机共享列表。"""
        self.my_shares_list_widget.clear()
        shares = load_config(force_reload=True).get("shares", [])
        if not shares:
            item = QListWidgetItem("无共享文件夹");
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.my_shares_list_widget.addItem(item)
            return
        for share in shares:
            name = share.get('name', '未命名');
            permissions = share.get("permissions", [])
            parts = []
            if "read" in permissions: parts.append("可读")
            if "download" in permissions: parts.append("可下载")
            if "upload" in permissions: parts.append("可上传")
            perm_text = "/".join(parts) if parts else "无权限"
            item = QListWidgetItem(f"{name} ({perm_text})");
            item.setToolTip(share.get('path'));
            item.setIcon(self.folder_icon)
            self.my_shares_list_widget.addItem(item)