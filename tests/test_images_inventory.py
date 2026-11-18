"""Image validation, inventory and export tests."""
import io


def test_register_image_reference(client, admin_headers, seeded):
    r = client.post(
        "/api/v1/images",
        json={"fabric_id": seeded["fabric"]["id"], "image_url": "https://example.com/a.jpg",
              "image_type": "FRONT"},
        headers=admin_headers,
    )
    assert r.status_code == 201
    assert r.json()["image_id"].startswith("FIMG-")


def test_image_requires_parent(client, admin_headers):
    r = client.post("/api/v1/images", json={"image_url": "https://example.com/a.jpg"}, headers=admin_headers)
    assert r.status_code == 422


def test_invalid_image_url_rejected(client, admin_headers, seeded):
    r = client.post(
        "/api/v1/images",
        json={"fabric_id": seeded["fabric"]["id"], "image_url": "ftp://bad/file"},
        headers=admin_headers,
    )
    assert r.status_code == 422


def test_upload_rejects_bad_type(client, admin_headers, seeded):
    files = {"file": ("evil.txt", io.BytesIO(b"hello"), "text/plain")}
    r = client.post(
        "/api/v1/images/upload",
        files=files,
        data={"fabric_id": str(seeded["fabric"]["id"])},
        headers=admin_headers,
    )
    assert r.status_code == 415


def test_upload_rejects_fake_image(client, admin_headers, seeded):
    files = {"file": ("fake.jpg", io.BytesIO(b"not really a jpeg"), "image/jpeg")}
    r = client.post(
        "/api/v1/images/upload",
        files=files,
        data={"fabric_id": str(seeded["fabric"]["id"])},
        headers=admin_headers,
    )
    assert r.status_code == 422


def _real_png() -> bytes:
    """A genuinely decodable PNG (Pillow-verified) for the upload path."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (10, 20, 30)).save(buf, "PNG")
    return buf.getvalue()


def test_upload_valid_png(client, admin_headers, seeded):
    png = _real_png()
    files = {"file": ("swatch.png", io.BytesIO(png), "image/png")}
    r = client.post(
        "/api/v1/images/upload",
        files=files,
        data={"fabric_id": str(seeded["fabric"]["id"]), "image_type": "SWATCH"},
        headers=admin_headers,
    )
    assert r.status_code == 201
    assert r.json()["image_url"].startswith("/uploads/")


def test_inventory_update_and_negative_rejection(client, admin_headers, seeded):
    """PUT is an absolute recount: it must carry the value last read."""

    vid = seeded["v1"]["id"]
    r = client.put(
        f"/api/v1/inventory/{vid}",
        json={"stock_quantity": "10.5", "reserved_quantity": "2", "expected_stock_quantity": "0"},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    assert float(r.json()["stock_quantity"]) == 10.5
    bad = client.put(
        f"/api/v1/inventory/{vid}",
        json={"stock_quantity": "-1", "expected_stock_quantity": "10.5"},
        headers=admin_headers,
    )
    assert bad.status_code == 422
    over = client.put(
        f"/api/v1/inventory/{vid}",
        json={"stock_quantity": "1", "reserved_quantity": "5", "expected_stock_quantity": "10.5"},
        headers=admin_headers,
    )
    assert over.status_code == 422
    # Unguarded absolute write is refused: this is the R4 fix.
    unguarded = client.put(
        f"/api/v1/inventory/{vid}", json={"stock_quantity": "99"}, headers=admin_headers
    )
    assert unguarded.status_code == 428


def test_export_json_and_csv(client, seeded):
    r = client.get("/api/v1/export?format=json")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    r2 = client.get("/api/v1/export?format=csv")
    assert r2.status_code == 200
    assert "fabric_id" in r2.text
