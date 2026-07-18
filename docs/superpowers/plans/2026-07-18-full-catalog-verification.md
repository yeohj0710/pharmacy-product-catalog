# Full Catalog Verification and Production Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the 776-product canonical catalog, prove all 95 field names were reviewed for every product, correct official matches, structured medication content, and product images from exact public sources, then push and deploy the verified result to production.

**Architecture:** Preserve the restored production payload as an immutable baseline, generate an auditable per-product/per-field ledger, and keep research batches isolated from canonical writes. Matching, rich-text normalization, and image verification expose deterministic validators; the main agent alone merges two-pass review results and releases generated artifacts after local and production gates pass.

**Tech Stack:** Bundled Python 3.12.13 with Pillow 12.2.0 and lxml 6.0.2, existing `lib/official_data` and catalog normalizers, JSON Schema-compatible documents, bundled Node.js 24.14.0, TypeScript/React/Next.js, Playwright, Git, GitHub remote, and Vercel production deployment.

---

## File structure

- `lib/catalog_review/__init__.py`: public review-domain exports.
- `lib/catalog_review/baseline.py`: production restore validation, field-union discovery, and immutable hashes.
- `lib/catalog_review/ledger.py`: 95-field review records, state transitions, batch coverage, and merge validation.
- `lib/catalog_review/source_routing.py`: product-domain classification and allowed evidence-source tiers.
- `lib/catalog_review/official_match.py`: evidence-based official match decisions and conflict checks.
- `lib/catalog_review/image_validation.py`: remote image fetch, decode, dimensions, hashes, source tier, and duplicate checks.
- `scripts/restore_production_catalog.py`: restore the ignored canonical JSON from production without trusting it until validated.
- `scripts/prepare_full_catalog_review.py`: create four 194-product queues and initial field-review ledgers.
- `scripts/validate_catalog_review_batch.py`: reject incomplete, conflicting, or evidence-free batch reviews.
- `scripts/merge_full_catalog_reviews.py`: combine two-pass reviews and materialize approved changes atomically.
- `scripts/refresh_kpic_content.py`: resumable Korea Pharmaceutical Information Center page refresh and structured normalization.
- `scripts/audit_full_catalog.py`: final 776-row, 95-field, match, content, image, provenance, and baseline-preservation gate.
- `schemas/catalog-review-ledger.schema.json`: stable review record contract.
- `schemas/catalog-canonical-fields.json`: checked-in 95-field union and conditional-field rules.
- `tests/test_catalog_review_baseline.py`: restore and baseline invariants.
- `tests/test_catalog_review_ledger.py`: ledger and batch invariants.
- `tests/test_catalog_review_matching.py`: exact identity and conflict behavior.
- `tests/test_catalog_review_images.py`: image response and duplicate behavior.
- `tests/test_refresh_kpic_content.py`: rich source parsing and resume behavior.
- `tests/full-catalog-production.e2e.mjs`: local and production all-product browser verification.
- `data/review/v1/catalog-review-ledger.ndjson`: committed final one-line-per-product review evidence.
- `data/review/v1/catalog-review-summary.json`: release counts, exceptions, and hashes.
- `etc/catalog-verification/`: ignored baseline, raw source cache, batch queues, reviewer outputs, backups, and browser evidence.

## Task 1: Establish the supported runtime and restore an immutable baseline

**Files:**
- Create: `lib/catalog_review/__init__.py`
- Create: `lib/catalog_review/baseline.py`
- Create: `scripts/restore_production_catalog.py`
- Create: `tests/test_catalog_review_baseline.py`
- Create: `schemas/catalog-canonical-fields.json`
- Create at runtime: `etc/catalog-verification/baseline-manifest.json`
- Create at runtime: `data/enrichment-queue.json`

- [ ] **Step 1: Select the bundled Node.js 24 runtime and verify tools**

Run:

```powershell
$env:PATH = 'C:\Users\hjyeo\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin;' + $env:PATH
node --version
python --version
git status --short --branch
```

Expected: Node reports `v24.14.0`, Python is at least 3.12, and only the approved design/plan documentation changes are present.

- [ ] **Step 2: Write failing baseline tests**

Create `tests/test_catalog_review_baseline.py` with these cases:

