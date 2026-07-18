from __future__ import annotations

import json
import hashlib
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REVIEW_FILES = (
    ROOT / "etc/image-research/unmatched-text-review-001-163.json",
    ROOT / "etc/image-research/unmatched-text-review-164-427.json",
    ROOT / "etc/image-research/unmatched-text-review-428-595.json",
    ROOT / "etc/image-research/unmatched-text-review-596-776.json",
)
OUTPUT = ROOT / "data/catalog-text-corrections.json"
REPORT = ROOT / "etc/image-research/unmatched-text-review-summary.json"
EXPECTED_REVIEW_COHORT_COUNT = 407
EXPECTED_APPROVED_CORRECTION_COUNT = 252
EXPECTED_REVIEW_FILE_HASHES = {
    "unmatched-text-review-001-163.json": "2c5c4ba054027b9eba8683d70d5041e788b6268890ea878f9b05468f6db7225a",
    "unmatched-text-review-164-427.json": "932ee07a14a4a0f2d826c0ca8cca3c4b3ecd883af0d176fe7a2cf1fa006e6285",
    "unmatched-text-review-428-595.json": "f3af8c844f7c92962ed3f52cbc21c45698b7229d52b23133cd0d4a9cc0be6964",
    "unmatched-text-review-596-776.json": "bf30e99f9ff798590dc9b1ad8e36bad509474c8fbac00cbcc866ef254fd1a2af",
}

# 주 에이전트가 원문을 다시 확인한 결과, 상품·규격을 하나로 확정할 수 없는 제안입니다.
MANUAL_REJECTIONS = {
    466: "50캡슐을 60캡슐로 바꾸는 근거가 포장 옵션 목록뿐이라 실제 판매 구성을 확정할 수 없음",
    470: "훼마틴에이시럽과 훼마틴캡슐이 모두 실재하여 원본 이름과 60캡슐 규격만으로 한 제품을 확정할 수 없음",
}

# 중간 신뢰도 제안 중 주 에이전트가 공식 페이지·실제 상품 페이지를 다시 대조한 항목입니다.
MANUAL_ACCEPTED_MEDIUM = {31, 55, 56, 57, 78, 190, 225, 331, 427, 468, 570}

# 주 에이전트가 약학정보원 원문과 규격을 다시 확인해 추가 승인한 항목입니다.
MANUAL_CORRECTIONS = {
    333: {
        "accepted_previous_names": ["성광포비스틱스왑액"],
        "corrected_name": "성광포스틱스왑액",
        "corrected_capacity": "2매×6개입",
        "confidence": "high",
        "evidence_urls": [
            "https://www.firsonhealthcare.com/sub_products/prod_view.php?block=1&cate=0003_&effi=%EC%99%B8%ED%94%BC%EC%9A%A9%EC%82%B4%EA%B7%A0%EC%86%8C%EB%8F%85%EC%A0%9C&p_idx=25&pg=1",
            "https://health.kr/searchDrug/result_drug.asp?drug_cd=A11AKP07L0538",
            "https://health.kr/searchDrug/result_drug.asp?drug_cd=A11AKP08F1029",
            "https://health.kr/searchDrug/result_drug.asp?drug_cd=h3lj31or61ahr",
            "https://health.kr/searchDrug/result_drug.asp?drug_cd=A11A6030B0011",
            "https://health.kr/searchDrug/result_drug.asp?drug_cd=A11A6030B0003",
            "https://health.kr/searchDrug/result_drug.asp?drug_cd=A11AKP08F1030",
        ],
        "evidence_text": (
            "퍼슨헬스케어 제품 페이지와 약학정보원 원문을 다시 확인했다. 정식 제품명은 "
            "‘성광포스틱스왑액(포비돈요오드)’이고 규격은 2매×6개입이다. 이전 "
            "‘포비스틱’ 교정은 잘못되어 ‘포스틱’으로 바로잡는다."
        ),
        "action": "correct",
    },
    384: {
        "corrected_name": "광동우황청심원현탁액",
        "corrected_capacity": "50mL",
        "confidence": "high",
        "evidence_urls": [
            "https://health.kr/searchDrug/result_drug.asp?drug_cd=A11A2260A0347"
        ],
        "evidence_text": (
            "약학정보원 원문은 광동제약 ‘광동우황청심원현탁액’의 포장단위를 "
            "1병 50mL로 표시한다. 카탈로그의 50ml 규격은 환제가 될 수 없으므로 "
            "원문의 ‘환’을 액상 제품명으로 바로잡는다."
        ),
        "action": "correct",
    }
}


