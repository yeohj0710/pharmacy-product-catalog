from __future__ import annotations

import argparse
import copy
import html
import json
import re
import time
from collections import Counter
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests


BASE_URL = "https://health.kr"
DETAIL_URL = f"{BASE_URL}/searchDrug/result_drug.asp"
AJAX_URL = f"{BASE_URL}/searchDrug/ajax/ajax_result_drug2.asp"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0 Safari/537.36"
)
EXPECTED_DOM_IDS = (
    "ingr_mg",
    "upso_title",
    "drug_form",
    "dosage_route",
    "drug_box",
    "stmt",
    "effect",
    "dosage",
    "caution",
)
CONTENT_FIELDS = (
    "ingredients",
    "efficacy",
    "dosage",
    "precautions",
    "storage",
    "manufacturer",
    "dosage_form",
    "route",
    "package",
    "images",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def normalize_name(value: Any) -> str:
    text = html.unescape(str(value or "")).lower()
    text = re.sub(r"\([^)]*\)", "", text)
    return re.sub(r"[^0-9a-z가-힣]", "", text)


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"br", "p", "li", "div", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"p", "li", "div", "tr"}:
            self.parts.append("\n")

    def text(self) -> str:
        return "".join(self.parts)


class SectionExtractor(HTMLParser):
    def __init__(self, target_ids: tuple[str, ...]) -> None:
        super().__init__(convert_charrefs=True)
        self.targets = set(target_ids)
        self.sections: dict[str, list[str]] = {}
        self.active: list[tuple[str, int]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        element_id = attrs_dict.get("id")
        if element_id in self.targets:
            self.sections.setdefault(str(element_id), [])
            self.active.append((str(element_id), 1))
            return
        if self.active:
            element_id, depth = self.active[-1]
            self.active[-1] = (element_id, depth + 1)
            if tag.lower() in {"br", "p", "li", "div", "tr"}:
                self.sections[element_id].append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.active and tag.lower() == "br":
            self.sections[self.active[-1][0]].append("\n")

    def handle_endtag(self, tag: str) -> None:
        if not self.active:
            return
        element_id, depth = self.active[-1]
        if tag.lower() in {"p", "li", "div", "tr"}:
            self.sections[element_id].append("\n")
        depth -= 1
        if depth <= 0:
            self.active.pop()
        else:
            self.active[-1] = (element_id, depth)

    def handle_data(self, data: str) -> None:
        if self.active:
            self.sections[self.active[-1][0]].append(data)


def clean_text(value: Any) -> str:
    raw = html.unescape(str(value or ""))
    raw = re.sub(r"(?i)brbr", "\n\n", raw)
    raw = re.sub(r"(?i)<br\s*/?>", "\n", raw)
    parser = TextExtractor()
    try:
        parser.feed(raw)
        raw = parser.text()
    except Exception:
        raw = re.sub(r"<[^>]+>", " ", raw)
    lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in raw.splitlines()]
    output: list[str] = []
    for line in lines:
        if line:
            output.append(line)
        elif output and output[-1] != "":
            output.append("")
    return "\n".join(output).strip()


def parse_page_sections(document: str) -> tuple[dict[str, str], list[str]]:
    parser = SectionExtractor(EXPECTED_DOM_IDS)
    parser.feed(document)
    sections = {
        key: clean_text("".join(value))
        for key, value in parser.sections.items()
    }
    found_ids = [element_id for element_id in EXPECTED_DOM_IDS if element_id in parser.sections]
    return sections, found_ids


def parse_ingredients(value: Any, fallback: Any = "") -> list[str]:
    raw = str(value or fallback or "")
    parts = [clean_text(part) for part in raw.split("@")]
    return list(dict.fromkeys(part for part in parts if part))


def split_urls(value: Any, separator: str) -> list[str]:
    urls: list[str] = []
    for part in str(value or "").replace("\r", "").replace("\n", "").split(separator):
        url = html.unescape(part).strip()
        if url.startswith("https://") and "health.kr/" in url and "img_empty" not in url:
            urls.append(url)
    return list(dict.fromkeys(urls))


