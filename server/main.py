"""
API调度网关 - 主应用
"""
import logging
import asyncio
import uuid
import json
import time
from contextlib import asynccontextmanager
from typing import Optional, Callable, Any, Dict, AsyncGenerator

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import Response

import httpx

from config import settings
from backends_manager import BackendsManager
from health_checker import HealthChecker
from models import HealthStatus, HealthStatusResponse, ErrorResponse, BackendInfo, BackendInfoPublic
from time_utils import setup_shanghai_logging

# ==================== 日志配置 ====================
# 必须在 basicConfig 之前调用，确保所有 Formatter 使用上海时间
setup_shanghai_logging()
logging.basicConfig(
    level=settings.log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== 全局单例 ====================
backends_manager: Optional[BackendsManager] = None
health_checker: Optional[HealthChecker] = None
httpx_client: Optional[httpx.AsyncClient] = None  # 全局 httpx 客户端
config_watcher_task: Optional[asyncio.Task] = None  # 配置文件监听任务


# ==================== 配置文件监听 ====================
async def watch_config_file():
    """
    后台任务：轮询 backends.json 的 mtime，检测到变化时触发热重载。
    - 仅检测 mtime，不读取文件内容，开销极小
    - reload 使用增量合并，不影响其他正常节点和在途请求
    - JSON 语法错误/IO 错误时保持旧配置继续运行
    """
    from pathlib import Path
    config_path = Path(settings.backends_config_path)
    logger.info(
        f"👁️  启动配置文件监听: {config_path} "
        f"(间隔 {settings.config_reload_interval}s)"
    )
    
    while True:
        try:
            await asyncio.sleep(settings.config_reload_interval)
            if backends_manager is None:
                continue
            try:
                current_mtime = config_path.stat().st_mtime
            except OSError as e:
                logger.warning(f"⚠️  读取配置文件 mtime 失败: {e}")
                continue
            
            # mtime 变化 → 触发热重载
            if current_mtime > backends_manager.last_mtime:
                logger.info(f"📝 检测到配置文件变更 (mtime {backends_manager.last_mtime} → {current_mtime})，开始热重载...")
                try:
                    await backends_manager.reload_config()
                except Exception as e:
                    logger.error(f"❌ 自动热重载失败（保持旧配置）: {e}")
        except asyncio.CancelledError:
            logger.info("👁️  配置文件监听已停止")
            break
        except Exception as e:
            logger.error(f"配置文件监听异常: {e}", exc_info=True)




async def stream_sse_events(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    body: bytes,
    headers: Dict,
    request_id: str,
) -> AsyncGenerator[str, None]:
    """
    标准 SSE 格式转发：原样转发 data: 前缀，保证前端能实时渲染
    """
    try:
        async with client.stream(
            method=method,
            url=url,
            content=body,
            headers=headers,
            follow_redirects=True
        ) as response:
            
            buffer = ""
            async for chunk in response.aiter_text(chunk_size=512):
                buffer += chunk

                # 按 SSE 标准事件分割 \n\n
                while "\n\n" in buffer:
                    event, buffer = buffer.split("\n\n", 1)
                    if event.strip():
                        # ✅ 关键：直接原样转发，不破坏格式
                        yield event.strip() + "\n\n"

            # 最后剩余内容
            if buffer.strip():
                yield buffer.strip() + "\n\n"

    except Exception as e:
        logger.error(f"[{request_id}] SSE 错误: {e}")
        yield f'data: {{"error": "{str(e)}"}}\n\n'


# ==================== 创建全局 httpx 客户端 ====================
async def get_httpx_client() -> httpx.AsyncClient:
    """获取全局 httpx AsyncClient（连接池复用，线程安全）"""
    global httpx_client
    if httpx_client is None:
        httpx_client = httpx.AsyncClient(
            timeout=httpx.Timeout(300, connect=10),
            limits=httpx.Limits(
                max_connections=settings.max_connections,
                max_keepalive_connections=settings.max_keepalive_connections,
            ),
            follow_redirects=True,
        )
    return httpx_client


# ==================== 生命周期 ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动/关闭生命周期"""
    global backends_manager, health_checker, httpx_client, config_watcher_task
    
    # 启动
    logger.info("🚀 应用启动中...")
    backends_manager = BackendsManager(settings.backends_config_path)
    health_checker = HealthChecker(backends_manager)
    
    # 初始化 httpx 连接池
    httpx_client = await get_httpx_client()
    logger.info(f"✅ httpx 连接池已初始化 (max_connections={settings.max_connections})")
    
    # 在后台启动健康检查
    health_check_task = asyncio.create_task(health_checker.start())
    
    # 在后台启动配置文件监听（热加载）
    if settings.config_reload_watch:
        config_watcher_task = asyncio.create_task(watch_config_file())
    else:
        logger.info("👁️  配置文件监听已禁用 (CONFIG_RELOAD_WATCH=false)")
    
    logger.info("✅ 应用启动完成")
    
    yield  # 应用运行
    
    # 关闭
    logger.info("🛑 应用关闭中...")
    if health_checker:
        health_checker.stop()
    
    # 取消配置监听任务
    if config_watcher_task and not config_watcher_task.done():
        config_watcher_task.cancel()
        try:
            await config_watcher_task
        except asyncio.CancelledError:
            pass
    
    # 关闭 httpx 连接池
    if httpx_client:
        await httpx_client.aclose()
        logger.info("✅ httpx 连接池已关闭")
    
    await asyncio.sleep(0.5)  # 等待任务清理
    logger.info("✅ 应用关闭完成")


# ==================== FastAPI 应用 ====================
app = FastAPI(
    title="API 调度网关",
    description="支持负载均衡和健康检查的API代理",
    version="1.0.0",
    lifespan=lifespan
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== 中间件 ====================
@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """添加请求ID用于链路追踪"""
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.middleware("http")
async def verify_api_key_middleware(request: Request, call_next):
    """
    验证API密钥中间件
    公开端点：/health, /ready, / (仪表板), /static/* (静态文件)
    受保护端点：/api/health/status, /api/health/status/{service}, /{service}/{model}
    """
    request_path = request.url.path
    
    # 公开端点 - 不需要认证
    public_paths = {"/health", "/ready", "/", "/api/health/status"}
    
    # 检查是否是公开端点或静态文件
    if request_path in public_paths or request_path.startswith("/static"):
        return await call_next(request)
    
    # 所有其他请求都需要验证密钥
    auth_header = request.headers.get("Authorization")
    api_key_header = request.headers.get("X-API-Key")
    
    # 检查 Authorization header (Bearer token)
    if auth_header:
        parts = auth_header.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            if parts[1] == settings.backend_api_key:
                return await call_next(request)
    
    # 检查 X-API-Key header
    if api_key_header and api_key_header == settings.backend_api_key:
        return await call_next(request)
    
    # 密钥验证失败
    return JSONResponse(
        status_code=401,
        content={"error": "无效或缺失的API密钥"}
    )


# ==================== 健康检查端点 ====================
@app.get("/health")
async def health():
    """应用健康检查"""
    return {
        "status": "ok",
        "service": "api-proxy-gateway",
        "version": "1.0.0"
    }


@app.get("/ready")
async def readiness():
    """就绪检查"""
    if backends_manager is None:
        raise HTTPException(status_code=503, detail="应用未完全初始化")
    return {"status": "ready"}


# ==================== API 健康状态端点（必须在通用路由之前） ====================
@app.get("/api/health/status")
async def get_all_health():
    """获取所有服务的健康状态 (不包含后端 URL)"""
    all_backends = backends_manager.get_all_backends()
    
    # 转换为公开版本（移除 URL）
    public_data = {}
    for service, models in all_backends.items():
        public_data[service] = {}
        for model, backends in models.items():
            public_data[service][model] = [
                BackendInfoPublic(
                    id=b.id,
                    name=b.name,
                    weight=b.weight,
                    status=b.status,
                    last_check=b.last_check,
                    error_message=b.error_message,
                    response_time_ms=b.response_time_ms
                )
                for b in backends
            ]
    
    return {
        "service": "api-proxy-gateway",
        "type": "health_status",
        "data": public_data
    }


@app.get("/api/health/status/{service}")
async def get_service_health(service: str):
    """
    获取某个服务的健康状态 (不包含后端 URL)
    
    示例: GET /api/health/status/google
    """
    service_backends = backends_manager.get_service_backends(service)
    
    if service_backends is None:
        raise HTTPException(status_code=404, detail=f"服务不存在: {service}")
    
    # 转换为公开版本（移除 URL）
    public_backends = {}
    for model, backends in service_backends.items():
        public_backends[model] = [
            BackendInfoPublic(
                id=b.id,
                name=b.name,
                weight=b.weight,
                status=b.status,
                last_check=b.last_check,
                error_message=b.error_message,
                response_time_ms=b.response_time_ms
            )
            for b in backends
        ]
    
    return {
        "service": service,
        "data": public_backends
    }


# ==================== 配置热重载端点 ====================
@app.post("/api/config/reload")
async def reload_config_endpoint():
    """
    手动触发 backends.json 热重载（增量合并）。
    - 保留同 id 后端的健康状态、响应时间，不影响其他正常节点
    - 在途请求已持有后端引用，继续正常完成
    - JSON 非法时返回 400 并保持旧配置
    - 受 API 密钥中间件保护（需 Authorization/X-API-Key 头）
    """
    if backends_manager is None:
        raise HTTPException(status_code=503, detail="应用未完全初始化")
    try:
        diff = await backends_manager.reload_config()
        return {
            "status": "ok",
            "message": "配置已热重载",
            "diff": diff,
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"配置文件不存在: {e}")
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"配置文件 JSON 格式错误: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"热重载失败: {e}")


@app.get("/api/config/status")
async def config_status_endpoint():
    """查询当前配置文件监听状态与已加载 mtime"""
    if backends_manager is None:
        raise HTTPException(status_code=503, detail="应用未完全初始化")
    return {
        "watch_enabled": settings.config_reload_watch,
        "watch_interval_seconds": settings.config_reload_interval,
        "config_path": str(backends_manager.config_path),
        "loaded_mtime": backends_manager.last_mtime,
    }


# ==================== 现代化的API端点 ====================
# ✅ 关键修复：使用 router.add_api_route 手动添加路由以控制顺序
# 更具体的路由（带 path）必须先添加，否则 /{service}/{model} 会先匹配

async def forward_request_with_path(
    service: str,
    model: str,
    path: str,
    request: Request,
    background_tasks: BackgroundTasks,
):
    """转发请求到后端（带额外路径）"""
    return await forward_request(service, model, request, background_tasks, path)

async def forward_request_no_path(
    service: str,
    model: str,
    request: Request,
    background_tasks: BackgroundTasks,
):
    """转发请求到后端（无额外路径）"""
    return await forward_request(service, model, request, background_tasks, "")

# 先添加带 path 的路由（更具体）
app.router.add_api_route(
    "/{service}/{model}/{path:path}",
    forward_request_with_path,
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]
)

# 后添加不带 path 的路由（更通用）
app.router.add_api_route(
    "/{service}/{model}",
    forward_request_no_path,
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]
)