def read_array(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
        raise ValueError(f"JSON 배열 형식이 아닙니다: {path}")
    return payload


def atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def validate_review_cohort(
    review_files: tuple[Path, ...],
    reviews: list[dict[str, Any]],
    *,
    expected_hashes: dict[str, str] = EXPECTED_REVIEW_FILE_HASHES,
    expected_count: int = EXPECTED_REVIEW_COHORT_COUNT,
) -> None:
    actual_names = {path.name for path in review_files}
    if actual_names != set(expected_hashes):
        raise ValueError("검토 파일 집합이 승인된 코호트와 다릅니다.")
    for path in review_files:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected_hashes[path.name]:
            raise ValueError(f"검토 파일 해시가 승인된 값과 다릅니다: {path.name}")
    document_ids = [str(row.get("document_id") or "") for row in reviews]
    if (
        len(reviews) != expected_count
        or len(set(document_ids)) != expected_count
        or "" in document_ids
    ):
        raise ValueError(
            f"검토 코호트는 고유 상품 {expected_count}개여야 합니다: "
            f"rows={len(reviews)}, unique={len(set(document_ids))}"
        )


def main() -> int:
    products = read_array(ROOT / "data/enrichment-queue.json")
    product_by_id = {str(row.get("document_id")): row for row in products}
    unmatched = [row for row in products if row.get("official_match_status") != "confirmed"]
    unmatched_by_id = {str(row.get("document_id")): row for row in unmatched}
    reviews = [row for path in REVIEW_FILES for row in read_array(path)]
    validate_review_cohort(REVIEW_FILES, reviews)
    review_by_id = {str(row.get("document_id")): row for row in reviews}

    if len(product_by_id) != len(products) or "" in product_by_id:
        raise ValueError("상품 document_id가 비어 있거나 중복됩니다.")
    if len(review_by_id) != len(reviews):
        raise ValueError("검토 결과 document_id가 비어 있거나 중복됩니다.")
    missing = sorted(set(unmatched_by_id) - set(review_by_id))
    unknown = sorted(set(review_by_id) - set(product_by_id))
    if missing or unknown:
        raise ValueError(
            "현재 미매칭 상품의 검토가 없거나 알 수 없는 검토가 있습니다: "
            f"missing={missing}, unknown={unknown}"
        )

    corrections: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for review in sorted(reviews, key=lambda row: int(row["source_order"])):
        review = {**review, **MANUAL_CORRECTIONS.get(int(review["source_order"]), {})}
        product = product_by_id[str(review["document_id"])]
        accepted_names = {review.get("original_name"), review.get("corrected_name")}
        accepted_capacities = {
            review.get("original_capacity"),
            review.get("corrected_capacity"),
        }
        if product.get("name") not in accepted_names:
            raise ValueError(
                f"검토 상품명이 정식 데이터와 다릅니다: {review['document_id']}"
            )
        if product.get("capacity") not in accepted_capacities:
            raise ValueError(
                f"검토 규격이 정식 데이터와 다릅니다: {review['document_id']}"
            )

        if review.get("action") != "correct":
            continue
        source_order = int(review["source_order"])
        reject_reason = MANUAL_REJECTIONS.get(source_order)
        evidence_urls = [str(url) for url in review.get("evidence_urls", []) if str(url)]
        confidence = str(review.get("confidence") or "")
        if not reject_reason and confidence == "medium" and source_order not in MANUAL_ACCEPTED_MEDIUM:
            reject_reason = "중간 신뢰도 제안이며 독립된 공식·상품 페이지로 정식 값 전체를 확정하지 못함"
        if not reject_reason and confidence not in {"high", "medium"}:
            reject_reason = f"신뢰도 {confidence!r}는 자동 승인 기준에 미달"
        if not reject_reason and not evidence_urls:
            reject_reason = "독립된 제품 페이지 또는 공식 원문 URL이 없음"
        if reject_reason:
            rejected.append(
                {
                    "source_order": source_order,
                    "document_id": review["document_id"],
                    "original_name": review["original_name"],
                    "proposed_name": review["corrected_name"],
                    "reason": reject_reason,
                }
            )
            continue

        correction = {
                "source_order": source_order,
                "document_id": review["document_id"],
                "original_name": review["original_name"],
                "corrected_name": review["corrected_name"],
                "original_capacity": review["original_capacity"],
                "corrected_capacity": review["corrected_capacity"],
                "evidence_urls": evidence_urls,
                "evidence_text": review["evidence_text"],
                "review_confidence": confidence,
                "approved": True,
            }
        if review.get("accepted_previous_names"):
            correction["accepted_previous_names"] = review["accepted_previous_names"]
        corrections.append(correction)

    status_counts = Counter(str(row.get("action") or "") for row in reviews)
    confidence_counts = Counter(str(row.get("confidence") or "") for row in reviews)
    current_unmatched_corrections = sum(
        row["document_id"] in unmatched_by_id for row in corrections
    )
    if len(corrections) != EXPECTED_APPROVED_CORRECTION_COUNT:
        raise ValueError(
            "승인 교정 수가 검수된 기준과 다릅니다: "
            f"{len(corrections)} != {EXPECTED_APPROVED_CORRECTION_COUNT}"
        )
    report = {
        "unmatched_product_count": len(unmatched),
        "review_cohort_product_count": len(reviews),
        "reviewed_product_count": len(reviews),
        "current_unmatched_reviewed_count": len(unmatched) - len(missing),
        "review_coverage_complete": not missing,
        "review_action_counts": dict(sorted(status_counts.items())),
        "review_confidence_counts": dict(sorted(confidence_counts.items())),
        "approved_correction_count": len(corrections),
        "current_unmatched_approved_correction_count": current_unmatched_corrections,
        "rejected_correction_count": len(rejected),
        "unchanged_or_followup_count": len(unmatched) - len(corrections),
        "rejected_corrections": rejected,
        "review_files": [str(path.relative_to(ROOT)).replace("\\", "/") for path in REVIEW_FILES],
        "canonical_product_schema_unchanged": True,
        "raw_app_fields_preserved": True,
    }
    atomic_write(OUTPUT, corrections)
    atomic_write(REPORT, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
