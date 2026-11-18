"""Application configuration via environment variables."""
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Fabric Catalog System"
    app_env: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    # SQLite by default (zero-config). Set to PostgreSQL URL in production:
    #   DATABASE_URL=postgresql+psycopg://user:pass@host:5432/fabric_catalog
    database_url: str = "sqlite:///./fabric_catalog.db"

    # Admin authentication: Bearer token. MUST be overridden in production.
    # Generate: python -c "import secrets; print(secrets.token_urlsafe(32))"
    # The app refuses to start in production with the default value.
    admin_api_key: str = "dev-only-change-me"

    def validate_production(self) -> None:
        if self.app_env == "production" and (
            self.admin_api_key in (
                "dev-only-change-me",
                "change-me",
                "replace-with-a-long-random-secret",
            )
            or len(self.admin_api_key) < 16
        ):
            raise RuntimeError(
                "ADMIN_API_KEY must be set to a strong secret when APP_ENV=production. "
                "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
            )

    # Image uploads
    upload_dir: str = "./uploads"
    max_upload_bytes: int = 5 * 1024 * 1024  # 5 MB
    allowed_image_types: list[str] = ["image/jpeg", "image/png", "image/webp"]

    # Inventory tracking (optional feature flag)
    inventory_enabled: bool = True

    # CORS — comma-separated origins, "*" for dev
    cors_origins: str = "*"

    # Pagination defaults
    default_page_size: int = 20
    max_page_size: int = 100

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------
    # Requests per minute per client key. 0 disables limiting entirely.
    rate_limit_per_minute: int = 120
    # "memory" = THIS PROCESS ONLY (default; limit x workers in practice).
    # "redis"  = shared across workers/replicas using REDIS_URL.
    # "off"    = disabled.
    rate_limit_backend: Literal["memory", "redis", "off"] = "memory"
    # Only used when backend == "redis". Never logged.
    redis_url: str | None = None
    # If Redis is down: True = allow requests (fail-open), False = 503.
    rate_limit_fail_open: bool = True
    # Number of reverse proxies in front of the app that overwrite
    # X-Forwarded-For. 0 = ignore the header entirely (prevents spoofing
    # to bypass rate limits).
    trusted_proxy_count: int = 0

    # ------------------------------------------------------------------
    # Backend-to-backend authentication (Module 01 -> Module 02)
    # ------------------------------------------------------------------
    # Module 01 authenticates with its own service key, never the human
    # admin key. Comma-separated "name:key" pairs.
    service_api_keys: str = ""
    # Default scopes granted to a service key unless overridden by
    # service_key_scopes ("name:scope1+scope2,...").
    service_key_scopes: str = ""
    # If set, only these client IPs may use service keys (defence in depth).
    service_allowed_ips: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
