from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.catalog_text_normalization import (
    clean_ingredient,
    clean_interaction_text,
    normalize_health_text,
    parse_health_rich_text,
)

try:
    from scripts.apply_catalog_text_corrections import atomic_write_text, write_csv
except ModuleNotFoundError:
    from apply_catalog_text_corrections import atomic_write_text, write_csv


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "enrichment-queue.json"
DEFAULT_CSV = ROOT / "data" / "enrichment-queue.csv"
DEFAULT_CACHE = ROOT / "etc" / "health-enrichment" / "cache" / "detail"
DEFAULT_REPORT = ROOT / "etc" / "text-normalization" / "catalog-content-normalization.json"
NORMALIZATION_VERSION = "catalog-text-v1"

RAW_TO_PUBLIC_FIELDS = {
    "effect": "official_efficacy",
    "dosage": "official_dosage",
    "caution": "official_precautions",
    "stmt": "official_storage",
    "drug_box": "official_pack_unit",
    "drug_form": "official_dosage_form",
    "dosage_route": "official_route",
    "charact_new": "official_appearance",
}

PUBLIC_TEXT_FIELDS = (
    "official_item_name",
    "official_manufacturer",
    "official_english_name",
    "official_category",
    "official_dosage_form",
    "official_route",
    "official_atc_code",
    "official_kpic_atc",
    "official_pack_unit",
    "official_storage",
    "official_valid_term",
    "official_appearance",
    "official_efficacy",
    "official_dosage",
    "official_precautions",
    "official_professional_precautions",
    "official_patient_guidance",
    "official_medication_guide",
    "official_medication_summary",
    "official_identification",
    "official_dur_contraindications",
    "official_dur_age",
    "official_dur_pregnancy",
    "official_dur_senior",
    "official_dur_max_dose",
    "official_dur_max_period",
    "official_dur_split_dosage",
)

STRUCTURED_FIELDS = {
    "efficacy": "official_efficacy",
    "dosage": "official_dosage",
    "precautions": "official_precautions",
    "professional_precautions": "official_professional_precautions",
    "patient_guidance": "official_patient_guidance",
    "medication_guide": "official_medication_guide",
}


def stable_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def normalize_display_text(value: Any) -> str:
    text = unicodedata.normalize("NFC", str(value or ""))
    text = re.sub(r"[\u200b-\u200f\u2060\ufeff]", "", text)
    text = text.replace("\u00a0", " ").replace("\u3000", " ")
    return re.sub(r"[ \t]+", " ", text).strip()


def cache_path(cache_dir: Path, code: str) -> Path:
    return cache_dir / f"{hashlib.sha256(code.encode('utf-8')).hexdigest()}.json"


def load_source(cache_dir: Path, code: str) -> dict[str, Any] | None:
    path = cache_path(cache_dir, code)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def normalize_string_list(value: Any, *, ingredient: bool = False) -> list[str]:
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value:
        text = clean_ingredient(item) if ingredient else normalize_health_text(item)
        if text and text not in output:
            output.append(text)
    return output


