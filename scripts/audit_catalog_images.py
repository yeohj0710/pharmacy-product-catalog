from __future__ import annotations

import argparse
import glob
import hashlib
import io
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from PIL import Image

try:
    from scripts.apply_catalog_text_corrections import apply_corrections, refresh_duplicate_groups
except ModuleNotFoundError:  # `python scripts/audit_catalog_images.py` 실행 경로
    from apply_catalog_text_corrections import apply_corrections, refresh_duplicate_groups


ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = "Mozilla/5.0 (compatible; pharmacy-product-catalog-image-audit/1.0)"
SEARCH_HOSTS = {"search.naver.com", "search.pstatic.net", "search.daum.net", "search.danawa.com", "www.google.com", "www.bing.com"}
ORIGINAL_FIELDS = (
    "document_id", "document_create_time", "document_update_time", "id", "name", "capacity", "category", "price", "etc", "updated",
    "app_id", "app_name", "app_capacity", "app_category", "app_price", "app_etc", "app_updated", "specification",
    "displayed_price_krw", "normalized_name", "normalized_capacity", "source_order", "source_type", "recorded_at", "price_status",
    "verification_status", "duplicate_group_id", "duplicate_group_size",
)
IMAGE_FIELDS = ("image_kind", "image_url", "image_source_url", "image_rights_status", "image_checked_at", "enrichment_status")


def is_search_url(value: str) -> bool:
    return (urlparse(value).hostname or "").lower() in SEARCH_HOSTS


def unauthorized_protected_changes(
    before: dict[str, Any],
    after: dict[str, Any],
    protected_fields: set[str],
    allowed_fields: set[str] | None = None,
) -> list[str]:
    allowed = allowed_fields or set()
    return [
        field
        for field in sorted(protected_fields)
        if field not in allowed and before.get(field) != after.get(field)
    ]


def read_json(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"JSON 최상위 값은 배열이어야 합니다: {path}")
    return payload


def fetch_image(row: dict[str, Any]) -> dict[str, Any]:
    url = str(row.get("image_url") or "")
    result: dict[str, Any] = {
        "document_id": str(row.get("document_id") or ""), "name": str(row.get("name") or ""), "url": url,
        "status": 0, "final_url": "", "content_type": "", "byte_count": 0, "width": 0, "height": 0, "sha256": "", "error": "", "warnings": [],
    }
    if is_search_url(url):
        result["warnings"].append("search_thumbnail_url")
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30, allow_redirects=True)
        result.update(status=response.status_code, final_url=response.url, content_type=response.headers.get("content-type", ""), byte_count=len(response.content))
        if is_search_url(response.url) and "redirected_to_search_thumbnail" not in result["warnings"]:
            result["warnings"].append("redirected_to_search_thumbnail")
        if response.status_code < 200 or response.status_code >= 400:
            result["error"] = f"http_{response.status_code}"
            return result
        if result["content_type"].lower().startswith("text/html"):
            result["error"] = "non_image_content_type"
            return result
        image = Image.open(io.BytesIO(response.content))
        image.load()
        result.update(width=image.width, height=image.height, sha256=hashlib.sha256(response.content).hexdigest())
        if not result["content_type"].lower().startswith("image/"):
            result["warnings"].append("missing_or_nonstandard_image_content_type")
        if max(image.width, image.height) < 150 or image.width * image.height < 20_000:
            result["warnings"].append("image_too_small")
    except (requests.RequestException, OSError, ValueError) as exc:
        result["error"] = str(exc)
    return result


def source_page_status(url: str) -> dict[str, Any]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or (parsed.hostname or "").lower() in SEARCH_HOSTS:
        return {"url": url, "status": 0, "final_url": "", "error": "invalid_or_search_page_url"}
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=25, allow_redirects=True)
        final_host = (urlparse(response.url).hostname or "").lower()
        if final_host in SEARCH_HOSTS:
            error = "redirected_to_search_page"
        else:
            error = "" if response.status_code < 400 or response.status_code in {401, 403, 429} else f"http_{response.status_code}"
        return {"url": url, "status": response.status_code, "final_url": response.url, "error": error}
    except requests.RequestException as exc:
        return {"url": url, "status": 0, "final_url": "", "error": str(exc)}


