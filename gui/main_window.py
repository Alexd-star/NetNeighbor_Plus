import os
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
            if self.task_type == "download":
                self._run_download()
            elif self.task_type == "upload":
                self._run_upload()
        except Exception as e:
            self.error.emit(str(e))

    def _run_download(self):
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
        self.finished.emit(f"文件 '{os.path.basename(save_path)}' 下载完成！")

    def _run_upload(self):
        peer_client = self.kwargs['peer_client']
        share_name, dest_path, local_file_path = self.kwargs['share_name'], self.kwargs['dest_path'], self.kwargs[
            'local_file_path']
        self.progress.emit(0)
        peer_client.upload_file_stream(share_name, dest_path, local_file_path)
        self.progress.emit(100)
        self.finished.emit(f"文件上传成功！")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.api_client = ApiClient("http://192.168.182.206:8080")

        self.online_devices_data = {}
        self.current_peer_client: Optional[ApiClient] = None
        self.current_share_name: Optional[str] = None
        self.current_path_stack: list[str] = []
        self.worker_thread = None

        self.setup_window()
        self.setup_ui()
        self.setup_timers()

    def setup_window(self):
        self.setWindowTitle("邻里+ (NetNeighbor Plus)")
        self.setGeometry(100, 100, 1200, 700)

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout()
        central_widget.setLayout(main_layout)
        self.device_list_widget = QListWidget()
        self.device_list_widget.setFixedWidth(250)
        # --- 【核心修正】将信号从 currentItemChanged 改为 itemClicked ---
        # 这样只有在用户真正用鼠标点击时才会触发 on_device_selected
        self.device_list_widget.itemClicked.connect(self.on_device_selected)
        main_layout.addWidget(self.device_list_widget)
        right_panel = QWidget()
        right_layout = QVBoxLayout()
        right_panel.setLayout(right_layout)
        main_layout.addWidget(right_panel)
        toolbar_layout = QHBoxLayout()
        self.back_button = QPushButton("返回上一级")
        self.back_button.clicked.connect(self.go_back_directory)
        self.current_path_label = QLineEdit("/")
        self.current_path_label.setReadOnly(True)
        self.upload_button = QPushButton("上传文件到此")
        self.upload_button.clicked.connect(self.handle_upload_action)
        toolbar_layout.addWidget(self.back_button)
        toolbar_layout.addWidget(self.current_path_label)
        toolbar_layout.addWidget(self.upload_button)
        right_layout.addLayout(toolbar_layout)
        self.file_table_widget = QTableWidget()
        self.file_table_widget.setColumnCount(3)
        self.file_table_widget.setHorizontalHeaderLabels(["文件名", "类型", "大小 (Bytes)"])
        self.file_table_widget.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.file_table_widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.file_table_widget.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.file_table_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.file_table_widget.customContextMenuRequested.connect(self.show_file_context_menu)
        self.file_table_widget.itemDoubleClicked.connect(self.on_item_double_clicked)
        right_layout.addWidget(self.file_table_widget)

    def setup_timers(self):
        self.peer_update_timer = QTimer(self)
        self.peer_update_timer.timeout.connect(self.update_device_list)
        self.peer_update_timer.start(5000)
        self.update_device_list()

    def show_file_context_menu(self, pos):
        if not (selected_items := self.file_table_widget.selectedItems()): return
        row = selected_items[0].row()
        if self.file_table_widget.item(row, 1).text() == "文件夹": return
        menu, download_action = QMenu(), QAction("下载", self)
        download_action.triggered.connect(self.handle_download_action)
        menu.addAction(download_action)
        menu.exec(self.file_table_widget.mapToGlobal(pos))

    def handle_download_action(self):
        if (selected_row := self.file_table_widget.currentRow()) < 0: return
        file_name = self.file_table_widget.item(selected_row, 0).text()
        path_parts = self.current_path_stack + [file_name]
        remote_file_path = "/".join(path_parts)
        if not (save_path := QFileDialog.getSaveFileName(self, "保存文件", file_name)[0]): return
        if not self.current_peer_client or not self.current_share_name: return
        task_args = {'peer_client': self.current_peer_client, 'share_name': self.current_share_name,
                     'remote_path': remote_file_path, 'save_path': save_path}
        self.start_worker_thread("download", "正在下载...", task_args)

    def handle_upload_action(self):
        if not self.current_peer_client or not self.current_share_name: return QMessageBox.warning(self, "错误",
                                                                                                   "请先在左侧选择一个设备。")
        if not (local_file_path := QFileDialog.getOpenFileName(self, "选择要上传的文件")[0]): return
        task_args = {'peer_client': self.current_peer_client, 'share_name': self.current_share_name,
                     'dest_path': "/".join(self.current_path_stack), 'local_file_path': local_file_path}
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
        if self.worker_thread.task_type == 'upload': self.refresh_current_file_view()

    def on_worker_error(self, error_message):
        self.progress_dialog.close();
        QMessageBox.critical(self, "传输错误", f"发生错误: {error_message}")

    def on_item_double_clicked(self, item: QTableWidgetItem):
        if self.file_table_widget.item(item.row(), 1).text() == "文件夹":
            self.current_path_stack.append(self.file_table_widget.item(item.row(), 0).text())
            self.refresh_current_file_view()

    def go_back_directory(self):
        if self.current_path_stack: self.current_path_stack.pop(); self.refresh_current_file_view()

    def refresh_current_file_view(self):
        if not self.current_peer_client or not self.current_share_name: return
        current_path = "/" + "/".join(self.current_path_stack)
        self.current_path_label.setText(current_path)
        files = self.current_peer_client.get_files(self.current_share_name, current_path)
        self.update_file_table(files)

    def update_device_list(self):
        if (peers := self.api_client.get_peers()) is None: return
        self.online_devices_data = peers
        current_item = self.device_list_widget.currentItem()
        current_selection_name = current_item.data(100) if current_item else None
        self.device_list_widget.clear()
        new_item_to_select = None
        for full_service_name, data in peers.items():
            list_item = QListWidgetItem(full_service_name.split('._netneighbor._tcp.local.')[0])
            list_item.setData(100, full_service_name)
            self.device_list_widget.addItem(list_item)
            if full_service_name == current_selection_name: new_item_to_select = list_item
        if new_item_to_select:
            # 这里的setCurrentItem现在是安全的，因为它不会触发on_device_selected
            self.device_list_widget.setCurrentItem(new_item_to_select)

    # --- 【核心修正】函数签名不再需要 previous_item ---
    def on_device_selected(self, current_item: QListWidgetItem):
        """当用户用鼠标点击左侧设备列表中的一项时被调用。"""
        self.current_path_stack = []  # 切换设备时，总是重置路径到根目录
        if current_item is None:
            self.current_peer_client = self.current_share_name = None
            self.update_file_table(None);
            self.current_path_label.setText("/");
            return

        device_data = self.online_devices_data.get(current_item.data(100))
        if not device_data: return

        self.current_peer_client = ApiClient(f"http://{device_data['address']}:{device_data['port']}")
        if (shares := self.current_peer_client.get_shares()) and len(shares) > 0:
            self.current_share_name = shares[0]['name']
            self.refresh_current_file_view()
        else:
            self.current_share_name = None
            self.update_file_table(None);
            self.current_path_label.setText("/")

    def update_file_table(self, files: Optional[list]):
        if files is None: self.file_table_widget.setRowCount(0); return
        self.file_table_widget.setRowCount(len(files))
        for row, file_info in enumerate(files):
            name_item = QTableWidgetItem(file_info['name'])
            type_item = QTableWidgetItem("文件夹" if file_info['is_dir'] else "文件")
            size_item = QTableWidgetItem(str(file_info['size']))
            self.file_table_widget.setItem(row, 0, name_item)
            self.file_table_widget.setItem(row, 1, type_item)
            self.file_table_widget.setItem(row, 2, size_item)