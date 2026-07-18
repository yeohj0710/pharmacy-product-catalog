# Health.kr 776-Product Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Rebuild `C:\dev\pharmacy-product-catalog\data\enrichment-queue.json` as a verified 776-object UTF-8 JSON array enriched from public health.kr product data while preserving every original field, value, identifier, and row order.

**Architecture:** A resumable Python program will read the immutable backup, search health.kr through its CSRF-protected public search endpoint, score candidates conservatively, fetch confirmed product detail and auxiliary pages, normalize the required fields, and preserve every cleaned upstream key under `official_additional_data.health_kr_raw`. A separate test and audit program will enforce original-data invariants, status-specific blanking, source and image rules, and final object counts before an atomic replacement of the canonical JSON.

**Tech Stack:** Python 3.14, `requests`, `lxml`, standard-library `json`, `unittest`, and health.kr public HTML/AJAX endpoints.

---

## File structure

- `C:\dev\pharmacy-product-catalog\data\enrichment-queue.json`: canonical final artifact, replaced only after every audit passes.
- `C:\dev\pharmacy-product-catalog\etc\health-enrichment\enrichment-queue.original.json`: immutable source backup used for invariant comparison.
- `C:\dev\pharmacy-product-catalog\scripts\health_enrichment.py`: search variation, candidate scoring, detail extraction, image validation, checkpointing, and final serialization.
- `C:\dev\pharmacy-product-catalog\tests\test_health_enrichment.py`: unit tests for normalization, matching safety, HTML-to-text conversion, status blanking, and image-domain checks.
- `C:\dev\pharmacy-product-catalog\scripts\audit_health_enrichment.py`: independent final artifact audit against the backup.
- `C:\dev\pharmacy-product-catalog\etc\health-enrichment\cache\`: resumable per-query and per-product JSON cache.
- `C:\dev\pharmacy-product-catalog\etc\health-enrichment\enrichment-checkpoint.json`: resumable full-array checkpoint.
- `C:\dev\pharmacy-product-catalog\etc\health-enrichment\enrichment-audit.json`: machine-readable final audit report.

### Task 1: Lock original-data invariants

**Files:**
- Create: `C:\dev\pharmacy-product-catalog\tests\test_health_enrichment.py`
- Read: `C:\dev\pharmacy-product-catalog\etc\health-enrichment\enrichment-queue.original.json`

- [x] **Step 1: Write normalization and invariant tests**

```python
import json
import unittest
from pathlib import Path

from health_enrichment import clean_text, make_search_variants, valid_official_image

ROOT = Path(r"C:\dev\pharmacy-product-catalog")
ORIGINAL = json.loads((ROOT / "etc" / "enrichment-queue.original.json").read_text(encoding="utf-8"))

class EnrichmentTests(unittest.TestCase):
    def test_original_has_776_unique_rows(self):
        self.assertEqual(len(ORIGINAL), 776)
        self.assertEqual(len({row["document_id"] for row in ORIGINAL}), 776)

    def test_clean_text_preserves_paragraphs(self):
        self.assertEqual(clean_text("첫 문단<br><br><P></P>둘째 문단"), "첫 문단\n\n둘째 문단")

    def test_variants_keep_product_distinguishers(self):
        variants = make_search_variants("산타몬 플러스 120c", "120c")
        self.assertIn("산타몬플러스", variants)

    def test_image_domain_is_restricted(self):
        self.assertTrue(valid_official_image("https://common.health.kr/shared/a.jpg"))
        self.assertFalse(valid_official_image("https://shopping.example/a.jpg"))

if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2: Run tests and confirm the missing implementation fails**

Run: `python -m unittest C:\dev\pharmacy-product-catalog\tests\test_health_enrichment.py -v`

Expected: import failure for `health_enrichment`.

### Task 2: Implement health.kr search and conservative candidate scoring

