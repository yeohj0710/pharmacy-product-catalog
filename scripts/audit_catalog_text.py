from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "enrichment-queue.json"
DEFAULT_REPORT = ROOT / "etc" / "text-normalization" / "catalog-text-audit.json"

EXCLUDED_ROOT_FIELDS = {
    "official_additional_data",
    "app_id",
    "app_name",
    "app_capacity",
    "app_category",
    "app_price",
    "app_etc",
    "app_updated",
}

PATTERNS = {
    "literal_br": re.compile(
        r"(?i)(?:^\s*br\s*$|(?<=[가-힣0-9.!?\]\)])br(?=\s*(?:\n|$)))",
        re.MULTILINE,
    ),
    "residual_html": re.compile(r"</?[A-Za-z][^>]*>"),
    "replacement_character": re.compile("\ufffd"),
    "zero_width_character": re.compile(r"[\u200b-\u200f\u2060\ufeff]"),
    "malformed_numeric_range": re.compile(
        r"(?:\d\s*\?\s*\d|\[\d+\s*\?\s*[가-힣A-Za-z])"
    ),
    "literal_null": re.compile(r"\b(?:undefined|null|nan)\b", re.IGNORECASE),
}


def walk_strings(value: Any, path: str):
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


def audit_products(products: list[dict[str, Any]]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    product_results: list[dict[str, Any]] = []

    for product in products:
        document_id = str(product.get("document_id") or product.get("id") or "")
        name = str(product.get("name") or "")
        product_findings: list[dict[str, Any]] = []

        if not document_id or document_id in seen_ids:
            product_findings.append(
                {"kind": "missing_or_duplicate_product_id", "field": "document_id", "sample": document_id}
            )
        seen_ids.add(document_id)

        for field, value in product.items():
            if field in EXCLUDED_ROOT_FIELDS or field.lower().endswith(("url", "urls")):
                continue
            for path, text in walk_strings(value, field):
                for kind, pattern in PATTERNS.items():
                    match = pattern.search(text)
                    if match:
                        product_findings.append(
                            {
                                "kind": kind,
                                "field": path,
                                "sample": text[max(0, match.start() - 40) : match.end() + 80],
                            }
                        )
                if field in {"official_ingredients", "official_active_ingredients"} and re.search(
                    r"\s/\s*$", text
                ):
                    product_findings.append(
                        {"kind": "trailing_ingredient_separator", "field": path, "sample": text[-100:]}
                    )
                if field == "official_interactions" and re.search(r"(?:^|\n)복사\s*$", text):
                    product_findings.append(
                        {"kind": "copied_ui_label", "field": path, "sample": text[-100:]}
                    )

        if product.get("official_match_status") == "confirmed":
            content = product.get("official_content")
            if not isinstance(content, dict) or content.get("schema_version") != "1.0":
                product_findings.append(
                    {
                        "kind": "missing_structured_content",
                        "field": "official_content",
                        "sample": "",
                    }
                )

        for finding in product_findings:
            findings.append({"document_id": document_id, "name": name, **finding})
        product_results.append(
            {
                "document_id": document_id,
                "name": name,
                "status": "failed" if product_findings else "passed",
                "finding_count": len(product_findings),
            }
        )

    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding["kind"]] = counts.get(finding["kind"], 0) + 1
    return {
        "product_count": len(products),
        "passed_product_count": sum(row["status"] == "passed" for row in product_results),
        "failed_product_count": sum(row["status"] == "failed" for row in product_results),
        "error_count": len(findings),
        "finding_counts": counts,
        "findings": findings,
        "products": product_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="정식 상품 데이터의 공개 텍스트 손상을 전수 검사합니다.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--allow-errors", action="store_true")
    args = parser.parse_args()

    products = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(products, list) or not all(isinstance(row, dict) for row in products):
        raise SystemExit("입력 파일은 상품 객체의 JSON 배열이어야 합니다.")
    report = {"generated_at": datetime.now().astimezone().isoformat(), **audit_products(products)}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.report.with_suffix(args.report.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.report)
    print(
        json.dumps(
            {key: value for key, value in report.items() if key not in {"findings", "products"}},
            ensure_ascii=False,
        )
    )
    if report["product_count"] != 776:
        raise SystemExit(f"상품 수가 776개가 아닙니다: {report['product_count']}")
    if report["error_count"] and not args.allow_errors:
        raise SystemExit(f"공개 텍스트 오류가 {report['error_count']}건 남아 있습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
