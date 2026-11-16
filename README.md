# Fabric Catalog System

**CUSTOM SHIRT STUDIO — Module 02/08: FABRIC CATALOG SYSTEM**

The source of truth for fabric catalogue data: fabrics, colour variants,
photos, customer prices, availability and optional inventory. Built for a
small family tailoring business in Dhundhwana, Gujarat, India, and designed
for future integration with the other seven Custom Shirt Studio modules.

> **Important:** This system never invents inventory. A fabric is only shown
> as available when a verified variant exists. Demo/seed data is clearly
> labelled example data and is not real stock.

## Features

- Fabric, category, colour-variant, image, price-history and inventory CRUD
- Permanent, database-allocated IDs (`FAB-001`, `FVAR-001`, `FIMG-001`, `FLOT-001`, `FCAT-001`)
- Search, category/type/colour/price/availability filtering, sorting, pagination
- Customer-facing catalogue + admin panel (single-page app, mobile-friendly)
- Image upload with type/size/magic-byte validation and safe generated names
- Decimal-safe INR pricing; supplier costs are admin-only and never public
- Sourcing model: `CUSTOMER_SUPPLIED` / `BUSINESS_INVENTORY` / `SUPPLIER_SOURCED`
- Catalogue export (JSON / CSV), OpenAPI docs at `/docs`

## Architecture

```
app/
  main.py          FastAPI app, CORS, static frontend, /health
  config.py        Environment-based settings
  database.py      SQLAlchemy engine/session (SQLite default, PostgreSQL ready)
  models.py        ORM models (Fabric, Variant, Image, Price, Lot, Movement, Supplier)
  schemas.py       Pydantic validation (HEX, prices, quantities)
  id_generator.py  Concurrency-safe DB-backed ID allocation
  auth.py          Admin Bearer-token auth
  services.py      Business logic layer
  routers/         fabrics, variants, categories, colours, images,
                   prices, inventory, suppliers, export
  static/          Customer catalogue + admin UI (HTML/CSS/JS)
tests/             34 pytest tests
docs/              Data model, colour, image, inventory, API, installation docs
```

## Technology stack

Python 3.11 · FastAPI · SQLAlchemy 2 · Pydantic 2 · SQLite (dev) / PostgreSQL
(prod) · Alembic-ready · Pytest · Vanilla HTML/CSS/JS frontend (no build step)

## Prerequisites

- Python 3.11+
- (Optional) PostgreSQL 14+ for production

## Installation

```bash
git clone https://github.com/dhundhwana-arch/fabric-catalog-system.git
cd fabric-catalog-system
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then set a real ADMIN_API_KEY
```

## Database setup

SQLite (default): tables are created automatically on startup.

PostgreSQL: set `DATABASE_URL=postgresql+psycopg://user:pass@host:5432/fabric_catalog`
in `.env`. Tables are created on startup; Alembic migrations can be added
against the same models for schema evolution.

## Running

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000 — customer catalogue. Use the **Admin** tab with
your `ADMIN_API_KEY` to manage the catalogue. API docs: http://localhost:8000/docs

Optional demo data (example only, not real inventory):

```bash
python scripts/seed_demo.py
```

## Environment configuration

See `.env.example`. Key variables: `DATABASE_URL`, `ADMIN_API_KEY`,
`UPLOAD_DIR`, `INVENTORY_ENABLED`, `CORS_ORIGINS`.

## API documentation

Interactive OpenAPI UI at `/docs`; full reference in `docs/API_DOCUMENTATION.md`.

## Testing

```bash
python -m pytest tests/ -q
```

## Contributing

See `CONTRIBUTING.md`. Integration with other modules: see `INTEGRATION.md`.

## Licence

MIT — see `LICENSE`.
