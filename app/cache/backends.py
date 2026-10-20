import hashlib
import json
from datetime import timedelta
from typing import Any, Dict, Optional

import redis

from app.config import settings
from app import observability


class CacheKey:
    @staticmethod
    def build(*parts: Any) -> str:
        raw = json.dumps(parts, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class RedisCache:
    def __init__(self):
        self.client = redis.Redis(host=settings.redis_host, port=settings.redis_port, db=settings.redis_db)

    def get(self, key: str) -> Optional[str]:
        value = self.client.get(key)
        observability.log_step("cache.redis.get", f"hit={value is not None}")
        return value.decode("utf-8") if value else None

    def set(self, key: str, value: str, ttl: int) -> None:
        self.client.setex(key, ttl, value)
        observability.log_step("cache.redis.set", f"ttl={ttl}")

    def delete(self, key: str) -> None:
        self.client.delete(key)
        observability.log_step("cache.redis.delete", "entry_deleted")


class InMemoryCache:
    def __init__(self):
        self.store: Dict[str, Dict[str, Any]] = {}

    def get(self, key: str) -> Optional[str]:
        item = self.store.get(key)
        if not item or item["expires_at"] < settings.now():
            self.store.pop(key, None)
            observability.log_step("cache.memory.get", "hit=false")
            return None
        observability.log_step("cache.memory.get", "hit=true")
        return item["value"]

    def set(self, key: str, value: str, ttl: int) -> None:
        self.store[key] = {
            "value": value,
            "expires_at": settings.now() + timedelta(seconds=ttl),
        }
        observability.log_step("cache.memory.set", f"ttl={ttl}")

    def delete(self, key: str) -> None:
        self.store.pop(key, None)
        observability.log_step("cache.memory.delete", "entry_deleted")

    def clear(self) -> None:
        self.store.clear()
        observability.log_step("cache.memory.clear", "entries_deleted")
