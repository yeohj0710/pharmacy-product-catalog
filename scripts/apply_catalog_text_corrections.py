from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

try:
    from scripts.enrichment_schema import build_duplicate_groups, normalize as duplicate_key
except ModuleNotFoundError:  # Direct execution: python scripts/apply_catalog_text_corrections.py
    from enrichment_schema import build_duplicate_groups, normalize as duplicate_key


ROOT = Path(__file__).resolve().parents[1]


def normalize(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", value.lower())


def apply_corrections(
    products: list[dict[str, Any]], corrections: list[dict[str, Any]]
) -> int:
    by_id = {str(product.get("document_id") or ""): product for product in products}
    if len(by_id) != len(products) or "" in by_id:
        raise ValueError("상품 document_id가 비어 있거나 중복됩니다.")

    seen: set[str] = set()
    changed = 0
    for correction in corrections:
        if not correction.get("approved"):
            continue
        document_id = str(correction.get("document_id") or "")
        if not document_id or document_id in seen:
            raise ValueError(f"교정 document_id가 비어 있거나 중복됩니다: {document_id!r}")
        seen.add(document_id)
        if document_id not in by_id:
            raise ValueError(f"교정할 상품을 찾지 못했습니다: {document_id}")

        evidence_urls = correction.get("evidence_urls")
        evidence_text = str(correction.get("evidence_text") or "").strip()
        if not isinstance(evidence_urls, list) or not any(
            str(url).startswith(("https://", "http://")) for url in evidence_urls
        ) or not evidence_text:
            raise ValueError(f"승인된 교정에 근거가 없습니다: {document_id}")

        product = by_id[document_id]
        original_name = str(correction.get("original_name") or "")
        corrected_name = str(correction.get("corrected_name") or "")
        original_capacity = str(correction.get("original_capacity") or "")
        corrected_capacity = str(correction.get("corrected_capacity") or "")
        if not corrected_name or not corrected_capacity:
            raise ValueError(f"교정 상품명 또는 규격이 비었습니다: {document_id}")

        current_name = str(product.get("name") or "")
        current_capacity = str(product.get("capacity") or "")
        accepted_previous_names = {
            str(value)
            for value in correction.get("accepted_previous_names", [])
            if str(value)
        }
        if current_name not in {original_name, corrected_name, *accepted_previous_names}:
            raise ValueError(
                f"원본 상품명이 예상과 다릅니다: {document_id} "
                f"({current_name!r} != {original_name!r})"
            )
        if current_capacity not in {original_capacity, corrected_capacity}:
            raise ValueError(
                f"원본 규격이 예상과 다릅니다: {document_id} "
                f"({current_capacity!r} != {original_capacity!r})"
            )

        desired = {
            "name": corrected_name,
            "capacity": corrected_capacity,
            "specification": corrected_capacity,
            "normalized_name": normalize(corrected_name),
            "normalized_capacity": normalize(corrected_capacity),
        }
        if any(product.get(key) != value for key, value in desired.items()):
            product.update(desired)
            changed += 1

    return changed


def refresh_duplicate_groups(products: list[dict[str, Any]]) -> int:
    """Rebuild deterministic duplicate metadata from the corrected display names."""
    group_map = build_duplicate_groups(products)
    changed = 0
    for product in products:
        key = duplicate_key(product.get("normalized_name") or product.get("name"))
        group_id, group_size = group_map.get(key, ("", 1))
        desired = {
            "duplicate_group_id": group_id,
            "duplicate_group_size": group_size,
        }
        if any(product.get(field) != value for field, value in desired.items()):
            product.update(desired)
            changed += 1
    return changed


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding=encoding)
    temporary.replace(path)


def value_as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def write_csv(path: Path, products: list[dict[str, Any]]) -> None:
    existing_header: list[str] = []
    if path.is_file():
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            existing_header = next(csv.reader(handle), [])
    all_fields = {key for product in products for key in product}
    fields = [field for field in existing_header if field in all_fields]
    fields.extend(sorted(all_fields - set(fields)))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for product in products:
            writer.writerow({key: value_as_text(value) for key, value in product.items()})
    temporary.replace(path)


def read_array(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
        raise ValueError(f"JSON 배열 형식이 아닙니다: {path}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="검수된 상품명·규격 교정을 표시용 필드에 적용합니다. app_* 원문은 보존합니다."
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
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    products = read_array(args.input)
    corrections = read_array(args.corrections)
    changed = apply_corrections(products, corrections)
    duplicate_changed = refresh_duplicate_groups(products)
    approved = sum(bool(row.get("approved")) for row in corrections)

    if args.check:
        if changed or duplicate_changed:
            raise SystemExit(
                f"표시용 상품명·규격 교정 {changed}건과 중복 그룹 {duplicate_changed}건이 "
                "정식 데이터에 적용되지 않았습니다. "
                "npm run catalog:correct를 실행하세요."
            )
        print(
            f"상품명·규격 교정 {approved}건과 중복 그룹 메타데이터가 모두 적용되어 있습니다."
        )
        return 0

    payload = json.dumps(products, ensure_ascii=False, indent=2) + "\n"
    atomic_write_text(args.input, payload)
    atomic_write_text(args.public_json, payload)
    write_csv(args.csv, products)
    write_csv(args.public_csv, products)
    print(
        f"상품명·규격 교정 {changed}건과 중복 그룹 {duplicate_changed}건을 적용했습니다"
        f"(승인 목록 {approved}건)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
