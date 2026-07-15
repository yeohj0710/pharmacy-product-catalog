from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import statistics
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from androguard.core.apk import APK
from loguru import logger


DEFAULT_APK = Path("etc/apk/com.hiddenwave.yakcheck-9.apk")
DEFAULT_COLLECTION = "products"
SOURCE_PACKAGE = "com.hiddenwave.yakcheck"
SOURCE_APP_VERSION = "11.0.0"
SOURCE_VERSION_CODE = 9
SOURCE_URL = "https://play.google.com/store/apps/details?id=com.hiddenwave.yakcheck"
PAGE_SIZE = 300
EXPECTED_FIELDS = ("id", "name", "capacity", "category", "price", "etc", "updated")
NOTIFICATION_PATTERNS = (
    "님에게 메시지를 보냈",
    "메시지가 도착",
    "카카오톡",
    "새 메시지",
)
PII_PATTERNS = {
    "email": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    "mobile_phone": re.compile(r"(?<!\d)01[016789][ -]?\d{3,4}[ -]?\d{4}(?!\d)"),
    "resident_number": re.compile(r"(?<!\d)\d{6}[ -]?[1-4]\d{6}(?!\d)"),
}


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding=encoding)
    temporary.replace(path)


def resource_string(apk: APK, name: str) -> str:
    resources = apk.get_android_resources()
    value = resources.get_string(apk.get_package(), name)
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        value = value[1]
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"APK 리소스에서 {name} 값을 찾지 못했습니다.")
    return value


def read_firebase_config(apk_path: Path) -> tuple[str, str]:
    if not apk_path.is_file():
        raise FileNotFoundError(f"APK 파일이 없습니다: {apk_path}")
    # Androguard의 상세 분석 로그에는 필요한 정보가 없고 출력만 과도하므로 끕니다.
    logger.remove()
    apk = APK(str(apk_path))
    return resource_string(apk, "project_id"), resource_string(apk, "google_api_key")


def fetch_documents(
    project_id: str,
    api_key: str,
    collection: str,
    *,
    page_size: int = PAGE_SIZE,
) -> list[dict[str, Any]]:
    url = (
        "https://firestore.googleapis.com/v1/projects/"
        f"{project_id}/databases/(default)/documents/{collection}"
    )
    headers = {"x-goog-api-key": api_key}
    documents: list[dict[str, Any]] = []
    page_token = ""
    page = 0
    with httpx.Client(timeout=60, follow_redirects=False) as client:
        while True:
            params: dict[str, Any] = {
                "pageSize": min(max(page_size, 1), PAGE_SIZE),
                "orderBy": "__name__",
                "showMissing": "false",
            }
            if page_token:
                params["pageToken"] = page_token
            response = client.get(url, params=params, headers=headers)
            if response.status_code != 200:
                # 응답 본문이나 요청 헤더를 출력하지 않아 키와 서버 내부 정보 노출을 막습니다.
                raise RuntimeError(f"Firestore 목록 요청 실패: HTTP {response.status_code}")
            payload = response.json()
            page_documents = payload.get("documents", [])
            if not isinstance(page_documents, list):
                raise RuntimeError("Firestore 응답의 documents 형식이 올바르지 않습니다.")
            documents.extend(page_documents)
            page += 1
            print(f"{page}페이지 · 누적 {len(documents)}개", file=sys.stderr)
            page_token = payload.get("nextPageToken", "")
            if not page_token:
                break
    return documents


def decode_value(value: dict[str, Any]) -> Any:
    if "nullValue" in value:
        return None
    if "booleanValue" in value:
        return bool(value["booleanValue"])
    if "integerValue" in value:
        return int(value["integerValue"])
    if "doubleValue" in value:
        return float(value["doubleValue"])
    if "timestampValue" in value:
        return value["timestampValue"]
    if "stringValue" in value:
        return value["stringValue"]
    if "bytesValue" in value:
        return {"base64": value["bytesValue"]}
    if "referenceValue" in value:
        return value["referenceValue"]
    if "geoPointValue" in value:
        return dict(value["geoPointValue"])
    if "arrayValue" in value:
        return [decode_value(item) for item in value["arrayValue"].get("values", [])]
    if "mapValue" in value:
        return {key: decode_value(item) for key, item in value["mapValue"].get("fields", {}).items()}
    raise ValueError(f"지원하지 않는 Firestore 값 형식: {sorted(value)}")


def decode_document(document: dict[str, Any]) -> dict[str, Any]:
    document_path = str(document.get("name", ""))
    return {
        "document_id": document_path.rsplit("/", 1)[-1],
        "document_path": document_path,
        "create_time": document.get("createTime", ""),
        "update_time": document.get("updateTime", ""),
        "fields": {
            key: decode_value(value)
            for key, value in document.get("fields", {}).items()
        },
    }