```python
import unittest

from lib.catalog_review.baseline import validate_baseline


class CatalogBaselineTests(unittest.TestCase):
    def test_accepts_776_rows_with_conditional_official_content(self):
        rows = [
            {"id": f"p-{index}", "source_order": index + 1, "name": "상품", "official_match_status": "confirmed", "official_content": {}}
            if index < 458
            else {"id": f"p-{index}", "source_order": index + 1, "name": "상품", "official_match_status": "not_applicable"}
            for index in range(776)
        ]
        expected_fields = {"id", "name", "official_content", "official_match_status", "source_order"}
        result = validate_baseline(rows, expected_count=776, expected_field_union=expected_fields)
        self.assertEqual(set(result["field_union"]), expected_fields)
        self.assertEqual(result["row_field_count_distribution"], {4: 318, 5: 458})

    def test_rejects_duplicate_ids(self):
        with self.assertRaisesRegex(ValueError, "duplicate product IDs"):
            validate_baseline([{"id": "same"}, {"id": "same"}], expected_count=2)

    def test_rejects_unexpected_conditional_field_pattern(self):
        rows = [{"id": "a", "official_match_status": "not_applicable", "official_content": {}}]
        with self.assertRaisesRegex(ValueError, "official_content"):
            validate_baseline(rows, expected_count=1)
```

- [ ] **Step 3: Run the tests and confirm the missing module failure**

Run: `python -m unittest tests.test_catalog_review_baseline -v`

Expected: FAIL because `lib.catalog_review.baseline` does not exist.

- [ ] **Step 4: Implement baseline validation and hashing**

Create `lib/catalog_review/baseline.py` with `validate_baseline(rows, expected_count, expected_field_union=None)`, `canonical_json_sha256(rows)`, and `field_schema(rows)`. `validate_baseline` must require the expected row count, unique non-empty IDs, integer source order matching file order, the supplied field union, and `official_content` only on `official_match_status == "confirmed"` rows. The production restore command passes the fixed 95-name union derived from its checked-in schema snapshot; small unit-test fixtures pass their own expected union. Hash JSON using UTF-8, `ensure_ascii=False`, compact separators, and no key sorting so the original order is protected.

Use this exact hash implementation:

```python
def canonical_json_sha256(rows: list[dict]) -> str:
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
```

- [ ] **Step 5: Check in the observed canonical field contract**

Create `schemas/catalog-canonical-fields.json` with `schema_version: "1.0"`, the alphabetically sorted 95-field union observed on 2026-07-18, and one conditional rule: `official_content` is required exactly when `official_match_status` is `confirmed`. Include the two accepted row field counts, 94 and 95. Tests load this file and assert it contains 95 unique names including all seven `app_*` originals, all original Firestore fields, image fields, official fields, and `official_content`.

- [ ] **Step 6: Implement a safe production restore command**

Create `scripts/restore_production_catalog.py` with defaults:

```python
DEFAULT_URL = "https://pharmacy-product-catalog.vercel.app/data/enrichment-queue.json"
DEFAULT_OUTPUT = ROOT / "data/enrichment-queue.json"
DEFAULT_MANIFEST = ROOT / "etc/catalog-verification/baseline-manifest.json"
```

Download to a sibling `.download` file, parse and validate against `schemas/catalog-canonical-fields.json` before replacement, write a manifest containing URL, HTTP status, ETag, Last-Modified, byte SHA-256, canonical JSON SHA-256, count, field union, field-count distribution, and retrieval time, then use `Path.replace()` for the final atomic move. Never log response bodies or credentials.

- [ ] **Step 7: Run tests, restore the baseline, and inspect hashes**

Run:

```powershell
python -m unittest tests.test_catalog_review_baseline -v
python scripts/restore_production_catalog.py
Get-Content -LiteralPath 'etc\catalog-verification\baseline-manifest.json' -Encoding utf8 -Raw
```

Expected: all baseline tests pass; the manifest reports 776 rows, a 95-field union, 318 rows with 94 fields, and 458 rows with 95 fields.

- [ ] **Step 8: Commit the foundation without ignored data**

```powershell
git add lib/catalog_review/__init__.py lib/catalog_review/baseline.py scripts/restore_production_catalog.py tests/test_catalog_review_baseline.py schemas/catalog-canonical-fields.json docs/superpowers/specs/2026-07-18-full-catalog-verification-design.md docs/superpowers/plans/2026-07-18-full-catalog-verification.md
git commit -m "feat: establish catalog verification baseline"
```

## Task 2: Define the 95-field review ledger and four exclusive batches

