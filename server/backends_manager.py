"""
后端管理 - 负载均衡、IP映射、健康状态
"""
import json
import asyncio
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set
from datetime import datetime
import hashlib
import logging

from models import BackendNode, BackendInfo, HealthStatus, Config
from time_utils import now_shanghai

logger = logging.getLogger(__name__)


class LoadBalancer:
    """负载均衡器"""
    
    def __init__(self):
        self.round_robin_counters: Dict[str, int] = {}
        self.ip_backend_mapping: Dict[str, str] = {}  # IP -> backend_id
    
    def select_backend(
        self, 
        backends: List[BackendInfo], 
        client_ip: str
    ) -> Optional[BackendInfo]:
        """
        使用轮询 + IP哈希策略选择后端
        同一IP会一直映射到同一后端
        """
        if not backends:
            return None
        
        # 过滤健康的后端
        healthy = [b for b in backends if b.status == HealthStatus.HEALTHY]
        candidates = healthy if healthy else backends
        
        # 检查IP映射缓存
        mapping_key = f"{id(backends)}"
        if client_ip in self.ip_backend_mapping:
            backend_id = self.ip_backend_mapping[client_ip]
            # 验证该后端还在候选列表中
            for backend in candidates:
                if backend.id == backend_id:
                    logger.info(f"IP {client_ip} 使用缓存映射 -> {backend_id}")
                    return backend
        
        # 轮询选择
        counter_key = mapping_key
        if counter_key not in self.round_robin_counters:
            self.round_robin_counters[counter_key] = 0
        
        idx = self.round_robin_counters[counter_key] % len(candidates)
        selected = candidates[idx]
        self.round_robin_counters[counter_key] = (idx + 1) % len(candidates)
        
        # 记录IP映射
        self.ip_backend_mapping[client_ip] = selected.id
        logger.info(f"IP {client_ip} 新映射 -> {selected.id}")
        
        return selected


