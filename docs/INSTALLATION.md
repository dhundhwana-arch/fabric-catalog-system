# Installation

## Requirements
Python 3.11+. Optional: PostgreSQL 14+.

## Local (SQLite, zero-config)

```bash
git clone https://github.com/dhundhwana-arch/fabric-catalog-system.git
cd fabric-catalog-system
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env: set ADMIN_API_KEY to a long random secret
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Tables auto-create on startup. Open http://localhost:8000.

## PostgreSQL

```bash
# in .env:
# DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/fabric_catalog
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Docker

```bash
docker compose up --build
```

## Tests

```bash
python -m pytest tests/ -q
```

## Demo data (example only)

```bash
python scripts/seed_demo.py
```
