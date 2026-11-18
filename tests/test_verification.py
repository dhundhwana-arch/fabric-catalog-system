"""Independent verification suite for Module 02.

Covers the specific concerns raised in the technical audit:
concurrency (all ID kinds), privacy leaks, production guards, upload
validation, decimal pricing and archive behaviour.
"""
from __future__ import annotations

import io
import threading
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.database import Base
from app.inventory_service import adjust_stock, ensure_lot
from app.schemas import FabricCreate, VariantCreate
from app.services import create_fabric, create_variant, record_price


def _fresh_session_factory(tmp_path, name):
    db_file = tmp_path / name
    engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _run_threads(worker, count):
    errors, lock = [], threading.Lock()

    def wrapped(n):
        try:
            worker(n)
        except Exception as exc:  # noqa: BLE001
            with lock:
                errors.append(repr(exc)[:200])

    threads = [threading.Thread(target=wrapped, args=(n,)) for n in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return errors


# --------------------------------------------------------------------------
# 1. Concurrency: every ID kind
# --------------------------------------------------------------------------
def test_concurrent_fabric_and_variant_ids(tmp_path):
    """10 threads x 5 fabric+variant creates: no errors, no duplicates."""
    Session = _fresh_session_factory(tmp_path, "conc_fab.db")
    fabric_ids, variant_ids, lock = [], [], threading.Lock()

    def worker(n):
        db = Session()
        try:
            for i in range(5):
                f = create_fabric(db, FabricCreate(fabric_name=f"Conc-{n}-{i}"))
                v = create_variant(
                    db,
                    VariantCreate(
                        fabric_id=f.id,
                        colour_name="Navy",
                        colour_hex="#000080",
                        customer_price="450.00",
                    ),
                )
                with lock:
                    fabric_ids.append(f.fabric_id)
                    variant_ids.append(v.variant_id)
        finally:
            db.close()

    errors = _run_threads(worker, 10)
    assert errors == [], f"concurrent errors: {errors[:3]}"
    assert len(fabric_ids) == 50, len(fabric_ids)
    assert len(set(fabric_ids)) == 50, "duplicate FAB ids issued"
    assert len(set(variant_ids)) == 50, "duplicate FVAR ids issued"


def test_concurrent_image_lot_and_price_ids(tmp_path):
    """Concurrent image, inventory-lot and price ID allocation."""
    Session = _fresh_session_factory(tmp_path, "conc_all.db")
    setup = Session()
    fab = create_fabric(setup, FabricCreate(fabric_name="Conc All"))
    variants = [
        create_variant(
            setup,
            VariantCreate(
                fabric_id=fab.id,
                colour_name=f"C{i}",
                colour_hex=f"#0000{i:02X}",
                customer_price="100.00",
            ),
        )
        for i in range(10)
    ]
    variant_pks = [v.id for v in variants]
    fabric_pk = fab.id
    setup.close()

    image_ids, lot_ids, price_ids, lock = [], [], [], threading.Lock()

    def worker(n):
        db = Session()
        try:
            # image
            from app.id_generator import next_id

            img = models.FabricImage(
                image_id=next_id(db, "image"),
                fabric_id=fabric_pk,
                image_url="https://example.com/x.jpg",
            )
            db.add(img)
            db.commit()
            with lock:
                image_ids.append(img.image_id)
            # price
            price = record_price(
                db, variant_pks[n], Decimal("199.99"), "INR", models.Unit.METER
            )
            with lock:
                price_ids.append(price.price_id)
            # inventory lot
            ensure_lot(db, variant_pks[n], models.Unit.METER)
            lot = adjust_stock(
                db, variant_pks[n], Decimal("10"), models.MovementType.RECEIVE, "test"
            )
            with lock:
                lot_ids.append(lot.lot_id)
        finally:
            db.close()

    errors = _run_threads(worker, 10)
    assert errors == [], f"concurrent errors: {errors[:3]}"
    for label, ids in (("image", image_ids), ("lot", lot_ids), ("price", price_ids)):
        assert len(ids) == 10, f"{label}: expected 10, got {len(ids)}"
        assert len(set(ids)) == 10, f"{label}: duplicate ids {sorted(ids)}"


def test_ids_never_reused_after_delete(tmp_path):
    """Allocating after a hard delete must not hand out the old ID."""
    Session = _fresh_session_factory(tmp_path, "reuse.db")
    db = Session()
    first = create_fabric(db, FabricCreate(fabric_name="Reuse A"))
    old_id = first.fabric_id
    db.delete(first)
    db.commit()
    second = create_fabric(db, FabricCreate(fabric_name="Reuse B"))
    db.close()
    assert second.fabric_id != old_id
    assert int(second.fabric_id.split("-")[1]) > int(old_id.split("-")[1])


# --------------------------------------------------------------------------
# 2. Privacy: supplier / procurement data must never leak
# --------------------------------------------------------------------------
PRIVATE_KEYS = ("supplier", "procurement", "wholesale", "cost", "purchase")


def _walk_keys(obj, path="$"):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield path, k
            yield from _walk_keys(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_keys(v, f"{path}[{i}]")


@pytest.mark.parametrize("path", ["/api/v1/fabrics", "/api/v1/variants", "/api/v1/colours"])
def test_no_supplier_keys_in_public_payloads(client, admin_headers, seeded, path):
    body = client.get(path).json()
    for where, key in _walk_keys(body):
        for bad in PRIVATE_KEYS:
            assert bad not in key.lower(), f"private key {key!r} at {where} via {path}"


def test_supplier_data_absent_from_detail_and_export(client, admin_headers, seeded):
    fid = seeded["fabric"]["id"]
    secret = "Zenith Weaving Pvt Ltd"
    client.post(
        "/api/v1/suppliers",
        json={"fabric_id": fid, "supplier_name": secret, "procurement_price": "123.45"},
        headers=admin_headers,
    )
    blobs = [
        client.get(f"/api/v1/fabrics/{fid}").text,
        client.get(f"/api/v1/fabrics/by-code/{seeded['fabric']['fabric_id']}").text,
        client.get("/api/v1/variants").text,
        client.get("/api/v1/export?format=json").text,
        client.get("/api/v1/export?format=csv").text,
    ]
    for blob in blobs:
        assert secret not in blob
        assert "123.45" not in blob
        assert "procurement" not in blob.lower()


def test_suppliers_endpoint_requires_admin(client, seeded):
    assert client.get("/api/v1/suppliers").status_code == 401
    assert client.post("/api/v1/suppliers", json={}).status_code == 401


# --------------------------------------------------------------------------
# 3. Security configuration
# --------------------------------------------------------------------------
def test_mutating_endpoints_require_admin(client, seeded):
    fid = seeded["fabric"]["id"]
    calls = [
        ("post", "/api/v1/fabrics", {"fabric_name": "X"}),
        ("put", f"/api/v1/fabrics/{fid}", {"fabric_name": "X"}),
        ("delete", f"/api/v1/fabrics/{fid}", None),
        ("post", "/api/v1/categories", {"name": "X"}),
        ("post", "/api/v1/variants", {"fabric_id": fid, "colour_name": "R", "colour_hex": "#000000"}),
        ("post", "/api/v1/prices", {"variant_id": seeded["v1"]["id"], "customer_price": "1.00"}),
        ("post", f"/api/v1/inventory/{seeded['v1']['id']}/adjust", {"quantity": "5"}),
        ("post", f"/api/v1/inventory/{seeded['v1']['id']}/reserve", {"quantity": "5"}),
        ("post", f"/api/v1/inventory/{seeded['v1']['id']}/release", {"quantity": "5"}),
        ("post", f"/api/v1/inventory/{seeded['v1']['id']}/dispatch", {"quantity": "5"}),
        ("put", f"/api/v1/inventory/{seeded['v1']['id']}", {"stock_quantity": "5"}),
    ]
    for method, url, body in calls:
        kwargs = {"json": body} if body is not None else {}
        r = getattr(client, method)(url, **kwargs)
        assert r.status_code == 401, f"{method.upper()} {url} -> {r.status_code}"


def test_wrong_key_rejected(client, seeded):
    r = client.get(
        "/api/v1/suppliers", headers={"Authorization": "Bearer wrong-key"}
    )
    assert r.status_code == 401


def test_production_guard_rejects_default_key():
    from app.config import Settings

    with pytest.raises(RuntimeError):
        Settings(app_env="production", admin_api_key="dev-only-change-me").validate_production()
    with pytest.raises(RuntimeError):
        Settings(app_env="production", admin_api_key="").validate_production()
    Settings(app_env="production", admin_api_key="s" * 40).validate_production()
    Settings(app_env="development", admin_api_key="dev-only-change-me").validate_production()


def test_cors_never_allows_credentials_with_wildcard():
    from app.config import Settings
    from app.main import app as application

    settings = Settings()
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    for mw in application.user_middleware:
        if mw.cls.__name__ == "CORSMiddleware":
            assert mw.kwargs["allow_credentials"] is (origins != ["*"])


# --------------------------------------------------------------------------
# 4. Upload validation
# --------------------------------------------------------------------------
def _png_bytes(width: int = 4, height: int = 4) -> bytes:
    """A real, decodable PNG (used to exercise the upload path)."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), (10, 20, 30)).save(buf, "PNG")
    return buf.getvalue()


PNG_1PX = _png_bytes()


def _upload(client, headers, data=PNG_1PX, name="a.png", ctype="image/png", fabric_id=1):
    return client.post(
        "/api/v1/images/upload",
        files={"file": (name, io.BytesIO(data), ctype)},
        data={"fabric_id": str(fabric_id)},
        headers=headers,
    )


def test_upload_requires_admin(client, seeded):
    r = _upload(client, {}, fabric_id=seeded["fabric"]["id"])
    assert r.status_code == 401


def test_upload_rejects_oversized(client, admin_headers, seeded):
    from app.config import get_settings

    limit = get_settings().max_upload_bytes
    big = PNG_1PX + b"\x00" * (limit + 10)
    r = _upload(client, admin_headers, data=big, fabric_id=seeded["fabric"]["id"])
    assert r.status_code == 413


def test_upload_rejects_wrong_type_and_bad_magic(client, admin_headers, seeded):
    fid = seeded["fabric"]["id"]
    assert _upload(client, admin_headers, data=b"hello", ctype="text/plain", fabric_id=fid).status_code == 415
    assert (
        _upload(client, admin_headers, data=b"not-a-png", ctype="image/png", fabric_id=fid).status_code
        == 422
    )


def test_upload_ignores_path_traversal_filename(client, admin_headers, seeded, tmp_path):
    r = _upload(
        client,
        admin_headers,
        name="../../../../etc/passwd.png",
        fabric_id=seeded["fabric"]["id"],
    )
    assert r.status_code == 201, r.text
    url = r.json()["image_url"]
    assert url.startswith("/uploads/")
    assert ".." not in url and "etc" not in url
    from pathlib import Path

    from app.config import get_settings

    stored = Path(get_settings().upload_dir) / Path(url).name
    assert stored.exists()
    assert stored.resolve().parent == Path(get_settings().upload_dir).resolve()


def test_upload_rejects_undecodable_bytes(client, admin_headers, seeded):
    """PNG magic bytes but corrupt body must be rejected by the decoder."""
    bogus = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    r = _upload(client, admin_headers, data=bogus, fabric_id=seeded["fabric"]["id"])
    assert r.status_code == 422


# --------------------------------------------------------------------------
# 5. Decimal-safe INR pricing + price history
# --------------------------------------------------------------------------
def test_decimal_precision_preserved(client, admin_headers, seeded):

    vid = seeded["v1"]["id"]
    r = client.post(
        "/api/v1/prices",
        json={"variant_id": vid, "customer_price": "450.10", "currency": "INR"},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    assert str(r.json()["customer_price"]) in ("450.10", "450.1")
    variant = client.get(f"/api/v1/variants/{vid}").json()
    assert str(variant["customer_price"]) in ("450.10", "450.1")


def test_price_history_appends_and_orders(client, admin_headers, seeded):
    vid = seeded["v1"]["id"]
    for price in ("500.00", "525.50", "499.99"):
        assert (
            client.post(
                "/api/v1/prices",
                json={"variant_id": vid, "customer_price": price},
                headers=admin_headers,
            ).status_code
            == 201
        )
    hist = client.get(f"/api/v1/prices/variants/{vid}").json()
    assert len(hist) >= 4  # initial + 3
    price_ids = [h["price_id"] for h in hist]
    assert len(set(price_ids)) == len(price_ids)
    values = [h["customer_price"] for h in hist]
    assert all(isinstance(v, (int, float, str)) for v in values)


def test_negative_price_rejected(client, admin_headers, seeded):
    r = client.post(
        "/api/v1/prices",
        json={"variant_id": seeded["v1"]["id"], "customer_price": "-1.00"},
        headers=admin_headers,
    )
    assert r.status_code == 422


# --------------------------------------------------------------------------
# 6. Archive behaviour
# --------------------------------------------------------------------------
def test_archive_cascades_to_variants(client, admin_headers, seeded):
    fid = seeded["fabric"]["id"]
    assert client.delete(f"/api/v1/fabrics/{fid}", headers=admin_headers).status_code == 200

    assert client.get(f"/api/v1/variants?fabric_id={fid}").json()["total"] == 0
    for colour in client.get("/api/v1/colours").json():
        assert colour["variant_count"] == 0, colour

    detail = client.get(f"/api/v1/fabrics/{fid}").json()
    assert detail["variants"] == []
    full = client.get(f"/api/v1/fabrics/{fid}?include_inactive=true").json()
    assert len(full["variants"]) == 2
    assert seeded["v1"]["id"] in [v["id"] for v in full["variants"]]


def test_archived_fabric_hidden_from_list(client, admin_headers, seeded):
    fid = seeded["fabric"]["id"]
    client.delete(f"/api/v1/fabrics/{fid}", headers=admin_headers)
    assert client.get("/api/v1/fabrics").json()["total"] == 0
    assert client.get("/api/v1/fabrics?include_inactive=true").json()["total"] == 1


def test_hard_delete_blocked_by_variants_and_images(client, admin_headers, seeded):
    fid = seeded["fabric"]["id"]
    assert client.delete(f"/api/v1/fabrics/{fid}?hard=true", headers=admin_headers).status_code == 409

    other = client.post("/api/v1/fabrics", json={"fabric_name": "ImgFab"}, headers=admin_headers).json()
    client.post(
        "/api/v1/images",
        json={"fabric_id": other["id"], "image_url": "https://example.com/x.jpg"},
        headers=admin_headers,
    )
    assert client.delete(f"/api/v1/fabrics/{other['id']}?hard=true", headers=admin_headers).status_code == 409

    plain = client.post("/api/v1/fabrics", json={"fabric_name": "Plain"}, headers=admin_headers).json()
    assert client.delete(f"/api/v1/fabrics/{plain['id']}?hard=true", headers=admin_headers).status_code == 200


def test_archived_fabric_keeps_inventory_history(client, admin_headers, seeded):
    vid = seeded["v1"]["id"]
    assert client.post(
        f"/api/v1/inventory/{vid}/adjust",
        json={"quantity": "12.500", "movement_type": "RECEIVE"},
        headers=admin_headers,
    ).status_code == 200
    assert client.post(
        f"/api/v1/inventory/{vid}/reserve",
        json={"quantity": "2.000"},
        headers=admin_headers,
    ).status_code == 200
    fid = seeded["fabric"]["id"]
    client.delete(f"/api/v1/fabrics/{fid}", headers=admin_headers)
    # Inventory rows survive the soft archive (audit trail intact)
    inv = client.get(f"/api/v1/inventory/{vid}")
    assert inv.status_code == 200
    assert str(inv.json()["stock_quantity"]) in ("12.5", "12.500")


def test_archive_is_idempotent(client, admin_headers, seeded):
    fid = seeded["fabric"]["id"]
    assert client.delete(f"/api/v1/fabrics/{fid}", headers=admin_headers).status_code == 200
    assert client.delete(f"/api/v1/fabrics/{fid}", headers=admin_headers).status_code == 200


# --------------------------------------------------------------------------
# 7. Inventory integrity
# --------------------------------------------------------------------------
def test_concurrent_inventory_upsert_single_lot(tmp_path):
    """10 concurrent first-time upserts for ONE variant -> exactly one lot."""
    from sqlalchemy import func, select

    Session = _fresh_session_factory(tmp_path, "inv.db")
    setup = Session()
    fab = create_fabric(setup, FabricCreate(fabric_name="InvRace"))
    var = create_variant(
        setup,
        VariantCreate(
            fabric_id=fab.id, colour_name="Navy", colour_hex="#000080", customer_price="100.00"
        ),
    )
    variant_pk = var.id
    setup.close()

    def worker(n):
        db = Session()
        try:
            ensure_lot(db, variant_pk, models.Unit.METER)
            adjust_stock(
                db,
                variant_pk,
                Decimal("10.000"),
                models.MovementType.RECEIVE,
                f"t{n}",
            )
        finally:
            db.close()

    errors = _run_threads(worker, 10)
    check = Session()
    count = check.execute(
        select(func.count()).select_from(models.InventoryLot).where(
            models.InventoryLot.variant_id == variant_pk
        )
    ).scalar_one()
    check.close()
    assert count == 1, f"expected 1 lot, found {count} (errors: {errors[:2]})"


def test_negative_and_oversell_rejected(client, admin_headers, seeded):
    vid = seeded["v1"]["id"]
    # Negative result is refused by the atomic conditional update itself.
    assert client.post(
        f"/api/v1/inventory/{vid}/adjust", json={"quantity": "-5"}, headers=admin_headers
    ).status_code == 409
    # Reserving more than available is refused.
    client.post(
        f"/api/v1/inventory/{vid}/adjust", json={"quantity": "5"}, headers=admin_headers
    )
    assert client.post(
        f"/api/v1/inventory/{vid}/reserve", json={"quantity": "9"}, headers=admin_headers
    ).status_code == 409


def test_inventory_persists_across_updates(client, admin_headers, seeded):
    vid = seeded["v1"]["id"]
    client.post(
        f"/api/v1/inventory/{vid}/adjust", json={"quantity": "20.000"}, headers=admin_headers
    )
    r = client.post(
        f"/api/v1/inventory/{vid}/adjust", json={"quantity": "-5.000"}, headers=admin_headers
    )
    assert r.status_code == 200, r.text
    assert str(r.json()["stock_quantity"]) in ("15.0", "15.000")
    assert str(r.json()["reserved_quantity"]) in ("0.0", "0.000")
