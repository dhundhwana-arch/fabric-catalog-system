import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_catalog.db")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("UPLOAD_DIR", "./test_uploads")
# The limiter is per-process/per-IP; tests issue far more than the
# production default, so disable it for the suite (it has its own test).
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "0")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.database import Base, engine, get_db
from app.main import app

# Use the application engine so tests exercise the real SQLite pragmas
# (WAL, busy_timeout, BEGIN IMMEDIATE) rather than a bare engine.
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

_TABLES_IN_FK_ORDER = [
    "inventory_movements",
    "inventory_lots",
    "fabric_prices",
    "fabric_images",
    "supplier_references",
    "fabric_variants",
    "fabrics",
    "fabric_categories",
    "id_sequences",
]


@pytest.fixture(scope="session", autouse=True)
def _tables():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def _wipe():
    """Clear all rows between tests.

    A transaction-rollback harness is deliberately NOT used: the app runs
    with ``BEGIN IMMEDIATE`` on SQLite (required for correct concurrent ID
    allocation), so a long-lived outer transaction in a fixture would block
    the application's own writes.
    """
    with engine.begin() as conn:
        for table in _TABLES_IN_FK_ORDER:
            conn.execute(text(f"DELETE FROM {table}"))


@pytest.fixture(autouse=True)
def _clean(_tables):
    _wipe()
    yield


@pytest.fixture()
def db_session():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def client(db_session):
    def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def admin_headers():
    return {"Authorization": "Bearer test-admin-key"}


@pytest.fixture()
def seeded(client, admin_headers):
    """Create a category, fabric and two variants; return ids."""
    cat = client.post("/api/v1/categories", json={"name": "Cotton"}, headers=admin_headers).json()
    fab = client.post(
        "/api/v1/fabrics",
        json={"fabric_name": "Test Poplin", "category_id": cat["id"], "fabric_type": "Poplin"},
        headers=admin_headers,
    ).json()
    v1 = client.post(
        "/api/v1/variants",
        json={"fabric_id": fab["id"], "colour_name": "Navy Blue", "colour_hex": "#000080",
              "customer_price": "450.00", "availability_status": "AVAILABLE"},
        headers=admin_headers,
    ).json()
    v2 = client.post(
        "/api/v1/variants",
        json={"fabric_id": fab["id"], "colour_name": "White", "colour_hex": "#FFFFFF",
              "customer_price": "420.00", "availability_status": "OUT_OF_STOCK"},
        headers=admin_headers,
    ).json()
    return {"category": cat, "fabric": fab, "v1": v1, "v2": v2}


@pytest.fixture()
def service_keys(monkeypatch):
    """Configure two backend service credentials with distinct scopes.

    module01: catalog:read + inventory:write (deliberately NOT supplier:read)
    module07: inventory:write only
    """
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "service_api_keys", "module01:svc-key-1,module07:svc-key-7")
    monkeypatch.setattr(
        settings,
        "service_key_scopes",
        "module01:catalog:read+inventory:write,module07:inventory:write",
    )
    return settings
