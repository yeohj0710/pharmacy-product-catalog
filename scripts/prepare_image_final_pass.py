from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.prepare_image_followup_batches import DATA, OUT, queue_row, read_array, write_batches


def main() -> int:
    prior = {}
    for pattern in ("results-batch-*.json", "retry-results-batch-*.json", "followup-results-batch-*.json"):
        for filename in sorted(glob.glob(str(OUT / pattern))):
            for row in read_array(Path(filename)):
                prior[str(row.get("catalog_product_id") or "")] = row

    queue = []
    for product in read_array(DATA):
        if str(product.get("image_url") or "").strip():
            continue
        product_id = str(product.get("document_id") or "")
        queue.append(queue_row(product, prior.get(product_id, {}), replace_existing=False))
    sizes = write_batches("final-pass", queue)
    print(json.dumps({"final_pass_count": len(queue), "batch_sizes": sizes}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
