# Portable Catalog Text Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Normalize every catalog product's public text, reconstruct medicine content from the preserved health.kr source payloads, and publish a versioned data package that another project or AI API workflow can consume without project-specific cleanup.

**Architecture:** Keep the existing 776-row canonical catalog as the compatibility source, but replace damaged display fields from the preserved upstream detail cache. A shared Python normalizer produces both backward-compatible plain text and structured paragraph/table blocks. A separate exporter creates a versioned, schema-validated portable package and an NDJSON AI-ingestion form; publication checks reject damaged text before build or deployment.

**Tech Stack:** Python 3 standard library, lxml, JSON Schema-compatible documents, Node.js synchronization scripts, TypeScript/React rendering, Node test runner, Python unittest, Playwright.

---

### Task 1: Capture the corruption inventory

**Files:**
- Create: `scripts/audit_catalog_text.py`
- Create: `tests/test_catalog_text_audit.py`
- Create: `etc/text-normalization/catalog-text-audit.json`

- [ ] Write tests that detect literal health.kr `br` separators, residual HTML, replacement characters, zero-width characters, malformed numeric ranges, trailing ingredient separators, and copied UI labels.
- [ ] Run `python -m unittest tests.test_catalog_text_audit -v` and confirm the tests fail because the auditor does not exist.
- [ ] Implement recursive public-field auditing while excluding URLs and explicitly preserved raw provenance payloads.
- [ ] Run the auditor against all 776 products and record counts and per-product findings.

### Task 2: Build one reusable health.kr rich-text normalizer

**Files:**
- Create: `lib/catalog_text_normalization.py`
- Create: `tests/test_catalog_text_normalization.py`
- Modify: `scripts/health_enrichment.py`
- Modify: `scripts/collect_kpic_details_part2.py`

- [ ] Add failing cases for `brbr<P></P>`, standalone legacy `.br`, nested tables, non-breaking and zero-width spaces, numeric ranges such as `50 ? 79`, formulas such as `[140 ? 연령]`, and idempotence.
- [ ] Run `python -m unittest tests.test_catalog_text_normalization -v` and confirm the expected failures.
- [ ] Implement `normalize_health_text()` and `parse_health_rich_text()` with ordered paragraph and table blocks.
- [ ] Replace duplicate cleaning implementations in both health.kr collectors with the shared normalizer.
- [ ] Verify that raw upstream values remain preserved separately from normalized public values.

### Task 3: Rebuild all canonical official content

**Files:**
- Create: `scripts/normalize_catalog_content.py`
- Create: `tests/test_normalize_catalog_content.py`
- Modify: `data/enrichment-queue.json`
- Modify: `data/enrichment-queue.csv`
- Modify: `public/data/enrichment-queue.json`
- Modify: `public/data/enrichment-queue.csv`

- [ ] Test loading an upstream cache entry by `official_item_seq`, updating existing plain-text fields, generating structured content, cleaning ingredient arrays and interaction cells, and preserving retail and provenance fields byte-for-byte.
- [ ] Run the test before implementation and confirm it fails.
- [ ] Implement deterministic reconstruction for every confirmed product and a safe fallback for unmatched or uncached products.
- [ ] Back up the canonical JSON and CSV under `etc/text-normalization/backups/` before materialization.
- [ ] Materialize all 776 rows and require one audit result per product.

### Task 4: Publish the cross-project data contract

**Files:**
- Create: `scripts/export_portable_catalog.py`
- Create: `tests/test_portable_catalog.py`
- Create: `data/portable/v1/products.json`
- Create: `data/portable/v1/products.ndjson`
- Create: `data/portable/v1/schema.json`
- Create: `data/portable/v1/manifest.json`
- Create: `data/portable/v1/README.md`
- Modify: `scripts/sync-public-catalog.mjs`

- [ ] Define a versioned record with stable product identity, display data, media provenance, medicine identity, structured medicine content, quality state, source links, and update timestamps.
- [ ] Add tests for exactly 776 unique products, schema-required fields, no raw HTML or damaged separators in portable text, deterministic output, SHA-256 manifest hashes, and one-line-valid NDJSON.
- [ ] Export every product, using `null` rather than invented medicine content for non-matches.
- [ ] Include an `ai_context` field assembled only from normalized facts and source URLs so AI callers do not need to parse the application schema.
- [ ] Copy the package to `public/data/portable/v1/` during catalog synchronization.

### Task 5: Render normalized structure instead of flattened source text

**Files:**
- Modify: `types/catalog.ts`
- Modify: `components/catalog/ProductModal.tsx`
- Modify: `app/globals.css`
- Modify: `tests/rendered-html.test.mjs`
- Modify: `tests/catalog-utils.test.ts`

- [ ] Add the structured paragraph/table block types.
- [ ] Add failing render assertions that literal `br` is absent and dosage tables use semantic table markup.
- [ ] Render structured blocks when available and retain normalized plain text as a compatibility fallback.
- [ ] Verify accessible headings, table headers, mobile overflow, and unchanged source links.

### Task 6: Make text quality a publication gate

**Files:**
- Modify: `package.json`
- Modify: `scripts/check-publication-gate.mjs`
- Modify: `DATA_POLICY.md`
- Create: `docs/catalog-data-contract.md`

- [ ] Add `catalog:text:normalize`, `catalog:text:audit`, and `catalog:portable:export` commands.
- [ ] Make prebuild fail when counts, schema, hashes, or normalized-text invariants fail.
- [ ] Document raw-versus-normalized fields, compatibility guarantees, source attribution, AI API ingestion, versioning, and regeneration commands.
- [ ] Verify a fresh checkout can regenerate the same portable package from canonical data and preserved source cache.

### Task 7: Verify every product and deploy

**Files:**
- Modify: `tests/product-images.e2e.mjs` or create `tests/product-content.e2e.mjs`
- Create: `etc/text-normalization/product-content-browser-local.json`
- Create: `etc/text-normalization/product-content-browser-production.json`

- [ ] Run unit tests, type checking, lint, text audit, portable-package validation, static build, and image audit.
- [ ] In a real browser, open all 776 product detail modals and assert no damaged marker is visible; verify structured content for all 458 confirmed medicines and empty-state behavior for the remaining products.
- [ ] Deploy to the approved production Vercel project only after every gate passes.
- [ ] Repeat the 776-product browser audit at `https://pharmacy-product-catalog.vercel.app/` and compare the served manifest hash with the canonical manifest.

