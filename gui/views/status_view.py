"""
状态视图类，用于显示本机状态信息
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QGroupBox


class StatusView(QWidget):
    """状态视图，显示本机状态信息"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        
    def _setup_ui(self):
        """设置UI组件"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 状态框
        status_box = QGroupBox("本机状态")
        status_box.setObjectName("StatusGroupBox")
        status_layout = QHBoxLayout(status_box)
        
        self.device_name_label = QLabel("设备名: 正在检测...")
        self.device_type_label = QLabel("类型: 未知")
        self.ip_address_label = QLabel("IP地址: 未知")
        
        status_layout.addWidget(self.device_name_label)
        status_layout.addSpacing(20)
        status_layout.addWidget(self.device_type_label)
        status_layout.addStretch()
        status_layout.addWidget(self.ip_address_label)
        
        layout.addWidget(status_box)
        
    def set_device_name(self, name: str):
        """设置设备名称"""
        self.device_name_label.setText(f"<b>设备名:</b> {name}")
        
    def set_device_type(self, device_type: str):
        """设置设备类型"""
        self.device_type_label.setText(f"<b>类型:</b> {device_type}")
        
    def set_ip_address(self, ip: str, port: int):
        """设置IP地址和端口"""
        self.ip_address_label.setText(f"<b>IP地址:</b> {ip}:{port}") 