"""Alembic migration verification.

Two things are proven here:

1. **Clean creation** — ``alembic upgrade head`` on an empty database
   produces a schema identical to the ORM metadata, on SQLite and on
   PostgreSQL.
2. **Upgrade from the pre-Alembic schema** — databases created by the old
   ``Base.metadata.create_all()`` path (the current production state) can
   be adopted without data loss and without duplicate DDL: the baseline
   revision inspects existing tables first.

PostgreSQL tests run against a real server when ``PG_TEST_URL`` is set to a
SQLAlchemy URL; otherwise they are skipped and reported as skipped, never
as passed.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

REPO = Path(__file__).resolve().parents[1]

SAMPLE_ROWS = {
    "fabric_categories": {
        "category_id": "FCAT-001", "name": "Cotton", "description": None,
        "is_active": True, "created_at": "2026-01-01 00:00:00", "updated_at": "2026-01-01 00:00:00",
    },
    "fabrics": {
        "fabric_id": "FAB-001", "fabric_name": "Existing Poplin", "category_id": 1,
        "fabric_type": "Poplin", "composition": None, "description": None,
        "sourcing_method": "BUSINESS_INVENTORY", "is_active": True,
        "created_at": "2026-01-01 00:00:00", "updated_at": "2026-01-01 00:00:00",
    },
    "fabric_variants": {
        "variant_id": "FVAR-001", "fabric_id": 1, "colour_name": "Navy",
        "colour_hex": "#000080", "availability_status": "UNKNOWN", "unit": "METER",
        "customer_price": "450.00", "currency": "INR", "is_active": True,
        "created_at": "2026-01-01 00:00:00", "updated_at": "2026-01-01 00:00:00",
    },
    "id_sequences": {"kind": "fabric", "last_value": 1},
    "inventory_lots": {
        "lot_id": "FLOT-001", "variant_id": 1, "stock_quantity": "10.000",
        "reserved_quantity": "0.000", "unit": "METER", "revision": 0,
        "last_updated": "2026-01-01 00:00:00",
    },
}


def _alembic(db_url: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "ALEMBIC_DATABASE_URL": db_url}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO, env=env, capture_output=True, text=True, timeout=180,
    )


def _tables(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def _columns(url: str) -> dict[str, list[tuple]]:
    engine = create_engine(url)
    try:
        insp = inspect(engine)
        out = {}
        for t in insp.get_table_names():
            out[t] = sorted((c["name"], str(c["type"]), c["nullable"]) for c in insp.get_columns(t))
        return out
    finally:
        engine.dispose()


APP_TABLES = {
    "fabric_categories", "fabrics", "fabric_variants", "fabric_images",
    "fabric_prices", "supplier_references", "inventory_lots",
    "inventory_movements", "id_sequences", "idempotency_records",
}


# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------
def test_clean_database_creation_sqlite(tmp_path):
    url = f"sqlite:///{tmp_path/'clean.db'}"
    result = _alembic(url, "upgrade", "head")
    assert result.returncode == 0, result.stderr[-2000:]
    tables = _tables(url)
    assert tables >= APP_TABLES, f"missing: {APP_TABLES - tables}"


def test_migration_matches_orm_metadata_sqlite(tmp_path):
    """After upgrade, Alembic sees no pending diff (schema == models)."""
    url = f"sqlite:///{tmp_path/'drift.db'}"
    assert _alembic(url, "upgrade", "head").returncode == 0
    check = _alembic(url, "check")
    assert check.returncode == 0, f"schema drift:\n{check.stdout[-2000:]}{check.stderr[-2000:]}"


def test_upgrade_from_create_all_schema_preserves_data_sqlite(tmp_path):
    """Adopt a pre-Alembic database without dropping anything."""
    path = tmp_path / "legacy.db"
    url = f"sqlite:///{path}"

    import app.models  # noqa: F401
    from app.database import Base

    engine = create_engine(url)
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        for table, row in SAMPLE_ROWS.items():
            cols = ", ".join(row)
            placeholders = ", ".join(f":{c}" for c in row)
            conn.execute(text(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"), row)
    engine.dispose()

    result = _alembic(url, "upgrade", "head")
    assert result.returncode == 0, result.stderr[-2000:]

    engine = create_engine(url)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT fabric_name FROM fabrics")).scalar_one() == "Existing Poplin"
        assert conn.execute(text("SELECT last_value FROM id_sequences")).scalar_one() == 1
        assert conn.execute(text("SELECT stock_quantity FROM inventory_lots")).scalar_one() is not None
    engine.dispose()
    assert _tables(url) >= APP_TABLES


def test_downgrade_and_reupgrade_sqlite(tmp_path):
    url = f"sqlite:///{tmp_path/'cycle.db'}"
    assert _alembic(url, "upgrade", "head").returncode == 0
    assert _alembic(url, "downgrade", "base").returncode == 0
    remaining = _tables(url) - {"alembic_version"}
    assert remaining == set(), f"downgrade left tables: {remaining}"
    assert _alembic(url, "upgrade", "head").returncode == 0
    assert _tables(url) >= APP_TABLES


# ---------------------------------------------------------------------------
# PostgreSQL (real server; skipped and reported if unavailable)
# ---------------------------------------------------------------------------
PG_URL = os.getenv("PG_TEST_URL")


def _pg_available() -> bool:
    if not PG_URL:
        return False
    try:
        engine = create_engine(PG_URL)
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


needs_pg = pytest.mark.skipif(
    not _pg_available(),
    reason="PG_TEST_URL not set/available - PostgreSQL migration test NOT run",
)


def _pg_fresh_db(name: str) -> tuple[str, str]:
    """Create a throwaway database; return (admin_url, db_url).

    Splits on the LAST "/" that precedes any query string, so URLs of the
    form postgresql://user:pw@host/db?host=/socket/dir keep their socket
    directory intact.
    """
    import psycopg

    admin = PG_URL
    head, sep, tail = admin.partition("?")
    base, _, _old = head.rpartition("/")
    db_url = f"{base}/{name}" + (f"?{tail}" if sep else "")

    raw = admin.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(raw, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}"')
        conn.execute(f'CREATE DATABASE "{name}"')
    return admin, db_url


@needs_pg
def test_clean_database_creation_postgresql():
    _, url = _pg_fresh_db("mig_clean")
    result = _alembic(url, "upgrade", "head")
    assert result.returncode == 0, result.stderr[-2000:]
    tables = _tables(url)
    assert tables >= APP_TABLES, f"missing: {APP_TABLES - tables}"


@needs_pg
def test_migration_matches_orm_metadata_postgresql():
    _, url = _pg_fresh_db("mig_drift")
    assert _alembic(url, "upgrade", "head").returncode == 0
    check = _alembic(url, "check")
    assert check.returncode == 0, f"schema drift:\n{check.stdout[-3000:]}{check.stderr[-2000:]}"


@needs_pg
def test_upgrade_from_create_all_preserves_data_postgresql():
    """The real production-adoption scenario, on real PostgreSQL."""
    _, url = _pg_fresh_db("mig_legacy")

    import app.models  # noqa: F401
    from app.database import Base

    engine = create_engine(url)
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        for table, row in SAMPLE_ROWS.items():
            cols = ", ".join(row)
            placeholders = ", ".join(f":{c}" for c in row)
            conn.execute(text(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"), row)
    engine.dispose()

    result = _alembic(url, "upgrade", "head")
    assert result.returncode == 0, result.stderr[-3000:]

    engine = create_engine(url)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT fabric_name FROM fabrics")).scalar_one() == "Existing Poplin"
        assert conn.execute(text("SELECT last_value FROM id_sequences")).scalar_one() == 1
    engine.dispose()
    assert _tables(url) >= APP_TABLES


@needs_pg
def test_types_match_on_postgresql():
    """Numeric precision must be identical on PG, not just SQLite."""
    _, url = _pg_fresh_db("mig_types")
    assert _alembic(url, "upgrade", "head").returncode == 0
    engine = create_engine(url)
    insp = inspect(engine)
    price_cols = {c["name"]: c for c in insp.get_columns("fabric_prices")}
    assert "NUMERIC(12, 2)" in str(price_cols["customer_price"]["type"]).upper()
    lot_cols = {c["name"]: c for c in insp.get_columns("inventory_lots")}
    assert "NUMERIC(12, 3)" in str(lot_cols["stock_quantity"]["type"]).upper()
    engine.dispose()


@needs_pg
def test_postgresql_downgrade_cycle():
    _, url = _pg_fresh_db("mig_cycle")
    assert _alembic(url, "upgrade", "head").returncode == 0
    assert _alembic(url, "downgrade", "base").returncode == 0
    assert (_tables(url) - {"alembic_version"}) == set()
    assert _alembic(url, "upgrade", "head").returncode == 0
