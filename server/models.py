"""
数据模型定义
"""
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, Literal
from enum import Enum
from datetime import datetime

from time_utils import now_shanghai


class HealthStatus(str, Enum):
    """健康状态"""
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class BackendNode(BaseModel):
    """后端节点定义"""
    id: str
    name: str
    url: str
    weight: int = 1
    api_key: Optional[str] = None  # 该后端的 API 密钥（可选，优先级高于全局密钥）
    auth_mode: Optional[str] = None  # 该后端的认证方式（可选：Authorization 或 x-api-key）


class BackendInfo(BaseModel):
    """后端节点信息（包含运行时状态）"""
    id: str
    name: str
    url: str
    weight: int
    api_key: Optional[str] = None  # 该后端的 API 密钥（不在响应中暴露）
    auth_mode: Optional[str] = None  # 该后端的认证方式（不在响应中暴露）
    status: HealthStatus = HealthStatus.UNKNOWN
    last_check: Optional[datetime] = None
    error_message: Optional[str] = None
    response_time_ms: float = 0.0


class BackendInfoPublic(BaseModel):
    """后端节点信息（公开版本，不包含 URL）"""
    id: str
    name: str
    weight: int
    status: HealthStatus = HealthStatus.UNKNOWN
    last_check: Optional[datetime] = None
    error_message: Optional[str] = None
    response_time_ms: float = 0.0


class ModelGroup(BaseModel):
    """模型分组"""
    backends: List[BackendNode]


class ServiceConfig(BaseModel):
    """服务配置"""
    models: Dict[str, ModelGroup]


class Config(BaseModel):
    """完整配置"""
    services: Dict[str, ServiceConfig]


class ErrorResponse(BaseModel):
    """错误响应"""
    error: str
    request_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=now_shanghai)


class HealthStatusResponse(BaseModel):
    """健康检查响应"""
    service: str
    type_name: Literal["health_status"]
    timestamp: datetime = Field(default_factory=now_shanghai)
    data: Dict[str, Dict[str, List[BackendInfo]]]
