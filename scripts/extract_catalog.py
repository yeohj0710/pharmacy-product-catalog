from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import cv2
from paddleocr import PaddleOCR
from rapidfuzz.fuzz import ratio


PRICE_RE = re.compile(r"^\d{1,3}(?:,\d{3})*$")
SIZE_RE = re.compile(
    r"(?:\s+|^)(\d+(?:\.\d+)?\s*(?:mg|g|kg|ml|l|정|캡슐|연질캡슐|포|병|개|매|EA|ea|T|C|c|정제|캅셀|롤|스틱|박스|통|세트|입))$",
    re.IGNORECASE,
)


@dataclass
class Candidate:
    name: str
    specification: str
    category: str
    displayed_price_krw: int
    source_video: str
    source_second: float
    source_frame: int
    ocr_confidence: float
    first_seen_order: int
    observations: int = 1

    @property
    def normalized_name(self) -> str:
        return normalize(self.name)


def normalize(text: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", text.lower())


def clean_text(text: str) -> str:
    text = text.replace("|", "l").replace("㎖", "ml").strip()
    return re.sub(r"\s+", " ", text)


def split_specification(raw_name: str) -> tuple[str, str]:
    raw_name = clean_text(raw_name)
    match = SIZE_RE.search(raw_name)
    if not match:
        return raw_name, ""
    spec = clean_text(match.group(1))
    name = raw_name[: match.start()].strip()
    return name or raw_name, spec


def result_payload(result: Any) -> dict[str, Any]:
    payload = result.json
    if callable(payload):
        payload = payload()
    return payload.get("res", payload)


def extract_candidates(
    payload: dict[str, Any],
    *,
    source_video: str,
    source_second: float,
    source_frame: int,
    order_start: int,
) -> list[Candidate]:
    texts = payload.get("rec_texts", [])
    scores = payload.get("rec_scores", [])
    boxes = payload.get("rec_boxes", [])
    lines: list[dict[str, Any]] = []

    for text, score, box in zip(texts, scores, boxes):
        text = clean_text(str(text))
        if not text or float(score) < 0.45:
            continue
        x1, y1, x2, y2 = [int(v) for v in box]
        lines.append(
            {
                "text": text,
                "score": float(score),
                "x1": x1,
                "x2": x2,
                "cy": (y1 + y2) / 2,
            }
        )

    prices = []
    for line in lines:
        compact = line["text"].replace(" ", "")
        if line["x1"] < 750 or not PRICE_RE.fullmatch(compact):
            continue
        value = int(compact.replace(",", ""))
        if 100 <= value <= 10_000_000:
            prices.append((line, value))

    found: list[Candidate] = []
    for price_line, price_value in sorted(prices, key=lambda item: item[0]["cy"]):
        same_row = [
            line
            for line in lines
            if line["x1"] < 760
            and abs(line["cy"] - price_line["cy"]) <= 52
            and line["text"] not in {"검색", "초기화"}
        ]
        if not same_row:
            continue
        same_row.sort(key=lambda line: line["x1"])
        raw_name = clean_text(" ".join(line["text"] for line in same_row))
        name, specification = split_specification(raw_name)
        if len(normalize(name)) < 2 or not re.search(r"[A-Za-z가-힣]", name):
            continue

        category_lines = [
            line
            for line in lines
            if line["x1"] < 420
            and 42 <= line["cy"] - price_line["cy"] <= 118
            and len(line["text"]) <= 16
        ]
        category_lines.sort(key=lambda line: (abs((price_line["cy"] + 78) - line["cy"]), line["x1"]))
        category = category_lines[0]["text"] if category_lines else "미분류"
        confidence_values = [price_line["score"], *[line["score"] for line in same_row]]
        if category_lines:
            confidence_values.append(category_lines[0]["score"])

        found.append(
            Candidate(
                name=name,
                specification=specification,
                category=category,
                displayed_price_krw=price_value,
                source_video=source_video,
                source_second=round(source_second, 2),
                source_frame=source_frame,
                ocr_confidence=round(sum(confidence_values) / len(confidence_values), 4),
                first_seen_order=order_start + len(found),
            )
        )
    return found


def is_same_product(left: Candidate, right: Candidate) -> bool:
    if left.source_frame == right.source_frame:
        return False
    if left.displayed_price_krw != right.displayed_price_krw:
        return False
    if abs(left.source_second - right.source_second) > 12:
        return False
    left_name = normalize(left.name + left.specification)
    right_name = normalize(right.name + right.specification)
    if left_name == right_name:
        return True
    if min(len(left_name), len(right_name)) < 4:
        return False
    return ratio(left_name, right_name) >= 88


def merge_candidates(catalog: list[Candidate], incoming: Candidate) -> None:
    for existing in reversed(catalog[-24:]):
        if not is_same_product(existing, incoming):
            continue
        existing.observations += 1
        if incoming.ocr_confidence > existing.ocr_confidence or len(incoming.name) > len(existing.name):
            observations = existing.observations
            order = existing.first_seen_order
            existing.__dict__.update(incoming.__dict__)
            existing.observations = observations
            existing.first_seen_order = order
        return
    catalog.append(incoming)


def write_outputs(output_dir: Path, catalog: list[Candidate], metadata: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for index, item in enumerate(catalog, start=1):
        record = asdict(item)
        record["id"] = f"product-{index:04d}"
        record["normalized_name"] = item.normalized_name
        record["price_status"] = "녹화 당시 앱 표시값"
        record["verification_status"] = "OCR 추출·검수 필요"
        record["image_url"] = ""
        record["image_source_url"] = ""
        record["image_rights_status"] = "미확인"
        records.append(record)

    (output_dir / "products.raw.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "source-manifest.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if records:
        with (output_dir / "products.raw.csv").open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(records[0].keys()))
            writer.writeheader()
            writer.writerows(records)


def main() -> int:
    parser = argparse.ArgumentParser(description="화면 녹화에서 상품명·규격·분류·표시 가격을 추출합니다.")
    parser.add_argument("video", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data"))
    parser.add_argument("--interval", type=float, default=0.75)
    parser.add_argument("--scale", type=float, default=0.6)
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--end", type=float, default=None)
    args = parser.parse_args()

    if not args.video.exists():
        parser.error(f"영상 파일을 찾을 수 없습니다: {args.video}")

    capture = cv2.VideoCapture(str(args.video))
    fps = capture.get(cv2.CAP_PROP_FPS)
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frame_count / fps if fps else 0
    end_second = min(args.end or duration, duration)
    sample_count = max(0, int((end_second - args.start) / args.interval) + 1)

    print(f"영상: {args.video.name}")
    print(f"길이: {duration:.2f}초, OCR 표본: {sample_count}장", flush=True)
    ocr = PaddleOCR(
        lang="korean",
        text_detection_model_name="PP-OCRv5_mobile_det",
        text_recognition_model_name="korean_PP-OCRv5_mobile_rec",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        enable_mkldnn=False,
    )

    catalog: list[Candidate] = []
    raw_dir = args.output.parent / "etc" / "ocr"
    raw_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = raw_dir / "checkpoint.json"
    started_at = time.time()

    for sample_index in range(sample_count):
        second = args.start + sample_index * args.interval
        if second > end_second:
            break
        frame_number = int(round(second * fps))
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ok, frame = capture.read()
        if not ok:
            continue
        height = frame.shape[0]
        crop = frame[int(height * 0.235) : int(height * 0.94), :]
        if args.scale != 1:
            crop = cv2.resize(crop, None, fx=args.scale, fy=args.scale, interpolation=cv2.INTER_AREA)
        result = ocr.predict(crop)[0]
        payload = result_payload(result)
        if args.scale != 1:
            payload["rec_boxes"] = [
                [round(value / args.scale) for value in box] for box in payload.get("rec_boxes", [])
            ]
        found = extract_candidates(
            payload,
            source_video=args.video.name,
            source_second=second,
            source_frame=frame_number,
            order_start=len(catalog),
        )
        for candidate in found:
            merge_candidates(catalog, candidate)

        if sample_index % 10 == 0 or sample_index + 1 == sample_count:
            elapsed = time.time() - started_at
            print(
                f"{sample_index + 1}/{sample_count} 표본 · {len(catalog)}개 후보 · {elapsed:.0f}초",
                flush=True,
            )
            checkpoint.write_text(
                json.dumps([asdict(item) for item in catalog], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    capture.release()
    metadata = {
        "source_file": args.video.name,
        "source_path_not_published": True,
        "duration_seconds": round(duration, 3),
        "sample_interval_seconds": args.interval,
        "ocr_scale": args.scale,
        "sample_count": sample_count,
        "extracted_fields": ["상품명", "규격", "분류", "앱 표시 가격"],
        "price_notice": "가격은 녹화 당시 앱에 표시된 참고값이며 현재 판매가나 재고를 뜻하지 않습니다.",
        "raw_screen_images_published": False,
    }
    write_outputs(args.output, catalog, metadata)
    print(f"완료: {len(catalog)}개 후보", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
