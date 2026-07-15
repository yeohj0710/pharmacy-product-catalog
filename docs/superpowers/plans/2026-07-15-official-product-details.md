# Official Product Details Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Match the 776 catalog products to MFDS and other licensed public records, then store images, dosage, efficacy, precautions, ingredients, manufacturer, identifiers, and field-level provenance without copying protected KPIC content.

**Architecture:** Keep the retail catalog product and official regulatory product as separate entities connected by a many-to-one match record. Download public-source indexes once, score candidates locally, and call detail endpoints only for confirmed matches. Materialize confirmed fields into the site queue while retaining raw hashes, source URLs, dataset IDs, fetch dates, and review decisions.

**Tech Stack:** Python 3 standard library, MFDS/data.go.kr JSON APIs, Node.js validation tests, existing Next.js/Vinext catalog UI.

---

## File structure

- `lib/official_data/schema.py`: canonical official product, match, image, and provenance field definitions.
- `lib/official_data/normalize.py`: Korean product-name, company, dosage-form, and capacity normalization.
- `lib/official_data/sources.py`: source specifications and MFDS response parsers.
- `lib/official_data/client.py`: encoded-key HTTP client, retry, rate limiting, response cache, and hashing.
- `lib/official_data/matching.py`: candidate generation, scoring, conflict detection, and match decisions.
- `scripts/collect_official_product_data.py`: resumable 25-product batch runner.
- `scripts/materialize_official_product_data.py`: merge approved records into site JSON/CSV.
- `tests/test_official_data.py`: schema, parser, normalization, matching, resume, and materialization tests.
- `data/official-product-details.json`: unique official regulatory records.
- `data/product-official-matches.json`: one match decision per catalog product.
- `data/official-data-summary.json`: counts by source, status, and missing field.
- `etc/official-source-cache/`: ignored API responses and locally cached licensed images.
- `DATA_DICTIONARY.md`: all added fields and enumerations.
- `DATA_POLICY.md`: KPIC restriction, MFDS license, and image-publication rules.

### Task 1: Lock source policy and rich schema

**Files:**
- Create: `lib/official_data/schema.py`
- Modify: `DATA_DICTIONARY.md`
- Modify: `DATA_POLICY.md`
- Test: `tests/test_official_data.py`

- [ ] **Step 1: Write a failing schema test**

```python
def test_official_record_requires_identity_content_and_provenance():
    record = make_official_record(
        source_domain="drug",
        source_dataset_id="15095677",
        source_record_id="200808876",
        item_name="테스트정",
    )
    assert record["official_product_key"] == "drug:200808876"
    assert set(record["content"]) >= {"efficacy", "dosage", "precautions", "ingredients"}
    assert record["provenance"]["source_dataset_id"] == "15095677"
```

- [ ] **Step 2: Run the test and confirm the missing module failure**

Run: `python -m unittest tests.test_official_data.OfficialSchemaTests -v`
Expected: import failure for `lib.official_data.schema`.

- [ ] **Step 3: Implement the canonical record factory**

```python
def make_official_record(*, source_domain, source_dataset_id, source_record_id, item_name):
    return {
        "official_product_key": f"{source_domain}:{source_record_id}",
        "source_domain": source_domain,
        "item_name": item_name,
        "manufacturer": "",
        "identifiers": {"item_seq": source_record_id, "barcode": "", "standard_codes": []},
        "classification": {"category": "", "dosage_form": "", "route": "", "atc_code": ""},
        "content": {
            "appearance": "", "pack_unit": "", "storage": "", "valid_term": "",
            "efficacy": "", "dosage": "", "precautions": "", "professional_precautions": "",
            "ingredients": [], "active_ingredients": [], "consumer_guidance": {},
        },
        "images": [],
        "provenance": {
            "source_dataset_id": source_dataset_id, "source_record_id": source_record_id,
            "source_url": "", "license": "공공데이터포털 이용허락범위 제한 없음",
            "fetched_at": "", "upstream_updated_at": "", "raw_sha256": "",
        },
    }
```

- [ ] **Step 4: Document match and image states**

Use `confirmed`, `review_required`, `not_found`, `not_applicable`, and `blocked_missing_key`. Use `package`, `pill`, `label`, and `instruction` for image kinds. Store an image only with a source URL and license value.

