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
    
    async def _probe_models(self, url: str) -> tuple:
        """探测 GET /v1/models。返回 (ok, response_time_ms, error_message)。"""
        start_time = time.time()
        try:
            headers = self._get_auth_headers()
            async with httpx.AsyncClient(timeout=settings.health_check_timeout) as client:
                response = await client.get(
                    f"{url}/v1/models", headers=headers, follow_redirects=True
                )
            elapsed = (time.time() - start_time) * 1000
            if response.status_code == 200:
                return (True, elapsed, None)
            return (False, elapsed, f"HTTP {response.status_code}")
        except asyncio.TimeoutError:
            return (False, (time.time() - start_time) * 1000, "连接超时")
        except Exception as e:
            return (False, (time.time() - start_time) * 1000, str(e))
    
    async def _probe_chat_completions(self, url: str, model: str) -> tuple:
        """探测 POST /v1/chat/completions（最小 tokens）。返回 (ok, response_time_ms, error_message)。"""
        start_time = time.time()
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1,
            "stream": False,
        }
        try:
            headers = {**self._get_auth_headers(), "Content-Type": "application/json"}
            async with httpx.AsyncClient(timeout=settings.health_check_timeout) as client:
                response = await client.post(
                    f"{url}/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    follow_redirects=True,
                )
            elapsed = (time.time() - start_time) * 1000
            if response.status_code == 200:
                return (True, elapsed, None)
            return (False, elapsed, f"HTTP {response.status_code}")
        except asyncio.TimeoutError:
            return (False, (time.time() - start_time) * 1000, "连接超时")
        except Exception as e:
            return (False, (time.time() - start_time) * 1000, str(e))
    
    async def check_backend_health(self, url: str, service: str, model: str, backend_id: str):
        """
        检查单个后端健康：优先 GET /v1/models，失败则回退到 POST /v1/chat/completions
        （最小 tokens 提问）。任一成功即判定 HEALTHY。
        """
        # 1) 优先 /v1/models
        ok, response_time, err_models = await self._probe_models(url)
        probe_used = "/v1/models"
        
        # 2) 失败则回退 /v1/chat/completions（最小 tokens）
        if not ok:
            logger.debug(
                f"{service}/{model}/{backend_id} /v1/models 失败 ({err_models})，回退 /v1/chat/completions"
            )
            ok2, rt2, err_chat = await self._probe_chat_completions(url, model)
            if ok2:
                ok = True
                response_time = rt2
                probe_used = "/v1/chat/completions"
                err_models = None
            else:
                # 两个接口都失败，合并错误消息便于排查
                response_time = rt2
                err_models = f"/v1/models: {err_models}; /v1/chat/completions: {err_chat}"
        
        # 3) 更新状态
        if ok:
            self.backends_manager.update_backend_status(
                service=service,
                model=model,
                backend_id=backend_id,
                status=HealthStatus.HEALTHY,
                response_time_ms=response_time,
            )
            logger.debug(
                f"✅ {service}/{model}/{backend_id} 健康 via {probe_used} ({response_time:.1f}ms)"
            )
        else:
            self.backends_manager.update_backend_status(
                service=service,
                model=model,
                backend_id=backend_id,
                status=HealthStatus.UNHEALTHY,
                response_time_ms=response_time,
                error_message=err_models,
            )
            logger.warning(f"⚠️ {service}/{model}/{backend_id} 健康检查失败: {err_models}")
    
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
