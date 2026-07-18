from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "enrichment-queue.json"
DEFAULT_OUTPUT = ROOT / "data" / "portable" / "v1"
SCHEMA_VERSION = "1.0"
PACKAGE_VERSION = "pharmacy-product-catalog-v1"


def compact(value: Any) -> str:
    return str(value or "").strip()


def image_record(product: dict[str, Any]) -> dict[str, Any] | None:
    url = compact(product.get("image_url"))
    if not url:
        return None
    return {
        "url": url,
        "source_url": compact(product.get("image_source_url")) or None,
        "kind": compact(product.get("image_kind")) or None,
        "rights_status": compact(product.get("image_rights_status")) or None,
        "checked_at": compact(product.get("image_checked_at")) or None,
    }


def medicine_record(product: dict[str, Any]) -> dict[str, Any] | None:
    if product.get("official_match_status") != "confirmed":
        return None
    content = product.get("official_content")
    if not isinstance(content, dict):
        content = {}
    return {
        "identity": {
            "item_name": compact(product.get("official_item_name")) or None,
            "item_code": compact(product.get("official_item_seq")) or None,
            "manufacturer": compact(product.get("official_manufacturer")) or None,
            "english_name": compact(product.get("official_english_name")) or None,
            "category": compact(product.get("official_category")) or None,
            "classification_code": compact(product.get("official_classification_code")) or None,
            "dosage_form": compact(product.get("official_dosage_form")) or None,
            "route": compact(product.get("official_route")) or None,
            "pack_unit": compact(product.get("official_pack_unit")) or None,
            "atc_code": compact(product.get("official_atc_code")) or None,
        },
        "content": copy.deepcopy(content),
        "ingredients": {
            "active": copy.deepcopy(product.get("official_active_ingredients") or []),
            "all": copy.deepcopy(product.get("official_ingredients") or []),
            "additives": copy.deepcopy(product.get("official_additives") or []),
        },
        "storage": compact(product.get("official_storage")) or None,
        "appearance": compact(product.get("official_appearance")) or None,
        "source": {
            "type": compact(product.get("official_source_type")) or None,
            "url": compact(product.get("official_source_url")) or None,
            "checked_at": compact(product.get("official_checked_at")) or None,
        },
    }


def build_ai_context(record: dict[str, Any]) -> str:
    display = record["display"]
    lines = [
        f"상품명: {display['name']}",
        f"규격: {display['specification']}",
        f"분류: {display['category']}",
        f"가격(원): {display['price_krw']}",
    ]
    medicine = record.get("medicine")
    if medicine:
        identity = medicine["identity"]
        for label, key in (
            ("약학정보원 품목명", "item_name"),
            ("제조사", "manufacturer"),
            ("제형", "dosage_form"),
            ("포장단위", "pack_unit"),
        ):
            if identity.get(key):
                lines.append(f"{label}: {identity[key]}")
        content = medicine.get("content") or {}
        for label, key in (
            ("효능·효과", "efficacy"),
            ("용법·용량", "dosage"),
            ("사용상의 주의사항", "precautions"),
            ("복약 안내", "medication_guide"),
        ):
            section = content.get(key)
            if isinstance(section, dict) and compact(section.get("text")):
                lines.append(f"{label}:\n{section['text'].strip()}")
        source_url = medicine.get("source", {}).get("url")
        if source_url:
            lines.append(f"약학정보원 출처: {source_url}")
    image = record.get("media", {}).get("primary_image")
    if image and image.get("source_url"):
        lines.append(f"제품 이미지 출처: {image['source_url']}")
    return "\n\n".join(lines)


def build_portable_record(product: dict[str, Any]) -> dict[str, Any]:
    record = {
        "schema_version": SCHEMA_VERSION,
        "product_id": compact(product.get("document_id") or product.get("id")),
        "display": {
            "name": compact(product.get("name")),
            "specification": compact(product.get("capacity") or product.get("specification")),
            "category": compact(product.get("category")),
            "price_krw": int(product.get("displayed_price_krw") or product.get("price") or 0),
            "notes": compact(product.get("etc")) or None,
            "source_order": int(product.get("source_order") or 0),
        },
        "media": {"primary_image": image_record(product)},
        "medicine": medicine_record(product),
        "quality": {
            "verification_status": compact(product.get("verification_status")) or None,
            "official_match_status": compact(product.get("official_match_status")) or None,
            "official_content_status": compact(product.get("official_content_status")) or None,
            "image_rights_status": compact(product.get("image_rights_status")) or None,
        },
        "provenance": {
            "catalog_source_type": compact(product.get("source_type")) or None,
            "catalog_recorded_at": compact(product.get("recorded_at")) or None,
            "catalog_document_updated_at": compact(product.get("document_update_time")) or None,
        },
    }
    record["ai_context"] = build_ai_context(record)
    return record


