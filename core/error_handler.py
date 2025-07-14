import traceback
from typing import Optional, Callable, Any
from fastapi import HTTPException


class ErrorHandler:
    """统一的错误处理器"""
    
    @staticmethod
    def handle_api_error(error: Exception, default_status: int = 500, 
                        custom_message: Optional[str] = None) -> HTTPException:
        """
        处理API错误，返回适当的HTTPException
        
        Args:
            error: 原始异常
            default_status: 默认HTTP状态码
            custom_message: 自定义错误消息
            
        Returns:
            HTTPException: 格式化的HTTP异常
        """
        if isinstance(error, HTTPException):
            return error
        elif isinstance(error, FileNotFoundError):
            return HTTPException(status_code=404, detail=custom_message or str(error))
        elif isinstance(error, PermissionError):
            return HTTPException(status_code=403, detail=custom_message or str(error))
        elif isinstance(error, ValueError):
            return HTTPException(status_code=400, detail=custom_message or str(error))
        else:
            return HTTPException(
                status_code=default_status, 
                detail=custom_message or f"Internal server error: {str(error)}"
            )
    
    @staticmethod
    def log_error(error: Exception, context: str = "", is_critical: bool = False):
        """
        记录错误日志
        
        Args:
            error: 异常对象
            context: 错误上下文
            is_critical: 是否为严重错误
        """
        error_type = type(error).__name__
        error_msg = str(error)
        
        prefix = "🔴 CRITICAL" if is_critical else "❌ ERROR"
        log_message = f"{prefix}: {context} - {error_type}: {error_msg}"
        
        print(log_message)
        
        if is_critical:
            print("Stack trace:")
            traceback.print_exc()
    
    @staticmethod
    def safe_execute(func: Callable, *args, error_handler: Optional[Callable] = None, 
                    default_return: Any = None, **kwargs) -> Any:
        """
        安全执行函数，捕获异常
        
        Args:
            func: 要执行的函数
            *args: 函数参数
            error_handler: 错误处理函数
            default_return: 发生错误时的默认返回值
            **kwargs: 函数关键字参数
            
        Returns:
            函数执行结果或默认返回值
        """
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if error_handler:
                error_handler(e)
            else:
                ErrorHandler.log_error(e, f"Error in {func.__name__}")
            return default_return
    
    @staticmethod
    def format_user_friendly_error(error: Exception) -> str:
        """
        将技术错误转换为用户友好的错误消息
        
        Args:
            error: 异常对象
            
        Returns:
            str: 用户友好的错误消息
        """
        error_type = type(error).__name__
        error_msg = str(error).lower()
        
        # 网络相关错误
        if "connection" in error_msg or "network" in error_msg:
            return "网络连接失败，请检查网络设置"
        elif "timeout" in error_msg:
            return "操作超时，请稍后重试"
        elif "refused" in error_msg:
            return "连接被拒绝，目标设备可能不可用"
        
        # 文件相关错误
        elif error_type == "FileNotFoundError":
            return "文件或文件夹不存在"
        elif error_type == "PermissionError":
            return "权限不足，无法访问该文件或文件夹"
        elif "disk" in error_msg or "space" in error_msg:
            return "磁盘空间不足"
        
        # 其他常见错误
        elif error_type == "ValueError":
            return "输入参数无效"
        elif "cancelled" in error_msg:
            return "操作已被用户取消"
        
        # 默认错误消息
        return f"操作失败: {str(error)}"


def handle_transfer_error(error: Exception, operation: str = "传输") -> str:
    """
    处理文件传输相关的错误
    
    Args:
        error: 异常对象
        operation: 操作类型（如"上传"、"下载"）
        
    Returns:
        str: 格式化的错误消息
    """
    friendly_msg = ErrorHandler.format_user_friendly_error(error)
    return f"{operation}失败: {friendly_msg}"


def log_server_error(error: Exception, client_info: str = ""):
    """
    记录服务器错误
    
    Args:
        error: 异常对象
        client_info: 客户端信息
    """
    context = f"Server error"
    if client_info:
        context += f" (client: {client_info})"
    
    ErrorHandler.log_error(error, context, is_critical=True)


def create_error_response(error: Exception, operation: str = "操作") -> dict:
    """
    创建标准的错误响应
    
    Args:
        error: 异常对象
        operation: 操作描述
        
    Returns:
        dict: 错误响应字典
    """
    return {
        "status": "error",
        "message": ErrorHandler.format_user_friendly_error(error),
        "operation": operation,
        "error_type": type(error).__name__
    }
