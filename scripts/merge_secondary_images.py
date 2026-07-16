from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.collect_secondary_images import valid_image_url, write_csv, write_json_atomic


def safe_match(record: dict[str, Any]) -> bool:
    return record.get("manual_verified") is True and record.get("visual_verified") is True


def is_placeholder_image(url: str) -> bool:
    lowered = url.lower()
    return any(marker in lowered for marker in ("19_limited", "noimg", "no_image", "placeholder"))


def load_records(paths: list[Path]) -> dict[str, dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"이미지 조사 파일의 최상위 값은 배열이어야 합니다: {path}")
        for record in payload:
            product_id = str(record.get("catalog_product_id") or "")
            if not product_id:
                continue
            previous = selected.get(product_id)
            rank = (safe_match(record), record.get("status") == "confirmed", int(record.get("match_score") or 0))
            previous_rank = (
                safe_match(previous),
                previous.get("status") == "confirmed",
                int(previous.get("match_score") or 0),
            ) if previous else (False, False, 0)
            if previous is None or rank > previous_rank:
                selected[product_id] = record
    return selected


def merge_images(products: list[dict[str, Any]], records: dict[str, dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for product in products:
        if product.get("image_rights_status") != "source_preview":
            continue
        product.update(
            {
                "image_kind": "",
                "image_url": "",
                "image_source_url": "",
                "image_rights_status": "미확인",
                "image_checked_at": "",
                "enrichment_status": "official_details_linked" if product.get("official_content_status") else "pending",
            }
        )
        counts["cleared_previous"] += 1
    safe_urls: Counter[str] = Counter(
        valid_image_url(str(record.get("image_url") or ""))
        for record in records.values()
        if record.get("status") == "confirmed" and safe_match(record)
    )
    for product in products:
        product_id = str(product.get("id") or product.get("document_id") or "")
        record = records.get(product_id)
        if not record:
            continue
        if product.get("image_url"):
            counts["already_has_image"] += 1
            continue
        image_url = valid_image_url(str(record.get("image_url") or ""))
        if (
            record.get("status") != "confirmed"
            or not safe_match(record)
            or not image_url
            or is_placeholder_image(image_url)
            or safe_urls[image_url] > 1
        ):
            counts["not_linked"] += 1
            continue
        product.update(
            {
                "image_kind": "package",
                "image_url": image_url,
                "image_source_url": str(record.get("result_url") or record.get("source_url") or ""),
                "image_rights_status": "verified",
                "image_checked_at": str(record.get("checked_at") or ""),
                "enrichment_status": "secondary_image_linked",
            }
        )
        counts["linked"] += 1
    return dict(counts)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="분할 조사한 보조 상품 이미지를 상품 큐에 병합합니다.")
    parser.add_argument("--input", type=Path, default=Path("data/enrichment-queue.json"))
    parser.add_argument("--output", type=Path, default=Path("data/enrichment-queue.json"))
    parser.add_argument("--csv", type=Path, default=Path("data/enrichment-queue.csv"))
    parser.add_argument("--summary", type=Path, default=Path("data/secondary-image-summary.json"))
    parser.add_argument("--part", action="append", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    part_paths = args.part or [
        Path(path)
        for pattern in (
            "data/secondary-image-part-[123].json",
            "data/naver-image-part-[123].json",
            "data/image-manual-review-part-[123].json",
        )
        for path in sorted(glob.glob(pattern))
    ]
    baseline = Path("data/secondary-image-matches.json")
    if baseline.exists():
        part_paths = [baseline, *part_paths]
    if not part_paths:
        raise ValueError("병합할 보조 이미지 조사 파일이 없습니다.")
    products = json.loads(args.input.read_text(encoding="utf-8"))
    records = load_records(part_paths)
    status_counts = merge_images(products, records)
    summary = {
        "product_count": len(products),
        "record_count": len(records),
        "status_counts": status_counts,
        "image_count": sum(bool(row.get("image_url")) for row in products),
        "image_missing_count": sum(not row.get("image_url") for row in products),
        "sources": [str(path.as_posix()) for path in part_paths],
    }
    write_json_atomic(args.output, products)
    write_csv(args.csv, products)
    write_json_atomic(args.summary, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
