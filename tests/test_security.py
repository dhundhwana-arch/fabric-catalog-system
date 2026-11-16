"""Auth, permissions and privacy tests."""


def test_public_get_open(client, seeded):
    assert client.get("/api/v1/fabrics").status_code == 200
    assert client.get("/api/v1/colours").status_code == 200


def test_mutations_require_admin(client, seeded):
    assert client.post("/api/v1/fabrics", json={"fabric_name": "X"}).status_code == 401
    assert client.post("/api/v1/categories", json={"name": "X"}).status_code == 401
    fid = seeded["fabric"]["id"]
    assert client.put(f"/api/v1/fabrics/{fid}", json={"fabric_name": "Y"}).status_code == 401
    assert client.delete(f"/api/v1/fabrics/{fid}").status_code == 401


def test_wrong_key_rejected(client, seeded):
    r = client.post("/api/v1/fabrics", json={"fabric_name": "X"}, headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_supplier_data_never_public(client, admin_headers, seeded):
    fid = seeded["fabric"]["id"]
    r = client.post(
        "/api/v1/suppliers",
        json={"fabric_id": fid, "supplier_name": "Internal Supplier", "procurement_price": "300.00"},
        headers=admin_headers,
    )
    assert r.status_code == 201
    # Public fabric detail must not leak supplier fields
    detail = client.get(f"/api/v1/fabrics/{fid}").json()
    assert "supplier_references" not in detail
    assert "procurement_price" not in detail
    # Supplier endpoints require admin
    assert client.get("/api/v1/suppliers").status_code == 401
    assert client.get("/api/v1/suppliers", headers=admin_headers).status_code == 200


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
