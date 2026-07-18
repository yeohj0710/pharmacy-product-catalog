# Pharmacy Product Catalog portable data v1

This directory is the stable cross-project data package. `products.json` is a JSON array,
`products.ndjson` contains one equivalent record per line for AI or search ingestion,
`schema.json` defines the record contract, and `manifest.json` provides counts and hashes.

Use `medicine: null` as an explicit non-match. Never infer medicine facts from the retail
name when `quality.official_match_status` is not `confirmed`. `ai_context` contains only
normalized public facts and source URLs; raw upstream HTML is intentionally excluded.

Regenerate with `python scripts/export_portable_catalog.py` after canonical normalization.
Breaking field changes require a new `data/portable/vN/` directory and schema version.
