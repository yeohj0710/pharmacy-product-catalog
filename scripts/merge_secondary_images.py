from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.collect_secondary_images import valid_image_url, write_csv, write_json_atomic


def safe_match(record: dict[str, Any]) -> bool:
    return record.get("manual_verified") is True and record.get("visual_verified") is True


def is_placeholder_image(url: str) -> bool:
    lowered = url.lower()
    return any(marker in lowered for marker in ("19_limited", "noimg", "no_image", "placeholder"))


def is_search_thumbnail(url: str) -> bool:
    hostname = (urlparse(url).hostname or "").lower()
    return hostname in {"search.pstatic.net", "search.naver.com", "search.daum.net", "search.danawa.com"}


def is_health_kr_preview(image_url: str, source_url: str) -> bool:
    image_host = (urlparse(image_url).hostname or "").lower()
    source_host = (urlparse(source_url).hostname or "").lower()
    return image_host in {"health.kr", "www.health.kr", "common.health.kr"} and source_host in {"health.kr", "www.health.kr"}


def valid_product_page_url(url: str) -> bool:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    return (
        parsed.scheme in {"http", "https"}
        and bool(hostname)
        and hostname not in {"search.pstatic.net", "search.naver.com", "search.daum.net", "search.danawa.com"}
    )


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


def merge_images(
    products: list[dict[str, Any]],
    records: dict[str, dict[str, Any]],
    *,
    include_unverified_previews: bool = False,
    replace_search_thumbnails: bool = False,
    replace_existing_verified: bool = False,
) -> dict[str, int]:
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
        existing_image_url = str(product.get("image_url") or "")
        can_replace_search_thumbnail = replace_search_thumbnails and is_search_thumbnail(existing_image_url)
        can_replace_verified = replace_existing_verified and product.get(
            "image_rights_status"
        ) in {"verified", "official_source_preview"}
        if existing_image_url and not can_replace_search_thumbnail and not can_replace_verified:
            counts["already_has_image"] += 1
            continue
        image_url = valid_image_url(str(record.get("image_url") or ""))
        source_url = str(record.get("result_url") or record.get("source_url") or "")
        is_verified = record.get("status") == "confirmed" and safe_match(record)
        if (
            not is_verified
            or not image_url
            or not valid_product_page_url(source_url)
            or is_placeholder_image(image_url)
            or is_search_thumbnail(image_url)
            or safe_urls[image_url] > 1
        ):
            counts["not_linked"] += 1
            continue
        official_preview = is_health_kr_preview(image_url, source_url)
        product.update(
            {
                "image_kind": "package",
                "image_url": image_url,
                "image_source_url": source_url,
                "image_rights_status": "official_source_preview" if official_preview else "verified",
                "image_checked_at": str(record.get("checked_at") or ""),
                "enrichment_status": "secondary_image_linked",
            }
        )
        counts["linked_verified"] += 1
        counts["linked"] += 1
        if can_replace_search_thumbnail:
            counts["replaced_search_thumbnail"] += 1
        elif can_replace_verified:
            counts["replaced_verified_image"] += 1
    return dict(counts)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="분할 조사한 보조 상품 이미지를 상품 큐에 병합합니다.")
    parser.add_argument("--input", type=Path, default=Path("data/enrichment-queue.json"))
    parser.add_argument("--output", type=Path, default=Path("data/enrichment-queue.json"))
    parser.add_argument("--csv", type=Path, default=Path("data/enrichment-queue.csv"))
    parser.add_argument("--summary", type=Path, default=Path("data/secondary-image-summary.json"))
    parser.add_argument("--part", action="append", type=Path)
    parser.add_argument(
        "--include-unverified-previews",
        action="store_true",
        help="호환성용 옵션입니다. 검수되지 않은 이미지는 연결하지 않습니다.",
    )
    parser.add_argument(
        "--replace-search-thumbnails",
        action="store_true",
        help="검수 승인된 이미지로 기존 검색 결과 썸네일만 교체합니다.",
    )
    parser.add_argument(
        "--replace-existing-verified",
        action="store_true",
        help="교정 검수를 통과한 레코드로 기존 외부 검증 이미지를 교체합니다.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.part:
        part_paths = args.part
    else:
        part_paths = [
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
    status_counts = merge_images(
        products,
        records,
        include_unverified_previews=args.include_unverified_previews,
        replace_search_thumbnails=args.replace_search_thumbnails,
        replace_existing_verified=args.replace_existing_verified,
    )
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
