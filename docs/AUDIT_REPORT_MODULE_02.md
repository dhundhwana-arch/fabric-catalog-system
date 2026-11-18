# Module 02 — Independent Technical Verification Report

**Module:** 02 — Fabric Catalog System (`dhundhwana-arch/fabric-catalog-system`)
**Branch:** `arena/9fb44bec-fabric-catalog-system`
**Audited commits:** `8761caa` (implementation) → `f8c6e1c` (fixes applied during audit)
**Merge status:** **NOT MERGED.** `main` remains at `6524f79`. Owner approval required.
**Hardening release 1.1.0** (2026-11-18) — see §13 for residual-issue closure.
**Verification date:** 2026-11-16
**Tests:** 62 passed, 0 failed, 1 non-blocking warning

Every statement below was produced by running the code in this repository.
Nothing in this report is inferred from reading code alone unless explicitly
labelled "code inspection".

---

## 1. Verdict

Module 02 is **not yet production-ready at commit `8761caa`** — it contained
one critical defect that produced duplicate permanent IDs under concurrent
load, plus three high-severity security/behaviour issues.

All issues found are **now fixed and re-verified** at commit `f8c6e1c`.
On that commit I would call Module 02 **integration-ready for a single-worker
SQLite or multi-worker PostgreSQL deployment**, with the residual items in
§9 still open.

I did not merge to `main`, did not modify any other module, and did not start
another module.

---

## 2. Test results (actually executed)

```
$ python3 -m pytest tests/ -q
62 passed, 1 warning in 3.86s
```

Run three times consecutively on a clean database: `59 passed`, `59 passed`,
`62 passed` (the 62-count includes three inventory tests added later in the
audit). Final state: **62 passed, 0 failed**.

The only warning is `StarletteDeprecationWarning: Using 'httpx' with
'starlette.testclient' is deprecated; install 'httpx2' instead` — a library
notice, not a defect.

Baseline at `8761caa`: `34 passed, 4 warnings`. The additional 28 tests were
added by this audit and each one targets a specific audit question.

Live-server results (real `uvicorn` process on port 8010, not TestClient):

| Check | Result |
|---|---|
| 200 concurrent fabric creates, 10 threads over HTTP | 200 created, 200 unique, **0 errors** |
| Health endpoint | `{"status":"ok",...}` 200 |
| Unauthenticated `POST /api/v1/fabrics` | `401` |
| Static frontend `/` and `/styles.css` | `200` / `200` |
| Static traversal `/../../etc/passwd` | `404` |
| Uploaded file served at `/uploads/<name>` | `200` |
| `--path-as-is /uploads/../../app/config.py` | `404` |

---

## 3. Critical findings

### C1 — Duplicate permanent IDs under concurrency (CRITICAL, FIXED)

**Question asked:** "Do not assume SELECT FOR UPDATE provides row-level
locking in SQLite."

The assumption in `8761caa` was exactly that assumption, and it was wrong.

**Reproduced (10 threads × 5 fabric+variant creates on SQLite):**

```
IntegrityError UNIQUE constraint failed: fabrics.fabric_id   (duplicate FAB-003)
IntegrityError UNIQUE constraint failed: id_sequences.kind
RESULT: FAIL
```

**Root cause.** `id_generator.next_id()` did `SELECT … FOR UPDATE`,
incremented in Python, and flushed. SQLite parses `FOR UPDATE` and silently
ignores it — SQLite serialises *writers*, not *readers*. Worse, the
increment lived in the caller's uncommitted transaction and the
application-level lock was released before commit, so thread B read the
pre-increment value while thread A still held it uncommitted.

**Fix (`app/id_generator.py`).** Allocation is now one atomic statement:

```sql
UPDATE id_sequences SET last_value = last_value + 1 WHERE kind = :kind RETURNING last_value
```

