"""统一异常体系 — 1基类+9子类，全局异常处理器自动转 {code, data, message}。"""

from typing import Optional, Dict, Any
from fastapi import status


class AppError(Exception):
    """应用异常基类。子类只需传 message + code + http_status。"""

    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_ERROR",
        msg_code: str = "INTERNAL_ERROR",
        http_status: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.message = message
        self.code = code
        self.msg_code = msg_code
        self.http_status = http_status
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        """标准错误响应格式。msg_code 供前端 messages.js 查 i18n 翻译。"""
        return {"code": self.http_status, "data": None, "message": self.message, "msg_code": self.msg_code}


class ValidationError(AppError):
    """400 — 输入参数验证失败。"""
    def __init__(self, message: str = "输入验证失败", msg_code: str = "VALIDATION_ERROR",
                 details: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, code="VALIDATION_ERROR", msg_code=msg_code,
                         http_status=status.HTTP_400_BAD_REQUEST, details=details)


class ResourceNotFoundError(AppError):
    """404 — 资源不存在。"""
    def __init__(self, resource_type: str = "资源", resource_id: Optional[str] = None,
                 msg_code: str = "RESOURCE_NOT_FOUND",
                 details: Optional[Dict[str, Any]] = None):
        message = f"{resource_type}不存在"
        if resource_id:
            message = f"{resource_type}[{resource_id}]不存在"
        super().__init__(message=message, code="RESOURCE_NOT_FOUND", msg_code=msg_code,
                         http_status=status.HTTP_404_NOT_FOUND, details=details)


class ExternalServiceError(AppError):
    """502 — 外部服务调用失败。"""
    def __init__(self, service_name: str = "外部服务", msg_code: str = "EXTERNAL_SERVICE_ERROR",
                 details: Optional[Dict[str, Any]] = None):
        super().__init__(message=f"{service_name}调用失败", code="EXTERNAL_SERVICE_ERROR",
                         msg_code=msg_code,
                         http_status=status.HTTP_502_BAD_GATEWAY, details=details)


class InsufficientQuotaError(AppError):
    """403 — 使用次数不足。"""
    def __init__(self, resource_type: str = "次数", msg_code: str = "INSUFFICIENT_QUOTA",
                 details: Optional[Dict[str, Any]] = None):
        super().__init__(message=f"{resource_type}不足", code="INSUFFICIENT_QUOTA",
                         msg_code=msg_code,
                         http_status=status.HTTP_403_FORBIDDEN, details=details)
