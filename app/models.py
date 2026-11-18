"""SQLAlchemy ORM models for the Fabric Catalog System.

Money is stored as ``Numeric(12, 2)`` (decimal-safe) in INR. Floats are
never used for monetary values.
"""
from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AvailabilityStatus(str, enum.Enum):
    UNKNOWN = "UNKNOWN"
    AVAILABLE = "AVAILABLE"
    LOW_STOCK = "LOW_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    ON_REQUEST = "ON_REQUEST"
    DISCONTINUED = "DISCONTINUED"


class SourcingMethod(str, enum.Enum):
    CUSTOMER_SUPPLIED = "CUSTOMER_SUPPLIED"
    BUSINESS_INVENTORY = "BUSINESS_INVENTORY"
    SUPPLIER_SOURCED = "SUPPLIER_SOURCED"


class ImageType(str, enum.Enum):
    FRONT = "FRONT"
    CLOSE_UP = "CLOSE_UP"
    TEXTURE = "TEXTURE"
    SWATCH = "SWATCH"
    OTHER = "OTHER"


class Unit(str, enum.Enum):
    METER = "METER"
    YARD = "YARD"
    PIECE = "PIECE"
    SET = "SET"


class MovementType(str, enum.Enum):
    """Every inventory change is recorded with one of these types.

    Reservation lifecycle: ``RESERVE`` -> (``RELEASE`` | ``DISPATCH``).
    ``DISPATCH`` is the only operation that reduces ``stock_quantity`` as a
    result of an order; ``RECEIVE`` and ``ADJUST`` change stock directly.
    """

    RECEIVE = "RECEIVE"
    RESERVE = "RESERVE"
    RELEASE = "RELEASE"
    DISPATCH = "DISPATCH"
    ADJUST = "ADJUST"


# ---------------------------------------------------------------------------
# ID sequence (database-backed allocation)
# ---------------------------------------------------------------------------
class IdSequence(Base):
    __tablename__ = "id_sequences"

    kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    last_value: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


# ---------------------------------------------------------------------------
# Category
# ---------------------------------------------------------------------------
class FabricCategory(Base):
    __tablename__ = "fabric_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category_id: Mapped[str] = mapped_column(String(16), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    fabrics: Mapped[list[Fabric]] = relationship(back_populates="category", cascade="save-update, merge")