preceded by a dialect-aware `INSERT … ON CONFLICT (kind) DO NOTHING` so the
"row does not exist" race cannot raise a unique violation. The update runs
inside the caller's transaction (so a failed request does not burn an ID) and
the database—not Python—serialises it.

**Additionally required (`app/database.py`).** With atomic SQL in place,
concurrent SQLite writers still failed: 9 of 10 workers died with
`database is locked`, because SQLite takes its write lock lazily and then
cannot upgrade it. The engine now applies, on every connection:

```
PRAGMA journal_mode=WAL
PRAGMA busy_timeout=15000
PRAGMA foreign_keys=ON
BEGIN IMMEDIATE   (via the SQLAlchemy "begin" event)
```

**Re-verified after the fix:**

| Harness | Result |
|---|---|
| 10 threads × 5 fabric+variants | 50/50 unique, 0 errors (1.3 s) |
| 10 threads, image + lot + price IDs | 10/10 unique each, 0 errors |
| 6 separate OS processes × 8 creates | 48/48 unique, 0 errors |
| 200 concurrent HTTP POSTs | 200/200 unique, 0 errors |
| 10 concurrent inventory upserts, one variant | exactly 1 lot created |
| ID after hard delete | never reuses the deleted value |

No `SELECT … FOR UPDATE` remains. It is documented in the module docstring
and in `docs/API_DOCUMENTATION.md` why it must not be reintroduced.

---

## 4. High-severity findings

### H1 — Default admin credential shipped (HIGH, FIXED)

`app/config.py` defaulted `ADMIN_API_KEY = "dev-only-change-me"` and
`.env.example` shipped the same value, so a deployed instance with an
untouched `.env.example` was trivially admin-writable.

**Fix.** Added `Settings.validate_production()`, called at import of
`app.main`, which refuses to start when `APP_ENV=production` and the key is
a placeholder (`dev-only-change-me`, `change-me`,
`replace-with-a-long-random-secret`) or shorter than 16 characters.
`.env.example` now ships `replace-with-a-long-random-secret`.

**Verified live:**

```
APP_ENV=production ADMIN_API_KEY=dev-only-change-me  -> BLOCKED: ADMIN_API_KEY must be set…
APP_ENV=production ADMIN_API_KEY=<48-char secret>    -> starts OK
```

### H2 — CORS allowed credentials with wildcard origin (HIGH, FIXED)

`allow_credentials=True` was combined with a default `CORS_ORIGINS=*`.
**Fix:** `allow_credentials = (origins != ["*"])`. A test asserts the
middleware configuration.

Verified header on the live server: `access-control-allow-origin: *` only,
no `access-control-allow-credentials`.

### H3 — Archiving a fabric did not cascade to its variants (HIGH, FIXED)

`DELETE /api/v1/fabrics/{pk}` set only `fabric.is_active = False`. Its
variants stayed visible in `/api/v1/variants` and `/api/v1/colours`, so an
archived fabric's colours were still offered to customers.

**Fix.** Archiving now deactivates the fabric's variants; variant listing
and `/colours` join on the parent fabric's `is_active`; fabric detail
filters inactive variants unless `?include_inactive=true`.

**Verified:** after archive, `/variants?fabric_id=N` returns `total: 0`,
`/colours` returns `[]`, detail returns `variants: []`, and
`?include_inactive=true` still returns both variants for admin/history.
Images, inventory lots and price history are deliberately retained.
Archive is idempotent (`200` twice).

### H4 — Detail endpoints mutated ORM state (HIGH, FIXED)

`GET /fabrics/{pk}` implemented filtering as
`fabric.variants = [v for v in fabric.variants if v.is_active]`. Because the
object is session-attached, that assignment dirtied the collection and the
filtered view leaked into later requests in the same session. Caught by
`test_archive_cascades_to_variants` returning `0` variants under
`include_inactive=true`.

**Fix.** `_detail_payload()` builds the response dict without assigning to
the model.

---

