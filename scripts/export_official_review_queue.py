from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FIELDS = [
    "batch_no", "source_order", "catalog_product_id", "catalog_name", "catalog_capacity",
    "catalog_category", "catalog_price", "lookup_status", "match_status", "official_product_key",
    "official_domain", "official_item_seq", "official_name", "official_manufacturer",
    "official_dosage_form", "official_pack_unit", "official_barcode", "official_dataset_id",
    "official_source_url", "official_efficacy", "official_dosage", "official_precautions",
    "official_ingredients_json", "official_images_json", "match_score", "match_reason",
    "conflict_reasons_json", "reviewer", "reviewed_at",
]


def lookup_status(match_status: str) -> str:
    return {
        "confirmed": "found",
        "review_required": "found",
        "not_found": "not_found",
        "not_applicable": "not_applicable",
        "blocked_missing_key": "blocked",
        "error": "error",
    }.get(match_status, "pending")


def score_reason(match: dict) -> str:
    components = match.get("score_components", {})
    labels = {
        "identifier": "공식 식별자",
        "name": "제품명",
        "manufacturer": "업체",
        "capacity": "규격",
        "dosage_form": "제형",
        "unique_exact_name": "유일한 정확 제품명",
    }
    parts = [f"{labels.get(key, key)} {value}점" for key, value in components.items()]
    return ", ".join(parts)


def main() -> int:
    command = argparse.ArgumentParser(description="GPT Pro 또는 사람이 검수할 25개 단위 공식 제품 매칭표를 만듭니다.")
    command.add_argument("--input", type=Path, default=ROOT / "data/enrichment-queue.json")
    command.add_argument("--matches", type=Path, default=ROOT / "data/product-official-matches.json")
    command.add_argument("--official", type=Path, default=ROOT / "data/official-product-details.json")
    command.add_argument("--output", type=Path, default=ROOT / "data/gpt-pro-official-review-queue.csv")
    command.add_argument("--batch-size", type=int, default=25)
    args = command.parse_args()

    products = json.loads(args.input.read_text(encoding="utf-8"))
    matches = json.loads(args.matches.read_text(encoding="utf-8")) if args.matches.exists() else []
    matches_by_id = {str(match.get("catalog_product_id", "")): match for match in matches}
    official_products = json.loads(args.official.read_text(encoding="utf-8")) if args.official.exists() else []
    official_by_key = {str(record.get("official_product_key", "")): record for record in official_products}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for index, product in enumerate(products):
            product_id = str(product.get("id") or product.get("document_id") or "")
            match = matches_by_id.get(product_id, {})
            alternative = (match.get("alternatives") or [{}])[0]
            record = official_by_key.get(str(match.get("official_product_key", "")), {})
            identifiers = record.get("identifiers", {})
            classification = record.get("classification", {})
            content = record.get("content", {})
            provenance = record.get("provenance", {})
            writer.writerow({
                "batch_no": index // max(1, args.batch_size) + 1,
                "source_order": index + 1,
                "catalog_product_id": product_id,
                "catalog_name": product.get("name", ""),
                "catalog_capacity": product.get("capacity", ""),
                "catalog_category": product.get("category", ""),
                "catalog_price": product.get("price", ""),
                "lookup_status": lookup_status(str(match.get("status", "pending"))),
                "match_status": match.get("status", "pending"),
                "official_product_key": match.get("official_product_key", ""),
                "official_domain": record.get("source_domain") or alternative.get("source_domain", ""),
                "official_item_seq": identifiers.get("item_seq") or alternative.get("item_seq", ""),
                "official_name": record.get("item_name") or alternative.get("item_name", ""),
                "official_manufacturer": record.get("manufacturer") or alternative.get("manufacturer", ""),
                "official_dosage_form": classification.get("dosage_form") or alternative.get("dosage_form", ""),
                "official_pack_unit": content.get("pack_unit") or alternative.get("pack_unit", ""),
                "official_barcode": identifiers.get("barcode") or alternative.get("barcode", ""),
                "official_dataset_id": provenance.get("source_dataset_id") or alternative.get("source_dataset_id", ""),
                "official_source_url": provenance.get("source_url") or alternative.get("source_url", ""),
                "official_efficacy": content.get("efficacy", ""),
                "official_dosage": content.get("dosage", ""),
                "official_precautions": content.get("precautions", ""),
                "official_ingredients_json": json.dumps(content.get("ingredients", []), ensure_ascii=False),
                "official_images_json": json.dumps(record.get("images", []), ensure_ascii=False),
                "match_score": match.get("score", ""),
                "match_reason": score_reason(match),
                "conflict_reasons_json": json.dumps(match.get("conflicts", []), ensure_ascii=False),
                "reviewer": match.get("reviewer", ""),
                "reviewed_at": match.get("reviewed_at", ""),
            })
    temporary.replace(args.output)
    print(json.dumps({"rows": len(products), "batches": (len(products) + args.batch_size - 1) // args.batch_size, "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
