# Colour System

Colours live on **variants** (a colour only exists as part of a real fabric
variant — no orphan colour catalogue).

Fields: `colour_name` (e.g. "Navy Blue"), `colour_hex` (validated `#RRGGBB`,
stored uppercase), `variant_id`, `availability_status`, optional swatch image.

- `GET /api/v1/colours` returns distinct colours with variant counts and
  available-variant counts (used for filter dropdowns).
- `GET /api/v1/variants?colour=…` / `?colour_hex=…` filter by colour.
- HEX is validated with `^#[0-9A-Fa-f]{6}$`; invalid values return 422.

> **Customer notice (shown in the UI):** "Digital colour representation may
> differ from the actual physical fabric due to lighting, display settings,
> and material characteristics."

A colour is only selectable in the UI when its variant's
`availability_status` is `AVAILABLE` (or `ON_REQUEST` with a clear label).