## 5. Medium-severity findings

| ID | Finding | Status |
|---|---|---|
| M1 | **Duplicate inventory lots.** Two concurrent first-time `PUT /inventory/{pk}` could each see "no lot" and insert one. `variant_id` had no uniqueness constraint. | **FIXED** — `inventory_lots.variant_id` is now `unique=True` + `index=True`; `upsert_inventory` retries as an update. Verified with 10 concurrent writers → exactly 1 lot. |
| M2 | **Hard delete orphaned images.** `?hard=true` refused only when variants existed, so a fabric with images was deleted and its image rows orphaned. | **FIXED** — returns `409` when variants *or* images exist. Covered by test. |
| M3 | **Upload validation was magic-byte only.** Forgeable header; no decode, so a decompression bomb would pass. Also `file.file.read()` buffered the whole body before the size check. | **FIXED** — read is capped at `max_upload_bytes + 1`, then Pillow decode + `verify()` + 40 MP ceiling. `pillow` added to requirements/pyproject/Dockerfile path. Verified `422` for PNG-magic-with-garbage-body, `413` for 6 MB upload. |
| M4 | **Rate limiter configured but never used.** `rate_limit_per_minute` existed in settings and did nothing. | **FIXED** — fixed-window per-IP middleware, default 120/min, `429` on exceed. Disabled in the test suite (which has its own coverage concern) via `RATE_LIMIT_PER_MINUTE=0`. |
| M5 | **`_with_retry` did not roll back** between attempts, so every retry after an `IntegrityError` raised `PendingRollbackError` — the safety net could never actually recover. | **FIXED** — `_with_retry(db, fn)` rolls back and sleeps between attempts. Applies to category, fabric, variant, price, inventory. |
| M6 | **Deprecated startup hook.** `@app.on_event("startup")` | **FIXED** — replaced with a `lifespan` handler. |

---

## 6. Verified-clean areas

These were actively tested and passed; they are not assumptions.

### 6.1 Supplier / procurement data never leaks (asked explicitly)

Seeded a supplier named `Zenith Weaving Pvt Ltd` with `procurement_price
123.45`, then scanned five public surfaces:

```
GET /api/v1/fabrics/{pk}            -> clean
GET /api/v1/fabrics/by-code/FAB-001 -> clean
GET /api/v1/variants                -> clean
GET /api/v1/export?format=json      -> clean
GET /api/v1/export?format=csv       -> clean
```

Confirmed live against `uvicorn` too (`grep -c` returned `0` for the supplier
name and `procurement` in both export formats). A generic test additionally
walks every key of `/fabrics`, `/variants`, `/colours` and asserts no key
matches `supplier|procurement|wholesale|cost|purchase`
(`test_no_supplier_keys_in_public_payloads`).

`/api/v1/suppliers` and `/api/v1/suppliers/fabrics/{pk}` return `401`
without a valid admin key, and with a *wrong* key.

### 6.2 Authentication coverage

Every mutating endpoint was called without credentials and returned `401`:
`POST/PUT/DELETE /fabrics`, `POST /categories`, `POST /variants`,
`POST /prices`, `PUT /inventory/{pk}`, `POST /images/upload`,
`GET/POST /suppliers`. Public GETs remain open by design.

### 6.3 Decimal-safe INR pricing

Prices round-trip exactly: `450.10` returns as `450.10` (not `450.09999…`), stored as
`Numeric(12,2)`. Quantity columns are `Numeric(12,3)` and return `25.500`.
Negative price → `422`. Price history appends: after three changes, four
rows exist (`FPR-001`…`FPR-004`) with unique IDs, newest first, and the
variant's `customer_price` mirrors the latest entry. All financial math is
`Decimal`, never `float`.

### 6.4 Upload / filesystem safety

