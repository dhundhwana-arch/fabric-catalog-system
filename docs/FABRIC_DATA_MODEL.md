# Fabric Data Model

## Entities

| Table | Purpose | Key fields |
|---|---|---|
| `id_sequences` | DB-backed ID allocation | `kind`, `last_value` |
| `fabric_categories` | Extensible categories | `category_id` (FCAT-…), `name`, `is_active` |
| `fabrics` | Fabric product | `fabric_id` (FAB-…), `fabric_name`, `category_id`, `fabric_type`, `composition`, `description`, `sourcing_method`, `is_active` |
| `fabric_variants` | Colour + price + availability per fabric | `variant_id` (FVAR-…), `fabric_id`, `colour_name`, `colour_hex`, `availability_status`, `unit`, `customer_price`, `currency` |
| `fabric_images` | Photo references | `image_id` (FIMG-…), `fabric_id`/`variant_id`, `image_url`, `storage_reference`, `image_type`, `is_primary` |
| `fabric_prices` | Price history | `price_id` (FPR-…), `variant_id`, `customer_price`, `currency`, `unit`, `effective_from` |
| `supplier_references` | **Internal only** procurement info | `fabric_id`, `supplier_name`, `procurement_price` — never in public API |
| `inventory_lots` | Stock per variant | `lot_id` (FLOT-…), `variant_id`, `stock_quantity`, `reserved_quantity`, `unit` |
| `inventory_movements` | Stock audit trail | `lot_id`, `movement_type`, `quantity`, `reference` |

## Relationships

```
FabricCategory 1───* Fabric 1───* FabricVariant 1───* FabricImage
                                      ├───* FabricPrice
                                      ├───* InventoryLot 1───* InventoryMovement
Fabric 1───* FabricImage
Fabric 1───* SupplierReference (internal)
```

## Rules

- Money: `Numeric(12,2)` decimal, currency `INR`. Never floats.
- `composition` is stored only when verified (nullable).
- `fabric_type` (e.g. Poplin) is separate from `category` (e.g. Cotton).
- Variants are unique per (fabric, colour_hex, unit).
- Archive = `is_active=false` (soft delete). Hard delete is blocked when
  variants exist, protecting order history.
- `sourcing_method`: `CUSTOMER_SUPPLIED` | `BUSINESS_INVENTORY` | `SUPPLIER_SOURCED`.

## Identifier strategy

`id_sequences` table + `SELECT … FOR UPDATE` (PostgreSQL row lock) gives
concurrency-safe, never-reused IDs. See `app/id_generator.py`.