- [ ] **Step 5: Run schema tests**

Run: `python -m unittest tests.test_official_data.OfficialSchemaTests -v`
Expected: all schema tests pass.

### Task 2: Implement licensed source adapters

**Files:**
- Create: `lib/official_data/sources.py`
- Create: `lib/official_data/client.py`
- Test: `tests/fixtures/official_api/*.json`
- Test: `tests/test_official_data.py`

- [ ] **Step 1: Add fixture parser tests**

Test these dataset IDs and records:

```python
DATASETS = {
    "15095677": "drug",
    "15075057": "easy_drug",
    "15057639": "pill_identification",
    "15095679": "quasi_drug",
    "15056760": "supplement",
    "15095680": "functional_cosmetic_report",
    "15056939": "functional_cosmetic_review",
    "15073875": "medical_device",
    "15033307": "food_image",
}
```

- [ ] **Step 2: Verify parser tests fail**

Run: `python -m unittest tests.test_official_data.SourceParserTests -v`
Expected: missing parser registry.

- [ ] **Step 3: Implement source specifications**

Each source specification must define dataset ID, endpoint, record key, query fields, output aliases, applicable domains, and whether images are pill or package images. Drug detail parsing must retain `EE_DOC_DATA`, `UD_DOC_DATA`, `NB_DOC_DATA`, and `PN_DOC_DATA` raw XML plus normalized text.

- [ ] **Step 4: Implement cached HTTP access**

Require `DATA_GO_KR_SERVICE_KEY`, cap requests at 1.5 requests/second, retry 429 and 5xx with exponential delays, atomically write cache files, and never print the service key. A missing key must write a summary with `blocked_missing_key` and leave product outputs unchanged.

- [ ] **Step 5: Run parser and client tests**

Run: `python -m unittest tests.test_official_data.SourceParserTests tests.test_official_data.ClientTests -v`
Expected: all source parser and client tests pass.

### Task 3: Build deterministic candidate matching

**Files:**
- Create: `lib/official_data/normalize.py`
- Create: `lib/official_data/matching.py`
- Test: `tests/test_official_data.py`

- [ ] **Step 1: Add normalization and scoring tests**

```python
def test_exact_name_company_and_capacity_is_confirmed():
    result = score_candidate(
        catalog={"name": "챔프시럽 해열진통", "capacity": "10포", "manufacturer_hint": "동아제약"},
        official={"item_name": "챔프시럽(아세트아미노펜)", "pack_unit": "10포", "manufacturer": "동아제약(주)"},
    )
    assert result.score >= 95
    assert result.status == "confirmed"

def test_same_name_conflict_requires_review():
    results = choose_candidate([candidate("동일제품", "10정"), candidate("동일제품", "20정")])
    assert results.status == "review_required"
```

- [ ] **Step 2: Verify tests fail**

Run: `python -m unittest tests.test_official_data.MatchingTests -v`
Expected: missing matching functions.

- [ ] **Step 3: Implement scoring**

Score exact official identifier or barcode as 100. Otherwise score normalized name up to 60, manufacturer up to 20, capacity/strength up to 15, and dosage form up to 5. Confirm only scores of 95 or higher with no competing record within three points; use `review_required` for 80–94 or conflicts; reject lower scores.

- [ ] **Step 4: Keep many retail SKUs per official item**

Store `catalog_product_id`, `official_product_key`, score components, matched fields, alternatives, decision source, reviewer, reviewed time, and notes in `product-official-matches.json`.

- [ ] **Step 5: Run matching tests**

Run: `python -m unittest tests.test_official_data.MatchingTests -v`
Expected: matching tests pass.

### Task 4: Add resumable 25-product batches

**Files:**
- Create: `scripts/collect_official_product_data.py`
- Test: `tests/test_official_data.py`

- [ ] **Step 1: Add resume and range tests**

The runner must accept `--start 0 --limit 25`, skip completed records unless `--force`, and atomically checkpoint after every product.

- [ ] **Step 2: Verify runner tests fail**

Run: `python -m unittest tests.test_official_data.RunnerTests -v`
Expected: missing runner.

