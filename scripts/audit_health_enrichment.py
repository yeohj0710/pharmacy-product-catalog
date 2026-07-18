from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from health_enrichment import OFFICIAL_DEFAULTS, ORIGINAL_FIELDS, clean_text, valid_official_image


ROOT = Path(__file__).resolve().parents[1]
WORK_DIR = ROOT / "etc" / "health-enrichment"
ALLOWED_STATUSES = {"confirmed", "review_required", "not_found", "not_applicable"}
ALLOWED_IMAGE_KINDS = {"package", "pill", "label", "instruction"}
ARRAY_FIELDS = {
    "official_standard_codes",
    "official_ingredients",
    "official_active_ingredients",
    "official_additives",
    "official_interactions",
    "official_same_ingredient_products",
    "official_insurance_history",
    "official_images",
    "official_pictograms",
}
OBJECT_FIELDS = {
    "official_manufacturer_details",
    "official_consumer_guidance",
    "official_section_evidence",
    "official_additional_data",
}


def image_probe_is_valid(cache_dir: Path, url: str) -> bool:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    path = cache_dir / "image_probe" / f"{digest}.json"
    if not path.exists():
        return False
    try:
        return bool(json.loads(path.read_text(encoding="utf-8")).get("valid"))
    except (OSError, json.JSONDecodeError, AttributeError):
        return False


def empty_value(value: Any) -> bool:
    return value in {None, "", 0} if not isinstance(value, (list, dict)) else len(value) == 0