class BackendsManager:
    """后端管理器"""
    
    def __init__(self, config_path: str):
        self.config_path = Path(config_path)
        # {service: {model: [BackendInfo, ...]}}
        self.backends_status: Dict[str, Dict[str, List[BackendInfo]]] = {}
        self.load_balancer = LoadBalancer()
        # 热加载并发安全锁：保证 reload 和读取互斥
        self._reload_lock = asyncio.Lock()
        # 记录最后加载的配置文件 mtime，用于文件监听判断
        self.last_mtime: float = 0.0
        self._load_config()
    
    def _read_config_file(self) -> Config:
        """读取并解析配置文件（不修改状态）"""
        with open(self.config_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return Config(**data)
    
    def _update_mtime(self) -> None:
        """更新已加载配置的 mtime。"""
        try:
            self.last_mtime = self.config_path.stat().st_mtime
        except OSError:
            self.last_mtime = 0.0
    
    def _load_config(self):
        """首次加载并解析配置文件"""
        try:
            config = self._read_config_file()
            
            # 初始化后端状态
            for service_name, service_config in config.services.items():
                if service_name not in self.backends_status:
                    self.backends_status[service_name] = {}
                
                for model_name, model_group in service_config.models.items():
                    backend_infos = [
                        BackendInfo(
                            id=b.id,
                            name=b.name,
                            url=b.url,
                            weight=b.weight,
                            api_key=b.api_key,
                            auth_mode=b.auth_mode,
                            status=HealthStatus.UNKNOWN
                        )
                        for b in model_group.backends
                    ]
                    self.backends_status[service_name][model_name] = backend_infos
                    logger.info(f"加载后端配置: {service_name}/{model_name} -> {len(backend_infos)}个节点")
            
            self._update_mtime()
            logger.info("✅ 后端配置加载成功")
        except FileNotFoundError as e:
            logger.error(f"❌ 配置文件不存在: {self.config_path}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"❌ 配置文件JSON格式错误: {e}")
            raise
        except Exception as e:
            logger.error(f"❌ 加载配置文件失败: {e}")
            raise
    
    async def reload_config(self) -> Dict[str, any]:
        """
        热重载配置文件（增量合并）
        - 同 id 的后端：保留健康状态、响应时间、最后检查时间，仅更新可变字段(url/weight/api_key/auth_mode/name)
        - 新增后端：状态置为 UNKNOWN，等待下一轮健康检查
        - 移除后端：从状态表中删除，并清理对应的 IP 映射
        - 新增 service/model：添加
        - 移除 service/model：删除并清理相关轮询计数器
        - 失败时回滚，不改变当前状态
        
        返回 diff 信息：{added, removed, updated, service_added, service_removed}
        """
        async with self._reload_lock:
            try:
                new_config = self._read_config_file()
            except FileNotFoundError:
                logger.error(f"❌ 重载失败: 配置文件不存在 {self.config_path}")
                raise
            except json.JSONDecodeError as e:
                logger.error(f"❌ 重载失败: JSON 格式错误 {e}，保持旧配置")
                raise
            except Exception as e:
                logger.error(f"❌ 重载失败: {e}，保持旧配置")
                raise
            
            diff = {
                "added": [],       # ["service/model/backend_id"]
                "removed": [],     # ["service/model/backend_id"]
                "updated": [],     # ["service/model/backend_id"]
                "service_added": [],
                "service_removed": [],
                "model_added": [],
                "model_removed": [],
            }
            
            # 收集新配置中的所有 service/model/backend
            new_services: Set[str] = set(new_config.services.keys())
            old_services: Set[str] = set(self.backends_status.keys())
            
            # 1) 处理被移除的 service
            for svc in old_services - new_services:
                for model, backends in self.backends_status[svc].items():
                    for b in backends:
                        diff["removed"].append(f"{svc}/{model}/{b.id}")
                        self._cleanup_ip_mapping_for_backend(b.id)
                    self._cleanup_counter(svc, model)
                diff["service_removed"].append(svc)
                del self.backends_status[svc]
            
            # 2) 处理新增的 service
            for svc in new_services - old_services:
                self.backends_status[svc] = {}
                diff["service_added"].append(svc)
            
            # 3) 逐 service 处理 model
            for svc_name in new_services:
                new_svc_cfg = new_config.services[svc_name]
                new_models: Set[str] = set(new_svc_cfg.models.keys())
                old_models: Set[str] = set(self.backends_status.get(svc_name, {}).keys())
                
                # 移除的 model
                for model in old_models - new_models:
                    for b in self.backends_status[svc_name][model]:
                        diff["removed"].append(f"{svc_name}/{model}/{b.id}")
                        self._cleanup_ip_mapping_for_backend(b.id)
                    self._cleanup_counter(svc_name, model)
                    diff["model_removed"].append(f"{svc_name}/{model}")
                    del self.backends_status[svc_name][model]
                
                # 新增和更新的 model
                for model in new_models:
                    new_backends = new_svc_cfg.models[model].backends
                    old_list = self.backends_status[svc_name].get(model, [])
                    old_map = {b.id: b for b in old_list}
                    new_ids = {b.id for b in new_backends}
                    
                    if model not in old_models:
                        diff["model_added"].append(f"{svc_name}/{model}")
                    
                    # 构造新列表：保留已有节点状态，仅更新可变字段
                    merged: List[BackendInfo] = []
                    for nb in new_backends:
                        if nb.id in old_map:
                            existing = old_map[nb.id]
                            # 先缓存变更标志（在更新字段前）
                            url_changed = existing.url != nb.url
                            changed = (
                                url_changed
                                or existing.weight != nb.weight
                                or existing.name != nb.name
                                or existing.api_key != nb.api_key
                                or existing.auth_mode != nb.auth_mode
                            )
                            # 就地更新可变字段，保留状态
                            existing.url = nb.url
                            existing.weight = nb.weight
                            existing.name = nb.name
                            existing.api_key = nb.api_key
                            existing.auth_mode = nb.auth_mode
                            # url 改变时健康状态需重新评估
                            if url_changed:
                                existing.status = HealthStatus.UNKNOWN
                                existing.error_message = None
                                existing.response_time_ms = 0.0
                            merged.append(existing)
                            if changed:
                                diff["updated"].append(f"{svc_name}/{model}/{nb.id}")
                        else:
                            merged.append(BackendInfo(
                                id=nb.id,
                                name=nb.name,
                                url=nb.url,
                                weight=nb.weight,
                                api_key=nb.api_key,
                                auth_mode=nb.auth_mode,
                                status=HealthStatus.UNKNOWN,
                            ))
                            diff["added"].append(f"{svc_name}/{model}/{nb.id}")
                    
                    # 移除的节点
                    for old_id in set(old_map.keys()) - new_ids:
                        diff["removed"].append(f"{svc_name}/{model}/{old_id}")
                        self._cleanup_ip_mapping_for_backend(old_id)
                    
                    # 替换列表引用。已有在途请求持有的是 BackendInfo实例引用，不受影响。
                    self.backends_status[svc_name][model] = merged
                    # 因为列表身份变了，轮询计数器需重置（唯一键以 id(list) 形式存在）
                    # 直接重置为 0，让下次 select 重新分配
                    # 旧 key 因 id() 不同会自然失效，但我们主动清理避免内存泄漏
                    # （更干净的做法是以 service/model 为键）
                    # 不立即处理，统一在下面清理旧 counter
            
            # 4) 重建轮询计数器/IP 映射索引，避免持有旧列表 id() 导致的内存泄漏
            self._rebuild_load_balancer_indexes()
            
            self._update_mtime()
            
            if any([diff["added"], diff["removed"], diff["updated"],
                    diff["service_added"], diff["service_removed"],
                    diff["model_added"], diff["model_removed"]]):
                logger.info(
                    f"♻️ 配置热重载成功: "
                    f"+{len(diff['added'])} -{len(diff['removed'])} ~{len(diff['updated'])} "
                    f"services(+{len(diff['service_added'])}/-{len(diff['service_removed'])}) "
                    f"models(+{len(diff['model_added'])}/-{len(diff['model_removed'])})"
                )
                if diff["added"]:
                    logger.info(f"  新增: {diff['added']}")
                if diff["removed"]:
                    logger.info(f"  移除: {diff['removed']}")
                if diff["updated"]:
                    logger.info(f"  更新: {diff['updated']}")
            else:
                logger.info("♻️ 配置热重载完成（无变化）")
            
            return diff
    
    def _cleanup_ip_mapping_for_backend(self, backend_id: str) -> None:
        """移除指向已删除后端的所有 IP 映射条目。"""
        stale_ips = [ip for ip, bid in self.load_balancer.ip_backend_mapping.items() if bid == backend_id]
        for ip in stale_ips:
            del self.load_balancer.ip_backend_mapping[ip]
        if stale_ips:
            logger.debug(f"清理 IP 映射 {len(stale_ips)} 个 -> backend {backend_id}")
    
    def _cleanup_counter(self, service: str, model: str) -> None:
        """预留接口，当前轮询计数器用 id(list) 为键，会随旧列表被 GC 逐渐失效。统一在 rebuild 中处理。"""
        pass
    
    def _rebuild_load_balancer_indexes(self) -> None:
        """
        重建轮询计数器的有效键集合。当前实现使用 id(list) 作为键，
        reload 后旧键会被 GC 清理；为避免在长期运行中累积无用键，此处重置 counter 字典。
        已有的 IP 映射（ip -> backend_id）与列表身份无关，不重置。
        """
        # 清空旧的轮询键：reload 后 id() 键已失效，下次 select 会自动创建新键
        self.load_balancer.round_robin_counters.clear()
    
    def select_backend(
        self, 
        service: str, 
        model: str, 
        client_ip: str
    ) -> Optional[BackendInfo]:
        """选择后端节点"""
        if service not in self.backends_status:
            logger.warning(f"服务不存在: {service}")
            return None
        
        if model not in self.backends_status[service]:
            logger.warning(f"模型不存在: {service}/{model}")
            return None
        
        backends = self.backends_status[service][model]
        return self.load_balancer.select_backend(backends, client_ip)
    
    def update_backend_status(
        self, 
        service: str, 
        model: str, 
        backend_id: str, 
        status: HealthStatus, 
        response_time_ms: float = 0.0,
        error_message: Optional[str] = None
    ):
        """更新后端状态"""
        if service not in self.backends_status:
            return
        
        if model not in self.backends_status[service]:
            return
        
        for backend in self.backends_status[service][model]:
            if backend.id == backend_id:
                backend.status = status
                backend.last_check = now_shanghai()
                backend.response_time_ms = response_time_ms
                backend.error_message = error_message
                logger.info(
                    f"后端状态更新: {service}/{model}/{backend_id} -> {status.value} "
                    f"({response_time_ms:.1f}ms)"
                )
                break
    
    def get_all_backends(self) -> Dict[str, Dict[str, List[BackendInfo]]]:
        """获取所有后端信息"""
        return self.backends_status
    
    def get_service_backends(self, service: str) -> Optional[Dict[str, List[BackendInfo]]]:
        """获取某个服务的所有后端"""
        return self.backends_status.get(service)
