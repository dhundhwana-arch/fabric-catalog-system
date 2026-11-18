"""Authentication: human admin key and machine service keys.

Two distinct credential types, never interchangeable
-----------------------------------------------------
``ADMIN_API_KEY``
    The owner/staff credential. Full access. Must never be shipped to a
    browser or embedded in frontend code.

``SERVICE_API_KEYS`` (``name:key,name2:key2``)
    Backend-to-backend credentials for other modules. Module 01 calls
    Module 02 with its own key, so revoking Module 01 does not require
    rotating the human admin key and vice versa. Each service key carries
    a scope set.

Scopes
------
``catalog:read``   public catalogue data (what a public GET already exposes)
``inventory:read`` stock levels
``inventory:write`` reserve/release/dispatch/adjust
``catalog:write``  create/update/archive catalogue records
``supplier:read``  supplier/procurement data -- NEVER given to Module 01

Scopes are granted per key via ``SERVICE_KEY_SCOPES``
(``module01:inventory:write+catalog:read``). A service key with no scope
entry gets *no* privileges, so a new key must be granted explicitly.

Comparison is constant-time (``secrets.compare_digest``) to avoid leaking
key bytes through timing.

Browser clients never receive these keys: the frontend calls Module 02's
public GETs directly and Module 01's own backend for anything privileged.
"""
from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, Request, status

from app.config import get_settings

# All scopes recognised by the system.
ALL_SCOPES = {
    "catalog:read",
    "catalog:write",
    "inventory:read",
    "inventory:write",
    "supplier:read",
}


def _parse_pairs(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for chunk in (raw or "").split(","):
        chunk = chunk.strip()
        if not chunk or ":" not in chunk:
            continue
        name, _, value = chunk.partition(":")
        if name.strip() and value.strip():
            out[name.strip()] = value.strip()
    return out


def _provided_token(authorization: str | None, x_admin_key: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    if x_admin_key:
        return x_admin_key.strip()
    return None


def _match_service_key(token: str) -> tuple[str, set[str]] | None:
    settings = get_settings()
    keys = _parse_pairs(settings.service_api_keys)
    scopes_map = _parse_pairs(settings.service_key_scopes)
    for name, key in keys.items():
        if secrets.compare_digest(token, key):
            raw = scopes_map.get(name, "")
            granted = {s.strip() for s in raw.replace("+", ",").split(",") if s.strip()}
            return name, granted & ALL_SCOPES
    return None


def _ip_allowed(request: Request | None) -> bool:
    settings = get_settings()
    allow = [ip.strip() for ip in (settings.service_allowed_ips or "").split(",") if ip.strip()]
    if not allow:
        return True
    if request is None or request.client is None:
        return False
    return request.client.host in allow


async def require_admin(
    authorization: str | None = Header(default=None),
    x_admin_key: str | None = Header(default=None),
) -> None:
    """Human admin credential only. Service keys are NOT admin."""
    settings = get_settings()
    token = _provided_token(authorization, x_admin_key)
    if not token or not secrets.compare_digest(token, settings.admin_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Administrator authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )


class ScopeChecker:
    """Dependency factory: require one of ``scopes``.

    Satisfied by the admin key (full access) or by a service key holding
    the scope. Returns the caller identity so handlers/audit logs can tell
    a human from a module.
    """

    def __init__(self, *scopes: str, allow_admin: bool = True):
        unknown = set(scopes) - ALL_SCOPES
        if unknown:  # pragma: no cover - programming error
            raise ValueError(f"unknown scope(s): {unknown}")
        self.scopes = set(scopes)
        self.allow_admin = allow_admin

    async def __call__(self, request: Request) -> str:
        settings = get_settings()
        token = _provided_token(
            request.headers.get("authorization"), request.headers.get("x-admin-key")
        )
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if self.allow_admin and secrets.compare_digest(token, settings.admin_api_key):
            return "admin"
        matched = _match_service_key(token)
        if matched is None:
            # Same 401 for unknown key and insufficient scope? No: distinct
            # codes help operators debug without revealing which keys exist.
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credential",
                headers={"WWW-Authenticate": "Bearer"},
            )
        name, granted = matched
        if not _ip_allowed(request):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Service key not permitted from this address",
            )
        if not (self.scopes & granted):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required scope: {' or '.join(sorted(self.scopes))}",
            )
        return name


def require_scope(*scopes: str) -> ScopeChecker:
    return ScopeChecker(*scopes)
