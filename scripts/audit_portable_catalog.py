from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "portable" / "v1" / "products.json"
DEFAULT_REPORT = ROOT / "data" / "portable-catalog-audit.json"
DEFAULT_QUEUE_JSON = ROOT / "data" / "official-data-gap-queue.json"
DEFAULT_QUEUE_CSV = ROOT / "data" / "official-data-gap-queue.csv"

KST = timezone(timedelta(hours=9))

TEXT_PATTERNS = {
    "replacement_character": re.compile("\N{REPLACEMENT CHARACTER}"),
    "zero_width_character": re.compile("[\u200b-\u200f\u2060\ufeff]"),
    "control_character": re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]"),
    "residual_html": re.compile(r"</?[A-Za-z][^>]*>"),
    "html_entity": re.compile(r"&(?:nbsp|amp|lt|gt|quot|#\d+|#x[0-9a-fA-F]+);"),
    "literal_br": re.compile(
        r"(?i)(?:^\s*br\s*$|(?<=[가-힣0-9.!?\]\)])br(?=\s*(?:\n|$)))",
        re.MULTILINE,
    ),
    "literal_null": re.compile(r"\b(?:undefined|null|nan)\b", re.IGNORECASE),
}

SEARCH_PROXY_IMAGE_PATTERN = re.compile(
    r"(?:encrypted-tbn|gstatic\.com|googleusercontent|mm\.bing\.net|"
    r"thumbnail\.coupangcdn\.com|search\.pstatic\.net)",
    re.IGNORECASE,
)

# Suffixes that describe pack size or count, not product identity.
_SIZE_TOKEN = re.compile(
    r"\d+(?:\.\d+)?\s*(?:mg|g|kg|ml|l|iu|정|캡슐|포|병|매|개|환|앰플|스틱|캅셀)",
    re.IGNORECASE,
)


def normalize_identity_name(name: str) -> str:
    """Collapse a display name to an identity key that ignores spacing and pack sizes."""
    value = unicodedata.normalize("NFC", str(name))
    value = _SIZE_TOKEN.sub("", value)
    value = re.sub(r"[\s()\[\]×xX*·,./-]+", "", value)
    return value.lower()


