"""
Redis 存储工具类，用于多 worker 共享状态
"""
import redis
import json
from typing import Optional, Any, Dict, List
from datetime import timedelta
import os
from loguru import logger

# Redis 配置（支持环境变量）
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)
REDIS_SOCKET_TIMEOUT = int(os.getenv("REDIS_SOCKET_TIMEOUT", 5))
REDIS_SOCKET_CONNECT_TIMEOUT = int(os.getenv("REDIS_SOCKET_CONNECT_TIMEOUT", 5))

class RedisStore:
    """Redis 存储工具类，用于多 worker 共享状态"""
    
    def __init__(self):
        try:
            self.redis_client = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                db=REDIS_DB,
                password=REDIS_PASSWORD,
                decode_responses=True,  # 自动解码字符串
                socket_timeout=REDIS_SOCKET_TIMEOUT,
                socket_connect_timeout=REDIS_SOCKET_CONNECT_TIMEOUT,
                health_check_interval=30  # 健康检查间隔（秒）
            )
            # 测试连接
            self.redis_client.ping()
            logger.info(f"Redis 连接成功 | host={REDIS_HOST} port={REDIS_PORT} db={REDIS_DB}")
        except Exception as e:
            logger.error(f"Redis 连接失败: {e}")
            raise
    
    def set(self, key: str, value: Any, expire_seconds: Optional[int] = None):
        """设置键值对，支持过期时间
        
        Args:
            key: 键名
            value: 值（支持字符串、数字、字典、列表等）
            expire_seconds: 过期时间（秒），None 表示不过期
        """
        try:
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            elif not isinstance(value, str):
                value = str(value)
            
            self.redis_client.set(key, value, ex=expire_seconds)
        except Exception as e:
            logger.error(f"Redis SET 失败 | key={key} error={e}")
            raise
    
    def get(self, key: str) -> Optional[Any]:
        """获取值
        
        Args:
            key: 键名
            
        Returns:
            值（如果是 JSON 字符串会自动解析为字典或列表），如果不存在返回 None
        """
        try:
            value = self.redis_client.get(key)
            if value is None:
                return None
            
            # 尝试解析为 JSON
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value
        except Exception as e:
            logger.error(f"Redis GET 失败 | key={key} error={e}")
            return None
    
    def delete(self, key: str) -> bool:
        """删除键
        
        Args:
            key: 键名
            
        Returns:
            是否删除成功
        """
        try:
            return self.redis_client.delete(key) > 0
        except Exception as e:
            logger.error(f"Redis DELETE 失败 | key={key} error={e}")
            return False
    
    def exists(self, key: str) -> bool:
        """检查键是否存在
        
        Args:
            key: 键名
            
        Returns:
            是否存在
        """
        try:
            return self.redis_client.exists(key) > 0
        except Exception as e:
            logger.error(f"Redis EXISTS 失败 | key={key} error={e}")
            return False
    
    def set_hash(self, key: str, field: str, value: Any):
        """设置哈希表字段
        
        Args:
            key: 哈希表键名
            field: 字段名
            value: 字段值
        """
        try:
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            elif not isinstance(value, str):
                value = str(value)
            
            self.redis_client.hset(key, field, value)
        except Exception as e:
            logger.error(f"Redis HSET 失败 | key={key} field={field} error={e}")
            raise
    
    def get_hash(self, key: str, field: str) -> Optional[Any]:
        """获取哈希表字段
        
        Args:
            key: 哈希表键名
            field: 字段名
            
        Returns:
            字段值（如果是 JSON 字符串会自动解析），如果不存在返回 None
        """
        try:
            value = self.redis_client.hget(key, field)
            if value is None:
                return None
            
            # 尝试解析为 JSON
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value
        except Exception as e:
            logger.error(f"Redis HGET 失败 | key={key} field={field} error={e}")
            return None
    
    def get_all_hash(self, key: str) -> Dict[str, Any]:
        """获取哈希表所有字段
        
        Args:
            key: 哈希表键名
            
        Returns:
            所有字段的字典
        """
        try:
            result = self.redis_client.hgetall(key)
            # 尝试解析 JSON 值
            parsed_result = {}
            for field, value in result.items():
                try:
                    parsed_result[field] = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    parsed_result[field] = value
            return parsed_result
        except Exception as e:
            logger.error(f"Redis HGETALL 失败 | key={key} error={e}")
            return {}
    
    def delete_hash(self, key: str, field: str) -> bool:
        """删除哈希表字段
        
        Args:
            key: 哈希表键名
            field: 字段名
            
        Returns:
            是否删除成功
        """
        try:
            return self.redis_client.hdel(key, field) > 0
        except Exception as e:
            logger.error(f"Redis HDEL 失败 | key={key} field={field} error={e}")
            return False
    
    def set_expire(self, key: str, expire_seconds: int) -> bool:
        """设置键过期时间
        
        Args:
            key: 键名
            expire_seconds: 过期时间（秒）
            
        Returns:
            是否设置成功
        """
        try:
            return self.redis_client.expire(key, expire_seconds)
        except Exception as e:
            logger.error(f"Redis EXPIRE 失败 | key={key} error={e}")
            return False
    
    def keys(self, pattern: str) -> List[str]:
        """获取匹配模式的所有键
        
        Args:
            pattern: 匹配模式（如 "upload_task:*"）
            
        Returns:
            匹配的键列表
        """
        try:
            return self.redis_client.keys(pattern)
        except Exception as e:
            logger.error(f"Redis KEYS 失败 | pattern={pattern} error={e}")
            return []
    
    def get_stats(self) -> Dict[str, Any]:
        """获取 Redis 统计信息
        
        Returns:
            统计信息字典
        """
        try:
            info = self.redis_client.info()
            return {
                "connected_clients": info.get("connected_clients", 0),
                "used_memory_human": info.get("used_memory_human", "0B"),
                "total_commands_processed": info.get("total_commands_processed", 0),
                "keyspace_hits": info.get("keyspace_hits", 0),
                "keyspace_misses": info.get("keyspace_misses", 0),
                "db_size": self.redis_client.dbsize()
            }
        except Exception as e:
            logger.error(f"获取 Redis 统计信息失败: {e}")
            return {}

# 全局 Redis 实例（延迟初始化）
_redis_store: Optional[RedisStore] = None

def get_redis_store() -> RedisStore:
    """获取 Redis 存储实例（单例模式）"""
    global _redis_store
    if _redis_store is None:
        _redis_store = RedisStore()
    return _redis_store

# 为了向后兼容，提供直接访问
try:
    redis_store = get_redis_store()
except Exception as e:
    logger.warning(f"Redis 初始化失败，将使用内存存储（仅单 worker 模式）: {e}")
    redis_store = None

