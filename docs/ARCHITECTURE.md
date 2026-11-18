# Architecture — Module 02 (Fabric Catalog System)

## 1. System context

Module 02 is one bounded context inside the Custom Shirt Studio ecosystem.
It owns fabric catalogue data and nothing else: no garment pricing, no
measurements, no orders.

```
                        ┌─────────────────────────────┐
                        │  Customer browser           │
                        │  (no credentials ever)      │
                        └──────────────┬──────────────┘
                                       │ public GET /api/v1/*
                                       │ (CORS allowlist)
                                       ▼
   ┌───────────────────────────────────────────────────────────────┐
   │  MODULE 01 — Customer platform (owner of the UX)              │
   │                                                                │
   │   Browser ──► Module 01 backend ──► service key ──┐            │
   └───────────────────────────────────────────────────┼───────────┘
                                                        │
   ┌────────────────────────────────────────────────────┼───────────┐
   │  MODULE 02 — Fabric Catalog System                 │           │
   │                                                     ▼           │
   │   ┌─────────────────────────────────────────────────────────┐   │
   │   │ FastAPI app (app/main.py)                               │   │
   │   │                                                          │   │
   │   │  middleware:  RateLimit ─► CORS ─► routers              │   │
   │   │                                                          │   │
   │   │  auth:  admin key (human)  |  service keys (machines)   │   │
   │   │         require_admin         require_scope(...)         │   │
   │   │                                                          │   │
   │   │  routers/                                                │   │
   │   │    categories  fabrics  variants  colours               │   │
   │   │    images      prices   inventory  suppliers  export    │   │
   │   │                                                          │   │
   │   │  services:            inventory_service:                 │   │
   │   │    catalogue CRUD       atomic conditional stock ops     │   │
   │   │    _with_retry          reserve/release/dispatch          │   │
   │   │                         idempotency claims                │   │
   │   │                                                          │   │
   │   │  id_generator: atomic UPDATE ... RETURNING (permanent IDs)│  │
   │   └───────────────┬──────────────────────┬──────────────────┘   │
   │                   │                      │                      │
   │            SQLAlchemy ORM          filesystem                  │
   │                   │                      │                      │
   │        ┌──────────▼─────────┐   ┌────────▼────────┐            │
   │        │ SQLite (dev)       │   │ UPLOAD_DIR      │            │
   │        │ PostgreSQL (prod)  │   │ /uploads/*      │            │
   │        └────────────────────┘   └─────────────────┘            │
   │                                                                │
   │   Alembic migrations ──► same scripts on SQLite + PostgreSQL   │
   └────────────────────────────────────────────────────────────────┘
                                                        ▲
                     Module 07 (orders) ──── service key ┘
                     reserve / release / dispatch only
```

## 2. Trust boundaries

| Boundary | Rule |
|---|---|
| Browser → Module 02 | Public GETs only. **No credential is ever sent to a browser.** |
| Module 01 backend → Module 02 | `SERVICE_API_KEYS`, scoped. Never the admin key. |
| Module 07 backend → Module 02 | `inventory:write` scope only. |
| Admin/staff → Module 02 | `ADMIN_API_KEY`, full access, from the admin UI only. |

Supplier and procurement data sits **behind `supplier:read`**. No public
route, export, or error message exposes it.

## 3. Data ownership

| Table | Purpose | Public? |
|---|---|---|
| `fabrics` | fabric master | yes (read) |
| `fabric_variants` | colour variant + customer price | yes (read) |
| `fabric_categories` | taxonomy | yes (read) |
| `fabric_images` | image references | yes (read) |
| `fabric_prices` | price history | yes (read) |
| `inventory_lots` | one lot per variant | yes (read) |
| `inventory_movements` | append-only ledger | yes (read) |
| `supplier_references` | supplier + procurement cost | **never** |
| `id_sequences` | permanent ID allocation | internal |
| `idempotency_records` | replay safety | internal |
| `alembic_version` | migration head | internal |

## 4. Concurrency design

Three separate mechanisms, each solving a different problem:

```
Permanent IDs          Inventory quantities        Duplicate requests
─────────────          ───────────────────        ──────────────────
UPDATE id_sequences    UPDATE inventory_lots      idempotency_records
  SET last_value =       SET stock = stock ± n       UNIQUE(key)
      last_value + 1     WHERE <business cond>       claim BEFORE work
  RETURNING last_value   (one statement)             replay stored body
        │                       │                            │
   atomic, no              no check-then-act            retry-safe,
   read-modify-write       window at all                no double-apply
```

No `SELECT ... FOR UPDATE` is used for allocation: SQLite ignores it (see
`docs/AUDIT_REPORT_MODULE_02.md`, C1).

## 5. Request lifecycle (inventory write)

```
POST /api/v1/inventory/{id}/reserve      Idempotency-Key: ord-123
        │
        ├─ require_scope("inventory:write")   → 401 / 403
        ├─ idempotency lookup                  → replay if completed
        ├─ claim key (INSERT, UNIQUE)          → in-flight? wait for winner
        ├─ ensure lot exists (INSERT ... ON CONFLICT)
        ├─ UPDATE inventory_lots
        │     SET reserved = reserved + q
        │   WHERE variant_id = :id
        │     AND stock - reserved >= q        ← rowcount 0 → 409
        ├─ INSERT inventory_movements (...)    ← append-only audit
        ├─ complete claim with response body
        └─ 200 { stock, reserved, revision }
```

Every step is in one transaction except the ID allocation, which commits
independently by design (IDs are never reused, gaps allowed).

## 6. Deployment shapes

| Shape | Database | Limiter | Notes |
|---|---|---|---|
| Local dev | SQLite | memory | zero-config, `RATE_LIMIT_BACKEND=memory` |
| Single worker | SQLite (WAL) | memory | acceptable for one tailor's shop |
| Multi-worker | **PostgreSQL** | **redis** | SQLite is single-writer; do not scale it horizontally |
| Multi-replica | PostgreSQL | redis | shared limiter required for correct limits |

## 7. What Module 02 deliberately does NOT own

- Garment pricing and quotes (Module 05).
- Orders and allocation to a specific order (Module 07).
- Customer accounts, sessions, and the storefront UI (Module 01).
- Payment, measurement, or delivery data.

See `INTEGRATION.md` for the proposed contracts and the questions that
still need Module 07's answers.