def walk_strings(value: Any, path: str = ""):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from walk_strings(item, f"{path}[{index}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower().endswith(("url", "urls")):
                continue
            yield from walk_strings(item, f"{path}.{key}" if path else str(key))


def audit_text(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for product in products:
        product_id = product.get("product_id", "")
        for path, text in walk_strings(product):
            for code, pattern in TEXT_PATTERNS.items():
                if pattern.search(text):
                    findings.append(
                        {
                            "product_id": product_id,
                            "field": path,
                            "code": code,
                            "sample": text[:160],
                        }
                    )
    return findings


def primary_image(product: dict[str, Any]) -> dict[str, Any] | None:
    image = (product.get("media") or {}).get("primary_image")
    if image and image.get("url"):
        return image
    return None


def audit_images(products: list[dict[str, Any]]) -> dict[str, Any]:
    missing: list[dict[str, Any]] = []
    by_url: dict[str, list[dict[str, Any]]] = defaultdict(list)
    proxy_findings: list[dict[str, Any]] = []
    host_counter: Counter[str] = Counter()

    for product in products:
        image = primary_image(product)
        if image is None:
            missing.append(
                {
                    "product_id": product.get("product_id", ""),
                    "name": (product.get("display") or {}).get("name"),
                    "category": (product.get("display") or {}).get("category"),
                    "official_match_status": (product.get("quality") or {}).get(
                        "official_match_status"
                    ),
                }
            )
            continue
        url = image["url"]
        by_url[url].append(product)
        host_counter[urlparse(url).netloc] += 1
        if SEARCH_PROXY_IMAGE_PATTERN.search(url):
            proxy_findings.append(
                {
                    "product_id": product.get("product_id", ""),
                    "name": (product.get("display") or {}).get("name"),
                    "url": url,
                    "code": "search_or_thumbnail_proxy_host",
                }
            )

    shared_url_groups: list[dict[str, Any]] = []
    for url, group in sorted(by_url.items()):
        if len(group) < 2:
            continue
        identity_names = {
            normalize_identity_name((item.get("display") or {}).get("name", ""))
            for item in group
        }
        shared_url_groups.append(
            {
                "url": url,
                "product_ids": [item.get("product_id", "") for item in group],
                "names": [(item.get("display") or {}).get("name") for item in group],
                "distinct_identity_names": len(identity_names),
                "cross_identity": len(identity_names) > 1,
            }
        )

    return {
        "missing": missing,
        "shared_url_groups": shared_url_groups,
        "search_proxy_findings": proxy_findings,
        "host_counts": dict(host_counter.most_common()),
    }


def audit_official(products: list[dict[str, Any]]) -> dict[str, Any]:
    status_counter: Counter[str] = Counter()
    confirmed_missing_fields: list[dict[str, Any]] = []
    code_map: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for product in products:
        quality = product.get("quality") or {}
        status = quality.get("official_match_status") or "missing_status"
        status_counter[status] += 1
        medicine = product.get("medicine")
        if status == "confirmed":
            missing: list[str] = []
            identity = (medicine or {}).get("identity") or {}
            content = (medicine or {}).get("content") or {}
            source = (medicine or {}).get("source") or {}
            if medicine is None:
                missing.append("medicine")
            for key in ("item_name", "item_code", "manufacturer"):
                if not identity.get(key):
                    missing.append(f"identity.{key}")
            if not source.get("url"):
                missing.append("source.url")
            for section in ("efficacy", "dosage", "precautions"):
                section_value = content.get(section) or {}
                if not str(section_value.get("text") or "").strip():
                    missing.append(f"content.{section}")
            if missing:
                confirmed_missing_fields.append(
                    {
                        "product_id": product.get("product_id", ""),
                        "name": (product.get("display") or {}).get("name"),
                        "missing": missing,
                    }
                )
            item_code = identity.get("item_code")
            if item_code:
                code_map[str(item_code)].append(product)

    shared_codes_cross_identity: list[dict[str, Any]] = []
    for item_code, group in sorted(code_map.items()):
        if len(group) < 2:
            continue
        identity_names = {
            normalize_identity_name((item.get("display") or {}).get("name", ""))
            for item in group
        }
        if len(identity_names) > 1:
            shared_codes_cross_identity.append(
                {
                    "item_code": item_code,
                    "product_ids": [item.get("product_id", "") for item in group],
                    "names": [(item.get("display") or {}).get("name") for item in group],
                }
            )

    return {
        "status_counts": dict(status_counter),
        "confirmed_missing_fields": confirmed_missing_fields,
        "shared_item_codes_cross_identity": shared_codes_cross_identity,
    }


QUEUE_REASON_PRIORITY = {
    "official_match_unresolved": 1,
    "shared_item_code_identity_conflict": 2,
    "image_missing": 3,
    "image_search_proxy_source": 4,
    "shared_image_cross_identity": 5,
    "non_medicine_official_source_pending": 6,
}


def build_gap_queue(
    products: list[dict[str, Any]],
    image_audit: dict[str, Any],
    official_audit: dict[str, Any],
) -> list[dict[str, Any]]:
    reasons: dict[str, list[str]] = defaultdict(list)

    for product in products:
        product_id = product.get("product_id", "")
        status = (product.get("quality") or {}).get("official_match_status")
        if status in ("review_required", "not_found"):
            reasons[product_id].append("official_match_unresolved")
        elif status == "not_applicable":
            reasons[product_id].append("non_medicine_official_source_pending")
        if primary_image(product) is None:
            reasons[product_id].append("image_missing")

    for finding in image_audit["search_proxy_findings"]:
        reasons[finding["product_id"]].append("image_search_proxy_source")
    for group in image_audit["shared_url_groups"]:
        if group["cross_identity"]:
            for product_id in group["product_ids"]:
                reasons[product_id].append("shared_image_cross_identity")
    for group in official_audit["shared_item_codes_cross_identity"]:
        for product_id in group["product_ids"]:
            reasons[product_id].append("shared_item_code_identity_conflict")

    by_id = {product.get("product_id", ""): product for product in products}
    queue: list[dict[str, Any]] = []
    for product_id, reason_list in reasons.items():
        product = by_id.get(product_id)
        if product is None:
            continue
        display = product.get("display") or {}
        quality = product.get("quality") or {}
        image = primary_image(product)
        unique_reasons = sorted(set(reason_list), key=lambda r: QUEUE_REASON_PRIORITY[r])
        queue.append(
            {
                "product_id": product_id,
                "name": display.get("name"),
                "specification": display.get("specification"),
                "category": display.get("category"),
                "official_match_status": quality.get("official_match_status"),
                "image_url": image["url"] if image else None,
                "image_rights_status": quality.get("image_rights_status"),
                "queue_reasons": unique_reasons,
                "priority": min(QUEUE_REASON_PRIORITY[r] for r in unique_reasons),
                "source_order": display.get("source_order"),
            }
        )

    queue.sort(key=lambda row: (row["priority"], row["source_order"] or 0))
    return queue


def run_audit(products: list[dict[str, Any]], generated_at: str) -> dict[str, Any]:
    text_findings = audit_text(products)
    image_audit = audit_images(products)
    official_audit = audit_official(products)
    queue = build_gap_queue(products, image_audit, official_audit)

    reason_counter: Counter[str] = Counter()
    for row in queue:
        for reason in row["queue_reasons"]:
            reason_counter[reason] += 1

    report = {
        "generated_at": generated_at,
        "input": "data/portable/v1/products.json",
        "product_count": len(products),
        "summary": {
            "text_finding_count": len(text_findings),
            "image_missing_count": len(image_audit["missing"]),
            "image_search_proxy_count": len(image_audit["search_proxy_findings"]),
            "shared_image_cross_identity_group_count": sum(
                1 for g in image_audit["shared_url_groups"] if g["cross_identity"]
            ),
            "official_status_counts": official_audit["status_counts"],
            "confirmed_missing_field_count": len(
                official_audit["confirmed_missing_fields"]
            ),
            "shared_item_code_cross_identity_group_count": len(
                official_audit["shared_item_codes_cross_identity"]
            ),
            "gap_queue_row_count": len(queue),
            "gap_queue_reason_counts": dict(reason_counter),
        },
        "text_findings": text_findings,
        "image_audit": image_audit,
        "official_audit": official_audit,
    }
    return report, queue


QUEUE_CSV_COLUMNS = [
    "product_id",
    "name",
    "specification",
    "category",
    "official_match_status",
    "image_url",
    "image_rights_status",
    "queue_reasons",
    "priority",
    "source_order",
]


def write_queue_csv(queue: list[dict[str, Any]], path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=QUEUE_CSV_COLUMNS)
        writer.writeheader()
        for row in queue:
            csv_row = dict(row)
            csv_row["queue_reasons"] = ";".join(row["queue_reasons"])
            writer.writerow(csv_row)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Offline audit of the committed portable v1 catalog."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--queue-json", type=Path, default=DEFAULT_QUEUE_JSON)
    parser.add_argument("--queue-csv", type=Path, default=DEFAULT_QUEUE_CSV)
    args = parser.parse_args()

    products = json.loads(args.input.read_text(encoding="utf-8"))
    generated_at = datetime.now(KST).isoformat(timespec="seconds")
    report, queue = run_audit(products, generated_at)

    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    queue_document = {
        "generated_at": generated_at,
        "input": "data/portable/v1/products.json",
        "row_count": len(queue),
        "reason_counts": report["summary"]["gap_queue_reason_counts"],
        "rows": queue,
    }
    args.queue_json.write_text(
        json.dumps(queue_document, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    write_queue_csv(queue, args.queue_csv)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
