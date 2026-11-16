from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.config import get_settings
from app.database import get_db
from app.models import InventoryLot
from app.schemas import InventoryOut, InventoryUpdate
from app.services import get_variant_or_404, upsert_inventory

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("", response_model=list[InventoryOut])
def list_inventory(db: Session = Depends(get_db)):
    if not get_settings().inventory_enabled:
        raise HTTPException(status_code=404, detail="Inventory tracking is disabled")
    return db.execute(select(InventoryLot).order_by(InventoryLot.variant_id)).scalars().all()


@router.get("/{variant_pk}", response_model=InventoryOut)
def get_inventory(variant_pk: int, db: Session = Depends(get_db)):
    if not get_settings().inventory_enabled:
        raise HTTPException(status_code=404, detail="Inventory tracking is disabled")
    get_variant_or_404(db, variant_pk)
    lot = db.execute(select(InventoryLot).where(InventoryLot.variant_id == variant_pk)).scalar_one_or_none()
    if lot is None:
        raise HTTPException(status_code=404, detail="No inventory lot for this variant")
    return lot


@router.put("/{variant_pk}", response_model=InventoryOut, dependencies=[Depends(require_admin)])
def update_inventory(variant_pk: int, payload: InventoryUpdate, db: Session = Depends(get_db)):
    if not get_settings().inventory_enabled:
        raise HTTPException(status_code=404, detail="Inventory tracking is disabled")
    return upsert_inventory(
        db,
        variant_pk,
        payload.stock_quantity,
        payload.reserved_quantity,
        payload.unit,
        payload.movement_type,
        payload.reference,
    )
