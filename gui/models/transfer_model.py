"""
传输任务模型类，用于管理文件传输任务
"""
from typing import Dict, Any, List, Callable, Optional, Union
import os
import time
import math


class TransferModel:
    """传输任务数据模型，管理文件传输任务"""
    
    def __init__(self):
        self._tasks: List[Dict[str, Any]] = []
        self._is_transfer_active: bool = False
        self._progress: int = 0
        self._progress_text: str = ""
        self._speed_text: str = ""
        self._current_task_index: int = 0
        self._start_time: float = 0
        
        self._on_transfer_state_changed_callbacks: List[Callable[[bool], None]] = []
        self._on_progress_changed_callbacks: List[Callable[[int], None]] = []
        self._on_progress_text_changed_callbacks: List[Callable[[str], None]] = []
        self._on_speed_text_changed_callbacks: List[Callable[[str], None]] = []
        
    def set_tasks(self, tasks: List[Dict[str, Any]]) -> None:
        """设置传输任务列表"""
        self._tasks = tasks
        
    def get_tasks(self) -> List[Dict[str, Any]]:
        """获取传输任务列表"""
        return self._tasks.copy()
        
    def start_transfer(self) -> None:
        """开始传输任务"""
        self._is_transfer_active = True
        self._progress = 0
        self._progress_text = "准备开始..."
        self._speed_text = ""
        self._current_task_index = 0
        self._start_time = time.time()
        
        self._notify_transfer_state_changed()
        self._notify_progress_changed()
        self._notify_progress_text_changed()
        self._notify_speed_text_changed()
        
    def stop_transfer(self) -> None:
        """停止传输任务"""
        self._is_transfer_active = False
        self._notify_transfer_state_changed()
        
    def is_transfer_active(self) -> bool:
        """检查是否有传输任务正在进行"""
        return self._is_transfer_active
        
    def set_is_transfer_active(self, active: bool) -> None:
        """设置传输任务状态"""
        if self._is_transfer_active != active:
            self._is_transfer_active = active
            self._notify_transfer_state_changed()
        
    def set_progress(self, progress: int) -> None:
        """设置进度值（0-100）"""
        if self._progress != progress:
            self._progress = progress
            self._notify_progress_changed()
            
    def get_progress(self) -> int:
        """获取当前进度值"""
        return self._progress
        
    def set_progress_text(self, text: str) -> None:
        """设置进度文本"""
        if self._progress_text != text:
            self._progress_text = text
            self._notify_progress_text_changed()
            
    def get_progress_text(self) -> str:
        """获取进度文本"""
        return self._progress_text
        
    def set_speed_text(self, text: str) -> None:
        """设置速度文本"""
        if self._speed_text != text:
            self._speed_text = text
            self._notify_speed_text_changed()
            
    def get_speed_text(self) -> str:
        """获取速度文本"""
        return self._speed_text
        
    def set_current_task_index(self, index: int) -> None:
        """设置当前任务索引"""
        self._current_task_index = index
        
    def get_current_task_index(self) -> int:
        """获取当前任务索引"""
        return self._current_task_index
        
    def get_current_task(self) -> Optional[Dict[str, Any]]:
        """获取当前任务"""
        if 0 <= self._current_task_index < len(self._tasks):
            return self._tasks[self._current_task_index]
        return None
        
    def get_elapsed_time(self) -> float:
        """获取已经过时间（秒）"""
        if self._start_time == 0:
            return 0
        return time.time() - self._start_time
        
    def format_elapsed_time(self) -> str:
        """格式化已经过时间"""
        elapsed = self.get_elapsed_time()
        if elapsed < 60:
            return f"{elapsed:.1f}秒"
        elif elapsed < 3600:
            minutes = int(elapsed / 60)
            seconds = int(elapsed % 60)
            return f"{minutes}分钟{seconds}秒"
        else:
            hours = int(elapsed / 3600)
            minutes = int((elapsed % 3600) / 60)
            return f"{hours}小时{minutes}分钟"
            
    def on_transfer_state_changed(self, callback: Callable[[bool], None]) -> None:
        """注册传输状态变化回调"""
        self._on_transfer_state_changed_callbacks.append(callback)
        
    def on_progress_changed(self, callback: Callable[[int], None]) -> None:
        """注册进度变化回调"""
        self._on_progress_changed_callbacks.append(callback)
        
    def on_progress_text_changed(self, callback: Callable[[str], None]) -> None:
        """注册进度文本变化回调"""
        self._on_progress_text_changed_callbacks.append(callback)
        
    def on_speed_text_changed(self, callback: Callable[[str], None]) -> None:
        """注册速度文本变化回调"""
        self._on_speed_text_changed_callbacks.append(callback)
        
    def _notify_transfer_state_changed(self) -> None:
        """通知所有回调传输状态已变化"""
        for callback in self._on_transfer_state_changed_callbacks:
            callback(self._is_transfer_active)
            
    def _notify_progress_changed(self) -> None:
        """通知所有回调进度已变化"""
        for callback in self._on_progress_changed_callbacks:
            callback(self._progress)
            
    def _notify_progress_text_changed(self) -> None:
        """通知所有回调进度文本已变化"""
        for callback in self._on_progress_text_changed_callbacks:
            callback(self._progress_text)
            
    def _notify_speed_text_changed(self) -> None:
        """通知所有回调速度文本已变化"""
        for callback in self._on_speed_text_changed_callbacks:
            callback(self._speed_text)
            
    @staticmethod
    def format_size(size_bytes: Union[int, float]) -> str:
        """将字节大小格式化为人类可读的字符串"""
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