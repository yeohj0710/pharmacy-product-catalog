from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.collect_secondary_images import write_csv, write_json_atomic
from scripts.merge_secondary_images import is_placeholder_image, is_search_thumbnail, valid_product_page_url


IMAGE_FIELDS = ("image_kind", "image_url", "image_source_url", "image_rights_status", "image_checked_at", "enrichment_status")


def read_array(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"최상위 값은 배열이어야 합니다: {path}")
    return payload


def expected_rights(image_url: str, source_url: str) -> str:
    image_host = (urlparse(image_url).hostname or "").lower()
    source_host = (urlparse(source_url).hostname or "").lower()
    if image_host in {"health.kr", "www.health.kr", "common.health.kr"} and source_host in {"health.kr", "www.health.kr"}:
        return "official_source_preview"
    return "verified"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/enrichment-queue.json"))
    parser.add_argument("--csv", type=Path, default=Path("data/enrichment-queue.csv"))
    parser.add_argument("--baseline", type=Path, default=Path("etc/image-research/backups/enrichment-queue.start.json"))
    parser.add_argument("--approved", action="append", type=Path)
    parser.add_argument("--clear-unapproved-search-thumbnails", action="store_true", default=True)
    args = parser.parse_args()

    products = read_array(args.input)
    baseline = read_array(args.baseline)
    if [row.get("document_id") for row in products] != [row.get("document_id") for row in baseline]:
        raise ValueError("정식 데이터와 기준 데이터의 document_id 순서가 다릅니다.")
    approved_paths = args.approved or [
        Path(path)
        for pattern in (
            "etc/image-research/approved-batch-*.json",
            "etc/image-research/approved-retry-batch-*.json",
            "etc/image-research/approved-followup-batch-*.json",
            "etc/image-research/approved-legacy-search-batch-*.json",
            "etc/image-research/approved-final-pass-batch-*.json",
            "etc/image-research/approved-source-correction-batch-*.json",
        )
        for path in sorted(glob.glob(pattern))
    ]
    catalog_ids = {str(row.get("document_id") or "") for row in products}
    approved_ids: set[str] = set()
    for path in approved_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list) or any(not isinstance(value, str) or not value for value in payload):
            raise ValueError(f"승인 파일은 문자열 배열이어야 합니다: {path}")
        approved_ids.update(payload)
    unknown_ids = approved_ids - catalog_ids
    if unknown_ids:
        raise ValueError(f"정식 데이터에 없는 승인 ID가 있습니다: {sorted(unknown_ids)}")

    reviewed_paths = [
        Path(path)
        for pattern in (
            "etc/image-research/reviewed-batch-*.json",
            "etc/image-research/reviewed-retry-batch-*.json",
            "etc/image-research/reviewed-followup-batch-*.json",
            "etc/image-research/reviewed-legacy-search-batch-*.json",
            "etc/image-research/reviewed-final-pass-batch-*.json",
            "etc/image-research/reviewed-source-correction-batch-*.json",
        )
        for path in sorted(glob.glob(pattern))
    ]
    reviewed: dict[str, dict[str, Any]] = {}
    reviewed_legacy_ids: set[str] = set()
    for path in reviewed_paths:
        for row in read_array(path):
            if "reviewed-legacy-search-batch-" in path.name:
                reviewed_legacy_ids.add(str(row.get("catalog_product_id") or ""))
            if row.get("status") != "confirmed" or row.get("manual_verified") is not True or row.get("visual_verified") is not True:
                continue
            product_id = str(row.get("catalog_product_id") or "")
            previous = reviewed.get(product_id)
            is_correction = "reviewed-source-correction-batch-" in path.name
            if previous and not is_correction and any(previous.get(field) != row.get(field) for field in ("image_url", "result_url", "source_url")):
                raise ValueError(f"같은 승인 ID에 서로 다른 검수 레코드가 있습니다: {product_id}")
            reviewed[product_id] = row
    missing_review = approved_ids - set(reviewed)
    if missing_review:
        raise ValueError(f"검수 레코드가 없는 승인 ID가 있습니다: {sorted(missing_review)}")
    for product_id in approved_ids:
        record = reviewed[product_id]
        image_url = str(record.get("image_url") or "")
        source_url = str(record.get("result_url") or record.get("source_url") or "")
        if (
            urlparse(image_url).scheme != "https"
            or is_search_thumbnail(image_url)
            or is_placeholder_image(image_url)
            or not valid_product_page_url(source_url)
        ):
            raise ValueError(f"승인 레코드의 이미지 또는 출처 URL이 안전하지 않습니다: {product_id}")

    restored: list[str] = []
    mismatched: list[str] = []
    protected_baseline_restored: list[str] = []
    cleared_search_thumbnails: list[str] = []
    for before, current in zip(baseline, products, strict=True):
        document_id = str(current.get("document_id") or "")
        if document_id in approved_ids:
            record = reviewed[document_id]
            source_url = str(record.get("result_url") or record.get("source_url") or "")
            expected = {
                "image_kind": "package",
                "image_url": str(record.get("image_url") or ""),
                "image_source_url": source_url,
                "image_rights_status": expected_rights(str(record.get("image_url") or ""), source_url),
                "image_checked_at": str(record.get("checked_at") or ""),
                "enrichment_status": "secondary_image_linked",
            }
            if any(current.get(field, "") != value for field, value in expected.items()):
                for field in IMAGE_FIELDS:
                    current[field] = before.get(field, "")
                mismatched.append(document_id)
            continue
        if (
            before.get("image_url")
            and args.clear_unapproved_search_thumbnails
            and document_id in reviewed_legacy_ids
            and is_search_thumbnail(str(before.get("image_url") or ""))
        ):
            current.update({
                "image_kind": "",
                "image_url": "",
                "image_source_url": "",
                "image_rights_status": "미확인",
                "image_checked_at": "",
                "enrichment_status": "official_details_linked" if current.get("official_content_status") else "pending",
            })
            cleared_search_thumbnails.append(document_id)
            continue
        if before.get("image_url"):
            if any(before.get(field, "") != current.get(field, "") for field in IMAGE_FIELDS):
                for field in IMAGE_FIELDS:
                    current[field] = before.get(field, "")
                protected_baseline_restored.append(document_id)
            continue
        if not current.get("image_url"):
            continue
        for field in IMAGE_FIELDS:
            current[field] = before.get(field, "")
        restored.append(document_id)

    current_by_id = {str(row.get("document_id") or ""): row for row in products}
    approved_missing = sorted(product_id for product_id in approved_ids if not current_by_id[product_id].get("image_url"))

    write_json_atomic(args.input, products)
    write_csv(args.csv, products)
    report = {
        "approved_count": len(approved_ids),
        "approved_files": [str(path) for path in approved_paths],
        "restored_count": len(restored),
        "restored_ids": restored,
        "mismatched_approved_ids": mismatched,
        "protected_baseline_restored_ids": protected_baseline_restored,
        "cleared_search_thumbnail_count": len(cleared_search_thumbnails),
        "cleared_search_thumbnail_ids": cleared_search_thumbnails,
        "approved_missing_ids": approved_missing,
    }
    print(json.dumps(report, ensure_ascii=False))
    return 1 if mismatched or protected_baseline_restored or approved_missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
