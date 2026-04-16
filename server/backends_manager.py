"""
后端管理 - 负载均衡、IP映射、健康状态
"""
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import hashlib
import logging

from models import BackendNode, BackendInfo, HealthStatus, Config

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
        self.backends_status: Dict[str, Dict[str, Dict[str, BackendInfo]]] = {}
        self.load_balancer = LoadBalancer()
        self._load_config()
    
    def _load_config(self):
        """加载并解析配置文件"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            config = Config(**data)
            
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
                            status=HealthStatus.UNKNOWN
                        )
                        for b in model_group.backends
                    ]
                    self.backends_status[service_name][model_name] = backend_infos
                    logger.info(f"加载后端配置: {service_name}/{model_name} -> {len(backend_infos)}个节点")
            
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
                backend.last_check = datetime.utcnow()
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