def parse_images(detail: dict[str, Any]) -> dict[str, Any]:
    pack_urls = split_urls(detail.get("pack_img"), "@")
    drug_pic_urls = split_urls(detail.get("drug_pic"), "|")
    for url in drug_pic_urls:
        if "/pack_img/" in url and url not in pack_urls:
            pack_urls.append(url)
    identification_urls = [
        url
        for url in drug_pic_urls
        if url not in pack_urls and any(marker in url for marker in ("/sb_photo/", "/daily_img/", "/drug_info/"))
    ]
    if pack_urls:
        primary_url, primary_type = pack_urls[0], "package"
    elif identification_urls:
        primary_url, primary_type = identification_urls[0], "identification"
    else:
        primary_url, primary_type = "", "none"
    return {
        "primary_url": primary_url,
        "primary_type": primary_type,
        "pack_urls": pack_urls,
        "identification_urls": identification_urls,
    }


class KpicClient:
    def __init__(self, delay: float, timeout: float, retries: int) -> None:
        self.delay = max(delay, 0.75)
        self.timeout = timeout
        self.retries = max(retries, 1)
        self.last_request_at = 0.0
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.7,en;q=0.6",
                "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            }
        )

    def get(self, url: str, *, referer: str = BASE_URL) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(self.retries):
            elapsed = time.monotonic() - self.last_request_at
            if self.last_request_at and elapsed < self.delay:
                time.sleep(self.delay - elapsed)
            try:
                self.last_request_at = time.monotonic()
                response = self.session.get(
                    url,
                    headers={"Referer": referer},
                    timeout=self.timeout,
                )
                response.raise_for_status()
                return response
            except (requests.RequestException, TimeoutError) as exc:
                last_error = exc
                if attempt + 1 < self.retries:
                    time.sleep(2**attempt)
        raise RuntimeError(f"KPIC request failed: {type(last_error).__name__}: {last_error}") from last_error

    def collect_code(self, code: str) -> tuple[dict[str, Any], dict[str, Any]]:
        source_url = f"{DETAIL_URL}?drug_cd={quote(code)}"
        detail_response = self.get(source_url)
        detail_response.encoding = "utf-8"
        page_sections, found_ids = parse_page_sections(detail_response.text)

        ajax_source_url = f"{AJAX_URL}?drug_cd={quote(code)}"
        ajax_response = self.get(ajax_source_url, referer=source_url)
        payload = ajax_response.json()
        if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
            raise RuntimeError("KPIC AJAX payload did not contain a product object")
        detail = payload[0]
        if str(detail.get("drug_code") or "") != code:
            raise RuntimeError("KPIC AJAX product code did not match the requested code")

        content = {
            "ingredients": parse_ingredients(detail.get("sunb"), detail.get("list_sunb_name")),
            "efficacy": clean_text(detail.get("effect") or page_sections.get("effect")),
            "dosage": clean_text(detail.get("dosage") or page_sections.get("dosage")),
            "precautions": clean_text(detail.get("caution") or page_sections.get("caution")),
            "storage": clean_text(detail.get("stmt") or page_sections.get("stmt")),
            "manufacturer": clean_text(str(detail.get("upso_name") or "").split("|")[0]),
            "dosage_form": clean_text(detail.get("drug_form") or page_sections.get("drug_form")),
            "route": clean_text(detail.get("dosage_route") or page_sections.get("dosage_route")),
            "package": clean_text(detail.get("drug_box") or page_sections.get("drug_box")),
            "images": parse_images(detail),
        }
        fields_present = [
            key
            for key in CONTENT_FIELDS
            if (
                content[key].get("primary_url")
                if key == "images"
                else bool(content[key])
            )
        ]
        evidence = {
            "detail_page_verified": len(found_ids) >= 6,
            "ajax_payload_verified": True,
            "required_dom_ids": found_ids,
            "required_fields_present": fields_present,
        }
        metadata = {
            "drug_name": clean_text(detail.get("drug_name")),
            "source_url": source_url,
            "section_evidence": evidence,
        }
        return content, metadata


