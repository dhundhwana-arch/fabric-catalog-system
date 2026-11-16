"""Business logic / service layer.

Kept separate from HTTP so it can be unit-tested and reused by other
modules (e.g. a future order-integration service).
"""
from __future__ import annotations

import time
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app import models
from app.id_generator import next_id
from app.models import AvailabilityStatus


def get_fabric_or_404(db: Session, fabric_id: int) -> models.Fabric:
    fabric = db.get(models.Fabric, fabric_id)
    if fabric is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Fabric not found")
    return fabric


def get_variant_or_404(db: Session, variant_id: int) -> models.FabricVariant:
    variant = db.get(models.FabricVariant, variant_id)
    if variant is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Variant not found")
    return variant


def _with_retry(db: Session, fn, attempts: int = 3):
    """Retry a create operation on IntegrityError / SQLite lock contention.

    Atomic allocation in ``id_generator`` makes a collision unlikely; this
    is the final safety net for multi-process deployments. The session MUST
    be rolled back between attempts, otherwise it stays in a failed state
    and every retry raises ``PendingRollbackError``.
    """
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except IntegrityError as exc:
            db.rollback()
            last_exc = exc
        except OperationalError as exc:
            db.rollback()
            # SQLite "database is locked" under concurrent writers.
            if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                raise
            last_exc = exc
        if attempt + 1 < attempts:
            time.sleep(0.01 * (attempt + 1))
    assert last_exc is not None
    raise last_exc


def create_category(db: Session, name: str, description: str | None) -> models.FabricCategory:
    def _do():
        cat = models.FabricCategory(
            category_id=next_id(db, "category"),
            name=name,
            description=description,
        )
        db.add(cat)
        db.commit()
        db.refresh(cat)
        return cat

    try:
        return _with_retry(db, _do)
    except IntegrityError:
        db.rollback()
        raise


def create_fabric(db: Session, data) -> models.Fabric:
    def _do():
        fabric = models.Fabric(
            fabric_id=next_id(db, "fabric"),
            fabric_name=data.fabric_name,
            category_id=data.category_id,
            fabric_type=data.fabric_type,
            composition=data.composition,
            description=data.description,
            sourcing_method=data.sourcing_method,
        )
        db.add(fabric)
        db.commit()
        db.refresh(fabric)
        return fabric

    try:
        return _with_retry(db, _do)
    except IntegrityError:
        db.rollback()
        raise


def create_variant(db: Session, data) -> models.FabricVariant:
    # Parent must exist
    get_fabric_or_404(db, data.fabric_id)

    def _do():
        variant = models.FabricVariant(
            variant_id=next_id(db, "variant"),
            fabric_id=data.fabric_id,
            colour_name=data.colour_name,
            colour_hex=data.colour_hex,
            availability_status=data.availability_status,
            unit=data.unit,
            customer_price=data.customer_price,
            currency=data.currency,
        )
        db.add(variant)
        db.flush()
        # Keep a price-history row for the initial customer price
        if data.customer_price is not None:
            db.add(
                models.FabricPrice(
                    price_id=next_id(db, "price"),
                    variant_id=variant.id,
                    customer_price=data.customer_price,
                    currency=data.currency,
                    unit=data.unit,
                )
            )
        db.commit()
        db.refresh(variant)
        return variant

    try:
        return _with_retry(db, _do)
    except IntegrityError:
        db.rollback()
        raise


def record_price(db: Session, variant_id: int, price: Decimal, currency: str, unit) -> models.FabricPrice:
    variant = get_variant_or_404(db, variant_id)
    row = models.FabricPrice(
        price_id=next_id(db, "price"),
        variant_id=variant.id,
        customer_price=price,
        currency=currency,
        unit=unit,
    )
    variant.customer_price = price
    variant.currency = currency
    variant.unit = unit
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def upsert_inventory(
    db: Session,
    variant_id: int,
    stock: Decimal,
    reserved: Decimal,
    unit,
    movement_type,
    reference: str | None,
) -> models.InventoryLot:
    variant = get_variant_or_404(db, variant_id)
    if stock < 0 or reserved < 0:
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail="Stock quantities cannot be negative")
    if reserved > stock:
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail="Reserved quantity cannot exceed stock quantity")

    def _do():
        lot = db.execute(
            select(models.InventoryLot).where(models.InventoryLot.variant_id == variant.id)
        ).scalar_one_or_none()
        if lot is None:
            lot = models.InventoryLot(
                lot_id=next_id(db, "lot"),
                variant_id=variant.id,
                stock_quantity=stock,
                reserved_quantity=reserved,
                unit=unit,
            )
            db.add(lot)
            db.flush()
        else:
            lot.stock_quantity = stock
            lot.reserved_quantity = reserved
            lot.unit = unit
        db.add(
            models.InventoryMovement(
                lot_id=lot.id,
                movement_type=movement_type,
                quantity=stock,
                reference=reference,
            )
        )
        db.commit()
        db.refresh(lot)
        return lot

    try:
        # Two concurrent first-time PUTs can both see "no lot"; the UNIQUE
        # constraint on inventory_lots.variant_id turns that race into an
        # IntegrityError which we retry as an update.
        return _with_retry(db, _do)
    except IntegrityError:
        db.rollback()
        raise


def available_quantity(lot: models.InventoryLot) -> Decimal:
    return Decimal(str(lot.stock_quantity)) - Decimal(str(lot.reserved_quantity))


def colour_list(db: Session) -> list[dict]:
    rows = db.execute(
        select(
            models.FabricVariant.colour_name,
            models.FabricVariant.colour_hex,
            func.count(models.FabricVariant.id),
            func.sum(
                case(
                    (models.FabricVariant.availability_status == AvailabilityStatus.AVAILABLE, 1),
                    else_=0,
                )
            ),
        )
        .join(models.Fabric, models.FabricVariant.fabric_id == models.Fabric.id)
        .where(
            models.FabricVariant.is_active.is_(True),
            models.Fabric.is_active.is_(True),
        )
        .group_by(models.FabricVariant.colour_name, models.FabricVariant.colour_hex)
    ).all()
    return [
        {
            "colour_name": r[0],
            "colour_hex": r[1],
            "variant_count": int(r[2]),
            "available_variant_count": int(r[3] or 0),
        }
        for r in rows
    ]
