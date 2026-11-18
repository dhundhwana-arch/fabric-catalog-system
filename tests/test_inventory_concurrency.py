"""Real concurrent-session tests for inventory operations (Priority 1 / R4).

These do NOT use the FastAPI TestClient: a single shared session cannot
demonstrate concurrency. Each thread gets its own Session on its own
connection, exactly like separate HTTP requests would.
"""
from __future__ import annotations

import threading
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import models
from app.database import Base
from app.inventory_service import (
    adjust_stock,
    available_quantity,
    dispatch,
    ensure_lot,
    release,
    reserve,
    set_stock,
)
from app.models import MovementType
from app.schemas import FabricCreate, VariantCreate
from app.services import create_fabric, create_variant


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path/'inv.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    from sqlalchemy import event

    # Register BEFORE create_all: connections created by create_all are
    # returned to the pool, and threads would otherwise reuse a connection
    # that never had busy_timeout applied.
    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _rec):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=15000")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    @event.listens_for(engine, "begin")
    def _immediate(conn):
        conn.exec_driver_sql("BEGIN IMMEDIATE")

    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture()
def variant_pk(session_factory):
    db = session_factory()
    fab = create_fabric(db, FabricCreate(fabric_name="Concurrency Fabric"))
    var = create_variant(
        db,
        VariantCreate(
            fabric_id=fab.id, colour_name="Navy", colour_hex="#000080",
            customer_price="100.00",
        ),
    )
    ensure_lot(db, var.id, models.Unit.METER)
    pk = var.id
    db.close()
    return pk


