from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.database import get_db
from app.models import AvailabilityStatus, FabricVariant
from app.schemas import PaginatedResponse, VariantCreate, VariantOut, VariantUpdate
from app.services import create_variant, get_variant_or_404, record_price

router = APIRouter(prefix="/variants", tags=["variants"])


@router.get("", response_model=PaginatedResponse)
def list_variants(
    fabric_id: int | None = None,
    colour: str | None = None,
    colour_hex: str | None = None,
    availability: AvailabilityStatus | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    include_inactive: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    stmt = select(FabricVariant)
    if not include_inactive:
        stmt = stmt.where(FabricVariant.is_active.is_(True))
    if fabric_id:
        stmt = stmt.where(FabricVariant.fabric_id == fabric_id)
    if colour:
        stmt = stmt.where(FabricVariant.colour_name.ilike(f"%{colour}%"))
    if colour_hex:
        stmt = stmt.where(FabricVariant.colour_hex == colour_hex.upper())
    if availability:
        stmt = stmt.where(FabricVariant.availability_status == availability)
    if min_price is not None:
        stmt = stmt.where(FabricVariant.customer_price >= min_price)
    if max_price is not None:
        stmt = stmt.where(FabricVariant.customer_price <= max_price)
    stmt = stmt.order_by(FabricVariant.colour_name.asc())
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    pages = max(1, (total + page_size - 1) // page_size)
    items = db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return {
        "items": [VariantOut.model_validate(v) for v in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
    }


@router.post("", response_model=VariantOut, status_code=201, dependencies=[Depends(require_admin)])
def create(payload: VariantCreate, db: Session = Depends(get_db)):
    try:
        return create_variant(db, payload)
    except HTTPException:
        raise
    except Exception as exc:  # unique constraint on (fabric, colour, unit)
        db.rollback()
        raise HTTPException(status_code=409, detail=f"Variant already exists: {exc}") from exc


@router.get("/{variant_pk}", response_model=VariantOut)
def detail(variant_pk: int, db: Session = Depends(get_db)):
    return get_variant_or_404(db, variant_pk)


@router.get("/by-code/{variant_code}", response_model=VariantOut)
def detail_by_code(variant_code: str, db: Session = Depends(get_db)):
    v = db.execute(select(FabricVariant).where(FabricVariant.variant_id == variant_code.upper())).scalar_one_or_none()
    if v is None:
        raise HTTPException(status_code=404, detail="Variant not found")
    return v


@router.put("/{variant_pk}", response_model=VariantOut, dependencies=[Depends(require_admin)])
def update(variant_pk: int, payload: VariantUpdate, db: Session = Depends(get_db)):
    variant = get_variant_or_404(db, variant_pk)
    data = payload.model_dump(exclude_unset=True)
    price_changed = "customer_price" in data and data["customer_price"] is not None
    for k, v in data.items():
        setattr(variant, k, v)
    db.commit()
    if price_changed:
        record_price(db, variant.id, data["customer_price"], data.get("currency") or variant.currency, variant.unit)
        db.refresh(variant)
    return variant


@router.delete("/{variant_pk}", dependencies=[Depends(require_admin)])
def archive(variant_pk: int, db: Session = Depends(get_db)):
    variant = get_variant_or_404(db, variant_pk)
    variant.is_active = False
    db.commit()
    return {"message": "Variant archived"}
