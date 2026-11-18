# Changelog

## [1.1.0] — 2026-11-18

Hardening release: closes audit residuals R1, R4, R5 and prepares the
Module 01 / Module 07 integration contracts.

### Added
- **Atomic inventory operations** (`app/inventory_service.py`):
  `POST /inventory/{pk}/adjust` (relative delta), `/reserve`, `/release`,
  `/dispatch`. All are single conditional `UPDATE`s, so concurrent writers
  cannot lose updates or oversell.
- **Optimistic concurrency** on stock-takes: `PUT /inventory/{pk}` now
  requires `expected_revision` or `expected_stock_quantity` (`428`
  otherwise) and returns `409` on a stale write.
- **Idempotent mutations**: `Idempotency-Key` header, claimed before work,
  original response replayed with `Idempotent-Replay: true`.
- `inventory_lots.revision` token; `inventory_movements.stock_after`,
  `reserved_after`, `idempotency_key`.
- `GET /inventory/{pk}/movements` — append-only audit ledger.
- **Scoped service credentials** (`SERVICE_API_KEYS`,
  `SERVICE_KEY_SCOPES`, `SERVICE_ALLOWED_IPS`) for backend-to-backend
  calls. Module 01 is not granted `supplier:read`.
- **Rate limiting backends** (`RATE_LIMIT_BACKEND`): `memory`
  (process-local), `redis` (shared), `off`. Response headers state the
  scope. Fail-open/fail-closed configurable.
- **Alembic migrations** with baseline `bf18530135e8`, verified on SQLite
  and PostgreSQL 16.2.
- Docs: `ARCHITECTURE.md`, `MIGRATIONS.md`,
  `MODULE_01_INTEGRATION_CONTRACT.md`, `INVENTORY_API_MODULE_07.md`.
- Tests: 62 → 126.

### Changed
- `PUT /inventory/{pk}` is now a guarded stock-take, not a general write
  path. `reserved_quantity` defaults to "unchanged" instead of 0.
- Production startup refuses `CORS_ORIGINS=*`.
- `app/services.py` no longer contains `upsert_inventory`; the
  implementation moved to `app/inventory_service.py`.
- `/suppliers` requires `supplier:read` (admin key still satisfies it).
- Ruff is configured with a real rule set (`E,F,W,I,UP,B,C4,SIM`) and the
  codebase passes cleanly.

### Fixed
- Idempotent replay returned `"<InventoryLot object at 0x...>"` instead of
  the original JSON body — replays now return the stored response.
- Concurrent requests sharing an `Idempotency-Key` all returned `202`
  (the in-flight claim) instead of one applying and the rest replaying.
- `_with_retry` did not roll the session back between attempts, so retries
  raised `PendingRollbackError`.
- Alembic `downgrade` left PostgreSQL ENUM types behind, breaking
  re-upgrade (PostgreSQL-only; SQLite could not reveal it).

## [1.0.1] — 2026-11-16

Independent technical verification pass. No API-breaking changes.

### Fixed
- **CRITICAL — duplicate permanent IDs under concurrency.** ID allocation
  relied on `SELECT … FOR UPDATE`, which SQLite silently ignores (no
  row-level locks). Two threads could read the same sequence value and
  produce duplicate `FAB-003` plus `id_sequences` unique violations.
  Allocation is now a single atomic
  `UPDATE id_sequences SET last_value = last_value + 1 … RETURNING`
  executed inside the caller's transaction. `services._with_retry`
  remains as a multi-process safety net.
- **SQLite write contention.** The engine now applies `BEGIN IMMEDIATE`,
  `journal_mode=WAL`, `busy_timeout=15000` and `foreign_keys=ON`, so
  concurrent writers queue instead of failing with `database is locked`.
  (Previously 9 of 10 concurrent workers failed; now 0.)
- **Archive did not cascade.** Archiving a fabric left its variants visible
  in `/variants` and `/colours`. Archiving now deactivates the variants
  too, and public variant/colour listings join on the parent's
  `is_active`. Images, inventory and price history are retained.
- **Detail responses mutated ORM state.** `GET /fabrics/{pk}` assigned a
  filtered list onto `fabric.variants`, which dirtied the session and
  leaked the filtered view into later requests. Responses are now built
  without mutating the model.
- **Duplicate inventory lots.** Two concurrent first-time
  `PUT /inventory/{pk}` calls could create two lots for one variant.
  Now enforced by a DB UNIQUE constraint on `inventory_lots.variant_id`
  with retry-as-update.
- **Hard delete with images.** `?hard=true` checked only variants, so a
  fabric with images was deleted and orphaned them. Now returns `409`.

### Security
- Production startup guard: the app refuses to start with `APP_ENV=production`
  and a placeholder or short (`<16` char) `ADMIN_API_KEY`.
- CORS no longer sets `allow_credentials=true` together with `"*"` origins.
- Implemented the previously configured-but-unused rate limiter
  (`RATE_LIMIT_PER_MINUTE`, default 120, `429` on exceed).
- Uploads are now capped while reading (never fully buffered), and are
  decoded with Pillow with a 40 MP ceiling to reject spoofed headers and
  decompression bombs. Added `pillow` to requirements.
- `.env.example` no longer ships a usable-looking default key.

### Changed
- Replaced deprecated `@app.on_event("startup")` with a `lifespan` handler.
- Test harness uses per-test data wipe instead of a long-lived outer
  transaction (which is incompatible with `BEGIN IMMEDIATE`).
- Test suite expanded from 34 to 62 tests, adding concurrency (threads +
  processes), privacy-leak key scanning, auth coverage, upload validation,
  decimal precision, price history and archive-behaviour tests.

## [1.0.0] — 2026-11-16

### Added
- Complete Fabric Catalog System (Module 02): fabrics, categories, variants,
  colours, images, price history, inventory lots/movements, supplier refs.
- Database-backed permanent IDs (FAB/FVAR/FIMG/FLOT/FCAT/FPR).
- Versioned REST API under `/api/v1` with OpenAPI docs.
- Customer catalogue + admin panel (single-page app).
- Image upload with validation; JSON/CSV export.
- Admin Bearer-token auth; supplier data hidden from public API.
- 62 automated tests (all passing).
- Docs: data model, colour system, image management, inventory rules,
  API reference, installation, integration handoff.
