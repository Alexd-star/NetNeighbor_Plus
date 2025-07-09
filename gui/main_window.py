# 文件: gui/main_window.py
# 描述: 应用的主窗口，负责UI的整体布局和用户交互逻辑。
# (已添加实时速度显示, 并修正类型提示以兼容 Python 3.9)

import asyncio
import json
import math
import os
import re
import socket
import threading
import time
from typing import Any, Dict, List, Optional, Union

import toml
import websockets
from PySide6.QtCore import QCoreApplication, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QFont, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QDialog, QFileDialog, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMenu, QMessageBox, QProgressDialog,
    QPushButton, QStackedWidget, QStatusBar, QStyle, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget, QComboBox
)

from .api_client import ApiClient, UploadStreamer
from .app_controller import AppController
from .settings_window import SettingsWindow
from core.config_loader import get_config, load_config, CONFIG_PATH


def natural_sort_key(s: str) -> list:
    """
    为字符串生成一个可用于自然排序的键。
    例如，'v10' 会被转换为 ['v', 10]，'v2' 会被转换为 ['v', 2]。
    这样在比较时，10 会被正确地识别为大于 2。
    """
    return [int(text) if text.isdigit() else text.lower()
            for text in re.split(r'([0-9]+)', s)]

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
            # 现在在这里执行真正的、会超时的网络操作
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

class WebSocketClientThread(QThread):
    """在后台线程中处理 WebSocket 连接, 并通过信号与主线程通信。"""
    message_received = Signal(str, str)

    def __init__(self, uri: str, source: str):
        super().__init__()
        self.uri = uri
        self.source = source
        self._is_running = True
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.task: Optional[asyncio.Task] = None

    async def listen(self):
        """异步监听 WebSocket 消息的核心循环。"""
        while self._is_running:
            try:
                connect_kwargs = {"open_timeout": 5, "close_timeout": 5}
                async with websockets.connect(self.uri, **connect_kwargs) as ws:
                    print(f"WebSocket ({self.source}) 已连接到 {self.uri}")
                    self.message_received.emit(
                        json.dumps({"event": f"ws_{self.source}_connected"}),
                        self.source
                    )
                    while self._is_running:
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                            self.message_received.emit(msg, self.source)
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
                    print(f"WebSocket ({self.source}) 连接错误: {e}。5秒后重连...")
                    self.message_received.emit(
                        json.dumps({"event": f"ws_{self.source}_disconnected"}),
                        self.source
                    )
                    for _ in range(50):
                        if not self._is_running:
                            break
                        await asyncio.sleep(0.1)

    def run(self):
        """QThread的入口点, 设置并运行asyncio事件循环。"""
        try:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.task = self.loop.create_task(self.listen())
            self.loop.run_until_complete(self.task)
        except asyncio.CancelledError:
            pass
        finally:
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
        if self.loop and self.task and not self.task.done():
            self.loop.call_soon_threadsafe(self.task.cancel)
        if not self.wait(2000):
            print(f"警告: WebSocket ({self.source}) 线程超时，强制终止。")
            self.terminate()


