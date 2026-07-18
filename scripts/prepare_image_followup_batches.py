from __future__ import annotations

import glob
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "enrichment-queue.json"
OUT = ROOT / "etc" / "image-research"


def read_array(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"최상위 값은 배열이어야 합니다: {path}")
    return payload


def write_batches(prefix: str, rows: list[dict[str, Any]], batch_count: int = 4) -> list[int]:
    sizes = [len(rows) // batch_count + (1 if index < len(rows) % batch_count else 0) for index in range(batch_count)]
    cursor = 0
    ids: list[str] = []
    for number, size in enumerate(sizes, start=1):
        batch = rows[cursor : cursor + size]
        cursor += size
        ids.extend(str(row["catalog_product_id"]) for row in batch)
        (OUT / f"{prefix}-queue-batch-{number:02d}.json").write_text(
            json.dumps(batch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if len(ids) != len(set(ids)) or ids != [str(row["catalog_product_id"]) for row in rows]:
        raise ValueError(f"{prefix} 큐가 중복되었거나 순서가 달라졌습니다.")
    return sizes


def queue_row(product: dict[str, Any], previous: dict[str, Any], *, replace_existing: bool) -> dict[str, Any]:
    product_id = str(product.get("document_id") or "")
    return {
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
        "replace_existing_search_thumbnail": replace_existing,
        "existing_image_url": str(product.get("image_url") or "") if replace_existing else "",
        "existing_image_source_url": str(product.get("image_source_url") or "") if replace_existing else "",
        "previous_status": str(previous.get("status") or ""),
        "previous_candidate_name": str(previous.get("candidate_name") or ""),
        "previous_source_url": str(previous.get("source_url") or ""),
        "previous_image_url": str(previous.get("image_url") or ""),
        "previous_searched_queries": previous.get("searched_queries") or [],
        "previous_searched_sites": previous.get("searched_sites") or [],
        "previous_failure_reason": str(previous.get("failure_reason") or ""),
    }


def main() -> int:
    products = read_array(DATA)
    prior: dict[str, dict[str, Any]] = {}
    for pattern in ("results-batch-*.json", "retry-results-batch-*.json"):
        for filename in sorted(glob.glob(str(OUT / pattern))):
            for row in read_array(Path(filename)):
                prior[str(row.get("catalog_product_id") or "")] = row

    missing: list[dict[str, Any]] = []
    search_thumbnails: list[dict[str, Any]] = []
    for product in products:
        product_id = str(product.get("document_id") or "")
        image_url = str(product.get("image_url") or "").strip()
        if not image_url:
            missing.append(queue_row(product, prior.get(product_id, {}), replace_existing=False))
        elif "search.pstatic.net" in image_url:
            search_thumbnails.append(queue_row(product, prior.get(product_id, {}), replace_existing=True))

    missing_sizes = write_batches("followup", missing)
    legacy_sizes = write_batches("legacy-search", search_thumbnails)
    print(json.dumps({"missing": len(missing), "missing_batches": missing_sizes,
                      "search_thumbnails": len(search_thumbnails), "search_batches": legacy_sizes}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
