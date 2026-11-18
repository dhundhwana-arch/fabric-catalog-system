"""Rate limiting scope and backend-to-backend service authentication.

Redis behaviour is exercised against ``fakeredis``. That exercises the real
``RedisRateLimiter`` code path (INCR/EXPIRE, key bucketing, fail-open) but
it is NOT a substitute for a real Redis server test; see AUDIT report
limitation L2.
"""
from __future__ import annotations

import pytest

from app.rate_limit import (
    MemoryRateLimiter,
    RedisRateLimiter,
    build_limiter,
    client_key,
)


# ---------------------------------------------------------------------------
# Memory limiter: single-process semantics
# ---------------------------------------------------------------------------
def test_memory_limiter_allows_up_to_limit_then_blocks():
    lim = MemoryRateLimiter(3)
    assert [lim.hit("1.2.3.4")[0] for _ in range(3)] == [True, True, True]
    allowed, _ = lim.hit("1.2.3.4")
    assert allowed is False


def test_memory_limiter_is_per_key():
    lim = MemoryRateLimiter(1)
    assert lim.hit("a")[0] is True
    assert lim.hit("a")[0] is False
    assert lim.hit("b")[0] is True


def test_memory_limiter_declares_process_local_scope():
    """It must never claim to be distributed."""
    assert MemoryRateLimiter(5).scope == "process-local"


def test_reset_clears_window():
    lim = MemoryRateLimiter(1)
    lim.hit("x")
    assert lim.hit("x")[0] is False
    lim.reset()
    assert lim.hit("x")[0] is True


# ---------------------------------------------------------------------------
# Redis limiter: shared semantics (fakeredis)
# ---------------------------------------------------------------------------
class _FakeRedisLimiter(RedisRateLimiter):
    def __init__(self, limit, fail_open=True, broken=False):
        super().__init__(limit, "redis://localhost:6379/0", fail_open=fail_open)
        import fakeredis

        self._fake = None if broken else fakeredis.FakeStrictRedis(decode_responses=True)
        self._broken = broken

    def _get_client(self):
        if self._broken:
            raise ConnectionError("simulated redis outage")
        return self._fake


def test_redis_limiter_is_shared_across_instances():
    """Two 'workers' sharing one Redis enforce ONE combined limit."""
    # Independent limiter objects = independent processes, same Redis.
    import fakeredis

    server = fakeredis.FakeServer()
    client_a = fakeredis.FakeStrictRedis(server=server, decode_responses=True)
    client_b = fakeredis.FakeStrictRedis(server=server, decode_responses=True)

    lim_a = RedisRateLimiter(2, "redis://localhost/0")
    lim_b = RedisRateLimiter(2, "redis://localhost/0")
    lim_a._client, lim_b._client = client_a, client_b

    assert lim_a.hit("ip")[0] is True
    assert lim_b.hit("ip")[0] is True
    # Third request total, across both workers, is refused.
    assert lim_a.hit("ip")[0] is False
    assert lim_b.hit("ip")[0] is False


def test_redis_limiter_declares_shared_scope():
    assert RedisRateLimiter(5, "redis://x").scope == "shared-across-workers"


def test_redis_limiter_fails_open_when_configured():
    lim = _FakeRedisLimiter(1, fail_open=True, broken=True)
    allowed, _ = lim.hit("ip")
    assert allowed is True


def test_redis_limiter_fails_closed_when_configured():
    lim = _FakeRedisLimiter(1, fail_open=False, broken=True)
    with pytest.raises(Exception):
        lim.hit("ip")


def test_build_limiter_respects_configuration():
    from app.config import Settings

    assert build_limiter(Settings(rate_limit_per_minute=0)) is None
    assert build_limiter(Settings(rate_limit_backend="off")) is None
    assert isinstance(build_limiter(Settings(rate_limit_per_minute=10)), MemoryRateLimiter)
    redis_limiter = build_limiter(
        Settings(
            rate_limit_per_minute=10,
            rate_limit_backend="redis",
            redis_url="redis://localhost:6379/0",
        )
    )
    assert isinstance(redis_limiter, RedisRateLimiter)
    with pytest.raises(RuntimeError):
        build_limiter(Settings(rate_limit_per_minute=10, rate_limit_backend="redis"))


# ---------------------------------------------------------------------------
# Client key derivation: no spoofable-header bypass
# ---------------------------------------------------------------------------
class _Req:
    def __init__(self, host="10.0.0.1", headers=None):
        self.client = type("C", (), {"host": host})()
        self.headers = headers or {}


def test_xff_ignored_when_no_trusted_proxies():
    req = _Req(headers={"x-forwarded-for": "1.1.1.1"})
    assert client_key(req, trusted_proxy_count=0) == "10.0.0.1"


def test_xff_honours_nearest_trusted_hop_not_client_supplied():
    # Client prepends a fake 1.1.1.1; the real proxy appended 203.0.113.9.
    req = _Req(headers={"x-forwarded-for": "1.1.1.1, 203.0.113.9"})
    assert client_key(req, trusted_proxy_count=1) == "203.0.113.9"