**Files:**
- Create: `schemas/catalog-review-ledger.schema.json`
- Create: `lib/catalog_review/ledger.py`
- Create: `scripts/prepare_full_catalog_review.py`
- Create: `scripts/validate_catalog_review_batch.py`
- Create: `tests/test_catalog_review_ledger.py`
- Create at runtime: `etc/catalog-verification/batches/batch-01.json` through `batch-04.json`

- [ ] **Step 1: Write failing ledger coverage tests**

Create tests that assert:

```python
record = make_review_record(product, field_union, baseline_sha256="abc", reviewer="agent-1")
self.assertEqual(set(record["field_reviews"]), set(field_union))
self.assertEqual(record["field_reviews"]["official_content"]["applicability"], "not_applicable")
self.assertEqual(split_batch_sizes(list(range(776)), batch_count=4), [194, 194, 194, 194])
```

Also require `validate_batch` to reject a missing product, duplicate ID, unknown field name, `pending` decision, correction without at least one opened source URL, mismatched original value, and a product outside the assigned range.

- [ ] **Step 2: Run the ledger tests and verify failure**

Run: `python -m unittest tests.test_catalog_review_ledger -v`

Expected: FAIL because ledger functions do not exist.

- [ ] **Step 3: Implement explicit ledger states**

Create `lib/catalog_review/ledger.py` with these enums encoded as constants:

```python
FIELD_DECISIONS = {"pending", "verified", "corrected", "not_applicable", "verified_exception"}
REVIEW_DIMENSIONS = (
    "identity", "capacity", "category", "price_preservation",
    "official_match", "official_content", "image", "provenance",
)
```

Each field review must contain `original_value_sha256`, `decision`, `applicability`, `method`, `evidence_ids`, `reviewer`, `reviewed_at`, and `reason`. Keep large original values out of the committed ledger; hash them and record before/after values only for corrections.

- [ ] **Step 4: Add the JSON schema**

Define required top-level keys `schema_version`, `catalog_product_id`, `source_order`, `baseline_sha256`, `field_reviews`, `dimensions`, `corrections`, `evidence`, `first_pass`, `second_pass`, and `final_decision`. Set `additionalProperties: false` at every stable object boundary and restrict final decisions to the five review states.

- [ ] **Step 5: Generate deterministic queues**

Implement `scripts/prepare_full_catalog_review.py` to read the ignored baseline, derive the sorted 95-field union, create four contiguous ranges `1-194`, `195-388`, `389-582`, and `583-776`, and write exact IDs plus review scaffolds. Assert that the ordered union equals the baseline IDs.

- [ ] **Step 6: Validate generated batches**

Run:

```powershell
python -m unittest tests.test_catalog_review_ledger -v
python scripts/prepare_full_catalog_review.py
python scripts/validate_catalog_review_batch.py --queue etc/catalog-verification/batches/batch-01.json --allow-pending
```

Expected: tests pass, each queue contains 194 unique IDs, and the preparation summary reports 776/776 coverage and 95 review keys per product.

- [ ] **Step 7: Commit ledger infrastructure**

```powershell
git add schemas/catalog-review-ledger.schema.json lib/catalog_review/ledger.py scripts/prepare_full_catalog_review.py scripts/validate_catalog_review_batch.py tests/test_catalog_review_ledger.py
git commit -m "feat: add full catalog review ledger"
```

## Task 3: Replace score-only official matching with evidence decisions

**Files:**
- Create: `lib/catalog_review/source_routing.py`
- Create: `lib/catalog_review/official_match.py`
- Create: `tests/test_catalog_review_matching.py`
- Modify: `lib/official_data/matching.py`
- Modify: `scripts/refresh_corrected_official_matches.py`
- Modify: `scripts/apply_official_rematch_reviews.py`

- [ ] **Step 1: Write failing source-routing and evidence-decision tests**

Cover domain classification for licensed medicine, quasi-drug, health functional food, food, medical device, cosmetic, and general goods. Require each domain to return an ordered list of allowed source tiers and prohibit a Korea Pharmaceutical Information Center `not_found` result from automatically classifying a supplement, device, cosmetic, or general good as globally not found.

Also cover exact identifier acceptance, exact normalized name plus compatible manufacturer/form/pack acceptance, strength conflict, dosage-form conflict, manufacturer conflict, flavor/variant conflict, export-only rejection, retail capacity versus ingredient strength, and duplicate official record pack support.

Use explicit cases such as:

```python
decision = decide_official_match(
    catalog={"name": "후시딘연고", "capacity": "5g"},
    official={"item_name": "후시딘연고", "item_seq": "A11A0570A0226", "dosage_form": "연고제", "pack_unit": "5g,10g"},
    evidence={"opened_source_url": "https://health.kr/searchDrug/result_drug.asp?drug_cd=A11A0570A0226"},
)
self.assertEqual(decision.status, "confirmed")
self.assertIn("pack_unit", decision.matched_fields)
```

and require a `review_required` result when `capacity="60포"` is paired with a record whose pack unit cannot prove 60포.

- [ ] **Step 2: Run routing and matching tests and verify failure**

Run: `python -m unittest tests.test_catalog_review_matching -v`

Expected: FAIL because `classify_product_domain` and `decide_official_match` are missing.

- [ ] **Step 3: Implement domain routing and allowed source tiers**

Create `lib/catalog_review/source_routing.py` with `ProductDomain` and `SourceTier` enums plus `classify_product_domain(product)` and `allowed_source_tiers(domain)`. Use category, regulatory identifiers, dosage-form cues, and explicit evidence; ambiguous classification returns `review_required` rather than guessing. The ordered routes are regulatory/Korea Pharmaceutical Information Center for medicines, MFDS/HACCP/manufacturer for supplements and foods, MFDS/manufacturer/authorized distributor for devices, and manufacturer/official store/stable retailer for cosmetics and general goods.

- [ ] **Step 4: Implement typed match evidence**

Implement dataclasses `OfficialCandidate`, `MatchEvidence`, `MatchConflict`, and `MatchDecision`. `confirmed` requires either a matching identifier or the complete compatible identity tuple. Fuzzy score remains diagnostic only. Return matched fields, conflicts, rejected alternatives, source URL, and reason.

- [ ] **Step 5: Integrate the decision engine without weakening old safeguards**

Have existing matching and rematch scripts call `decide_official_match`. Preserve current candidates, but clear official content and official images whenever the new result is not `confirmed`. A manual approval must still pass hard identity conflicts; reviewer input cannot override a strength, form, manufacturer, or package conflict without new source evidence.

- [ ] **Step 6: Run routing, matching, and existing official tests**

Run:

```powershell
python -m unittest tests.test_catalog_review_matching tests.test_official_data tests.test_kpic_images tests.test_merge_kpic_details -v
```

Expected: all tests pass and score-only confirmation is impossible.

- [ ] **Step 7: Commit matching changes**

```powershell
git add lib/catalog_review/source_routing.py lib/catalog_review/official_match.py lib/official_data/matching.py scripts/refresh_corrected_official_matches.py scripts/apply_official_rematch_reviews.py tests/test_catalog_review_matching.py
git commit -m "fix: require evidence for official matches"
```

## Task 4: Recollect and normalize complete Korea Pharmaceutical Information Center content

**Files:**
- Create: `scripts/refresh_kpic_content.py`
- Create: `tests/test_refresh_kpic_content.py`
- Create: `tests/fixtures/kpic/rich-content-page.html`
- Modify: `lib/catalog_text_normalization.py`
- Modify: `scripts/normalize_catalog_content.py`
- Modify: `scripts/audit_catalog_text.py`
- Create at runtime: `etc/catalog-verification/kpic-cache/`

- [ ] **Step 1: Add a fixture containing difficult rich content**

The fixture must include nested paragraphs, numbered lists, `br`, non-breaking and zero-width spaces, `rowspan`/`colspan` tables, a `50 ~ 79` range, a `[140 - 연령]` formula, ingredient rows, and repeated UI labels. The fixture contains fabricated test medicine text, not copied production content.

- [ ] **Step 2: Write failing parser and audit tests**

Require ordered paragraph/list/table blocks, expanded table cells, preserved Korean units and formulas, deterministic plain text, idempotence, no HTML, no literal `br`, no replacement/zero-width characters, and a source hash attached to every normalized section.

- [ ] **Step 3: Run tests and verify the new cases fail**

Run: `python -m unittest tests.test_refresh_kpic_content tests.test_catalog_text_normalization tests.test_catalog_text_audit -v`

Expected: at least the rich table and section provenance cases fail.

- [ ] **Step 4: Implement the resumable content refresher**

`scripts/refresh_kpic_content.py` reads only newly confirmed rows, retrieves the exact `official_source_url` with a 0.8-second minimum delay, writes raw bytes and a metadata sidecar under ignored cache storage, skips unchanged source hashes, and saves a checkpoint after each product. It records HTTP status, effective URL, content type, byte hash, retrieval time, parser version, and per-section outcome.