def normalize_interactions(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []

    def clean(item: Any) -> Any:
        if isinstance(item, str):
            return clean_interaction_text(item)
        if isinstance(item, list):
            return [clean(child) for child in item]
        if isinstance(item, dict):
            return {str(key): clean(child) for key, child in item.items()}
        return item

    return [clean(item) for item in value]


def normalize_guidance(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    output: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(item, str):
            continue
        text = normalize_health_text(item)
        if text:
            output[str(key)] = text
    return output


def normalize_product(product: dict[str, Any], cache_dir: Path) -> dict[str, Any]:
    before = copy.deepcopy(product)
    for field in ("name", "capacity", "category", "etc", "specification"):
        if field in product:
            product[field] = normalize_display_text(product.get(field))

    confirmed = product.get("official_match_status") == "confirmed"
    code = str(product.get("official_item_seq") or "")
    source = load_source(cache_dir, code) if confirmed and code else None

    if confirmed:
        rich_sources: dict[str, Any] = {}
        existing_content = product.get("official_content")
        if not isinstance(existing_content, dict):
            existing_content = {}
        if source:
            for raw_field, public_field in RAW_TO_PUBLIC_FIELDS.items():
                raw_value = source.get(raw_field)
                if raw_field == "charact_new" and not raw_value:
                    raw_value = source.get("charact")
                if raw_value not in {None, ""}:
                    rich_sources[public_field] = raw_value
                    product[public_field] = normalize_health_text(raw_value)

        for field in PUBLIC_TEXT_FIELDS:
            if field in product:
                product[field] = normalize_health_text(product.get(field))

        product["official_ingredients"] = normalize_string_list(
            product.get("official_ingredients"), ingredient=True
        )
        product["official_active_ingredients"] = normalize_string_list(
            product.get("official_active_ingredients"), ingredient=True
        )
        product["official_additives"] = normalize_string_list(product.get("official_additives"))
        product["official_interactions"] = normalize_interactions(
            product.get("official_interactions")
        )
        product["official_consumer_guidance"] = normalize_guidance(
            product.get("official_consumer_guidance")
        )

        content: dict[str, Any] = {
            "schema_version": "1.0",
            "normalization_version": NORMALIZATION_VERSION,
        }
        for key, field in STRUCTURED_FIELDS.items():
            existing_section = existing_content.get(key)
            if (
                not source
                and isinstance(existing_section, dict)
                and isinstance(existing_section.get("text"), str)
                and isinstance(existing_section.get("blocks"), list)
            ):
                rich = copy.deepcopy(existing_section)
            else:
                rich = parse_health_rich_text(rich_sources.get(field, product.get(field)))
            if rich["text"]:
                content[key] = rich
        guidance = product.get("official_consumer_guidance")
        if guidance:
            content["consumer_guidance"] = guidance
        product["official_content"] = content
        if source:
            product["official_content_status"] = "normalized_from_upstream_cache"
        elif not product.get("official_content_status"):
            product["official_content_status"] = "normalized_from_canonical"
        if not product.get("official_upstream_updated_at"):
            product["official_upstream_updated_at"] = str(
                product.get("official_checked_at") or ""
            )
        if source:
            additional = product.setdefault("official_additional_data", {})
            if not isinstance(additional, dict):
                additional = {}
                product["official_additional_data"] = additional
            additional["health_kr_source_sha256"] = hashlib.sha256(
                stable_json_bytes(source)
            ).hexdigest()

    changed_fields = sorted(
        key for key in set(before) | set(product) if before.get(key) != product.get(key)
    )
    return {
        "document_id": str(product.get("document_id") or product.get("id") or ""),
        "name": str(product.get("name") or ""),
        "official_match_status": str(product.get("official_match_status") or ""),
        "official_item_seq": code,
        "source_cache": bool(source),
        "changed_fields": changed_fields,
    }


def normalize_products(
    products: list[dict[str, Any]], cache_dir: Path = DEFAULT_CACHE
) -> dict[str, Any]:
    rows = [normalize_product(product, cache_dir) for product in products]
    return {
        "normalization_version": NORMALIZATION_VERSION,
        "product_count": len(products),
        "confirmed_count": sum(
            product.get("official_match_status") == "confirmed" for product in products
        ),
        "source_cache_count": sum(row["source_cache"] for row in rows),
        "changed_product_count": sum(bool(row["changed_fields"]) for row in rows),
        "products": rows,
    }


def backup_file(path: Path, backup_dir: Path) -> None:
    if not path.is_file():
        return
    backup_dir.mkdir(parents=True, exist_ok=True)
    destination = backup_dir / path.name
    if not destination.exists():
        shutil.copy2(path, destination)


def main() -> int:
    parser = argparse.ArgumentParser(description="정식 카탈로그의 표시용 의약품 텍스트를 원문 캐시에서 재생성합니다.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    products = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(products, list) or not all(isinstance(row, dict) for row in products):
        raise SystemExit("입력 파일은 상품 객체의 JSON 배열이어야 합니다.")
    original = copy.deepcopy(products)
    report = normalize_products(products, args.cache)
    if len(products) != 776:
        raise SystemExit(f"상품 수가 776개가 아닙니다: {len(products)}")

    if args.check:
        if products != original:
            raise SystemExit(
                f"정규화되지 않은 상품이 {report['changed_product_count']}개 있습니다. "
                "npm run catalog:text:normalize를 실행하세요."
            )
        print(json.dumps({key: value for key, value in report.items() if key != "products"}, ensure_ascii=False))
        return 0

    backup_dir = ROOT / "etc" / "text-normalization" / "backups"
    baseline_path = backup_dir / args.input.name
    baseline_for_report = original
    if baseline_path.is_file():
        try:
            saved_baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            if isinstance(saved_baseline, list) and len(saved_baseline) == len(products):
                baseline_for_report = saved_baseline
        except (OSError, json.JSONDecodeError):
            pass
    for row_report, before, after in zip(
        report["products"], baseline_for_report, products, strict=True
    ):
        row_report["changed_fields"] = sorted(
            key
            for key in set(before) | set(after)
            if before.get(key) != after.get(key)
        )
    report["changed_product_count"] = sum(
        bool(row["changed_fields"]) for row in report["products"]
    )
    backup_file(args.input, backup_dir)
    backup_file(args.csv, backup_dir)
    payload = json.dumps(products, ensure_ascii=False, indent=2) + "\n"
    atomic_write_text(args.input, payload)
    write_csv(args.csv, products)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        args.report,
        json.dumps(
            {"generated_at": datetime.now().astimezone().isoformat(), **report},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )
    print(json.dumps({key: value for key, value in report.items() if key != "products"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
