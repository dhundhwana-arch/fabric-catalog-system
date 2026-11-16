"""Application configuration via environment variables."""
from functools import lru_cache
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
    admin_api_key: str = "dev-only-change-me"

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

    # Rate limiting (requests per minute per IP, 0 = disabled)
    rate_limit_per_minute: int = 0


@lru_cache
def get_settings() -> Settings:
    return Settings()
