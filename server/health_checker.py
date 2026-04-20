"""
健康检查 - 后台任务
"""
import asyncio
import logging
import time
from datetime import datetime
from typing import Optional
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
    
    def _get_auth_headers(
        self,
        api_key: Optional[str] = None,
        auth_mode: Optional[str] = None,
    ) -> dict:
        """获取认证请求头

        per-backend 的 api_key/auth_mode 优先，全局 settings 作为兜底，
        行为与 main.py 转发路径保持一致，避免 health check 与实际请求鉴权不一致。
        """
        headers = {}
        key = api_key or settings.backend_api_key
        mode = auth_mode or settings.backend_auth_mode
        if key:
            if mode and mode.lower() == "authorization":
                headers["Authorization"] = f"Bearer {key}"
            elif mode and mode.lower() == "x-api-key":
                headers["X-API-Key"] = key
        return headers
    
    async def _probe_options(
        self,
        url: str,
        api_key: Optional[str] = None,
        auth_mode: Optional[str] = None,
    ) -> tuple:
        """探测 OPTIONS /v1/chat/completions。

        仅验证连通性、鉴权和服务在线，不触发推理、不消耗 Token。
        判定规则：
        - HTTP 状态码 < 500（如 200/204/401/403/405）→ 后端正常（服务可达）
        - 5xx / 超时 / 连接错误 → 后端异常

        返回 (ok, response_time_ms, error_message)。
        """
        start_time = time.time()
        try:
            headers = self._get_auth_headers(api_key, auth_mode)
            async with httpx.AsyncClient(timeout=settings.health_check_timeout) as client:
                response = await client.request(
                    "OPTIONS",
                    f"{url}/v1/chat/completions",
                    headers=headers,
                    follow_redirects=True,
                )
            elapsed = (time.time() - start_time) * 1000
            if response.status_code < 500:
                return (True, elapsed, None)
            return (False, elapsed, f"HTTP {response.status_code}")
        except asyncio.TimeoutError:
            return (False, (time.time() - start_time) * 1000, "连接超时")
        except httpx.TimeoutException:
            return (False, (time.time() - start_time) * 1000, "连接超时")
        except Exception as e:
            return (False, (time.time() - start_time) * 1000, str(e))
    
    async def check_backend_health(
        self,
        url: str,
        service: str,
        model: str,
        backend_id: str,
        api_key: Optional[str] = None,
        auth_mode: Optional[str] = None,
    ):
        """
        检查单个后端健康：发送 OPTIONS /v1/chat/completions，不消耗 Token。

        - HTTP 状态码 < 500（包含 200/204/401/403/405 等）→ HEALTHY
        - 5xx / 超时 / 连接错误 → UNHEALTHY

        api_key/auth_mode 为 per-backend 配置，优先使用，全局 settings 作为兜底，
        语义与 main.py 转发路径完全一致。
        """
        ok, response_time, err = await self._probe_options(url, api_key, auth_mode)
        
        if ok:
            self.backends_manager.update_backend_status(
                service=service,
                model=model,
                backend_id=backend_id,
                status=HealthStatus.HEALTHY,
                response_time_ms=response_time,
            )
            logger.debug(
                f"✅ {service}/{model}/{backend_id} 健康 via OPTIONS ({response_time:.1f}ms)"
            )
        else:
            self.backends_manager.update_backend_status(
                service=service,
                model=model,
                backend_id=backend_id,
                status=HealthStatus.UNHEALTHY,
                response_time_ms=response_time,
                error_message=err,
            )
            logger.warning(f"⚠️ {service}/{model}/{backend_id} 健康检查失败: {err}")
    
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
                        backend_id=backend.id,
                        api_key=backend.api_key,
                        auth_mode=backend.auth_mode,
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
