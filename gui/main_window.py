import os
import socket
import json
from PySide6.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QListWidget, QTableWidget,
                               QAbstractItemView, QHeaderView, QListWidgetItem, QTableWidgetItem,
                               QMenu, QMessageBox, QFileDialog, QPushButton, QLineEdit, QProgressDialog)
from PySide6.QtCore import QTimer, Qt, QThread, Signal
from PySide6.QtGui import QAction
from typing import Optional
from .api_client import ApiClient


class WorkerThread(QThread):
    progress = Signal(int)
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, task_type, **kwargs):
        super().__init__()
        self.task_type = task_type
        self.kwargs = kwargs

    def run(self):
        try:
            if self.task_type == "download_http":
                self._run_download_http()
            elif self.task_type == "download_tcp":
                self._run_download_tcp()
            elif self.task_type == "upload":
                self._run_upload()
        except Exception as e:
            self.error.emit(str(e))

    def _run_download_http(self):
        peer_client = self.kwargs['peer_client']
        share_name, remote_path, save_path = self.kwargs['share_name'], self.kwargs['remote_path'], self.kwargs[
            'save_path']
        with peer_client.download_file_stream(share_name, remote_path) as response:
            response.raise_for_status()
            total_size = int(response.headers.get('content-length', 0))
            downloaded_size = 0
            with open(save_path, "wb") as f:
                for chunk in response.iter_bytes(chunk_size=8192):
                    f.write(chunk)
                    downloaded_size += len(chunk)
                    if total_size > 0:
                        self.progress.emit(int((downloaded_size / total_size) * 100))
        self.finished.emit(f"文件 '{os.path.basename(save_path)}' (HTTP) 下载完成！")

    def _run_download_tcp(self):
        tcp_host, tcp_port = self.kwargs['tcp_host'], self.kwargs['tcp_port']
        header, save_path = self.kwargs['header'], self.kwargs['save_path']
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((tcp_host, tcp_port))
            s.sendall(json.dumps(header).encode('utf-8'))
            response_header = json.loads(s.recv(1024).decode('utf-8'))
            if response_header.get("status") != "ok":
                raise ConnectionError(f"服务器错误: {response_header.get('message')}")
            total_size = response_header.get("size", 0)
            s.sendall(b'ready')
            downloaded_size = 0
            with open(save_path, 'wb') as f:
                while downloaded_size < total_size:
                    chunk = s.recv(4 * 1024 * 1024)
                    if not chunk: break
                    f.write(chunk)
                    downloaded_size += len(chunk)
                    if total_size > 0: self.progress.emit(int((downloaded_size / total_size) * 100))
        self.finished.emit(f"文件 '{os.path.basename(save_path)}' (TCP高速) 下载完成！")

    def _run_upload(self):
        peer_client, share_name, dest_path, local_file_path = self.kwargs['peer_client'], self.kwargs['share_name'], \
                                                              self.kwargs['dest_path'], self.kwargs['local_file_path']
        self.progress.emit(0)
        peer_client.upload_file_stream(share_name, dest_path, local_file_path)
        self.progress.emit(100)
        self.finished.emit(f"文件上传成功！")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.api_client = ApiClient("http://192.168.182.206:8080")

        # --- 【核心修正】在这里完整地初始化所有状态变量 ---
        self.online_devices_data = {}
        self.active_peer_client: Optional[ApiClient] = None
        self.active_share_name: Optional[str] = None
        self.active_path_stack: list[str] = []
        self.worker_thread: Optional[WorkerThread] = None

        self.setup_window()
        self.setup_ui()
        self.setup_timers()

    def setup_window(self):
        self.setWindowTitle("邻里+ (NetNeighbor Plus)")
        self.setGeometry(100, 100, 1200, 700)

    def setup_ui(self):
        central_widget = QWidget();
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout();
        central_widget.setLayout(main_layout)
        self.device_list_widget = QListWidget();
        self.device_list_widget.setFixedWidth(250)
        self.device_list_widget.itemClicked.connect(self.handle_device_click)
        main_layout.addWidget(self.device_list_widget)
        right_panel, right_layout = QWidget(), QVBoxLayout();
        right_panel.setLayout(right_layout);
        main_layout.addWidget(right_panel)
        toolbar_layout = QHBoxLayout()
        self.back_button = QPushButton("返回上一级");
        self.back_button.clicked.connect(self.go_back_directory)
        self.current_path_label = QLineEdit("/");
        self.current_path_label.setReadOnly(True)
        self.upload_button = QPushButton("上传文件到此");
        self.upload_button.clicked.connect(self.handle_upload_action)
        toolbar_layout.addWidget(self.back_button);
        toolbar_layout.addWidget(self.current_path_label);
        toolbar_layout.addWidget(self.upload_button)
        right_layout.addLayout(toolbar_layout)
        self.file_table_widget = QTableWidget();
        self.file_table_widget.setColumnCount(3)
        self.file_table_widget.setHorizontalHeaderLabels(["文件名", "类型", "大小 (Bytes)"])
        self.file_table_widget.setSelectionBehavior(QAbstractItemView.SelectRows);
        self.file_table_widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.file_table_widget.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.file_table_widget.setContextMenuPolicy(Qt.CustomContextMenu);
        self.file_table_widget.customContextMenuRequested.connect(self.show_file_context_menu)
        self.file_table_widget.itemDoubleClicked.connect(self.on_item_double_clicked)
        right_layout.addWidget(self.file_table_widget)

    def setup_timers(self):
        self.peer_update_timer = QTimer(self);
        self.peer_update_timer.timeout.connect(self.update_device_list);
        self.peer_update_timer.start(5000)
        self.update_device_list()

    def show_file_context_menu(self, pos):
        if not (selected_items := self.file_table_widget.selectedItems()): return
        if self.file_table_widget.item(selected_items[0].row(), 1).text() == "文件夹": return
        menu, download_action = QMenu(), QAction("下载", self)
        download_action.triggered.connect(self.handle_download_action)
        menu.addAction(download_action)
        menu.exec(self.file_table_widget.mapToGlobal(pos))

    def handle_download_action(self):
        if (selected_row := self.file_table_widget.currentRow()) < 0: return
        file_name = self.file_table_widget.item(selected_row, 0).text()
        file_size = int(self.file_table_widget.item(selected_row, 2).text())
        path_parts = self.active_path_stack + [file_name]
        remote_file_path = "/".join(path_parts)
        if not (save_path := QFileDialog.getSaveFileName(self, "保存文件", file_name)[0]): return
        if not self.active_peer_client or not self.active_share_name: return

        TCP_THRESHOLD = 20 * 1024 * 1024
        current_device_item = self.device_list_widget.currentItem()
        if not current_device_item: return
        full_service_name = current_device_item.data(100)
        device_data = self.online_devices_data.get(full_service_name, {})
        tcp_port_str = device_data.get("properties", {}).get("tcp_port")

        if file_size >= TCP_THRESHOLD and tcp_port_str:
            print("决策：使用TCP高速通道下载...")
            task_args = {'tcp_host': device_data['address'], 'tcp_port': int(tcp_port_str),
                         'header': {"action": "download", "share_name": self.active_share_name,
                                    "file_path": remote_file_path}, 'save_path': save_path}
            self.start_worker_thread("download_tcp", "正在高速下载...", task_args)
        else:
            print("决策：使用HTTP普通通道下载...")
            task_args = {'peer_client': self.active_peer_client, 'share_name': self.active_share_name,
                         'remote_path': remote_file_path, 'save_path': save_path}
            self.start_worker_thread("download_http", "正在下载...", task_args)

    def handle_upload_action(self):
        if not self.active_peer_client or not self.active_share_name: return QMessageBox.warning(self, "错误",
                                                                                                 "请先在左侧选择一个设备。")
        if not (local_file_path := QFileDialog.getOpenFileName(self, "选择要上传的文件")[0]): return
        task_args = {'peer_client': self.active_peer_client, 'share_name': self.active_share_name,
                     'dest_path': "/".join(self.active_path_stack), 'local_file_path': local_file_path}
        self.start_worker_thread("upload", "正在上传...", task_args)

    def start_worker_thread(self, task_type, progress_title, kwargs):
        self.progress_dialog = QProgressDialog(progress_title, "取消", 0, 100, self)
        self.progress_dialog.setWindowModality(Qt.WindowModal);
        self.progress_dialog.setAutoClose(False);
        self.progress_dialog.setAutoReset(False)
        self.worker_thread = WorkerThread(task_type, **kwargs)
        self.worker_thread.progress.connect(self.progress_dialog.setValue)
        self.worker_thread.finished.connect(self.on_worker_finished)
        self.worker_thread.error.connect(self.on_worker_error)
        self.progress_dialog.canceled.connect(self.worker_thread.terminate)
        self.worker_thread.start();
        self.progress_dialog.show()

    def on_worker_finished(self, message):
        self.progress_dialog.close();
        QMessageBox.information(self, "成功", message)
        if self.worker_thread and self.worker_thread.task_type == 'upload': self.refresh_current_file_view()

    def on_worker_error(self, error_message):
        self.progress_dialog.close();
        QMessageBox.critical(self, "传输错误", f"发生错误: {error_message}")

    def on_item_double_clicked(self, item: QTableWidgetItem):
        if self.file_table_widget.item(item.row(), 1).text() == "文件夹":
            self.active_path_stack.append(self.file_table_widget.item(item.row(), 0).text())
            self.refresh_current_file_view()

    def go_back_directory(self):
        if self.active_path_stack: self.active_path_stack.pop(); self.refresh_current_file_view()

    def refresh_current_file_view(self):
        if not self.active_peer_client or not self.active_share_name: return
        current_path = "/" + "/".join(self.active_path_stack)
        self.current_path_label.setText(current_path)
        files = self.active_peer_client.get_files(self.active_share_name, current_path)
        self.update_file_table(files)

    def update_device_list(self):
        if (peers := self.api_client.get_peers()) is None: return
        self.online_devices_data = peers
        current_item = self.device_list_widget.currentItem()
        current_selection_name = current_item.data(100) if current_item else None
        self.device_list_widget.clear()
        item_to_reselect = None
        for full_service_name, data in peers.items():
            list_item = QListWidgetItem(full_service_name.split('._netneighbor._tcp.local.')[0])
            list_item.setData(100, full_service_name)
            self.device_list_widget.addItem(list_item)
            if full_service_name == current_selection_name:
                item_to_reselect = list_item
        if item_to_reselect:
            self.device_list_widget.setCurrentItem(item_to_reselect)
        if self.active_peer_client is None and self.device_list_widget.count() > 0:
            first_item = self.device_list_widget.item(0)
            self.device_list_widget.setCurrentItem(first_item)
            self.handle_device_click(first_item)

    def handle_device_click(self, clicked_item: QListWidgetItem):
        if clicked_item is None: return
        service_name = clicked_item.data(100)
        device_data = self.online_devices_data.get(service_name)
        if not device_data: return

        # 检查是否点击的是当前已激活的设备
        if self.active_peer_client and self.active_peer_client.base_url.find(device_data['address']) != -1:
            return

        self.active_path_stack = []
        self.active_peer_client = ApiClient(f"http://{device_data['address']}:{device_data['port']}")
        if (shares := self.active_peer_client.get_shares()) and len(shares) > 0:
            self.active_share_name = shares[0]['name']
            self.refresh_current_file_view()
        else:
            self.active_share_name = None
            self.update_file_table(None);
            self.current_path_label.setText("/")

    def update_file_table(self, files: Optional[list]):
        if files is None: self.file_table_widget.setRowCount(0); return
        self.file_table_widget.setRowCount(len(files))
        for row, file_info in enumerate(files):
            self.file_table_widget.setItem(row, 0, QTableWidgetItem(file_info['name']))
            self.file_table_widget.setItem(row, 1, QTableWidgetItem("文件夹" if file_info['is_dir'] else "文件"))
            self.file_table_widget.setItem(row, 2, QTableWidgetItem(str(file_info['size'])))