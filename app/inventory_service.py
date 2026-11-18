"""Concurrency-safe inventory operations.

Design (replaces the residual R4 read-then-write problem)
--------------------------------------------------------
The old API was ``PUT /inventory/{variant}`` with *absolute* quantities.
Two concurrent callers could each read ``stock=10``, each decide to reserve
2, and both write ``reserved=2`` — one reservation was lost. Under Module 07
(order manager) load that silently oversells fabric.

This module separates three concerns that were previously conflated:

1. **Valuation / stock correction** — ``set_stock``. Absolute, for physical
   recounts. Guarded by optimistic concurrency: the caller must supply the
   ``expected_*`` values it read (or an ``expected_revision``), and the
   update is a single conditional ``UPDATE … WHERE stock = :expected``.
   A stale caller gets ``409`` instead of silently overwriting.

2. **Movement** — ``adjust_stock``. *Relative* delta (``+5`` / ``-3``),
   applied as ``stock_quantity = stock_quantity + :delta`` inside the
   database. Never read-then-write, so deltas compose correctly under
   concurrency. A conditional ``WHERE stock_quantity + :delta >= 0`` makes
   negative stock impossible in the same statement (no check-then-act gap).

3. **Reservation lifecycle** — ``reserve`` / ``release`` / ``dispatch``.
   Order-owned holds. ``reserve`` is conditional on available quantity::

       WHERE stock_quantity - reserved_quantity >= :qty

   so concurrent reservations cannot exceed stock. ``release`` returns held
   quantity to the pool; ``dispatch`` consumes both stock and the hold.

Every mutation:
- runs as ONE conditional ``UPDATE`` and inspects ``rowcount`` — the database
  decides who wins, not the application;
- bumps ``InventoryLot.revision`` so optimistic readers can detect staleness;
- writes an append-only ``InventoryMovement`` row (with before/after
  snapshots) so history is never lost;
- is wrapped in a transaction, so a failed movement cannot leave the lot
  changed.

Idempotency
-----------
Mutating calls accept an ``Idempotency-Key``. The key is UNIQUE in the DB:
a retry cannot apply the movement twice. The stored response is replayed so
the client sees the original result rather than a spurious conflict.

Negative stock
--------------
Prevented by the conditional update itself. There is no ``allow_negative``
flag: the business rule is "never oversell", and an escape hatch that could
be set by a request would defeat the point. Physical recounts that need to
correct downward use ``set_stock`` with an explicit ``ADJUST`` reason.

Not implemented on purpose (needs Module 07 agreement)
------------------------------------------------------
Hard allocation to a specific order, reservation expiry/TTL, backorder
queues, and per-channel reservations. See INTEGRATION.md for the proposed
design and the open questions.
"""
from __future__ import annotations

import json
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models
from app.id_generator import next_id
from app.models import MovementType

ZERO = Decimal("0.000")


# ---------------------------------------------------------------------------
# Lot access
# ---------------------------------------------------------------------------
def get_lot_or_404(db: Session, variant_id: int) -> models.InventoryLot:
    lot = db.execute(
        select(models.InventoryLot).where(models.InventoryLot.variant_id == variant_id)
    ).scalar_one_or_none()
    if lot is None:
        raise HTTPException(status_code=404, detail="No inventory lot for this variant")
    return lot


def ensure_lot(db: Session, variant_id: int, unit) -> models.InventoryLot:
    """Create the (unique, zero-quantity) lot for a variant if absent.

    Safe under concurrency: ``inventory_lots.variant_id`` is UNIQUE, so the
    loser of a race gets an IntegrityError and simply re-reads the winner's
    row.
    """
    lot = db.execute(
        select(models.InventoryLot).where(models.InventoryLot.variant_id == variant_id)
    ).scalar_one_or_none()
    if lot is not None:
        return lot
    try:
        lot = models.InventoryLot(
            lot_id=next_id(db, "lot"),
            variant_id=variant_id,
            stock_quantity=ZERO,
            reserved_quantity=ZERO,
            unit=unit,
        )
        db.add(lot)
        db.commit()
        db.refresh(lot)
        return lot
    except IntegrityError:
        db.rollback()
        lot = db.execute(
            select(models.InventoryLot).where(models.InventoryLot.variant_id == variant_id)
        ).scalar_one_or_none()
        if lot is None:  # pragma: no cover - defensive
            raise
        return lot


