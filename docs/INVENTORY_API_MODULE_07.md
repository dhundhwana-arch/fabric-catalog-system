# Inventory API Contract — proposed for Module 07

**Status: PROPOSED.** The endpoints below are implemented and tested.
The *reservation semantics in §6 are NOT agreed with Module 07 yet* and
must be confirmed before Module 07 depends on them. Everything in §1–§5
is implemented behaviour; §6 lists explicitly unresolved decisions.

---

## 1. Concepts

Module 02 tracks stock per **variant** (a colour of a fabric), in a
physical unit (`METER`, `YARD`, `PIECE`, `SET`).

```
stock_quantity      physical metres on the shelf
reserved_quantity   metres held for orders, not yet shipped
available           stock_quantity - reserved_quantity   (never negative)
```

Three operations on stock, kept separate on purpose:

| Operation | Changes | Use for |
|---|---|---|
| `adjust` | `stock` by a signed delta | goods received, losses, corrections |
| `reserve` | `reserved` +q | an order takes a hold |
| `release` | `reserved` −q | hold cancelled / expired |
| `dispatch` | `stock` −q **and** `reserved` −q | goods physically shipped |
| `PUT` (set) | absolute `stock` | physical stock-take only |

`adjust` is relative and atomic, so concurrent receipts compose. `PUT` is
absolute and must carry the value previously read; a stale one is
rejected with `409` rather than silently erasing someone else's movement.

---

## 2. Authentication

Module 07 uses a **service key**, never the human admin key:

```
Authorization: Bearer <SERVICE_API_KEY for module07>
```

Required scope: `inventory:write`. A key with no granted scope receives
`403`, never implicit access.

Configured on Module 02:

```env
SERVICE_API_KEYS=module07:<long-random-secret>
SERVICE_KEY_SCOPES=module07:inventory:write
SERVICE_ALLOWED_IPS=10.0.0.0/8      # optional defence in depth
```

The key is never given to a browser and never appears in a URL.

---

## 3. Endpoints

### 3.1 Read a lot

```http
GET /api/v1/inventory/{variant_pk}
```

```json
{
  "id": 1,
  "lot_id": "FLOT-001",
  "variant_id": 1,
  "stock_quantity": "50.000",
  "reserved_quantity": "12.000",
  "unit": "METER",
  "revision": 7,
  "last_updated": "2026-11-18T15:21:01.756028Z"
}
```

`404` if the variant has never had stock recorded. Treat 404 as
"availability unknown", **not** as zero.

### 3.2 Adjust stock (relative)

```http
POST /api/v1/inventory/{variant_pk}/adjust
Idempotency-Key: <uuid>            # strongly recommended
Content-Type: application/json

{ "quantity": "25.500", "movement_type": "RECEIVE", "reference": "GRN-1042" }
```

- `quantity` is a **signed decimal**; negative reduces stock.
- `422` if quantity is zero or not numeric.
- `409` if the result would be negative (insufficient stock).
- The database evaluates `stock = stock + quantity` in one statement, so
  concurrent adjustments cannot lose updates.

### 3.3 Reserve

```http
POST /api/v1/inventory/{variant_pk}/reserve
Idempotency-Key: ord-2026-0001-line-1
Content-Type: application/json

{ "quantity": "5.000", "reference": "ORD-2026-0001" }
```

`200` → hold created. `409` → not enough available:

```json
{ "detail": "Insufficient available stock to reserve (available = stock - reserved)" }
```

**A 409 here means "do not promise this fabric".** Module 07 must surface
that to the customer rather than retrying blindly.

### 3.4 Release

```http
POST /api/v1/inventory/{variant_pk}/release
{ "quantity": "5.000", "reference": "ORD-2026-0001" }
```

`409` if releasing more than is currently held.

### 3.5 Dispatch

```http
POST /api/v1/inventory/{variant_pk}/dispatch
{ "quantity": "5.000", "reference": "ORD-2026-0001" }
```

Reduces `stock` and `reserved` together. `409` if the quantity is not
both reserved and in stock.

### 3.6 Absolute stock-take

```http
PUT /api/v1/inventory/{variant_pk}
{ "stock_quantity": "48.000", "expected_revision": 7, "reference": "stocktake-2026-11" }
```

- `428` if neither `expected_revision` nor `expected_stock_quantity` given.
- `409` if the lot changed since you read it (re-read and retry).

### 3.7 Movement history

```http
GET /api/v1/inventory/{variant_pk}/movements?limit=100
```

