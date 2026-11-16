from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.database import get_db
from app.models import FabricPrice
from app.schemas import PriceCreate, PriceOut
from app.services import record_price

router = APIRouter(prefix="/prices", tags=["prices"])


@router.post("", response_model=PriceOut, status_code=201, dependencies=[Depends(require_admin)])
def create_price(payload: PriceCreate, db: Session = Depends(get_db)):
    return record_price(db, payload.variant_id, payload.customer_price, payload.currency, payload.unit)


@router.get("/variants/{variant_pk}", response_model=list[PriceOut])
def price_history(variant_pk: int, db: Session = Depends(get_db)):
    return db.execute(
        select(FabricPrice)
        .where(FabricPrice.variant_id == variant_pk)
        .order_by(FabricPrice.effective_from.desc())
    ).scalars().all()
