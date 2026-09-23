"""Dağıtık kilit: aynı hesabın döngüsü iki süreçte (ör. deploy sırasında) aynı anda çalışmasın."""

from __future__ import annotations

import uuid
from typing import Protocol

from redis.asyncio import Redis

_RELEASE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""
_EXTEND_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('pexpire', KEYS[1], ARGV[2])
end
return 0
"""


class DistributedLock(Protocol):
    ttl_ms: int

    async def acquire(self) -> bool: ...

    async def extend(self) -> bool: ...

    async def release(self) -> None: ...


class RedisLock:
    def __init__(self, redis: Redis, key: str, ttl_ms: int) -> None:
        self._redis = redis
        self._key = key
        self._token = uuid.uuid4().hex
        self.ttl_ms = ttl_ms

    async def acquire(self) -> bool:
        return bool(await self._redis.set(self._key, self._token, nx=True, px=self.ttl_ms))

    async def extend(self) -> bool:
        return bool(await self._redis.eval(_EXTEND_LUA, 1, self._key, self._token, self.ttl_ms))

    async def release(self) -> None:
        await self._redis.eval(_RELEASE_LUA, 1, self._key, self._token)


class LocalLock:
    """Redis yokken tek süreç içinde aynı işi korur."""

    _held: set[str] = set()

    def __init__(self, key: str, ttl_ms: int) -> None:
        self._key = key
        self._owned = False
        self.ttl_ms = ttl_ms

    async def acquire(self) -> bool:
        if self._key in LocalLock._held:
            return False
        LocalLock._held.add(self._key)
        self._owned = True
        return True

    async def extend(self) -> bool:
        return self._owned

    async def release(self) -> None:
        if self._owned:
            LocalLock._held.discard(self._key)
            self._owned = False


class LockFactory:
    def __init__(self, redis: Redis | None, prefix: str = "tgbt:lock:", ttl_ms: int = 60_000):
        self._redis = redis
        self._prefix = prefix
        self._ttl_ms = ttl_ms

    def __call__(self, name: str) -> DistributedLock:
        key = self._prefix + name
        if self._redis is None:
            return LocalLock(key, self._ttl_ms)
        return RedisLock(self._redis, key, self._ttl_ms)
