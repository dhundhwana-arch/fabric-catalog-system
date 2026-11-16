from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import ColourOut
from app.services import colour_list

router = APIRouter(prefix="/colours", tags=["colours"])


@router.get("", response_model=list[ColourOut])
def list_colours(db: Session = Depends(get_db)):
    return colour_list(db)