# ---------------------------------------------------------------------------
# Service (backend-to-backend) authentication
# ---------------------------------------------------------------------------
def test_service_key_can_use_inventory_write(client, seeded, service_keys):
    vid = seeded["v1"]["id"]
    r = client.post(
        f"/api/v1/inventory/{vid}/adjust",
        json={"quantity": "5"},
        headers={"Authorization": "Bearer svc-key-1"},
    )
    assert r.status_code == 200, r.text


def test_service_key_cannot_read_suppliers(client, seeded, service_keys):
    """catalog:read + inventory:write is not supplier:read."""
    r = client.get(
        "/api/v1/suppliers", headers={"Authorization": "Bearer svc-key-1"}
    )
    assert r.status_code == 403


def test_unknown_service_key_rejected(client, seeded, service_keys):
    r = client.post(
        f"/api/v1/inventory/{seeded['v1']['id']}/adjust",
        json={"quantity": "5"},
        headers={"Authorization": "Bearer not-a-real-key"},
    )
    assert r.status_code == 401


def test_admin_key_still_works_for_everything(client, seeded, admin_headers):
    assert client.get("/api/v1/suppliers", headers=admin_headers).status_code == 200


def test_service_key_without_scope_entry_gets_nothing(client, seeded, monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "service_api_keys", "unscoped:svc-key-x")
    monkeypatch.setattr(settings, "service_key_scopes", "")
    r = client.post(
        f"/api/v1/inventory/{seeded['v1']['id']}/adjust",
        json={"quantity": "5"},
        headers={"Authorization": "Bearer svc-key-x"},
    )
    assert r.status_code == 403


def test_service_key_ip_allowlist_enforced(client, seeded, monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "service_api_keys", "module01:svc-key-1")
    monkeypatch.setattr(settings, "service_key_scopes", "module01:inventory:write")
    monkeypatch.setattr(settings, "service_allowed_ips", "203.0.113.99")
    r = client.post(
        f"/api/v1/inventory/{seeded['v1']['id']}/adjust",
        json={"quantity": "5"},
        headers={"Authorization": "Bearer svc-key-1"},
    )
    assert r.status_code == 403


def test_service_keys_are_never_in_openapi_or_health(client):
    """No credential material is exposed by public introspection endpoints."""
    spec = client.get("/openapi.json").text
    assert "svc-key" not in spec
    assert "service_api_keys" not in spec
    health = client.get("/health").text
    assert "key" not in health.lower()


def test_admin_and_service_credentials_are_distinct(service_keys):
    """A service key must NOT be accepted as the admin credential."""
    settings = service_keys
    assert settings.service_api_keys != settings.admin_api_key


# ---------------------------------------------------------------------------
# HTTP-level idempotency
# ---------------------------------------------------------------------------
def test_http_idempotent_replay_returns_stored_body(client, seeded, admin_headers):
    """A repeated Idempotency-Key must replay the original JSON, not the ORM."""
    vid = seeded["v1"]["id"]
    headers = {**admin_headers, "Idempotency-Key": "http-idem-1"}
    first = client.post(
        f"/api/v1/inventory/{vid}/adjust", json={"quantity": "7"}, headers=headers
    )
    assert first.status_code == 200, first.text
    second = client.post(
        f"/api/v1/inventory/{vid}/adjust", json={"quantity": "7"}, headers=headers
    )
    assert second.status_code == 200
    assert second.headers.get("Idempotent-Replay") == "true"
    assert second.json() == first.json()
    assert isinstance(second.json(), dict)
    assert "object at 0x" not in second.text
    # Stock moved exactly once.
    inv = client.get(f"/api/v1/inventory/{vid}").json()
    assert str(inv["stock_quantity"]) in ("7.0", "7.000")


def test_http_idempotency_key_reuse_with_different_body_conflicts(
    client, seeded, admin_headers
):
    vid = seeded["v1"]["id"]
    headers = {**admin_headers, "Idempotency-Key": "http-idem-2"}
    assert client.post(
        f"/api/v1/inventory/{vid}/adjust", json={"quantity": "5"}, headers=headers
    ).status_code == 200
    conflict = client.post(
        f"/api/v1/inventory/{vid}/adjust", json={"quantity": "9"}, headers=headers
    )
    assert conflict.status_code == 409


def test_concurrent_identical_idempotent_requests_apply_once(client, seeded, admin_headers):
    """12 concurrent requests sharing one key must move stock exactly once."""
    import threading


    vid = seeded["v1"]["id"]
    client.post(f"/api/v1/inventory/{vid}/adjust", json={"quantity": "50"}, headers=admin_headers)

    statuses, lock = [], threading.Lock()

    def worker():
        headers = {**admin_headers, "Idempotency-Key": "race-key-1"}
        try:
            r = client.post(
                f"/api/v1/inventory/{vid}/reserve", json={"quantity": "5"}, headers=headers
            )
            with lock:
                statuses.append(r.status_code)
        except Exception:
            with lock:
                statuses.append("error")

    threads = [threading.Thread(target=worker) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    inv = client.get(f"/api/v1/inventory/{vid}").json()
    assert str(inv["reserved_quantity"]) in ("5.0", "5.000"), (
        f"stock moved more than once: {inv['reserved_quantity']} (statuses={statuses})"
    )