def reviewed_expected_fields(record: dict[str, Any]) -> dict[str, str]:
    image_url = str(record.get("image_url") or "")
    source_url = str(record.get("result_url") or record.get("source_url") or "")
    image_host = (urlparse(image_url).hostname or "").lower()
    source_host = (urlparse(source_url).hostname or "").lower()
    rights = (
        "official_source_preview"
        if image_host in {"health.kr", "www.health.kr", "common.health.kr"} and source_host in {"health.kr", "www.health.kr"}
        else "verified"
    )
    return {
        "image_kind": "package",
        "image_url": image_url,
        "image_source_url": source_url,
        "image_rights_status": rights,
        "image_checked_at": str(record.get("checked_at") or ""),
        "enrichment_status": "secondary_image_linked",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=ROOT / "data" / "enrichment-queue.json")
    parser.add_argument("--baseline", type=Path, default=ROOT / "etc" / "image-research" / "backups" / "enrichment-queue.start.json")
    parser.add_argument("--report", type=Path, default=ROOT / "etc" / "image-research" / "final-image-audit.json")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--text-corrections", type=Path, default=ROOT / "data" / "catalog-text-corrections.json")
    parser.add_argument(
        "--official-rematch-report",
        type=Path,
        default=ROOT / "etc" / "image-research" / "corrected-official-rematch-report.json",
    )
    parser.add_argument(
        "--unmatched-rematch-report",
        type=Path,
        default=ROOT / "etc" / "image-research" / "unmatched-official-rematch-report.json",
    )
    parser.add_argument(
        "--reviewed-rematch-report",
        type=Path,
        default=ROOT / "etc" / "image-research" / "official-rematch-reviewed-merge-report.json",
    )
    parser.add_argument(
        "--content-normalization-report",
        type=Path,
        default=ROOT / "etc" / "text-normalization" / "catalog-content-normalization.json",
    )
    args = parser.parse_args()

    products = read_json(args.input)
    baseline = read_json(args.baseline)
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if len(products) != 776 or len(baseline) != 776:
        errors.append({"kind": "bad_row_count", "current": len(products), "baseline": len(baseline)})
    current_ids = [str(row.get("document_id") or "") for row in products]
    baseline_ids = [str(row.get("document_id") or "") for row in baseline]
    if current_ids != baseline_ids or len(current_ids) != len(set(current_ids)):
        errors.append({"kind": "id_order_or_uniqueness_changed"})

    baseline_by_id = {str(row.get("document_id") or ""): row for row in baseline}
    corrected_ids: set[str] = set()
    if args.text_corrections.is_file():
        corrections = read_json(args.text_corrections)
        corrected_ids = {
            str(row.get("document_id") or "") for row in corrections if row.get("approved")
        }
        apply_corrections(baseline, corrections)
        refresh_duplicate_groups(baseline)
        baseline_by_id = {str(row.get("document_id") or ""): row for row in baseline}
    rematched_ids: set[str] = set()
    rematch_confirmed_ids: set[str] = set()
    for report_path in (
        args.official_rematch_report,
        args.unmatched_rematch_report,
    ):
        if report_path.is_file():
            rematch_report = json.loads(report_path.read_text(encoding="utf-8"))
            for transition in rematch_report.get("transitions", []):
                document_id = str(transition.get("document_id") or "")
                rematched_ids.add(document_id)
                if transition.get("after_status") == "confirmed":
                    rematch_confirmed_ids.add(document_id)
    if args.reviewed_rematch_report.is_file():
        reviewed_rematch = json.loads(
            args.reviewed_rematch_report.read_text(encoding="utf-8")
        )
        for document_id in reviewed_rematch.get("manual_confirmation_ids", []):
            rematched_ids.add(str(document_id))
            rematch_confirmed_ids.add(str(document_id))
    normalized_content_fields: dict[str, set[str]] = {}
    if args.content_normalization_report.is_file():
        normalization_report = json.loads(
            args.content_normalization_report.read_text(encoding="utf-8")
        )
        for product in normalization_report.get("products", []):
            document_id = str(product.get("document_id") or "")
            changed_fields = product.get("changed_fields")
            if document_id and isinstance(changed_fields, list):
                normalized_content_fields[document_id] = {
                    str(field) for field in changed_fields
                }
    research_root = ROOT / "etc" / "image-research"
    approved_ids: set[str] = set()
    for pattern in ("approved-batch-*.json", "approved-retry-batch-*.json", "approved-followup-batch-*.json", "approved-legacy-search-batch-*.json", "approved-final-pass-batch-*.json", "approved-source-correction-batch-*.json"):
        for filename in sorted(glob.glob(str(research_root / pattern))):
            approved_ids.update(json.loads(Path(filename).read_text(encoding="utf-8")))
    reviewed_records: dict[str, dict[str, Any]] = {}
    reviewed_legacy_ids: set[str] = set()
    for pattern in ("reviewed-batch-*.json", "reviewed-retry-batch-*.json", "reviewed-followup-batch-*.json", "reviewed-legacy-search-batch-*.json", "reviewed-final-pass-batch-*.json", "reviewed-source-correction-batch-*.json"):
        for filename in sorted(glob.glob(str(research_root / pattern))):
            for record in read_json(Path(filename)):
                product_id = str(record.get("catalog_product_id") or "")
                if "reviewed-legacy-search-batch-" in Path(filename).name:
                    reviewed_legacy_ids.add(product_id)
                if record.get("status") == "confirmed" and record.get("manual_verified") is True and record.get("visual_verified") is True:
                    reviewed_records[product_id] = record
    override_path = ROOT / "data" / "image-source-overrides.json"
    if override_path.is_file():
        for record in read_json(override_path):
            product_id = str(record.get("catalog_product_id") or "")
            if (
                product_id
                and record.get("status") == "confirmed"
                and record.get("manual_verified") is True
                and record.get("visual_verified") is True
            ):
                approved_ids.add(product_id)
                reviewed_records[product_id] = record
    changed_ids: list[str] = []
    image_changed_ids: list[str] = []
    image_payload_changed_ids: list[str] = []
    replaced_ids: list[str] = []
    removed_ids: list[str] = []
    official_changed: list[str] = []
    for row in products:
        document_id = str(row.get("document_id") or "")
        before = baseline_by_id.get(document_id)
        if before is None:
            errors.append({"kind": "document_id_missing_from_baseline", "document_id": document_id})
            continue
        protected_fields = set(ORIGINAL_FIELDS)
        if document_id not in rematched_ids:
            protected_fields |= {key for key in before.keys() | row.keys() if key.startswith("official_")} | {"match_alternatives"}
        changed_protected = unauthorized_protected_changes(
            before,
            row,
            protected_fields,
            normalized_content_fields.get(document_id),
        )
        if changed_protected:
            errors.append({"kind": "protected_fields_changed", "document_id": document_id, "fields": changed_protected})
        image_changed = any(before.get(field, "") != row.get(field, "") for field in IMAGE_FIELDS)
        image_payload_changed = any(
            before.get(field, "") != row.get(field, "")
            for field in IMAGE_FIELDS
            if field != "enrichment_status"
        )
        if image_changed:
            image_changed_ids.append(document_id)
            if image_payload_changed:
                image_payload_changed_ids.append(document_id)
            if document_id in rematch_confirmed_ids and row.get("image_rights_status") == "official_source_preview":
                pass
            elif document_id in approved_ids:
                record = reviewed_records.get(document_id)
                expected = reviewed_expected_fields(record) if record else {}
                mismatched = [
                    field
                    for field, value in expected.items()
                    if row.get(field, "") != value
                    and not (document_id in rematched_ids and field == "enrichment_status")
                ]
                if not record or mismatched:
                    errors.append({"kind": "approved_image_value_mismatch", "document_id": document_id, "fields": mismatched})
            elif document_id in rematched_ids and not image_payload_changed:
                pass
            elif before.get("image_url") and is_search_url(str(before.get("image_url") or "")) and not row.get("image_url"):
                if document_id not in reviewed_legacy_ids:
                    errors.append({"kind": "unreviewed_search_thumbnail_removed", "document_id": document_id})
            else:
                errors.append({"kind": "image_changed_without_approval", "document_id": document_id})
        if not before.get("image_url") and row.get("image_url"):
            changed_ids.append(document_id)
        elif before.get("image_url") and not row.get("image_url"):
            removed_ids.append(document_id)
            if not is_search_url(str(before.get("image_url") or "")):
                errors.append({"kind": "preexisting_image_removed", "document_id": document_id})
        elif before.get("image_url") and before.get("image_url") != row.get("image_url"):
            replaced_ids.append(document_id)
            if (
                document_id not in rematch_confirmed_ids
                and (not is_search_url(str(before.get("image_url") or "")) or is_search_url(str(row.get("image_url") or "")))
            ):
                errors.append({"kind": "preexisting_image_replaced", "document_id": document_id})
        if document_id not in rematch_confirmed_ids and before.get("image_rights_status") == "official_source_preview" and any(
            before.get(field) != row.get(field) for field in ("image_url", "image_source_url", "image_rights_status", "official_images", "official_source_url")
        ):
            official_changed.append(document_id)
    if official_changed:
        errors.append({"kind": "official_images_changed", "document_ids": official_changed})

    image_rows = [row for row in products if str(row.get("image_url") or "").strip()]
    image_checks: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {executor.submit(fetch_image, row): row for row in image_rows}
        for future in as_completed(futures):
            image_checks.append(future.result())
    image_checks.sort(key=lambda item: current_ids.index(item["document_id"]))
    for check in image_checks:
        if check["error"]:
            errors.append({"kind": "image_response_failed", **check})
        for warning in check["warnings"]:
            item = {"kind": "image_response_warning", "warning": warning, **check}
            if warning in {"search_thumbnail_url", "redirected_to_search_thumbnail"} and check["document_id"] in image_payload_changed_ids:
                errors.append({**item, "kind": "new_or_changed_search_thumbnail"})
            elif warning == "image_too_small" and check["document_id"] in image_payload_changed_ids:
                errors.append({**item, "kind": "new_or_changed_image_too_small"})
            else:
                warnings.append(item)

    digest_groups: dict[str, list[str]] = {}
    for check in image_checks:
        if check["sha256"]:
            digest_groups.setdefault(check["sha256"], []).append(check["document_id"])
    duplicate_groups: list[dict[str, Any]] = []
    current_by_id = {str(row["document_id"]): row for row in products}
    for digest, ids in digest_groups.items():
        if len(ids) < 2:
            continue
        identities = set()
        for item in ids:
            row = current_by_id[item]
            official_item_seq = str(row.get("official_item_seq") or "")
            if official_item_seq:
                identities.add(("official", official_item_seq))
            else:
                identities.add(
                    (
                        "catalog",
                        str(row.get("normalized_name") or ""),
                        str(row.get("normalized_capacity") or ""),
                    )
                )
        duplicate_groups.append({"sha256": digest, "document_ids": ids, "identities": sorted(identities), "unrelated": len(identities) > 1})
        if len(identities) > 1 and any(document_id in image_payload_changed_ids for document_id in ids):
            errors.append({"kind": "duplicate_image_for_unrelated_products", "sha256": digest, "document_ids": ids})
        elif len(identities) > 1:
            warnings.append({"kind": "preexisting_duplicate_image_for_different_catalog_variants", "sha256": digest, "document_ids": ids})

    source_checks: list[dict[str, Any]] = []
    pending_source_checks: list[tuple[str, str]] = []
    for document_id in image_payload_changed_ids:
        row = current_by_id[document_id]
        if not str(row.get("image_url") or "").strip():
            continue
        source_url = str(row.get("image_source_url") or "")
        if not source_url:
            errors.append({"kind": "missing_image_source_url", "document_id": document_id})
            continue
        pending_source_checks.append((document_id, source_url))
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {
            executor.submit(source_page_status, source_url): document_id
            for document_id, source_url in pending_source_checks
        }
        for future in as_completed(futures):
            document_id = futures[future]
            check = future.result()
            source_checks.append({"document_id": document_id, **check})
    source_checks.sort(key=lambda item: current_ids.index(item["document_id"]))
    for check in source_checks:
        if check["error"]:
            errors.append({"kind": "image_source_page_failed", **check})

    confirmed_without_link = [
        str(row["document_id"]) for row in products
        if row.get("official_match_status") == "confirmed" and not str(row.get("official_source_url") or "").strip()
    ]
    if confirmed_without_link:
        errors.append({"kind": "confirmed_missing_official_source_url", "document_ids": confirmed_without_link})

    report = {
        "summary": {
            "total_count": len(products),
            "image_count": len(image_rows),
            "image_missing_count": len(products) - len(image_rows),
            "official_image_count": sum(row.get("image_rights_status") == "official_source_preview" for row in image_rows),
            "external_image_count": sum(row.get("image_rights_status") != "official_source_preview" for row in image_rows),
            "new_image_count": len(changed_ids),
            "changed_product_ids": changed_ids,
            "image_changed_count": len(image_changed_ids),
            "image_changed_product_ids": image_changed_ids,
            "image_payload_changed_count": len(image_payload_changed_ids),
            "replaced_image_count": len(replaced_ids),
            "removed_image_count": len(removed_ids),
            "corrected_search_thumbnail_count": sum(
                is_search_url(str(baseline_by_id[document_id].get("image_url") or ""))
                for document_id in replaced_ids
            ),
            "cleared_search_thumbnail_count": sum(
                is_search_url(str(baseline_by_id[document_id].get("image_url") or ""))
                for document_id in removed_ids
            ),
            "image_failure_count": sum(bool(check["error"]) for check in image_checks),
            "duplicate_group_count": len(duplicate_groups),
            "unrelated_duplicate_group_count": sum(group["unrelated"] for group in duplicate_groups),
            "error_count": len(errors),
            "warning_count": len(warnings),
        },
        "errors": errors,
        "warnings": warnings,
        "image_checks": image_checks,
        "source_checks": source_checks,
        "duplicate_groups": duplicate_groups,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