class WorkerThread(QThread):
    """
    通用工作线程, 处理所有耗时文件/文件夹传输任务。
    【新增】增加了速度计算和信号。
    """
    progress = Signal(int)
    # --- 【优化1】新增两个信号, 用于更新进度文本和实时速度 ---
    progress_text_update = Signal(str)
    speed_update = Signal(str)
    file_finished = Signal(str)
    all_finished = Signal()
    error = Signal(str)

    def __init__(self, tasks: List[Dict]):
        super().__init__()
        self.tasks = tasks
        self.has_errors = False
        self._is_running = True

    def run(self):
        """线程主执行函数, 按顺序处理任务列表。"""
        total_tasks = len(self.tasks)
        for i, task in enumerate(self.tasks):
            if not self._is_running:
                self.error.emit("任务被用户取消。")
                break

            self.progress_text_update.emit(
                f"({i + 1}/{total_tasks}) 正在处理: {task.get('name', 'N/A')}"
            )

            try:
                task_type = task.get("type")
                if task_type == "download_file":
                    self._run_download_file(task)
                elif task_type == "download_folder_tcp":
                    self._run_download_folder_tcp(task)
                elif task_type == "upload_folder":
                    self._run_upload_folder(task)
                elif task_type == "upload_file":
                    self._run_upload_file(task)
                else:
                    raise ValueError(f"未知的任务类型: {task_type}")
            except Exception as e:
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

    # --- 【优化2】重构传输函数以包含速度计算逻辑 ---
    def _transfer_loop(self, iterator, file_handle, total_size):
        """通用的传输循环, 包含进度、速度计算和超详细的日志。"""
        start_time = time.time()
        last_update_time = start_time
        bytes_since_last_update = 0
        transferred_bytes = 0
        chunk_count = 0

        print(f"[CLIENT] 开始文件传输循环。预计总大小: {total_size} 字节。")

        for chunk in iterator:
            if not self._is_running:
                print("[CLIENT] 传输被用户取消。")
                raise InterruptedError("Transfer cancelled by user")

            chunk_len = len(chunk)
            chunk_count += 1

            file_handle.write(chunk)

            transferred_bytes += chunk_len
            bytes_since_last_update += chunk_len

            current_time = time.time()
            time_delta = current_time - last_update_time

            if time_delta >= 0.5:
                speed = bytes_since_last_update / time_delta
                self.speed_update.emit(f"{self._format_size(speed)}/s")
                last_update_time = current_time
                bytes_since_last_update = 0

            if total_size > 0:
                self.progress.emit(int((transferred_bytes / total_size) * 100))

        print(f"[CLIENT] 传输循环正常结束。总共接收 {chunk_count} 个数据块，总大小: {transferred_bytes} 字节。")
        self.speed_update.emit("")

    def _run_download_file(self, task_info):
        """下载单个文件的具体实现。"""
        p_client, s_name = task_info['peer_client'], task_info['share_name']
        r_path, save_p = task_info['remote_path'], task_info['save_path']
        file_name = os.path.basename(save_p)

        with p_client.download_file_stream(s_name, r_path) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get('content-length', 0))
            with open(save_p, "wb") as f:
                self._transfer_loop(resp.iter_bytes(chunk_size=8192), f, total)

        self.file_finished.emit(f"文件 '{file_name}' 下载完成！")


    def _run_download_folder_tcp(self, task_info):
        """
        【最终架构版】通过高性能TCP通道下载并打包文件夹。
        使用 'with' 语句来确保连接资源被正确管理。
        """
        peer_client, share_name = task_info['peer_client'], task_info['share_name']
        remote_path, save_path = task_info['remote_path'], task_info['save_path']
        folder_name = task_info['name']

        self.progress_text_update.emit(f"开始下载 '{folder_name}.zip' (TCP高速模式)...")

        try:
            # 使用 'with' 语句来安全地使用我们新的 TcpDownloader
            # 当 with 代码块结束时, downloader.__exit__ 会被自动调用, socket 会被关闭
            with peer_client.download_folder_tcp(share_name, remote_path) as downloader:
                with open(save_path, "wb") as f:
                    # 将 downloader (它本身就是个迭代器) 传入传输循环
                    # TCP流大小未知, 传入 0, 进度条会显示为不确定模式
                    self._transfer_loop(downloader, f, 0)
        except Exception as e:
            # 将任何发生的异常往上抛，由总的错误处理器来显示给用户
            raise e

        self.file_finished.emit(
            f"文件夹 '{folder_name}' 已通过TCP高速下载为 '{os.path.basename(save_path)}'！"
        )

    def _run_upload_file(self, task_info):
        """上传单个文件的具体实现。"""
        local_path, p_client = task_info['local_path'], task_info['peer_client']
        s_name, dest = task_info['share_name'], task_info['dest_path']
        file_name = os.path.basename(local_path)

        # UploadStreamer 现在也需要包含速度计算逻辑
        # (为了简化, 我们在回调中计算)
        total_size = os.path.getsize(local_path)
        sent_bytes = 0
        last_update_time = time.time()
        bytes_since_last_update = 0

        def progress_callback(chunk_len):
            nonlocal sent_bytes, last_update_time, bytes_since_last_update
            sent_bytes += chunk_len
            bytes_since_last_update += chunk_len

            current_time = time.time()
            time_delta = current_time - last_update_time
            if time_delta >= 0.5:
                speed = bytes_since_last_update / time_delta
                self.speed_update.emit(f"{self._format_size(speed)}/s")
                last_update_time = current_time
                bytes_since_last_update = 0

            if total_size > 0:
                self.progress.emit(int((sent_bytes / total_size) * 100))

        with UploadStreamer(local_path, progress_callback=progress_callback) as uploader:
            p_client.upload_file_stream(s_name, dest, uploader)

        self.speed_update.emit("")
        self.file_finished.emit(f"文件 '{file_name}' 上传成功。")

    def _run_upload_folder(self, task_info):
        """上传整个文件夹的具体实现。"""
        local_folder, p_client = task_info['local_path'], task_info['peer_client']
        s_name, base_dest = task_info['share_name'], task_info['dest_path']
        folder_name = os.path.basename(local_folder)

        root_remote_path = os.path.join(base_dest, folder_name).replace('\\', '/')
        p_client.create_directory(s_name, root_remote_path)
        self.file_finished.emit(f"在远程创建目录: {root_remote_path}")

        files_to_upload = []
        for root, dirs, files in os.walk(local_folder):
            if not self._is_running:
                raise InterruptedError("Upload cancelled")

            rel_path = os.path.relpath(root, local_folder)
            for d in dirs:
                remote_dir = os.path.join(root_remote_path, rel_path, d)
                p_client.create_directory(s_name, remote_dir.replace('\\', '/'))

            for f in files:
                remote_folder = os.path.join(root_remote_path, rel_path)
                files_to_upload.append({
                    'local_file': os.path.join(root, f),
                    'remote_dest': remote_folder.replace('\\', '/')
                })

        total_files = len(files_to_upload)
        for i, file_task in enumerate(files_to_upload):
            self.progress_text_update.emit(
                f"上传文件 ({i + 1}/{total_files}): {os.path.basename(file_task['local_file'])}"
            )
            upload_task = {
                "type": "upload_file",
                "local_path": file_task['local_file'],
                "peer_client": p_client,
                "share_name": s_name,
                "dest_path": file_task['remote_dest']
            }
            self._run_upload_file(upload_task)

    # --- 【优化3】将格式化函数移到 WorkerThread 中，方便内部调用 ---
    def _format_size(self, size_bytes: Union[int, float]) -> str:
        """将字节大小格式化为人类可读的字符串。"""
        if size_bytes <= 0:
            return "0 B"
        if size_bytes < 1024:
            return f"{size_bytes} B"

        # KB, MB, GB, TB
        power_labels = ('KB', 'MB', 'GB', 'TB')
        i = int(math.floor(math.log(size_bytes, 1024)))
        # 确保索引在元组范围内
        i = min(i - 1, len(power_labels) - 1)

        p = math.pow(1024, i + 1)
        s = round(size_bytes / p, 2)
        return f"{s} {power_labels[i]}"


