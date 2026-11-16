from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.database import get_db
from app.models import FabricCategory
from app.schemas import CategoryCreate, CategoryOut, CategoryUpdate
from app.services import create_category

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("", response_model=list[CategoryOut])
def list_categories(include_inactive: bool = False, db: Session = Depends(get_db)):
    stmt = select(FabricCategory)
    if not include_inactive:
        stmt = stmt.where(FabricCategory.is_active.is_(True))
    return db.execute(stmt.order_by(FabricCategory.name)).scalars().all()


@router.post("", response_model=CategoryOut, status_code=201, dependencies=[Depends(require_admin)])
def create(payload: CategoryCreate, db: Session = Depends(get_db)):
    return create_category(db, payload.name, payload.description)


@router.put("/{category_pk}", response_model=CategoryOut, dependencies=[Depends(require_admin)])
def update(category_pk: int, payload: CategoryUpdate, db: Session = Depends(get_db)):
    cat = db.get(FabricCategory, category_pk)
    if cat is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Category not found")
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(cat, k, v)
    db.commit()
    db.refresh(cat)
    return cat