def _run(worker, count, session_factory):
    errors, lock = [], threading.Lock()

    def wrapped(n):
        db = session_factory()
        try:
            worker(db, n)
        except Exception as exc:  # noqa: BLE001
            with lock:
                errors.append(f"{type(exc).__name__}: {exc}"[:160])
        finally:
            db.close()

    threads = [threading.Thread(target=wrapped, args=(n,)) for n in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return errors


def _lot(session_factory, variant_pk):
    db = session_factory()
    try:
        return db.execute(
            select(models.InventoryLot).where(models.InventoryLot.variant_id == variant_pk)
        ).scalar_one()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 1. Lost updates on relative movement (the R4 defect)
# ---------------------------------------------------------------------------
def test_concurrent_receipts_never_lose_updates(session_factory, variant_pk):
    """20 concurrent +5 receipts must total exactly 100, not 5."""
    errors = _run(
        lambda db, n: adjust_stock(db, variant_pk, Decimal("5"), MovementType.RECEIVE, f"po-{n}"),
        20,
        session_factory,
    )
    assert errors == [], errors[:3]
    lot = _lot(session_factory, variant_pk)
    assert Decimal(str(lot.stock_quantity)) == Decimal("100.000")


def test_concurrent_mixed_deltas_are_additive(session_factory, variant_pk):
    """Interleaved +/- deltas must net out exactly."""
    db = session_factory()
    adjust_stock(db, variant_pk, Decimal("100"), MovementType.RECEIVE, "seed")
    db.close()

    def worker(db, n):
        delta = Decimal("7") if n % 2 == 0 else Decimal("-3")
        adjust_stock(db, variant_pk, delta, MovementType.ADJUST, f"m{n}")

    errors = _run(worker, 20, session_factory)
    assert errors == [], errors[:3]
    # 10 * +7 = +70 ; 10 * -3 = -30  -> 100 + 40
    lot = _lot(session_factory, variant_pk)
    assert Decimal(str(lot.stock_quantity)) == Decimal("140.000")


# ---------------------------------------------------------------------------
# 2. Negative stock impossible under concurrency
# ---------------------------------------------------------------------------
def test_concurrent_withdrawals_cannot_go_negative(session_factory, variant_pk):
    """Stock 10, 20 concurrent -1 withdrawals: exactly 10 succeed."""
    db = session_factory()
    adjust_stock(db, variant_pk, Decimal("10"), MovementType.RECEIVE, "seed")
    db.close()

    from fastapi import HTTPException

    outcomes, lock = [], threading.Lock()

    def worker(db, n):
        try:
            adjust_stock(db, variant_pk, Decimal("-1"), MovementType.DISPATCH, f"w{n}")
            with lock:
                outcomes.append("ok")
        except HTTPException as exc:
            with lock:
                outcomes.append(exc.status_code)

    errors = _run(worker, 20, session_factory)
    lot = _lot(session_factory, variant_pk)
    ok = outcomes.count("ok")
    assert ok == 10, f"expected exactly 10 successes, got {ok}"
    assert outcomes.count(409) == 10
    assert Decimal(str(lot.stock_quantity)) == Decimal("0.000")
    assert Decimal(str(lot.stock_quantity)) >= 0
    assert not [e for e in errors if "HTTPException" not in e], errors[:2]


# ---------------------------------------------------------------------------
# 3. Reservation semantics
# ---------------------------------------------------------------------------
def test_concurrent_reservations_cannot_oversell(session_factory, variant_pk):
    """Stock 10, 20 concurrent reserve(1): exactly 10 hold, 10 rejected."""
    db = session_factory()
    adjust_stock(db, variant_pk, Decimal("10"), MovementType.RECEIVE, "seed")
    db.close()

    results, lock = [], threading.Lock()

    def worker(db, n):
        try:
            reserve(db, variant_pk, Decimal("1"), f"order-{n}")
            with lock:
                results.append("held")
        except Exception:  # HTTPException 409
            with lock:
                results.append("rejected")

    _run(worker, 20, session_factory)
    lot = _lot(session_factory, variant_pk)
    assert results.count("held") == 10, results
    assert results.count("rejected") == 10
    assert Decimal(str(lot.reserved_quantity)) == Decimal("10.000")
    assert available_quantity(lot) == Decimal("0.000")


def test_reserve_then_release_restores_availability(session_factory, variant_pk):
    db = session_factory()
    adjust_stock(db, variant_pk, Decimal("5"), MovementType.RECEIVE, "seed")
    reserve(db, variant_pk, Decimal("3"), "order-1")
    lot = release(db, variant_pk, Decimal("3"), "order-1")
    assert Decimal(str(lot.stock_quantity)) == Decimal("5.000")
    assert Decimal(str(lot.reserved_quantity)) == Decimal("0.000")
    db.close()


def test_dispatch_consumes_stock_and_hold(session_factory, variant_pk):
    db = session_factory()
    adjust_stock(db, variant_pk, Decimal("10"), MovementType.RECEIVE, "seed")
    reserve(db, variant_pk, Decimal("4"), "order-1")
    lot = dispatch(db, variant_pk, Decimal("4"), "order-1")
    assert Decimal(str(lot.stock_quantity)) == Decimal("6.000")
    assert Decimal(str(lot.reserved_quantity)) == Decimal("0.000")
    db.close()


def test_dispatch_beyond_reservation_rejected(session_factory, variant_pk):
    from fastapi import HTTPException

    db = session_factory()
    adjust_stock(db, variant_pk, Decimal("10"), MovementType.RECEIVE, "seed")
    reserve(db, variant_pk, Decimal("2"), "order-1")
    with pytest.raises(HTTPException) as exc:
        dispatch(db, variant_pk, Decimal("5"), "order-1")
    assert exc.value.status_code == 409
    db.close()


def test_release_more_than_reserved_rejected(session_factory, variant_pk):
    from fastapi import HTTPException

    db = session_factory()
    adjust_stock(db, variant_pk, Decimal("10"), MovementType.RECEIVE, "seed")
    reserve(db, variant_pk, Decimal("2"), "order-1")
    with pytest.raises(HTTPException) as exc:
        release(db, variant_pk, Decimal("5"), "order-1")
    assert exc.value.status_code == 409
    db.close()


# ---------------------------------------------------------------------------
# 4. Absolute writes: optimistic concurrency (the other half of R4)
# ---------------------------------------------------------------------------
def test_stale_absolute_write_is_rejected(session_factory, variant_pk):
    """Two clerks read stock=10; the second write must not silently win."""
    from fastapi import HTTPException

    reader_a, reader_b = session_factory(), session_factory()
    adjust_stock(reader_a, variant_pk, Decimal("10"), MovementType.RECEIVE, "seed")
    seen_by_a = Decimal(str(_lot(session_factory, variant_pk).stock_quantity))
    seen_by_b = seen_by_a

    # Clerk A recounts to 12 (correct).
    set_stock(reader_a, variant_pk, Decimal("12"), expected_stock=seen_by_a)
    # Clerk B, still holding the old value, tries to write 8.
    with pytest.raises(HTTPException) as exc:
        set_stock(reader_b, variant_pk, Decimal("8"), expected_stock=seen_by_b)
    assert exc.value.status_code == 409
    reader_a.close()
    reader_b.close()
    assert Decimal(str(_lot(session_factory, variant_pk).stock_quantity)) == Decimal("12.000")


def test_absolute_write_requires_expected_value(session_factory, variant_pk):
    from fastapi import HTTPException

    db = session_factory()
    with pytest.raises(HTTPException) as exc:
        set_stock(db, variant_pk, Decimal("5"))
    assert exc.value.status_code == 428
    db.close()


def test_concurrent_absolute_writes_exactly_one_wins(session_factory, variant_pk):
    """10 clerks all recount from the same revision: 1 success, 9 conflicts."""
    from fastapi import HTTPException

    db = session_factory()
    adjust_stock(db, variant_pk, Decimal("50"), MovementType.RECEIVE, "seed")
    rev = _lot(session_factory, variant_pk).revision
    db.close()

    outcomes, lock = [], threading.Lock()

    def worker(db, n):
        try:
            set_stock(db, variant_pk, Decimal(n + 1), expected_revision=rev)
            with lock:
                outcomes.append("ok")
        except HTTPException as exc:
            with lock:
                outcomes.append(exc.status_code)

    _run(worker, 10, session_factory)
    assert outcomes.count("ok") == 1, outcomes
    assert outcomes.count(409) == 9, outcomes


# ---------------------------------------------------------------------------
# 5. Movement history is preserved
# ---------------------------------------------------------------------------
def test_movement_history_records_every_change(session_factory, variant_pk):
    from sqlalchemy import func

    db = session_factory()
    adjust_stock(db, variant_pk, Decimal("20"), MovementType.RECEIVE, "po-1")
    reserve(db, variant_pk, Decimal("5"), "order-1")
    release(db, variant_pk, Decimal("2"), "order-1")
    reserve(db, variant_pk, Decimal("4"), "order-2")
    dispatch(db, variant_pk, Decimal("3"), "order-2")
    count = db.execute(
        select(func.count())
        .select_from(models.InventoryMovement)
        .where(models.InventoryMovement.lot_id == _lot(session_factory, variant_pk).id)
    ).scalar_one()
    assert count == 5

    types = [
        m.movement_type
        for m in db.execute(
            select(models.InventoryMovement).order_by(models.InventoryMovement.id)
        ).scalars()
    ]
    assert types == [
        MovementType.RECEIVE,
        MovementType.RESERVE,
        MovementType.RELEASE,
        MovementType.RESERVE,
        MovementType.DISPATCH,
    ]
    # Snapshots let the ledger be read without replaying.
    last = db.execute(
        select(models.InventoryMovement).order_by(models.InventoryMovement.id.desc()).limit(1)
    ).scalar_one()
    assert Decimal(str(last.stock_after)) == Decimal("17.000")
    # reserved: +5 (reserve) -2 (release) +4 (reserve) -3 (dispatch) = 4
    assert Decimal(str(last.reserved_after)) == Decimal("4.000")
    db.close()


def test_revision_increments_on_every_change(session_factory, variant_pk):
    db = session_factory()
    adjust_stock(db, variant_pk, Decimal("1"), MovementType.RECEIVE, "a")
    r1 = _lot(session_factory, variant_pk).revision
    adjust_stock(db, variant_pk, Decimal("1"), MovementType.RECEIVE, "b")
    r2 = _lot(session_factory, variant_pk).revision
    assert r2 == r1 + 1
    db.close()


# ---------------------------------------------------------------------------
# 6. Idempotency (service level)
# ---------------------------------------------------------------------------
def test_idempotency_key_prevents_double_reservation(session_factory, variant_pk):
    """A duplicated movement with the same key must not double-apply."""
    from fastapi import HTTPException

    db = session_factory()
    adjust_stock(db, variant_pk, Decimal("10"), MovementType.RECEIVE, "seed")
    reserve(db, variant_pk, Decimal("2"), "order-1", idempotency_key="idem-abc")
    with pytest.raises(HTTPException) as exc:
        reserve(db, variant_pk, Decimal("2"), "order-1", idempotency_key="idem-abc")
    assert exc.value.status_code == 409
    db.close()
    lot = _lot(session_factory, variant_pk)
    assert Decimal(str(lot.reserved_quantity)) == Decimal("2.000")


def test_concurrent_duplicate_idempotency_key_applies_once(session_factory, variant_pk):
    """10 threads racing with the SAME key must move stock exactly once."""
    db = session_factory()
    adjust_stock(db, variant_pk, Decimal("100"), MovementType.RECEIVE, "seed")
    db.close()

    outcomes, lock = [], threading.Lock()

    def worker(db, n):
        try:
            reserve(db, variant_pk, Decimal("5"), "order-xyz", idempotency_key="same-key-1")
            with lock:
                outcomes.append("ok")
        except Exception:
            with lock:
                outcomes.append("rejected")

    _run(worker, 10, session_factory)
    lot = _lot(session_factory, variant_pk)
    assert Decimal(str(lot.reserved_quantity)) == Decimal("5.000"), (
        f"stock moved more than once: {lot.reserved_quantity} (outcomes={outcomes})"
    )
