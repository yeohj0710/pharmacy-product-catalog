from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="주 에이전트가 명시적으로 승인한 이미지 조사 결과만 병합 형식으로 만듭니다.")
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--approved-ids", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    audit = read_json(args.audit)
    records = audit.get("records") if isinstance(audit, dict) else None
    approved_payload = read_json(args.approved_ids)
    if not isinstance(records, list) or not isinstance(approved_payload, list):
        raise ValueError("audit.records와 approved-ids는 배열이어야 합니다.")
    approved_ids = {str(value) for value in approved_payload}
    record_ids = {str(record.get("catalog_product_id") or "") for record in records}
    unknown = approved_ids - record_ids
    if unknown:
        raise ValueError(f"audit에 없는 승인 ID가 있습니다: {sorted(unknown)}")

    output: list[dict[str, Any]] = []
    for record in records:
        product_id = str(record.get("catalog_product_id") or "")
        approved = product_id in approved_ids
        if approved and (record.get("status") != "confirmed" or record.get("automated_valid") is not True):
            raise ValueError(f"자동 검증을 통과하지 않은 레코드는 승인할 수 없습니다: {product_id}")
        clean = {
            key: value
            for key, value in record.items()
            if key not in {"source_check", "image_check", "automated_failures", "automated_valid"}
        }
        if approved:
            clean.update(status="confirmed", manual_verified=True, visual_verified=True)
        elif clean.get("status") == "confirmed":
            clean.update(
                status="review_required",
                image_url="",
                source_url="",
                result_url="",
                manual_verified=False,
                visual_verified=False,
                failure_reason="주 에이전트의 시각 검수에서 승인되지 않음",
            )
        output.append(clean)

    write_json(args.output, output)
    print(
        json.dumps(
            {
                "record_count": len(output),
                "approved_count": len(approved_ids),
                "review_required_count": sum(row.get("status") == "review_required" for row in output),
                "not_found_count": sum(row.get("status") == "not_found" for row in output),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
