from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path, fallback: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else fallback


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def content_status(record: dict[str, Any]) -> str:
    content = record.get("content", {})
    classification = record.get("classification", {})
    identifiers = record.get("identifiers", {})
    domain = record.get("source_domain", "")
    required = {
        "drug": [content.get("efficacy"), content.get("dosage"), content.get("precautions")],
        "quasi_drug": [content.get("efficacy"), content.get("dosage")],
        "supplement": [content.get("efficacy"), content.get("dosage"), content.get("precautions")],
        "cosmetic": [record.get("manufacturer"), classification.get("category")],
        "medical_device": [record.get("manufacturer"), identifiers.get("udi_di")],
        "food": [record.get("manufacturer"), content.get("pack_unit"), record.get("images")],
    }.get(domain, [record.get("item_name")])
    observed = [value for value in required if value not in (None, "", [], {})]
    return "complete" if len(observed) == len(required) else "partial" if observed else "pending"


def materialize_products(
    products: list[dict[str, Any]],
    matches: list[dict[str, Any]],
    official_products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    matches_by_id = {str(match.get("catalog_product_id", "")): match for match in matches}
    official_by_key = {str(record.get("official_product_key", "")): record for record in official_products}
    output: list[dict[str, Any]] = []
    for product in products:
        row = dict(product)
        product_id = str(product.get("id") or product.get("document_id") or "")
        match = matches_by_id.get(product_id)
        if not match:
            output.append(row)
            continue
        row["official_match_status"] = match.get("status", "pending")
        row["official_match_score"] = match.get("score", "")
        row["lookup_status"] = "found" if match.get("status") in {"confirmed", "review_required"} else match.get("status", "pending")
        row["match_alternatives"] = match.get("alternatives", [])
        if match.get("status") != "confirmed":
            row["enrichment_status"] = "review_required" if match.get("status") == "review_required" else match.get("status", "pending")
            output.append(row)
            continue
        record = official_by_key.get(str(match.get("official_product_key", "")))
        if not record:
            row["enrichment_status"] = "error"
            row["enrichment_error"] = "확정된 공식 제품 레코드를 찾을 수 없습니다."
            output.append(row)
            continue
        identifiers = record.get("identifiers", {})
        classification = record.get("classification", {})
        content = record.get("content", {})
        provenance = record.get("provenance", {})
        images = record.get("images", [])
        first_image = images[0] if images else {}
        row.update({
            "official_product_key": record.get("official_product_key", ""),
            "official_domain": record.get("source_domain", ""),
            "official_item_name": record.get("item_name", ""),
            "official_manufacturer": record.get("manufacturer", ""),
            "official_item_seq": identifiers.get("item_seq", ""),
            "official_barcode": identifiers.get("barcode", ""),
            "official_standard_codes": identifiers.get("standard_codes", []),
            "official_report_number": identifiers.get("report_number", ""),
            "official_udi_di": identifiers.get("udi_di", ""),
            "official_category": classification.get("category", ""),
            "official_dosage_form": classification.get("dosage_form", ""),
            "official_route": classification.get("route", ""),
            "official_atc_code": classification.get("atc_code", ""),
            "official_pack_unit": content.get("pack_unit", ""),
            "official_storage": content.get("storage", ""),
            "official_valid_term": content.get("valid_term", ""),
            "official_appearance": content.get("appearance", ""),
            "official_efficacy": content.get("efficacy", ""),
            "official_dosage": content.get("dosage", ""),
            "official_precautions": content.get("precautions", ""),
            "official_professional_precautions": content.get("professional_precautions", ""),
            "official_ingredients": content.get("ingredients", []),
            "official_active_ingredients": content.get("active_ingredients", []),
            "official_consumer_guidance": content.get("consumer_guidance", {}),
            "official_images": images,
            "official_source_type": f"공공데이터포털 {provenance.get('source_dataset_id', '')}",
            "official_source_url": provenance.get("source_url", ""),
            "official_license": provenance.get("license", ""),
            "official_checked_at": provenance.get("fetched_at", ""),
            "official_upstream_updated_at": provenance.get("upstream_updated_at", ""),
            "official_raw_sha256": provenance.get("raw_sha256", ""),
            "official_content_status": content_status(record),
            "image_url": first_image.get("url", ""),
            "image_source_url": first_image.get("source_url", ""),
            "image_rights_status": "approved" if first_image.get("license") else "미확인",
            "image_kind": first_image.get("kind", ""),
            "image_checked_at": first_image.get("fetched_at", ""),
            "enrichment_status": "complete" if content_status(record) == "complete" else "partial",
        })
        output.append(row)
    return output


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                key: json.dumps(value, ensure_ascii=False, separators=(",", ":")) if isinstance(value, (dict, list)) else value
                for key, value in row.items()
            })
    temporary.replace(path)


def main() -> int:
    command = argparse.ArgumentParser(description="확정된 공식 제품 데이터를 사이트용 상품 목록에 병합합니다.")
    command.add_argument("--input", type=Path, default=ROOT / "data/enrichment-queue.json")
    command.add_argument("--matches", type=Path, default=ROOT / "data/product-official-matches.json")
    command.add_argument("--official", type=Path, default=ROOT / "data/official-product-details.json")
    command.add_argument("--output-json", type=Path, default=ROOT / "data/enrichment-queue.json")
    command.add_argument("--output-csv", type=Path, default=ROOT / "data/enrichment-queue.csv")
    command.add_argument("--summary", type=Path, default=ROOT / "data/official-data-summary.json")
    args = command.parse_args()

    products = read_json(args.input, [])
    matches = read_json(args.matches, [])
    official = read_json(args.official, [])
    output = materialize_products(products, matches, official)
    write_json_atomic(args.output_json, output)
    write_csv(args.output_csv, output)
    status_counts = Counter(row.get("enrichment_status", "pending") for row in output)
    summary = read_json(args.summary, {})
    summary.update({
        "materialized_product_count": len(output),
        "materialized_status_counts": dict(sorted(status_counts.items())),
        "materialized_image_count": sum(bool(row.get("image_url")) for row in output),
    })
    write_json_atomic(args.summary, summary)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