- [ ] **Step 3: Implement two-phase acquisition**

Download each source index once into `etc/official-source-cache/index/`, generate local candidates for all catalog products, then fetch detailed records only for confirmed candidates. Store product errors separately so one failing API response does not abort the batch.

- [ ] **Step 4: Emit batch summary**

Report attempted, confirmed, review required, not found, not applicable, images found, complete content, API calls, cache hits, errors, and remaining products.

- [ ] **Step 5: Run runner tests**

Run: `python -m unittest tests.test_official_data.RunnerTests -v`
Expected: resume tests pass without network access.

### Task 5: Materialize site and spreadsheet-ready exports

**Files:**
- Create: `scripts/materialize_official_product_data.py`
- Modify: `types/catalog.ts`
- Modify: `lib/catalog/download.ts`
- Modify: `components/catalog/ProductModal.tsx`
- Modify: `components/catalog/ProductImage.tsx`
- Modify: `scripts/sync-public-catalog.mjs`
- Test: `tests/catalog-utils.test.ts`
- Test: `tests/test_official_data.py`

- [ ] **Step 1: Add materialization tests**

Confirmed matches must expose official product name, company, code, efficacy, dosage, precautions, ingredients, storage, package, source date, and licensed images. Review records must not overwrite a catalog field.

- [ ] **Step 2: Verify materialization tests fail**

Run: `python -m unittest tests.test_official_data.MaterializationTests -v`
Expected: missing materializer.

- [ ] **Step 3: Implement materialized exports**

Generate `data/enrichment-queue.json`, `data/enrichment-queue.csv`, `data/official-product-details.json`, `data/product-official-matches.json`, and `data/official-data-summary.json`. Preserve every existing retail field and add official fields without replacing source price or source name.

- [ ] **Step 4: Add detail sections to the site**

Show official identity, efficacy, dosage, precautions, ingredients, storage, package, image kind, source, official update date, and match confidence. Label `review_required` records clearly and keep unlicensed images hidden.

- [ ] **Step 5: Run UI and export tests**

Run: `npm test && node --experimental-strip-types --test tests/catalog-utils.test.ts && npm run lint`
Expected: build, rendered HTML, catalog utilities, and lint all pass.

### Task 6: Execute batches and review ambiguous matches

**Files:**
- Update: `data/official-product-details.json`
- Update: `data/product-official-matches.json`
- Update: `data/official-data-summary.json`

- [ ] **Step 1: Confirm credential availability without printing it**

Run: `python scripts/collect_official_product_data.py --check`
Expected with a key: source connectivity and quota-safe sample checks pass. Expected without a key: `blocked_missing_key` and no data mutation.

- [ ] **Step 2: Run 25-product batches**

Run consecutive ranges from `--start 0 --limit 25` through the end of 776 products. Resume from checkpoints after interruptions.

- [ ] **Step 3: Review 80–94 scores and conflicts**

Use GPT Pro only to rank candidates and explain differences. Confirm values only from official API records or manufacturer pages with explicit reuse permission.

- [ ] **Step 4: Materialize after every completed batch**

Run: `python scripts/materialize_official_product_data.py && npm run catalog:sync`
Expected: totals and hashes in the summary match generated JSON and CSV.

- [ ] **Step 5: Verify final completeness**

Run: `python scripts/collect_official_product_data.py --report-only && npm test && npm run lint`
Expected: 776 terminal match states, no duplicate catalog IDs, no orphaned confirmed official keys, and no image without provenance and license.

### Task 7: Obtain KPIC content approval only if official sources leave required gaps

**Files:**
- Modify after written approval: `DATA_POLICY.md`

- [ ] **Step 1: Request content partnership permission**

Use KPIC's content partnership inquiry page and specify fields, image types, record count, private/public use, commercial status, cache duration, refresh frequency, attribution, and deletion obligations.

- [ ] **Step 2: Store the written permission outside the public repository**

Keep the agreement in the user-controlled evidence folder and record only permission scope and expiry in `DATA_POLICY.md`.

- [ ] **Step 3: Add a KPIC adapter only within the approved scope**

Do not automate or copy any KPIC page, image, or text before written approval. Until then, store only a human-readable verification URL and a `permission_required` status.
