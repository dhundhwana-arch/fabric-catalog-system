from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.config import get_settings
from app.database import get_db
from app.models import AvailabilityStatus, Fabric, FabricVariant
from app.schemas import FabricCreate, FabricDetailOut, FabricOut, FabricUpdate, PaginatedResponse
from app.services import create_fabric, get_fabric_or_404

router = APIRouter(prefix="/fabrics", tags=["fabrics"])


def _paginate(db: Session, stmt, page: int, page_size: int):
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    pages = max(1, (total + page_size - 1) // page_size)
    items = db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return items, total, pages


@router.get("", response_model=PaginatedResponse)
def list_fabrics(
    search: str | None = None,
    fabric_id: str | None = None,
    category_id: int | None = None,
    fabric_type: str | None = None,
    colour: str | None = None,
    colour_hex: str | None = None,
    availability: AvailabilityStatus | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    include_inactive: bool = False,
    sort: str = Query(default="name", pattern="^(name|created_at|price)$"),
    order: str = Query(default="asc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    page_size: int | None = None,
    db: Session = Depends(get_db),
):
    settings = get_settings()
    page_size = page_size or settings.default_page_size
    page_size = min(page_size, settings.max_page_size)

    stmt = select(Fabric)
    if not include_inactive:
        stmt = stmt.where(Fabric.is_active.is_(True))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(Fabric.fabric_name.ilike(like), Fabric.fabric_id.ilike(like)))
    if fabric_id:
        stmt = stmt.where(Fabric.fabric_id == fabric_id.upper())
    if category_id:
        stmt = stmt.where(Fabric.category_id == category_id)
    if fabric_type:
        stmt = stmt.where(Fabric.fabric_type == fabric_type)

    # Variant-level filters via EXISTS
    variant_filters = []
    if colour:
        variant_filters.append(FabricVariant.colour_name.ilike(f"%{colour}%"))
    if colour_hex:
        variant_filters.append(FabricVariant.colour_hex == colour_hex.upper())
    if availability:
        variant_filters.append(FabricVariant.availability_status == availability)
    if min_price is not None:
        variant_filters.append(FabricVariant.customer_price >= min_price)
    if max_price is not None:
        variant_filters.append(FabricVariant.customer_price <= max_price)
    if variant_filters:
        from sqlalchemy import exists

        stmt = stmt.where(
            exists().where(FabricVariant.fabric_id == Fabric.id, *variant_filters)
        )

    if sort == "name":
        col = Fabric.fabric_name
    elif sort == "created_at":
        col = Fabric.created_at
    else:  # price — order by cheapest variant price
        col = (
            select(func.min(FabricVariant.customer_price))
            .where(FabricVariant.fabric_id == Fabric.id)
            .scalar_subquery()
        )
    stmt = stmt.order_by(col.desc() if order == "desc" else col.asc())

    items, total, pages = _paginate(db, stmt, page, page_size)
    return {
        "items": [FabricOut.model_validate(f) for f in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
    }


@router.post("", response_model=FabricOut, status_code=201, dependencies=[Depends(require_admin)])
def create(payload: FabricCreate, db: Session = Depends(get_db)):
    if payload.category_id is not None:
        from app.models import FabricCategory

        if db.get(FabricCategory, payload.category_id) is None:
            raise HTTPException(status_code=422, detail="Category not found")
    return create_fabric(db, payload)


@router.get("/{fabric_pk}", response_model=FabricDetailOut)
def detail(fabric_pk: int, db: Session = Depends(get_db)):
    return get_fabric_or_404(db, fabric_pk)


@router.get("/by-code/{fabric_code}", response_model=FabricDetailOut)
def detail_by_code(fabric_code: str, db: Session = Depends(get_db)):
    fabric = db.execute(select(Fabric).where(Fabric.fabric_id == fabric_code.upper())).scalar_one_or_none()
    if fabric is None:
        raise HTTPException(status_code=404, detail="Fabric not found")
    return fabric


@router.put("/{fabric_pk}", response_model=FabricOut, dependencies=[Depends(require_admin)])
def update(fabric_pk: int, payload: FabricUpdate, db: Session = Depends(get_db)):
    fabric = get_fabric_or_404(db, fabric_pk)
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(fabric, k, v)
    db.commit()
    db.refresh(fabric)
    return fabric


@router.delete("/{fabric_pk}", dependencies=[Depends(require_admin)])
def archive(fabric_pk: int, hard: bool = False, db: Session = Depends(get_db)):
    """Archive (soft-delete) by default. Hard delete only if no variants exist."""
    fabric = get_fabric_or_404(db, fabric_pk)
    if hard:
        if fabric.variants:
            raise HTTPException(
                status_code=409,
                detail="Cannot hard-delete a fabric that has variants. Archive instead.",
            )
        db.delete(fabric)
        db.commit()
        return {"message": "Fabric permanently deleted"}
    fabric.is_active = False
    db.commit()
    return {"message": "Fabric archived"}
