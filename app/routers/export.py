"""Catalogue export (CSV / JSON). Public-safe: no supplier data."""
import csv
import io
import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Fabric, FabricVariant

router = APIRouter(prefix="/export", tags=["export"])


def _rows(db: Session):
    fabrics = db.execute(select(Fabric).order_by(Fabric.fabric_id)).scalars().all()
    out = []
    for f in fabrics:
        variants = db.execute(
            select(FabricVariant).where(FabricVariant.fabric_id == f.id).order_by(FabricVariant.variant_id)
        ).scalars().all()
        for v in variants:
            out.append(
                {
                    "fabric_id": f.fabric_id,
                    "fabric_name": f.fabric_name,
                    "category": f.category.name if f.category else "",
                    "fabric_type": f.fabric_type or "",
                    "composition": f.composition or "",
                    "sourcing_method": f.sourcing_method.value,
                    "variant_id": v.variant_id,
                    "colour_name": v.colour_name,
                    "colour_hex": v.colour_hex,
                    "availability": v.availability_status.value,
                    "unit": v.unit.value,
                    "customer_price": str(v.customer_price) if v.customer_price is not None else "",
                    "currency": v.currency,
                    "is_active": str(f.is_active),
                }
            )
    return out


@router.get("")
def export(
    format: str = Query(default="json", pattern="^(json|csv)$"),
    db: Session = Depends(get_db),
):
    rows = _rows(db)
    if format == "json":
        return Response(
            content=json.dumps(rows, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=fabric_catalog.json"},
        )
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()) if rows else [])
    writer.writeheader()
    writer.writerows(rows)
    return PlainTextResponse(
        content=buf.getvalue(),
        headers={"Content-Disposition": "attachment; filename=fabric_catalog.csv"},
    )
