"""Caché Redis. Best-effort: si Redis cae, el sistema sigue funcionando."""

from __future__ import annotations

import json
import logging
from typing import Any

import redis

from ..config import get_settings

log = logging.getLogger(__name__)


class RedisCache:
    def __init__(self, url: str | None = None, prefix: str = "pg") -> None:
        cfg = get_settings()
        self._prefix = prefix
        self._client = redis.Redis.from_url(
            url or cfg.redis_url, decode_responses=True, socket_timeout=2, socket_connect_timeout=2
        )

    def _key(self, key: str) -> str:
        return f"{self._prefix}:{key}"

    def get(self, key: str) -> Any | None:
        try:
            raw = self._client.get(self._key(key))
            return json.loads(raw) if raw else None
        except Exception as exc:
            log.debug("cache get falló: %s", exc)
            return None

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        try:
            payload = json.dumps(value, ensure_ascii=False, default=str)
            if ttl_seconds:
                self._client.setex(self._key(key), ttl_seconds, payload)
            else:
                self._client.set(self._key(key), payload)
        except Exception as exc:
            log.debug("cache set falló: %s", exc)

    def delete(self, key: str) -> None:
        try:
            self._client.delete(self._key(key))
        except Exception as exc:
            log.debug("cache delete falló: %s", exc)

    def delete_prefix(self, prefix: str) -> int:
        """Invalidación por patrón. Usa SCAN, nunca KEYS."""
        deleted = 0
        try:
            for key in self._client.scan_iter(match=f"{self._prefix}:{prefix}*", count=500):
                self._client.delete(key)
                deleted += 1
        except Exception as exc:
            log.debug("cache delete_prefix falló: %s", exc)
        return deleted

    def lock(self, key: str, ttl_seconds: int = 60) -> bool:
        """Lock simple para que dos workers no calculen el mismo informe."""
        try:
            return bool(self._client.set(self._key(f"lock:{key}"), "1", nx=True, ex=ttl_seconds))
        except Exception:
            return True  # ante la duda, dejamos pasar: mejor duplicar que bloquear

    def unlock(self, key: str) -> None:
        self.delete(f"lock:{key}")

    def incr_window(self, subject: str, window_seconds: int) -> int:
        """Contador con ventana deslizante. Base del rate limiting."""
        key = self._key(f"rl:{subject}:{window_seconds}")
        try:
            pipe = self._client.pipeline()
            pipe.incr(key)
            pipe.expire(key, window_seconds, nx=True)
            count, _ = pipe.execute()
            return int(count)
        except Exception:
            return 0

    def ping(self) -> bool:
        try:
            return bool(self._client.ping())
        except Exception:
            return False


class NullCache:
    """Sin caché. Útil en tests y como respaldo."""

    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        return None

    def delete(self, key: str) -> None:
        return None

    def delete_prefix(self, prefix: str) -> int:
        return 0

    def lock(self, key: str, ttl_seconds: int = 60) -> bool:
        return True

    def incr_window(self, subject: str, window_seconds: int) -> int:
        return 0

    def ping(self) -> bool:
        return False


_cache: RedisCache | NullCache | None = None


def get_cache() -> RedisCache | NullCache:
    global _cache
    if _cache is None:
        try:
            candidate = RedisCache()
            _cache = candidate if candidate.ping() else NullCache()
        except Exception:
            _cache = NullCache()
    return _cache
