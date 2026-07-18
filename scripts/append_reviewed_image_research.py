from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_array(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"최상위 값은 배열이어야 합니다: {path}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path, default=Path("data/image-manual-web-research.json"))
    parser.add_argument("--reviewed", type=Path, required=True)
    args = parser.parse_args()

    existing = read_array(args.target) if args.target.exists() else []
    reviewed = read_array(args.reviewed)
    selected = {
        str(row.get("catalog_product_id") or ""): row
        for row in reviewed
        if row.get("status") == "confirmed"
        and row.get("manual_verified") is True
        and row.get("visual_verified") is True
    }
    if "" in selected:
        raise ValueError("승인 레코드에 catalog_product_id가 없습니다.")
    output: list[dict[str, Any]] = []
    replaced: set[str] = set()
    for row in existing:
        product_id = str(row.get("catalog_product_id") or "")
        if product_id in selected:
            output.append(selected[product_id])
            replaced.add(product_id)
        else:
            output.append(row)
    for product_id, row in selected.items():
        if product_id not in replaced:
            output.append(row)
    args.target.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"before": len(existing), "approved": len(selected), "after": len(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
