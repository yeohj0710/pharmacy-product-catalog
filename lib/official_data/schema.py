from __future__ import annotations

from datetime import datetime
from typing import Any


MATCH_STATUSES = {
    "pending",
    "confirmed",
    "review_required",
    "not_found",
    "not_applicable",
    "blocked_missing_key",
    "error",
}
IMAGE_KINDS = {"package", "pill", "label", "instruction"}
OPEN_DATA_LICENSE = "공공데이터포털 이용허락범위 제한 없음"


def utc_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def make_official_record(
    *,
    source_domain: str,
    source_dataset_id: str,
    source_record_id: str,
    item_name: str,
) -> dict[str, Any]:
    if not all((source_domain, source_dataset_id, source_record_id, item_name)):
        raise ValueError("공식 제품 레코드에는 도메인, 데이터셋, 레코드 ID, 제품명이 필요합니다.")
    return {
        "official_product_key": f"{source_domain}:{source_record_id}",
        "source_domain": source_domain,
        "item_name": item_name,
        "manufacturer": "",
        "identifiers": {
            "item_seq": source_record_id,
            "barcode": "",
            "standard_codes": [],
            "report_number": "",
            "udi_di": "",
        },
        "classification": {
            "category": "",
            "dosage_form": "",
            "route": "",
            "atc_code": "",
            "professional_or_general": "",
        },
        "content": {
            "appearance": "",
            "pack_unit": "",
            "storage": "",
            "valid_term": "",
            "efficacy": "",
            "dosage": "",
            "precautions": "",
            "professional_precautions": "",
            "ingredients": [],
            "active_ingredients": [],
            "consumer_guidance": {},
        },
        "content_raw": {
            "efficacy": "",
            "dosage": "",
            "precautions": "",
            "professional_precautions": "",
        },
        "images": [],
        "provenance": {
            "source_dataset_id": source_dataset_id,
            "source_record_id": source_record_id,
            "source_url": "",
            "license": OPEN_DATA_LICENSE,
            "fetched_at": "",
            "upstream_updated_at": "",
            "raw_sha256": "",
        },
        "field_provenance": {},
    }


def make_match_record(
    *,
    catalog_product_id: str,
    official_product_key: str,
    score: int,
    status: str,
    score_components: dict[str, int] | None = None,
    alternatives: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if status not in MATCH_STATUSES:
        raise ValueError(f"알 수 없는 매칭 상태: {status}")
    return {
        "catalog_product_id": catalog_product_id,
        "official_product_key": official_product_key,
        "score": int(score),
        "status": status,
        "score_components": score_components or {},
        "matched_fields": [],
        "alternatives": alternatives or [],
        "decision_source": "automatic" if status == "confirmed" else "pending_review",
        "reviewer": "",
        "reviewed_at": "",
        "notes": "",
        "updated_at": utc_now(),
    }


def make_image(
    *,
    url: str,
    kind: str,
    source_url: str,
    source_dataset_id: str,
    fetched_at: str,
) -> dict[str, str]:
    if kind not in IMAGE_KINDS:
        raise ValueError(f"알 수 없는 이미지 종류: {kind}")
    if not url.startswith("https://") or not source_url.startswith("https://"):
        raise ValueError("이미지 URL과 출처 URL은 HTTPS여야 합니다.")
    return {
        "url": url,
        "kind": kind,
        "source_url": source_url,
        "source_dataset_id": source_dataset_id,
        "license": OPEN_DATA_LICENSE,
        "fetched_at": fetched_at,
        "sha256": "",
        "mime_type": "",
        "local_path": "",
    }


def validate_official_record(record: dict[str, Any]) -> None:
    for key in ("official_product_key", "source_domain", "item_name", "identifiers", "content", "provenance"):
        if key not in record:
            raise ValueError(f"공식 제품 레코드 필드 누락: {key}")
    if not record["official_product_key"].startswith(f"{record['source_domain']}:"):
        raise ValueError("공식 제품 키와 도메인이 일치하지 않습니다.")
    for image in record.get("images", []):
        if not image.get("source_url") or not image.get("license"):
            raise ValueError("이미지에는 출처 URL과 이용허락 정보가 필요합니다.")
