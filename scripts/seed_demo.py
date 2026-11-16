"""Seed DEMO data for local development only.

WARNING: These are example records for testing the software. They are NOT
real inventory, real suppliers, or real prices. Never treat them as stock.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATABASE_URL", "sqlite:///./fabric_catalog.db")

from app.database import SessionLocal, init_db  # noqa: E402
from app.services import create_category, create_fabric, create_variant  # noqa: E402
from app.schemas import CategoryCreate, FabricCreate, VariantCreate  # noqa: E402
from app.models import AvailabilityStatus, SourcingMethod  # noqa: E402


def main():
    init_db()
    db = SessionLocal()
    try:
        cat = create_category(db, "Cotton (demo)", "Demo category for local testing only")
        fab = create_fabric(
            db,
            FabricCreate(
                fabric_name="Demo Poplin (example)",
                category_id=cat.id,
                fabric_type="Poplin",
                sourcing_method=SourcingMethod.BUSINESS_INVENTORY,
            ),
        )
        create_variant(
            db,
            VariantCreate(
                fabric_id=fab.id,
                colour_name="Navy Blue",
                colour_hex="#000080",
                customer_price="450.00",
                availability_status=AvailabilityStatus.ON_REQUEST,
            ),
        )
        print(f"Seeded demo fabric {fab.fabric_id} — example data only, not real inventory.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
