from __future__ import annotations

import argparse
import csv
import glob
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DETAIL_FIELDS = (
    "official_efficacy",
    "official_dosage",
    "official_precautions",
    "official_storage",
    "official_dosage_form",
    "official_route",
    "official_pack_unit",
    "official_appearance",
    "official_category",
    "official_atc_code",
    "official_ingredients",
    "official_active_ingredients",
    "official_additives",
    "official_english_name",
    "official_insurance",
    "official_permit_date",
    "official_patient_guidance",
    "official_medication_guide",
    "official_medication_summary",
    "official_classification_code",
    "official_kpic_atc",
    "official_insurance_detail",
    "official_identification",
    "official_manufacturer_details",
    "official_insert_pdf_url",
    "official_dur_contraindications",
    "official_dur_age",
    "official_dur_pregnancy",
    "official_dur_senior",
    "official_dur_max_dose",
    "official_dur_max_period",
    "official_dur_split_dosage",
    "official_section_evidence",
    "official_additional_data",
    "official_images",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def csv_value(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    preferred = [
        "document_id", "id", "name", "capacity", "category", "price",
        "official_item_name", "official_manufacturer", "official_item_seq",
        "official_source_type", "official_source_url", "official_match_score",
        "official_match_status", "official_efficacy", "official_dosage",
        "official_precautions", "official_ingredients", "official_storage",
        "image_kind", "image_url", "image_source_url", "image_rights_status",
        "enrichment_status",
    ]
    fields = list(dict.fromkeys(preferred + [key for row in rows for key in row]))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: csv_value(value) for key, value in row.items()})


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def clean_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [clean_text(item) for item in value if clean_text(item)]
    text = clean_text(value)
    return [text] if text else []


def valid_kpic_image(value: Any) -> str:
    url = clean_text(value)
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    if parsed.scheme != "https" or parsed.hostname not in {"health.kr", "www.health.kr", "common.health.kr"}:
        return ""
    if "img_empty" in parsed.path.lower():
        return ""
    return url


def official_images(content: dict[str, Any], source_url: str, checked_at: str) -> list[dict[str, str]]:
    images = content.get("images") if isinstance(content.get("images"), dict) else {}
    output: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(url_value: Any, kind: str) -> None:
        url = valid_kpic_image(url_value)
        if not url or url in seen:
            return
        seen.add(url)
        output.append(
            {
                "url": url,
                "kind": kind,
                "source_url": source_url,
                "source_dataset_id": "kpic-drug-detail",
                "license": "",
                "fetched_at": checked_at,
            }
        )

    add(images.get("primary_url"), "package" if images.get("primary_type") != "pill" else "pill")
    for url in images.get("pack_urls") or []:
        add(url, "package")
    for url in images.get("identification_urls") or []:
        add(url, "pill")
    return output


def record_priority(record: dict[str, Any]) -> tuple[int, int, int]:
    status = clean_text(record.get("status"))
    status_rank = {"collected": 3, "confirmed": 3, "review_required": 2, "error": 1}.get(status, 0)
    content = record.get("content") if isinstance(record.get("content"), dict) else {}
    filled = sum(bool(content.get(key)) for key in ("ingredients", "efficacy", "dosage", "precautions", "storage"))
    return status_rank, int(record.get("match_score") or 0), filled


