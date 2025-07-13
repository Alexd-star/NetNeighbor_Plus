"""
状态Presenter类，连接应用控制器和状态视图
"""
from gui.app_controller import AppController
from gui.views.status_view import StatusView
from gui.models.connection_model import ConnectionModel


class StatusPresenter:
    """状态Presenter，连接应用控制器和状态视图"""
    
    def __init__(self, controller: AppController, connection_model: ConnectionModel, view: StatusView):
        self.controller = controller
        self.connection_model = connection_model
        self.view = view
        
        # 初始化状态显示
        self._update_status()
        
        # 连接控制器信号
        self.controller.device_info_updated.connect(self._update_status)
        
    def _update_status(self):
        """更新状态显示"""
        device_name = self.controller.device_name
        self.view.set_device_name(device_name)
        
        device_type = self.controller.device_properties.get('dev_type', '未知')
        self.view.set_device_type(device_type)
        
        ip = self.connection_model.get_my_ip()
        port = self.controller.port
        self.view.set_ip_address(ip, port) 