"""
设备列表视图类，用于显示在线设备
"""

import re
from typing import Dict, Any, Optional, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QWidget, QVBoxLayout, QLabel


def natural_sort_key(s: str) -> list:
    """
    为字符串生成一个可用于自然排序的键。
    例如，'v10' 会被转换为 ['v', 10]，'v2' 会被转换为 ['v', 2]。
    这样在比较时，10 会被正确地识别为大于 2。
    """
    result = []
    parts = re.split(r"(\d+)", s)
    for part in parts:
        if part.isdigit():
            result.append(int(part))
        else:
            result.append(part.lower())
    return result


class DeviceListView(QWidget):
    """设备列表视图，显示在线设备"""

    device_selected = Signal(str)  # 发射设备服务名称

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

        # 设备项缓存，避免重复创建
        self._device_items = {}  # service_name -> QListWidgetItem
        self._update_pending = False

    def _setup_ui(self):
        """设置UI组件"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)

        # 标题
        title_label = QLabel("<h4>在线设备</h4>")
        layout.addWidget(title_label)

        # 设备列表
        self.device_list_widget = QListWidget()
        self.device_list_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.device_list_widget.itemClicked.connect(self._on_device_clicked)
        layout.addWidget(self.device_list_widget)

        # 设置最小高度
        self.setMinimumHeight(180)

    def _on_device_clicked(self, item: QListWidgetItem):
        """处理设备项点击事件"""
        service_name = item.data(Qt.ItemDataRole.UserRole)
        self.device_selected.emit(service_name)

    def clear_devices(self):
        """清空设备列表"""
        self.device_list_widget.clear()
        self._device_items.clear()

    def add_device(
        self,
        service_name: str,
        display_name: str,
        device_type: str,
        icon: Optional[QIcon] = None,
    ):
        """添加设备到列表 - 增量更新版本"""
        # 如果设备已存在，先移除
        if service_name in self._device_items:
            self.remove_device(service_name)

        item = QListWidgetItem(f"{display_name}\n类型: {device_type}")
        if icon:
            item.setIcon(icon)
        item.setData(Qt.ItemDataRole.UserRole, service_name)

        # 使用自然排序算法查找插入位置
        inserted = False
        for i in range(self.device_list_widget.count()):
            existing_item = self.device_list_widget.item(i)
            existing_display_name = existing_item.text().split("\n")[0]

            if natural_sort_key(display_name) < natural_sort_key(existing_display_name):
                self.device_list_widget.insertItem(i, item)
                inserted = True
                break

        # 如果没有找到合适的位置，添加到末尾
        if not inserted:
            self.device_list_widget.addItem(item)

        # 缓存设备项
        self._device_items[service_name] = item

    def remove_device(self, service_name: str):
        """从列表中移除设备 - 增量更新版本"""
        if service_name in self._device_items:
            item = self._device_items[service_name]
            # 找到项目在列表中的位置并移除
            for i in range(self.device_list_widget.count()):
                if self.device_list_widget.item(i) == item:
                    self.device_list_widget.takeItem(i)
                    break
            # 从缓存中移除
            del self._device_items[service_name]

    def update_devices(self, devices: Dict[str, Dict[str, Any]], device_icon: QIcon):
        """更新整个设备列表 - 智能增量更新版本"""
        # 获取当前设备列表
        current_devices = set(self._device_items.keys())
        new_devices = set(devices.keys())

        # 找出需要移除的设备
        devices_to_remove = current_devices - new_devices
        for service_name in devices_to_remove:
            self.remove_device(service_name)

        # 找出需要添加或更新的设备
        devices_to_add_or_update = new_devices - current_devices
        for service_name in devices_to_add_or_update:
            device_data = devices[service_name]
            display_name = service_name.split("._netneighbor._tcp.local.")[0]
            dev_type = device_data.get("properties", {}).get("dev_type", "未知")
            self.add_device(service_name, display_name, dev_type, device_icon)

    def update_devices_full(
        self, devices: Dict[str, Dict[str, Any]], device_icon: QIcon
    ):
        """完全重建设备列表 - 仅在必要时使用"""
        self.clear_devices()

        # 使用自然排序对设备进行排序
        sorted_devices = sorted(
            devices.items(),
            key=lambda item: natural_sort_key(
                item[0].split("._netneighbor._tcp.local.")[0]
            ),
        )

        for service_name, device_data in sorted_devices:
            display_name = service_name.split("._netneighbor._tcp.local.")[0]
            dev_type = device_data.get("properties", {}).get("dev_type", "未知")
            self.add_device(service_name, display_name, dev_type, device_icon)

    def get_device_count(self) -> int:
        """获取设备数量"""
        return self.device_list_widget.count()
