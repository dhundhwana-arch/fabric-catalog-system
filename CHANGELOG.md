# Changelog

## [1.0.0] — 2026-11-16

### Added
- Complete Fabric Catalog System (Module 02): fabrics, categories, variants,
  colours, images, price history, inventory lots/movements, supplier refs.
- Database-backed permanent IDs (FAB/FVAR/FIMG/FLOT/FCAT/FPR).
- Versioned REST API under `/api/v1` with OpenAPI docs.
- Customer catalogue + admin panel (single-page app).
- Image upload with validation; JSON/CSV export.
- Admin Bearer-token auth; supplier data hidden from public API.
- 34 automated tests (all passing).
- Docs: data model, colour system, image management, inventory rules,
  API reference, installation, integration handoff.
