"""Rate limiting with explicit, honest scope semantics (residual R1).

Three modes, chosen by ``RATE_LIMIT_BACKEND``:

``memory`` (default)
    Fixed-window counters in a module-level dict.
    **Scope: this process only.** With N uvicorn workers behind a load
    balancer the effective limit is approximately ``N x limit``, counters
    reset on restart, and nothing is shared between replicas. This is
    correct for a single-worker deployment and for development.

``redis``
    Fixed-window counters in Redis via an atomic ``INCR`` + ``EXPIRE``, so
    the limit is enforced **across all workers and replicas** that point at
    the same Redis instance. If Redis is unreachable the configured
    ``RATE_LIMIT_FAIL_OPEN`` decides between allowing the request (fail-open,
    recommended so a cache outage cannot take the API down) and rejecting
    with 503 (fail-closed).

``off``
    Disabled entirely (``RATE_LIMIT_PER_MINUTE=0`` also disables).

What is deliberately NOT claimed
--------------------------------
- This is not a defence against distributed volumetric attacks. A shared
  gateway/CDN limiter is still the right first line.
- The key is the client IP as seen by the app. Behind a proxy, configure
  ``TRUSTED_PROXY_COUNT`` so ``X-Forwarded-For`` is only honoured when the
  immediate peer is a trusted proxy; otherwise clients could spoof the
  header to bypass the limit.
- ``memory`` mode is never described as distributed.
"""
from __future__ import annotations

import logging
import threading
import time

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# Paths that are cheap and used by orchestrators; never rate limit them.
EXEMPT_PATHS = {"/health"}


class MemoryRateLimiter:
    scope = "process-local"

    def __init__(self, limit: int):
        self.limit = limit
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> tuple[bool, int]:
        now = time.time()
        with self._lock:
            window = [t for t in self._hits.get(key, []) if now - t < 60]
            if len(window) >= self.limit:
                self._hits[key] = window
                return False, 0
            window.append(now)
            self._hits[key] = window
            return True, self.limit - len(window)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


class RedisRateLimiter:
    scope = "shared-across-workers"

    def __init__(self, limit: int, url: str, fail_open: bool = True):
        self.limit = limit
        self.url = url
        self.fail_open = fail_open
        self._client = None

    def _get_client(self):
        if self._client is None:
            import redis  # imported lazily: optional dependency

            self._client = redis.Redis.from_url(self.url, decode_responses=True)
        return self._client

    def hit(self, key: str) -> tuple[bool, int]:
        # Fixed 60 s window keyed on the minute bucket: the counter is
        # created atomically and expires on its own, so no cleanup job and
        # no read-modify-write race between workers.
        bucket = int(time.time() // 60)
        redis_key = f"rl:{key}:{bucket}"
        try:
            client = self._get_client()
            pipe = client.pipeline()
            pipe.incr(redis_key)
            pipe.expire(redis_key, 120)
            count, _ = pipe.execute()
            remaining = max(0, self.limit - int(count))
            return int(count) <= self.limit, remaining
        except Exception as exc:  # noqa: BLE001 - any Redis failure
            # Never log the URL: it may embed a password.
            logger.warning("rate limiter backend unavailable (%s); fail_open=%s",
                           type(exc).__name__, self.fail_open)
            if self.fail_open:
                return True, self.limit
            raise

    def reset(self) -> None:  # pragma: no cover - used by tests only
        try:
            client = self._get_client()
            for k in client.scan_iter("rl:*"):
                client.delete(k)
        except Exception:  # noqa: BLE001
            pass


def client_key(request: Request, trusted_proxy_count: int = 0) -> str:
    """Derive the limiting key without trusting spoofable headers.

    ``X-Forwarded-For`` is only consulted when ``trusted_proxy_count > 0``,
    and then the entry inserted by the *nearest trusted proxy* is used
    (counting from the right), not the leftmost value the client controls.
    """
    if trusted_proxy_count > 0:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            parts = [p.strip() for p in forwarded.split(",") if p.strip()]
            if parts:
                idx = max(0, len(parts) - trusted_proxy_count)
                return parts[idx]
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limiter, trusted_proxy_count: int = 0):
        super().__init__(app)
        self.limiter = limiter
        self.trusted_proxy_count = trusted_proxy_count

    async def dispatch(self, request: Request, call_next):
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)
        key = client_key(request, self.trusted_proxy_count)
        try:
            allowed, remaining = self.limiter.hit(key)
        except Exception:  # fail-closed backend failure
            return JSONResponse(
                status_code=503,
                content={"detail": "Rate limiter backend unavailable"},
            )
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={"Retry-After": "60", "X-RateLimit-Scope": self.limiter.scope},
            )
        response = await call_next(request)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Scope"] = self.limiter.scope
        return response


def build_limiter(settings):
    """Return a limiter instance, or None when limiting is disabled."""
    if settings.rate_limit_per_minute <= 0 or settings.rate_limit_backend == "off":
        return None
    if settings.rate_limit_backend == "redis":
        if not settings.redis_url:
            raise RuntimeError(
                "RATE_LIMIT_BACKEND=redis requires REDIS_URL to be set"
            )
        return RedisRateLimiter(
            settings.rate_limit_per_minute,
            settings.redis_url,
            fail_open=settings.rate_limit_fail_open,
        )
    return MemoryRateLimiter(settings.rate_limit_per_minute)
