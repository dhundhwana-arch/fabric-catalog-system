# API Documentation

Base path: `/api/v1`. Interactive docs: `/docs` (OpenAPI) and `/redoc`.
Health: `GET /health`.

## Public (no auth)

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/fabrics` | List fabrics. Query: `search`, `fabric_id`, `category_id`, `fabric_type`, `colour`, `colour_hex`, `availability`, `min_price`, `max_price`, `include_inactive`, `sort` (name/created_at/price), `order`, `page`, `page_size` |
| GET | `/api/v1/fabrics/{pk}` | Fabric detail with variants + images |
| GET | `/api/v1/fabrics/by-code/{code}` | Detail by `FAB-…` |
| GET | `/api/v1/variants` | List variants (colour/price/availability filters) |
| GET | `/api/v1/variants/{pk}` · `/by-code/{code}` | Variant detail |
| GET | `/api/v1/categories` | Active categories |
| GET | `/api/v1/colours` | Distinct colours + counts |
| GET | `/api/v1/fabrics/{pk}/images` · `/variants/{pk}/images` | Image references |
| GET | `/api/v1/prices/variants/{pk}` | Price history |
| GET | `/api/v1/inventory` · `/inventory/{variant_pk}` | Stock levels |
| GET | `/api/v1/export?format=json\|csv` | Catalogue export |

## Admin (Bearer token required)

`POST/PUT/DELETE /api/v1/fabrics`, `/variants`, `/categories`,
`POST /api/v1/images`, `POST /api/v1/images/upload`,
`POST /api/v1/prices`, `PUT /api/v1/inventory/{variant_pk}`,
`GET/POST /api/v1/suppliers` (internal procurement data).

## Examples

Create a fabric:

```bash
curl -X POST localhost:8000/api/v1/fabrics \
  -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"fabric_name":"Example Poplin","fabric_type":"Poplin"}'
```

Create a variant:

```bash
curl -X POST localhost:8000/api/v1/variants \
  -H "Authorization: Bearer $ADMIN_API_KEY" \
  -d '{"fabric_id":1,"colour_name":"Navy Blue","colour_hex":"#000080","customer_price":"450.00"}'
```

List response shape:

```json
{"items":[...],"total":1,"page":1,"page_size":20,"pages":1}
```

Errors: standard HTTP codes with `{"detail":"..."}`.
