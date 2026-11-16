"""Admin authentication via Bearer API key.

The key is read from the ``ADMIN_API_KEY`` environment variable. In
production this MUST be a long random secret. Public (customer-facing)
GET endpoints do not require authentication; all mutating endpoints do.
"""
from fastapi import Depends, Header, HTTPException, status

from app.config import get_settings


async def require_admin(
    authorization: str | None = Header(default=None),
    x_admin_key: str | None = Header(default=None),
) -> None:
    settings = get_settings()
    expected = settings.admin_api_key
    provided = None
    if authorization and authorization.lower().startswith("bearer "):
        provided = authorization[7:].strip()
    elif x_admin_key:
        provided = x_admin_key.strip()
    if not provided or provided != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Administrator authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
