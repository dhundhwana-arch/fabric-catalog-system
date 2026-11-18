"""baseline schema

Revision ID: bf18530135e8
Revises:
Create Date: 2026-11-18 15:17:46.713011

ADOPTION SAFETY
---------------
Before Alembic existed, deployments created the schema with
``Base.metadata.create_all()``. Such a database already holds every table
but has no ``alembic_version`` row, so a naive ``upgrade head`` would fail
with "table already exists".

``upgrade()`` therefore creates only objects that are MISSING. On a fresh
database it builds the full schema; on a pre-Alembic database it is
effectively a no-op that stamps this revision. Nothing is dropped or
altered, so adopting an existing deployment cannot destroy data.

``downgrade()`` drops the tables this baseline owns and is intended for
disposable development databases only.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "bf18530135e8"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Reverse dependency order for downgrade.
_ALL_TABLES = [
    "idempotency_records",
    "inventory_movements",
    "inventory_lots",
    "fabric_prices",
    "fabric_images",
    "supplier_references",
    "fabric_variants",
    "fabrics",
    "id_sequences",
    "fabric_categories",
]


def _existing_tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _index_exists(table: str, index: str) -> bool:
    insp = sa.inspect(op.get_bind())
    try:
        return index in {i["name"] for i in insp.get_indexes(table)}
    except Exception:  # pragma: no cover
        return False


def upgrade() -> None:
    existing = _existing_tables()

    if "fabric_categories" not in existing:
        op.create_table('fabric_categories',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('category_id', sa.String(length=16), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
        )

    if not _index_exists("fabric_categories", "ix_fabric_categories_category_id"):
        op.create_index(op.f('ix_fabric_categories_category_id'), 'fabric_categories', ['category_id'], unique=True)
    if "id_sequences" not in existing:
        op.create_table('id_sequences',
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('last_value', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('kind')
        )

    if "idempotency_records" not in existing:
        op.create_table('idempotency_records',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('idempotency_key', sa.String(length=80), nullable=False),
        sa.Column('scope', sa.String(length=60), nullable=False),
        sa.Column('request_fingerprint', sa.String(length=64), nullable=False),
        sa.Column('status_code', sa.Integer(), nullable=False),
        sa.Column('response_body', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
        )

    if not _index_exists("idempotency_records", "ix_idempotency_records_idempotency_key"):
        op.create_index(op.f('ix_idempotency_records_idempotency_key'), 'idempotency_records', ['idempotency_key'], unique=True)
    if "fabrics" not in existing:
        op.create_table('fabrics',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('fabric_id', sa.String(length=16), nullable=False),
        sa.Column('fabric_name', sa.String(length=200), nullable=False),
        sa.Column('category_id', sa.Integer(), nullable=True),
        sa.Column('fabric_type', sa.String(length=120), nullable=True),
        sa.Column('composition', sa.String(length=200), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('sourcing_method', sa.Enum('CUSTOMER_SUPPLIED', 'BUSINESS_INVENTORY', 'SUPPLIER_SOURCED', name='sourcingmethod'), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['category_id'], ['fabric_categories.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
        )

    if not _index_exists("fabrics", "ix_fabrics_category_id"):
        op.create_index(op.f('ix_fabrics_category_id'), 'fabrics', ['category_id'], unique=False)
    if not _index_exists("fabrics", "ix_fabrics_fabric_id"):
        op.create_index(op.f('ix_fabrics_fabric_id'), 'fabrics', ['fabric_id'], unique=True)
    if not _index_exists("fabrics", "ix_fabrics_fabric_name"):
        op.create_index(op.f('ix_fabrics_fabric_name'), 'fabrics', ['fabric_name'], unique=False)
    if not _index_exists("fabrics", "ix_fabrics_fabric_type"):
        op.create_index(op.f('ix_fabrics_fabric_type'), 'fabrics', ['fabric_type'], unique=False)
    if "fabric_variants" not in existing:
        op.create_table('fabric_variants',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('variant_id', sa.String(length=16), nullable=False),
        sa.Column('fabric_id', sa.Integer(), nullable=False),
        sa.Column('colour_name', sa.String(length=120), nullable=False),
        sa.Column('colour_hex', sa.String(length=7), nullable=False),
        sa.Column('availability_status', sa.Enum('UNKNOWN', 'AVAILABLE', 'LOW_STOCK', 'OUT_OF_STOCK', 'ON_REQUEST', 'DISCONTINUED', name='availabilitystatus'), nullable=False),
        sa.Column('unit', sa.Enum('METER', 'YARD', 'PIECE', 'SET', name='unit'), nullable=False),
        sa.Column('customer_price', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['fabric_id'], ['fabrics.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('fabric_id', 'colour_hex', 'unit', name='uq_variant_fabric_colour_unit')
        )

    if not _index_exists("fabric_variants", "ix_fabric_variants_availability_status"):
        op.create_index(op.f('ix_fabric_variants_availability_status'), 'fabric_variants', ['availability_status'], unique=False)
    if not _index_exists("fabric_variants", "ix_fabric_variants_colour_hex"):
        op.create_index(op.f('ix_fabric_variants_colour_hex'), 'fabric_variants', ['colour_hex'], unique=False)
    if not _index_exists("fabric_variants", "ix_fabric_variants_fabric_id"):
        op.create_index(op.f('ix_fabric_variants_fabric_id'), 'fabric_variants', ['fabric_id'], unique=False)
    if not _index_exists("fabric_variants", "ix_fabric_variants_variant_id"):
        op.create_index(op.f('ix_fabric_variants_variant_id'), 'fabric_variants', ['variant_id'], unique=True)
    if "supplier_references" not in existing:
        op.create_table('supplier_references',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('fabric_id', sa.Integer(), nullable=False),
        sa.Column('supplier_name', sa.String(length=200), nullable=False),
        sa.Column('supplier_code', sa.String(length=120), nullable=True),
        sa.Column('procurement_price', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['fabric_id'], ['fabrics.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )

    if not _index_exists("supplier_references", "ix_supplier_references_fabric_id"):
        op.create_index(op.f('ix_supplier_references_fabric_id'), 'supplier_references', ['fabric_id'], unique=False)
    if "fabric_images" not in existing:
        op.create_table('fabric_images',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('image_id', sa.String(length=16), nullable=False),
        sa.Column('fabric_id', sa.Integer(), nullable=True),
        sa.Column('variant_id', sa.Integer(), nullable=True),
        sa.Column('image_url', sa.String(length=1024), nullable=False),
        sa.Column('storage_reference', sa.String(length=1024), nullable=True),
        sa.Column('image_type', sa.Enum('FRONT', 'CLOSE_UP', 'TEXTURE', 'SWATCH', 'OTHER', name='imagetype'), nullable=False),
        sa.Column('image_description', sa.Text(), nullable=True),
        sa.Column('is_primary', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['fabric_id'], ['fabrics.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['variant_id'], ['fabric_variants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )

    if not _index_exists("fabric_images", "ix_fabric_images_fabric_id"):
        op.create_index(op.f('ix_fabric_images_fabric_id'), 'fabric_images', ['fabric_id'], unique=False)
    if not _index_exists("fabric_images", "ix_fabric_images_image_id"):
        op.create_index(op.f('ix_fabric_images_image_id'), 'fabric_images', ['image_id'], unique=True)
    if not _index_exists("fabric_images", "ix_fabric_images_variant_id"):
        op.create_index(op.f('ix_fabric_images_variant_id'), 'fabric_images', ['variant_id'], unique=False)
    if "fabric_prices" not in existing:
        op.create_table('fabric_prices',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('price_id', sa.String(length=16), nullable=False),
        sa.Column('variant_id', sa.Integer(), nullable=False),
        sa.Column('customer_price', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('unit', sa.Enum('METER', 'YARD', 'PIECE', 'SET', name='unit'), nullable=False),
        sa.Column('effective_from', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['variant_id'], ['fabric_variants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )

    if not _index_exists("fabric_prices", "ix_fabric_prices_price_id"):
        op.create_index(op.f('ix_fabric_prices_price_id'), 'fabric_prices', ['price_id'], unique=True)
    if not _index_exists("fabric_prices", "ix_fabric_prices_variant_id"):
        op.create_index(op.f('ix_fabric_prices_variant_id'), 'fabric_prices', ['variant_id'], unique=False)
    if "inventory_lots" not in existing:
        op.create_table('inventory_lots',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('lot_id', sa.String(length=16), nullable=False),
        sa.Column('variant_id', sa.Integer(), nullable=False),
        sa.Column('stock_quantity', sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column('reserved_quantity', sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column('unit', sa.Enum('METER', 'YARD', 'PIECE', 'SET', name='unit'), nullable=False),
        sa.Column('revision', sa.Integer(), server_default='0', nullable=False),
        sa.Column('last_updated', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['variant_id'], ['fabric_variants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )

    if not _index_exists("inventory_lots", "ix_inventory_lots_lot_id"):
        op.create_index(op.f('ix_inventory_lots_lot_id'), 'inventory_lots', ['lot_id'], unique=True)
    if not _index_exists("inventory_lots", "ix_inventory_lots_variant_id"):
        op.create_index(op.f('ix_inventory_lots_variant_id'), 'inventory_lots', ['variant_id'], unique=True)
    if "inventory_movements" not in existing:
        op.create_table('inventory_movements',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('lot_id', sa.Integer(), nullable=False),
        sa.Column('movement_type', sa.Enum('RECEIVE', 'RESERVE', 'RELEASE', 'DISPATCH', 'ADJUST', name='movementtype'), nullable=False),
        sa.Column('quantity', sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column('reference', sa.String(length=200), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('idempotency_key', sa.String(length=80), nullable=True),
        sa.Column('stock_after', sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column('reserved_after', sa.Numeric(precision=12, scale=3), nullable=True),
        sa.ForeignKeyConstraint(['lot_id'], ['inventory_lots.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )

    if not _index_exists("inventory_movements", "ix_inventory_movements_idempotency_key"):
        op.create_index(op.f('ix_inventory_movements_idempotency_key'), 'inventory_movements', ['idempotency_key'], unique=True)
    if not _index_exists("inventory_movements", "ix_inventory_movements_lot_id"):
        op.create_index(op.f('ix_inventory_movements_lot_id'), 'inventory_movements', ['lot_id'], unique=False)
    # ### end Alembic commands ###


# PostgreSQL ENUM types are separate schema objects: dropping the tables
# does NOT remove them, so a downgrade/upgrade cycle would fail with
# "type already exists". SQLite has no such concept and needs no cleanup.
_PG_ENUMS = [
    "availabilitystatus",
    "imagetype",
    "movementtype",
    "sourcingmethod",
    "unit",
]


def downgrade() -> None:
    """Destructive: for disposable development databases only."""
    existing = _existing_tables()
    for table in _ALL_TABLES:
        if table in existing:
            op.drop_table(table)
    if op.get_bind().dialect.name == "postgresql":
        for enum_name in _PG_ENUMS:
            op.execute(sa.text(f'DROP TYPE IF EXISTS "{enum_name}"'))