def choose_records(part_paths: list[Path]) -> dict[str, dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for path in part_paths:
        payload = read_json(path)
        if not isinstance(payload, list):
            raise ValueError(f"상세정보 파일의 최상위 값은 배열이어야 합니다: {path}")
        for record in payload:
            product_id = clean_text(record.get("catalog_product_id"))
            if not product_id:
                continue
            if product_id not in selected or record_priority(record) > record_priority(selected[product_id]):
                selected[product_id] = record
    return selected


def merge_product(product: dict[str, Any], record: dict[str, Any]) -> str:
    status = clean_text(record.get("status"))
    score = int(record.get("match_score") or 0)
    if status == "review_required" or score < 96:
        for field in DETAIL_FIELDS + ("official_content_status",):
            product.pop(field, None)
        if product.get("image_rights_status") == "official_source_preview":
            product.update(
                {
                    "image_kind": "",
                    "image_url": "",
                    "image_source_url": "",
                    "image_rights_status": "미확인",
                    "image_checked_at": "",
                }
            )
        product["official_match_status"] = "review_required"
        product["enrichment_status"] = "official_review_required"
        return "review_required"
    if status not in {"collected", "confirmed"}:
        return "skipped"

    content = record.get("content") if isinstance(record.get("content"), dict) else {}
    additional = content.get("additional") if isinstance(content.get("additional"), dict) else {}
    source_url = clean_text(record.get("source_url"))
    checked_at = clean_text(record.get("collected_at")) or now_iso()
    images = official_images(content, source_url, checked_at)
    ingredients = clean_list(content.get("ingredients"))
    classification = clean_text(content.get("classification")) or clean_text(additional.get("classification"))
    atc = clean_text(content.get("atc")) or clean_text(additional.get("atc"))
    appearance = clean_text(content.get("characteristics")) or clean_text(additional.get("appearance"))

    product.update(
        {
            "official_item_name": clean_text(record.get("kpic_name")),
            "official_manufacturer": clean_text(content.get("manufacturer")),
            "official_item_seq": clean_text(record.get("kpic_code")),
            "official_source_type": "약학정보원 의약품 상세정보",
            "official_source_url": source_url,
            "official_match_score": score,
            "official_match_status": "confirmed",
            "official_checked_at": checked_at,
            "official_domain": "health.kr",
            "official_efficacy": clean_text(content.get("efficacy")),
            "official_dosage": clean_text(content.get("dosage")),
            "official_precautions": clean_text(content.get("precautions")),
            "official_storage": clean_text(content.get("storage")),
            "official_dosage_form": clean_text(content.get("dosage_form")),
            "official_route": clean_text(content.get("route")),
            "official_pack_unit": clean_text(content.get("package")),
            "official_appearance": appearance,
            "official_category": classification,
            "official_atc_code": atc,
            "official_ingredients": ingredients,
            "official_active_ingredients": ingredients,
            "official_additives": clean_text(content.get("additives")) or clean_text(additional.get("additives")),
            "official_english_name": clean_text(additional.get("english_name")),
            "official_insurance": clean_text(content.get("insurance")) or clean_text(additional.get("insurance")),
            "official_permit_date": clean_text(content.get("permit_date")) or clean_text(additional.get("permit_date")),
            "official_patient_guidance": content.get("patient_guidance") or additional.get("medication_summary") or "",
            "official_medication_guide": content.get("medication_guide") or additional.get("medication_guide") or "",
            "official_medication_summary": content.get("medicine_summary") or additional.get("medication_summary") or "",
            "official_classification_code": clean_text(content.get("classification_code")) or clean_text(additional.get("classification_code")),
            "official_kpic_atc": clean_text(content.get("kpic_atc")) or clean_text(additional.get("kpic_atc")),
            "official_insurance_detail": clean_text(additional.get("insurance_detail")),
            "official_identification": content.get("identification") or additional.get("identification") or "",
            "official_manufacturer_details": content.get("manufacturer_details") or additional.get("manufacturer_details") or "",
            "official_insert_pdf_url": clean_text(content.get("insert_pdf_url")),
            "official_dur_contraindications": additional.get("dur_contraindications") or "",
            "official_dur_age": additional.get("dur_age") or "",
            "official_dur_pregnancy": additional.get("dur_pregnancy") or "",
            "official_dur_senior": additional.get("dur_senior") or "",
            "official_dur_max_dose": additional.get("dur_max_dose") or "",
            "official_dur_max_period": additional.get("dur_max_period") or "",
            "official_dur_split_dosage": additional.get("dur_split_dosage") or "",
            "official_section_evidence": record.get("section_evidence") or {},
            "official_additional_data": additional,
            "official_images": images,
            "official_content_status": "complete" if all(
                [ingredients, content.get("efficacy"), content.get("dosage"), content.get("precautions")]
            ) else "partial",
            "enrichment_status": "official_details_linked",
        }
    )
    if images:
        primary = images[0]
        product.update(
            {
                "image_kind": primary["kind"],
                "image_url": primary["url"],
                "image_source_url": source_url,
                "image_rights_status": "official_source_preview",
                "image_checked_at": checked_at,
            }
        )
    return "merged"


def merge_files(input_path: Path, part_paths: list[Path]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    products = read_json(input_path)
    if not isinstance(products, list):
        raise ValueError("상품 큐의 최상위 값은 배열이어야 합니다.")
    records = choose_records(part_paths)
    counts: Counter[str] = Counter()
    product_ids = {clean_text(row.get("id") or row.get("document_id")) for row in products}
    for product in products:
        product_id = clean_text(product.get("id") or product.get("document_id"))
        record = records.get(product_id)
        if not record:
            continue
        counts[merge_product(product, record)] += 1
    counts["orphan_records"] = sum(product_id not in product_ids for product_id in records)
    summary = {
        "generated_at": now_iso(),
        "product_count": len(products),
        "detail_record_count": len(records),
        "status_counts": dict(counts),
        "complete_detail_count": sum(row.get("official_content_status") == "complete" for row in products),
        "official_detail_count": sum(bool(row.get("official_efficacy") or row.get("official_dosage")) for row in products),
        "image_count": sum(bool(row.get("image_url")) for row in products),
        "sources": [str(path.as_posix()) for path in part_paths],
    }
    return products, summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="분할 수집한 약학정보원 상세정보를 상품 큐에 병합합니다.")
    parser.add_argument("--input", type=Path, default=Path("data/enrichment-queue.json"))
    parser.add_argument("--output", type=Path, default=Path("data/enrichment-queue.json"))
    parser.add_argument("--csv", type=Path, default=Path("data/enrichment-queue.csv"))
    parser.add_argument("--summary", type=Path, default=Path("data/kpic-details-summary.json"))
    parser.add_argument("--part", action="append", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    part_paths = args.part or [Path(path) for path in sorted(glob.glob("data/kpic-details-part-[123].json"))]
    if not part_paths:
        raise ValueError("병합할 약학정보원 상세정보 파일이 없습니다.")
    products, summary = merge_files(args.input, part_paths)
    write_json_atomic(args.output, products)
    write_csv(args.csv, products)
    write_json_atomic(args.summary, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
