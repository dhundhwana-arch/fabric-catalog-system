# Image Management

- Types: `FRONT`, `CLOSE_UP`, `TEXTURE`, `SWATCH`, `OTHER`.
- Two ways to attach: register an existing URL (`POST /api/v1/images`) or
  upload a file (`POST /api/v1/images/upload`, multipart).
- Upload validation: JPEG/PNG/WebP only (MIME + magic-byte check), max 5 MB
  (configurable via `MAX_UPLOAD_BYTES`). Unsupported/fake files are rejected
  (415/422).
- Storage: local disk under `UPLOAD_DIR`, served at `/uploads/`. Filenames
  are generated (`<uuid>-<sha256-prefix>.ext`) — user filenames are never
  trusted. The DB stores only `image_url` + `storage_reference`, never
  binaries. Swapping in Cloudinary/S3 later only requires changing the
  storage step; the API and DB contract stay the same.
- Only real business photos should be used for production records. When no
  photo exists the UI shows an honest "No photo yet" placeholder — never a
  stock photo presented as inventory.