def portable_schema() -> dict[str, Any]:
    nullable_string = {"type": ["string", "null"]}
    rich_text = {
        "type": "object",
        "additionalProperties": False,
        "required": ["text", "blocks"],
        "properties": {
            "text": {"type": "string", "minLength": 1},
            "blocks": {
                "type": "array",
                "items": {
                    "oneOf": [
                        {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["type", "text"],
                            "properties": {
                                "type": {"const": "paragraph"},
                                "text": {"type": "string", "minLength": 1},
                            },
                        },
                        {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["type", "headers", "rows"],
                            "properties": {
                                "type": {"const": "table"},
                                "headers": {"type": "array", "items": {"type": "string"}},
                                "rows": {
                                    "type": "array",
                                    "items": {"type": "array", "items": {"type": "string"}},
                                },
                            },
                        },
                    ]
                },
            },
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://pharmacy-product-catalog.vercel.app/data/portable/v1/schema.json",
        "title": "Pharmacy Product Catalog Portable Record v1",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "product_id",
            "display",
            "media",
            "medicine",
            "quality",
            "provenance",
            "ai_context",
        ],
        "properties": {
            "schema_version": {"const": SCHEMA_VERSION},
            "product_id": {"type": "string", "minLength": 1},
            "display": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "specification", "category", "price_krw", "notes", "source_order"],
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "specification": {"type": "string"},
                    "category": {"type": "string"},
                    "price_krw": {"type": "integer", "minimum": 0},
                    "notes": {"type": ["string", "null"]},
                    "source_order": {"type": "integer", "minimum": 0},
                },
            },
            "media": {
                "type": "object",
                "additionalProperties": False,
                "required": ["primary_image"],
                "properties": {
                    "primary_image": {
                        "type": ["object", "null"],
                        "additionalProperties": False,
                        "required": ["url", "source_url", "kind", "rights_status", "checked_at"],
                        "properties": {
                            "url": {"type": "string", "minLength": 1},
                            "source_url": nullable_string,
                            "kind": nullable_string,
                            "rights_status": nullable_string,
                            "checked_at": nullable_string,
                        },
                    }
                },
            },
            "medicine": {
                "type": ["object", "null"],
                "additionalProperties": False,
                "required": ["identity", "content", "ingredients", "storage", "appearance", "source"],
                "properties": {
                    "identity": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["item_name", "item_code", "manufacturer", "english_name", "category", "classification_code", "dosage_form", "route", "pack_unit", "atc_code"],
                        "properties": {key: nullable_string for key in ("item_name", "item_code", "manufacturer", "english_name", "category", "classification_code", "dosage_form", "route", "pack_unit", "atc_code")},
                    },
                    "content": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["schema_version", "normalization_version"],
                        "properties": {
                            "schema_version": {"const": "1.0"},
                            "normalization_version": {"type": "string", "minLength": 1},
                            **{key: rich_text for key in ("efficacy", "dosage", "precautions", "professional_precautions", "patient_guidance", "medication_guide")},
                            "consumer_guidance": {"type": "object", "additionalProperties": {"type": "string"}},
                        },
                    },
                    "ingredients": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["active", "all", "additives"],
                        "properties": {key: {"type": "array", "items": {"type": "string"}} for key in ("active", "all", "additives")},
                    },
                    "storage": nullable_string,
                    "appearance": nullable_string,
                    "source": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["type", "url", "checked_at"],
                        "properties": {key: nullable_string for key in ("type", "url", "checked_at")},
                    },
                },
            },
            "quality": {
                "type": "object",
                "additionalProperties": False,
                "required": ["verification_status", "official_match_status", "official_content_status", "image_rights_status"],
                "properties": {key: nullable_string for key in ("verification_status", "official_match_status", "official_content_status", "image_rights_status")},
            },
            "provenance": {
                "type": "object",
                "additionalProperties": False,
                "required": ["catalog_source_type", "catalog_recorded_at", "catalog_document_updated_at"],
                "properties": {key: nullable_string for key in ("catalog_source_type", "catalog_recorded_at", "catalog_document_updated_at")},
            },
            "ai_context": {"type": "string", "minLength": 1},
        },
    }