| Attack | Result |
|---|---|
| No admin key | `401` |
| `text/plain` declared | `415` |
| `image/png` declared, GIF bytes | `422` |
| PNG magic, garbage body | `422` |
| 6 MB upload (limit 5 MB) | `413` |
| Filename `../../../../etc/passwd.png` | stored as `/uploads/<uuid>-<sha256>.png` |
| `--path-as-is /uploads/../../app/config.py` | `404` |

Filenames are generated (`uuid + sha256 digest`); the client filename is
discarded. Stored path is asserted to resolve to a direct child of
`UPLOAD_DIR`.

### 6.5 Inventory guardrails

Negative stock → `422`. `reserved_quantity > stock_quantity` → `422`. One
lot per variant enforced in the DB. Inventory rows survive fabric archive
(`GET /inventory/{pk}` still `200`), preserving the audit trail.

### 6.6 Default availability

New variants default to `UNKNOWN` (verified: the live create returned
`"availability_status":"UNKNOWN"` with no explicit value). Nothing marks a
fabric `AVAILABLE` automatically. Demo seed output is explicit:
`Seeded demo fabric FAB-001 — example data only, not real inventory.`

---

## 7. Documentation review (asked explicitly)

`INTEGRATION.md` and `docs/API_DOCUMENTATION.md` were checked against the
live OpenAPI schema, which matched the router set exactly (23 paths). Both
were accurate for `8761caa` but incomplete on behaviour the audit changed.
Updated:

- `INTEGRATION.md` — added a **"Guarantees other modules may rely on
  (verified)"** section, the auth guarantee, the archive-cascade behaviour,
  the inventory "absolute quantity, not delta" warning, and a full
  **Module 01 integration contract proposal** (§8 below).
- `docs/API_DOCUMENTATION.md` — added verified Archive, Image-upload,
  Concurrency and Rate-limiting contracts.
- `docs/INVENTORY_RULES.md` — documents the DB-level uniqueness constraint
  and that archive preserves lots/movements.
- `README.md` — test count and upload-validation description corrected.
- `CHANGELOG.md` — full `1.0.1` entry listing every fix with its severity.
- `.env.example` — placeholder key, `ALLOWED_IMAGE_TYPES`,
  `RATE_LIMIT_PER_MINUTE`, CORS guidance.
- Version bumped to `1.0.1` in `app/__init__.py`, `app/main.py` (FastAPI +
  `/health`), `pyproject.toml`.

No documentation claims a capability that does not exist. No breaking API
change was introduced: the archive behaviour changed, but the route,
method, status codes and response shapes did not.

---

## 8. Module 01 integration contract proposal

Full text in `INTEGRATION.md`; summary:

- **Envelope:** `{items, total, page, page_size, pages}` — stable.
- **Identify by permanent ID** (`FAB-NNN`, `FVAR-NNN`), not the numeric
  primary key. IDs are never reassigned, so Module 01 may safely persist
  them.
- **Fields Module 01 persists:** `fabric_id`, `variant_id`, `colour_hex`,
  `customer_price` (decimal string, INR, fabric component only — Module 05
  owns garment pricing).
- **Module 01 must:** render the digital-colour disclaimer beside swatches;
  never call `/api/v1/suppliers` or hold the admin key in browser code;
  treat `404` on a saved fabric as "archived — drop from selection";
  re-read prices per render rather than caching.
- **Open handshake items** (need owner decision, not code):
  1. service-to-service auth — today one shared admin key, no per-service tokens;
  2. whether Module 01 hosts the catalogue UI or embeds Module 02's static frontend;
  3. final CORS origin allowlist for production.

---

## 9. Residual issues (status after hardening pass, 2026-11-18)

> **Update:** R1, R4 and R5 have since been addressed in the hardening
> release. See §13 for the closure report. The table below is retained as
> the original audit snapshot.



