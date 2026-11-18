"""Inventory endpoints.

Read this together with ``app/inventory_service.py``, which documents why
absolute read-then-write updates were replaced by atomic conditional ones.

Route summary
-------------
``GET    /inventory``                          list lots (public)
``GET    /inventory/{variant_pk}``             one lot (public)
``POST   /inventory/{variant_pk}/adjust``      relative delta        (admin)
``POST   /inventory/{variant_pk}/reserve``     create a hold         (admin)
``POST   /inventory/{variant_pk}/release``     release a hold        (admin)
``POST   /inventory/{variant_pk}/dispatch``    ship reserved goods   (admin)
``PUT    /inventory/{variant_pk}``             absolute recount      (admin)
``GET    /inventory/{variant_pk}/movements``   movement history      (public)

``PUT`` is retained for compatibility but now REFUSES to run without
``expected_stock`` or ``expected_revision`` (428), and points callers at
the delta endpoints.
"""
from __future__ import annotations

import hashlib
import json
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import inventory_service as inv
from app.auth import require_scope
from app.config import get_settings
from app.database import get_db
from app.models import InventoryLot, InventoryMovement
from app.schemas import (
    DispatchRequest,
    InventoryAdjustRequest,
    InventoryMovementOut,
    InventoryOut,
    InventoryUpdate,
    ReleaseRequest,
    ReserveRequest,
)
from app.services import get_variant_or_404

router = APIRouter(prefix="/inventory", tags=["inventory"])


def _require_inventory_enabled() -> None:
    if not get_settings().inventory_enabled:
        raise HTTPException(status_code=404, detail="Inventory tracking is disabled")


def _fingerprint(payload) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def _serialize(result) -> dict:
    """Serialise a service result to plain JSON-compatible data.

    The service returns ORM objects, which are NOT JSON serialisable
    directly - json.dumps would store "<InventoryLot object at 0x...>"
    and a replay would later return that string. Always go through the
    response schema.
    """
    return InventoryOut.model_validate(result).model_dump(mode="json")


def _replay(stored) -> Response:
    return Response(
        content=stored.response_body,
        status_code=stored.status_code,
        media_type="application/json",
        headers={"Idempotent-Replay": "true", "Idempotency-Key": stored.idempotency_key},
    )


def _wait_for_winner(db: Session, key: str, scope: str, fingerprint: str) -> Response:
    """Poll briefly for the request that owns ``key`` to finish."""
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        stored = inv.idempotency_lookup(db, key, scope, fingerprint)
        if stored is None:
            # Winner failed and released the claim: the key is free again.
            raise HTTPException(
                status_code=409,
                detail=(
                    "The original request with this Idempotency-Key did not complete; "
                    "retry the operation"
                ),
            )
        if stored.status_code != 202:
            return _replay(stored)
        db.expire_all()
        time.sleep(0.02)
    raise HTTPException(
        status_code=409,
        detail="A request with this Idempotency-Key is still in progress; retry shortly",
    )


def _idempotent(
    db: Session,
    key: str | None,
    scope: str,
    payload,
    run,
    response: Response,
):
    """Execute ``run`` at most once per Idempotency-Key.

    Replay returns the original status code and body, so a client retry after
    a network timeout cannot double-reserve fabric.
    """
    if not key:
        return run()
    if len(key) > 80:
        raise HTTPException(status_code=422, detail="Idempotency-Key must be <= 80 characters")
    fingerprint = _fingerprint(payload)
    stored = inv.idempotency_lookup(db, key, scope, fingerprint)
    # A 202 record is an in-flight CLAIM, not a completed response: another
    # request is still working. Replaying it would surface a bogus 202 to
    # the client, so wait for the winner to finish instead.
    if stored is not None and stored.status_code != 202:
        return _replay(stored)
    if stored is not None:
        return _wait_for_winner(db, key, scope, fingerprint)
    # Claim BEFORE running so a concurrent duplicate cannot also apply it.
    try:
        inv.claim_idempotency(db, key, scope, fingerprint)
    except inv.IdempotencyInFlight:
        # Winner is still working (or crashed mid-flight).
        return _wait_for_winner(db, key, scope, fingerprint)

    try:
        result = run()
    except Exception:
        # Operation failed: release the claim so the client may retry the
        # same key with a genuinely different outcome.
        inv.idempotency_release(db, key)
        raise
    body = _serialize(result)
    inv.idempotency_complete(db, key, 200, body)
    response.headers["Idempotency-Key"] = key
    return result


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
@router.get("", response_model=list[InventoryOut])
def list_inventory(db: Session = Depends(get_db)):
    _require_inventory_enabled()
    return db.execute(select(InventoryLot).order_by(InventoryLot.variant_id)).scalars().all()


