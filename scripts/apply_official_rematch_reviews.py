from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.apply_catalog_text_corrections import atomic_write_text, read_array, write_csv
from scripts.health_enrichment import (
    DEFAULT_CACHE,
    STATUS_TO_ENRICHMENT,
    HealthKrClient,
    build_confirmed_record,
    score_candidate,
)
from scripts.refresh_corrected_official_matches import merge_refresh_result


ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "etc" / "image-research"
REVIEW_FILES = (
    RESEARCH / "official-rematch-review-001-200.json",
    RESEARCH / "official-rematch-review-201-400.json",
    RESEARCH / "official-rematch-review-401-600.json",
    RESEARCH / "official-rematch-review-601-776.json",
)
DECISION_STATUS = {
    "confirmed": "confirmed",
    "not_applicable": "not_applicable",
    "not_found": "not_found",
    "review_required": "review_required",
    "rejected": "review_required",
}


def load_reviews(paths: tuple[Path, ...]) -> list[dict[str, Any]]:
    reviews: list[dict[str, Any]] = []
    for path in paths:
        reviews.extend(read_array(path))
    return reviews


def validate_coverage(
    baseline: list[dict[str, Any]], reviews: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    expected = {
        str(row.get("document_id") or "")
        for row in baseline
        if row.get("official_match_status") != "confirmed"
    }
    by_id: dict[str, dict[str, Any]] = {}
    for review in reviews:
        document_id = str(review.get("document_id") or "")
        decision = str(review.get("decision") or "")
        if not document_id or document_id in by_id:
            raise ValueError(f"검수 document_id가 비었거나 중복됩니다: {document_id!r}")
        if decision not in DECISION_STATUS:
            raise ValueError(f"알 수 없는 검수 결정입니다: {document_id} {decision!r}")
        if not str(review.get("evidence") or "").strip() or not str(
            review.get("rationale") or ""
        ).strip():
            raise ValueError(f"검수 근거가 비었습니다: {document_id}")
        if decision == "confirmed":
            code = str(review.get("official_item_seq") or "")
            source_url = str(review.get("official_source_url") or "")
            if not code or code not in source_url or "health.kr" not in source_url:
                raise ValueError(f"확정 검수의 약학정보원 코드·링크가 잘못됐습니다: {document_id}")
        by_id[document_id] = review
    missing = sorted(expected - set(by_id))
    extra = sorted(set(by_id) - expected)
    if missing or extra:
        raise ValueError(f"검수 범위가 정확하지 않습니다: missing={missing}, extra={extra}")
    return by_id


def build_manual_confirmation(
    client: HealthKrClient,
    current: dict[str, Any],
    review: dict[str, Any],
) -> dict[str, Any]:
    code = str(review["official_item_seq"])
    detail = client.detail(code)
    if not detail:
        raise ValueError(f"약학정보원 상세 원문을 가져오지 못했습니다: {code}")
    official_name = str(detail.get("drug_name") or "")
    reviewed_name = str(review.get("official_item_name") or "")
    if official_name.replace(" ", "") != reviewed_name.replace(" ", ""):
        raise ValueError(
            f"검수 제품명과 약학정보원 원문이 다릅니다: {code} "
            f"({reviewed_name!r} != {official_name!r})"
        )
    candidate = {
        "drug_code": code,
        "drug_name": official_name,
        "drug_form": detail.get("drug_form", ""),
        "upso_name_kfda": str(detail.get("upso_name") or "").split("|")[0],
    }
    score, reasons, conflicts = score_candidate(current, candidate, code, detail)
    reasons.append("미확정 상품 개별 검수 승인")
    reasons.append(str(review.get("rationale") or ""))
    refreshed = build_confirmed_record(
        current,
        candidate,
        detail,
        max(95, score),
        list(dict.fromkeys(reasons)),
        conflicts,
        client,
        include_aux=True,
    )
    return merge_refresh_result(current, refreshed)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="구간별 약학정보원 개별 검수 결과를 작업 JSON에 검증·병합합니다."
    )
    parser.add_argument(
        "--baseline", type=Path, default=ROOT / "data" / "enrichment-queue.json"
    )
    parser.add_argument(
        "--input", type=Path, default=RESEARCH / "unmatched-rematch-working.json"
    )
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "enrichment-queue.json")
    parser.add_argument("--csv", type=Path, default=ROOT / "data" / "enrichment-queue.csv")
    parser.add_argument(
        "--public-json", type=Path, default=ROOT / "public/data/enrichment-queue.json"
    )
    parser.add_argument(
        "--public-csv", type=Path, default=ROOT / "public/data/enrichment-queue.csv"
    )
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--report",
        type=Path,
        default=RESEARCH / "official-rematch-reviewed-merge-report.json",
    )
    args = parser.parse_args()

    baseline = read_array(args.baseline)
    products = read_array(args.input)
    reviews = load_reviews(REVIEW_FILES)
    reviews_by_id = validate_coverage(baseline, reviews)
    products_by_id = {str(row.get("document_id") or ""): row for row in products}
    if set(products_by_id) != {str(row.get("document_id") or "") for row in baseline}:
        raise ValueError("작업 JSON과 정식 기준 JSON의 상품 ID가 다릅니다.")

    disagreements: list[dict[str, Any]] = []
    manual_confirmations: list[str] = []
    for document_id, review in reviews_by_id.items():
        current = products_by_id[document_id]
        manual_confirmed = review["decision"] == "confirmed"
        automatic_confirmed = current.get("official_match_status") == "confirmed"
        same_code = str(current.get("official_item_seq") or "") == str(
            review.get("official_item_seq") or ""
        )
        if automatic_confirmed and (not manual_confirmed or not same_code):
            disagreements.append(
                {
                    "document_id": document_id,
                    "source_order": current.get("source_order"),
                    "automatic_status": current.get("official_match_status"),
                    "automatic_code": current.get("official_item_seq", ""),
                    "manual_decision": review.get("decision"),
                    "manual_code": review.get("official_item_seq", ""),
                }
            )
        elif manual_confirmed and not automatic_confirmed:
            manual_confirmations.append(document_id)
    if disagreements:
        raise ValueError(f"자동 결과와 개별 검수가 충돌합니다: {disagreements}")

    if args.check:
        print(
            json.dumps(
                {
                    "reviewed_count": len(reviews),
                    "manual_confirmation_count": len(manual_confirmations),
                    "decision_counts": dict(Counter(row["decision"] for row in reviews)),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    client = HealthKrClient(args.cache_dir, min_interval=0.05)
    for document_id, review in reviews_by_id.items():
        current = products_by_id[document_id]
        decision = str(review["decision"])
        if decision == "confirmed":
            if current.get("official_match_status") != "confirmed":
                products_by_id[document_id] = build_manual_confirmation(
                    client, current, review
                )
        else:
            status = DECISION_STATUS[decision]
            current["official_match_status"] = status
            if not current.get("image_url"):
                current["enrichment_status"] = STATUS_TO_ENRICHMENT[status]

    merged = [products_by_id[str(row["document_id"])] for row in products]
    payload = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    atomic_write_text(args.output, payload)
    atomic_write_text(args.public_json, payload)
    write_csv(args.csv, merged)
    write_csv(args.public_csv, merged)

    report = {
        "reviewed_count": len(reviews),
        "manual_confirmation_count": len(manual_confirmations),
        "decision_counts": dict(sorted(Counter(row["decision"] for row in reviews).items())),
        "final_status_counts": dict(
            sorted(Counter(str(row.get("official_match_status") or "") for row in merged).items())
        ),
        "manual_confirmation_ids": manual_confirmations,
        "disagreements": disagreements,
    }
    atomic_write_text(args.report, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
