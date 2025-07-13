"""
文件模型类，用于管理文件数据
"""
from typing import Dict, Any, List, Callable, Optional
import math


class FileModel:
    """文件数据模型，管理文件列表"""
    
    def __init__(self):
        self._files: List[Dict[str, Any]] = []
        self._on_files_changed_callbacks: List[Callable[[], None]] = []
        self._current_path: str = "/"
        
    def set_files(self, files: List[Dict[str, Any]]) -> None:
        """设置文件列表"""
        self._files = sorted(files, key=lambda x: (not x['is_dir'], x['name'].lower()))
        self._notify_files_changed()
        
    def get_files(self) -> List[Dict[str, Any]]:
        """获取所有文件"""
        return self._files.copy()
        
    def get_file_count(self) -> int:
        """获取文件数量"""
        return len(self._files)
        
    def get_selected_files(self, selected_rows: List[int]) -> List[Dict[str, Any]]:
        """根据选中的行获取文件信息"""
        result = []
        for row in selected_rows:
            if 0 <= row < len(self._files):
                result.append(self._files[row])
        return result
        
    def clear(self) -> None:
        """清空文件列表"""
        self._files = []
        self._notify_files_changed()
        
    def on_files_changed(self, callback: Callable[[], None]) -> None:
        """注册文件列表变化回调"""
        self._on_files_changed_callbacks.append(callback)
        
    def _notify_files_changed(self) -> None:
        """通知所有回调文件列表已变化"""
        for callback in self._on_files_changed_callbacks:
            callback()
            
    def get_current_path(self) -> str:
        """获取当前路径"""
        return self._current_path
        
    def set_current_path(self, path: str) -> None:
        """设置当前路径"""
        self._current_path = path
        
    @staticmethod
    def format_size(size_bytes: int) -> str:
        """将字节大小格式化为人类可读的字符串"""
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