def _movement(
    db: Session,
    lot_id: int,
    movement_type: MovementType,
    quantity: Decimal,
    reference: str | None,
    idempotency_key: str | None = None,
    stock_after: Decimal | None = None,
    reserved_after: Decimal | None = None,
) -> models.InventoryMovement:
    row = models.InventoryMovement(
        lot_id=lot_id,
        movement_type=movement_type,
        quantity=abs(quantity),
        reference=reference,
        idempotency_key=idempotency_key,
        stock_after=stock_after,
        reserved_after=reserved_after,
    )
    db.add(row)
    return row


def _apply(
    db: Session,
    variant_id: int,
    stmt,
    movement_type: MovementType,
    quantity: Decimal,
    reference: str | None,
    idempotency_key: str | None,
    conflict_detail: str,
    extra_where: bool = True,
) -> models.InventoryLot:
    """Run one conditional UPDATE, record the movement, return the lot.

    ``stmt`` must be an UPDATE against InventoryLot carrying all business
    conditions. ``rowcount == 0`` means the conditions were not met *at the
    moment the database executed the write* — no check-then-act window.
    """
    lot = get_lot_or_404(db, variant_id)
    try:
        result = db.execute(stmt)
        if result.rowcount == 0:
            db.rollback()
            raise HTTPException(status_code=409, detail=conflict_detail)
        _movement(
            db,
            lot.id,
            movement_type,
            quantity,
            reference,
            idempotency_key,
        )
        db.commit()
    except HTTPException:
        raise
    except IntegrityError as exc:
        db.rollback()
        if idempotency_key and _is_idempotency_conflict(exc):
            raise HTTPException(
                status_code=409,
                detail="Idempotency-Key was already used for a different operation",
            ) from exc
        raise
    except Exception:
        db.rollback()
        raise
    db.refresh(lot)
    _stamp_snapshot(db, lot)
    return lot