async def forward_request(
    service: str,
    model: str,
    request: Request,
    background_tasks: BackgroundTasks,
    path: str = ""
) -> Response:
    request_id = request.state.request_id
    client_ip = request.client.host if request.client else "unknown"
    
    try:
        logger.info(f"[{request_id}] 接收请求: {service}/{model}")

        # 选择后端
        selected_backend = backends_manager.select_backend(service, model, client_ip)
        if not selected_backend:
            return JSONResponse(status_code=404, content={"error": f"无可用后端: {service}/{model}"})

        # 读取请求体
        body = await request.body()
        headers = dict(request.headers)

        # 清理无效头
        hop_by_hop = {
            "host", "connection", "keep-alive", "transfer-encoding",
            "accept-encoding", "content-length"
        }
        headers = {k: v for k, v in headers.items() if k.lower() not in hop_by_hop}
        headers["Accept-Encoding"] = "identity"

        # 后端认证
        backend_key = selected_backend.api_key or settings.backend_api_key
        auth_mode = selected_backend.auth_mode or settings.backend_auth_mode
        if backend_key:
            if auth_mode and auth_mode.lower() == "authorization":
                headers["Authorization"] = f"Bearer {backend_key}"
            elif auth_mode and auth_mode.lower() == "x-api-key":
                headers["X-API-Key"] = backend_key

        # 路径拼接
        base = f"/{service}/{model}"
        fpath = request.url.path[len(base):]
        target = selected_backend.url.rstrip("/") + fpath

        client = await get_httpx_client()

        # ✅ 关键修复：把 stream 整个交给生成器，不提前退出上下文
        async def streaming_proxy():
            try:
                async with client.stream(
                    method=request.method,
                    url=target,
                    content=body,
                    headers=headers,
                    follow_redirects=True
                ) as resp:
                    async for chunk in resp.aiter_bytes(chunk_size=512):
                        yield chunk
            except Exception as e:
                logger.error(f"[{request_id}] 流异常: {str(e)}")
                yield f'data: {{"error": "stream closed"}}\n\n'.encode('utf-8')

        # 先发起一次请求，获取 header 和状态
        async with client.stream(
            method=request.method,
            url=target,
            content=body,
            headers=headers,
            follow_redirects=True
        ) as probe_resp:
            content_type = probe_resp.headers.get("content-type", "")
            status = probe_resp.status_code
            is_stream = "text/event-stream" in content_type or "application/x-ndjson" in content_type

            if is_stream:
                # 流式响应
                sh = {}
                for k, v in probe_resp.headers.items():
                    if k.lower() not in ["content-length", "content-encoding", "connection"]:
                        sh[k] = v
                sh["Cache-Control"] = "no-cache"
                sh["X-Accel-Buffering"] = "no"
                sh["Connection"] = "keep-alive"

                return StreamingResponse(
                    streaming_proxy(),
                    media_type=content_type,
                    status_code=status,
                    headers=sh
                )
            else:
                # 普通响应
                data = await probe_resp.aread()
                return Response(
                    content=data,
                    status_code=status,
                    media_type=content_type,
                    headers=dict(probe_resp.headers)
                )

    except httpx.TimeoutException:
        return JSONResponse(status_code=504, content={"error": "后端超时"})
    except httpx.RequestError as e:
        logger.error(f"[{request_id}] 请求失败: {e}")
        return JSONResponse(status_code=502, content={"error": "无法连接后端"})
    except Exception as e:
        logger.error(f"[{request_id}] 错误: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": f"内部错误: {str(e)}"})
# ==================== 前端页面 ====================
@app.get("/")
async def dashboard():
    """返回管理仪表板"""
    return FileResponse("./static/index.html")


# 安全挂载静态文件
import os
if os.path.exists("./static"):
    app.mount("/static", StaticFiles(directory="./static"), name="static")
else:
    logger.warning("静态文件夹不存在，跳过挂载")


# ==================== 错误处理 ====================
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "request_id": request.state.request_id
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"未处理的异常: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "内部服务器错误",
            "request_id": request.state.request_id
        }
    )


if __name__ == "__main__":
    import uvicorn
    logger.info(f"启动服务器: 0.0.0.0:{settings.port}")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=settings.port,
        log_level=settings.log_level.lower()
    )
