# 文件: gui/main_window.py
import os, socket, json, copy, asyncio, websockets, threading, time, math
from PySide6.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QListWidget, QTableWidget,
                               QAbstractItemView, QHeaderView, QListWidgetItem, QTableWidgetItem,
                               QMenu, QMessageBox, QFileDialog, QPushButton, QLineEdit, QProgressDialog,
                               QGroupBox, QLabel, QComboBox, QTextEdit, QStatusBar, QStyle)
from PySide6.QtCore import QTimer, Qt, QThread, Signal
from PySide6.QtGui import QAction, QIcon
from typing import Optional
from .api_client import ApiClient, UploadStreamer
from .settings_window import SettingsWindow
from .app_controller import AppController
from core.config_loader import load_config, get_config


class WebSocketClientThread(QThread):
    message_received = Signal(str)

    def __init__(self, uri):
        super().__init__();
        self.uri, self._is_running = uri, True

    async def listen(self):
        while self._is_running:
            try:
                async with websockets.connect(self.uri) as websocket:
                    print(f"WebSocket已连接到 {self.uri}")
                    self.message_received.emit(json.dumps({"event": "ws_connected"}))
                    while self._is_running:
                        try:
                            message = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                            self.message_received.emit(message)
                        except asyncio.TimeoutError:
                            continue
            except Exception as e:
                if self._is_running:
                    print(f"WebSocket连接错误: {e}。5秒后重连...")
                    self.message_received.emit(json.dumps({"event": "ws_disconnected"}))
                    await asyncio.sleep(5)

    def run(self):
        try:
            # 为这个线程创建一个新的事件循环
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.listen())
        except Exception as e:
            print(f"WebSocket线程启动失败: {e}")

    def stop(self):
        print("正在请求WebSocket线程停止...");
        self._is_running = False