class MainWindow(QMainWindow):
    """应用主窗口类, 包含所有UI元素和交互逻辑。"""

    def _on_connection_thread_finished(self):
        """当连接线程结束后，安全地清除对它的引用。"""
        self.connection_thread = None

    def __init__(self, controller: AppController):
        super().__init__()
        self.controller = controller
        self.my_ip = self._get_my_ip()
        self.api_client: Optional[ApiClient] = None
        self.online_devices_data: Dict[str, Any] = {}
        self.active_peer_client: Optional[ApiClient] = None
        self.active_path_stack: List[str] = []
        self.worker_thread: Optional[WorkerThread] = None
        self.connection_thread: Optional[ConnectionThread] = None
        self.ws_local_thread: Optional[WebSocketClientThread] = None
        self.ws_remote_thread: Optional[WebSocketClientThread] = None
        self.progress_dialog: Optional[QProgressDialog] = None
        self.is_transfer_active = False

        # --- 【优化4】增加一个变量来存储进度对话框的标签文本 ---
        self._progress_label_text = ""
        # --- 【第一步优化 - 新增代码】: 新增一个用于设备列表更新防抖的计时器 ---
        # 1. 创建用于缓冲设备更新事件的队列
        self.device_add_queue = []
        self.device_remove_queue = []

        # 2. 创建一个单次触发的定时器，用于批处理UI更新
        self.ui_update_timer = QTimer(self)
        self.ui_update_timer.setSingleShot(True)
        self.ui_update_timer.setInterval(150)
        self.ui_update_timer.timeout.connect(self._process_device_list_updates)

        self._setup_window()
        self._load_icons()
        self._setup_ui()
        self.update_my_shares_list()
        self.controller.device_info_updated.connect(
            self.update_local_status_display
        )

    # ... 省略部分未改动的函数 ...

    def start_worker_thread(self, progress_title: str, tasks: List[Dict]):
        """
        启动工作线程并显示进度对话框。
        [最终修复] 修正对文件夹下载任务的判断逻辑，并增加提示文本。
        """
        if self.worker_thread and self.worker_thread.isRunning():
            QMessageBox.warning(self, "任务正在进行", "已有文件在传输中，请稍后重试。", QMessageBox.Ok)
            return

        self.is_transfer_active = True
        self.progress_dialog = QProgressDialog(self)
        self.progress_dialog.setWindowTitle(progress_title)
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)


        # 1. 正确检查任务列表中是否包含任何 "download_folder_tcp" 类型的任务
        is_downloading_folder = any(task.get("type") == "download_folder_tcp" for task in tasks)

        if is_downloading_folder:
            # 2. 如果是，则设置进度条为不确定模式（滚动条）
            self.progress_dialog.setRange(0, 0)
            # 3. 增加友好的提示信息
            self._progress_label_text = "正在准备流式传输，总大小未知..."
        else:
            # 4. 如果是文件下载或上传，则恢复原始的确定模式进度条
            is_single_task = len(tasks) == 1
            self.progress_dialog.setRange(0, 100 if is_single_task else 0)
            self._progress_label_text = "准备开始..."

        self.progress_dialog.setLabelText(self._progress_label_text)

        self.worker_thread = WorkerThread(tasks)
        self.worker_thread.progress.connect(self.progress_dialog.setValue)
        self.worker_thread.progress_text_update.connect(self.on_worker_progress_text_update)
        self.worker_thread.speed_update.connect(self.on_worker_speed_update)
        self.worker_thread.file_finished.connect(self.on_worker_file_finished)
        self.worker_thread.all_finished.connect(self.on_worker_all_finished)
        self.worker_thread.error.connect(self.on_worker_error)
        self.progress_dialog.canceled.connect(self.worker_thread.stop)

        self.worker_thread.start()
        self.progress_dialog.show()

    # --- 【优化6】为新的信号创建槽函数 ---
    def on_worker_progress_text_update(self, text: str):
        """当工作线程更新进度文本时调用的槽函数。"""
        self._progress_label_text = text
        # 同时更新速度显示
        current_speed_label = getattr(self, '_current_speed_label', '')
        self.progress_dialog.setLabelText(
            f"{self._progress_label_text}\n{current_speed_label}"
        )

    def on_worker_speed_update(self, speed_text: str):
        """当工作线程更新速度时调用的槽函数。"""
        self._current_speed_label = speed_text
        self.progress_dialog.setLabelText(
            f"{self._progress_label_text}\n{self._current_speed_label}"
        )

    # ... 省略其他未改动的函数, 只保留 _format_size 的修改 ...

    def _format_size(self, size_bytes: int) -> str:
        """将字节大小格式化为人类可读的字符串。"""
        # 这个函数现在可以调用 WorkerThread 中的版本, 但为了UI独立性, 保留一份
        if size_bytes <= 0:
            return ""
        if size_bytes < 1024:
            return f"{size_bytes} B"

        power_labels = ('KB', 'MB', 'GB', 'TB')
        i = int(math.floor(math.log(size_bytes, 1024)))
        i = min(i - 1, len(power_labels) - 1)

        p = math.pow(1024, i + 1)
        s = round(size_bytes / p, 2)
        return f"{s} {power_labels[i]}"

    # --- 为了让您能直接替换, 我将省略的函数也包含进来 ---
    def post_init_setup(self):
        """在后台服务启动后进行网络相关的初始化。"""
        self.add_log_message("后端服务已就绪, UI开始进行网络初始化...")
        base_url = f"http://{self._get_my_ip()}:{self.controller.port}"
        self.api_client = ApiClient(base_url)
        self._setup_websocket()
        self.update_local_status_display()
        # 【核心改动】: 转而调用新的方法，在启动时拉取一次全量设备列表。
        self.populate_initial_devices()

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
        self.manage_shares_button = QPushButton("设置")
        self.manage_shares_button.setToolTip("打开设置窗口以添加、移除或修改本机共享")
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
        self.back_button.setToolTip("返回上一级目录")
        self.back_button.clicked.connect(self.go_back_directory)
        self.current_path_label = QLineEdit("/")
        self.current_path_label.setReadOnly(True)
        self.current_path_label.setToolTip("当前正在浏览的远程路径")

        self.upload_button = QPushButton(self.upload_icon, "上传")
        self.upload_button.setToolTip("向当前远程路径上传文件或文件夹")
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
        menu = QMenu()
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
        """显示关于对话框，包含版本和功能说明。"""
        QMessageBox.about(
            self,
            "关于 邻里+",
            """<b>邻里+ (NetNeighbor Plus) v3.3.0</b>
            <p>一款基于局域网的、开源的、跨平台文件共享工具。</p>
            <p><b>核心功能:</b></p>
            <ul>
                <li>自动发现局域网内的其他设备</li>
                <li>支持文件和文件夹的上传与下载</li>
                <li>灵活的文件夹权限管理 (可读/可下载/可上传)</li>
                <li>实时文件变更监控与通知</li>
                <li>跨平台支持 (Windows, macOS, Linux)</li>
            </ul>
            <p>感谢您的使用！</p>
            """
        )

    def add_log_message(self, message: str, icon: str = "ℹ️"):
        """向日志窗口添加一条带时间戳和图标的消息。"""
        timestamp = time.strftime('%H:%M:%S')
        self.log_text_edit.append(f"{icon} [{timestamp}] {message}")

    def handle_websocket_message(self, message: str, source: str):
        """处理来自WebSocket的消息。"""
        try:
            data = json.loads(message)
            event = data.get("event")

            # 直接根据事件类型调用相应的UI更新方法
            if event == "peer_online":
                self.add_log_message(f"设备上线: {data.get('friendly_name')}", "🟢")
                self.device_add_queue.append((data['name'], data['data']))
                self.ui_update_timer.start()
            elif event == "peer_offline":
                self.add_log_message(f"设备下线: {data.get('friendly_name')}", "🔴")
                self.device_remove_queue.append(data['name'])
                self.ui_update_timer.start()

            # 其余事件处理保持不变
            elif event == "refresh_files" and self.active_peer_client:
                if self.is_transfer_active:
                    return
                self.add_log_message("远程文件变更，延时刷新...", "🔄")
                QTimer.singleShot(500, self.refresh_current_file_view)
            elif event == "shares_updated" and source == 'remote':
                self.add_log_message(f"设备 {data.get('device_name')} 共享已更新。", "🔄")
                if self.device_list_widget.currentItem():
                    self.handle_device_click(self.device_list_widget.currentItem(), force_refresh=True)
        except (json.JSONDecodeError, KeyError, AttributeError) as e:
            print(f"处理WebSocket消息时出错: {e}")

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
        """
        处理下载按钮或右键菜单的点击事件。
        【架构统一】: 所有文件夹下载现在都走TCP通道，并保存为.tar文件。
                     旧的HTTP方式作为备用，也会请求.tar文件。
        """
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
                # --- 【核心修正】: 无论新旧逻辑，文件夹都保存为 .tar ---
                save_path = os.path.join(save_dir, f"{item['name']}.tar")
                tasks.append({
                    # 优先使用新的TCP高速模式
                    "type": "download_folder_tcp",
                    "name": item['name'],
                    "peer_client": self.active_peer_client,
                    "share_name": self.share_selector_combo.currentText(),
                    "remote_path": remote_path,
                    "save_path": save_path,
                })
            else:
                # 文件下载逻辑保持不变
                save_path = os.path.join(save_dir, item['name'])
                tasks.append({
                    "type": "download_file",
                    "name": item['name'],
                    "peer_client": self.active_peer_client,
                    "share_name": self.share_selector_combo.currentText(),
                    "remote_path": remote_path,
                    "save_path": save_path,
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

    def on_worker_file_finished(self, message: str):
        """当工作线程完成一个文件时调用的槽函数。"""
        self.add_log_message(message, "✅")

    def on_worker_all_finished(self):
        """当工作线程完成所有任务时调用的槽函数。"""
        self.is_transfer_active = False
        if self.progress_dialog: self.progress_dialog.close()
        if self.worker_thread and not self.worker_thread.has_errors:
            QMessageBox.information(self, "任务完成", "所有传输任务已成功完成。", QMessageBox.Ok)
            self.add_log_message("所有传输任务已完成。", "🎉")

        self.refresh_current_file_view()
        self.worker_thread = None

    def on_worker_error(self, error_message: str):
        """当工作线程发生错误时调用的槽函数。"""
        self.is_transfer_active = False
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
        """【最终修复版】使用健壮的线程生命周期管理。"""
        if not clicked_item:
            return

        # 检查是否有线程正在运行，现在这个检查是安全的了
        if self.connection_thread and self.connection_thread.isRunning():
            return

        service_name = clicked_item.data(Qt.ItemDataRole.UserRole)
        device_data = self.online_devices_data.get(service_name)
        if not device_data:
            return

        new_base_url = f"http://{device_data['address']}:{device_data['port']}"
        display_name = service_name.split('._netneighbor._tcp.local.')[0]

        if not force_refresh and self.active_peer_client and self.active_peer_client.base_url == new_base_url:
            self.right_stack.setCurrentWidget(self.file_browser_page)
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.status_bar_label.setText(f"正在连接到 {display_name}...")
        self.add_log_message(f"正在尝试连接到 {display_name}...", "⏳")
        self.right_stack.setCurrentWidget(self.welcome_page)

        self.connection_thread = ConnectionThread(new_base_url)
        self.connection_thread.connection_successful.connect(
            lambda client, shares: self._on_connection_successful(client, shares, display_name)
        )
        self.connection_thread.connection_failed.connect(
            lambda error_msg: self._on_connection_failed(error_msg, display_name)
        )

        # --- 【最终修复-第3步】: 修改这里的信号连接 ---
        # 1. 线程结束后，先调用我们的清理函数
        self.connection_thread.finished.connect(self._on_connection_thread_finished)
        # 2. 然后再安全地调度删除
        self.connection_thread.finished.connect(self.connection_thread.deleteLater)

        self.connection_thread.start()

    def _connect_to_device_background(self, base_url: str, display_name: str):
        """
        【诊断版本】在后台线程中执行诊断，用 time.sleep 模拟网络延迟。
        """
        try:
            # 这条打印信息会出现在您的控制台（命令行窗口）
            print(f"[{time.strftime('%H:%M:%S')}] 后台线程启动，即将休眠5秒以模拟网络延迟...")

            # --- 诊断代码: 我们用一个无害的休眠来替换掉真正的网络请求 ---
            time.sleep(5)

            # 我们直接模拟一个失败的场景，以便测试流程
            raise ConnectionError("这是一个模拟的超时错误，用于测试。")

        except Exception as e:
            # 这条打印信息也会出现在控制台
            print(f"[{time.strftime('%H:%M:%S')}] 后台线程休眠结束，准备在主线程中报告错误...")

            # 使用QTimer在主线程安全地更新UI
            QTimer.singleShot(0, lambda: self._on_connection_failed(str(e), display_name))

    def _on_connection_successful(self, client: ApiClient, shares: list, display_name: str):
        """【最终修复版】连接成功后的UI更新槽函数。"""
        QApplication.restoreOverrideCursor()
        self.add_log_message(f"已连接到设备: {display_name}", "🔌")
        self.status_bar_label.setText(f"已连接到 {display_name}")
        self.right_stack.setCurrentWidget(self.file_browser_page)

        self.active_peer_client = client

        if self.ws_remote_thread and self.ws_remote_thread.isRunning():
            self.ws_remote_thread.stop()

        ws_uri = f"ws://{client.base_url.split('//')[1]}/ws/events"
        self.ws_remote_thread = WebSocketClientThread(ws_uri, 'remote')
        self.ws_remote_thread.message_received.connect(self.handle_websocket_message)
        self.ws_remote_thread.start()

        self.share_selector_combo.blockSignals(True)
        self.share_selector_combo.clear()
        share_names = [s['name'] for s in shares] if shares else []
        if share_names:
            self.share_selector_combo.addItems(share_names)
        self.share_selector_combo.blockSignals(False)

        self.handle_share_selection_change(self.share_selector_combo.currentIndex())
        self.measure_ping(client, display_name)

    def _on_connection_failed(self, error_message: str, display_name: str):
        """【最终修复版】连接失败后的UI更新槽函数。"""
        QApplication.restoreOverrideCursor()
        friendly_error = f"连接到 {display_name} 失败"
        self.add_log_message(f"{friendly_error}: {error_message}", "❌")
        self.status_bar_label.setText(friendly_error)

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
                event.ignore()
                return
            else:
                self.worker_thread.stop()
        self.add_log_message("应用正在关闭...", "👋")
        if self.ws_local_thread: self.ws_local_thread.stop()
        if self.ws_remote_thread: self.ws_remote_thread.stop()
        self.controller.stop_all_services()
        self.add_log_message("所有服务和线程已停止。应用退出。", "👋")
        event.accept()

    def _add_device_to_list(self, service_name: str, device_data: dict):
        """向UI列表和内部数据结构中添加一个设备。"""
        if service_name in self.online_devices_data:
            return

        self.online_devices_data[service_name] = device_data

        display_name = service_name.split('._netneighbor._tcp.local.')[0]
        dev_type = device_data.get("properties", {}).get("dev_type", "未知")

        item = QListWidgetItem(f"{display_name}\n类型: {dev_type}")
        item.setIcon(self.device_icon)
        item.setData(Qt.ItemDataRole.UserRole, service_name)

        # 1. 获取新项目的自然排序键
        new_item_key = natural_sort_key(display_name)

        # 2. 遍历现有列表，找到第一个比新项目“大”的位置
        insert_row = 0
        for i in range(self.device_list_widget.count()):
            existing_item = self.device_list_widget.item(i)
            # 列表项的文本是多行的，我们只取第一行（设备名）进行比较
            existing_display_name = existing_item.text().split('\n')[0]
            existing_item_key = natural_sort_key(existing_display_name)

            if new_item_key < existing_item_key:
                break  # 找到了插入位置，跳出循环
            insert_row += 1

        # 3. 在找到的正确位置插入新项目
        self.device_list_widget.insertItem(insert_row, item)
        self._update_status_bar_device_count()

    def _remove_device_from_list(self, service_name: str):
        """从UI列表和内部数据结构中移除一个设备。"""
        if service_name not in self.online_devices_data:
            return

        # 检查是否断开了当前连接的设备
        if self.active_peer_client:
            device_data = self.online_devices_data.get(service_name)
            if device_data:
                active_url_part = self.active_peer_client.base_url.split('//')[1]
                device_url_part = f"{device_data['address']}:{device_data['port']}"
                if active_url_part == device_url_part:
                    self.clear_active_peer_view()

        del self.online_devices_data[service_name]

        for i in range(self.device_list_widget.count()):
            item = self.device_list_widget.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == service_name:
                self.device_list_widget.takeItem(i)
                break

        self._update_status_bar_device_count()

    def _update_status_bar_device_count(self):
        """更新状态栏中的设备计数。"""
        count = len(self.online_devices_data)
        self.status_bar_label.setText(f"发现在线设备: {count} 个" if count > 0 else "就绪. 正在扫描局域网设备...")

    def populate_initial_devices(self):
        """应用启动时，获取一次完整的设备列表进行填充。"""
        print("正在获取初始设备列表...")
        self.device_list_widget.clear()
        self.online_devices_data.clear()

        peers = self.api_client.get_peers() if self.api_client else None
        if not peers:
            self._update_status_bar_device_count()
            return

        my_service_name = f"{self.controller.service_name}._netneighbor._tcp.local."
        for name, data in peers.items():
            if name != my_service_name:
                self._add_device_to_list(name, data)

    def _process_device_list_updates(self):
        """
        批处理所有待处理的设备列表UI更新。由QTimer触发。
        """
        # 复制当前队列的内容，然后立刻清空，以便接收下一批事件
        add_batch = self.device_add_queue[:]
        remove_batch = self.device_remove_queue[:]
        self.device_add_queue.clear()
        self.device_remove_queue.clear()

        # 关键优化：在批量操作前，暂停UI的重绘，防止界面闪烁
        self.device_list_widget.setUpdatesEnabled(False)

        try:
            # 批量处理移除
            # 先创建一个待移除名称的集合，以提高查找效率
            remove_set = set(remove_batch)
            items_to_delete = []
            for i in range(self.device_list_widget.count()):
                item = self.device_list_widget.item(i)
                if item and item.data(Qt.ItemDataRole.UserRole) in remove_set:
                    items_to_delete.append(item)

            for item in items_to_delete:
                self.device_list_widget.takeItem(self.device_list_widget.row(item))

            # 批量处理添加
            for service_name, device_data in add_batch:
                self._add_device_to_list(service_name, device_data)  # 调用我们已有的添加方法

        finally:
            # 关键优化：在所有操作完成后，一次性地重新启用UI重绘并应用所有更改
            self.device_list_widget.setUpdatesEnabled(True)

        # 最后，只更新一次状态栏的计数
        self._update_status_bar_device_count()

    def update_my_shares_list(self):
        """从配置文件加载并更新本机共享列表。"""
        self.my_shares_list_widget.clear()
        # 从新的、智能的config_loader加载配置
        shares = load_config(force_reload=True).get("shares", [])

        if not shares:
            # --- 【核心改进】: 为新用户提供清晰的引导 ---
            item = QListWidgetItem("👉 请点击右侧“设置”按钮\n    添加您的第一个共享文件夹")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            font = item.font()
            font.setItalic(True)
            item.setFont(font)
            item.setForeground(Qt.gray)
            self.my_shares_list_widget.addItem(item)
            return

        for share in shares:
            name = share.get('name', '未命名')
            permissions = share.get("permissions", [])
            parts = []
            if "read" in permissions: parts.append("可读")
            if "download" in permissions: parts.append("可下载")
            if "upload" in permissions: parts.append("可上传")
            perm_text = "/".join(parts) if parts else "无权限"
            item = QListWidgetItem(f"{name} ({perm_text})")
            item.setToolTip(f"本地路径: {share.get('path')}")
            item.setIcon(self.folder_icon)
            self.my_shares_list_widget.addItem(item)