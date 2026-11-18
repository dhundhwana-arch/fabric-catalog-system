"""Supplier references — ADMIN ONLY. Never exposed publicly."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_scope
from app.database import get_db
from app.models import SupplierReference
from app.schemas import SupplierCreate, SupplierOut
from app.services import get_fabric_or_404

router = APIRouter(prefix="/suppliers", tags=["suppliers"], dependencies=[Depends(require_scope("supplier:read"))])


@router.post("", response_model=SupplierOut, status_code=201)
def create(payload: SupplierCreate, db: Session = Depends(get_db)):
    get_fabric_or_404(db, payload.fabric_id)
    row = SupplierReference(
        fabric_id=payload.fabric_id,
        supplier_name=payload.supplier_name,
        supplier_code=payload.supplier_code,
        procurement_price=payload.procurement_price,
        currency=payload.currency,
        notes=payload.notes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("", response_model=list[SupplierOut])
def list_all(db: Session = Depends(get_db)):
    return db.execute(select(SupplierReference).order_by(SupplierReference.id)).scalars().all()


@router.get("/fabrics/{fabric_pk}", response_model=list[SupplierOut])
def list_for_fabric(fabric_pk: int, db: Session = Depends(get_db)):
    get_fabric_or_404(db, fabric_pk)
    return db.execute(
        select(SupplierReference).where(SupplierReference.fabric_id == fabric_pk)
    ).scalars().all()