class WorkerThread(QThread):
    progress = Signal(int)
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, task_type, **kwargs):
        super().__init__();
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
                    chunk = s.recv(4096 * 1024)
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
        super().__init__();
        self.controller = controller;
        self.config_data = self.controller.running_config
        self.my_ip = self.get_my_ip()
        self.api_client = None
        self.online_devices_data, self.active_peer_client, self.active_path_stack, self.worker_thread = {}, None, [], None

        self.setup_window()
        self.load_icons()
        self.setup_ui()
        self.update_my_shares_list()

    def post_init_setup(self):
        """此函数在后端服务确认启动后被调用"""
        print("后端服务已就绪, UI开始进行网络初始化...")
        self.api_client = ApiClient(f"http://{self.my_ip}:{self.controller.port}")
        self.setup_timers()
        self.setup_websocket()
        self.status_bar_label.setText("就绪. 正在扫描局域网设备...")
        self.update_device_list()  # 首次立即刷新

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

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # --- 菜单栏 ---
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("文件")
        settings_action = QAction(self.settings_icon, "设置...", self)
        settings_action.triggered.connect(self.open_settings)
        file_menu.addAction(settings_action)

        help_menu = menu_bar.addMenu("帮助")
        performance_test_action = QAction(self.help_icon, "关于...", self)
        performance_test_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(performance_test_action)

        # --- 本机状态 ---
        my_status_box = QGroupBox("本机状态")
        # 【修复6】给 GroupBox 设置一个对象名，方便QSS精准控制样式
        my_status_box.setObjectName("StatusGroupBox")
        my_status_layout = QHBoxLayout(my_status_box)
        # 使用controller中最终确定的设备名和端口
        self.device_name_label = QLabel(f"<b>设备名:</b> {self.controller.device_name}")
        my_ip_label = QLabel(f"<b>IP地址:</b> {self.my_ip}:{self.controller.port}")
        my_status_layout.addWidget(self.device_name_label)
        my_status_layout.addWidget(my_ip_label)
        my_status_layout.addStretch()
        main_layout.addWidget(my_status_box)

        # --- 主交互区 ---
        interaction_layout = QHBoxLayout()
        main_layout.addLayout(interaction_layout, stretch=1)

        # --- 左侧面板 ---
        left_panel_widget = QWidget()
        left_panel_layout = QVBoxLayout(left_panel_widget)
        left_panel_widget.setFixedWidth(280)
        left_panel_layout.setContentsMargins(0, 0, 0, 0)

        left_panel_layout.addWidget(QLabel("<h4>在线设备</h4>"))
        self.device_list_widget = QListWidget()
        self.device_list_widget.itemClicked.connect(self.handle_device_click)
        left_panel_layout.addWidget(self.device_list_widget, stretch=3)  # 调整比例

        # 【UI增强】新增本机共享列表
        left_panel_layout.addWidget(QLabel("<h4>本机共享</h4>"))
        self.my_shares_list_widget = QListWidget()
        self.my_shares_list_widget.setToolTip(
            "这是你本机当前正在共享的文件夹列表。\n在'文件->设置'中修改后会在这里更新。")
        left_panel_layout.addWidget(self.my_shares_list_widget, stretch=2)  # 调整比例

        left_panel_layout.addWidget(QLabel("<h4>事件日志</h4>"))
        self.log_text_edit = QTextEdit()
        self.log_text_edit.setReadOnly(True)
        left_panel_layout.addWidget(self.log_text_edit, stretch=2)  # 调整比例
        interaction_layout.addWidget(left_panel_widget)

        # --- 右侧面板 ---
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        interaction_layout.addWidget(right_panel, stretch=1)

        # 工具栏
        toolbar_layout = QHBoxLayout()
        self.share_selector_combo = QComboBox()
        self.share_selector_combo.setPlaceholderText("选择共享文件夹")
        self.share_selector_combo.setMinimumWidth(180)
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

        # 文件列表
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

        # --- 状态栏 ---
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar_label = QLabel("正在初始化...")
        self.status_bar.addWidget(self.status_bar_label, 1)

    def setup_timers(self):
        self.peer_update_timer = QTimer(self)
        self.peer_update_timer.timeout.connect(self.update_device_list)
        self.peer_update_timer.start(10000)  # 10秒刷新一次

    def setup_websocket(self):
        ws_uri = f"ws://127.0.0.1:{self.controller.port}/ws/events"
        self.ws_thread = WebSocketClientThread(ws_uri)
        self.ws_thread.message_received.connect(self.handle_websocket_message)
        self.ws_thread.start()

    def open_settings(self):
        # 【修复4】将整个controller实例传给设置窗口
        # 这样设置窗口就能知道真实的运行端口，即使它是被命令行覆盖的
        dialog = SettingsWindow(self.controller, self)
        if dialog.exec():
            self.config_data = load_config(force_reload=True)
            if not self.config_data:
                QMessageBox.critical(self, "错误", "重新加载配置文件失败，请检查文件格式或重启应用。")
                return

            self.controller.running_config = self.config_data

            # 【重要】设置保存后，需要告知用户哪些需要重启才能生效
            # 设备名和端口的更改需要重启后台服务，我们这里只更新UI显示，并提示用户
            new_name_from_file = self.config_data.get("service", {}).get("name", "未知设备")
            # 更新UI，但要明确这是“配置文件”中的值
            self.device_name_label.setText(f"<b>设备名 (下次启动生效):</b> {new_name_from_file}")

            self.update_my_shares_list()
            self.controller.restart_file_watcher()

            self.add_log_message("配置已更新。共享列表已立即生效。", "⚙️")
            QMessageBox.information(self, "设置已保存",
                                    "设置已成功保存。\n- 共享文件夹的更改已立即生效。\n- 设备名和端口的更改需要重启应用才能完全生效。")

    # 【全新功能】更新本机共享列表的UI显示
    def update_my_shares_list(self):
        self.my_shares_list_widget.clear()
        shares = self.config_data.get("shares", [])
        if not shares:
            item = QListWidgetItem("无共享文件夹")
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)  # 不可选
            self.my_shares_list_widget.addItem(item)
            return

        for share in shares:
            name = share.get('name', '未命名共享')
            permissions = "可读/写" if "write" in share.get("permissions", []) else "只读"
            item = QListWidgetItem(f"{name} ({permissions})")
            item.setToolTip(share.get('path'))  # 鼠标悬浮显示完整路径
            item.setIcon(self.folder_icon)
            self.my_shares_list_widget.addItem(item)

    def show_about_dialog(self):
        QMessageBox.about(self, "关于 邻里+",
                          "<b>邻里+ (NetNeighbor Plus)</b><br><br>"
                          "一个基于 Python 和 PySide6 的局域网文件共享工具。<br>"
                          "旨在提供一个简单、轻量、跨平台的本地网络文件传输解决方案。<br><br>"
                          "版本: 1.0.0 (Enhanced)")

    def add_log_message(self, message: str, icon: str = "ℹ️"):
        from datetime import datetime
        timestamp = datetime.now().strftime('%H:%M:%S')
        self.log_text_edit.append(f"{icon} [{timestamp}] {message}")


    def handle_websocket_message(self, message: str):
        try:
            data = json.loads(message)
            event = data.get("event")
            name = data.get("name")

            if event == "ws_connected":
                self.add_log_message("已连接到本机事件服务。", "✅")
                return
            if event == "ws_disconnected":
                self.add_log_message("与本机事件服务断开，正在尝试重连...", "⚠️")
                return

            if event == "peer_online":
                self.add_log_message(f"设备已上线: {name}", "🟢")
                self.update_device_list()
            elif event == "peer_offline":
                self.add_log_message(f"设备已下线: {name}", "🔴")
                self.update_device_list()
            elif event == "refresh_files":
                self.add_log_message("文件系统变更，自动刷新当前视图...", "🔄")
                self.refresh_current_file_view()
        except json.JSONDecodeError:
            print(f"收到无法解析的WebSocket消息: {message}")

    def format_size(self, size_bytes):
        if size_bytes <= 0:
            return "" # 对于文件夹或0字节文件，不显示大小
        # 【修复1】使用 math 模块中的函数，而不是 os.path
        size_name = ("B", "KB", "MB", "GB", "TB")
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {size_name[i]}"

    def show_file_context_menu(self, pos):
        selected_items = self.file_table_widget.selectedItems()
        if not selected_items: return

        # 确保我们获取的是行的第一个item来判断
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
        size_str = self.file_table_widget.item(selected_row, 2).data(Qt.UserRole)
        file_size = int(size_str)

        remote_file_path = "/".join(self.active_path_stack + [file_name])

        save_path, _ = QFileDialog.getSaveFileName(self, "保存文件", os.path.join(os.path.expanduser('~'), file_name))
        if not save_path: return

        if not self.active_peer_client or not self.share_selector_combo.currentText():
            QMessageBox.warning(self, "操作失败", "无法执行下载，因为尚未连接到有效的设备或共享。")
            return

        current_share = self.share_selector_combo.currentText()
        TCP_THRESHOLD = 20 * 1024 * 1024  # 20 MB

        current_device_name = self.device_list_widget.currentItem().data(100)
        device_data = self.online_devices_data.get(current_device_name, {})
        tcp_port_str = device_data.get("properties", {}).get("tcp_port")

        if file_size >= TCP_THRESHOLD and tcp_port_str:
            self.add_log_message(f"开始TCP高速下载: {file_name}", "🚀")
            task_args = {'tcp_host': device_data['address'], 'tcp_port': int(tcp_port_str),
                         'header': {"action": "download", "share_name": current_share, "file_path": remote_file_path},
                         'save_path': save_path}
            self.start_worker_thread("download_tcp", "正在高速下载...", task_args)
        else:
            self.add_log_message(f"开始HTTP下载: {file_name}", "⬇️")
            task_args = {'peer_client': self.active_peer_client, 'share_name': current_share,
                         'remote_path': remote_file_path, 'save_path': save_path}
            self.start_worker_thread("download_http", "正在下载...", task_args)

    def handle_upload_action(self):
        if not self.active_peer_client or not self.share_selector_combo.currentText():
            QMessageBox.warning(self, "无法上传", "请先从左侧选择一个在线设备，并从上方选择一个共享文件夹。")
            return

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
        if not self.api_client: return  # 如果自身API客户端还未就绪，则不执行

        peers = self.api_client.get_peers()
        if peers is None:
            self.status_bar_label.setText("无法获取设备列表，请检查网络或重启应用。")
            return

        self.online_devices_data = peers
        self.status_bar_label.setText(f"发现 {len(peers)} 个在线设备。")

        current_selection_name = None
        if self.device_list_widget.currentItem():
            current_selection_name = self.device_list_widget.currentItem().data(100)

        self.device_list_widget.clear()
        item_to_reselect = None

        for full_service_name, data in sorted(peers.items()):
            # 不在列表中显示自己
            if data['address'] == self.my_ip and data['port'] == self.controller.port: continue

            display_name = full_service_name.split('._netneighbor._tcp.local.')[0]
            list_item = QListWidgetItem(self.style().standardIcon(QStyle.SP_DriveNetIcon), display_name)
            list_item.setData(100, full_service_name)
            self.device_list_widget.addItem(list_item)
            if full_service_name == current_selection_name:
                item_to_reselect = list_item

        if item_to_reselect:
            self.device_list_widget.setCurrentItem(item_to_reselect)
        elif not self.active_peer_client and self.device_list_widget.count() > 0:
            # 如果之前没有选择，并且列表不为空，自动选择第一个
            first_item = self.device_list_widget.item(0)
            self.device_list_widget.setCurrentItem(first_item)
            self.handle_device_click(first_item)  # 触发点击事件

    def handle_device_click(self, clicked_item: QListWidgetItem):
        if clicked_item is None: return

        service_name = clicked_item.data(100)
        device_data = self.online_devices_data.get(service_name)

        if not device_data: return

        # 如果点击的是当前已连接的设备，则不重新连接，但可以刷新
        new_base_url = f"http://{device_data['address']}:{device_data['port']}"
        if self.active_peer_client and self.active_peer_client.base_url == new_base_url:
            self.refresh_current_file_view()
            return

        self.active_path_stack = []
        self.active_peer_client = ApiClient(new_base_url)
        self.add_log_message(f"已连接到设备: {clicked_item.text()}", "🔌")

        self.measure_ping(self.active_peer_client, clicked_item.text())

        self.share_selector_combo.blockSignals(True)
        self.share_selector_combo.clear()
        self.update_file_table(None)

        shares = self.active_peer_client.get_shares()
        if shares:
            share_names = [s['name'] for s in shares]
            self.share_selector_combo.addItems(share_names)
            # 【关键】确保在有共享项时启用下拉框
            self.share_selector_combo.setEnabled(True)
            self.upload_button.setEnabled(True)
            self.current_path_label.setText("请选择一个共享")
        else:
            self.current_path_label.setText("对方无共享或获取失败")
            # 【关键】在没有共享项时禁用下拉框
            self.share_selector_combo.setEnabled(False)
            self.upload_button.setEnabled(False)

        self.share_selector_combo.blockSignals(False)
        if self.share_selector_combo.count() > 0:
            self.handle_share_selection_change(0)  # 自动加载第一个共享

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
        if files is None:
            # 可以显示一个提示信息
            return

        self.file_table_widget.setRowCount(len(files))
        files.sort(key=lambda x: (not x['is_dir'], x['name']))  # 文件夹优先，然后按名字排序

        for row, file_info in enumerate(files):
            # 文件名
            name_item = QTableWidgetItem(file_info['name'])
            name_item.setFlags(name_item.flags() | Qt.ItemIsEnabled)
            # 类型和图标
            if file_info['is_dir']:
                type_item = QTableWidgetItem("文件夹")
                name_item.setIcon(self.folder_icon)
            else:
                type_item = QTableWidgetItem("文件")
                name_item.setIcon(self.file_icon)
            type_item.setFlags(type_item.flags() | Qt.ItemIsEnabled)

            # 大小
            size_item = QTableWidgetItem(self.format_size(file_info['size']))
            size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            size_item.setData(Qt.UserRole, file_info['size'])  # 存储原始大小

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

        self.add_log_message("应用正在关闭...", "👋")
        self.controller.stop_all_services()
        if hasattr(self, 'ws_thread') and self.ws_thread.isRunning():
            self.ws_thread.stop()
            self.ws_thread.wait(2000)  # 等待线程结束
        event.accept()