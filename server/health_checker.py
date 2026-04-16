"""
健康检查 - 后台任务
"""
import asyncio
import logging
import time
from datetime import datetime
import httpx

from models import HealthStatus
from backends_manager import BackendsManager
from config import settings

logger = logging.getLogger(__name__)


class HealthChecker:
    """健康检查器"""
    
    def __init__(self, backends_manager: BackendsManager):
        self.backends_manager = backends_manager
        self.is_running = False
        self.last_check_time = {}
    
    def _get_auth_headers(self) -> dict:
        """获取认证请求头"""
        headers = {}
        if settings.backend_api_key:
            if settings.backend_auth_mode.lower() == "authorization":
                headers["Authorization"] = f"Bearer {settings.backend_api_key}"
            elif settings.backend_auth_mode.lower() == "x-api-key":
                headers["X-API-Key"] = settings.backend_api_key
        return headers
    
    async def check_backend_health(self, url: str, service: str, model: str, backend_id: str):
        """检查单个后端的健康状态"""
        try:
            start_time = time.time()
            headers = self._get_auth_headers()
            
            async with httpx.AsyncClient(timeout=settings.health_check_timeout) as client:
                response = await client.get(f"{url}/v1/models", headers=headers, follow_redirects=True)
            
            response_time = (time.time() - start_time) * 1000  # 转换为毫秒
            
            if response.status_code == 200:
                self.backends_manager.update_backend_status(
                    service=service,
                    model=model,
                    backend_id=backend_id,
                    status=HealthStatus.HEALTHY,
                    response_time_ms=response_time
                )
                logger.debug(f"✅ {service}/{model}/{backend_id} 健康检查通过 ({response_time:.1f}ms)")
            else:
                self.backends_manager.update_backend_status(
                    service=service,
                    model=model,
                    backend_id=backend_id,
                    status=HealthStatus.UNHEALTHY,
                    response_time_ms=response_time,
                    error_message=f"HTTP {response.status_code}"
                )
                logger.warning(f"⚠️ {service}/{model}/{backend_id} 返回HTTP {response.status_code}")
        
        except asyncio.TimeoutError:
            self.backends_manager.update_backend_status(
                service=service,
                model=model,
                backend_id=backend_id,
                status=HealthStatus.UNHEALTHY,
                error_message="连接超时"
            )
            logger.warning(f"⚠️ {service}/{model}/{backend_id} 健康检查超时")
        
        except Exception as e:
            self.backends_manager.update_backend_status(
                service=service,
                model=model,
                backend_id=backend_id,
                status=HealthStatus.UNHEALTHY,
                error_message=str(e)
            )
            logger.warning(f"⚠️ {service}/{model}/{backend_id} 健康检查失败: {e}")
    
    async def run_health_checks(self):
        """执行所有健康检查"""
        all_backends = self.backends_manager.get_all_backends()
        
        tasks = []
        for service, models in all_backends.items():
            for model, backends in models.items():
                for backend in backends:
                    task = self.check_backend_health(
                        url=backend.url,
                        service=service,
                        model=model,
                        backend_id=backend.id
                    )
                    tasks.append(task)
        
        if tasks:
            await asyncio.gather(*tasks)
            logger.info(f"✅ 健康检查完成 ({len(tasks)}个后端)")
    
    async def start(self):
        """启动定时健康检查"""
        self.is_running = True
        logger.info(f"🚀 启动健康检查 (间隔: {settings.health_check_interval}秒)")
        
        # 首次立即检查
        await self.run_health_checks()
        
        # 定时检查
        while self.is_running:
            await asyncio.sleep(settings.health_check_interval)
            await self.run_health_checks()
    
    def stop(self):
        """停止健康检查"""
        self.is_running = False
        logger.info("🛑 停止健康检查")
