import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_catalog.db")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("UPLOAD_DIR", "./test_uploads")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app

engine = create_engine("sqlite:///./test_catalog.db", connect_args={"check_same_thread": False})
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="session", autouse=True)
def _tables():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSession(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture()
def client(db_session):
    def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
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
