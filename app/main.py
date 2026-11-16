"""FastAPI application entrypoint.

Serves the REST API under /api/v1 and the customer/admin frontend as
static files. Run:  uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import init_db
from app.routers import categories, colours, export, fabrics, images, inventory, prices, suppliers, variants

settings = get_settings()

app = FastAPI(
    title="Custom Shirt Studio — Fabric Catalog System",
    description=(
        "Module 02: Fabric catalogue, colours, images, prices and availability. "
        "Public GET endpoints are open; all mutating endpoints require an admin Bearer token."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):  # pragma: no cover - safety net
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok", "module": "fabric-catalog-system", "version": "1.0.0"}


@app.get("/api/v1", tags=["meta"])
def api_root():
    return {
        "name": "Fabric Catalog System API",
        "version": "v1",
        "docs": "/docs",
        "endpoints": [
            "/api/v1/fabrics", "/api/v1/variants", "/api/v1/categories",
            "/api/v1/colours", "/api/v1/images", "/api/v1/prices",
            "/api/v1/inventory", "/api/v1/export",
        ],
    }


prefix = settings.api_v1_prefix
app.include_router(categories.router, prefix=prefix)
app.include_router(fabrics.router, prefix=prefix)
app.include_router(variants.router, prefix=prefix)
app.include_router(colours.router, prefix=prefix)
app.include_router(images.router, prefix=prefix)
app.include_router(prices.router, prefix=prefix)
app.include_router(inventory.router, prefix=prefix)
app.include_router(suppliers.router, prefix=prefix)
app.include_router(export.router, prefix=prefix)

# Uploaded images (provider-independent local storage)
upload_dir = Path(settings.upload_dir)
upload_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(upload_dir)), name="uploads")

# Frontend (customer catalogue + admin panel, single-page app)
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")


@app.on_event("startup")
def _startup():
    init_db()
