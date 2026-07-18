from __future__ import annotations

import glob
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "enrichment-queue.json"
OUT = ROOT / "etc" / "image-research"
BATCH_SIZES = [24, 24, 24, 23]


def read_array(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"최상위 값은 배열이어야 합니다: {path}")
    return payload


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    products = read_array(DATA)
    prior: dict[str, dict[str, Any]] = {}
    for filename in sorted(glob.glob(str(OUT / "results-batch-*.json"))):
        for row in read_array(Path(filename)):
            prior[str(row.get("catalog_product_id") or "")] = row

    queue: list[dict[str, Any]] = []
    for product in products:
        if str(product.get("image_url") or "").strip():
            continue
        product_id = str(product.get("document_id") or "")
        previous = prior.get(product_id, {})
        queue.append(
            {
                "catalog_product_id": product_id,
                "document_id": product_id,
                "catalog_name": str(product.get("name") or ""),
                "catalog_capacity": str(product.get("capacity") or ""),
                "catalog_category": str(product.get("category") or ""),
                "catalog_etc": str(product.get("etc") or ""),
                "official_match_status": str(product.get("official_match_status") or ""),
                "official_item_name": str(product.get("official_item_name") or ""),
                "official_manufacturer": str(product.get("official_manufacturer") or ""),
                "official_dosage_form": str(product.get("official_dosage_form") or ""),
                "official_pack_unit": str(product.get("official_pack_unit") or ""),
                "official_source_url": str(product.get("official_source_url") or ""),
                "previous_status": str(previous.get("status") or ""),
                "previous_candidate_name": str(previous.get("candidate_name") or ""),
                "previous_source_url": str(previous.get("source_url") or ""),
                "previous_image_url": str(previous.get("image_url") or ""),
                "previous_searched_queries": previous.get("searched_queries") or [],
                "previous_searched_sites": previous.get("searched_sites") or [],
                "previous_failure_reason": str(previous.get("failure_reason") or ""),
            }
        )
    if len(queue) != sum(BATCH_SIZES):
        raise ValueError(f"예상 재조사 수 {sum(BATCH_SIZES)}와 실제 {len(queue)}가 다릅니다.")

    cursor = 0
    all_ids: list[str] = []
    for number, size in enumerate(BATCH_SIZES, start=1):
        batch = queue[cursor:cursor + size]
        cursor += size
        all_ids.extend(str(row["catalog_product_id"]) for row in batch)
        write_json(OUT / f"retry-queue-batch-{number:02d}.json", batch)
    if len(all_ids) != len(set(all_ids)) or all_ids != [str(row["catalog_product_id"]) for row in queue]:
        raise ValueError("재조사 큐가 중복되었거나 순서가 달라졌습니다.")
    write_json(OUT / "retry-queue.json", queue)
    print(json.dumps({"retry_count": len(queue), "batch_sizes": BATCH_SIZES}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
