from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
from pathlib import Path
from typing import Any

from rapidfuzz.fuzz import ratio


NOTIFICATION_PATTERNS = (
    "님에게",
    "메시지를 보냈",
    "메시지 도착",
    "카카오톡",
    "알림",
)


def normalize(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", value.lower())


def full_key(item: dict[str, Any]) -> str:
    return normalize(str(item.get("name", "")) + str(item.get("specification", "")))


def contains_notification(item: dict[str, Any]) -> bool:
    text = " ".join(str(item.get(key, "")) for key in ("name", "specification", "category"))
    return any(pattern in text for pattern in NOTIFICATION_PATTERNS)


def same_product(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left.get("displayed_price_krw") != right.get("displayed_price_krw"):
        return False
    if abs(float(left.get("source_second", 0)) - float(right.get("source_second", 0))) > 5:
        return False
    left_key, right_key = full_key(left), full_key(right)
    if left_key == right_key:
        return True
    if min(len(left_key), len(right_key)) < 5:
        return False
    return ratio(left_key, right_key) >= 96


def preferred(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    def quality(item: dict[str, Any]) -> tuple[int, float, int]:
        return (
            int(item.get("observations", 1)),
            float(item.get("ocr_confidence", 0)),
            len(str(item.get("name", ""))) + len(str(item.get("specification", ""))),
        )

    winner = dict(max((left, right), key=quality))
    winner["observations"] = int(left.get("observations", 1)) + int(right.get("observations", 1))
    winner["source_second"] = min(float(left.get("source_second", 0)), float(right.get("source_second", 0)))
    winner["source_frame"] = min(int(left.get("source_frame", 0)), int(right.get("source_frame", 0)))
    return winner


def merge(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items.sort(key=lambda item: (float(item.get("source_second", 0)), int(item.get("first_seen_order", 0))))
    merged: list[dict[str, Any]] = []
    for item in items:
        for index in range(len(merged) - 1, max(-1, len(merged) - 30), -1):
            if same_product(merged[index], item):
                merged[index] = preferred(merged[index], item)
                break
        else:
            merged.append(dict(item))
    return sorted(merged, key=lambda item: (float(item.get("source_second", 0)), int(item.get("first_seen_order", 0))))


def merge_reference(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items.sort(key=lambda item: float(item.get("source_second", 0)))
    merged: list[dict[str, Any]] = []
    for item in items:
        item_key = full_key(item)
        for index in range(len(merged) - 1, max(-1, len(merged) - 12), -1):
            existing = merged[index]
            if existing.get("displayed_price_krw") != item.get("displayed_price_krw"):
                continue
            if abs(float(existing.get("source_second", 0)) - float(item.get("source_second", 0))) > 5:
                continue
            score = ratio(full_key(existing), item_key)
            one_is_weak = min(int(existing.get("observations", 1)), int(item.get("observations", 1))) <= 1
            if score >= 94 or (one_is_weak and score >= 78):
                merged[index] = preferred(existing, item)
                break
        else:
            merged.append(dict(item))
    return sorted(merged, key=lambda item: float(item.get("source_second", 0)))


def alignment_score(left: dict[str, Any], right: dict[str, Any]) -> float:
    if left.get("displayed_price_krw") != right.get("displayed_price_krw"):
        return -80
    name_score = ratio(full_key(left), full_key(right))
    if name_score < 52:
        return -50
    category_bonus = 10 if left.get("category") == right.get("category") else -4
    time_penalty = min(25, abs(float(left.get("source_second", 0)) - float(right.get("source_second", 0))) * 3)
    return name_score - 54 + category_bonus - time_penalty


def align_passes(primary: list[dict[str, Any]], secondary: list[dict[str, Any]]) -> list[dict[str, Any]]:
    primary = sorted(primary, key=lambda item: float(item.get("source_second", 0)))
    secondary = sorted(secondary, key=lambda item: float(item.get("source_second", 0)))
    rows, columns = len(primary), len(secondary)
    gap = -12.0
    scores = [[0.0] * (columns + 1) for _ in range(rows + 1)]
    directions = [[0] * (columns + 1) for _ in range(rows + 1)]
    for row in range(1, rows + 1):
        scores[row][0] = row * gap
        directions[row][0] = 1
    for column in range(1, columns + 1):
        scores[0][column] = column * gap
        directions[0][column] = 2

    for row in range(1, rows + 1):
        for column in range(1, columns + 1):
            match = scores[row - 1][column - 1] + alignment_score(primary[row - 1], secondary[column - 1])
            drop_primary = scores[row - 1][column] + gap
            drop_secondary = scores[row][column - 1] + gap
            best = max(match, drop_primary, drop_secondary)
            scores[row][column] = best
            directions[row][column] = 0 if best == match else (1 if best == drop_primary else 2)

    aligned: list[dict[str, Any]] = []
    row, column = rows, columns
    while row > 0 or column > 0:
        direction = directions[row][column]
        if row > 0 and column > 0 and direction == 0:
            left, right = primary[row - 1], secondary[column - 1]
            if alignment_score(left, right) > 0:
                aligned.append(preferred(left, right))
            else:
                aligned.extend((left, right))
            row -= 1
            column -= 1
        elif row > 0 and (column == 0 or direction == 1):
            aligned.append(primary[row - 1])
            row -= 1
        else:
            aligned.append(secondary[column - 1])
            column -= 1
    return sorted(aligned, key=lambda item: float(item.get("source_second", 0)))


def main() -> int:
    parser = argparse.ArgumentParser(description="OCR 결과를 개인정보 없이 검색용 상품 데이터로 정리합니다.")
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, default=Path("etc/ocr-final/products.json"))
    parser.add_argument("--public-output", type=Path, default=Path("etc/ocr-final/products.public-copy.json"))
    parser.add_argument("--csv-output", type=Path, default=Path("etc/ocr-final/catalog.csv"))
    parser.add_argument("--public-csv-output", type=Path, default=Path("etc/ocr-final/catalog.public-copy.csv"))
    parser.add_argument("--report", type=Path, default=Path("etc/ocr-final/quality-report.json"))
    parser.add_argument("--manifest", type=Path, default=Path("etc/ocr-final/source-manifest.json"))
    parser.add_argument("--expected", type=int, default=776)
    parser.add_argument("--cosmetic-reference", type=Path)
    args = parser.parse_args()

    datasets = [json.loads(path.read_text(encoding="utf-8")) for path in args.inputs]
    items = [item for dataset in datasets for item in dataset]
    excluded = [item for item in items if contains_notification(item)]
    clean_datasets = [[item for item in dataset if not contains_notification(item)] for dataset in datasets]
    clean = clean_datasets[0]
    for dataset in clean_datasets[1:]:
        clean = align_passes(clean, dataset)
    if args.cosmetic_reference:
        reference = json.loads(args.cosmetic_reference.read_text(encoding="utf-8"))
        reference = merge_reference([item for item in reference if not contains_notification(item)])
        cosmetic_times = [float(item.get("source_second", 0)) for item in clean if item.get("category") == "코스메틱"]
        start = min(cosmetic_times, default=180)
        end = max(cosmetic_times, default=start + 16)
        clean = [item for item in clean if item.get("category") != "코스메틱"]
        for index, item in enumerate(reference):
            item["category"] = "코스메틱"
            item["source_second"] = start + (end - start) * index / max(1, len(reference) - 1)
            clean.append(item)
    clean = merge(clean)

    for index, item in enumerate(clean, start=1):
        item["id"] = f"product-{index:04d}"
        item["normalized_name"] = normalize(str(item.get("name", "")))
        item["recorded_at"] = "2026-07-15"
        item["price_status"] = "녹화 당시 앱 표시값"
        item["source_type"] = "사용자 제공 화면 녹화의 OCR 추출"
        observations = int(item.get("observations", 1))
        item["verification_status"] = "반복 화면 확인" if observations >= 2 else "사람 검수 필요"
        if item.get("category") == "아벤트":
            item["category"] = "이벤트"
        item.setdefault("image_url", "")
        item.setdefault("image_source_url", "")
        item.setdefault("image_rights_status", "미확인")
        item.pop("source_path", None)

    for path in (args.output, args.public_output, args.csv_output, args.public_csv_output, args.report, args.manifest):
        path.parent.mkdir(parents=True, exist_ok=True)

    payload = json.dumps(clean, ensure_ascii=False, indent=2)
    args.output.write_text(payload, encoding="utf-8")
    args.public_output.write_text(payload, encoding="utf-8")
    if clean:
        fields = sorted({key for item in clean for key in item})
        for csv_path in (args.csv_output, args.public_csv_output):
            with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(clean)

    categories: dict[str, int] = {}
    for item in clean:
        category = str(item.get("category") or "미분류")
        categories[category] = categories.get(category, 0) + 1
    prices = [int(item["displayed_price_krw"]) for item in clean]
    report = {
        "app_displayed_count": args.expected,
        "extracted_unique_count": len(clean),
        "coverage_percent": round(len(clean) / args.expected * 100, 1) if args.expected else None,
        "excluded_notification_rows": len(excluded),
        "human_review_required": sum(item["verification_status"] == "사람 검수 필요" for item in clean),
        "officially_linked": sum(bool(item.get("official_item_seq")) for item in clean),
        "images_linked": sum(bool(item.get("image_url")) for item in clean),
        "categories": dict(sorted(categories.items(), key=lambda pair: pair[1], reverse=True)),
        "price_min_krw": min(prices, default=0),
        "price_median_krw": int(statistics.median(prices)) if prices else 0,
        "price_max_krw": max(prices, default=0),
    }
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    source_counts: dict[str, int] = {}
    for item in clean:
        source_file = str(item.get("source_video") or "출처 파일 미확인")
        source_counts[source_file] = source_counts.get(source_file, 0) + 1
    manifest = {
        "recorded_at": "2026-07-15",
        "source_path_not_published": True,
        "source_files": source_counts,
        "extracted_fields": [
            "상품명",
            "규격",
            "분류",
            "녹화 당시 앱 표시 가격",
            "출처 녹화 파일명",
            "화면 시간",
            "화면 프레임",
            "문자 인식 신뢰도",
            "반복 관찰 횟수",
        ],
        "price_notice": "가격은 녹화 당시 앱에 표시된 참고값이며 현재 판매가나 재고를 뜻하지 않습니다.",
        "raw_screen_images_published": False,
        "notification_and_personal_data_excluded": True,
    }
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