- [ ] **Step 5: Extend the shared normalizer**

Implement semantic block parsing in `lib/catalog_text_normalization.py`. Plain text is produced by `blocks_to_text(blocks)` and must not have a separate cleaning path. Preserve raw values in ignored cache; canonical fields receive only normalized values plus `official_content` blocks and field provenance.

- [ ] **Step 6: Strengthen text auditing**

For every confirmed row require non-empty efficacy, dosage, precautions, storage, manufacturer, dosage form, pack unit, exact source URL, and normalized block structure. Flag source text that is suspiciously shorter than its raw extracted text, loses table cells, repeats the same paragraph, or contains malformed range separators.

- [ ] **Step 7: Run focused and regression tests**

Run:

```powershell
python -m unittest tests.test_refresh_kpic_content tests.test_catalog_text_normalization tests.test_normalize_catalog_content tests.test_catalog_text_audit -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit the content pipeline**

```powershell
git add scripts/refresh_kpic_content.py tests/test_refresh_kpic_content.py tests/fixtures/kpic/rich-content-page.html lib/catalog_text_normalization.py scripts/normalize_catalog_content.py scripts/audit_catalog_text.py
git commit -m "fix: preserve structured official medication content"
```

## Task 5: Build strict live image validation and exact-product evidence

**Files:**
- Create: `lib/catalog_review/image_validation.py`
- Create: `tests/test_catalog_review_images.py`
- Modify: `scripts/audit_catalog_images.py`
- Modify: `scripts/validate_image_research_batch.py`
- Modify: `scripts/enforce_image_research_approvals.py`

- [ ] **Step 1: Write failing image validator tests**

Use mocked responses to cover redirects, HTML masquerading as an image, zero-byte bodies, unsupported formats, tiny placeholders, stable PNG/JPEG/WebP images, exact duplicate SHA-256 across unrelated products, same image across legitimate duplicate SKUs, search proxy hosts, missing product-page evidence, and source-tier ordering.

Require this result shape:

```python
ImageValidation(
    status="verified",
    effective_url="https://manufacturer.example/product.jpg",
    content_type="image/jpeg",
    width=800,
    height=800,
    byte_sha256="0" * 64,
    source_tier="manufacturer_official",
    failures=(),
)
```

- [ ] **Step 2: Run image tests and verify failure**

Run: `python -m unittest tests.test_catalog_review_images -v`

Expected: FAIL because the validator module is absent.

- [ ] **Step 3: Implement network and binary validation**

Fetch with bounded redirects, explicit timeouts, a catalog user agent, and a maximum body size. Decode PNG/JPEG/WebP with the bundled Pillow 12.2.0 runtime and verify decoded dimensions. Reject bodies below 2 KiB, dimensions below 200×200 unless an explicit official-source exception is recorded, HTML/SVG placeholders, and known search-thumbnail/proxy URLs.

- [ ] **Step 4: Implement source and identity requirements**

Define source tiers `official_regulatory`, `manufacturer_official`, `official_store`, `authorized_distributor`, `major_retailer`, and `specialist_seller`. Reject `search_result`, `news`, `blog`, and `social`. Every accepted candidate needs the opened product page, visible identity evidence, checked fields, reviewer, and timestamp.

- [ ] **Step 5: Add duplicate and near-duplicate auditing**

Record byte SHA-256 for all images and perceptual hash when Pillow supports it. Duplicate content across unrelated normalized names is a release failure. Duplicate SKUs may share an image only when their visible package quantity does not conflict and the ledger records the reason.

- [ ] **Step 6: Run focused and existing image tests**

Run:

```powershell
python -m unittest tests.test_catalog_review_images tests.test_image_research tests.test_kpic_images tests.test_secondary_images tests.test_naver_images tests.test_merge_secondary_images -v
```

Expected: all tests pass; search proxies and weak evidence cannot be approved.

- [ ] **Step 7: Commit image validation**

```powershell
git add lib/catalog_review/image_validation.py scripts/audit_catalog_images.py scripts/validate_image_research_batch.py scripts/enforce_image_research_approvals.py tests/test_catalog_review_images.py
git commit -m "fix: enforce exact product image evidence"
```

## Task 6: Implement two-pass batch validation and canonical merge

**Files:**
- Create: `scripts/merge_full_catalog_reviews.py`
- Create: `tests/test_merge_full_catalog_reviews.py`
- Modify: `scripts/validate_catalog_review_batch.py`
- Create at runtime: `etc/catalog-verification/reviews/first-pass-01.json` through `first-pass-04.json`
- Create at runtime: `etc/catalog-verification/reviews/second-pass-01.json` through `second-pass-04.json`

- [ ] **Step 1: Write failing merge tests**

Require rejection of incomplete coverage, self-approved high-risk rows, reviewer disagreement, a correction without matching baseline hash, a changed original field, a confirmed match with unresolved conflicts, a non-official image with one review, and a verified exception without recorded search attempts.

- [ ] **Step 2: Run merge tests and verify failure**

Run: `python -m unittest tests.test_merge_full_catalog_reviews -v`

Expected: FAIL because the merge script is absent.

- [ ] **Step 3: Implement review agreement rules**

High-risk rows include all matches below 95, all shared official-record groups, all non-official images, all corrected names/capacities/categories, all `review_required`/`not_found`, and all verified exceptions. They require two distinct reviewers and matching final values. Low-risk unchanged baseline fields may use deterministic automated verification plus one reviewer.

- [ ] **Step 4: Implement an atomic canonical merge**

Load the immutable baseline, verify its hash, apply only approved `corrections`, match decisions, normalized content, and image decisions, and re-run baseline original-field comparison before writing. Write a timestamped ignored backup and replace canonical JSON only after all 776 records validate.

- [ ] **Step 5: Run merge tests**

Run: `python -m unittest tests.test_merge_full_catalog_reviews tests.test_catalog_review_ledger -v`

Expected: all tests pass.

- [ ] **Step 6: Commit merge infrastructure**

```powershell
git add scripts/merge_full_catalog_reviews.py scripts/validate_catalog_review_batch.py tests/test_merge_full_catalog_reviews.py
git commit -m "feat: merge two-pass catalog reviews safely"
```

## Task 7: Execute first-pass review for all 776 products in parallel

**Files:**
- Read: `etc/catalog-verification/batches/batch-01.json` through `batch-04.json`
- Create: `etc/catalog-verification/reviews/first-pass-01.json` through `first-pass-04.json`

- [ ] **Step 1: Dispatch four exclusive work streams**

Assign ranges 1-194, 195-388, 389-582, and 583-776 to the main agent plus three subagents. Each reviewer may write only its assigned first-pass file. Instruct reviewers to open every accepted source page and image, record all 95 field decisions, and leave uncertain decisions as `verified_exception` rather than guessing.

- [ ] **Step 2: Review official identity and content for every assigned row**

For each row, classify the product domain, validate or reject its current official match, inspect every populated official field against the opened source, and record applicability for every empty official field. Refresh exact confirmed source pages through the resumable collector.

- [ ] **Step 3: Review display fields and preservation fields**

Compare product name, capacity, category, and existing correction evidence to official/manufacturer/product pages. Verify all original Firestore/app values by baseline hash and ensure price is preserved as a recorded snapshot rather than a current-market claim.

- [ ] **Step 4: Review every image**

Open the product page and original image, compare visible identity and package details, run the live image validator, reject weak sources, and research missing/failed images in the defined source order. Record all failed attempts for exceptions.

- [ ] **Step 5: Validate each first-pass file**

Run once per batch:

```powershell
python scripts/validate_catalog_review_batch.py --queue etc/catalog-verification/batches/batch-01.json --review etc/catalog-verification/reviews/first-pass-01.json
```

Expected: 194/194 products, 18,430 field reviews per batch, zero pending decisions, no out-of-range IDs, and zero schema errors.

- [ ] **Step 6: Confirm global first-pass coverage**

Run: `python scripts/validate_catalog_review_batch.py --all-first-pass etc/catalog-verification/reviews`

Expected: 776 unique products, 73,720 field reviews, and no duplicate or missing IDs.

## Task 8: Perform rotated second-pass review and resolve disagreements

**Files:**
- Read: all first-pass review files
- Create: all second-pass review files
- Create at runtime: `etc/catalog-verification/reviews/disagreements.json`

- [ ] **Step 1: Rotate ownership**

Assign first-pass batch 01 to reviewer 02, batch 02 to reviewer 03, batch 03 to reviewer 04, and batch 04 to reviewer 01. No reviewer may approve its own high-risk decisions.

- [ ] **Step 2: Re-open high-risk official matches and images**

Independently verify the 41 current sub-95 matches, 38 shared official-record groups, all current review/not-found rows, every display correction, all non-official images, and all verified exceptions. Do not rely only on first-pass notes.

- [ ] **Step 3: Add deterministic sampling of low-risk rows**

For each batch, select every tenth source-order row plus a seeded sample derived from the baseline SHA-256. Re-open at least 20 low-risk confirmed official rows and 20 official images per batch. Any sampled failure expands second review to the entire affected source/match class.

- [ ] **Step 4: Record and resolve disagreements**

Generate `disagreements.json` containing both decisions and evidence. The main agent re-opens the sources and records a third decision. Unresolved cases become `verified_exception`; they cannot remain confirmed.

- [ ] **Step 5: Validate second-pass coverage**

Run: `python scripts/validate_catalog_review_batch.py --all-second-pass etc/catalog-verification/reviews`

Expected: every high-risk row has two distinct reviewers, every deterministic sample is present, and unresolved disagreement count is zero.

## Task 9: Materialize verified data and publish the review ledger

**Files:**
- Create: `scripts/audit_full_catalog.py`
- Create: `tests/test_audit_full_catalog.py`
- Modify at runtime: `data/enrichment-queue.json`
- Create: `data/review/v1/catalog-review-ledger.ndjson`
- Create: `data/review/v1/catalog-review-summary.json`
- Regenerate: `data/portable/v1/*`
- Regenerate: `public/data/portable/v1/*`

- [ ] **Step 1: Write failing complete-release audit tests**

Create `tests/test_audit_full_catalog.py` with fixtures that fail independently for 775 products, 94 field decisions instead of 95, a pending decision, a changed original-field hash, official content on an unconfirmed row, a confirmed row without structured content, an unverified image, an unresolved reviewer disagreement, and a portable hash mismatch. Include one complete two-product fixture that passes when `expected_count=2` and the expected field union is supplied.

- [ ] **Step 2: Run the audit test and verify failure**

Run: `python -m unittest tests.test_audit_full_catalog -v`

Expected: FAIL because `scripts.audit_full_catalog` does not exist.

- [ ] **Step 3: Implement the aggregate release auditor**

Create `scripts/audit_full_catalog.py` with a pure `audit_release(baseline, final_rows, ledger, portable_manifest, expected_count, expected_fields)` function plus a CLI. Return structured findings with product ID, field, code, severity, and evidence. `--require-complete-review` exits nonzero for any missing review, changed original value, match/content inconsistency, image validation failure, unresolved disagreement, or generated-artifact mismatch.

- [ ] **Step 4: Run audit unit tests**

Run: `python -m unittest tests.test_audit_full_catalog -v`

Expected: all audit tests pass.

- [ ] **Step 5: Merge approved review results**

Run:

```powershell
python scripts/merge_full_catalog_reviews.py --baseline-manifest etc/catalog-verification/baseline-manifest.json --reviews etc/catalog-verification/reviews
```

Expected: 776 products merged, original field changes 0, pending decisions 0, unresolved disagreements 0.

- [ ] **Step 6: Refresh normalized content and audits**

Run:

```powershell
python scripts/normalize_catalog_content.py
python scripts/audit_catalog_text.py
python scripts/audit_catalog_images.py
```

Expected: no damaged text, missing confirmed sections, invalid image responses, prohibited image sources, or unrelated duplicate images.

- [ ] **Step 7: Export deterministic portable data**

Run:

```powershell
python scripts/export_portable_catalog.py
node scripts/sync-public-catalog.mjs
python scripts/export_portable_catalog.py --check
```

Expected: product count 776, JSON/NDJSON equality, manifest hashes match, and public artifacts equal canonical exports.

- [ ] **Step 8: Write the committed review evidence**

Export one compact NDJSON record per product with all 95 field decisions, evidence metadata, reviewer IDs, and final decision. Exclude ignored raw page bodies, credentials, and local file paths. Write an aggregate summary containing baseline/final hashes, corrections, match counts, image counts, source tiers, exceptions, and review coverage.

- [ ] **Step 9: Validate the complete release data**

Run: `python scripts/audit_full_catalog.py --require-complete-review`

Expected: 776/776 products, 73,720/73,720 field decisions, zero pending fields, zero original-field changes, and zero unresolved conflicts.

- [ ] **Step 10: Commit verified data and evidence**

```powershell
git add scripts/audit_full_catalog.py tests/test_audit_full_catalog.py data/review/v1 data/portable/v1 public/data/portable/v1 data/catalog-text-corrections.json data/image-manual-web-research.json data/image-visual-review.json data/image-source-overrides.json
git commit -m "data: verify all 776 catalog products"
```

## Task 10: Run full local tests and all-product browser verification

**Files:**
- Create: `tests/full-catalog-production.e2e.mjs`
- Create at runtime: `etc/catalog-verification/browser/local-results.json`
- Modify: `package.json`

- [ ] **Step 1: Add the all-product browser test**

The test loads the 776-product public payload, visits every stable product ID through the application, opens its detail view, checks the displayed name/capacity/category, validates image `naturalWidth`/`naturalHeight` when present, checks source attribution, asserts no literal HTML/`br`/replacement characters are visible, and captures console/network errors with the product ID.

- [ ] **Step 2: Add a package command**

Add:

```json
"test:catalog:e2e": "node tests/full-catalog-production.e2e.mjs"
```

- [ ] **Step 3: Run complete static gates**

Run:

```powershell
npm run typecheck
npm run test:unit
npm run lint
npm run catalog:sync
npm run build:local
```

Expected: every command exits 0.

- [ ] **Step 4: Run local browser verification**

Start the production-equivalent local server in a background process with a hidden window, wait for readiness, then run `npm run test:catalog:e2e` against the local URL.

Expected: 776 details checked, broken images 0, text defects 0, console errors 0, and failed network requests 0 except explicitly allowlisted analytics.

- [ ] **Step 5: Commit browser tests**

```powershell
git add tests/full-catalog-production.e2e.mjs package.json package-lock.json
git commit -m "test: verify every catalog product in browser"
```

## Task 11: Final audit, push, production deploy, and live verification

**Files:**
- Read: `scripts/deploy_private_catalog.ps1`
- Create at runtime: `.vercel/project.json`
- Create at runtime: `etc/catalog-verification/browser/production-results.json`

- [ ] **Step 1: Review the release diff and repository state**

Run:

```powershell
git status --short --branch
git diff --check origin/main...HEAD
git log --oneline --decorate origin/main..HEAD
```

Expected: only planned files changed, no secrets or ignored raw caches are staged, and every implementation/data commit is present.

- [ ] **Step 2: Re-run the full release gate from a clean generated state**

Run the final catalog audit, portable check, typecheck, unit tests, lint, local build, and local 776-product browser audit again. Expected: every gate exits 0 with the same final hashes.

- [ ] **Step 3: Push and verify the remote commit**

Run:

```powershell
git push origin main
git fetch origin main
git rev-parse HEAD
git rev-parse origin/main
```

Expected: both hashes are identical.

- [ ] **Step 4: Restore the ignored Vercel project link on this computer**

Run read-only identity and project discovery first:

```powershell
npx.cmd --yes vercel@56.2.1 whoami
npx.cmd --yes vercel@56.2.1 project ls
```

Expected: the authenticated account can see the project serving `pharmacy-product-catalog.vercel.app`. Then link the verified project and inspect the resulting ignored file:

```powershell
npx.cmd --yes vercel@56.2.1 link --yes --project pharmacy-product-catalog
Get-Content -LiteralPath '.vercel\project.json' -Encoding utf8 -Raw
```

Expected: non-empty `projectId` and `orgId` for the verified production project. Stop before deployment if the account, project, or alias does not match.

- [ ] **Step 5: Deploy production**

Run the repository-supported production command:

```powershell
npm run deploy:public
```

Expected: deployment succeeds and reports the verified production project and URL.

- [ ] **Step 6: Wait for a ready production deployment and verify identity**

Confirm the deployment is `READY`, capture its deployment ID and commit SHA, and fetch the production manifest. Expected: production product count, official count, image count, and file hashes equal the committed manifest.

- [ ] **Step 7: Run production all-product browser verification**

Run `tests/full-catalog-production.e2e.mjs` against `https://pharmacy-product-catalog.vercel.app/` and save evidence under ignored verification storage.

Expected: 776/776 products pass, all non-empty images decode, no damaged text appears, source links are correct, filters/downloads work, and there are no unhandled console/runtime errors.

- [ ] **Step 8: Produce the final evidence report**

Report baseline and final hashes, correction counts, official match state counts, confirmed content coverage, image source tiers and exceptions, all test/build results, commit SHA, remote verification, deployment ID/URL, production manifest equality, and 776-product browser result. Mark the goal complete only when every design release gate has direct evidence.
