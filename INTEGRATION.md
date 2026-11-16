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
  Note this endpoint sets absolute quantities, not deltas; an order service
  must read-then-write and handle `422` (oversell) as a hard stop.
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

All mutating endpoints return `401` without a valid Bearer token (verified).
`ADMIN_API_KEY` must be a strong secret when `APP_ENV=production` — the app
refuses to start otherwise.

## Guarantees other modules may rely on (verified)

1. **Stable permanent IDs.** `FAB-…`, `FVAR-…`, `FIMG-…`, `FLOT-…`,
   `FCAT-…` are unique and never reused, including after archive or
   hard delete. Allocation is atomic and safe under concurrent writers
   (verified: 10 threads × 5 creates, 6 separate processes, and 200
   concurrent HTTP POSTs — 0 duplicates, 0 errors).
2. **No supplier data in public responses.** Supplier names, procurement
   prices and wholesale figures appear only on admin-only
   `/api/v1/suppliers` routes. Verified absent from `/fabrics`, `/variants`,
   `/colours`, detail payloads and `/export` (JSON + CSV).
3. **Decimal money.** All prices are `Numeric(12,2)` (INR). `450.10` is
   returned as `450.10`, never as a binary float approximation.
   `stock_quantity`/`reserved_quantity` are `Numeric(12,3)`.
4. **Archive is a soft delete that cascades to variants.** An archived
   fabric and its variants vanish from `/fabrics`, `/variants` and
   `/colours`; images, lots and price history are retained. Consumers that
   cache catalogue data should invalidate on archive.
5. **Overselling is prevented.** Inventory rejects negative stock and
   `reserved_quantity > stock_quantity` with `422`.

## Module 01 integration contract (PROPOSED — needs owner approval)

Module 01 is the platform shell. Proposal for how it consumes Module 02:

```http
GET /api/v1/fabrics?search=linen&availability=AVAILABLE&page=1&page_size=20
Accept: application/json
```

Response envelope (stable): `{items, total, page, page_size, pages}`.

Fields Module 01 may persist on its own records:

| Field | Type | Notes |
|---|---|---|
| `fabric_id` (permanent) | string `FAB-NNN` | use this, not the numeric `id` |
| `variant_id` (permanent) | string `FVAR-NNN` | colour choice |
| `colour_hex` | string `#RRGGBB` | for swatches; render the colour notice |
| `customer_price` | decimal string | fabric component only, INR |

Rules for Module 01:

1. Store the **permanent** ID; the numeric primary key is internal.
2. Never cache prices longer than a page render — Module 05 re-reads them.
3. Always render the digital colour disclaimer next to swatches.
4. Do not call `/api/v1/suppliers` or send the admin key from browser code;
   supplier data is server-side only.
5. Handle `404` (archived/unknown fabric) by removing the fabric from any
   saved selection — archived IDs are never reassigned to new fabrics.

Handshake items still open: service-to-service auth (single shared admin
key today), whether Module 01 hosts the catalogue UI or embeds Module 02's
static frontend, and CORS origins to whitelist.

## Versioning & errors

API version is in the path (`/api/v1`). Errors use standard HTTP codes with
`{"detail": "..."}` bodies. Breaking changes will ship as `/api/v2`.

## Known limitations

- Single admin API key (no per-user roles, no per-service tokens yet).
- Rate limiting is in-process (per worker); use a shared limiter at the
  reverse proxy for multi-worker deployments.
- `id_sequences` allocation is atomic per statement; multi-process SQLite
  remains discouraged — use PostgreSQL for more than one worker.
- Local-disk image storage (Cloudinary/S3 adapter is a future swap).
- No webhooks/events yet (PROPOSED for order/stock sync).
