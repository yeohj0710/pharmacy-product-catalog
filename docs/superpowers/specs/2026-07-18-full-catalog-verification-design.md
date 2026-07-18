# Full Catalog Verification and Production Release Design

## Objective

Review all 776 catalog products and every canonical field, correct unsupported or awkward values, rebuild trustworthy product-to-official-record matches, recover complete readable medication content, replace missing or incorrect images with exact-product sources where available, and publish the verified result to production.

The work is complete only when every product has an auditable review record. A field does not have to be populated when no trustworthy public evidence exists, but it must be explicitly marked `not_applicable` or `verified_exception` with the attempted sources and reason. Approximate matches and visually similar substitutes are not acceptable.

## Measured Baseline

The repository and current production payload were inspected on 2026-07-18.

- The production canonical payload contains 776 products and a 95-field union. The 458 confirmed rows contain all 95 fields; the other 318 rows contain 94 because `official_content` is conditionally absent.
- Official match states are 458 `confirmed`, 10 `review_required`, 11 `not_found`, and 297 `not_applicable`.
- Forty-one confirmed matches have a score below 95 and require mandatory re-review.
- Thirty-eight official-record groups are linked to multiple catalog SKUs and require pack-unit and variant review.
- The portable package contains 665 primary images and 111 products without an image.
- Image rights states are 410 `official_source_preview`, 255 `verified`, 108 `미확인`, and 3 blank.
- Existing image evidence includes retailer, search, news, and blog-derived candidates, so existing `confirmed` flags are not accepted as proof.
- The local checkout does not contain the ignored canonical payload or source caches. The deployed canonical JSON is available and can be restored with an immutable hash baseline.
- `DATA_GO_KR_SERVICE_KEY` is not present. Work must remain functional through public product pages and existing source data, while using licensed public APIs when a key becomes available.

## Approaches Considered

### Selected: evidence-led full rebuild

Restore the canonical payload, create a 776-row review ledger, re-evaluate every match and image, rebuild structured medication content, and require two-pass review for high-risk cases. This is the only approach that proves row-by-row and field-by-field coverage.

### Rejected: flagged-row patching

Only fixing missing images, review queues, and audit failures would be faster, but it would preserve false positives already marked `confirmed` and could not demonstrate complete review coverage.

### Rejected: regulatory API-only rebuild

MFDS and other public APIs provide strong official identity data, but they do not cover every retail SKU, supplement, cosmetic, device, or package image. The absent API credential would also make the pipeline non-reproducible on this computer.

## Canonical Data and Evidence Model

The recovered `data/enrichment-queue.json` remains the compatibility source. Original Firestore/app fields are immutable. Corrections affect display or enrichment fields and retain the original values.

A new machine-readable review ledger stores exactly one record per product. Each record contains:

- stable catalog product ID and source order;
- a `field_reviews` entry for every one of the 95 canonical field names, including the observed value, applicability, validation method, evidence references, reviewer, and decision; conditionally absent fields still receive an explicit `not_applicable` review;
- aggregate review state for identity, capacity, category, price preservation, official match, official content, image, and provenance;
- before and after values for every correction;
- source URL, source tier, retrieval time, response status, content hash, and reviewer;
- conflicts, rejected candidates, and a plain-language decision reason;
- first-pass and second-pass reviewer decisions;
- final state: `verified`, `corrected`, `not_applicable`, or `verified_exception`.

The release gate rejects missing product IDs, duplicate review records, missing or extra field-review keys, unreviewed review dimensions, corrections without evidence, and changed original fields. A schema snapshot derived from the restored baseline fixes the expected 95-field union and the conditional `official_content` rule so coverage cannot silently shrink.

## Source Routing and Priority

Each product is classified before research so the correct source family is used.

1. Licensed medicines and quasi-drugs: MFDS/public regulatory records and the matching Korea Pharmaceutical Information Center product page.
2. Health functional foods and foods: MFDS or HACCP records, manufacturer pages, and official brand stores.
3. Medical devices: MFDS device records, manufacturer pages, and authorized distributor pages.
4. Cosmetics and general goods: manufacturer or brand page, official store, then a stable major retailer product page.
5. Images: regulatory or Korea Pharmaceutical Information Center package image, manufacturer asset, official store asset, then an exact stable retailer asset.

Search-result thumbnails, category images, people, symptoms, advertising banners, generated images, news articles, blogs, cached search proxies, and a different capacity, flavor, dosage form, or package are rejected.

## Official Product Matching

Match decisions use identifiers first and text only as supporting evidence.

1. Exact item code, standard code, barcode, report number, or UDI-DI can establish identity when the catalog package is compatible.
2. Without an identifier, normalized product name, manufacturer or brand, dosage form, strength, route, and package capacity must agree.
3. Name similarity alone never confirms a match.
4. A capacity is compared as retail package quantity separately from ingredient strength.
5. Multiple catalog SKUs may share one official record only when the official pack-unit data or independent product evidence supports each SKU.
6. Export-only, discontinued, pediatric/adult, flavor, strength, dosage-form, or manufacturer conflicts force rejection or review.
7. All current scores below 95, all duplicate official-record groups, all current review/not-found states, and a sample of score-100 rows receive independent second review.