| ID | Severity | Issue | Note |
|---|---|---|---|
| R1 | Medium | **In-process rate limiter only.** Per-worker memory; resets on restart; not shared across workers. | Needs a reverse-proxy or Redis limiter for multi-worker production. Documented, not solved. |
| R2 | Medium | **Single shared admin key**, no roles or audit of who wrote what. | Deliberate scope boundary; recommended before multi-staff use. |
| R3 | Medium | **`/suppliers` has no delete/update endpoint** — supplier rows can be created and read but not corrected or removed. | Implement with Module 08 admin work; not required for integration. |
| R4 | Medium | **`PUT /inventory/{pk}` sets absolute quantities**, so a read-then-write by Module 07 can race. Bounded by the `reserved ≤ stock` rule, but two concurrent reservation writers could lose one reservation. | Recommend a delta endpoint (`POST /inventory/{pk}/reserve`) when Module 07 lands. |
| R5 | Low | **Schema created by `create_all`, not migrations,** even though `alembic` is a dependency. | Acceptable for SQLite dev; add initial Alembic migration before PostgreSQL production. |
| R6 | Low | **`/health` does not check database connectivity** — returns `ok` even if the DB is unreachable. | Cheap improvement, intentionally not bundled into an audit fix commit. |
| R7 | Low | **Multi-process SQLite not recommended.** Allocation is now atomic and 6-process testing passed, but SQLite remains a single-writer database. | Use PostgreSQL for > 1 worker. |
| R8 | Low | **Uploaded files are never garbage-collected** when an image row is deleted. | Disk growth only; needs an explicit retention policy decision. |
| R9 | Low | **`test_upload_requires_admin` covers only the upload route**, not `/images` JSON registration. | JSON registration is covered by the general 401 sweep. |
| R10 | Info | **TestClient deprecation warning** (`httpx` → `httpx2`). | Cosmetic; upgrade when the library updates. |

No issue in this table blocks integration. R1 and R4 should be closed before
multi-worker production and before Module 07 writes reservations.

---

## 10. Files changed by this audit

```
.env.example                  placeholder key, new vars documented
CHANGELOG.md                  1.0.1 entry (all fixes by severity)
INTEGRATION.md                verified guarantees + Module 01 proposal
README.md                     test count, upload validation wording
pyproject.toml                1.0.1, declared dependencies
requirements.txt              added pillow, fixed multipart pin, added pytest/httpx
app/__init__.py               1.0.1
app/config.py                 production guard, stricter placeholder check, limiter default
app/database.py               WAL, busy_timeout, foreign_keys, BEGIN IMMEDIATE
app/id_generator.py           rewritten: atomic UPDATE…RETURNING, ON CONFLICT insert
app/main.py                   1.0.1, lifespan, CORS credentials rule, rate limiter
app/models.py                 inventory_lots.variant_id UNIQUE
app/routers/fabrics.py        archive cascade, no ORM mutation, image check on hard delete
app/routers/images.py         capped read, Pillow decode + pixel ceiling
app/routers/variants.py       join on parent fabric is_active
app/services.py               _with_retry(db,…) with rollback, inventory upsert retry
docs/API_DOCUMENTATION.md     archive/upload/concurrency/rate-limit contracts
docs/INVENTORY_RULES.md       uniqueness constraint, archive retention
tests/conftest.py             per-test wipe (BEGIN IMMEDIATE incompatible with outer tx)
tests/test_images_inventory.py decodable PNG fixture
tests/test_verification.py    NEW — 28 audit tests
```

---

## 11. Repository state

| Item | Value |
|---|---|
| Branch | `arena/9fb44bec-fabric-catalog-system` |
| HEAD | `f8c6e1cd717bda5fded09bbde0cebc6962882371` |
| Pushed | Yes — `origin` is at the same SHA |
| Working tree | Clean |
| `main` | Untouched at `6524f79` |
| Merge | **Not performed** — awaiting owner approval |
| Tests | 62 passed, 0 failed |
| Files outside Module 02 touched | None |

### Sync steps if you want this locally

