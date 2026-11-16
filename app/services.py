"""Business logic / service layer.

Kept separate from HTTP so it can be unit-tested and reused by other
modules (e.g. a future order-integration service).
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import case, func, select
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


def create_category(db: Session, name: str, description: str | None) -> models.FabricCategory:
    cat = models.FabricCategory(
        category_id=next_id(db, "category"),
        name=name,
        description=description,
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


def create_fabric(db: Session, data) -> models.Fabric:
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


def create_variant(db: Session, data) -> models.FabricVariant:
    # Parent must exist
    get_fabric_or_404(db, data.fabric_id)
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
                price_id=next_id(db, "variant") if False else _next_price_id(db),
                variant_id=variant.id,
                customer_price=data.customer_price,
                currency=data.currency,
                unit=data.unit,
            )
        )
    db.commit()
    db.refresh(variant)
    return variant


def _next_price_id(db: Session) -> str:
    # Price IDs reuse the variant sequence space is confusing; use FPR prefix
    # via a dedicated lightweight sequence key.
    from app.models import IdSequence

    seq = db.execute(
        select(IdSequence).where(IdSequence.kind == "price").with_for_update()
    ).scalar_one_or_none()
    if seq is None:
        seq = IdSequence(kind="price", last_value=0)
        db.add(seq)
        db.flush()
    seq.last_value += 1
    db.flush()
    return f"FPR-{seq.last_value:03d}"


def record_price(db: Session, variant_id: int, price: Decimal, currency: str, unit) -> models.FabricPrice:
    variant = get_variant_or_404(db, variant_id)
    row = models.FabricPrice(
        price_id=_next_price_id(db),
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
        ).group_by(models.FabricVariant.colour_name, models.FabricVariant.colour_hex)
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
