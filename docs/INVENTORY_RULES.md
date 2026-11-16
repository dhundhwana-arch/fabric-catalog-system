# Inventory Rules

Inventory tracking is **optional** (`INVENTORY_ENABLED`, default on) and
per-variant via `inventory_lots` (one lot per variant).

- `stock_quantity` and `reserved_quantity` are decimals ≥ 0. Negative stock
  is rejected (422). `reserved_quantity` can never exceed `stock_quantity`.
- Available = `stock_quantity − reserved_quantity`. Reservations prevent
  overselling; every change writes an `inventory_movements` audit row
  (`RECEIVE`, `RESERVE`, `RELEASE`, `DISPATCH`, `ADJUST`).
- Availability statuses: `UNKNOWN`, `AVAILABLE`, `LOW_STOCK`,
  `OUT_OF_STOCK`, `ON_REQUEST`, `DISCONTINUED`. Never mark a fabric
  `AVAILABLE` without verified information — default is `UNKNOWN`.
- Sourcing separation: `CUSTOMER_SUPPLIED` fabric never reserves business
  stock; `SUPPLIER_SOURCED` is not "available" until confirmed and received.
- Enabling inventory is a business decision: it requires the owner to keep
  stock counts accurate. The system supports it but does not invent counts.
