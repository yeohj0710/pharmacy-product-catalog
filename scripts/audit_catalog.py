from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from rapidfuzz.fuzz import ratio


def normalize(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", value.lower())


def main() -> int:
    parser = argparse.ArgumentParser(description="시간·가격·이름 유사도로 OCR 중복 후보를 찾습니다.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--threshold", type=float, default=72)
    args = parser.parse_args()
    items = json.loads(args.input.read_text(encoding="utf-8"))
    pairs = []
    for index, left in enumerate(items):
        for right in items[index + 1 : index + 30]:
            if abs(float(left.get("source_second", 0)) - float(right.get("source_second", 0))) > 6:
                continue
            if left.get("displayed_price_krw") != right.get("displayed_price_krw"):
                continue
            left_key = normalize(str(left.get("name", "")) + str(left.get("specification", "")))
            right_key = normalize(str(right.get("name", "")) + str(right.get("specification", "")))
            score = ratio(left_key, right_key)
            if score < args.threshold:
                continue
            pairs.append(
                {
                    "score": round(score, 1),
                    "price": left.get("displayed_price_krw"),
                    "left": {
                        "name": left.get("name"),
                        "specification": left.get("specification"),
                        "observations": left.get("observations"),
                        "second": left.get("source_second"),
                    },
                    "right": {
                        "name": right.get("name"),
                        "specification": right.get("specification"),
                        "observations": right.get("observations"),
                        "second": right.get("source_second"),
                    },
                }
            )
    pairs.sort(key=lambda item: (-item["score"], item["left"]["second"]))
    print(json.dumps(pairs, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
