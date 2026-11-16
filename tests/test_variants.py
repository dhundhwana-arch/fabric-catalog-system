"""Variant, colour, price and availability tests."""


def test_create_variant(client, admin_headers, seeded):
    r = client.post(
        "/api/v1/variants",
        json={"fabric_id": seeded["fabric"]["id"], "colour_name": "Green", "colour_hex": "#008000",
              "customer_price": "400.00"},
        headers=admin_headers,
    )
    assert r.status_code == 201
    assert r.json()["variant_id"].startswith("FVAR-")
    assert r.json()["currency"] == "INR"


def test_variant_parent_must_exist(client, admin_headers):
    r = client.post(
        "/api/v1/variants",
        json={"fabric_id": 99999, "colour_name": "Red", "colour_hex": "#FF0000"},
        headers=admin_headers,
    )
    assert r.status_code == 404


def test_invalid_hex_rejected(client, admin_headers, seeded):
    r = client.post(
        "/api/v1/variants",
        json={"fabric_id": seeded["fabric"]["id"], "colour_name": "Bad", "colour_hex": "not-a-colour"},
        headers=admin_headers,
    )
    assert r.status_code == 422


def test_invalid_price_rejected(client, admin_headers, seeded):
    r = client.post(
        "/api/v1/variants",
        json={"fabric_id": seeded["fabric"]["id"], "colour_name": "Bad", "colour_hex": "#123456",
              "customer_price": "-10"},
        headers=admin_headers,
    )
    assert r.status_code == 422


def test_duplicate_variant_rejected(client, admin_headers, seeded):
    payload = {"fabric_id": seeded["fabric"]["id"], "colour_name": "Navy Blue", "colour_hex": "#000080"}
    r = client.post("/api/v1/variants", json=payload, headers=admin_headers)
    assert r.status_code == 409


def test_availability_update(client, admin_headers, seeded):
    vid = seeded["v1"]["id"]
    r = client.put(f"/api/v1/variants/{vid}", json={"availability_status": "LOW_STOCK"}, headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["availability_status"] == "LOW_STOCK"


def test_colour_list(client, seeded):
    r = client.get("/api/v1/colours")
    assert r.status_code == 200
    names = [c["colour_name"] for c in r.json()]
    assert "Navy Blue" in names


def test_colour_filter(client, seeded):
    r = client.get("/api/v1/variants?colour=Navy")
    assert r.json()["total"] >= 1
    r2 = client.get("/api/v1/variants?colour_hex=%23000080")
    assert r2.json()["total"] >= 1


def test_price_history(client, admin_headers, seeded):
    vid = seeded["v1"]["id"]
    r = client.post("/api/v1/prices", json={"variant_id": vid, "customer_price": "475.00"}, headers=admin_headers)
    assert r.status_code == 201
    hist = client.get(f"/api/v1/prices/variants/{vid}")
    assert hist.status_code == 200
    assert len(hist.json()) >= 2  # initial + new
