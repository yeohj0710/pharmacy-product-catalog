from __future__ import annotations

import argparse
import html
import http.cookiejar
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener

from collect_kpic_images import normalize, score_name


BASE_URL = "https://health.kr"
DETAIL_URL = f"{BASE_URL}/searchDrug/result_drug.asp"
AJAX_URL = f"{BASE_URL}/searchDrug/ajax/ajax_result_drug2.asp"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0 Safari/537.36"
)
PART_START = 0
PART_END_EXCLUSIVE = 259
REQUIRED_DOM_IDS = (
    "drug_form",
    "dosage_route",
    "drug_box",
    "stmt",
    "effect",
    "dosage",
    "caution",
    "tab_effect",
    "tab_dosage",
    "tab_caution",
)
DOSAGE_FORMS = (
    "연질캡슐",
    "경질캡슐",
    "구강붕해필름",
    "현탁용분말",
    "현탁액",
    "내복액",
    "점안액",
    "외용액",
    "장용정",
    "필름코팅정",
    "캡슐",
    "시럽",
    "과립",
    "산제",
    "연고",
    "크림",
    "로션",
    "겔",
    "액",
    "정",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


def load_json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def clean_rich_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"(?i)brbr", "\n", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</?p(?:\s+[^>]*)?>", "\n", text)
    text = re.sub(r"(?i)</?(?:div|li|tr)(?:\s+[^>]*)?>", "\n", text)
    text = re.sub(r"(?i)</?(?:td|th)(?:\s+[^>]*)?>", " ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\xa0", " ").replace("\u3000", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def parse_html_field(document: str, element_id: str) -> str:
    match = re.search(
        rf"<(?:p|div)\b[^>]*\bid=[\"']{re.escape(element_id)}[\"'][^>]*>([\s\S]*?)</(?:p|div)>",
        document,
        re.I,
    )
    return clean_rich_text(match.group(1)) if match else ""


def parse_ingredients(value: Any) -> tuple[list[str], list[dict[str, str]]]:
    raw = str(value or "")
    details: list[dict[str, str]] = []
    for href, label in re.findall(
        r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>([\s\S]*?)</a>", raw, re.I
    ):
        cleaned = clean_rich_text(label)
        code_match = re.search(r"ingd_code=([^&\"']+)", href)
        details.append(
            {
                "label": cleaned,
                "ingredient_code": code_match.group(1) if code_match else "",
                "source_url": f"{BASE_URL}{href}" if href.startswith("/") else href,
            }
        )
    if details:
        return [row["label"] for row in details if row["label"]], details
    ingredients = [clean_rich_text(part) for part in re.split(r"@\||\|", raw)]
    return [part for part in ingredients if part], []


def image_urls(value: Any) -> list[str]:
    output: list[str] = []
    for candidate in re.split(r"[|@]", str(value or "")):
        url = html.unescape(candidate).strip()
        try:
            parsed = urlparse(url)
        except ValueError:
            continue
        if (
            parsed.scheme == "https"
            and parsed.hostname in {"common.health.kr", "health.kr", "www.health.kr"}
            and "img_empty" not in parsed.path
            and any(
                marker in parsed.path
                for marker in ("/pack_img/", "/sb_photo/", "/drug_info/", "/daily_img/")
            )
        ):
            output.append(url)
    return list(dict.fromkeys(output))


def find_form(name: str) -> str:
    normalized = normalize(name)
    for dosage_form in DOSAGE_FORMS:
        if dosage_form in normalized:
            return dosage_form
    return ""


def forms_conflict(catalog_name: str, kpic_name: str) -> bool:
    catalog_form = find_form(catalog_name)
    kpic_form = find_form(kpic_name)
    if not catalog_form or not kpic_form:
        return False
    solid = {"정", "장용정", "필름코팅정"}
    capsules = {"캡슐", "경질캡슐", "연질캡슐"}
    if catalog_form in solid and kpic_form in solid:
        return False
    if catalog_form in capsules and kpic_form in capsules:
        return False
    return catalog_form != kpic_form


class RateLimitedClient:
    def __init__(self, delay: float, timeout: float, retries: int) -> None:
        self.delay = max(delay, 0.75)
        self.timeout = timeout
        self.retries = max(retries, 1)
        self.last_request_at = 0.0
        self.opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def get_text(self, url: str, referer: str) -> str:
        last_error: Exception | None = None
        for attempt in range(self.retries):
            elapsed = time.monotonic() - self.last_request_at
            if self.last_request_at and elapsed < self.delay:
                time.sleep(self.delay - elapsed)
            request = Request(
                url,
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
                    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
                    "Referer": referer,
                    "User-Agent": USER_AGENT,
                },
            )
            try:
                self.last_request_at = time.monotonic()
                with self.opener.open(request, timeout=self.timeout) as response:
                    return response.read().decode("utf-8", errors="replace")
            except (HTTPError, URLError, TimeoutError) as exc:
                last_error = exc
                if attempt + 1 < self.retries:
                    time.sleep(2**attempt)
        raise RuntimeError(f"약학정보원 요청 실패: {type(last_error).__name__}") from last_error


def duplicate_code_conflicts(all_matches: list[dict[str, Any]]) -> set[str]:
    by_code: dict[str, list[str]] = {}
    for row in all_matches:
        code = str(row.get("kpic_code") or "")
        if not code:
            continue
        name = str(row.get("catalog_name") or "")
        if name and name not in by_code.setdefault(code, []):
            by_code[code].append(name)
    conflicts: set[str] = set()
    for code, names in by_code.items():
        if len(names) <= 1:
            continue
        if any(score_name(left, right) < 96 for index, left in enumerate(names) for right in names[index + 1 :]):
            conflicts.add(code)
    return conflicts


def preliminary_review_reason(
    row: dict[str, Any], new_score: int, conflicting_codes: set[str]
) -> str:
    catalog_name = str(row.get("catalog_name") or "")
    kpic_name = str(row.get("kpic_name") or "")
    code = str(row.get("kpic_code") or "")
    if row.get("status") == "review_required":
        return "기존 자동 매칭이 검토 대상으로 분류됨"
    if new_score < 96:
        return "새 이름 점수가 96점 미만"
    if code in conflicting_codes:
        return "서로 다른 상품명이 동일한 약학정보원 코드에 매칭됨"
    if forms_conflict(catalog_name, kpic_name):
        return "카탈로그 상품명과 약학정보원 제품명의 제형이 다름"
    if "수출용" in kpic_name and "수출용" not in catalog_name:
        return "약학정보원 제품명에만 수출용 표기가 있음"
    return ""


def build_content(payload: dict[str, Any], document: str) -> dict[str, Any]:
    ingredients, ingredient_details = parse_ingredients(payload.get("sunb"))
    pack_urls = image_urls(payload.get("pack_img"))
    all_drug_urls = image_urls(payload.get("drug_pic"))
    pack_urls = list(
        dict.fromkeys(pack_urls + [url for url in all_drug_urls if "/pack_img/" in url])
    )
    identification_urls = [url for url in all_drug_urls if url not in pack_urls]
    primary_url = pack_urls[0] if pack_urls else (identification_urls[0] if identification_urls else "")
    html_effect = parse_html_field(document, "effect")
    html_dosage = parse_html_field(document, "dosage")
    html_caution = parse_html_field(document, "caution")
    manufacturer_parts = [part.strip() for part in str(payload.get("upso_name") or "").split("|")]
    while len(manufacturer_parts) < 6:
        manufacturer_parts.append("")
    return {
        "ingredients": ingredients,
        "efficacy": html_effect or clean_rich_text(payload.get("effect")),
        "dosage": html_dosage or clean_rich_text(payload.get("dosage")),
        "precautions": html_caution or clean_rich_text(payload.get("caution")),
        "storage": clean_rich_text(payload.get("stmt")),
        "manufacturer": manufacturer_parts[0],
        "dosage_form": clean_rich_text(payload.get("drug_form")),
        "route": clean_rich_text(payload.get("dosage_route")),
        "package": clean_rich_text(payload.get("drug_box")),
        "images": {
            "primary_url": primary_url,
            "primary_type": "package" if pack_urls else ("identification" if primary_url else ""),
            "pack_urls": pack_urls,
            "identification_urls": identification_urls,
        },
        "additional": {
            "english_name": clean_rich_text(payload.get("drug_enm")),
            "insurance": clean_rich_text(payload.get("boh")),
            "insurance_detail": clean_rich_text(payload.get("noins")),
            "classification": clean_rich_text(payload.get("cls_code")),
            "classification_code": clean_rich_text(payload.get("cls_code_num")),
            "appearance": clean_rich_text(payload.get("charact_new") or payload.get("charact")),
            "permit_date": clean_rich_text(payload.get("item_permit_date")),
            "atc": clean_rich_text(payload.get("atc_cd")),
            "kpic_atc": clean_rich_text(payload.get("kpic_atc")),
            "additives": clean_rich_text(payload.get("additives")),
            "medication_summary": clean_rich_text(payload.get("medititle")),
            "medication_guide": clean_rich_text(payload.get("mediguide")),
            "identification": clean_rich_text(payload.get("idfylength")),
            "dur_age": clean_rich_text(payload.get("dur_age")),
            "dur_contraindications": clean_rich_text(payload.get("dur_contra")),
            "dur_pregnancy": clean_rich_text(payload.get("dur_preg")),
            "dur_senior": clean_rich_text(payload.get("dur_senior")),
            "dur_max_dose": clean_rich_text(payload.get("dur_dose")),
            "dur_max_period": clean_rich_text(payload.get("dur_period")),
            "dur_split_dosage": clean_rich_text(payload.get("dur_form")),
            "manufacturer_details": {
                "name": manufacturer_parts[0],
                "english_name": manufacturer_parts[1],
                "address": manufacturer_parts[2],
                "phone": manufacturer_parts[3],
                "fax": manufacturer_parts[4],
                "website": manufacturer_parts[5],
            },
            "ingredient_details": ingredient_details,
        },
    }


def detail_record(
    row: dict[str, Any], client: RateLimitedClient, new_score: int
) -> dict[str, Any]:
    code = str(row.get("kpic_code") or "")
    source_url = f"{DETAIL_URL}?drug_cd={quote(code)}"
    document = client.get_text(source_url, DETAIL_URL)
    ajax_url = f"{AJAX_URL}?drug_cd={quote(code)}"
    ajax_text = client.get_text(ajax_url, source_url)
    payload_json = json.loads(ajax_text)
    payload = payload_json[0] if isinstance(payload_json, list) and payload_json else {}
    if not isinstance(payload, dict) or not payload:
        raise RuntimeError("약학정보원 상세 JSON이 비어 있음")

    hidden_code = re.search(
        r"id=[\"']drug_code_hidden[\"'][^>]*value=[\"']([^\"']+)", document, re.I
    )
    endpoint_match = re.search(r"ajax_result_drug2\.asp\?drug_cd=([^'\"&]+)", document, re.I)
    payload_code = str(payload.get("drug_code") or "")
    verified = (
        hidden_code is not None
        and hidden_code.group(1) == code
        and endpoint_match is not None
        and endpoint_match.group(1) == code
    )
    ajax_verified = payload_code == code
    official_name = str(payload.get("drug_name") or row.get("kpic_name") or "")
    if not verified or not ajax_verified:
        raise RuntimeError("상세 페이지 또는 JSON의 제품 코드가 요청 코드와 다름")
    if score_name(str(row.get("kpic_name") or ""), official_name) < 96:
        raise RuntimeError("검색 결과 제품명과 상세 JSON 제품명이 다름")

    content = build_content(payload, document)
    present_dom_ids = [
        element_id
        for element_id in REQUIRED_DOM_IDS
        if re.search(rf"\bid=[\"']{re.escape(element_id)}[\"']", document, re.I)
    ]
    required_present = {
        field: bool(content.get(field))
        for field in (
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
    }
    required_present["images"] = bool(content["images"]["primary_url"])
    return {
        "catalog_product_id": str(row.get("catalog_product_id") or ""),
        "catalog_name": str(row.get("catalog_name") or ""),
        "kpic_code": code,
        "kpic_name": official_name,
        "status": "collected",
        "match_score": new_score,
        "content": content,
        "source_url": source_url,
        "ajax_source_url": ajax_url,
        "section_evidence": {
            "detail_page_verified": verified,
            "ajax_payload_verified": ajax_verified,
            "required_dom_ids": present_dom_ids,
            "required_fields_present": required_present,
            "html_text_fields": [
                field
                for field, element_id in (
                    ("efficacy", "effect"),
                    ("dosage", "dosage"),
                    ("precautions", "caution"),
                )
                if parse_html_field(document, element_id)
            ],
        },
        "collected_at": now_iso(),
        "error": "",
    }


def review_record(row: dict[str, Any], new_score: int, reason: str) -> dict[str, Any]:
    return {
        "catalog_product_id": str(row.get("catalog_product_id") or ""),
        "catalog_name": str(row.get("catalog_name") or ""),
        "kpic_code": str(row.get("kpic_code") or ""),
        "kpic_name": str(row.get("kpic_name") or ""),
        "status": "review_required",
        "match_score": new_score,
        "content": {},
        "source_url": str(row.get("source_url") or ""),
        "ajax_source_url": "",
        "section_evidence": {},
        "collected_at": "",
        "error": reason,
    }


def make_summary(
    input_count: int, eligible_count: int, records: list[dict[str, Any]], started_at: str
) -> dict[str, Any]:
    collected = [row for row in records if row.get("status") == "collected"]
    review = [row for row in records if row.get("status") == "review_required"]
    failed = [row for row in records if row.get("status") == "error"]
    fields = (
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
    denominator = len(collected) or 1
    field_counts = {
        field: sum(bool(row.get("content", {}).get(field)) for row in collected) for field in fields
    }
    image_count = sum(
        bool(row.get("content", {}).get("images", {}).get("primary_url")) for row in collected
    )
    return {
        "generated_at": now_iso(),
        "started_at": started_at,
        "part": 1,
        "range": {"start_index": PART_START, "end_index_inclusive": PART_END_EXCLUSIVE - 1},
        "input_count": input_count,
        "eligible_count": eligible_count,
        "record_count": len(records),
        "collected_count": len(collected),
        "review_required_count": len(review),
        "error_count": len(failed),
        "field_counts": field_counts,
        "field_fill_rates": {
            field: round(count / denominator, 4) for field, count in field_counts.items()
        },
        "image_count": image_count,
        "image_fill_rate": round(image_count / denominator, 4),
        "detail_page_verified_count": sum(
            bool(row.get("section_evidence", {}).get("detail_page_verified")) for row in collected
        ),
        "source": "약학정보원 의약품 상세정보",
        "request_delay_seconds": 0.75,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matches", type=Path, default=Path("data/kpic-image-matches.json"))
    parser.add_argument("--output", type=Path, default=Path("data/kpic-details-part-1.json"))
    parser.add_argument(
        "--summary", type=Path, default=Path("data/kpic-details-part-1-summary.json")
    )
    parser.add_argument("--delay", type=float, default=0.8)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--checkpoint-every", type=int, default=10)
    args = parser.parse_args()

    started_at = now_iso()
    all_matches: list[dict[str, Any]] = load_json(args.matches, [])
    part = all_matches[PART_START:PART_END_EXCLUSIVE]
    conflicting_codes = duplicate_code_conflicts(all_matches)
    candidates: list[tuple[dict[str, Any], int]] = []
    for row in part:
        code = str(row.get("kpic_code") or "")
        new_score = score_name(str(row.get("catalog_name") or ""), str(row.get("kpic_name") or ""))
        if code and new_score >= 96:
            candidates.append((row, new_score))

    existing: list[dict[str, Any]] = load_json(args.output, [])
    records_by_id = {
        str(row.get("catalog_product_id") or ""): row
        for row in existing
        if row.get("catalog_product_id")
    }
    client = RateLimitedClient(args.delay, args.timeout, args.retries)
    processed_in_run = 0

    def checkpoint() -> None:
        ordered = [
            records_by_id[str(row.get("catalog_product_id") or "")]
            for row, _score in candidates
            if str(row.get("catalog_product_id") or "") in records_by_id
        ]
        write_json_atomic(args.output, ordered)
        write_json_atomic(args.summary, make_summary(len(part), len(candidates), ordered, started_at))

    for row, new_score in candidates:
        product_id = str(row.get("catalog_product_id") or "")
        prior = records_by_id.get(product_id)
        review_reason = preliminary_review_reason(row, new_score, conflicting_codes)
        if prior and prior.get("status") == "collected":
            continue
        if prior and prior.get("status") == "review_required" and review_reason:
            continue
        if review_reason:
            records_by_id[product_id] = review_record(row, new_score, review_reason)
            processed_in_run += 1
            continue
        try:
            records_by_id[product_id] = detail_record(row, client, new_score)
        except (RuntimeError, json.JSONDecodeError) as exc:
            records_by_id[product_id] = {
                **review_record(row, new_score, ""),
                "status": "error",
                "error": str(exc),
            }
        processed_in_run += 1
        if processed_in_run % args.checkpoint_every == 0:
            checkpoint()
            print(
                json.dumps(
                    {"processed_in_run": processed_in_run, "eligible": len(candidates)},
                    ensure_ascii=False,
                ),
                flush=True,
            )

    checkpoint()
    summary = load_json(args.summary, {})
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
