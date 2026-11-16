# Integration Guide — Module 02 as Fabric Source of Truth

Module 02 owns fabric catalogue data. Other modules consume it over the
versioned REST API (`/api/v1`). All contracts below are **verified against
the implementation** unless marked PROPOSED.

## Identifiers

| Entity | Format | Example |
|---|---|---|
| Fabric | `FAB-NNN` | `FAB-001` |
| Variant | `FVAR-NNN` | `FVAR-001` |
| Image | `FIMG-NNN` | `FIMG-001` |
| Inventory lot | `FLOT-NNN` | `FLOT-001` |
| Category | `FCAT-NNN` | `FCAT-001` |

IDs are permanent, unique, never reused, and stable across updates.

## Public API (no auth required)

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/fabrics` | List with search/filter/sort/pagination |
| `GET /api/v1/fabrics/{pk}` | Fabric detail incl. variants + images |
| `GET /api/v1/fabrics/by-code/{FAB-001}` | Detail by permanent ID |
| `GET /api/v1/variants` | List variants (filter by colour/price/availability) |
| `GET /api/v1/variants/by-code/{FVAR-001}` | Variant by permanent ID |
| `GET /api/v1/categories` | Active categories |
| `GET /api/v1/colours` | Distinct colours with availability counts |
| `GET /api/v1/fabrics/{pk}/images` | Image references (URL + type + description) |
| `GET /api/v1/prices/variants/{pk}` | Price history |
| `GET /api/v1/inventory`, `GET /api/v1/inventory/{variant_pk}` | Stock levels |
| `GET /api/v1/export?format=json\|csv` | Full catalogue export |

## Admin API (Bearer `ADMIN_API_KEY` required)

`POST/PUT/DELETE /api/v1/fabrics`, `/variants`, `/categories`, `/images`,
`/prices`, `/inventory/{variant_pk}`, `/suppliers` (supplier data is
admin-only and never appears in public responses).

## Per-module consumption

- **Module 01 (main platform):** Browse `GET /api/v1/fabrics` + detail for
  catalogue pages. Show the digital-colour disclaimer.
- **Module 03 (2D designer):** Use `variant_id` (`FVAR-…`) + `colour_hex`
  as the selectable colour options; only offer variants whose
  `availability_status` is `AVAILABLE`/`ON_REQUEST`.
- **Module 04 (3D preview):** Use `image_url` + `image_type` (`TEXTURE`,
  `CLOSE_UP`) from `GET /api/v1/fabrics/{pk}/images` as texture references.
- **Module 05 (price engine):** Use `customer_price` + `unit` + `currency`
  (INR, decimal) from variants as fabric-price inputs. Module 05 owns final
  garment pricing — Module 02 only supplies the fabric component.
- **Module 06 (measurement guide):** No direct dependency.
- **Module 07 (order manager):** Persist selected `fabric_id` + `variant_id`
  on the order; check `GET /api/v1/inventory/{variant_pk}` before promising
  stock. Reservations: `PUT /api/v1/inventory/{variant_pk}` with
  `reserved_quantity` (admin token required — PROPOSED: order-service token).
- **Module 08 (admin dashboard):** Use admin endpoints for catalogue/stock
  management; export via `/api/v1/export`.

## Response example

```json
{
  "items": [{
    "id": 1, "fabric_id": "FAB-001", "fabric_name": "Example Poplin",
    "category_id": 1, "fabric_type": "Poplin", "composition": null,
    "sourcing_method": "BUSINESS_INVENTORY", "is_active": true,
    "created_at": "2026-11-16T00:00:00Z", "updated_at": "2026-11-16T00:00:00Z"
  }],
  "total": 1, "page": 1, "page_size": 20, "pages": 1
}
```

## Authentication

Public GETs are open. Mutations require `Authorization: Bearer <ADMIN_API_KEY>`.
Per-module service accounts / OAuth are PROPOSED, pending confirmation from
the other modules.

## Versioning & errors

API version is in the path (`/api/v1`). Errors use standard HTTP codes with
`{"detail": "..."}` bodies. Breaking changes will ship as `/api/v2`.

## Known limitations

- Single admin API key (no per-user roles yet).
- Local-disk image storage (Cloudinary/S3 adapter is a future swap).
- No webhooks/events yet (PROPOSED for order/stock sync).