**Files:**
- Create: `C:\dev\pharmacy-product-catalog\scripts\health_enrichment.py`
- Modify: `C:\dev\pharmacy-product-catalog\tests\test_health_enrichment.py`

- [x] **Step 1: Implement deterministic text normalization and query variants**

```python
FORM_WORDS = ("정", "캡슐", "연질캡슐", "액", "시럽", "연고", "크림", "겔", "점안액", "산", "과립", "스프레이")

def normalize_name(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣+]", "", value or "").lower()

def make_search_variants(name: str, capacity: str) -> list[str]:
    seeds = [name, re.sub(r"\s+", "", name or "")]
    capacity_free = re.sub(r"\b\d+(?:[.,]\d+)?\s*(?:mg|g|ml|l|정|캡슐|포|병|개|c|ea|매|롤)\b", " ", name or "", flags=re.I)
    seeds.append(capacity_free)
    promo_free = re.sub(r"(?:해열진통|종합감기|목감기|코감기|알레르기|이벤트|고함량)", " ", capacity_free)
    seeds.append(promo_free)
    return list(dict.fromkeys(v for s in seeds if (v := normalize_name(s))))
```

- [x] **Step 2: Implement a session-bound CSRF search client**

```python
def search_health_kr(session, query: str) -> list[dict]:
    page = session.post(SEARCH_PAGE, data={"search_word": query, "search_flag": "all"}, timeout=30)
    page.raise_for_status()
    token = re.search(r'window\.csrfToken\s*=\s*"([^"]+)"', page.text).group(1)
    response = session.post(
        SEARCH_AJAX,
        params={"search_word": query, "csrf_token": token, "search_flag": "all"},
        data={"csrf_token": token},
        headers={"X-Requested-With": "XMLHttpRequest", "X-CSRF-Token": token, "Referer": page.url},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()
```

- [x] **Step 3: Score all candidates and reject unsafe conflicts**

```python
def score_candidate(row: dict, candidate: dict, existing_code: str = "") -> tuple[int, list[str], list[str]]:
    source = normalize_name(row.get("name", ""))
    official = normalize_name(candidate.get("drug_name", ""))
    ratio = int(SequenceMatcher(None, source, official).ratio() * 70)
    reasons = ["핵심 제품명 유사"] if ratio >= 45 else []
    conflicts = []
    if existing_code and candidate.get("drug_code") == existing_code:
        ratio += 20
        reasons.append("기존 제품 코드 재검증")
    form_conflict = detect_form_conflict(row.get("name", ""), candidate.get("drug_form", ""))
    if form_conflict:
        conflicts.append(form_conflict)
        ratio -= 45
    return max(0, min(100, ratio)), reasons, conflicts
```

- [x] **Step 4: Add tests for exact, inferred-form, ambiguous, and conflicting-form matches**

```python
def test_form_conflict_blocks_confirmation(self):
    row = {"name": "예시시럽", "capacity": "100mL"}
    candidate = {"drug_name": "예시정", "drug_form": "정제", "drug_code": "1"}
    score, _, conflicts = score_candidate(row, candidate)
    self.assertTrue(conflicts)
    self.assertLess(score, 80)
```

- [x] **Step 5: Run the focused test suite**

Run: `python -m unittest C:\dev\pharmacy-product-catalog\tests\test_health_enrichment.py -v`

Expected: all tests pass.

### Task 3: Extract every public detail field without lossy joining

**Files:**
- Modify: `C:\dev\pharmacy-product-catalog\scripts\health_enrichment.py`
- Modify: `C:\dev\pharmacy-product-catalog\tests\test_health_enrichment.py`

- [x] **Step 1: Implement HTML-to-text conversion that preserves paragraph boundaries**

```python
def clean_text(value) -> str:
    if value is None:
        return ""
    text = str(value).replace("brbr", "\n\n").replace("br<P></P>", "\n\n")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = lxml.html.fromstring(f"<div>{text}</div>").text_content()
    return re.sub(r"\n{3,}", "\n\n", html.unescape(text)).strip()
```

