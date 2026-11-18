# Database Migrations

Alembic owns the schema from this release onward. `Base.metadata.create_all()`
is still used at startup for zero-config development, but **production
schemas must be created and changed by Alembic** on PostgreSQL.

- `alembic.ini` — config; contains **no** credentials.
- `alembic/env.py` — reads the URL from `ALEMBIC_DATABASE_URL`, else
  `DATABASE_URL` from the app settings.
- `alembic/versions/` — migration scripts.
- Baseline revision: `bf18530135e8`.

---

## 1. How the URL is resolved

```
ALEMBIC_DATABASE_URL   (highest priority - used by the test suite)
        │
        ▼
app settings DATABASE_URL   (env var or .env)
```

```bash
# Local SQLite
export DATABASE_URL=sqlite:///./fabric_catalog.db

# PostgreSQL
export DATABASE_URL=postgresql+psycopg://user:password@host:5432/fabric_catalog
```

The same migration scripts run on both. On SQLite, `env.py` enables
`render_as_batch` (SQLite cannot `ALTER TABLE` most things, so Alembic
copies the table and swaps it).

---

## 2. Clean database

```bash
python -m alembic upgrade head          # build the schema
python -m alembic current               # show applied revision
python -m alembic check                 # fails if ORM and DB have drifted
```

---

## 3. Adopting an existing (pre-Alembic) database

Deployments created before Alembic have every table but no
`alembic_version` row. The baseline revision inspects the live database
and creates only what is **missing**, so it is safe to run against an
existing database:

```bash
# 1. BACK UP FIRST (see section 5)
python -m alembic upgrade head
python -m alembic current       # -> bf18530135e8 (head)
```

On an already-complete database this is effectively a no-op that stamps
the revision. **Nothing is dropped or altered.** Verified on both SQLite
and PostgreSQL by
`tests/test_migrations.py::test_upgrade_from_create_all_*_preserves_data_*`.

---

## 4. Everyday workflow for a schema change

```bash
# 1. edit app/models.py
# 2. generate the revision (review it before committing!)
python -m alembic revision --autogenerate -m "add production_notes to fabrics"
# 3. READ the generated file. Autogenerate misses renames, data moves,
#    and enum changes.
# 4. verify it applies and reverts cleanly on a scratch database
python -m alembic upgrade head
python -m alembic downgrade -1
python -m alembic upgrade head
# 5. run the suite
python -m pytest tests/ -q
```

Never edit an applied migration. Add a new one.

---

## 5. Backup procedure (before any migration)

**PostgreSQL**

```bash
pg_dump --format=custom --file=fabric_$(date +%F_%H%M).dump "$DATABASE_URL_RAW"
pg_restore --list fabric_2026-11-18_1200.dump | head   # sanity check
```

**SQLite**

```bash
sqlite3 fabric_catalog.db ".backup 'fabric_$(date +%F_%H%M).db'"
```

Test the restore on a scratch database before touching production. Keep
the dump until the new release has been running for a few days.

---

## 6. Applying a migration in production

```bash
# 1. backup (section 5)
# 2. review the SQL that will run
python -m alembic upgrade head --sql > migration_preview.sql
# 3. stop writers, or accept online DDL (PostgreSQL handles most cases;
#    adding a NOT NULL column without a default takes an exclusive lock)
# 4. apply
python -m alembic upgrade head
# 5. verify
python -m alembic current
python -m alembic check
# 6. start the app, hit /health, smoke-test a catalogue read
```

### Rollback

```bash
python -m alembic downgrade -1     # one revision
python -m alembic downgrade base   # EVERYTHING - destructive, dev only
```

**Downgrades destroy data.** They are for disposable databases. On
production prefer restore-from-dump, or write a forward-fix migration.
The baseline's `downgrade()` drops only the tables it owns and, on
PostgreSQL, also removes the five ENUM types it created (otherwise a
downgrade followed by an upgrade fails with "type already exists" — a
PostgreSQL-only issue that SQLite cannot reveal).

---

## 7. Verifying against PostgreSQL (not just SQLite)

SQLite silently accepts things PostgreSQL rejects (and vice versa). Run:

```bash
export PG_TEST_URL="postgresql+psycopg://user:pass@localhost:5432/postgres"
python -m pytest tests/test_migrations.py -v -rs
```

`PG_TEST_URL` must point at a server where the test user may
`CREATE DATABASE`. If it is unset the five PostgreSQL tests are reported
as **skipped**, never as passed.

Current results (PostgreSQL 16.2 and SQLite):

```
test_clean_database_creation_sqlite                        PASSED
test_migration_matches_orm_metadata_sqlite                 PASSED
test_upgrade_from_create_all_schema_preserves_data_sqlite  PASSED
test_downgrade_and_reupgrade_sqlite                        PASSED
test_clean_database_creation_postgresql                    PASSED
test_migration_matches_orm_metadata_postgresql             PASSED
test_upgrade_from_create_all_preserves_data_postgresql     PASSED
test_types_match_on_postgresql                             PASSED
test_postgresql_downgrade_cycle                            PASSED
```

`test_types_match_on_postgresql` is the one that catches the class of bug
SQLite hides: it asserts `NUMERIC(12,2)` for money and `NUMERIC(12,3)`
for quantities as actually stored by PostgreSQL.

---

## 8. Production guidance

| Environment | Schema creation | Notes |
|---|---|---|
| Local dev | `create_all()` on startup **or** `alembic upgrade head` | either is fine |
| Staging | `alembic upgrade head` only | must mirror production |
| Production | `alembic upgrade head` only | never rely on `create_all` |

Keep `create_all()` for dev convenience only. It cannot alter an existing
table, so it will silently do nothing when a column is added — the app
then fails on a missing column. Alembic is the source of truth.