def eligible(
    match: dict[str, Any],
    product: dict[str, Any],
    minimum_score: int,
) -> bool:
    score = max(int(match.get("suggestion_score") or 0), int(match.get("match_score") or 0))
    code = str(match.get("kpic_code") or "")
    return (
        bool(code)
        and score >= minimum_score
        and product.get("official_match_status") == "confirmed"
        and str(product.get("official_item_seq") or "") == code
        and bool(product.get("official_source_url"))
    )


def build_summary(
    records: list[dict[str, Any]],
    *,
    selected_count: int,
    eligible_count: int,
    unique_code_count: int,
    start: int,
    end: int,
    delay: float,
) -> dict[str, Any]:
    statuses = Counter(str(record.get("status") or "unknown") for record in records)
    collected = [record for record in records if record.get("status") == "collected"]
    field_counts: dict[str, int] = {}
    for key in CONTENT_FIELDS:
        if key == "images":
            field_counts[key] = sum(bool(record.get("content", {}).get(key, {}).get("primary_url")) for record in collected)
        else:
            field_counts[key] = sum(bool(record.get("content", {}).get(key)) for record in collected)
    denominator = len(collected) or 1
    return {
        "generated_at": now_iso(),
        "source": "약학정보원 의약품 상세정보",
        "range": {"start": start, "end_exclusive": end, "selected_count": selected_count},
        "minimum_name_score": 96,
        "request_delay_seconds": max(delay, 0.75),
        "eligible_count": eligible_count,
        "unique_kpic_code_count": unique_code_count,
        "record_count": len(records),
        "status_counts": dict(sorted(statuses.items())),
        "field_counts": field_counts,
        "field_rates_percent": {
            key: round(count / denominator * 100, 1)
            for key, count in field_counts.items()
        },
        "package_image_count": sum(
            bool(record.get("content", {}).get("images", {}).get("pack_urls"))
            for record in collected
        ),
        "identification_image_count": sum(
            bool(record.get("content", {}).get("images", {}).get("identification_urls"))
            for record in collected
        ),
        "missing_primary_image_count": sum(
            not bool(record.get("content", {}).get("images", {}).get("primary_url"))
            for record in collected
        ),
    }


