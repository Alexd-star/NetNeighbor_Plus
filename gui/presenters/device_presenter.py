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
        self.model.on_device_added(self._on_device_added)
        self.model.on_device_removed(self._on_device_removed)
        self.model.on_device_list_changed(self._on_device_list_changed)
        self.view.device_selected.connect(self._on_device_selected)
        self._on_device_selected_callback = None

    def set_device_icon(self, icon: QIcon):
        self.device_icon = icon
        self._update_view_incremental()

    def _on_device_added(self, service_name: str, device_data: dict):
        if self.device_icon:
            display_name = service_name.split("._netneighbor._tcp.local.")[0]
            dev_type = device_data.get("properties", {}).get("dev_type", "未知")
            self.view.add_device(service_name, display_name, dev_type, self.device_icon)

    def _on_device_removed(self, service_name: str):
        self.view.remove_device(service_name)

    def _on_device_list_changed(self):
        self._update_view_incremental()

    def _update_view_incremental(self):
        if self.device_icon:
            self.view.update_devices(self.model.get_all_devices(), self.device_icon)

    def _update_view(self):
        if self.device_icon:
            self.view.update_devices_full(
                self.model.get_all_devices(), self.device_icon
            )

    def _on_device_selected(self, service_name: str):
        if self._on_device_selected_callback:
            device_data = self.model.get_device(service_name)
            self._on_device_selected_callback(service_name, device_data)

    def on_device_selected(self, callback: Callable[[str, Dict[str, Any]], None]):
        self._on_device_selected_callback = callback
