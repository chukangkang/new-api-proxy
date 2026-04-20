"""
中央配置管理 - 环境变量验证，快速失败
"""
from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    # 应用设置
    port: int = 8000
    log_level: str = "INFO"
    
    # 后端配置
    backends_config_path: str = "./config/backends.json"
    
    # 健康检查
    health_check_interval: float = 30.0  # 秒
    
    # 超时配置
    request_timeout: float = 30.0
    health_check_timeout: float = 5.0
    
    # 配置热加载
    config_reload_watch: bool = True      # 是否启用 backends.json 文件监听热加载
    config_reload_interval: float = 2.0   # 文件 mtime 轮询间隔（秒）
    
    # 并发和连接池配置
    max_connections: int = 100  # httpx 连接池大小
    max_keepalive_connections: int = 20  # 保活连接数

    # 后端 API 密钥认证
    backend_api_key: str = ""  # 后端 API 密钥
    backend_auth_mode: str = "Authorization"  # 认证方式
    
    class Config:
        env_file = ".env"
        case_sensitive = False


# 初始化全局配置，启动时失败
settings = Settings()

# 验证配置文件存在
backends_path = Path(settings.backends_config_path)
if not backends_path.exists():
    raise FileNotFoundError(f"后端配置文件不存在: {settings.backends_config_path}")

# 验证 API 密钥已配置
if not settings.backend_api_key:
    raise ValueError("❌ 错误: BACKEND_API_KEY 环境变量未设置。请在 .env 文件中配置 BACKEND_API_KEY")

print(f"✅ 配置加载成功 - 后端配置文件: {backends_path.absolute()}")
print(f"✅ API 密钥已配置")