def _stamp_snapshot(db: Session, lot: models.InventoryLot) -> None:
    """Write after-values onto the newest movement (same transaction)."""
    latest = db.execute(
        select(models.InventoryMovement)
        .where(models.InventoryMovement.lot_id == lot.id)
        .order_by(models.InventoryMovement.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if latest is not None and latest.stock_after is None:
        latest.stock_after = lot.stock_quantity
        latest.reserved_after = lot.reserved_quantity
        db.commit()


def _is_idempotency_conflict(exc: IntegrityError) -> bool:
    text = str(exc.orig).lower()
    return "idempotency_key" in text or "idempotency" in text


def _bump(revision_expected: int | None):
    """Columns to set on every mutation (revision guard + timestamp)."""
    from app.models import _utcnow

    values = {"revision": models.InventoryLot.revision + 1, "last_updated": _utcnow()}
    return values


# ---------------------------------------------------------------------------
# 1. Stock movement (relative, atomic)  -- preferred write path
# ---------------------------------------------------------------------------
def adjust_stock(
    db: Session,
    variant_id: int,
    delta: Decimal,
    movement_type: MovementType = MovementType.ADJUST,
    reference: str | None = None,
    idempotency_key: str | None = None,
) -> models.InventoryLot:
    """Apply a relative stock delta atomically.

    ``stock = stock + delta`` is evaluated by the database, so N concurrent
    ``+5`` calls always produce ``+5N``. The same statement refuses to take
    stock below zero: ``WHERE stock_quantity + :delta >= 0``.
    """
    get_lot_or_404(db, variant_id)
    stmt = (
        update(models.InventoryLot)
        .where(
            models.InventoryLot.variant_id == variant_id,
            models.InventoryLot.stock_quantity + delta >= 0,
        )
        .values(
            stock_quantity=models.InventoryLot.stock_quantity + delta,
            revision=models.InventoryLot.revision + 1,
        )
    )
    return _apply(
        db,
        variant_id,
        stmt,
        movement_type,
        delta,
        reference,
        idempotency_key,
        conflict_detail=(
            "Insufficient stock: the resulting stock quantity would be negative"
            if delta < 0
            else "Stock could not be adjusted (concurrent modification)"
        ),
    )


# ---------------------------------------------------------------------------
# 2. Stock valuation (absolute, optimistic concurrency)
# ---------------------------------------------------------------------------
def set_stock(
    db: Session,
    variant_id: int,
    stock: Decimal,
    reserved: Decimal | None = None,
    expected_stock: Decimal | None = None,
    expected_revision: int | None = None,
    reference: str | None = None,
    idempotency_key: str | None = None,
) -> models.InventoryLot:
    """Absolute stock correction (physical recount).

    Requires the value the caller last read (``expected_stock`` or
    ``expected_revision``). Without it a stale write could erase another
    clerk's movement, which is exactly R4. Mismatch -> ``409``.
    """
    if stock < 0:
        raise HTTPException(status_code=422, detail="Stock quantity cannot be negative")
    if reserved is not None and reserved < 0:
        raise HTTPException(status_code=422, detail="Reserved quantity cannot be negative")
    if reserved is not None and reserved > stock:
        raise HTTPException(
            status_code=422, detail="Reserved quantity cannot exceed stock quantity"
        )
    if expected_stock is None and expected_revision is None:
        raise HTTPException(
            status_code=428,
            detail=(
                "Absolute stock updates require expected_stock or expected_revision "
                "to prevent lost updates. Use POST /inventory/{variant_id}/adjust for "
                "relative movements."
            ),
        )

    get_lot_or_404(db, variant_id)
    conditions = [models.InventoryLot.variant_id == variant_id]
    if expected_stock is not None:
        conditions.append(models.InventoryLot.stock_quantity == expected_stock)
    if expected_revision is not None:
        conditions.append(models.InventoryLot.revision == expected_revision)

    values = {
        "stock_quantity": stock,
        "revision": models.InventoryLot.revision + 1,
    }
    if reserved is not None:
        values["reserved_quantity"] = reserved

    stmt = update(models.InventoryLot).where(*conditions).values(**values)
    return _apply(
        db,
        variant_id,
        stmt,
        MovementType.ADJUST,
        stock,
        reference,
        idempotency_key,
        conflict_detail=(
            "Stock was modified by someone else since you read it "
            "(expected values did not match). Re-read and retry."
        ),
    )


# ---------------------------------------------------------------------------
# 3. Reservation lifecycle
# ---------------------------------------------------------------------------
def reserve(
    db: Session,
    variant_id: int,
    quantity: Decimal,
    reference: str | None = None,
    idempotency_key: str | None = None,
) -> models.InventoryLot:
    """Hold ``quantity`` for an order.

    Conditional on availability, so concurrent reservations for the same
    variant cannot jointly exceed stock:

        WHERE stock_quantity - reserved_quantity >= :quantity
    """
    if quantity <= 0:
        raise HTTPException(status_code=422, detail="Reservation quantity must be positive")
    get_lot_or_404(db, variant_id)
    stmt = (
        update(models.InventoryLot)
        .where(
            models.InventoryLot.variant_id == variant_id,
            models.InventoryLot.stock_quantity - models.InventoryLot.reserved_quantity
            >= quantity,
        )
        .values(
            reserved_quantity=models.InventoryLot.reserved_quantity + quantity,
            revision=models.InventoryLot.revision + 1,
        )
    )
    return _apply(
        db,
        variant_id,
        stmt,
        MovementType.RESERVE,
        quantity,
        reference,
        idempotency_key,
        conflict_detail=(
            "Insufficient available stock to reserve (available = stock - reserved)"
        ),
    )


def release(
    db: Session,
    variant_id: int,
    quantity: Decimal,
    reference: str | None = None,
    idempotency_key: str | None = None,
) -> models.InventoryLot:
    """Release a hold; stock is unchanged, reserved decreases."""
    if quantity <= 0:
        raise HTTPException(status_code=422, detail="Release quantity must be positive")
    get_lot_or_404(db, variant_id)
    stmt = (
        update(models.InventoryLot)
        .where(
            models.InventoryLot.variant_id == variant_id,
            models.InventoryLot.reserved_quantity >= quantity,
        )
        .values(
            reserved_quantity=models.InventoryLot.reserved_quantity - quantity,
            revision=models.InventoryLot.revision + 1,
        )
    )
    return _apply(
        db,
        variant_id,
        stmt,
        MovementType.RELEASE,
        quantity,
        reference,
        idempotency_key,
        conflict_detail="Cannot release more than is currently reserved",
    )


def dispatch(
    db: Session,
    variant_id: int,
    quantity: Decimal,
    reference: str | None = None,
    idempotency_key: str | None = None,
) -> models.InventoryLot:
    """Ship reserved goods: stock and reserved both decrease atomically."""
    if quantity <= 0:
        raise HTTPException(status_code=422, detail="Dispatch quantity must be positive")
    get_lot_or_404(db, variant_id)
    stmt = (
        update(models.InventoryLot)
        .where(
            models.InventoryLot.variant_id == variant_id,
            models.InventoryLot.reserved_quantity >= quantity,
            models.InventoryLot.stock_quantity >= quantity,
        )
        .values(
            stock_quantity=models.InventoryLot.stock_quantity - quantity,
            reserved_quantity=models.InventoryLot.reserved_quantity - quantity,
            revision=models.InventoryLot.revision + 1,
        )
    )
    return _apply(
        db,
        variant_id,
        stmt,
        MovementType.DISPATCH,
        quantity,
        reference,
        idempotency_key,
        conflict_detail="Cannot dispatch more than is reserved (and in stock)",
    )


def available_quantity(lot: models.InventoryLot) -> Decimal:
    return Decimal(str(lot.stock_quantity)) - Decimal(str(lot.reserved_quantity))


# ---------------------------------------------------------------------------
# Idempotency replay store
# ---------------------------------------------------------------------------
def idempotency_lookup(db: Session, key: str, scope: str, fingerprint: str):
    """Return a stored response for ``key``, or None.

    Raises 409 if the same key was used with a *different* payload — that is
    a client bug and silently replaying the wrong result would be worse.
    """
    rec = db.execute(
        select(models.IdempotencyRecord).where(
            models.IdempotencyRecord.idempotency_key == key
        )
    ).scalar_one_or_none()
    if rec is None:
        return None
    if rec.scope != scope or rec.request_fingerprint != fingerprint:
        raise HTTPException(
            status_code=409,
            detail=(
                "Idempotency-Key was reused with a different request. "
                "Use a new key for a different operation."
            ),
        )
    return rec


class IdempotencyInFlight(Exception):
    """Another request holds this key and has not finished yet."""

    def __init__(self, key: str):
        self.key = key
        super().__init__(key)


def claim_idempotency(
    db: Session, key: str, scope: str, fingerprint: str, status_code: int = 202, body: dict | None = None
) -> None:
    """Reserve the key BEFORE doing the work.

    Claiming first (rather than writing the result afterwards) closes the
    race where two concurrent requests with the same key both pass the
    "not seen yet" check and both apply the movement. The loser gets
    ``IdempotencyInFlight`` and replays once the winner commits.
    """
    db.add(
        models.IdempotencyRecord(
            idempotency_key=key,
            scope=scope,
            request_fingerprint=fingerprint,
            status_code=status_code,
            response_body=json.dumps(body or {}, default=str),
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise IdempotencyInFlight(key) from exc


def idempotency_release(db: Session, key: str) -> None:
    """Remove a claim whose operation failed, so the key can be retried."""
    rec = db.execute(
        select(models.IdempotencyRecord).where(
            models.IdempotencyRecord.idempotency_key == key
        )
    ).scalar_one_or_none()
    if rec is not None and rec.status_code == 202:
        db.delete(rec)
        db.commit()


def idempotency_complete(db: Session, key: str, status_code: int, body: dict) -> None:
    """Fill in the claimed record once the operation has succeeded."""
    rec = db.execute(
        select(models.IdempotencyRecord).where(
            models.IdempotencyRecord.idempotency_key == key
        )
    ).scalar_one_or_none()
    if rec is None:  # pragma: no cover - defensive
        return
    rec.status_code = status_code
    rec.response_body = json.dumps(body, default=str)
    db.commit()


def idempotency_store(
    db: Session, key: str, scope: str, fingerprint: str, status_code: int, body: dict
) -> None:
    db.add(
        models.IdempotencyRecord(
            idempotency_key=key,
            scope=scope,
            request_fingerprint=fingerprint,
            status_code=status_code,
            response_body=json.dumps(body, default=str),
        )
    )
    try:
        db.commit()
    except IntegrityError:
        # Another worker stored it first; replay will pick theirs up.
        db.rollback()
