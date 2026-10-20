from .backends import CacheKey, InMemoryCache, RedisCache

cache = InMemoryCache()

__all__ = ["CacheKey", "InMemoryCache", "RedisCache", "cache"]