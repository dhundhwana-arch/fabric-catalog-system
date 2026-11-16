"""Fabric CRUD, IDs, archive, search/filter tests."""


def test_create_and_retrieve(client, admin_headers):
    r = client.post("/api/v1/fabrics", json={"fabric_name": "Linen Shirt"}, headers=admin_headers)
    assert r.status_code == 201
    body = r.json()
    assert body["fabric_id"].startswith("FAB-")
    assert body["is_active"] is True
    got = client.get(f"/api/v1/fabrics/{body['id']}")
    assert got.status_code == 200
    assert got.json()["fabric_name"] == "Linen Shirt"


def test_ids_are_unique_and_stable(client, admin_headers):
    a = client.post("/api/v1/fabrics", json={"fabric_name": "A"}, headers=admin_headers).json()
    b = client.post("/api/v1/fabrics", json={"fabric_name": "B"}, headers=admin_headers).json()
    assert a["fabric_id"] != b["fabric_id"]
    # Update must not change the permanent ID
    r = client.put(f"/api/v1/fabrics/{a['id']}", json={"fabric_name": "A2"}, headers=admin_headers)
    assert r.json()["fabric_id"] == a["fabric_id"]


def test_update_fabric(client, admin_headers, seeded):
    fid = seeded["fabric"]["id"]
    r = client.put(f"/api/v1/fabrics/{fid}", json={"description": "Updated"}, headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["description"] == "Updated"


def test_archive_fabric(client, admin_headers, seeded):
    fid = seeded["fabric"]["id"]
    r = client.delete(f"/api/v1/fabrics/{fid}", headers=admin_headers)
    assert r.status_code == 200
    # Archived fabric hidden from default list
    listing = client.get("/api/v1/fabrics")
    assert all(f["id"] != fid for f in listing.json()["items"])
    # ...but visible with include_inactive
    listing2 = client.get("/api/v1/fabrics?include_inactive=true")
    assert any(f["id"] == fid for f in listing2.json()["items"])


def test_hard_delete_blocked_with_variants(client, admin_headers, seeded):
    fid = seeded["fabric"]["id"]
    r = client.delete(f"/api/v1/fabrics/{fid}?hard=true", headers=admin_headers)
    assert r.status_code == 409


def test_missing_required_field(client, admin_headers):
    r = client.post("/api/v1/fabrics", json={}, headers=admin_headers)
    assert r.status_code == 422


def test_search_by_name_and_id(client, seeded):
    r = client.get("/api/v1/fabrics?search=Poplin")
    assert r.json()["total"] >= 1
    code = seeded["fabric"]["fabric_id"]
    r2 = client.get(f"/api/v1/fabrics?fabric_id={code}")
    assert r2.json()["total"] == 1
    r3 = client.get(f"/api/v1/fabrics/by-code/{code}")
    assert r3.status_code == 200


def test_category_and_type_filter(client, seeded):
    cat_id = seeded["category"]["id"]
    r = client.get(f"/api/v1/fabrics?category_id={cat_id}")
    assert r.json()["total"] >= 1
    r2 = client.get("/api/v1/fabrics?fabric_type=Poplin")
    assert r2.json()["total"] >= 1


def test_colour_and_price_filter(client, seeded):
    r = client.get("/api/v1/fabrics?colour=Navy")
    assert r.json()["total"] >= 1
    r2 = client.get("/api/v1/fabrics?min_price=430&max_price=460")
    assert r2.json()["total"] >= 1
    r3 = client.get("/api/v1/fabrics?min_price=9999")
    assert r3.json()["total"] == 0


def test_availability_filter(client, seeded):
    r = client.get("/api/v1/fabrics?availability=AVAILABLE")
    assert r.json()["total"] >= 1


def test_pagination_and_sort(client, admin_headers):
    for i in range(5):
        client.post("/api/v1/fabrics", json={"fabric_name": f"Sort-{i}"}, headers=admin_headers)
    r = client.get("/api/v1/fabrics?page=1&page_size=2&sort=name&order=asc")
    assert r.json()["page_size"] == 2
    assert r.json()["pages"] >= 3
    names = [f["fabric_name"] for f in r.json()["items"]]
    assert names == sorted(names)


def test_response_format(client, seeded):
    r = client.get("/api/v1/fabrics")
    body = r.json()
    assert set(body.keys()) == {"items", "total", "page", "page_size", "pages"}
