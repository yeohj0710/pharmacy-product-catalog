from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "enrichment-queue.json"
OUT = ROOT / "etc" / "image-research"
BATCH_SIZES = [28, 28, 27, 27, 27, 27, 27, 27]


def json_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def research_row(index: int, product: dict[str, Any]) -> dict[str, Any]:
    return {
        "queue_index": index,
        "catalog_product_id": str(product.get("id") or product.get("document_id") or ""),
        "document_id": str(product.get("document_id") or ""),
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
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    products = json.loads(SOURCE.read_text(encoding="utf-8"))
    if not isinstance(products, list) or len(products) != 776:
        raise ValueError(f"정식 데이터는 776개여야 합니다: {len(products) if isinstance(products, list) else 'not-array'}")

    document_ids = [str(row.get("document_id") or "") for row in products]
    if not all(document_ids) or len(document_ids) != len(set(document_ids)):
        raise ValueError("document_id가 비어 있거나 중복되었습니다.")

    missing = [research_row(index, row) for index, row in enumerate(products) if not str(row.get("image_url") or "").strip()]
    if len(missing) != sum(BATCH_SIZES):
        raise ValueError(f"예상 누락 수 {sum(BATCH_SIZES)}와 실제 누락 수 {len(missing)}가 다릅니다.")

    cursor = 0
    batch_ids: list[str] = []
    for batch_number, batch_size in enumerate(BATCH_SIZES, start=1):
        batch = missing[cursor:cursor + batch_size]
        cursor += batch_size
        batch_ids.extend(str(row["catalog_product_id"]) for row in batch)
        write_json(OUT / f"queue-batch-{batch_number:02d}.json", batch)

    missing_ids = [str(row["catalog_product_id"]) for row in missing]
    if cursor != len(missing) or len(batch_ids) != len(set(batch_ids)) or batch_ids != missing_ids:
        raise ValueError("조사 배치가 누락·중복되었거나 정식 데이터 순서를 벗어났습니다.")

    rights_counts: dict[str, int] = {}
    for row in products:
        rights = str(row.get("image_rights_status") or "")
        rights_counts[rights] = rights_counts.get(rights, 0) + 1

    summary = {
        "canonical_path": str(SOURCE),
        "canonical_sha256": json_sha256(SOURCE),
        "total_count": len(products),
        "image_count": sum(bool(str(row.get("image_url") or "").strip()) for row in products),
        "image_missing_count": len(missing),
        "official_image_count": sum(
            bool(str(row.get("image_url") or "").strip())
            and row.get("image_rights_status") == "official_source_preview"
            for row in products
        ),
        "external_image_count": sum(
            bool(str(row.get("image_url") or "").strip())
            and row.get("image_rights_status") != "official_source_preview"
            for row in products
        ),
        "rights_status_counts": rights_counts,
        "batch_sizes": BATCH_SIZES,
        "missing_product_ids": missing_ids,
    }
    write_json(OUT / "baseline-summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
