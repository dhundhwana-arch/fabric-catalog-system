"""Pydantic request/response schemas.

Public responses never include supplier/procurement fields. Admin schemas
are separate and only used behind authentication.
"""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import (
    AvailabilityStatus,
    ImageType,
    MovementType,
    SourcingMethod,
    Unit,
)

HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _validate_hex(v: str) -> str:
    v = v.strip()
    if not HEX_RE.match(v):
        raise ValueError("colour_hex must be a valid hex colour, e.g. #000080")
    return v.upper()


def _validate_price(v: Decimal | None) -> Decimal | None:
    if v is not None:
        d = Decimal(str(v))
        if d < 0:
            raise ValueError("price must be >= 0")
        return d
    return v


def _validate_qty(v: Decimal) -> Decimal:
    d = Decimal(str(v))
    if d < 0:
        raise ValueError("quantity must be >= 0")
    return d


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------
class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    is_active: bool | None = None


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category_id: str
    name: str
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Fabrics
# ---------------------------------------------------------------------------
class FabricCreate(BaseModel):
    fabric_name: str = Field(min_length=1, max_length=200)
    category_id: int | None = None
    fabric_type: str | None = Field(default=None, max_length=120)
    composition: str | None = Field(default=None, max_length=200)
    description: str | None = None
    sourcing_method: SourcingMethod = SourcingMethod.BUSINESS_INVENTORY


class FabricUpdate(BaseModel):
    fabric_name: str | None = Field(default=None, min_length=1, max_length=200)
    category_id: int | None = None
    fabric_type: str | None = Field(default=None, max_length=120)
    composition: str | None = Field(default=None, max_length=200)
    description: str | None = None
    sourcing_method: SourcingMethod | None = None
    is_active: bool | None = None


class FabricOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fabric_id: str
    fabric_name: str
    category_id: int | None
    fabric_type: str | None
    composition: str | None
    description: str | None
    sourcing_method: SourcingMethod
    is_active: bool
    created_at: datetime
    updated_at: datetime


class FabricDetailOut(FabricOut):
    category: CategoryOut | None = None
    variants: list["VariantOut"] = []
    images: list["ImageOut"] = []


# ---------------------------------------------------------------------------
# Variants
# ---------------------------------------------------------------------------
class VariantCreate(BaseModel):
    fabric_id: int = Field(gt=0)
    colour_name: str = Field(min_length=1, max_length=120)
    colour_hex: str
    availability_status: AvailabilityStatus = AvailabilityStatus.UNKNOWN
    unit: Unit = Unit.METER
    customer_price: Decimal | None = None
    currency: str = "INR"

    _hex = field_validator("colour_hex", mode="before")(classmethod(lambda cls, v: _validate_hex(str(v))))
    _price = field_validator("customer_price", mode="before")(classmethod(lambda cls, v: _validate_price(v)))


class VariantUpdate(BaseModel):
    colour_name: str | None = Field(default=None, min_length=1, max_length=120)
    colour_hex: str | None = None
    availability_status: AvailabilityStatus | None = None
    unit: Unit | None = None
    customer_price: Decimal | None = None
    currency: str | None = None
    is_active: bool | None = None

    _hex = field_validator("colour_hex", mode="before")(classmethod(lambda cls, v: _validate_hex(str(v)) if v is not None else v))
    _price = field_validator("customer_price", mode="before")(classmethod(lambda cls, v: _validate_price(v)))


class VariantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    variant_id: str
    fabric_id: int
    colour_name: str
    colour_hex: str
    availability_status: AvailabilityStatus
    unit: Unit
    customer_price: Decimal | None
    currency: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Colours (derived from variants)
# ---------------------------------------------------------------------------
class ColourOut(BaseModel):
    colour_name: str
    colour_hex: str
    variant_count: int
    available_variant_count: int


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------
class ImageCreate(BaseModel):
    fabric_id: int | None = None
    variant_id: int | None = None
    image_url: str = Field(min_length=1, max_length=1024)
    storage_reference: str | None = None
    image_type: ImageType = ImageType.OTHER
    image_description: str | None = None
    is_primary: bool = False

    @field_validator("image_url")
    @classmethod
    def _url(cls, v: str) -> str:
        if not (v.startswith("http://") or v.startswith("https://") or v.startswith("/")):
            raise ValueError("image_url must be an http(s) URL or a site-relative path")
        return v


class ImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    image_id: str
    fabric_id: int | None
    variant_id: int | None
    image_url: str
    storage_reference: str | None
    image_type: ImageType
    image_description: str | None
    is_primary: bool
    created_at: datetime


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------
class PriceCreate(BaseModel):
    variant_id: int = Field(gt=0)
    customer_price: Decimal = Field(ge=0)
    currency: str = "INR"
    unit: Unit = Unit.METER


class PriceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    price_id: str
    variant_id: int
    customer_price: Decimal
    currency: str
    unit: Unit
    effective_from: datetime
    created_at: datetime


# ---------------------------------------------------------------------------
# Supplier references — ADMIN ONLY
# ---------------------------------------------------------------------------
class SupplierCreate(BaseModel):
    fabric_id: int = Field(gt=0)
    supplier_name: str = Field(min_length=1, max_length=200)
    supplier_code: str | None = None
    procurement_price: Decimal | None = None
    currency: str = "INR"
    notes: str | None = None

    _price = field_validator("procurement_price", mode="before")(classmethod(lambda cls, v: _validate_price(v)))


class SupplierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fabric_id: int
    supplier_name: str
    supplier_code: str | None
    procurement_price: Decimal | None
    currency: str
    notes: str | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------
class InventoryUpdate(BaseModel):
    stock_quantity: Decimal = Field(ge=0)
    reserved_quantity: Decimal = Field(default=Decimal("0"), ge=0)
    unit: Unit = Unit.METER
    movement_type: MovementType = MovementType.ADJUST
    reference: str | None = None

    _stock = field_validator("stock_quantity", "reserved_quantity", mode="before")(
        classmethod(lambda cls, v: _validate_qty(v))
    )

    @field_validator("reserved_quantity")
    @classmethod
    def _reserved_le_stock(cls, v: Decimal, info) -> Decimal:
        stock = info.data.get("stock_quantity")
        if stock is not None and v > stock:
            raise ValueError("reserved_quantity cannot exceed stock_quantity")
        return v


class InventoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lot_id: str
    variant_id: int
    stock_quantity: Decimal
    reserved_quantity: Decimal
    unit: Unit
    last_updated: datetime


# ---------------------------------------------------------------------------
# Common
# ---------------------------------------------------------------------------
class PaginatedResponse(BaseModel):
    items: list
    total: int
    page: int
    page_size: int
    pages: int


class MessageOut(BaseModel):
    message: str
