from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPROVED_INDICES = {
    10, 11, 14, 18, 27, 28, 29, 33, 36, 39, 43, 45, 46, 48, 49, 50, 52, 53, 55, 57, 60, 65, 67, 68, 71, 72,
    73, 75, 76, 78, 79, 80, 82, 84, 85, 86, 89, 90, 91, 92, 94, 95, 96, 97, 99, 101, 103, 105, 108,
    112, 113, 115, 116, 117, 118, 119, 120, 121, 122, 123, 124, 125, 126, 127, 128, 129, 130, 132, 134, 136, 141, 142, 143,
    145, 148, 150, 151, 152, 153, 154, 157, 158, 159, 160, 161, 162, 164, 166, 169, 170, 171, 173, 175, 180, 185, 186, 187, 191, 192, 193, 194, 196, 197,
    206, 212, 215, 220, 221, 222, 223, 224, 226, 228, 229, 232, 233, 235, 238, 242, 245, 247, 248, 250, 251,
    255, 257, 259, 260, 262, 263, 264, 265, 266, 267, 268, 270, 272, 275, 276, 279, 281, 287, 290, 292, 295, 296, 298, 299, 300, 303, 304, 305,
    307, 310, 315, 317, 318, 319, 320, 322, 330, 336, 337, 339, 340, 341, 342, 343, 345, 346, 347, 348, 351, 353, 354, 355, 356, 359,
    364, 367, 370, 375, 377, 378, 379, 380, 381, 382, 384, 385, 386, 388, 391, 395, 397, 398, 399, 402, 403, 405, 406, 412, 413, 417, 418,
}


def main() -> int:
    queue = json.loads((ROOT / "etc/image-review/review-index.json").read_text(encoding="utf-8"))
    approved = []
    decisions = []
    for index, entry in enumerate(queue, start=1):
        product, candidate = entry["product"], entry["candidate"]
        is_approved = index in APPROVED_INDICES
        decisions.append({
            "review_index": index,
            "catalog_product_id": product["id"],
            "catalog_name": product["name"],
            "catalog_capacity": product["capacity"],
            "decision": "approved" if is_approved else "rejected",
        })
        if is_approved:
            approved.append({
                **candidate,
                "status": "confirmed",
                "manual_verified": True,
                "visual_verified": True,
                "visual_review_index": index,
                "visual_review_reason": "상품명·규격·제품 패키지를 검수 시트에서 직접 대조함",
                "visual_reviewed_at": "2026-07-16T16:10:00+09:00",
            })
    (ROOT / "data/image-visual-review.json").write_text(
        json.dumps(approved, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "etc/image-review/visual-decisions.json").write_text(
        json.dumps(decisions, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"reviewed": len(queue), "approved": len(approved), "rejected": len(queue) - len(approved)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
