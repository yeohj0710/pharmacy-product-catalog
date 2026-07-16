from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.collect_kpic_images import safe_name_match, validated_match_score


BASE_URL = "https://health.kr"
DETAIL_URL = f"{BASE_URL}/searchDrug/result_drug.asp?drug_cd={{code}}"
AJAX_URL = f"{BASE_URL}/searchDrug/ajax/ajax_result_drug2.asp?drug_cd={{code}}"
DEFAULT_INPUT = Path("data/kpic-image-matches.json")
DEFAULT_OUTPUT = Path("data/kpic-details-part-3.json")
DEFAULT_SUMMARY = Path("data/kpic-details-part-3-summary.json")
SEGMENT_START = 518
SEGMENT_END = 776
MIN_SCORE = 96
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0 Safari/537.36"
)
REQUIRED_DOM_IDS = ("effect", "dosage", "caution")
REQUIRED_CONTENT_FIELDS = (
    "ingredients",
    "efficacy",
    "dosage",
    "precautions",
    "storage",
    "manufacturer",
    "dosage_form",
    "route",
    "package",
)
def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


def normalize(value: Any) -> str:
    text = html.unescape(str(value or "")).lower()
    for before, after in {"현탄액": "현탁액", "씨럽": "시럽", "캅셀": "캡슐"}.items():
        text = text.replace(before, after)
    text = re.sub(r"\([^)]*\)", "", text)
    return re.sub(r"[^0-9a-z가-힣]", "", text)


def score_name(left: str, right: str) -> int:
    a, b = normalize(left), normalize(right)
    if not a or not b:
        return 0
    if a == b:
        return 100
    ratio = round(SequenceMatcher(None, a, b).ratio() * 100)
    if min(len(a), len(b)) >= 4 and (a in b or b in a):
        ratio = max(ratio, 96)
    left_tokens = [normalize(token) for token in re.findall(r"[0-9a-zA-Z가-힣]+", left)]
    right_tokens = [normalize(token) for token in re.findall(r"[0-9a-zA-Z가-힣]+", right)]
    generic_tokens = {
        "식물성", "플러스", "프리미엄", "어린이", "에어로졸", "점안액", "현탁액",
        "내복액", "캡슐", "연고", "크림", "시럽", "과립", "드링크", "구강붕해필름",
        "비타민", "종합감기약", "건강보조식품",
    }
    distinctive = [
        token
        for token in left_tokens + right_tokens
        if len(token) >= 4 and token not in generic_tokens
    ]
    if any(
        token in a and token in b and len(token) / min(len(a), len(b)) >= 0.55
        for token in distinctive
    ):
        ratio = max(ratio, 96)
    return ratio


def clean_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"(?i)brbr", "\n", text)
    text = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", text)
    text = re.sub(r"(?i)</?\s*p\s*>", "\n", text)
    text = re.sub(r"(?i)</?\s*div\b[^>]*>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\u3000", " ").replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def split_urls(value: Any, separator: str) -> list[str]:
    return unique(
        part.strip()
        for part in str(value or "").split(separator)
        if part.strip().startswith("https://") and "img_empty" not in part
    )


def ingredient_list(detail: dict[str, Any]) -> list[str]:
    rich = str(detail.get("sunb") or "")
    values = [clean_text(item) for item in rich.split("@")]
    values = [value for value in values if value]
    if values:
        return unique(values)
    plain = clean_text(detail.get("list_sunb_name"))
    return [plain] if plain else []


def manufacturer_name(value: Any) -> str:
    return clean_text(str(value or "").split("|", 1)[0])


