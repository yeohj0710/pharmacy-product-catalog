from __future__ import annotations

import argparse
import copy
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.apply_catalog_text_corrections import atomic_write_text, read_array, write_csv
from scripts.health_enrichment import (
    DEFAULT_CACHE,
    OFFICIAL_DEFAULTS,
    HealthKrClient,
    process_record,
)


ROOT = Path(__file__).resolve().parents[1]
IMAGE_FIELDS = (
    "image_url",
    "image_source_url",
    "image_rights_status",
    "image_kind",
    "image_checked_at",
)
OFFICIAL_FIELDS = tuple(OFFICIAL_DEFAULTS) + ("match_alternatives", "official_match_reason")


def merge_refresh_result(
    current: dict[str, Any], refreshed: dict[str, Any]
) -> dict[str, Any]:
    merged = copy.deepcopy(current)
    for key in OFFICIAL_FIELDS:
        if key in refreshed:
            merged[key] = copy.deepcopy(refreshed[key])

    status = str(refreshed.get("official_match_status") or "")
    if status:
        merged["official_match_status"] = status
    if refreshed.get("official_checked_at"):
        merged["official_checked_at"] = refreshed["official_checked_at"]

    if status == "confirmed":
        merged["enrichment_status"] = refreshed.get(
            "enrichment_status", "official_details_linked"
        )
        if refreshed.get("image_url"):
            for key in IMAGE_FIELDS:
                merged[key] = refreshed.get(key, "")
    elif current.get("image_url"):
        # 외부 제품 이미지가 있으면 공식 재검색 실패가 이미지 연결 상태를 지우지 않게 합니다.
        for key in IMAGE_FIELDS:
            merged[key] = current.get(key, "")
        merged["enrichment_status"] = current.get(
            "enrichment_status", "secondary_image_linked"
        )
    else:
        merged["enrichment_status"] = refreshed.get(
            "enrichment_status", current.get("enrichment_status", "")
        )
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(
        description="교정한 미매칭 상품만 약학정보원에서 다시 검색해 공식 연결을 갱신합니다."
    )
    parser.add_argument("--input", type=Path, default=ROOT / "data/enrichment-queue.json")
    parser.add_argument(
        "--corrections", type=Path, default=ROOT / "data/catalog-text-corrections.json"
    )
    parser.add_argument("--csv", type=Path, default=ROOT / "data/enrichment-queue.csv")
    parser.add_argument(
        "--public-json", type=Path, default=ROOT / "public/data/enrichment-queue.json"
    )
    parser.add_argument(
        "--public-csv", type=Path, default=ROOT / "public/data/enrichment-queue.csv"
    )
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--min-interval", type=float, default=0.18)
    parser.add_argument(
        "--all-unmatched",
        action="store_true",
        help="교정 목록 대신 현재 confirmed가 아닌 모든 상품을 다시 조회합니다.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "etc/image-research/corrected-official-rematch-report.json",
    )
    args = parser.parse_args()

    products = read_array(args.input)
    corrections = read_array(args.corrections)
    approved_ids = (
        {
            str(row.get("document_id"))
            for row in products
            if row.get("official_match_status") != "confirmed"
        }
        if args.all_unmatched
        else {str(row.get("document_id")) for row in corrections if row.get("approved")}
    )
    by_id = {str(row.get("document_id")): index for index, row in enumerate(products)}
    missing = sorted(approved_ids - set(by_id))
    if missing:
        raise ValueError(f"교정 상품을 정식 데이터에서 찾지 못했습니다: {missing}")

    before_counts = Counter(str(row.get("official_match_status") or "") for row in products)
    client = HealthKrClient(args.cache_dir, min_interval=args.min_interval)
    transitions: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for position, document_id in enumerate(
        sorted(approved_ids, key=lambda item: int(products[by_id[item]]["source_order"])),
        start=1,
    ):
        index = by_id[document_id]
        current = products[index]
        before_status = str(current.get("official_match_status") or "")
        try:
            refreshed = process_record(client, current, include_aux=True)
            products[index] = merge_refresh_result(current, refreshed)
            after_status = str(products[index].get("official_match_status") or "")
            transitions.append(
                {
                    "source_order": current.get("source_order"),
                    "document_id": document_id,
                    "name": current.get("name"),
                    "before_status": before_status,
                    "after_status": after_status,
                    "official_item_name": products[index].get("official_item_name", ""),
                    "official_source_url": products[index].get("official_source_url", ""),
                }
            )
            print(
                f"[{position:03d}/{len(approved_ids)}] {current.get('name')} "
                f"{before_status} -> {after_status}",
                flush=True,
            )
        except Exception as error:  # 개별 외부 사이트 실패가 나머지 재검사를 막지 않게 합니다.
            failures.append(
                {
                    "source_order": current.get("source_order"),
                    "document_id": document_id,
                    "name": current.get("name"),
                    "error": f"{type(error).__name__}: {error}",
                }
            )
            print(
                f"[{position:03d}/{len(approved_ids)}] ERROR {current.get('name')}: "
                f"{type(error).__name__}: {error}",
                flush=True,
            )

    after_counts = Counter(str(row.get("official_match_status") or "") for row in products)
    payload = json.dumps(products, ensure_ascii=False, indent=2) + "\n"
    atomic_write_text(args.input, payload)
    atomic_write_text(args.public_json, payload)
    write_csv(args.csv, products)
    write_csv(args.public_csv, products)

    report = {
        "corrected_product_count": len(approved_ids),
        "processed_count": len(transitions),
        "failure_count": len(failures),
        "newly_confirmed_count": sum(
            row["before_status"] != "confirmed" and row["after_status"] == "confirmed"
            for row in transitions
        ),
        "before_status_counts": dict(sorted(before_counts.items())),
        "after_status_counts": dict(sorted(after_counts.items())),
        "transitions": transitions,
        "failures": failures,
    }
    atomic_write_text(
        args.report, json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps({key: value for key, value in report.items() if key not in {"transitions", "failures"}}, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
