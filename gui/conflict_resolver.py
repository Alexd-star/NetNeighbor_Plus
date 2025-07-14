"""
冲突解决器，处理文件上传时的冲突情况
"""

import threading
from typing import Dict, Any, Optional
from PySide6.QtCore import QObject, Signal


class ConflictResolver(QObject):
    """统一的冲突解决处理器"""

    # 冲突解决信号
    conflict_resolution_needed = Signal(dict, object)  # 文件信息，事件对象

    def __init__(self):
        super().__init__()
        self.conflict_resolution_result: Optional[Dict[str, Any]] = None

    def resolve_conflict(self, file_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:

        # 创建事件对象用于线程同步
        event = threading.Event()

        # 发射信号请求主线程处理冲突
        self.conflict_resolution_needed.emit(file_info, event)

        # 等待主线程处理完成
        event.wait()

        # 获取处理结果
        result = self.conflict_resolution_result

        # 重置结果
        self.conflict_resolution_result = None

        return result

    def set_resolution_result(self, result: Dict[str, Any]):

        self.conflict_resolution_result = result


def check_file_exists_safe(
    api_client, share_name: str, dest_path: str, filename: str
) -> bool:

    try:
        return api_client.check_file_exists(share_name, dest_path, filename)
    except Exception as e:
        print(f"检查文件是否存在时出错: {e}")
        return False


def check_folder_exists_safe(
    api_client, share_name: str, dest_path: str, folder_name: str
) -> bool:

    try:
        # 首先尝试专用的检查方法
        if hasattr(api_client, "check_folder_exists"):
            return api_client.check_folder_exists(share_name, dest_path, folder_name)
    except Exception as e:
        print(f"检查文件夹是否存在时出错: {e}")

    try:
        # 备用方法：尝试获取文件夹内容
        full_path = f"{dest_path}/{folder_name}".replace("//", "/")
        files = api_client.get_files(share_name, full_path)
        return files is not None
    except Exception:
        # 如果两种方法都失败，假设文件夹不存在
        return False


def apply_conflict_action_to_tasks(tasks: list, conflict_action: str, task_type: str):

    for task in tasks:
        if task.get("type") == task_type and not task.get("processed", False):
            task["conflict_action"] = conflict_action


def create_file_info(filename: str, is_folder: bool = False) -> Dict[str, Any]:

    return {"file_name": filename, "is_folder": is_folder}


def should_skip_conflict_check(conflict_action: str) -> bool:

    return conflict_action in ["overwrite", "rename", "merge"]


def is_conflict_cancelled(conflict_result: Optional[Dict[str, Any]]) -> bool:

    return conflict_result is None or conflict_result.get("action") == "cancelled"
