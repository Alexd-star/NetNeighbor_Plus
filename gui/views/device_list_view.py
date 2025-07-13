"""
设备列表视图类，用于显示在线设备
"""
from typing import Dict, Any, Optional, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QWidget, QVBoxLayout, QLabel
from PySide6.QtGui import QIcon


class DeviceListView(QWidget):
    """设备列表视图，显示在线设备"""
    
    device_selected = Signal(str)  # 发射设备服务名称
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        
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
        
    def add_device(self, service_name: str, display_name: str, device_type: str, icon: Optional[QIcon] = None):
        """添加设备到列表"""
        item = QListWidgetItem(f"{display_name}\n类型: {device_type}")
        if icon:
            item.setIcon(icon)
        item.setData(Qt.ItemDataRole.UserRole, service_name)
        
        # 查找插入位置（按显示名称排序）
        for i in range(self.device_list_widget.count()):
            existing_item = self.device_list_widget.item(i)
            existing_display_name = existing_item.text().split('\n')[0]
            if display_name.lower() < existing_display_name.lower():
                self.device_list_widget.insertItem(i, item)
                return
                
        # 如果没有找到合适的位置，添加到末尾
        self.device_list_widget.addItem(item)
        
    def remove_device(self, service_name: str):
        """从列表中移除设备"""
        for i in range(self.device_list_widget.count()):
            item = self.device_list_widget.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == service_name:
                self.device_list_widget.takeItem(i)
                break
                
    def update_devices(self, devices: Dict[str, Dict[str, Any]], device_icon: QIcon):
        """更新整个设备列表"""
        self.device_list_widget.clear()
        
        for service_name, device_data in devices.items():
            display_name = service_name.split('._netneighbor._tcp.local.')[0]
            dev_type = device_data.get("properties", {}).get("dev_type", "未知")
            self.add_device(service_name, display_name, dev_type, device_icon)
            
    def get_device_count(self) -> int:
        """获取设备数量"""
        return self.device_list_widget.count() 