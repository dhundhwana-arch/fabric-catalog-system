# Module 01 ⇄ Module 02 Integration Contract

**Status:** architecture approved by the owner; this document is the
implementation-facing contract. Items marked **OPEN** still need a joint
decision before Module 01 ships against them.

Division of responsibility, as directed:

1. **Module 01** owns the primary customer-facing platform.
2. **Module 02** owns fabric catalogue APIs and its own administrative UI.
3. Module 01 talks to Module 02 **backend-to-backend**.
4. **Browser clients never receive private service credentials.**
5. CORS uses an **explicit environment-configured production allowlist**.
6. Public fabric data stays separate from supplier/procurement data.

---

## 1. Credentials

Module 01 gets its own service key, configured on Module 02:

```env
# On Module 02
SERVICE_API_KEYS=module01:<long-random-secret>
SERVICE_KEY_SCOPES=module01:catalog:read+inventory:write
SERVICE_ALLOWED_IPS=10.0.0.0/8        # optional
```

```env
# On Module 01
FABRIC_CATALOG_URL=https://catalog.example.com
FABRIC_CATALOG_SERVICE_KEY=<same secret>
```

Rules:

- The admin key (`ADMIN_API_KEY`) is for humans only. Module 01 must not
  use it, and it must never reach a browser bundle.
- Module 01 is **not** granted `supplier:read`. Supplier data is
  procurement information and stays inside Module 02's admin UI.
- Rotating one key never requires rotating the other.

Scope reference:

| Scope | Grants |
|---|---|
| `catalog:read` | catalogue data (same data public GETs already expose) |
| `catalog:write` | create/update/archive catalogue records |
| `inventory:read` | stock levels |
| `inventory:write` | adjust / reserve / release / dispatch |
| `supplier:read` | supplier & procurement data — **not granted to Module 01** |

---

## 2. CORS

Development:

```env
CORS_ORIGINS=*
```

Production — **explicit allowlist**, required, or the app refuses to start:

```env
APP_ENV=production
CORS_ORIGINS=https://studio.example.com,https://www.studio.example.com
```

Wildcard plus credentials is never combined. Public GETs are the only
routes a browser should call.

---

## 3. Public surface Module 01 may call from the browser

These need no credential:

| Method | Path |
|---|---|
| GET | `/api/v1/fabrics` |
| GET | `/api/v1/fabrics/{pk}` |
| GET | `/api/v1/fabrics/by-code/{FAB-NNN}` |
| GET | `/api/v1/variants` |
| GET | `/api/v1/variants/by-code/{FVAR-NNN}` |
| GET | `/api/v1/categories` |
| GET | `/api/v1/colours` |
| GET | `/api/v1/fabrics/{pk}/images`, `/variants/{pk}/images` |
| GET | `/api/v1/prices/variants/{pk}` |
| GET | `/api/v1/inventory/{variant_pk}` |
| GET | `/api/v1/export?format=json\|csv` |

---

## 4. Contract detail

### 4.1 List envelope (stable)

```http
GET /api/v1/fabrics?search=linen&availability=AVAILABLE&page=1&page_size=20
```

```json
{
  "items": [
    {
      "id": 1,
      "fabric_id": "FAB-001",
      "fabric_name": "Example Poplin",
      "category_id": 1,
      "fabric_type": "Poplin",
      "composition": null,
      "description": null,
      "sourcing_method": "BUSINESS_INVENTORY",
      "is_active": true,
      "created_at": "2026-11-18T15:21:01.756028Z",
      "updated_at": "2026-11-18T15:21:01.756028Z"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20,
  "pages": 1
}
```

Query parameters: `search`, `fabric_id`, `category_id`, `fabric_type`,
`colour`, `colour_hex`, `availability`, `min_price`, `max_price`,
`include_inactive`, `sort` (`name|created_at|price`), `order` (`asc|desc`),
`page`, `page_size` (max 100).

### 4.2 Detail

```http
GET /api/v1/fabrics/1
```

```json
{
  "id": 1, "fabric_id": "FAB-001", "fabric_name": "Example Poplin",
  "category_id": 1, "fabric_type": "Poplin", "composition": null,
  "description": null, "sourcing_method": "BUSINESS_INVENTORY",
  "is_active": true,
  "created_at": "2026-11-18T15:21:01.756028Z",
  "updated_at": "2026-11-18T15:21:01.756028Z",
  "category": { "id": 1, "category_id": "FCAT-001", "name": "Cotton",
                "description": null, "is_active": true },
  "variants": [
    {
      "id": 1, "variant_id": "FVAR-001", "fabric_id": 1,
      "colour_name": "Navy Blue", "colour_hex": "#000080",
      "availability_status": "AVAILABLE", "unit": "METER",
      "customer_price": "450.00", "currency": "INR", "is_active": true,
      "created_at": "2026-11-18T15:21:01.756028Z",
      "updated_at": "2026-11-18T15:21:01.756028Z"
    }
  ],
  "images": [
    { "id": 1, "image_id": "FIMG-001", "fabric_id": 1, "variant_id": null,
      "image_url": "https://example.com/swatch.jpg",
      "storage_reference": null, "image_type": "SWATCH",
      "image_description": "Navy poplin swatch", "is_primary": true }
  ]
}
```