@router.get("/{variant_pk}", response_model=InventoryOut)
def get_inventory(variant_pk: int, db: Session = Depends(get_db)):
    _require_inventory_enabled()
    get_variant_or_404(db, variant_pk)
    return inv.get_lot_or_404(db, variant_pk)


@router.get("/{variant_pk}/movements", response_model=list[InventoryMovementOut])
def list_movements(
    variant_pk: int,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """Append-only movement history, newest first (audit trail)."""
    _require_inventory_enabled()
    lot = inv.get_lot_or_404(db, variant_pk)
    limit = max(1, min(limit, 500))
    return (
        db.execute(
            select(InventoryMovement)
            .where(InventoryMovement.lot_id == lot.id)
            .order_by(InventoryMovement.id.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )


# ---------------------------------------------------------------------------
# Writes (admin)
# ---------------------------------------------------------------------------
@router.post(
    "/{variant_pk}/adjust",
    response_model=InventoryOut,
    dependencies=[Depends(require_scope("inventory:write"))],
)
def adjust(
    variant_pk: int,
    payload: InventoryAdjustRequest,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    """Apply a RELATIVE stock delta atomically (preferred over PUT)."""
    _require_inventory_enabled()
    get_variant_or_404(db, variant_pk)
    inv.ensure_lot(db, variant_pk, payload.unit)

    def run():
        return inv.adjust_stock(
            db,
            variant_pk,
            payload.quantity,
            payload.movement_type,
            payload.reference,
        )

    return _idempotent(
        db,
        idempotency_key,
        f"inventory:adjust:{variant_pk}",
        payload.model_dump(mode="json"),
        run,
        response,
    )


@router.post(
    "/{variant_pk}/reserve",
    response_model=InventoryOut,
    dependencies=[Depends(require_scope("inventory:write"))],
)
def reserve(
    variant_pk: int,
    payload: ReserveRequest,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    """Hold stock for an order. Conditional on availability (no overselling)."""
    _require_inventory_enabled()
    get_variant_or_404(db, variant_pk)
    inv.ensure_lot(db, variant_pk, payload.unit)

    def run():
        return inv.reserve(db, variant_pk, payload.quantity, payload.reference)

    return _idempotent(
        db,
        idempotency_key,
        f"inventory:reserve:{variant_pk}",
        payload.model_dump(mode="json"),
        run,
        response,
    )


@router.post(
    "/{variant_pk}/release",
    response_model=InventoryOut,
    dependencies=[Depends(require_scope("inventory:write"))],
)
def release(
    variant_pk: int,
    payload: ReleaseRequest,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    _require_inventory_enabled()
    get_variant_or_404(db, variant_pk)
    inv.get_lot_or_404(db, variant_pk)

    def run():
        return inv.release(db, variant_pk, payload.quantity, payload.reference)

    return _idempotent(
        db,
        idempotency_key,
        f"inventory:release:{variant_pk}",
        payload.model_dump(mode="json"),
        run,
        response,
    )


@router.post(
    "/{variant_pk}/dispatch",
    response_model=InventoryOut,
    dependencies=[Depends(require_scope("inventory:write"))],
)
def dispatch(
    variant_pk: int,
    payload: DispatchRequest,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    """Ship reserved goods: stock and reserved both decrease atomically."""
    _require_inventory_enabled()
    get_variant_or_404(db, variant_pk)
    inv.get_lot_or_404(db, variant_pk)

    def run():
        return inv.dispatch(db, variant_pk, payload.quantity, payload.reference)

    return _idempotent(
        db,
        idempotency_key,
        f"inventory:dispatch:{variant_pk}",
        payload.model_dump(mode="json"),
        run,
        response,
    )


@router.put(
    "/{variant_pk}",
    response_model=InventoryOut,
    dependencies=[Depends(require_scope("inventory:write"))],
)
def update_inventory(
    variant_pk: int,
    payload: InventoryUpdate,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    """Absolute stock correction (physical recount), guarded by optimistic
    concurrency. Requires ``expected_stock`` or ``expected_revision``.

    Prefer ``POST /inventory/{id}/adjust`` for normal movements.
    """
    _require_inventory_enabled()
    get_variant_or_404(db, variant_pk)
    inv.ensure_lot(db, variant_pk, payload.unit)

    def run():
        return inv.set_stock(
            db,
            variant_pk,
            payload.stock_quantity,
            payload.reserved_quantity,
            expected_stock=payload.expected_stock_quantity,
            expected_revision=payload.expected_revision,
            reference=payload.reference,
        )

    return _idempotent(
        db,
        idempotency_key,
        f"inventory:set:{variant_pk}",
        payload.model_dump(mode="json"),
        run,
        response,
    )