def image_content(detail: dict[str, Any]) -> dict[str, Any]:
    pack_urls = split_urls(detail.get("pack_img"), "@")
    drug_pic = split_urls(detail.get("drug_pic"), "|")
    pack_urls = unique(pack_urls + [url for url in drug_pic if "/pack_img/" in url])
    identification_urls = unique([url for url in drug_pic if url not in pack_urls])
    if pack_urls:
        primary_url, primary_type = pack_urls[0], "package"
    elif identification_urls:
        primary_url, primary_type = identification_urls[0], "identification"
    else:
        primary_url, primary_type = "", ""
    return {
        "primary_url": primary_url,
        "primary_type": primary_type,
        "pack_urls": pack_urls,
        "identification_urls": identification_urls,
    }


def detail_content(detail: dict[str, Any]) -> dict[str, Any]:
    insert_pdf = str(detail.get("insertpaper") or "").strip()
    if insert_pdf.startswith("/"):
        insert_pdf = f"{BASE_URL}{insert_pdf}"
    return {
        "ingredients": ingredient_list(detail),
        "efficacy": clean_text(detail.get("effect")),
        "dosage": clean_text(detail.get("dosage")),
        "precautions": clean_text(detail.get("caution")),
        "storage": clean_text(detail.get("stmt")),
        "manufacturer": manufacturer_name(detail.get("upso_name") or detail.get("upso1")),
        "dosage_form": clean_text(detail.get("drug_form")),
        "route": clean_text(detail.get("dosage_route")),
        "package": clean_text(detail.get("drug_box")),
        "images": image_content(detail),
        "characteristics": clean_text(detail.get("charact_new") or detail.get("charact")),
        "medicine_summary": clean_text(detail.get("medititle")),
        "patient_guidance": clean_text(detail.get("mediguide")),
        "additives": [
            value
            for value in (clean_text(part) for part in re.split(r"(?i)</?br\s*/?>", str(detail.get("additives") or "")))
            if value
        ],
        "classification": clean_text(detail.get("cls_code")),
        "classification_code": clean_text(detail.get("cls_code_num")),
        "atc": clean_text(detail.get("atc_cd")),
        "kpic_atc": clean_text(detail.get("kpic_atc")),
        "insurance": clean_text(detail.get("boh")),
        "permit_date": clean_text(detail.get("item_permit_date")),
        "insert_pdf_url": insert_pdf,
    }


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


class RateLimitedClient:
    def __init__(self, delay: float, timeout: float, retries: int) -> None:
        self.delay = max(delay, 0.75)
        self.timeout = timeout
        self.retries = max(retries, 1)
        self.last_request_at = 0.0

    def get_text(self, url: str, *, referer: str = BASE_URL) -> str:
        last_error: Exception | None = None
        for attempt in range(self.retries):
            elapsed = time.monotonic() - self.last_request_at
            if self.last_request_at and elapsed < self.delay:
                time.sleep(self.delay - elapsed)
            request = Request(
                url,
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
                    "Referer": referer,
                    "User-Agent": USER_AGENT,
                },
            )
            try:
                self.last_request_at = time.monotonic()
                with urlopen(request, timeout=self.timeout) as response:
                    return response.read().decode("utf-8", errors="replace")
            except (HTTPError, URLError, TimeoutError) as exc:
                last_error = exc
                if attempt + 1 < self.retries:
                    time.sleep(2**attempt)
        raise RuntimeError(f"request_failed:{type(last_error).__name__}") from last_error


def verify_detail_page(document: str) -> tuple[bool, list[str]]:
    required_dom_ids = [
        dom_id
        for dom_id in REQUIRED_DOM_IDS
        if re.search(rf"\bid=[\"']{re.escape(dom_id)}[\"']", document, re.I)
    ]
    endpoint_present = "ajax_result_drug2.asp" in document
    headings_present = all(label in document for label in ("효능 · 효과", "용법 · 용량", "주의사항"))
    return endpoint_present and headings_present and len(required_dom_ids) == len(REQUIRED_DOM_IDS), required_dom_ids