```json
[
  {
    "id": 12, "lot_id": 1, "movement_type": "RESERVE",
    "quantity": "5.000", "reference": "ORD-2026-0001",
    "idempotency_key": "ord-2026-0001-line-1",
    "stock_after": "50.000", "reserved_after": "17.000",
    "created_at": "2026-11-18T15:21:01.756028Z"
  }
]
```

Append-only. `stock_after` / `reserved_after` allow reconciling without
replaying the ledger.

---

## 4. Idempotency

Send `Idempotency-Key` on every mutating call. Behaviour:

| Situation | Result |
|---|---|
| First use | operation runs, response stored |
| Retry, same key + same body | **original response replayed**, `Idempotent-Replay: true` |
| Retry, same key + different body | `409` — key reuse is a client bug |
| Concurrent duplicates with one key | operation applies **once**; the others replay |

Verified: 12 concurrent identical requests applied exactly one
reservation (see audit report §4.3).

Keys are scoped per operation and variant, max 80 characters. Use a UUID
or an order-line identifier, and keep it stable across retries.

---

## 5. Error contract

| Code | Meaning for Module 07 |
|---|---|
| `401` | Missing/invalid credential — configuration problem |
| `403` | Credential valid, scope missing — configuration problem |
| `404` | Variant or lot unknown — availability unknown |
| `409` | Business conflict (insufficient stock, stale write, key reuse) |
| `422` | Malformed quantity or zero |
| `428` | Absolute write without a precondition |
| `429` | Rate limited — honour `Retry-After` |
| `503` | Limiter backend down (only if `RATE_LIMIT_FAIL_OPEN=false`) |

All errors are `{"detail": "<human readable>"}`.

---

## 6. OPEN DECISIONS — require Module 07 agreement

These are deliberately **not** implemented, because guessing another
module's requirements would be worse than leaving them explicit.

1. **Is a reservation tied to one order line, or is it a pool?**
   Today `reserve`/`release` are per-variant quantities with a free-text
   `reference`. There is no server-side link from a reservation to an
   order. If Module 07 needs "list the holds for ORD-123" or per-order
   cancellation, Module 02 needs an `order_reservations` table.
   *Proposal:* add `order_reference` + `order_line_ref` as indexed columns
   and expose `GET /inventory/reservations?order_reference=...`.
2. **Do reservations expire?** No TTL exists. An abandoned order holds
   stock forever unless Module 07 calls `release`. *Options:* (a) Module
   07 owns expiry and calls release (simplest, recommended); (b) Module 02
   expires holds after `RESERVATION_TTL_HOURS` via a scheduled job.
3. **Partial dispatch.** Today `dispatch` moves exactly what you ask for,
   up to what is reserved. Multi-line partial shipments are Module 07's
   concern; confirm whether one dispatch call per line is acceptable.
4. **Over-reservation policy.** Should a customer be allowed to reserve
   more than `available` with an "on request" flag? Current answer is no
   (409). If the business wants backorders, that is a new status, not a
   relaxed invariant.
5. **Unit conversion.** Stock is in a single unit per lot (`METER`). If
   Module 07 sells in metres while stock is held in yards, conversion must
   be defined — currently rejected rather than guessed.
6. **Who may dispatch?** `inventory:write` covers adjust, reserve,
   release *and* dispatch. If dispatch should require a stronger scope
   (e.g. `inventory:fulfil`), say so — it is a one-line change now and a
   migration later.
7. **Read access.** `GET /inventory/*` is currently public (customer-facing
   "in stock" badges). If Module 07 wants private stock visibility, that
   needs a decision on which routes become scoped.

---

## 7. Verified evidence

| Behaviour | Evidence |
|---|---|
| Concurrent reservations cannot oversell | `tests/test_inventory_concurrency.py::test_concurrent_reservations_cannot_oversell` — 20 concurrent, exactly 10 held |
| Concurrent receipts are additive | `...::test_concurrent_receipts_never_lose_updates` — 20 × +5 = exactly 100 |
| Withdrawals never go negative | `...::test_concurrent_withdrawals_cannot_go_negative` |
| Stale absolute writes rejected | `...::test_stale_absolute_write_is_rejected` |
| One key applies once | `tests/test_rate_limit_auth.py::test_concurrent_identical_idempotent_requests_apply_once` |
| Live PostgreSQL, 60 concurrent HTTP reservations | 50 held / 10 refused, reserved == stock, not oversold |
| Live PostgreSQL, 12 identical idempotent requests | applied once, 11 replays |