```bash
git fetch origin
git checkout arena/9fb44bec-fabric-catalog-system
git pull
pip install -r requirements.txt      # pillow is new
python -m pytest tests/ -q           # expect: 62 passed
```

---

## 12. Recommendation

Merge `arena/9fb44bec-fabric-catalog-system` into `main` **after** the owner
reviews this report, R1/R4 are scheduled, and an Alembic baseline migration
is added for the PostgreSQL production target (R5). Until then keep Module 02
single-worker on SQLite, or PostgreSQL if multiple workers are needed.

I am not starting Module 01 or any other module.


---

# 13. Hardening release — residual issue closure

**Release:** 1.1.0 **Date:** 2026-11-18
**Prior audit HEAD:** `4ce3e10` — see §1–§12 above.

This section records what was closed, what was deliberately left open, and
the evidence for each claim. It supersedes §9 for status purposes.

## 13.1 Closure summary

| ID | Issue | Status | Evidence |
|---|---|---|---|
| R1 | Rate limiter process-local only | **CLOSED (with caveat)** | `app/rate_limit.py`; memory + shared Redis backends; `tests/test_rate_limit_auth.py` (21 tests) |
| R4 | Inventory lost updates / read-then-write | **CLOSED** | `app/inventory_service.py`; `tests/test_inventory_concurrency.py` (15 tests); live PG load test |
| R5 | No migrations; PostgreSQL unverified | **CLOSED** | `alembic/versions/bf18530135e8`; `tests/test_migrations.py` (9 tests, 5 on real PG 16.2) |
| R2 | Single admin key, no roles | OPEN (by design) | service keys added; human RBAC still absent |
| R3 | `/suppliers` has no update/delete | OPEN | unchanged |
| R6 | `/health` does not check DB | OPEN | unchanged |
| R7 | Multi-process SQLite discouraged | OPEN (guidance) | documented; PG supported |
| R8 | No upload GC | OPEN | unchanged |
| R9 | Upload auth coverage narrow | CLOSED | general 401 sweep covers upload routes |
| R10 | TestClient deprecation | OPEN (info) | library notice |

## 13.2 R4 — inventory concurrency (Priority 1)

**Root cause.** `PUT /inventory/{pk}` wrote absolute quantities that the
caller had read earlier. Two concurrent clerks (or Module 07 writers) both
read `stock=10, reserved=0`, both decide to reserve 2, both write
`reserved=2`: one reservation is silently lost. There was also a
check-then-act gap — availability was verified in Python, then written.

**Fix — three separated concerns**, each a single conditional statement
evaluated by the database:

| Operation | Statement condition | Guarantees |
|---|---|---|
| `POST /adjust` (relative) | `stock + delta >= 0` | deltas compose; never negative |
| `POST /reserve` | `stock - reserved >= qty` | concurrent holds cannot exceed stock |
| `POST /release` | `reserved >= qty` | cannot release unheld stock |
| `POST /dispatch` | `reserved >= qty AND stock >= qty` | ships only held+physical goods |
| `PUT` (absolute) | `stock = expected AND/OR revision = expected` | stale writes rejected (`409`); unguarded refused (`428`) |

`rowcount == 0` is the conflict signal. Because the condition and the write
are one statement, there is no window between checking and acting.

Additional properties:

- **Optimistic concurrency token** `inventory_lots.revision`, bumped by
  every mutation, exposed to callers.
- **Negative stock is impossible**; no per-request escape hatch exists.
  The documented physical-recount path is `PUT` with an explicit
  `expected_revision`.
- **History preserved**: every change appends an `inventory_movements` row
  with before/after snapshots (`stock_after`, `reserved_after`), readable
  at `GET /inventory/{pk}/movements`.
- **Idempotency**: `Idempotency-Key` is claimed (INSERT, UNIQUE) *before*
  work runs, then completed with the serialised response. A retry replays
  the original body (`Idempotent-Replay: true`); a concurrent duplicate
  waits for the winner. Key reuse with a different payload → `409`.

