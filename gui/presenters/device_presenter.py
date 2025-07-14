"""
设备列表控制器，管理设备列表的显示和交互
"""

from typing import Dict, Any, Optional, Callable

from PySide6.QtGui import QIcon

from gui.models.device_model import DeviceModel
from gui.views.device_list_view import DeviceListView


class DevicePresenter:
    """设备列表Presenter，连接设备模型和视图"""

    def __init__(self, model: DeviceModel, view: DeviceListView):
        self.model = model
        self.view = view
        self.device_icon = None

        # 连接模型和视图 - 使用增量更新
        self.model.on_device_added(self._on_device_added)
        self.model.on_device_removed(self._on_device_removed)
        self.model.on_device_list_changed(self._on_device_list_changed)
        self.view.device_selected.connect(self._on_device_selected)

        # 回调函数
        self._on_device_selected_callback = None

    def set_device_icon(self, icon: QIcon):
        """设置设备图标"""
        self.device_icon = icon
        # 设置图标后，显示现有设备
        self._update_view_incremental()

    def _on_device_added(self, service_name: str, device_data: dict):
        """处理设备添加 - 增量更新"""
        if self.device_icon:
            display_name = service_name.split("._netneighbor._tcp.local.")[0]
            dev_type = device_data.get("properties", {}).get("dev_type", "未知")
            self.view.add_device(service_name, display_name, dev_type, self.device_icon)

    def _on_device_removed(self, service_name: str):
        """处理设备移除 - 增量更新"""
        self.view.remove_device(service_name)

    def _on_device_list_changed(self):
        """处理设备列表变化 - 智能更新策略"""
        # 无论是否在批量模式，都使用智能增量更新
        self._update_view_incremental()

    def _update_view_incremental(self):
        """智能增量更新视图"""
        if self.device_icon:
            self.view.update_devices(self.model.get_all_devices(), self.device_icon)

    def _update_view(self):
        """完整更新视图 - 仅在必要时使用"""
        if self.device_icon:
            self.view.update_devices_full(
                self.model.get_all_devices(), self.device_icon
            )

    def _on_device_selected(self, service_name: str):
        """处理设备选择事件"""
        if self._on_device_selected_callback:
            device_data = self.model.get_device(service_name)
            self._on_device_selected_callback(service_name, device_data)

    def on_device_selected(self, callback: Callable[[str, Dict[str, Any]], None]):
        """设置设备选择回调"""
        self._on_device_selected_callback = callback
