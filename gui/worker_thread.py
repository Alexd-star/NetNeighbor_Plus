"""
工作线程类，用于处理耗时的文件传输任务
"""

import math
import os
import threading
import time
from typing import Dict, Any, List, Optional

from PySide6.QtCore import QThread, Signal

from .conflict_resolver import (
    ConflictResolver,
    check_file_exists_safe,
    check_folder_exists_safe,
    apply_conflict_action_to_tasks,
    create_file_info,
    should_skip_conflict_check,
    is_conflict_cancelled,
)


class WorkerThread(QThread):
    """
    通用工作线程, 处理所有耗时文件/文件夹传输任务。
    """

    progress = Signal(int)  # 进度值（0-100）
    progress_text_update = Signal(str)  # 进度文本更新
    speed_update = Signal(str)  # 速度更新
    file_finished = Signal(str)  # 文件完成消息
    all_finished = Signal()  # 所有任务完成信号
    error = Signal(str)  # 错误信号

    # 文件冲突解决信号
    conflict_resolution_needed = Signal(dict, object)  # 文件信息，事件对象

    def __init__(self, tasks: List[Dict]):
        super().__init__()
        self.tasks = tasks
        self.has_errors = False
        self._is_running = True

        # 使用新的冲突解决器
        self.conflict_resolver = ConflictResolver()
        self.conflict_resolver.conflict_resolution_needed.connect(
            lambda file_info, event: self.conflict_resolution_needed.emit(
                file_info, event
            )
        )

    def set_conflict_resolution_result(self, result):
        """设置冲突解决结果"""
        self.conflict_resolver.set_resolution_result(result)

    def _format_size(self, size_bytes):
        """格式化文件大小为人类可读的形式"""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes/1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes/(1024*1024):.1f} MB"
        else:
            return f"{size_bytes/(1024*1024*1024):.2f} GB"

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

    def _transfer_loop(self, source_iterator, dest_file, total_size):
        """
        通用的数据传输循环，用于文件下载和上传。
        处理进度更新和速度计算。
        """
        received = 0
        last_update_time = time.time()
        bytes_since_last_update = 0
        start_time = time.time()

        # 为流式传输（未知大小）添加估计进度变量
        estimated_progress = 0
        last_progress_update = time.time()

        # 估计文件大小的基准值（100MB，用于未知大小的传输）
        estimated_size = 100 * 1024 * 1024  # 100MB

        # 平滑进度显示的变量
        last_reported_progress = 0
        progress_smoothing_factor = 0.3  # 平滑因子，值越小变化越平滑

        for chunk in source_iterator:
            if not self._is_running:
                raise InterruptedError("Transfer cancelled")

            dest_file.write(chunk)
            chunk_size = len(chunk)
            received += chunk_size
            bytes_since_last_update += chunk_size

            # 更新速度显示（每0.5秒更新一次）
            current_time = time.time()
            if current_time - last_update_time >= 0.5:
                speed = bytes_since_last_update / (current_time - last_update_time)
                self.speed_update.emit(f"{self._format_size(speed)}/s")

                # 更新进度文本，包含已传输数据量
                if total_size > 0:
                    percent = int((received / total_size) * 100)
                    elapsed = current_time - start_time
                    if elapsed > 0 and received > 0:
                        # 估计剩余时间
                        remaining = (total_size - received) / (received / elapsed)
                        if remaining < 60:
                            time_str = f"{int(remaining)}秒"
                        elif remaining < 3600:
                            time_str = (
                                f"{int(remaining / 60)}分钟{int(remaining % 60)}秒"
                            )
                        else:
                            time_str = (
                                f"{int(remaining / 3600)}小时"
                                f"{int((remaining % 3600) / 60)}分钟"
                            )

                        self.progress_text_update.emit(
                            f"已传输: {self._format_size(received)}/"
                            f"{self._format_size(total_size)} ({percent}%) - "
                            f"剩余时间: {time_str}"
                        )
                    else:
                        self.progress_text_update.emit(
                            f"已传输: {self._format_size(received)}/"
                            f"{self._format_size(total_size)} ({percent}%)"
                        )
                else:
                    # 流式传输，显示已接收数据量
                    self.progress_text_update.emit(
                        f"已传输: {self._format_size(received)} - "
                        f"速度: {self._format_size(speed)}/s"
                    )

                last_update_time = current_time
                bytes_since_last_update = 0

            # 更新进度条
            if total_size > 0:
                # 已知总大小，正常计算进度
                self.progress.emit(int((received / total_size) * 100))
            else:
                # 未知总大小，使用估计进度
                current_time = time.time()

                # 每0.5秒更新一次估计进度（更频繁更新以获得更平滑的效果）
                if current_time - last_progress_update >= 0.5:
                    last_progress_update = current_time

                    # 使用更保守的估计大小调整策略
                    if received > estimated_size * 0.9:
                        # 逐渐增加估计大小，避免突然变化
                        estimated_size = estimated_size * 1.2

                    # 计算当前估计进度
                    raw_progress = min(95, int((received / estimated_size) * 100))

                    # 应用平滑算法
                    if last_reported_progress > 0:
                        # 限制每次变化的幅度，使进度更平滑
                        max_change = 3  # 每次最多变化3%
                        if raw_progress > last_reported_progress:
                            # 进度增加
                            progress_change = min(
                                max_change, raw_progress - last_reported_progress
                            )
                            estimated_progress = (
                                last_reported_progress + progress_change
                            )
                        else:
                            # 进度不应该减少，保持不变或微增
                            estimated_progress = last_reported_progress
                    else:
                        # 第一次更新，直接使用计算值
                        estimated_progress = raw_progress

                    # 记录本次报告的进度值
                    last_reported_progress = estimated_progress

                    # 发送进度更新
                    self.progress.emit(estimated_progress)

    def _run_download_file(self, task_info):
        """下载单个文件的具体实现。"""
        p_client = task_info["peer_client"]
        s_name = task_info["share_name"]
        r_path = task_info["remote_path"]
        save_p = task_info["save_path"]
        file_name = os.path.basename(save_p)

        with p_client.download_file_stream(s_name, r_path) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))
            with open(save_p, "wb") as f:
                self._transfer_loop(resp.iter_bytes(chunk_size=8192), f, total)

        self.file_finished.emit(f"文件 '{file_name}' 下载完成！")

    def _run_download_folder_tcp(self, task_info):
        """
        通过高性能TCP通道下载并打包文件夹。
        使用 'with' 语句来确保连接资源被正确管理。
        """
        peer_client, share_name = task_info["peer_client"], task_info["share_name"]
        remote_path, save_path = task_info["remote_path"], task_info["save_path"]
        folder_name = task_info["name"]

        self.progress_text_update.emit(f"正在准备下载 '{folder_name}.zip'...")

        # 添加初始进度更新，让用户知道任务已经开始
        self.progress.emit(1)  # 设置初始进度为1%

        try:
            # 使用 'with' 语句来安全地使用 TcpDownloader
            # 当 with 代码块结束时, downloader.__exit__ 会被自动调用, socket 会被关闭
            self.progress_text_update.emit(
                f"开始下载 '{folder_name}.zip' (TCP高速模式)..."
            )
            with peer_client.download_folder_tcp(share_name, remote_path) as downloader:
                with open(save_path, "wb") as f:
                    # 将 downloader (它本身就是个迭代器) 传入传输循环
                    # 我们现在使用估计进度，而不是不确定模式
                    self._transfer_loop(downloader, f, 0)
        except Exception as e:
            # 将任何发生的异常往上抛，由总的错误处理器来显示给用户
            raise e

        # 下载完成后，设置进度为100%
        self.progress.emit(100)
        self.file_finished.emit(
            f"文件夹 '{folder_name}' 已通过TCP高速下载为 '{os.path.basename(save_path)}'！"
        )

    def _run_upload_folder(self, task_info):
        """上传文件夹的具体实现，支持冲突处理。"""
        local_folder = task_info["local_path"]
        p_client = task_info["peer_client"]
        s_name = task_info["share_name"]
        base_dest = task_info["dest_path"]
        folder_name = task_info["name"]
        conflict_action = task_info.get("conflict_action", "ask")

        # 添加进度文本更新，让用户知道当前状态
        self.progress_text_update.emit(f"正在准备上传文件夹: {folder_name}")

        # 检查文件夹是否已存在并处理冲突
        if conflict_action == "ask":
            folder_exists = check_folder_exists_safe(
                p_client, s_name, base_dest, folder_name
            )

            if folder_exists:
                file_info = create_file_info(folder_name, is_folder=True)
                conflict_result = self.conflict_resolver.resolve_conflict(file_info)

                if is_conflict_cancelled(conflict_result):
                    return

                conflict_action = conflict_result.get("action", "skip")

                # 如果用户选择应用到所有冲突，更新所有后续任务
                if conflict_result.get("apply_to_all"):
                    apply_conflict_action_to_tasks(
                        self.tasks, conflict_action, "upload_folder"
                    )

        # 如果用户选择跳过，则直接返回
        if conflict_action == "skip":
            self.file_finished.emit(f"已跳过上传: {folder_name}")
            return

        # 添加进度更新，计算总大小
        self.progress_text_update.emit(f"正在计算文件夹大小: {folder_name}")

        # 计算文件夹总大小，用于进度显示
        total_size = 0
        file_count = 0
        try:
            for root, dirs, files in os.walk(local_folder):
                for file in files:
                    file_path = os.path.join(root, file)
                    if os.path.isfile(file_path):
                        total_size += os.path.getsize(file_path)
                        file_count += 1

                        # 每处理100个文件更新一次进度，避免大文件夹计算时间过长无反馈
                        if file_count % 100 == 0:
                            self.progress_text_update.emit(
                                f"正在计算文件夹大小: 已扫描 {file_count} 个文件..."
                            )
        except Exception as e:
            print(f"计算文件夹大小时出错: {e}")
            # 如果无法计算大小，则使用0表示未知
            total_size = 0

        # 添加文件数量信息
        self.progress_text_update.emit(
            f"开始上传文件夹: {folder_name} (共 {file_count} 个文件, {self._format_size(total_size)})"
        )
        QThread.msleep(100)  # 短暂延迟，确保UI更新

        # 设置进度回调函数
        sent_bytes = 0
        last_update_time = time.time()
        bytes_since_last_update = 0
        start_time = time.time()

        def progress_callback(chunk_len):
            nonlocal sent_bytes, last_update_time, bytes_since_last_update, start_time
            sent_bytes += chunk_len
            bytes_since_last_update += chunk_len

            current_time = time.time()
            time_delta = current_time - last_update_time
            if time_delta >= 0.5:
                # 计算速度
                speed = bytes_since_last_update / time_delta
                self.speed_update.emit(f"{self._format_size(speed)}/s")

                # 计算剩余时间
                elapsed_time = current_time - start_time
                if sent_bytes > 0 and total_size > 0:
                    progress_percent = sent_bytes / total_size
                    if progress_percent > 0:
                        estimated_total_time = elapsed_time / progress_percent
                        remaining_time = estimated_total_time - elapsed_time

                        # 格式化剩余时间
                        if remaining_time < 60:
                            time_str = f"{int(remaining_time)}秒"
                        elif remaining_time < 3600:
                            time_str = f"{int(remaining_time / 60)}分钟{int(remaining_time % 60)}秒"
                        else:
                            time_str = f"{int(remaining_time / 3600)}小时{int((remaining_time % 3600) / 60)}分钟"

                        # 更新进度文本，包含剩余时间
                        self.progress_text_update.emit(
                            f"上传文件夹: {folder_name} ({self._format_size(sent_bytes)}/{self._format_size(total_size)}, 剩余时间: {time_str})"
                        )

                last_update_time = current_time
                bytes_since_last_update = 0

            if total_size > 0:
                self.progress.emit(int((sent_bytes / total_size) * 100))

        try:
            # 添加tar包装开始提示
            self.progress_text_update.emit(f"正在打包文件夹: {folder_name}")

            # 使用TarUploader将文件夹打包并上传
            from gui.api_client import TarUploader

            with TarUploader(local_folder, progress_callback) as tar_uploader:
                result = p_client.upload_folder_tar(
                    s_name, base_dest, tar_uploader, conflict_action
                )

                # 重置速度显示
                self.speed_update.emit("")

                # 添加完成提示，包含总上传大小和时间
                total_time = time.time() - start_time
                if total_time < 60:
                    time_str = f"{total_time:.1f}秒"
                elif total_time < 3600:
                    time_str = f"{int(total_time / 60)}分钟" f"{int(total_time % 60)}秒"
                else:
                    time_str = (
                        f"{int(total_time / 3600)}小时"
                        f"{int((total_time % 3600) / 60)}分钟"
                    )

                self.progress_text_update.emit(
                    f"文件夹 '{folder_name}' 上传完成 "
                    f"({self._format_size(total_size)}, 耗时: {time_str})"
                )

                # 添加延迟，确保UI更新
                QThread.msleep(100)

                # 根据上传结果显示不同的消息
                if result.get("action") == "renamed":
                    new_folder_name = result.get("folder_name", folder_name)
                    self.file_finished.emit(
                        f"文件夹 '{folder_name}' 已重命名为 '{new_folder_name}' 并上传成功。"
                    )
                elif result.get("action") == "skipped":
                    self.file_finished.emit(f"已跳过上传: {folder_name}")
                elif result.get("action") == "merge":
                    self.file_finished.emit(f"文件夹 '{folder_name}' 已合并上传成功。")
                else:
                    self.file_finished.emit(f"文件夹 '{folder_name}' 上传成功。")
        except Exception as e:
            # 捕获上传过程中的异常
            self.progress_text_update.emit(f"上传文件夹时出错: {e}")
            raise Exception(f"上传文件夹时出错: {e}")

    def _run_upload_file(self, task_info):
        """上传单个文件的具体实现。"""
        local_path = task_info["local_path"]
        file_name = os.path.basename(local_path)
        p_client = task_info["peer_client"]
        s_name = task_info["share_name"]
        dest_path = task_info["dest_path"]
        conflict_action = task_info.get("conflict_action", "ask")

        # 检查文件是否已存在并处理冲突
        if conflict_action == "ask":
            file_exists = check_file_exists_safe(p_client, s_name, dest_path, file_name)

            if file_exists:
                file_info = create_file_info(file_name, is_folder=False)
                conflict_result = self.conflict_resolver.resolve_conflict(file_info)

                if is_conflict_cancelled(conflict_result):
                    return

                conflict_action = conflict_result.get("action", "skip")

                # 如果用户选择应用到所有冲突，更新所有后续任务
                if conflict_result.get("apply_to_all"):
                    apply_conflict_action_to_tasks(
                        self.tasks, conflict_action, "upload_file"
                    )

                # 如果用户选择跳过，直接返回
                if conflict_action == "skip":
                    self.file_finished.emit(f"已跳过上传: {file_name}")
                    return

        # 标记任务为已处理
        task_info["processed"] = True

        # 设置进度回调函数
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

        try:
            # 使用API客户端上传文件
            from gui.api_client import UploadStreamer

            with UploadStreamer(local_path, progress_callback) as uploader:
                result = p_client.upload_file_stream(
                    s_name, dest_path, uploader, conflict_action
                )

            # 重置速度显示
            self.speed_update.emit("")

            # 根据上传结果显示不同的消息
            if result.get("action") == "renamed":
                new_filename = result.get("filename", file_name)
                self.file_finished.emit(
                    f"文件 '{file_name}' 已重命名为 '{new_filename}' 并上传成功。"
                )
            elif result.get("action") == "skipped":
                self.file_finished.emit(f"已跳过上传: {file_name}")
            else:
                self.file_finished.emit(f"文件 '{file_name}' 上传成功。")
        except Exception as e:
            raise Exception(f"上传文件时出错: {e}")