**Evidence — real concurrent sessions (not TestClient):**

| Test | Result |
|---|---|
| 20 concurrent `+5` receipts | exactly `100.000` |
| 20 concurrent interleaved `+7`/`-3` | exactly `140.000` |
| stock 10, 20 concurrent `-1` | exactly 10 succeed, 10 → 409, stock `0.000` |
| stock 10, 20 concurrent `reserve(1)` | exactly 10 held, 10 → 409, `available == 0` |
| 10 concurrent absolute writes, same revision | exactly 1 success, 9 → 409 |
| 10 concurrent same-`Idempotency-Key` reserves | stock moved **once** |
| 5 consecutive suite runs | 16 passed each time, no flake |

**Evidence — live HTTP against real PostgreSQL 16.2:**

```
A) 60 concurrent reserve(1) vs stock 50
   held=50  refused=10  other=[]
   final stock=50.000 reserved=50.000   oversold: False

B) 12 concurrent identical idempotent requests
   statuses=[200]  replays=11
   reserved=5.000   applied once: True

C) stale guarded write
   first=200   stale=409 "Stock was modified by someone else..."
```

## 13.3 R1 — rate limiting (Priority 2)

**Implemented** (`app/rate_limit.py`), three explicit backends:

| Backend | Scope | Honest description |
|---|---|---|
| `memory` (default) | **this process only** | N workers ⇒ roughly N× the limit; resets on restart |
| `redis` | **shared across workers and replicas** | atomic `INCR`+`EXPIRE` on a per-minute bucket |
| `off` | none | `RATE_LIMIT_PER_MINUTE=0` also disables |

The response headers state the scope explicitly
(`X-RateLimit-Scope: process-local` or `shared-across-workers`) so an
operator can never mistake one for the other.

- **Fail behaviour is configurable**: `RATE_LIMIT_FAIL_OPEN=true` allows
  traffic if Redis dies (recommended — a cache outage should not be an
  API outage); `false` returns `503`. Redis errors log only the exception
  **type**, never the URL (which may embed a password).
- **Header spoofing is closed**: `X-Forwarded-For` is ignored unless
  `TRUSTED_PROXY_COUNT > 0`, and then the entry appended by the nearest
  trusted proxy is used, not the client-supplied leftmost value.
  Verified by `test_xff_ignored_when_no_trusted_proxies` and
  `test_xff_honours_nearest_trusted_hop_not_client_supplied`.
- `/health` is exempt so orchestrator probes are never throttled.
- `/docs` remains readable; limits apply to `/api/*`.

**Caveat, stated plainly:** the Redis path is verified against
`fakeredis`, which exercises the real limiter code (bucketing, INCR,
EXPIRE, fail-open) but is **not** a real Redis server. A live Redis
integration test is still outstanding — tracked as L2 below. This is also
why `memory` remains the default rather than quietly switching production
to an untested-in-CI backend.

## 13.4 R5 — migrations (Priority 3)

- Alembic baseline `bf18530135e8`, generated with `--autogenerate`
  **against a real PostgreSQL 16.2 server**, not SQLite.
- `alembic.ini` contains **no credentials**; `env.py` resolves the URL from
  `ALEMBIC_DATABASE_URL` then the app's `DATABASE_URL`.
- `render_as_batch` is enabled for SQLite so one script set serves both.

**Adoption safety (the "upgrade from current schema" requirement).** The
previous deployment path was `create_all()`, leaving a populated database
with no `alembic_version` row. A naive baseline would abort with "table
already exists". `upgrade()` therefore inspects the live database and
creates only missing objects — on a complete database it is a no-op that
stamps the revision. **Nothing is dropped or altered**, so adopting an
existing production database cannot destroy data.