def run_audit(original: list[dict], result: list[dict], cache_dir: Path) -> dict:
    errors: list[dict] = []

    def error(code: str, document_id: str = "", field: str = "", detail: str = "") -> None:
        errors.append({"code": code, "document_id": document_id, "field": field, "detail": detail})

    if len(original) != 776:
        error("original_count", detail=str(len(original)))
    if len(result) != 776:
        error("result_count", detail=str(len(result)))

    original_ids = [str(row.get("document_id", "")) for row in original]
    result_ids = [str(row.get("document_id", "")) for row in result]
    if original_ids != result_ids:
        error("document_order")
    duplicates = [value for value, count in Counter(result_ids).items() if count > 1]
    if duplicates:
        error("duplicate_document_id", detail=",".join(duplicates))

    for before, after in zip(original, result):
        document_id = str(before.get("document_id", ""))
        for field in ORIGINAL_FIELDS:
            if field not in after:
                error("missing_original_field", document_id, field)
            elif before.get(field) != after.get(field):
                error("changed_original_field", document_id, field)

        for field in OFFICIAL_DEFAULTS:
            if field not in after:
                error("missing_official_field", document_id, field)
        for field in ARRAY_FIELDS:
            if not isinstance(after.get(field), list):
                error("wrong_array_type", document_id, field, type(after.get(field)).__name__)
        for field in OBJECT_FIELDS:
            if not isinstance(after.get(field), dict):
                error("wrong_object_type", document_id, field, type(after.get(field)).__name__)
        score = after.get("official_match_score")
        if not isinstance(score, (int, float)) or isinstance(score, bool) or not (0 <= score <= 100):
            error("bad_match_score", document_id, "official_match_score", repr(score))

        status = after.get("official_match_status")
        if status not in ALLOWED_STATUSES:
            error("bad_status", document_id, "official_match_status", repr(status))
            continue

        images = after.get("official_images", []) if isinstance(after.get("official_images"), list) else []
        image_urls = [item.get("url", "") for item in images if isinstance(item, dict)]
        if len(image_urls) != len(set(image_urls)):
            error("duplicate_image", document_id, "official_images")
        for item in images:
            if not isinstance(item, dict):
                error("bad_image_item", document_id, "official_images")
                continue
            url = item.get("url", "")
            if not valid_official_image(url):
                error("invalid_image_domain", document_id, "official_images", url)
            if item.get("kind") not in ALLOWED_IMAGE_KINDS:
                error("invalid_image_kind", document_id, "official_images", repr(item.get("kind")))
            if item.get("source_url") != after.get("official_source_url"):
                error("image_source_mismatch", document_id, "official_images", url)
            if not image_probe_is_valid(cache_dir, url):
                error("image_not_probed", document_id, "official_images", url)

        if status == "confirmed":
            if after.get("enrichment_status") != "official_details_linked":
                error("confirmed_enrichment_status", document_id, "enrichment_status")
            if after.get("official_content_status") not in {"complete", "partial"}:
                error("confirmed_content_status", document_id, "official_content_status")
            if not after.get("official_item_seq"):
                error("confirmed_missing_item_seq", document_id, "official_item_seq")
            source_url = str(after.get("official_source_url") or "")
            parsed = urlparse(source_url)
            source_code = parse_qs(parsed.query).get("drug_cd", [""])[0]
            if parsed.hostname not in {"health.kr", "www.health.kr"} or source_code != str(after.get("official_item_seq")):
                error("confirmed_bad_source", document_id, "official_source_url", source_url)
            if after.get("official_domain") != "health.kr":
                error("confirmed_bad_domain", document_id, "official_domain")
            if not after.get("official_checked_at"):
                error("confirmed_missing_checked_at", document_id, "official_checked_at")
            evidence = after.get("official_section_evidence", {})
            for key in ("detail_page_verified", "ajax_payload_verified", "match_reasons", "conflicts", "source_urls", "verified_fields"):
                if key not in evidence:
                    error("missing_evidence_key", document_id, f"official_section_evidence.{key}")
            raw = after.get("official_additional_data", {}).get("health_kr_raw", {})
            detail = raw if isinstance(raw, dict) else None
            if not isinstance(detail, dict) or not detail.get("drug_code"):
                error("missing_raw_detail", document_id, "official_additional_data.health_kr_raw")
            else:
                if str(detail.get("drug_code")) != str(after.get("official_item_seq")):
                    error("raw_code_mismatch", document_id, "official_item_seq")
                for official_field, raw_field in (
                    ("official_efficacy", "effect"),
                    ("official_dosage", "dosage"),
                    ("official_precautions", "caution"),
                ):
                    if clean_text(detail.get(raw_field, "")) != after.get(official_field, ""):
                        error("normalized_text_mismatch", document_id, official_field)
            if images:
                if after.get("image_url") not in image_urls:
                    error("representative_not_in_images", document_id, "image_url")
                if after.get("image_rights_status") != "official_source_preview":
                    error("bad_image_rights", document_id, "image_rights_status")
            elif any(after.get(field) for field in ("image_url", "image_kind", "image_source_url", "image_checked_at")):
                error("image_metadata_without_image", document_id)
        else:
            if after.get("official_content_status") != "":
                error("nonconfirmed_content_status", document_id, "official_content_status")
            expected_enrichment = {
                "review_required": "official_review_required",
                "not_found": "not_found",
                "not_applicable": "not_applicable",
            }[status]
            if after.get("enrichment_status") != expected_enrichment:
                error("nonconfirmed_enrichment_status", document_id, "enrichment_status")
            allowed_nonempty = {"official_match_status", "official_checked_at"}
            for field in OFFICIAL_DEFAULTS:
                if field in allowed_nonempty:
                    continue
                if not empty_value(after.get(field)):
                    error("nonconfirmed_official_data", document_id, field)
            if images or any(after.get(field) for field in ("image_url", "image_kind", "image_source_url", "image_checked_at", "image_rights_status")):
                error("nonconfirmed_image_data", document_id)

        for value in after.get("official_additives", []) if isinstance(after.get("official_additives"), list) else []:
            if re_contains_html(value):
                error("additive_contains_html", document_id, "official_additives", value[:120])

    status_counts = Counter(row.get("official_match_status", "") for row in result)
    confirmed = status_counts.get("confirmed", 0)
    report = {
        "passed": not errors,
        "row_count": len(result),
        "unique_document_ids": len(set(result_ids)),
        "status_counts": dict(status_counts),
        "confirmed_complete": sum(1 for row in result if row.get("official_match_status") == "confirmed" and row.get("official_content_status") == "complete"),
        "confirmed_partial": sum(1 for row in result if row.get("official_match_status") == "confirmed" and row.get("official_content_status") == "partial"),
        "confirmed_with_images": sum(1 for row in result if row.get("official_match_status") == "confirmed" and row.get("official_images")),
        "confirmed_without_images": sum(1 for row in result if row.get("official_match_status") == "confirmed" and not row.get("official_images")),
        "confirmed_count": confirmed,
        "error_count": len(errors),
        "errors": errors,
    }
    return report


def re_contains_html(value: Any) -> bool:
    return isinstance(value, str) and bool(__import__("re").search(r"</?[A-Za-z][^>]*>", value))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("original")
    parser.add_argument("result")
    parser.add_argument("--cache-dir", default=str(WORK_DIR / "cache"))
    parser.add_argument("--report", default=str(WORK_DIR / "enrichment-audit.json"))
    parser.add_argument("--replace", default="")
    args = parser.parse_args()

    original_path = Path(args.original)
    result_path = Path(args.result)
    original = json.loads(original_path.read_text(encoding="utf-8"))
    result = json.loads(result_path.read_text(encoding="utf-8"))
    report = run_audit(original, result, Path(args.cache_dir))
    report_path = Path(args.report)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "errors"}, ensure_ascii=False, indent=2))
    if report["errors"]:
        print(json.dumps(report["errors"][:30], ensure_ascii=False, indent=2))
        raise SystemExit(1)
    if args.replace:
        destination = Path(args.replace)
        temp = destination.with_suffix(destination.suffix + ".tmp")
        shutil.copyfile(result_path, temp)
        reparsed = json.loads(temp.read_text(encoding="utf-8"))
        if len(reparsed) != 776:
            raise RuntimeError("replacement reparse failed")
        temp.replace(destination)
        print(f"REPLACED {destination}")


if __name__ == "__main__":
    main()
