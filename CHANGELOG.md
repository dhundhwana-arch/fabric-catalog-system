# Changelog

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