**A PostgreSQL-only defect found and fixed:** `downgrade()` left the five
ENUM types behind, so `downgrade` → `upgrade` failed with
"type already exists". SQLite has no ENUM types and could never reveal
this. The baseline now drops them on PostgreSQL only.

| Test (SQLite) | Result |
|---|---|
| clean database creation | PASSED |
| `alembic check` — no ORM drift | PASSED |
| upgrade from `create_all` schema, data preserved | PASSED |
| downgrade → re-upgrade cycle | PASSED |

| Test (PostgreSQL 16.2) | Result |
|---|---|
| clean database creation | PASSED |
| `alembic check` — no ORM drift | PASSED |
| upgrade from `create_all` schema, data preserved | PASSED |
| column types: `NUMERIC(12,2)` money, `NUMERIC(12,3)` qty | PASSED |
| downgrade → re-upgrade cycle | PASSED |

Without `PG_TEST_URL` the five PostgreSQL tests report **skipped**, never
passed — verified: `4 passed, 5 skipped`.

## 13.5 Module 01 / Module 07 integration

Implemented:

- **Scoped service credentials** (`SERVICE_API_KEYS` /
  `SERVICE_KEY_SCOPES`), constant-time comparison, optional IP allowlist.
  Separate from the human admin key; a service key is never accepted as
  admin.
- **Module 01 is not granted `supplier:read`** — verified by test.
- **CORS**: production now *refuses to start* with `CORS_ORIGINS=*`;
  an explicit allowlist is mandatory.
- **No credential reaches a browser**: verified that neither key appears in
  `/openapi.json` or `/health`.
- Contracts: `docs/MODULE_01_INTEGRATION_CONTRACT.md`,
  `docs/INVENTORY_API_MODULE_07.md`, `docs/ARCHITECTURE.md`.
- `tests/test_api_contract.py` — 18 tests pinning envelope keys, field
  sets, by-code lookups, error shape, 401 vs 403, and privacy.

## 13.6 Test evidence (whole release)

```
126 passed, 1 warning             # full suite, PostgreSQL enabled
105 passed, 5 skipped             # without PG_TEST_URL
 16 passed  x5 consecutive runs   # concurrency subset, no flakes
 48/48 unique, 0 errors           # 6 OS processes, ID generation
  9 passed                        # migrations (5 on real PG)
All checks passed!                # ruff
compile: OK                       # compileall
```

Suite grew 62 → 126 tests.

## 13.7 Remaining limitations (L-series, honest)

| ID | Limitation | Impact | Mitigation |
|---|---|---|---|
| L1 | **Redis path untested against a real Redis server** (fakeredis only) | medium | run `tests/test_rate_limit_auth.py` against real Redis before switching `RATE_LIMIT_BACKEND=redis` in production |
| L2 | **No reservation→order link, no TTL** | medium | open decisions with Module 07 (`INVENTORY_API_MODULE_07.md` §6) |
| L3 | **Multi-process SQLite not recommended** | medium | use PostgreSQL for >1 worker |
| L4 | **No human RBAC / per-user audit** | medium | single shared admin key; recommended before multiple staff |
| L5 | **No catalogue change notification** (webhook/ETag) | low | consumers must re-read |
| L6 | `/health` does not verify DB connectivity | low | use `alembic check` / monitoring |
| L7 | `/suppliers` is read+create only | low | Module 08 admin work |
| L8 | Uploaded files not garbage-collected | low | retention policy needed |
| L9 | No live-Redis CI job, no GitHub Actions pipeline | low | tests are local-only today |
| L10 | PostgreSQL tested via ephemeral local server, not a managed service | low | same engine; connection/pool specifics untested |

**Production readiness statement.** Module 02 is ready for a
**single-worker PostgreSQL deployment** with an explicit CORS allowlist and
a real `ADMIN_API_KEY`. It should **not** be described as ready for
multi-replica production until L1 (real Redis verification) and L2
(reservation contract with Module 07) are closed.