def summary_for(records: list[dict[str, Any]], total_segment: int, coded: int) -> dict[str, Any]:
    collected = [record for record in records if record.get("status") == "collected"]
    review = [record for record in records if record.get("status") == "review_required"]
    errors = [record for record in records if record.get("status") == "error"]
    field_counts = {
        field: sum(bool(record.get("content", {}).get(field)) for record in collected)
        for field in REQUIRED_CONTENT_FIELDS
    }
    image_count = sum(
        bool(record.get("content", {}).get("images", {}).get("primary_url"))
        for record in collected
    )
    denominator = len(collected) or 1
    return {
        "part": 3,
        "segment": {"start": SEGMENT_START, "end_exclusive": SEGMENT_END, "total": total_segment},
        "source_with_kpic_code": coded,
        "minimum_name_score": MIN_SCORE,
        "records": len(records),
        "collected": len(collected),
        "review_required": len(review),
        "errors": len(errors),
        "field_counts": field_counts,
        "field_coverage_percent": {
            field: round(count / denominator * 100, 1) for field, count in field_counts.items()
        },
        "primary_image_count": image_count,
        "primary_image_coverage_percent": round(image_count / denominator * 100, 1),
        "updated_at": now_iso(),
    }


def make_review_record(source: dict[str, Any], source_index: int, match_score: int, reason: str) -> dict[str, Any]:
    return {
        "source_index": source_index,
        "catalog_product_id": source.get("catalog_product_id", ""),
        "catalog_name": source.get("catalog_name", ""),
        "kpic_code": source.get("kpic_code", ""),
        "kpic_name": source.get("kpic_name", ""),
        "status": "review_required",
        "match_score": match_score,
        "content": {},
        "source_url": source.get("source_url") or DETAIL_URL.format(code=quote(str(source.get("kpic_code") or ""))),
        "section_evidence": {
            "detail_page_verified": False,
            "ajax_payload_verified": False,
            "required_dom_ids": [],
            "required_fields_present": [],
        },
        "review_reason": reason,
        "collected_at": now_iso(),
    }


def collect_one(client: RateLimitedClient, source: dict[str, Any], source_index: int) -> dict[str, Any]:
    catalog_name = str(source.get("catalog_name") or "")
    kpic_name = str(source.get("kpic_name") or "")
    code = str(source.get("kpic_code") or "")
    match_score = validated_match_score(catalog_name, kpic_name, source.get("catalog_capacity"))
    if match_score < MIN_SCORE:
        return make_review_record(source, source_index, match_score, "name_score_below_96")
    if source.get("status") != "confirmed":
        return make_review_record(source, source_index, match_score, "upstream_match_requires_review")
    if not safe_name_match(catalog_name, kpic_name, source.get("catalog_capacity")):
        return make_review_record(source, source_index, match_score, "name_or_dosage_conflict")

    source_url = DETAIL_URL.format(code=quote(code))
    document = client.get_text(source_url)
    page_verified, required_dom_ids = verify_detail_page(document)
    payload_text = client.get_text(AJAX_URL.format(code=quote(code)), referer=source_url)
    payload = json.loads(payload_text)
    detail = payload[0] if isinstance(payload, list) and payload and isinstance(payload[0], dict) else {}
    ajax_code = str(detail.get("drug_code") or "")
    ajax_name = str(detail.get("drug_name") or "")
    ajax_name_score = score_name(kpic_name, ajax_name)
    ajax_verified = (
        ajax_code == code
        and ajax_name_score >= MIN_SCORE
        and safe_name_match(catalog_name, ajax_name, source.get("catalog_capacity"))
    )
    if not page_verified or not ajax_verified:
        reason = "detail_page_structure_unverified" if not page_verified else "ajax_product_mismatch"
        record = make_review_record(source, source_index, match_score, reason)
        record["section_evidence"] = {
            "detail_page_verified": page_verified,
            "ajax_payload_verified": ajax_verified,
            "required_dom_ids": required_dom_ids,
            "required_fields_present": [],
        }
        record["ajax_product"] = {"code": ajax_code, "name": ajax_name, "name_score": ajax_name_score}
        return record

    content = detail_content(detail)
    present = [field for field in REQUIRED_CONTENT_FIELDS if content.get(field)]
    return {
        "source_index": source_index,
        "catalog_product_id": source.get("catalog_product_id", ""),
        "catalog_name": catalog_name,
        "kpic_code": code,
        "kpic_name": ajax_name or kpic_name,
        "status": "collected",
        "match_score": match_score,
        "content": content,
        "source_url": source_url,
        "section_evidence": {
            "detail_page_verified": page_verified,
            "ajax_payload_verified": ajax_verified,
            "required_dom_ids": required_dom_ids,
            "required_fields_present": present,
        },
        "collected_at": now_iso(),
    }


