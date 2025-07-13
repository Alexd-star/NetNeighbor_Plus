"""
设备列表Presenter类，连接设备模型和视图
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

        # 连接模型和视图
        self.model.on_device_list_changed(self._on_device_list_changed)
        self.view.device_selected.connect(self._on_device_selected)

        # 回调函数
        self._on_device_selected_callback = None

    def set_device_icon(self, icon: QIcon):
        """设置设备图标"""
        self.device_icon = icon
        self._update_view()

    def _on_device_list_changed(self):
        """处理设备列表变化"""
        self._update_view()

    def _update_view(self):
        """更新视图"""
        if self.device_icon:
            self.view.update_devices(self.model.get_all_devices(), self.device_icon)

    def _on_device_selected(self, service_name: str):
        """处理设备选择事件"""
        if self._on_device_selected_callback:
            device_data = self.model.get_device(service_name)
            self._on_device_selected_callback(service_name, device_data)

    def on_device_selected(self, callback: Callable[[str, Dict[str, Any]], None]):
        """设置设备选择回调"""
        self._on_device_selected_callback = callback