Archived variants are excluded unless `?include_inactive=true`.

### 4.3 Colours (for a colour picker)

```http
GET /api/v1/colours
```

```json
[ { "colour_name": "Navy Blue", "colour_hex": "#000080",
    "variant_count": 3, "available_count": 2 } ]
```

### 4.4 Prices

`customer_price` is a **decimal string**, INR, and is the *fabric
component only*. Module 05 owns garment pricing. Never parse it as a
float in a money calculation.

### 4.5 Stock

```http
GET /api/v1/inventory/1
```

```json
{ "id": 1, "lot_id": "FLOT-001", "variant_id": 1,
  "stock_quantity": "50.000", "reserved_quantity": "12.000",
  "unit": "METER", "revision": 7,
  "last_updated": "2026-11-18T15:21:01.756028Z" }
```

`404` = availability unknown (no lot). Do **not** render that as
"out of stock".

### 4.6 Write operations Module 01 may need

Catalogue management is done by staff in Module 02's own admin UI. If
Module 01 needs to create/archive on Module 01's behalf, request
`catalog:write`:

```http
POST /api/v1/fabrics
Authorization: Bearer <module01 service key>
Content-Type: application/json

{ "fabric_name": "New Poplin", "category_id": 1, "fabric_type": "Poplin" }
```

```json
{ "id": 7, "fabric_id": "FAB-007", "fabric_name": "New Poplin", ... }
```

---

## 5. Behaviour Module 01 must handle

| Situation | Status | Required behaviour |
|---|---|---|
| Fabric archived | `404` on detail | Drop it from saved selections; never re-resolve the ID |
| Variant archived | absent from `variants[]` | Re-prompt for colour |
| Price changed | `200` with new value | Always re-read; do not cache beyond one render |
| Rate limited | `429` + `Retry-After` | Back off; do not hammer |
| Upstream down | connection error | Serve a cached catalogue view, never a broken page |

**Archived IDs are never reused.** Module 01 may safely store
`FAB-`/`FVAR-` strings permanently.

---

## 6. Hard rules

1. Store the **permanent** ID (`FAB-…`, `FVAR-…`), not the numeric `id`,
   except as a local cache.
2. Render the digital colour notice next to any swatch:
   *"Digital colour representation may differ from the actual physical
   fabric due to lighting, display settings, and material
   characteristics."*
3. Never call `/api/v1/suppliers` from Module 01.
4. Never ship `SERVICE_API_KEY` or `ADMIN_API_KEY` to a browser.
5. Only offer variants whose `availability_status` is `AVAILABLE` or
   `ON_REQUEST`.
6. Do not treat a missing inventory lot as zero stock.

---

## 7. Verified guarantees

Each of these is asserted by an automated test (see
`tests/test_api_contract.py`):

- envelope keys are exactly `{items,total,page,page_size,pages}`;
- fabric/variant payloads contain no `supplier|procurement|wholesale|cost`
  keys;
- `/export` (JSON and CSV) contains no supplier name or procurement price;
- by-code lookups work with uppercase and lowercase input and `404` for
  unknown IDs;
- errors are always `{"detail": "..."}`;
- 401 = no/invalid credential, 403 = insufficient scope;
- inventory view exposes `revision` for optimistic concurrency.

---

## 8. OPEN questions for Module 01

1. **Who renders the catalogue UI** — Module 01's own pages calling the
   public API, or an iframe/redirect to Module 02's static frontend?
   *(Recommendation: Module 01 renders; Module 02's frontend stays as an
   independent admin/demo surface.)*
2. **Does Module 01 need write access**, or is all catalogue management
   done in Module 02's admin UI? If writes are needed, which subset?
3. **Final production origins** for `CORS_ORIGINS`.
4. **Reverse proxy depth** for `TRUSTED_PROXY_COUNT` (needed for accurate
   rate limiting by client IP).
5. **Does Module 01 cache catalogue data?** If yes, Module 02 needs a
   change-notification mechanism (webhook or `If-None-Match`/ETag); none
   exists today.