Confirmed matches store the exact official page, official code, match evidence, rejected alternatives, reviewer, and review timestamp. Unconfirmed rows do not expose medicine content.

## Medication Content Collection and Parsing

For each confirmed medicine, the collector retrieves and preserves source evidence for identity, manufacturer, dosage form, route, pack unit, storage, appearance, active/all ingredients, additives, efficacy, dosage, precautions, patient guidance, medication guide, interactions, and available official images.

Raw responses are stored only in ignored evidence storage with URL, retrieval time, response metadata, and SHA-256. Public data stores normalized content and field-level provenance.

The parser creates ordered semantic blocks:

- paragraphs and numbered or bulleted list items;
- tables with headers, rows, row/column spans normalized without losing cell order;
- line breaks inside a semantic block only when the source meaning requires them.

Normalization removes residual HTML, literal `br`, non-breaking or zero-width characters, replacement characters, duplicated labels, and malformed spacing while preserving Korean wording, units, mathematical ranges, formulas, and list order. Plain `text` is deterministically derived from `blocks`; it is not independently edited. Round-trip and source-coverage checks detect missing sections, collapsed tables, duplicate paragraphs, broken numeric ranges, and suspiciously short content.

## Image Verification

Every one of the 776 products receives an image decision, including products that already have an image.

For every candidate the verifier records the original image URL and the product page that proves identity. It then checks:

- successful HTTP response after redirects;
- image MIME type and decodability;
- width, height, aspect ratio, byte size, and content hash;
- duplicate and near-duplicate content across unrelated products;
- source stability and absence of placeholder or search-proxy behavior;
- visible product name, manufacturer or brand, strength, form, quantity, flavor, and variant against the catalog row.

Official package images may pass one evidence review when identifiers agree. Non-official images require two independent reviews. Any failing or ambiguous candidate is removed even when that increases the missing-image count. A final `verified_exception` is allowed only after official, manufacturer, official-store, and exact-product search attempts are recorded.

## Parallel Review Execution

The 776 products are split into four exclusive, contiguous batches of 194 products. The main agent and three subagents perform first-pass review with separate ledger files and no shared canonical edits.

Second-pass review rotates the batches so no reviewer approves its own high-risk decision. Work is further subdivided by source domain when necessary, but every product remains owned by exactly one batch ledger. The main agent validates batch coverage, resolves disagreements, and performs the only canonical merge.

Batch acceptance requires:

- exactly 194 unique expected IDs;
- a decision for every review dimension;
- valid evidence for every correction and match;
- no edits to original fields;
- no unresolved reviewer disagreement;
- successful schema and batch audit.

## Error Handling and Reproducibility

Network collection is resumable and rate-limited. Responses are retried only for transient failures, with exponential backoff and a maximum attempt count. Authentication, blocking, parsing changes, and permanent HTTP failures are recorded distinctly.

All canonical writes are atomic. A hash-addressed backup is created before the first merge. A failed batch or release gate leaves the prior canonical data untouched. Source caches, credentials, and potentially restricted raw responses remain ignored and are never committed.

The pipeline must be runnable on a fresh checkout by restoring the production baseline or by supplying the documented original extraction inputs. Generated public artifacts are deterministic and checked against the canonical source.

## Verification and Release Gates

Completion requires all of the following evidence:

1. Exactly 776 canonical rows and 776 final ledger rows with identical unique IDs and order.
2. Every original Firestore/app field preserved byte-for-byte from the baseline.
3. Every product has decisions for all 95 canonical field names, with explicit applicability for conditional fields, and passes the aggregate identity, capacity, category, price preservation, official match, official content, image, and provenance reviews.
4. Every confirmed official match supported by identifiers or compatible identity evidence; no unresolved conflicts.
5. Every confirmed medicine passes structured-content schema, text audit, section coverage, and source-link checks.
6. Every non-empty image passes live HTTP, decode, dimension, duplicate, source, and exact-product visual checks.
7. Every empty field that matters has an explicit `not_applicable` or `verified_exception` reason.
8. Portable JSON/NDJSON/schema/manifest regenerate deterministically from the canonical data.
9. Python and TypeScript unit tests, type checking, lint, catalog audits, production build, and browser tests pass.
10. A real browser opens all 776 product details locally without broken text, mismatched images, console errors, or missing source attribution.

## Version Control and Production Deployment

Only after all release gates pass:

1. Review the complete diff and confirm that generated artifacts match the canonical source.
2. Commit the verified pipeline, review ledgers, aggregate reports, and publishable data artifacts without credentials or restricted raw caches.
3. Push the target branch to the configured Git remote and verify the remote commit hash.
4. Deploy through the repository's production Vercel workflow.
5. Wait for the production deployment to reach a ready state.
6. Compare the production manifest and canonical counts to the committed artifacts.
7. Run the 776-product browser audit against production, including images, modal content, filters, downloads, source links, and console/network errors.
8. Report the commit, remote branch, deployment URL and ID, before/after quality counts, verified exceptions, and all gate results.

Deployment failure does not relax data gates. It is retried or diagnosed while the verified commit remains recoverable from the remote repository.
