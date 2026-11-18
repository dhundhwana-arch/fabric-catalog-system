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
  stock. **Use the atomic reservation endpoints** (service key with
  `inventory:write` scope) —
  `POST /inventory/{pk}/reserve`, `/release`, `/dispatch`
  (`docs/INVENTORY_API_MODULE_07.md`). They are conditional single-statement
  updates, so concurrent order writers cannot oversell or lose a hold.
  Handle `409` as "do not promise this fabric".
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

Two credential types, never interchangeable:

| Credential | Who | Access |
|---|---|---|
| `ADMIN_API_KEY` | owner/staff via Module 02 admin UI | everything |
| `SERVICE_API_KEYS` | other modules, backend-to-backend | only its granted scopes |

Scopes: `catalog:read`, `catalog:write`, `inventory:read`,
`inventory:write`, `supplier:read`.

```env
SERVICE_API_KEYS=module01:<secret>,module07:<secret>
SERVICE_KEY_SCOPES=module01:catalog:read+inventory:write,module07:inventory:write
```

A service key with no scope entry gets **no** privileges. Module 01 is
deliberately **not** granted `supplier:read`. Keys are compared in
constant time and are never exposed on `/health` or in the OpenAPI schema.

**Browser clients never receive either credential.** The frontend only
calls public GETs, or Module 01's own backend.

Full contracts: [`docs/MODULE_01_INTEGRATION_CONTRACT.md`](docs/MODULE_01_INTEGRATION_CONTRACT.md)
and [`docs/INVENTORY_API_MODULE_07.md`](docs/INVENTORY_API_MODULE_07.md).

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
5. **Overselling is prevented under concurrency.** Inventory writes are
   single atomic conditional `UPDATE`s, not read-then-write:
   `reserve` is conditional on `stock - reserved >= qty`, `adjust` is
   conditional on the resulting stock staying >= 0, and a physical
   stock-take must carry `expected_revision`/`expected_stock_quantity`
   (stale writes get `409`, unguarded ones `428`).
   Verified: 20 concurrent reservations against stock 10 → exactly 10
   held; 60 concurrent over live HTTP on PostgreSQL → 50 held, 10 refused,
   never `reserved > stock`.
6. **Inventory mutations are idempotent.** Send `Idempotency-Key`; a retry
   replays the original response (`Idempotent-Replay: true`) instead of
   moving stock twice. Verified with 12 concurrent identical requests
   applying exactly one reservation.
7. **Movement history is append-only.** Every change writes an
   `inventory_movements` row with `stock_after`/`reserved_after`
   snapshots, readable at `GET /inventory/{variant_pk}/movements`.

## Module 01 integration contract

Owner-approved architecture; full contract with example payloads in
[`docs/MODULE_01_INTEGRATION_CONTRACT.md`](docs/MODULE_01_INTEGRATION_CONTRACT.md).

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

- No per-user roles or audit of *which human* changed what; the admin key
  is still a single shared secret.
- Rate limiting defaults to **process-local** (`RATE_LIMIT_BACKEND=memory`).
  Set `RATE_LIMIT_BACKEND=redis` + `REDIS_URL` for a genuinely shared limit
  across workers and replicas. The Redis path is tested against
  `fakeredis`, not a real Redis server (see audit report limitation L2).
- `id_sequences` allocation is atomic per statement; multi-process SQLite
  remains discouraged — use PostgreSQL for more than one worker.
- Reservations have no server-side link to an order and no TTL. Both are
  open decisions with Module 07 (`docs/INVENTORY_API_MODULE_07.md` §6).
- No change-notification (webhook/ETag) for catalogue updates, so a
  consumer that caches will hold stale data until it re-reads.
- Uploaded image files are not garbage-collected when their row is
  deleted.
- Local-disk image storage (Cloudinary/S3 adapter is a future swap).
- No webhooks/events yet (PROPOSED for order/stock sync).