def collect(args: argparse.Namespace) -> dict[str, Any]:
    matches: list[dict[str, Any]] = load_json(args.matches, [])
    products: list[dict[str, Any]] = load_json(args.products, [])
    products_by_id = {
        str(product.get("id") or product.get("document_id") or ""): product
        for product in products
    }
    selected = matches[args.start : args.end]
    candidates = [
        match
        for match in selected
        if eligible(
            match,
            products_by_id.get(str(match.get("catalog_product_id") or ""), {}),
            args.minimum_score,
        )
    ]
    candidate_ids = {str(match.get("catalog_product_id") or "") for match in candidates}
    records: list[dict[str, Any]] = load_json(args.output, [])
    records_by_id = {
        str(record.get("catalog_product_id") or ""): record
        for record in records
        if record.get("catalog_product_id") in candidate_ids
    }
    code_cache: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for record in records:
        if record.get("status") == "collected" and record.get("kpic_code"):
            code_cache[str(record["kpic_code"])] = (
                copy.deepcopy(record.get("content") or {}),
                {
                    "drug_name": str(record.get("kpic_name") or ""),
                    "source_url": str(record.get("source_url") or ""),
                    "section_evidence": copy.deepcopy(record.get("section_evidence") or {}),
                },
            )

    client = KpicClient(args.delay, args.timeout, args.retries)
    processed_this_run = 0

    def checkpoint() -> None:
        ordered = sorted(records_by_id.values(), key=lambda item: str(item.get("catalog_product_id") or ""))
        write_json_atomic(args.output, ordered)

    for match in candidates:
        product_id = str(match.get("catalog_product_id") or "")
        code = str(match.get("kpic_code") or "")
        product = products_by_id.get(product_id, {})
        catalog_name = str(product.get("name") or match.get("catalog_name") or "").strip()
        kpic_name = str(match.get("kpic_name") or "").strip()
        score = max(int(match.get("suggestion_score") or 0), int(match.get("match_score") or 0))

        existing = records_by_id.get(product_id)
        if (
            existing
            and existing.get("status") == "collected"
            and existing.get("kpic_code") == code
            and not args.force
        ):
            continue

        record: dict[str, Any] = {
            "catalog_product_id": product_id,
            "catalog_name": catalog_name,
            "kpic_code": code,
            "kpic_name": kpic_name,
            "status": "error",
            "match_score": score,
            "content": {
                "ingredients": [],
                "efficacy": "",
                "dosage": "",
                "precautions": "",
                "storage": "",
                "manufacturer": "",
                "dosage_form": "",
                "route": "",
                "package": "",
                "images": {
                    "primary_url": "",
                    "primary_type": "none",
                    "pack_urls": [],
                    "identification_urls": [],
                },
            },
            "source_url": str(match.get("source_url") or f"{DETAIL_URL}?drug_cd={quote(code)}"),
            "section_evidence": {
                "detail_page_verified": False,
                "ajax_payload_verified": False,
                "required_dom_ids": [],
                "required_fields_present": [],
            },
        }
        try:
            if code in code_cache and not args.force:
                content, metadata = copy.deepcopy(code_cache[code])
            else:
                content, metadata = client.collect_code(code)
                code_cache[code] = (copy.deepcopy(content), copy.deepcopy(metadata))

            ajax_name = str(metadata.get("drug_name") or "")
            if normalize_name(ajax_name) != normalize_name(kpic_name):
                record["status"] = "review_required"
                record["review_reason"] = "매칭 파일의 제품명과 약학정보원 상세 응답의 제품명이 일치하지 않음"
                record["kpic_name"] = ajax_name or kpic_name
                record["source_url"] = str(metadata.get("source_url") or record["source_url"])
                record["section_evidence"] = metadata.get("section_evidence") or record["section_evidence"]
            else:
                record["status"] = "collected"
                record["kpic_name"] = ajax_name or kpic_name
                record["content"] = content
                record["source_url"] = str(metadata.get("source_url") or record["source_url"])
                record["section_evidence"] = metadata.get("section_evidence") or record["section_evidence"]
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"

        records_by_id[product_id] = record
        processed_this_run += 1
        if processed_this_run % args.checkpoint_every == 0:
            checkpoint()
            counts = Counter(row.get("status") for row in records_by_id.values())
            print(
                json.dumps(
                    {
                        "processed_this_run": processed_this_run,
                        "records": len(records_by_id),
                        "status_counts": counts,
                        "last_catalog_product_id": product_id,
                    },
                    ensure_ascii=False,
                    default=dict,
                ),
                flush=True,
            )

    checkpoint()
    final_records = sorted(records_by_id.values(), key=lambda item: str(item.get("catalog_product_id") or ""))
    summary = build_summary(
        final_records,
        selected_count=len(selected),
        eligible_count=len(candidates),
        unique_code_count=len({str(candidate.get("kpic_code")) for candidate in candidates}),
        start=args.start,
        end=args.end,
        delay=args.delay,
    )
    write_json_atomic(args.summary, summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="약학정보원 상세 페이지와 AJAX 응답에서 제품별 의약품 정보를 수집합니다."
    )
    parser.add_argument("--matches", type=Path, default=Path("data/kpic-image-matches.json"))
    parser.add_argument("--products", type=Path, default=Path("data/enrichment-queue.json"))
    parser.add_argument("--output", type=Path, default=Path("data/kpic-details-part-2.json"))
    parser.add_argument("--summary", type=Path, default=Path("data/kpic-details-part-2-summary.json"))
    parser.add_argument("--start", type=int, default=259)
    parser.add_argument("--end", type=int, default=518)
    parser.add_argument("--minimum-score", type=int, default=96)
    parser.add_argument("--delay", type=float, default=0.8)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--checkpoint-every", type=int, default=5)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(collect(parse_args()), ensure_ascii=False, indent=2))