def can_reuse_record(source: dict[str, Any], previous: dict[str, Any]) -> bool:
    same_code = previous.get("kpic_code") == source.get("kpic_code")
    current_safe = (
        source.get("status") == "confirmed"
        and validated_match_score(
            source.get("catalog_name"), source.get("kpic_name"), source.get("catalog_capacity")
        )
        >= MIN_SCORE
        and safe_name_match(
            source.get("catalog_name"), source.get("kpic_name"), source.get("catalog_capacity")
        )
    )
    if previous.get("status") == "collected":
        return bool(same_code and current_safe)
    if previous.get("status") == "review_required":
        return bool(same_code and not current_safe)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="약학정보원 제품 상세정보 수집기: 3/3 구간")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--delay", type=float, default=0.8)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-errors", action="store_true")
    args = parser.parse_args()

    source_all = json.loads(args.input.read_text(encoding="utf-8"))
    segment = source_all[SEGMENT_START:SEGMENT_END]
    coded = [(SEGMENT_START + offset, row) for offset, row in enumerate(segment) if row.get("kpic_code")]
    existing = json.loads(args.output.read_text(encoding="utf-8")) if args.output.exists() else []
    by_id = {
        str(record.get("catalog_product_id") or ""): record
        for record in existing
        if record.get("catalog_product_id")
    }
    client = RateLimitedClient(args.delay, args.timeout, args.retries)

    for position, (source_index, source) in enumerate(coded, start=1):
        product_id = str(source.get("catalog_product_id") or "")
        previous = by_id.get(product_id)
        if previous and can_reuse_record(source, previous):
            continue
        if previous and previous.get("status") == "error" and not args.retry_errors:
            continue
        try:
            record = collect_one(client, source, source_index)
        except (RuntimeError, json.JSONDecodeError, ValueError) as exc:
            record = {
                "source_index": source_index,
                "catalog_product_id": source.get("catalog_product_id", ""),
                "catalog_name": source.get("catalog_name", ""),
                "kpic_code": source.get("kpic_code", ""),
                "kpic_name": source.get("kpic_name", ""),
                "status": "error",
                "match_score": validated_match_score(
                    source.get("catalog_name", ""),
                    source.get("kpic_name", ""),
                    source.get("catalog_capacity", ""),
                ),
                "content": {},
                "source_url": source.get("source_url", ""),
                "section_evidence": {
                    "detail_page_verified": False,
                    "ajax_payload_verified": False,
                    "required_dom_ids": [],
                    "required_fields_present": [],
                },
                "error": f"{type(exc).__name__}:{exc}",
                "collected_at": now_iso(),
            }
        by_id[product_id] = record
        records = sorted(by_id.values(), key=lambda item: int(item.get("source_index") or 0))
        write_json_atomic(args.output, records)
        write_json_atomic(args.summary, summary_for(records, len(segment), len(coded)))
        print(f"[{position}/{len(coded)}] index={source_index} status={record['status']}", flush=True)

    records = sorted(by_id.values(), key=lambda item: int(item.get("source_index") or 0))
    write_json_atomic(args.output, records)
    summary = summary_for(records, len(segment), len(coded))
    write_json_atomic(args.summary, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