README = """# Pharmacy Product Catalog portable data v1

This directory is the stable cross-project data package. `products.json` is a JSON array,
`products.ndjson` contains one equivalent record per line for AI or search ingestion,
`schema.json` defines the record contract, and `manifest.json` provides counts and hashes.

Use `medicine: null` as an explicit non-match. Never infer medicine facts from the retail
name when `quality.official_match_status` is not `confirmed`. `ai_context` contains only
normalized public facts and source URLs; raw upstream HTML is intentionally excluded.

Regenerate with `python scripts/export_portable_catalog.py` after canonical normalization.
Breaking field changes require a new `data/portable/vN/` directory and schema version.
"""


def write_json(path: Path, value: Any) -> None:
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _type_matches(value: Any, expected: str) -> bool:
    return {
        "null": value is None,
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
    }.get(expected, False)


def validate_schema_value(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    if "oneOf" in schema:
        results = [validate_schema_value(value, candidate, path) for candidate in schema["oneOf"]]
        if sum(not result for result in results) != 1:
            return [f"{path}: value must match exactly one schema"]
        return []
    if "const" in schema and value != schema["const"]:
        return [f"{path}: expected constant {schema['const']!r}"]

    expected = schema.get("type")
    if expected:
        expected_types = expected if isinstance(expected, list) else [expected]
        if not any(_type_matches(value, item) for item in expected_types):
            return [f"{path}: expected type {expected_types}, got {type(value).__name__}"]
        if value is None:
            return []

    errors: list[str] = []
    if isinstance(value, dict) and (expected == "object" or "object" in (expected or [])):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required field {key!r}")
        additional = schema.get("additionalProperties", True)
        for key, item in value.items():
            if key in properties:
                errors.extend(validate_schema_value(item, properties[key], f"{path}.{key}"))
            elif additional is False:
                errors.append(f"{path}: unexpected field {key!r}")
            elif isinstance(additional, dict):
                errors.extend(validate_schema_value(item, additional, f"{path}.{key}"))
    if isinstance(value, list) and (expected == "array" or "array" in (expected or [])):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors.extend(validate_schema_value(item, item_schema, f"{path}[{index}]"))
    if isinstance(value, str) and "minLength" in schema and len(value) < int(schema["minLength"]):
        errors.append(f"{path}: string is shorter than {schema['minLength']}")
    if isinstance(value, int) and not isinstance(value, bool) and "minimum" in schema and value < schema["minimum"]:
        errors.append(f"{path}: value is below {schema['minimum']}")
    return errors


def export_package(
    products: list[dict[str, Any]], output: Path, *, expected_count: int = 776
) -> dict[str, Any]:
    if len(products) != expected_count:
        raise ValueError(
            f"Portable package requires exactly {expected_count} products; got {len(products)}"
        )
    output.mkdir(parents=True, exist_ok=True)
    records = [build_portable_record(product) for product in products]
    ids = [record["product_id"] for record in records]
    if any(not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("Portable product IDs must be non-empty and unique")

    products_path = output / "products.json"
    ndjson_path = output / "products.ndjson"
    schema_path = output / "schema.json"
    readme_path = output / "README.md"
    write_json(products_path, records)
    ndjson_path.write_bytes(
        "".join(
            json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
            for record in records
        ).encode("utf-8")
    )
    write_json(schema_path, portable_schema())
    readme_path.write_bytes(README.encode("utf-8"))

    manifest = {
        "package_version": PACKAGE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "product_count": len(records),
        "official_confirmed_count": sum(record["medicine"] is not None for record in records),
        "image_count": sum(record["media"]["primary_image"] is not None for record in records),
        "files": {
            "products.json": {"sha256": sha256(products_path)},
            "products.ndjson": {"sha256": sha256(ndjson_path)},
            "schema.json": {"sha256": sha256(schema_path)},
            "README.md": {"sha256": sha256(readme_path)},
        },
    }
    write_json(output / "manifest.json", manifest)
    return manifest


def validate_package(output: Path, *, expected_count: int = 776) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    required_files = ("products.json", "products.ndjson", "schema.json", "manifest.json")
    for name in required_files:
        if not (output / name).is_file():
            errors.append({"kind": "missing_file", "file": name})
    if errors:
        return {"error_count": len(errors), "errors": errors}

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    for name, metadata in manifest.get("files", {}).items():
        path = output / name
        if not path.is_file() or sha256(path) != metadata.get("sha256"):
            errors.append({"kind": "hash_mismatch", "file": name})

    try:
        records = json.loads((output / "products.json").read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"error_count": len(errors) + 1, "errors": [*errors, {"kind": "invalid_json", "error": str(exc)}]}
    ndjson_records: list[dict[str, Any]] = []
    for index, line in enumerate((output / "products.ndjson").read_text(encoding="utf-8").splitlines(), start=1):
        try:
            ndjson_records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            errors.append({"kind": "invalid_ndjson", "line": index, "error": str(exc)})

    if not isinstance(records, list):
        errors.append({"kind": "products_not_array"})
        records = []
    if records != ndjson_records:
        errors.append({"kind": "json_ndjson_mismatch"})
    if len(records) != manifest.get("product_count"):
        errors.append({"kind": "product_count_mismatch"})
    if len(records) != expected_count:
        errors.append(
            {"kind": "unexpected_product_count", "expected": expected_count, "actual": len(records)}
        )

    ids: set[str] = set()
    record_schema = portable_schema()
    damaged = re.compile(
        r"(?im)(?:^\s*br\s*$|(?<=[가-힣0-9.!?\]\)])br(?=\s*(?:\n|$))|</?[A-Za-z][^>]*>|\ufffd|[\u200b-\u200f\u2060\ufeff]|\d\s*\?\s*\d)"
    )

    def strings(value: Any, path: str = ""):
        if isinstance(value, str):
            yield path, value
        elif isinstance(value, list):
            for index, item in enumerate(value):
                yield from strings(item, f"{path}[{index}]")
        elif isinstance(value, dict):
            for key, item in value.items():
                yield from strings(item, f"{path}.{key}" if path else key)

    for index, record in enumerate(records):
        if not isinstance(record, dict):
            errors.append({"kind": "record_not_object", "index": index})
            continue
        product_id = compact(record.get("product_id"))
        if not product_id or product_id in ids:
            errors.append({"kind": "missing_or_duplicate_product_id", "index": index, "product_id": product_id})
        ids.add(product_id)
        for key in ("schema_version", "display", "media", "medicine", "quality", "provenance", "ai_context"):
            if key not in record:
                errors.append({"kind": "missing_required_field", "product_id": product_id, "field": key})
        if record.get("schema_version") != SCHEMA_VERSION:
            errors.append({"kind": "schema_version_mismatch", "product_id": product_id})
        for schema_error in validate_schema_value(record, record_schema):
            errors.append(
                {
                    "kind": "schema_validation",
                    "product_id": product_id,
                    "error": schema_error,
                }
            )
        for path, text in strings(record):
            if damaged.search(text):
                errors.append({"kind": "damaged_text", "product_id": product_id, "field": path})
    return {"product_count": len(records), "error_count": len(errors), "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description="다른 프로젝트와 AI API에서 사용할 휴대형 카탈로그를 생성합니다.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    products = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(products, list) or not all(isinstance(row, dict) for row in products):
        raise SystemExit("입력 파일은 상품 객체의 JSON 배열이어야 합니다.")
    if args.check:
        validation = validate_package(args.output)
        if validation["error_count"]:
            raise SystemExit(f"Portable package validation failed: {validation['error_count']} errors")
        with tempfile.TemporaryDirectory() as directory:
            expected = Path(directory)
            export_package(products, expected)
            for name in ("products.json", "products.ndjson", "schema.json", "manifest.json", "README.md"):
                if (args.output / name).read_bytes() != (expected / name).read_bytes():
                    raise SystemExit(f"Portable package is stale: {name}")
        print(json.dumps({"product_count": len(products), "validation_errors": 0, "up_to_date": True}, ensure_ascii=False))
        return 0

    manifest = export_package(products, args.output)
    if len(products) == 776 and manifest["product_count"] != 776:
        raise SystemExit("Portable package product count mismatch")
    validation = validate_package(args.output)
    if validation["error_count"]:
        raise SystemExit(f"Portable package validation failed: {validation['error_count']} errors")
    print(json.dumps({**manifest, "validation_errors": 0}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