# ---------------------------------------------------------------------------
# Fabric
# ---------------------------------------------------------------------------
class Fabric(Base):
    __tablename__ = "fabrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fabric_id: Mapped[str] = mapped_column(String(16), unique=True, nullable=False, index=True)
    fabric_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("fabric_categories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    fabric_type: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    composition: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sourcing_method: Mapped[SourcingMethod] = mapped_column(
        SAEnum(SourcingMethod), default=SourcingMethod.BUSINESS_INVENTORY, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    category: Mapped[FabricCategory | None] = relationship(back_populates="fabrics")
    variants: Mapped[list[FabricVariant]] = relationship(
        back_populates="fabric", cascade="all, delete-orphan", lazy="selectin"
    )
    images: Mapped[list[FabricImage]] = relationship(
        back_populates="fabric", cascade="all, delete-orphan", lazy="selectin"
    )
    supplier_references: Mapped[list[SupplierReference]] = relationship(
        back_populates="fabric", cascade="all, delete-orphan", lazy="selectin"
    )


# ---------------------------------------------------------------------------
# Variant (fabric + colour + price + availability)
# ---------------------------------------------------------------------------
class FabricVariant(Base):
    __tablename__ = "fabric_variants"
    __table_args__ = (
        UniqueConstraint("fabric_id", "colour_hex", "unit", name="uq_variant_fabric_colour_unit"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    variant_id: Mapped[str] = mapped_column(String(16), unique=True, nullable=False, index=True)
    fabric_id: Mapped[int] = mapped_column(
        ForeignKey("fabrics.id", ondelete="CASCADE"), nullable=False, index=True
    )
    colour_name: Mapped[str] = mapped_column(String(120), nullable=False)
    colour_hex: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    availability_status: Mapped[AvailabilityStatus] = mapped_column(
        SAEnum(AvailabilityStatus), default=AvailabilityStatus.UNKNOWN, nullable=False, index=True
    )
    unit: Mapped[Unit] = mapped_column(SAEnum(Unit), default=Unit.METER, nullable=False)
    customer_price: Mapped[Numeric | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    fabric: Mapped[Fabric] = relationship(back_populates="variants")
    images: Mapped[list[FabricImage]] = relationship(
        back_populates="variant", cascade="all, delete-orphan", lazy="selectin"
    )
    prices: Mapped[list[FabricPrice]] = relationship(
        back_populates="variant", cascade="all, delete-orphan", lazy="selectin"
    )
    lots: Mapped[list[InventoryLot]] = relationship(
        back_populates="variant", cascade="all, delete-orphan", lazy="selectin"
    )


# ---------------------------------------------------------------------------
# Image
# ---------------------------------------------------------------------------
class FabricImage(Base):
    __tablename__ = "fabric_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    image_id: Mapped[str] = mapped_column(String(16), unique=True, nullable=False, index=True)
    fabric_id: Mapped[int | None] = mapped_column(
        ForeignKey("fabrics.id", ondelete="CASCADE"), nullable=True, index=True
    )
    variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("fabric_variants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    image_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    storage_reference: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    image_type: Mapped[ImageType] = mapped_column(SAEnum(ImageType), default=ImageType.OTHER, nullable=False)
    image_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    fabric: Mapped[Fabric | None] = relationship(back_populates="images")
    variant: Mapped[FabricVariant | None] = relationship(back_populates="images")


# ---------------------------------------------------------------------------
# Price history (customer-facing price per variant)
# ---------------------------------------------------------------------------
class FabricPrice(Base):
    __tablename__ = "fabric_prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    price_id: Mapped[str] = mapped_column(String(16), unique=True, nullable=False, index=True)
    variant_id: Mapped[int] = mapped_column(
        ForeignKey("fabric_variants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_price: Mapped[Numeric] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    unit: Mapped[Unit] = mapped_column(SAEnum(Unit), default=Unit.METER, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    variant: Mapped[FabricVariant] = relationship(back_populates="prices")


# ---------------------------------------------------------------------------
# Supplier reference — INTERNAL ONLY, never exposed via public API
# ---------------------------------------------------------------------------
class SupplierReference(Base):
    __tablename__ = "supplier_references"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fabric_id: Mapped[int] = mapped_column(
        ForeignKey("fabrics.id", ondelete="CASCADE"), nullable=False, index=True
    )
    supplier_name: Mapped[str] = mapped_column(String(200), nullable=False)
    supplier_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    procurement_price: Mapped[Numeric | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    fabric: Mapped[Fabric] = relationship(back_populates="supplier_references")


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------
class InventoryLot(Base):
    __tablename__ = "inventory_lots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lot_id: Mapped[str] = mapped_column(String(16), unique=True, nullable=False, index=True)
    # One inventory lot per variant: enforced in the DB so two concurrent
    # PUTs cannot create duplicate lots for the same variant.
    variant_id: Mapped[int] = mapped_column(
        ForeignKey("fabric_variants.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    stock_quantity: Mapped[Numeric] = mapped_column(Numeric(12, 3), default=0, nullable=False)
    reserved_quantity: Mapped[Numeric] = mapped_column(Numeric(12, 3), default=0, nullable=False)
    unit: Mapped[Unit] = mapped_column(SAEnum(Unit), default=Unit.METER, nullable=False)
    # Optimistic concurrency token: bumped by every atomic mutation so a
    # caller that read the lot earlier can detect that it went stale.
    revision: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    variant: Mapped[FabricVariant] = relationship(back_populates="lots")
    movements: Mapped[list[InventoryMovement]] = relationship(
        back_populates="lot", cascade="all, delete-orphan", lazy="selectin"
    )


class InventoryMovement(Base):
    __tablename__ = "inventory_movements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lot_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_lots.id", ondelete="CASCADE"), nullable=False, index=True
    )
    movement_type: Mapped[MovementType] = mapped_column(SAEnum(MovementType), nullable=False)
    quantity: Mapped[Numeric] = mapped_column(Numeric(12, 3), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    # Client-supplied idempotency key. UNIQUE, so a retried request with the
    # same key can never move stock twice; the original outcome is replayed.
    idempotency_key: Mapped[str | None] = mapped_column(
        String(80), nullable=True, unique=True, index=True
    )
    # Post-operation snapshot, so the ledger is readable without replaying.
    stock_after: Mapped[Numeric | None] = mapped_column(Numeric(12, 3), nullable=True)
    reserved_after: Mapped[Numeric | None] = mapped_column(Numeric(12, 3), nullable=True)

    lot: Mapped[InventoryLot] = relationship(back_populates="movements")


class IdempotencyRecord(Base):
    """Stored HTTP response for a replayed idempotent request.

    Kept separate from ``inventory_movements`` so the replay can return the
    exact original body/status, not just "already applied".
    """

    __tablename__ = "idempotency_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    idempotency_key: Mapped[str] = mapped_column(
        String(80), nullable=False, unique=True, index=True
    )
    scope: Mapped[str] = mapped_column(String(60), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
