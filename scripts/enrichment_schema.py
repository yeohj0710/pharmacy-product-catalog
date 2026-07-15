from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ENRICHMENT_FIELDS: tuple[str, ...] = (
    "duplicate_group_id",
    "duplicate_group_size",
    "official_item_name",
    "official_manufacturer",
    "official_item_seq",
    "official_source_type",
    "official_source_url",
    "official_match_score",
    "official_match_status",
    "official_checked_at",
    "image_kind",
    "image_url",
    "image_source_url",
    "image_rights_status",
    "image_checked_at",
    "enrichment_status",
)


def normalize(value: Any) -> str:
    text = re.sub(r"\([^)]*\)", "", str(value or "").lower())
    return re.sub(r"[^0-9a-z가-힣]", "", text)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


def build_duplicate_groups(products: list[dict[str, Any]]) -> dict[str, tuple[str, int]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for product in products:
        key = normalize(product.get("normalized_name") or product.get("name"))
        grouped[key].append(str(product.get("document_id") or product.get("id") or ""))

    duplicate_keys = sorted(key for key, ids in grouped.items() if key and len(ids) > 1)
    group_ids = {key: f"dup-{index:04d}" for index, key in enumerate(duplicate_keys, start=1)}
    return {
        key: (group_ids.get(key, ""), len(ids))
        for key, ids in grouped.items()
    }


def blank_enrichment(product: dict[str, Any], group_id: str, group_size: int) -> dict[str, Any]:
    row = dict(product)
    row.update(
        {
            "duplicate_group_id": group_id,
            "duplicate_group_size": group_size,
            "official_item_name": product.get("official_item_name", ""),
            "official_manufacturer": product.get("official_manufacturer", ""),
            "official_item_seq": product.get("official_item_seq", ""),
            "official_source_type": product.get("official_source_type", ""),
            "official_source_url": product.get("official_source_url", ""),
            "official_match_score": product.get("official_match_score", ""),
            "official_match_status": product.get("official_match_status", "pending"),
            "official_checked_at": product.get("official_checked_at", ""),
            "image_kind": product.get("image_kind", ""),
            "image_url": product.get("image_url", ""),
            "image_source_url": product.get("image_source_url", ""),
            "image_rights_status": product.get("image_rights_status", "미확인"),
            "image_checked_at": product.get("image_checked_at", ""),
            "enrichment_status": product.get("enrichment_status", "pending"),
        }
    )
    return row


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    preferred = [
        "document_id",
        "id",
        "name",
        "capacity",
        "category",
        "price",
        "duplicate_group_id",
        "duplicate_group_size",
        "official_item_name",
        "official_manufacturer",
        "official_item_seq",
        "official_source_type",
        "official_source_url",
        "official_match_score",
        "official_match_status",
        "official_checked_at",
        "image_kind",
        "image_url",
        "image_source_url",
        "image_rights_status",
        "image_checked_at",
        "enrichment_status",
    ]
    all_fields = list(dict.fromkeys(preferred + [key for row in rows for key in row]))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=all_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="공식 공개 출처 조사를 위한 별도 큐를 생성합니다.")
    parser.add_argument("--input", type=Path, default=Path("data/products.json"))
    parser.add_argument("--output-json", type=Path, default=Path("data/enrichment-queue.json"))
    parser.add_argument("--output-csv", type=Path, default=Path("data/enrichment-queue.csv"))
    parser.add_argument("--public-output-json", type=Path, default=Path("public/data/enrichment-queue.json"))
    parser.add_argument("--public-output-csv", type=Path, default=Path("public/data/enrichment-queue.csv"))
    parser.add_argument("--summary", type=Path, default=Path("data/enrichment-summary.json"))
    args = parser.parse_args()

    products = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(products, list):
        raise ValueError("입력 JSON의 최상위 값은 상품 배열이어야 합니다.")

    group_map = build_duplicate_groups(products)
    rows: list[dict[str, Any]] = []
    for product in products:
        key = normalize(product.get("normalized_name") or product.get("name"))
        group_id, group_size = group_map.get(key, ("", 1))
        rows.append(blank_enrichment(product, group_id, group_size))

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(args.output_csv, rows)
    args.public_output_json.parent.mkdir(parents=True, exist_ok=True)
    args.public_output_json.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(args.public_output_csv, rows)

    group_counts = Counter(row["duplicate_group_id"] for row in rows if row["duplicate_group_id"])
    summary = {
        "generated_at": now_iso(),
        "input": str(args.input.as_posix()),
        "product_count": len(rows),
        "duplicate_group_count": len(group_counts),
        "products_in_duplicate_groups": sum(group_counts.values()),
        "official_identity_missing_count": sum(not row["official_item_seq"] for row in rows),
        "official_manufacturer_missing_count": sum(not row["official_manufacturer"] for row in rows),
        "official_source_url_missing_count": sum(not row["official_source_url"] for row in rows),
        "image_missing_count": sum(not row["image_url"] for row in rows),
        "image_rights_unconfirmed_count": sum(
            row["image_rights_status"] in {"", "미확인"} for row in rows
        ),
        "enrichment_status_counts": dict(Counter(row["enrichment_status"] for row in rows)),
        "outputs": [
            str(args.output_json.as_posix()),
            str(args.output_csv.as_posix()),
            str(args.public_output_json.as_posix()),
            str(args.public_output_csv.as_posix()),
        ],
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
