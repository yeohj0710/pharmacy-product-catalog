# Complete Product Image Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use parallel subagents for bounded web research only. Subagents must not edit canonical catalog data. The main agent reviews and merges every accepted image.

**Goal:** Resolve the 218 image-missing rows currently present in `data/enrichment-queue.json` with exact, traceable product images where reliable evidence exists, preserve honest exceptions where it does not, verify every changed row, and deploy the verified catalog to production.

**Architecture:** Generate eight disjoint research queues of 27–29 products under `etc/image-research/`. Each subagent writes one result JSON containing candidate page, original image URL, HTTP metadata, search evidence, and a failure reason when no exact image is found. The main agent reviews one batch at a time, materializes only exact and visually checked candidates through the existing image fields, runs batch audits, then performs full browser and production verification.

**Tech Stack:** Python 3 JSON and HTTP tooling, TypeScript/Next.js catalog UI, Node.js tests, Playwright browser automation, Vercel production deployment.

---

### Task 1: Freeze the canonical baseline and create disjoint queues

**Files:**
- Read: `data/enrichment-queue.json`
- Read: `data/enrichment-queue.csv`
- Create: `etc/image-research/baseline-summary.json`
- Create: `etc/image-research/queue-batch-01.json` through `queue-batch-08.json`
- Create: `scripts/prepare_image_research.py`

- [ ] Assert that the canonical JSON contains 776 rows, unique `document_id` values, 558 images, and 218 missing images.
- [ ] Save the ordered IDs, names, capacities, categories, and existing official-match context for only the 218 missing rows.
- [ ] Split those IDs into eight contiguous, non-overlapping batches with sizes `28, 28, 27, 27, 27, 27, 27, 27` and assert their union equals the missing-ID set.
- [ ] Preserve all canonical product fields and do not copy the Downloads queue into the canonical data path.

### Task 2: Run eight bounded research workers

**Files:**
- Read: `etc/image-research/queue-batch-01.json` through `queue-batch-08.json`
- Create: `etc/image-research/results-batch-01.json` through `results-batch-08.json`

- [ ] Give each worker exclusive ownership of one result file and tell it that other workers share the repository.
- [ ] For every product, search official manufacturer or brand pages first, then official stores, exact pharmacy or major retail pages, then specialist sellers.
- [ ] Record `catalog_product_id`, `catalog_name`, `catalog_capacity`, `candidate_name`, `status`, `image_url`, `source_url`, `result_url`, `source_tier`, `match_score`, `checked_at`, `match_evidence`, `searched_queries`, `searched_sites`, `http_status`, `content_type`, `width`, `height`, and `failure_reason`.
- [ ] Use only the original image URL from an opened product page. Reject search thumbnails, people, symptoms, banners, category art, generated images, placeholders, and different variants.
- [ ] Leave `status=not_found` or `review_required` when exact identity, dosage form, capacity, or package count cannot be proven.

### Task 3: Review and merge each 27–28 product batch

**Files:**
- Read: `etc/image-research/results-batch-NN.json`
- Create: `etc/image-research/reviewed-batch-NN.json`
- Modify: `data/image-manual-web-research.json`
- Modify: `data/enrichment-queue.json`
- Modify: `data/enrichment-queue.csv`
- Modify: `data/secondary-image-summary.json`
- Create: `etc/image-research/audit-batch-NN.json`

- [ ] Validate that every result ID belongs to exactly one queue and each queue ID has one result.
- [ ] Open each candidate product page and image. Compare visible product name, form, dosage, capacity, package count, flavor or variant, and manufacturer with the canonical row.
- [ ] Request each original image URL and require a successful image response, non-HTML content type, decodable dimensions, and a useful size.
- [ ] Reject duplicate images assigned to unrelated products and replace any failed candidate through a second research pass.
- [ ] Append only reviewed candidates with `status=confirmed`, `manual_verified=true`, and `visual_verified=true` to the existing research corpus.
- [ ] Back up canonical JSON and CSV in `etc/image-research/backups/` before the first merge, then run the existing merge command for the reviewed corpus.
- [ ] After every batch, assert 776 rows, unchanged original fields and order, unchanged valid KPIC images, no new schema fields, and the exact expected missing-count delta.

### Task 4: Re-research failures and produce honest exceptions

**Files:**
- Create: `etc/image-research/retry-queue.json`
- Create: `etc/image-research/retry-results.json`
- Create: `etc/image-research/final-exceptions.json`

- [ ] Give every failed or ambiguous row to a different worker or the main agent with its prior queries, sites, and failure reason.
- [ ] Accept a retry only when a real product page and exact package image independently satisfy all selection rules.
- [ ] Keep unresolved rows empty and record concrete reasons such as no product page, only another capacity, discontinued item, inaccessible original image, or ambiguous generic name.

### Task 5: Run canonical data and image audits

**Files:**
- Create: `scripts/audit_product_images.py`
- Create: `etc/image-research/final-image-audit.json`
- Modify: `public/data/enrichment-queue.json`
- Modify: `public/data/enrichment-queue.csv`

- [ ] Run `npm run catalog:sync` and compare canonical and public hashes.
- [ ] Check every non-empty image URL for HTTP status, image content type, decoded width and height, minimum useful dimensions, and duplicate SHA-256 content across unrelated rows.
- [ ] Verify all 335 pre-existing `official_source_preview` rows remain unchanged unless a broken official URL is proven.
- [ ] Verify original fields, structured medication information, official match status, official filtering, and row order against the baseline.

### Task 6: Verify all changed rows in the browser

**Files:**
- Create: `tests/product-images.e2e.mjs`
- Create: `etc/image-research/browser-verification.json`

- [ ] Start the production-equivalent local site and load every changed product by stable ID.
- [ ] For each changed row, verify the list thumbnail is visible and decodes with positive natural dimensions.
- [ ] Open the detail modal for each changed row and verify the same product name, image source link, and decoded image.
- [ ] Verify total row count, image filters, official-match filters, pagination, and zero broken changed images.

### Task 7: Run the release gate and deploy

**Files:**
- Read: `package.json`
- Read: `scripts/check-publication-gate.mjs`
- Read: `scripts/deploy_private_catalog.ps1`

- [ ] Run `npm run health:audit`, focused Python image tests, `npm run typecheck`, `npm run test:unit`, `npm run lint`, and the full production build with the explicit public-deploy acknowledgement.
- [ ] Run `npm run deploy:public` only after every required local check passes.
- [ ] Verify `https://pharmacy-product-catalog.vercel.app/` for 776 rows, image counts, every changed thumbnail and modal image, filters, and modal behavior.
- [ ] Report starting, added, and final missing counts; official and external image counts; replacements after failed review; unresolved products and reasons; tests; deployment URL; and changed canonical paths.
