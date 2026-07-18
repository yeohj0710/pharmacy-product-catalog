from __future__ import annotations

import glob
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "etc" / "image-research"


def read_array(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"배열 JSON이 아닙니다: {path}")
    return payload


def main() -> int:
    products = read_array(ROOT / "data" / "enrichment-queue.json")
    baseline = read_array(RESEARCH / "backups" / "enrichment-queue.start.json")
    baseline_by_id = {str(row.get("document_id") or ""): row for row in baseline}
    latest: dict[str, dict[str, Any]] = {}
    patterns = (
        "results-batch-*.json",
        "retry-results-batch-*.json",
        "followup-results-batch-*.json",
        "final-pass-results-batch-*.json",
        "legacy-search-results-batch-*.json",
    )
    for pattern in patterns:
        for filename in sorted(glob.glob(str(RESEARCH / pattern))):
            for row in read_array(Path(filename)):
                latest[str(row.get("catalog_product_id") or "")] = row

    missing = []
    for product in products:
        if str(product.get("image_url") or "").strip():
            continue
        product_id = str(product.get("document_id") or "")
        before = baseline_by_id[product_id]
        research = latest.get(product_id, {})
        removed_search_thumbnail = "search.pstatic.net" in str(before.get("image_url") or "")
        reason = str(research.get("failure_reason") or "").strip()
        latest_status = str(research.get("status") or "")
        if latest_status == "confirmed":
            latest_status = "rejected_after_main_review"
            if product_id == "20250812_104856":
                reason = "제조사 페이지가 제공한 파일이 실제 제품 사진이 아니라 '이미지 준비 중입니다' 자리표시자여서 제외했습니다."
        if removed_search_thumbnail:
            prefix = "기존 네이버 검색 결과 썸네일은 원본 이미지가 아니어서 제거했습니다."
            reason = f"{prefix} {reason}".strip()
        if not reason:
            reason = "여러 출처를 조사했지만 상품명·제형·용량·포장 단위를 모두 확인할 수 있는 정상 원본 이미지를 찾지 못했습니다."
        missing.append({
            "catalog_product_id": product_id,
            "name": str(product.get("name") or ""),
            "capacity": str(product.get("capacity") or ""),
            "category": str(product.get("category") or ""),
            "official_match_status": str(product.get("official_match_status") or ""),
            "removed_search_thumbnail": removed_search_thumbnail,
            "latest_research_status": latest_status,
            "searched_queries": research.get("searched_queries") or [],
            "searched_sites": research.get("searched_sites") or [],
            "reason": reason,
        })
    output = RESEARCH / "final-missing-products.json"
    output.write_text(json.dumps(missing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"missing_count": len(missing), "removed_search_thumbnail_count": sum(row["removed_search_thumbnail"] for row in missing)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