def normalized_text(value: Any) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", str(value or "").lower())


def price_to_integer(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    return int(digits) if digits else 0


def public_product(document: dict[str, Any], source_order: int) -> dict[str, Any]:
    original = document["fields"]
    # 원본 필드는 같은 이름과 값으로 보존하고 app_* 필드에도 손실 없이 복사합니다.
    # 검색·표시용 파생값은 다른 이름을 사용해 원본을 덮어쓰지 않습니다.
    item: dict[str, Any] = {
        "document_id": document["document_id"],
        "document_create_time": document["create_time"],
        "document_update_time": document["update_time"],
        **original,
        **{f"app_{key}": value for key, value in original.items()},
    }
    item.update(
        {
            "specification": original.get("capacity", ""),
            "displayed_price_krw": price_to_integer(original.get("price")),
            "normalized_name": normalized_text(original.get("name")),
            "normalized_capacity": normalized_text(original.get("capacity")),
            "source_order": source_order,
            "source_type": "공개 Firestore products 컬렉션",
            "recorded_at": "2026-07-15",
            "price_status": "2026-07-15 조회 당시 앱 데이터값",
            "verification_status": "Firestore 원본 확인",
            "image_url": "",
            "image_source_url": "",
            "image_rights_status": "미확인",
        }
    )
    return item


def values_as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def audit_pii(documents: list[dict[str, Any]]) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    for document in documents:
        for field, value in document["fields"].items():
            text = values_as_text(value)
            for pattern_name, pattern in PII_PATTERNS.items():
                if pattern.search(text):
                    findings.append(
                        {
                            "document_id": document["document_id"],
                            "field": field,
                            "pattern": pattern_name,
                        }
                    )
            if any(pattern in text for pattern in NOTIFICATION_PATTERNS):
                findings.append(
                    {
                        "document_id": document["document_id"],
                        "field": field,
                        "pattern": "notification_text",
                    }
                )
    return {
        "finding_count": len(findings),
        "findings": findings,
        "matched_values_not_logged": True,
    }


def write_csv(path: Path, products: list[dict[str, Any]]) -> None:
    columns = [
        "document_id",
        *EXPECTED_FIELDS,
        *(f"app_{field}" for field in EXPECTED_FIELDS),
        "document_create_time",
        "document_update_time",
        "specification",
        "displayed_price_krw",
        "normalized_name",
        "normalized_capacity",
        "source_order",
        "source_type",
        "recorded_at",
        "price_status",
        "verification_status",
        "image_url",
        "image_source_url",
        "image_rights_status",
    ]
    extra = sorted({key for product in products for key in product} - set(columns))
    columns.extend(extra)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for product in products:
            writer.writerow({key: values_as_text(value) for key, value in product.items()})
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="APK의 Firebase 설정을 실행 중에 읽어 공개 products 컬렉션을 추출합니다."
    )
    parser.add_argument("--apk", type=Path, default=DEFAULT_APK)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--expected", type=int, default=776)
    parser.add_argument("--canonical-output", type=Path, default=Path("data/firestore-products.json"))
    parser.add_argument("--output", type=Path, default=Path("data/products.json"))
    parser.add_argument("--public-output", type=Path, default=Path("public/data/products.json"))
    parser.add_argument("--csv-output", type=Path, default=Path("data/catalog.csv"))
    parser.add_argument("--public-csv-output", type=Path, default=Path("public/data/catalog.csv"))
    parser.add_argument("--report", type=Path, default=Path("data/firestore-extraction-report.json"))
    parser.add_argument("--quality-report", type=Path, default=Path("data/quality-report.json"))
    parser.add_argument("--manifest", type=Path, default=Path("data/source-manifest.json"))
    args = parser.parse_args()

    project_id, api_key = read_firebase_config(args.apk)
    raw_documents = fetch_documents(project_id, api_key, args.collection)
    decoded_documents = [decode_document(document) for document in raw_documents]
    decoded_documents.sort(key=lambda item: item["document_id"])

    document_ids = [item["document_id"] for item in decoded_documents]
    duplicated_ids = sorted(item for item, count in Counter(document_ids).items() if count > 1)
    field_counts = Counter(key for document in decoded_documents for key in document["fields"])
    missing_expected = {
        field: sum(field not in document["fields"] for document in decoded_documents)
        for field in EXPECTED_FIELDS
    }
    pii_audit = audit_pii(decoded_documents)
    extracted_at = datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")
    raw_prices = [document["fields"].get("price") for document in decoded_documents]
    parsed_prices = [price_to_integer(value) for value in raw_prices]
    price_missing_count = sum(value in (None, "") for value in raw_prices)
    price_zero_count = sum(value == 0 for value in parsed_prices)
    price_parse_failure_count = sum(
        value not in (None, "") and parsed == 0
        for value, parsed in zip(raw_prices, parsed_prices)
    )
    categories = Counter(str(document["fields"].get("category") or "미분류") for document in decoded_documents)
    source_type = "공개 Firestore products 컬렉션"
    apk_sha256 = hashlib.sha256(args.apk.read_bytes()).hexdigest().upper()
    source_apk = {
        "package": SOURCE_PACKAGE,
        "app_version": SOURCE_APP_VERSION,
        "version_code": SOURCE_VERSION_CODE,
        "sha256": apk_sha256,
        "acquisition_url": SOURCE_URL,
        "binary_published": False,
    }
    report = {
        "extracted_at": extracted_at,
        "source_type": source_type,
        "expected_count": args.expected,
        "document_count": len(decoded_documents),
        "count_matches_expected": len(decoded_documents) == args.expected,
        "unique_document_id_count": len(set(document_ids)),
        "duplicated_document_ids": duplicated_ids,
        "original_fields": list(EXPECTED_FIELDS),
        "field_presence_counts": dict(sorted(field_counts.items())),
        "missing_expected_field_counts": missing_expected,
        "price_missing_count": price_missing_count,
        "price_zero_count": price_zero_count,
        "price_parse_failure_count": price_parse_failure_count,
        "price_min_krw": min(parsed_prices, default=0),
        "price_median_krw": int(statistics.median(parsed_prices)) if parsed_prices else 0,
        "price_max_krw": max(parsed_prices, default=0),
        "categories": dict(sorted(categories.items(), key=lambda pair: (-pair[1], pair[0]))),
        "pii_audit": pii_audit,
        "api_key_saved": False,
        "source_apk": source_apk,
        "source": "실행 시점에 인증 설정을 메모리에서만 사용해 조회한 공개 Firestore products 컬렉션",
    }
    manifest = {
        "extracted_at": extracted_at,
        "source_type": source_type,
        "collection": args.collection,
        "source_apk": source_apk,
        "document_count": len(decoded_documents),
        "unique_document_id_count": len(set(document_ids)),
        "original_fields": list(EXPECTED_FIELDS),
        "original_fields_preserved": True,
        "price_fields": {
            "original": "price",
            "derived": "displayed_price_krw",
            "original_value_preserved": True,
        },
        "generated_files": [
            str(args.canonical_output).replace("\\", "/"),
            str(args.output).replace("\\", "/"),
            str(args.public_output).replace("\\", "/"),
            str(args.csv_output).replace("\\", "/"),
            str(args.public_csv_output).replace("\\", "/"),
        ],
        "api_key_saved": False,
        "app_storage_images_copied": False,
    }

    # 원본 타입과 값을 보존하는 로컬 정본입니다. API 키는 포함하지 않습니다.
    canonical = {
        "collection": args.collection,
        "document_count": len(decoded_documents),
        "documents": [
            {
                **document,
                "firestore_typed_fields": raw_document.get("fields", {}),
            }
            for document, raw_document in zip(decoded_documents, sorted(raw_documents, key=lambda item: item["name"]))
        ],
    }
    atomic_write_text(args.canonical_output, json.dumps(canonical, ensure_ascii=False, indent=2))
    atomic_write_text(args.report, json.dumps(report, ensure_ascii=False, indent=2))
    atomic_write_text(args.quality_report, json.dumps(report, ensure_ascii=False, indent=2))
    atomic_write_text(args.manifest, json.dumps(manifest, ensure_ascii=False, indent=2))

    if duplicated_ids:
        raise RuntimeError(f"중복 document id가 {len(duplicated_ids)}개 있습니다. 공개 파일을 만들지 않았습니다.")
    if pii_audit["finding_count"]:
        raise RuntimeError(
            f"개인정보 가능 항목이 {pii_audit['finding_count']}개 있습니다. "
            "로컬 정본과 검사 보고서만 만들었습니다."
        )

    products = [public_product(document, index) for index, document in enumerate(decoded_documents, start=1)]
    product_json = json.dumps(products, ensure_ascii=False, indent=2)
    atomic_write_text(args.output, product_json)
    atomic_write_text(args.public_output, product_json)
    write_csv(args.csv_output, products)
    write_csv(args.public_csv_output, products)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError, ValueError, httpx.HTTPError) as error:
        print(f"오류: {error}", file=sys.stderr)
        raise SystemExit(1)