- [x] **Step 2: Split arrays only at upstream separators**

```python
def split_upstream(value: str, separators=("</br>", "<br>", "@", "#")) -> list[str]:
    text = value or ""
    for separator in separators:
        text = text.replace(separator, "\n")
    return list(dict.fromkeys(v for part in text.splitlines() if (v := clean_text(part))))
```

- [x] **Step 3: Map the AJAX payload into every required normalized field**

The mapper will explicitly populate all required `official_*` keys, including currently absent keys, and will keep a cleaned key-for-key copy of the AJAX payload at `official_additional_data.health_kr_raw.detail_ajax`. Empty upstream values remain empty strings, arrays, or objects according to the required type.

- [x] **Step 4: Fetch and preserve auxiliary public pages**

Fetch `result_take.asp`, `result_sunb.asp`, `result_interaction.asp`, `ajax_boh_history2.asp`, and `ajax_result_idfy_delay.asp` for the confirmed code. Store structured rows, links, and cleaned full text under `health_kr_raw`; map same-ingredient, interaction, insurance-history, consumer-guidance, identification, and insert links into their normalized fields.

- [x] **Step 5: Verify source text is not truncated**

```python
def test_long_precautions_are_preserved(self):
    source = "1. 경고<br>" + ("주의 문장 " * 1000)
    cleaned = clean_text(source)
    self.assertGreater(len(cleaned), 5000)
    self.assertTrue(cleaned.endswith("주의 문장"))
```

### Task 4: Validate official images and build status-safe records

**Files:**
- Modify: `C:\dev\pharmacy-product-catalog\scripts\health_enrichment.py`
- Modify: `C:\dev\pharmacy-product-catalog\tests\test_health_enrichment.py`

- [x] **Step 1: Accept only permitted image hosts and non-placeholder URLs**

```python
def valid_official_image(url: str) -> bool:
    parsed = urllib.parse.urlparse(url or "")
    return parsed.scheme == "https" and parsed.hostname in {"health.kr", "www.health.kr", "common.health.kr"} and not re.search(r"placeholder|noimage|ready", parsed.path, re.I)
```

- [x] **Step 2: Probe each image and classify package, pill, label, or instruction**

Use `HEAD`, falling back to a streamed `GET`, require HTTP 200 and an `image/*` content type, deduplicate the final URLs, and select the representative image by `package`, `label`, `pill`, `instruction` order.

- [x] **Step 3: Enforce status-specific data blanking**

```python
def blank_official_fields(record: dict, status: str) -> None:
    if status == "confirmed":
        return
    for key, empty in OFFICIAL_DEFAULTS.items():
        record[key] = copy.deepcopy(empty)
    record["official_match_status"] = status
    record["official_content_status"] = ""
    record["enrichment_status"] = STATUS_TO_ENRICHMENT[status]
    record["image_url"] = record["image_kind"] = record["image_source_url"] = ""
    record["image_rights_status"] = record["image_checked_at"] = ""
```

- [x] **Step 4: Record alternatives without copying their product data**

Each ambiguous candidate is stored only in `match_alternatives` with product name, product code, manufacturer, dosage form, pack unit when available, URL, score, and conflict reasons.

### Task 5: Run all 776 rows with resume and rate controls

**Files:**
- Modify: `C:\dev\pharmacy-product-catalog\scripts\health_enrichment.py`
- Create during execution: `C:\dev\pharmacy-product-catalog\etc\health-enrichment\cache\*.json`
- Create during execution: `C:\dev\pharmacy-product-catalog\etc\health-enrichment\enrichment-checkpoint.json`

- [x] **Step 1: Add retry, delay, and cache behavior**

Use one `requests.Session`, a fixed user agent, exponential retries for 429/5xx/network failures, at least 0.25 seconds between uncached requests, and atomic JSON cache writes.

- [x] **Step 2: Reverify the 296 existing confirmed codes first**

