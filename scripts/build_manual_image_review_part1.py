from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = DATA / "image-manual-review-part-1.json"
SUMMARY = DATA / "image-manual-review-part-1-summary.json"
LIMIT = 77


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_atomic(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def candidate_maps(prefix: str) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for path in sorted(DATA.glob(f"{prefix}-image-part-*.json")):
        if "summary" in path.name:
            continue
        for row in load(path):
            product_id = str(row.get("catalog_product_id") or "")
            if product_id:
                output[product_id] = row
    return output


# 네이버/다나와 검색 결과 제목과 원문 링크를 상품명·용량·카테고리에 대조한 판정.
# n=네이버 이미지, s=다나와 상품 검색.
CONFIRMED_SOURCE = {
    3: "n", 4: "n", 5: "n", 6: "n",
    17: "s", 18: "s", 19: "n", 20: "n", 22: "n", 24: "n",
    27: "n", 28: "n", 31: "n", 34: "s", 35: "s", 36: "s",
    40: "s", 43: "s", 44: "s", 45: "s", 46: "s", 47: "s",
    48: "s", 50: "s", 55: "s", 56: "s", 59: "n", 61: "s",
    63: "n", 67: "n", 71: "s", 73: "n", 76: "n",
}


REVIEW_REASONS = {
    0: "카탈로그에 혈압계 모델명이 없고 후보도 다른 모델 또는 일반 혈압계 기사임",
    1: "카탈로그는 100캡슐이지만 후보는 60캡슐임",
    2: "카탈로그의 캡슐·수량과 후보의 정제·포장 구성이 일치하지 않음",
    7: "원문 제목이 세노바액·챔프알러논·지르세틴액을 함께 다뤄 이미지가 특정 제품인지 확인할 수 없음",
    8: "후보가 챔프이부펜 제품과 무관함",
    9: "카탈로그는 콜드캡슐이지만 후보는 콜드시럽임",
    10: "카탈로그 상품명이 '드링크'로 너무 일반적이어서 제품을 특정할 수 없음",
    11: "카탈로그는 병 단위 컨디션이지만 후보는 환·스틱 제품임",
    12: "후보 제목만으로 판피린 5병 제품의 정확한 제형과 규격을 확인할 수 없음",
    13: "상품명과 10병 규격이 일치하는 이미지 후보를 찾지 못함",
    14: "카탈로그는 10병이지만 후보는 100병 포장임",
    15: "카탈로그에 제조사·브랜드가 없어 해피홈 제품과 동일하다고 확정할 수 없음",
    16: "후보가 바세린 풋크림과 무관함",
    21: "다나와 후보는 운동용품이고 네이버 후보는 일반 엽산 정보라 제품을 특정할 수 없음",
    23: "후보 제품명이 훼리모아로 달라 훼로모아와 동일 제품인지 확정할 수 없음",
    25: "후보가 아세트아미노펜 성분명만 다루며 이큐펜키즈A 제품을 특정하지 않음",
    26: "후보가 해열제 성분 비교 글이며 이큐펜키즈A 이부프로펜 제품을 특정하지 않음",
    29: "후보에 시카케어 소형 규격이 표시되지 않아 크기별 제품을 구분할 수 없음",
    30: "상품명과 30ml 규격이 일치하는 이미지 후보를 찾지 못함",
    32: "후보가 멀티비타민V가 아닌 멀티비타민앤미네랄·하루바이타민맥스 제품임",
    33: "후보가 다른 제조사의 칼마디 제품임",
    37: "다나와 후보는 의류이며 네이버 후보도 알부스 영양제를 특정하지 않음",
    38: "후보가 프로폴리스 영양제가 아닌 선크림이거나 일반 프로폴리스 정보임",
    39: "카탈로그는 1박스지만 후보는 6개입 묶음 상품임",
    41: "후보에 키즈 규격이 없어 마데카습윤밴드키즈와 동일 제품인지 확인할 수 없음",
    42: "카탈로그는 30매지만 후보는 큐티용 10매임",
    49: "후보에 손목 L 사이즈가 표시되지 않음",
    51: "후보의 5cm×5m 1롤과 카탈로그 1박스 규격이 같은지 확인할 수 없음",
    52: "후보가 웰업엠앰엠테이프와 무관함",
    53: "후보에 중형 10cm 규격이 표시되지 않음",
    54: "카탈로그는 48정이지만 후보는 108정 또는 EX 제품임",
    57: "후보가 젠빅이 아닌 젠빅플러스 제품임",
    58: "후보가 리버시마린 일반 정보라 프리미엄리버시마린 제품을 특정하지 않음",
    60: "다나와 후보는 다른 상품이고 네이버 후보도 우루사 종류를 구분하지 않음",
    62: "후보가 기넥슨에프 제품과 무관함",
    64: "후보가 노이텍 의약품이 아닌 헬스케어 기기·기업 정보임",
    65: "후보가 일반 면역·비타민 정보라 5070면역비타민 제품을 특정하지 않음",
    66: "원문이 비가졸액·니조랄·댄스탑을 함께 다뤄 이미지가 비가졸 제품인지 확인할 수 없음",
    68: "후보가 알러나딘이 아닌 알러엑스 제품임",
    69: "후보에 하벤큐가 아닌 하벤만 표시되어 제품 변형을 구분할 수 없음",
    70: "카탈로그는 150ml지만 후보는 500ml 제품임",
    72: "카탈로그는 비타민C 500mg이지만 후보는 3000mg 제품임",
    74: "후보가 디어미T 제품과 무관함",
    75: "후보에 니코틴엘 30mg·7매 규격이 표시되지 않음",
}


def choose_review_candidate(
    secondary: dict[str, Any], naver: dict[str, Any]
) -> tuple[dict[str, Any], str]:
    available = [
        (secondary, "다나와 상품 검색"),
        (naver, "네이버 이미지 검색"),
    ]
    available = [(row, source) for row, source in available if row.get("image_url")]
    if not available:
        source_url = str(naver.get("source_url") or secondary.get("source_url") or "")
        return {"source_url": source_url}, ""
    return max(available, key=lambda item: int(item[0].get("match_score") or 0))


def verified_reason(product: dict[str, Any], candidate: dict[str, Any]) -> str:
    capacity = str(product.get("capacity") or "").strip()
    title = str(candidate.get("candidate_name") or "")
    if capacity and any(char.isdigit() for char in capacity) and any(char.isdigit() for char in title):
        return "후보 제목에서 고유 제품명과 규격을 확인했으며 제형·카테고리 충돌이 없음"
    return "후보 제목에서 고유 제품명을 확인했으며 용량·제형·대상 제품군 충돌이 없음"


def main() -> None:
    products = [row for row in load(DATA / "enrichment-queue.json") if not row.get("image_url")][:LIMIT]
    secondary = candidate_maps("secondary")
    naver = candidate_maps("naver")
    records: list[dict[str, Any]] = []

    expected_review = set(range(LIMIT)) - set(CONFIRMED_SOURCE)
    if expected_review != set(REVIEW_REASONS):
        missing = expected_review - set(REVIEW_REASONS)
        extra = set(REVIEW_REASONS) - expected_review
        raise RuntimeError(f"검수 판정 누락 또는 중복: missing={sorted(missing)}, extra={sorted(extra)}")

    for index, product in enumerate(products):
        product_id = str(product.get("id") or product.get("document_id") or "")
        secondary_candidate = secondary.get(product_id, {})
        naver_candidate = naver.get(product_id, {})
        manual_verified = index in CONFIRMED_SOURCE
        if manual_verified:
            source_key = CONFIRMED_SOURCE[index]
            candidate = secondary_candidate if source_key == "s" else naver_candidate
            source_label = "다나와 상품 검색" if source_key == "s" else "네이버 이미지 검색"
            if not candidate.get("image_url") or not candidate.get("result_url"):
                raise RuntimeError(f"확정 후보 자료 누락: index={index}, id={product_id}")
            status = "confirmed"
            reason = verified_reason(product, candidate)
        else:
            if index in {13, 30}:
                candidate = {
                    "source_url": str(
                        naver_candidate.get("source_url")
                        or secondary_candidate.get("source_url")
                        or ""
                    )
                }
                source_label = "네이버 이미지 검색"
            else:
                candidate, source_label = choose_review_candidate(secondary_candidate, naver_candidate)
            status = "review_required"
            reason = REVIEW_REASONS[index]

        records.append(
            {
                "catalog_product_id": product_id,
                "catalog_name": str(product.get("name") or ""),
                "catalog_capacity": str(product.get("capacity") or ""),
                "catalog_category": str(product.get("category") or ""),
                "candidate_name": str(candidate.get("candidate_name") or ""),
                "image_url": str(candidate.get("image_url") or ""),
                "source_url": str(candidate.get("source_url") or ""),
                "result_url": str(candidate.get("result_url") or ""),
                "match_score": int(candidate.get("match_score") or 0),
                "status": status,
                "manual_verified": manual_verified,
                "review_reason": reason,
                "candidate_source": source_label,
                "reviewed_at": now_iso(),
            }
        )

    status_counts = Counter(record["status"] for record in records)
    summary = {
        "generated_at": now_iso(),
        "range": {"start_index": 0, "end_index_inclusive": LIMIT - 1},
        "reviewed_count": len(records),
        "status_counts": dict(status_counts),
        "manual_verified_count": sum(record["manual_verified"] for record in records),
        "candidate_image_count": sum(bool(record["image_url"]) for record in records),
        "no_candidate_count": sum(not record["image_url"] for record in records),
        "confirmed_source_counts": dict(
            Counter(record["candidate_source"] for record in records if record["manual_verified"])
        ),
        "method": "상품명·용량·카테고리와 후보 제목·원문 링크를 대조하고 충돌 후보를 제외함",
    }
    write_atomic(OUTPUT, records)
    write_atomic(SUMMARY, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
