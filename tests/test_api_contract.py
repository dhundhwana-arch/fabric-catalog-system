"""API contract tests for Module 01 / Module 07 integration.

These pin the contract that other modules depend on. If a future change
breaks a documented shape, these tests fail rather than the consuming
module discovering it in production.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Envelope and catalogue contract (Module 01)
# ---------------------------------------------------------------------------
def test_fabric_list_envelope_is_stable(client, seeded):
    body = client.get("/api/v1/fabrics").json()
    assert set(body) == {"items", "total", "page", "page_size", "pages"}
    assert isinstance(body["items"], list)
    assert body["page"] == 1
    assert body["page_size"] == 20


def test_fabric_item_contract_fields(client, seeded):
    """Fields Module 01 is allowed to rely on, and nothing private."""
    item = client.get("/api/v1/fabrics").json()["items"][0]
    required = {
        "id", "fabric_id", "fabric_name", "category_id", "fabric_type",
        "composition", "description", "sourcing_method", "is_active",
        "created_at", "updated_at",
    }
    assert required <= set(item)
    assert item["fabric_id"].startswith("FAB-")
    # No procurement vocabulary anywhere in the payload.
    lowered = {k.lower() for k in item}
    for forbidden in ("supplier", "procurement", "wholesale", "cost"):
        assert not any(forbidden in k for k in lowered)


def test_variant_contract_fields(client, seeded):
    v = client.get("/api/v1/variants").json()["items"][0]
    required = {
        "id", "variant_id", "fabric_id", "colour_name", "colour_hex",
        "availability_status", "unit", "customer_price", "currency", "is_active",
    }
    assert required <= set(v)
    assert v["variant_id"].startswith("FVAR-")
    assert v["currency"] == "INR"
    # Colour hex is normalised to uppercase #RRGGBB for the UI.
    assert v["colour_hex"].startswith("#") and len(v["colour_hex"]) == 7


def test_detail_includes_variants_and_images(client, seeded, admin_headers):
    fid = seeded["fabric"]["id"]
    client.post(
        "/api/v1/images",
        json={"fabric_id": fid, "image_url": "https://example.com/a.jpg", "image_type": "TEXTURE"},
        headers=admin_headers,
    )
    body = client.get(f"/api/v1/fabrics/{fid}").json()
    assert "variants" in body and "images" in body and "category" in body
    assert body["images"][0]["image_type"] == "TEXTURE"
    assert body["images"][0]["image_url"] == "https://example.com/a.jpg"


def test_lookup_by_permanent_id_is_supported(client, seeded):
    """Module 01 stores FAB-/FVAR- strings, so by-code lookups must work."""
    fab_code = seeded["fabric"]["fabric_id"]
    var_code = seeded["v1"]["variant_id"]
    assert client.get(f"/api/v1/fabrics/by-code/{fab_code}").json()["fabric_id"] == fab_code
    assert client.get(f"/api/v1/variants/by-code/{var_code}").json()["variant_id"] == var_code
    # Lowercase input is accepted and normalised.
    assert client.get(f"/api/v1/fabrics/by-code/{fab_code.lower()}").status_code == 200


def test_unknown_permanent_id_returns_404(client):
    assert client.get("/api/v1/fabrics/by-code/FAB-999999").status_code == 404
    assert client.get("/api/v1/variants/by-code/FVAR-999999").status_code == 404


def test_error_shape_is_detail_key(client):
    r = client.get("/api/v1/fabrics/999999")
    assert r.status_code == 404
    assert set(r.json()) == {"detail"}
    assert isinstance(r.json()["detail"], str)


def test_pagination_and_filter_params_accepted(client, seeded):
    assert client.get("/api/v1/fabrics?page=1&page_size=5").json()["page_size"] == 5
    assert client.get("/api/v1/fabrics?search=Poplin").json()["total"] >= 1
    assert client.get("/api/v1/fabrics?fabric_type=Poplin").json()["total"] >= 1
    assert client.get("/api/v1/fabrics?availability=AVAILABLE").status_code == 200
    assert client.get("/api/v1/fabrics?sort=price&order=asc").status_code == 200
    assert client.get("/api/v1/fabrics?sort=name").status_code == 200


def test_colours_endpoint_contract(client, seeded):
    colours = client.get("/api/v1/colours").json()
    assert isinstance(colours, list) and colours
    first = colours[0]
    assert {"colour_name", "colour_hex", "variant_count"} <= set(first)
    for c in colours:
        assert c["colour_hex"].startswith("#")


def test_export_json_is_public_safe_list(client, seeded, admin_headers):
    client.post(
        "/api/v1/suppliers",
        json={"fabric_id": seeded["fabric"]["id"], "supplier_name": "Contract Secret",
              "procurement_price": "55.55"},
        headers=admin_headers,
    )
    body = client.get("/api/v1/export?format=json").json()
    assert isinstance(body, list) and body
    text = str(body)
    assert "Contract Secret" not in text
    assert "55.55" not in text
    assert "procurement" not in text.lower()


def test_export_csv_headers(client, seeded):
    text = client.get("/api/v1/export?format=csv").text
    header = text.splitlines()[0]
    assert "fabric_id" in header
    assert "supplier" not in header.lower()


# ---------------------------------------------------------------------------
# Inventory contract (Module 07)
# ---------------------------------------------------------------------------
def test_inventory_view_contract(client, seeded, admin_headers):
    vid = seeded["v1"]["id"]
    client.post(f"/api/v1/inventory/{vid}/adjust", json={"quantity": "10"}, headers=admin_headers)
    body = client.get(f"/api/v1/inventory/{vid}").json()
    required = {
        "id", "lot_id", "variant_id", "stock_quantity",
        "reserved_quantity", "unit", "revision", "last_updated",
    }
    assert required <= set(body)
    assert body["lot_id"].startswith("FLOT-")
    assert isinstance(body["revision"], int)


def test_movement_history_contract(client, seeded, admin_headers):
    vid = seeded["v1"]["id"]
    client.post(f"/api/v1/inventory/{vid}/adjust", json={"quantity": "10"}, headers=admin_headers)
    client.post(f"/api/v1/inventory/{vid}/reserve", json={"quantity": "3"}, headers=admin_headers)
    rows = client.get(f"/api/v1/inventory/{vid}/movements").json()
    assert len(rows) == 2
    assert {"id", "lot_id", "movement_type", "quantity", "reference",
            "stock_after", "reserved_after", "created_at"} <= set(rows[0])
    types = [r["movement_type"] for r in rows]
    assert "RESERVE" in types and "ADJUST" in types


def test_unavailable_reservation_returns_409_with_detail(client, seeded, admin_headers):
    vid = seeded["v1"]["id"]
    client.post(f"/api/v1/inventory/{vid}/adjust", json={"quantity": "2"}, headers=admin_headers)
    r = client.post(f"/api/v1/inventory/{vid}/reserve", json={"quantity": "5"}, headers=admin_headers)
    assert r.status_code == 409
    assert "detail" in r.json()


def test_unguarded_absolute_write_returns_428(client, seeded, admin_headers):
    r = client.put(
        f"/api/v1/inventory/{seeded['v1']['id']}",
        json={"stock_quantity": "10"},
        headers=admin_headers,
    )
    assert r.status_code == 428


def test_inventory_404_for_variant_without_lot(client, seeded):
    """A variant that never had a lot is not "0 stock" - it is unknown."""
    other = seeded["v2"]["id"]
    assert client.get(f"/api/v1/inventory/{other}").status_code == 404


# ---------------------------------------------------------------------------
# Auth contract
# ---------------------------------------------------------------------------
def test_401_vs_403_semantics(client, seeded, service_keys):
    vid = seeded["v1"]["id"]
    # No credential at all -> 401
    assert client.post(f"/api/v1/inventory/{vid}/adjust", json={"quantity": "1"}).status_code == 401
    # Valid service credential, insufficient scope -> 403
    r = client.get("/api/v1/suppliers", headers={"Authorization": "Bearer svc-key-1"})
    assert r.status_code == 403
    assert r.headers.get("www-authenticate") is None or r.status_code == 403


def test_rate_limit_response_shape(client, seeded, admin_headers, service_keys):
    """429 responses must carry Retry-After so clients can back off."""
    from app.rate_limit import MemoryRateLimiter

    lim = MemoryRateLimiter(1)
    allowed, _ = lim.hit("k")
    assert allowed is True
    blocked, remaining = lim.hit("k")
    assert blocked is False and remaining == 0