Each existing code must return exactly one detail payload whose product name remains compatible with the catalog name. Otherwise the row returns to candidate search and is reclassified.

- [x] **Step 3: Search pending and review-required rows with every generated variant**

Search exact and reduced names, include autocomplete suggestions, deduplicate candidates by `drug_code`, and fetch candidate details only when needed to resolve dosage form, manufacturer, ingredients, and pack conflicts.

- [x] **Step 4: Classify non-drug rows only after search exhaustion**

Rows in explicit device, cosmetic, food, household, or health-supplement categories become `not_applicable` only when no compatible health.kr drug candidate exists. Other exhausted rows become `not_found`.

- [x] **Step 5: Run the resumable job**

Run: `python C:\dev\pharmacy-product-catalog\scripts\health_enrichment.py --input C:\dev\pharmacy-product-catalog\etc\health-enrichment\enrichment-queue.original.json --checkpoint C:\dev\pharmacy-product-catalog\etc\health-enrichment\enrichment-checkpoint.json`

Expected: 776 processed rows and a completed checkpoint; restarts skip cached searches and details.

### Task 6: Independently audit and atomically replace the canonical file

**Files:**
- Create: `C:\dev\pharmacy-product-catalog\scripts\audit_health_enrichment.py`
- Create: `C:\dev\pharmacy-product-catalog\etc\health-enrichment\enrichment-audit.json`
- Replace after audit: `C:\dev\pharmacy-product-catalog\data\enrichment-queue.json`

- [x] **Step 1: Implement the independent audit**

```python
def assert_original_invariants(original, result):
    assert len(original) == len(result) == 776
    assert [x["document_id"] for x in original] == [x["document_id"] for x in result]
    for before, after in zip(original, result):
        for key in ORIGINAL_FIELDS:
            assert key in after and after[key] == before[key], (before["document_id"], key)
```

The audit also checks unique IDs, required field types, confirmed source URL/item sequence, status-specific blanking, image domains and response validity, image deduplication, complete evidence keys, separated additives, and parseable UTF-8 JSON.

- [x] **Step 2: Run unit tests and the independent audit**

Run: `python -m unittest C:\dev\pharmacy-product-catalog\tests\test_health_enrichment.py -v`

Expected: all tests pass.

Run: `python C:\dev\pharmacy-product-catalog\scripts\audit_health_enrichment.py C:\dev\pharmacy-product-catalog\etc\health-enrichment\enrichment-queue.original.json C:\dev\pharmacy-product-catalog\etc\health-enrichment\enrichment-checkpoint.json`

Expected: `PASS`, 776 rows, zero invariant violations, zero invalid confirmed sources, and zero invalid images.

- [x] **Step 3: Replace the canonical file only after PASS**

Serialize the audited array to a sibling temporary file with `ensure_ascii=False`, validate it again, then use `Path.replace()` to atomically update `C:\dev\pharmacy-product-catalog\data\enrichment-queue.json`.

- [x] **Step 4: Perform a clean-room final read**

Run: `python -c "import json,pathlib; p=pathlib.Path(r'C:\dev\pharmacy-product-catalog\data\enrichment-queue.json'); d=json.loads(p.read_text(encoding='utf-8')); print(len(d), len({x['document_id'] for x in d}), p.stat().st_size)"`

Expected: first two values are `776 776`; the file parses without warnings.

## Plan self-review

- All twelve objective sections map to Tasks 1–6: original preservation, complete population, repeated search, safe matching, full detail capture, normalized fields, raw-key preservation, image rules, evidence, status rules, audit, and final UTF-8 array delivery.
- Every created artifact is under the user-authoritative `C:\dev\pharmacy-product-catalog` root; only the canonical JSON remains in the root and all scripts, cache, logs, plans, and backup remain under `etc`.
- The plan uses exact functions, paths, commands, expected results, and field types; it contains no deferred implementation markers.
