# API Documentation

Base path: `/api/v1`. Interactive docs: `/docs` (OpenAPI) and `/redoc`.
Health: `GET /health`.

## Public (no auth)

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/fabrics` | List fabrics. Query: `search`, `fabric_id`, `category_id`, `fabric_type`, `colour`, `colour_hex`, `availability`, `min_price`, `max_price`, `include_inactive`, `sort` (name/created_at/price), `order`, `page`, `page_size` |
| GET | `/api/v1/fabrics/{pk}` | Fabric detail with variants + images |
| GET | `/api/v1/fabrics/by-code/{code}` | Detail by `FAB-…` |
| GET | `/api/v1/variants` | List variants (colour/price/availability filters) |
| GET | `/api/v1/variants/{pk}` · `/by-code/{code}` | Variant detail |
| GET | `/api/v1/categories` | Active categories |
| GET | `/api/v1/colours` | Distinct colours + counts |
| GET | `/api/v1/fabrics/{pk}/images` · `/variants/{pk}/images` | Image references |
| GET | `/api/v1/prices/variants/{pk}` | Price history |
| GET | `/api/v1/inventory` · `/inventory/{variant_pk}` | Stock levels |
| GET | `/api/v1/export?format=json\|csv` | Catalogue export |

## Admin (Bearer token required)

`POST/PUT/DELETE /api/v1/fabrics`, `/variants`, `/categories`,
`POST /api/v1/images`, `POST /api/v1/images/upload`,
`POST /api/v1/prices`, `PUT /api/v1/inventory/{variant_pk}`,
`GET/POST /api/v1/suppliers` (internal procurement data).

The admin key satisfies every scope. Backend modules should use a
**service key** with the minimum scope instead (see Authentication below).

## Inventory write endpoints (v1.1)

Prefer these over `PUT /inventory/{pk}`, which is now a guarded stock-take.

| Method | Path | Body | Conflict |
|---|---|---|---|
| POST | `/api/v1/inventory/{pk}/adjust` | `{quantity: "5.000"}` signed delta | `409` if stock would go negative |
| POST | `/api/v1/inventory/{pk}/reserve` | `{quantity: "2.000"}` | `409` if `stock - reserved < qty` |
| POST | `/api/v1/inventory/{pk}/release` | `{quantity: "2.000"}` | `409` if releasing more than held |
| POST | `/api/v1/inventory/{pk}/dispatch` | `{quantity: "2.000"}` | `409` unless reserved and in stock |
| PUT | `/api/v1/inventory/{pk}` | `{stock_quantity, expected_revision}` | `409` stale, `428` unguarded |
| GET | `/api/v1/inventory/{pk}/movements` | – | append-only ledger |

All four `POST`s accept `Idempotency-Key: <uuid>`; a retry replays the
original response with `Idempotent-Replay: true`.

## Authentication

| Credential | Env var | Grants |
|---|---|---|
| Admin (human) | `ADMIN_API_KEY` | everything |
| Service (machine) | `SERVICE_API_KEYS` + `SERVICE_KEY_SCOPES` | listed scopes only |

Scopes: `catalog:read`, `catalog:write`, `inventory:read`,
`inventory:write`, `supplier:read`. Missing credential → `401`,
insufficient scope → `403`. Keys are compared in constant time and never
appear in `/openapi.json` or `/health`.

## Rate limiting

`RATE_LIMIT_BACKEND=memory` limits **this process only** (N workers ≈ N×
the limit). `redis` shares the limit via `REDIS_URL`. Every response
carries `X-RateLimit-Scope`. Exceeding returns `429` with `Retry-After`.
`/health` is exempt.

## Examples

Create a fabric:

```bash
curl -X POST localhost:8000/api/v1/fabrics \
  -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"fabric_name":"Example Poplin","fabric_type":"Poplin"}'
```

Create a variant:

```bash
curl -X POST localhost:8000/api/v1/variants \
  -H "Authorization: Bearer $ADMIN_API_KEY" \
  -d '{"fabric_id":1,"colour_name":"Navy Blue","colour_hex":"#000080","customer_price":"450.00"}'
```

List response shape:

```json
{"items":[...],"total":1,"page":1,"page_size":20,"pages":1}
```

Errors: standard HTTP codes with `{"detail":"..."}`.

## Archive contract (verified)

`DELETE /api/v1/fabrics/{pk}` archives (`is_active=false`) and **also
archives its variants**, so archived fabrics disappear from
`/fabrics`, `/variants` and `/colours`. Pass `?include_inactive=true` on
the fabric detail/list endpoints to inspect archived records. Images,
inventory lots and price history are retained unchanged for audit.
`?hard=true` is refused with `409` while any variant or image remains.

Archive is idempotent (repeat `DELETE` returns `200`).

## Image upload contract (verified)

`POST /api/v1/images/upload` (multipart, admin only):

| Check | Failure |
|---|---|
| `Content-Type` in `ALLOWED_IMAGE_TYPES` | `415` |
| Body within `MAX_UPLOAD_BYTES` (read is capped, never fully buffered) | `413` |
| Magic bytes match declared type | `422` |
| Decodable by Pillow and ≤ 40 MP | `422` / `413` |

The stored filename is always a generated UUID + SHA-256 digest; the
client-supplied filename is discarded, so path traversal is impossible.
Files are written inside `UPLOAD_DIR` and served at `/uploads/<name>`.

## Concurrency contract (verified)

Permanent IDs are allocated with a single atomic
`UPDATE id_sequences SET last_value = last_value + 1 ... RETURNING`
statement inside the caller's transaction. `SELECT … FOR UPDATE` alone is
**not** sufficient on SQLite (it is silently ignored — no row locks), so
SQLite additionally uses `BEGIN IMMEDIATE`, WAL and `busy_timeout`.
Verified with 10 threads × 5 creates and with 6 separate OS processes.

## Rate limiting

When `RATE_LIMIT_PER_MINUTE > 0` a per-IP fixed-window limiter returns
`429`. It is in-process only; put a shared limiter at the reverse proxy
for multi-worker deployments.
