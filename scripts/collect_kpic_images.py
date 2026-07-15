from __future__ import annotations

import argparse
import csv
import html
import http.cookiejar
import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener


BASE_URL = "https://health.kr"
SEARCH_URL = f"{BASE_URL}/searchDrug/search_detail.asp"
SUGGEST_URL = f"{BASE_URL}/searchDrug/ajax/ajax_getDrugName_base.asp"
DETAIL_AJAX_URL = f"{BASE_URL}/searchDrug/ajax/ajax_result_drug2.asp"
USER_AGENT = "Mozilla/5.0 (compatible; pharmacy-product-catalog/1.0; +https://pharmacy-product-catalog.vercel.app)"
IMAGE_RIGHTS_STATUS = "official_source_preview"

FORM_PAIRS = [
    ("search_detail", "Y"), ("proTabState", "0"), ("NoProTabState", "0"),
    ("proYN", ""), ("icode", ""), ("input_drug_nm", "{query}"),
    ("search_sunb1", ""),
    *[("search_drugnm_initial", "") for _ in range(14)],
    ("drug_nm_mode", "field"), ("drug_nm", ""), ("match_value", ""),
    ("sunb_equals1", ""), ("sunb_equals2", ""), ("sunb_equals3", ""),
    ("sunb_where1", "and"), ("sunb_where2", "and"),
    ("input_upsoNm", ""), ("search_effect", ""),
    ("cbx_sunbcnt", "0"), ("cbx_sunbcnt_mode", "0"),
    *[("cbx_bohtype", "") for _ in range(4)],
    ("cbx_bohtype_mode", "0"),
    ("cbx_class", "0"), *[("cbx_class", "") for _ in range(3)],
    ("cbx_class_mode", "0"), ("search_bohcode", ""),
    ("anchor_dosage_route_hidden", ""), ("anchor_form_info_hidden", ""),
    ("mfds_cdWord", ""), ("mfds_cd", ""),
    *[("cbx_narcotic", "") for _ in range(5)],
    ("cbx_narcotic_mode", "0"),
    ("kpic_atc_nm", ""), ("kpic_atc_nm_opener", ""),
    ("atccode_name", ""), ("atccode_val", ""), ("atccode_val_opener", ""),
    ("input_hiraingdcd", ""), *[("cbx_bio", "") for _ in range(4)],
    ("cbx_bio_mode", "0"), ("movefrom", "drug"),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


def normalize(value: Any) -> str:
    text = html.unescape(str(value or "")).lower()
    for before, after in {"현탄액": "현탁액", "씨럽": "시럽", "캅셀": "캡슐"}.items():
        text = text.replace(before, after)
    text = re.sub(r"\([^)]*\)", "", text)
    return re.sub(r"[^0-9a-z가-힣]", "", text)


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


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
        token for token in left_tokens + right_tokens
        if len(token) >= 4 and token not in generic_tokens
    ]
    if any(
        token in a and token in b and len(token) / min(len(a), len(b)) >= 0.55
        for token in distinctive
    ):
        ratio = max(ratio, 96)
    return ratio


def query_variants(name: str) -> list[str]:
    candidates = [name.strip()]
    corrected = name.strip()
    for before, after in {"현탄액": "현탁액", "씨럽": "시럽", "캅셀": "캡슐"}.items():
        corrected = corrected.replace(before, after)
    candidates.append(corrected)
    candidates.append(
        re.sub(
            r"\s+\d+(?:\.\d+)?\s*(?:정|캡슐|포|병|개|ml|mL|g|mg|T|C|P)$",
            "",
            corrected,
        ).strip()
    )
    generic_tokens = {
        "식물성", "플러스", "프리미엄", "드링크", "건강", "대용량", "어린이",
        "성인용", "키즈", "오리지널", "리뉴얼",
    }
    tokens = re.findall(r"[0-9a-zA-Z가-힣]+", corrected)
    candidates.extend(
        token
        for token in sorted(tokens, key=len, reverse=True)
        if len(normalize(token)) >= 3 and token not in generic_tokens and not token.isdigit()
    )
    return list(dict.fromkeys(candidate for candidate in candidates if len(normalize(candidate)) >= 2))


def is_kpic_image(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname in {"common.health.kr", "www.health.kr", "health.kr"}
        and "img_empty" not in parsed.path
        and any(part in parsed.path for part in ("/pack_img/", "/drug_info/", "/daily_img/", "/sb_photo/"))
    )


@dataclass
class SearchCandidate:
    code: str
    name: str
    manufacturer: str
    image_url: str
    source_url: str
    score: int


def parse_candidates(document: str, catalog_name: str) -> list[SearchCandidate]:
    output: list[SearchCandidate] = []
    for row in re.findall(r"<tr\b[^>]*>[\s\S]*?</tr>", document, re.I):
        code_match = re.search(r"drug_detailHref\(['\"]([^'\"]+)", row, re.I)
        if not code_match:
            continue
        code = code_match.group(1).strip()
        name_match = re.search(
            r"<td\b[^>]*onclick=[\"'][^\"']*drug_detailHref\([^)]*\)[^\"']*[\"'][^>]*>([\s\S]*?)</td>",
            row,
            re.I,
        )
        if not name_match:
            continue
        cells = re.findall(r"<td\b[^>]*>([\s\S]*?)</td>", row, re.I)
        image_match = re.search(
            r"<img\b[^>]*src=[\"']([^\"']+)[\"'][^>]*alt=[\"']포장이미지",
            row,
            re.I,
        )
        image_url = html.unescape(image_match.group(1)).strip() if image_match else ""
        if image_url.startswith("/"):
            image_url = f"{BASE_URL}{image_url}"
        official_name = clean_text(name_match.group(1))
        output.append(
            SearchCandidate(
                code=code,
                name=official_name,
                manufacturer=clean_text(cells[4]) if len(cells) > 4 else "",
                image_url=image_url if is_kpic_image(image_url) else "",
                source_url=f"{BASE_URL}/searchDrug/result_drug.asp?drug_cd={quote(code)}",
                score=score_name(catalog_name, official_name),
            )
        )
    return output


class KpicClient:
    def __init__(self, delay: float, timeout: float = 20.0, retries: int = 3) -> None:
        self.delay = max(delay, 0.0)
        self.timeout = timeout
        self.retries = max(retries, 1)
        self.opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.last_request_at = 0.0
        self.get_text(SEARCH_URL)

    def get_text(self, url: str, *, data: bytes | None = None, referer: str = SEARCH_URL) -> str:
        elapsed = time.monotonic() - self.last_request_at
        if self.last_request_at and elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "User-Agent": USER_AGENT,
            "Referer": referer,
        }
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            headers["Origin"] = BASE_URL
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                self.last_request_at = time.monotonic()
                with self.opener.open(Request(url, data=data, headers=headers), timeout=self.timeout) as response:
                    return response.read().decode("utf-8", errors="replace")
            except (HTTPError, URLError, TimeoutError) as exc:
                last_error = exc
                if attempt + 1 < self.retries:
                    time.sleep(2**attempt)
        raise RuntimeError(f"약학정보원 요청 실패: {type(last_error).__name__}") from last_error

    def suggestions(self, query: str) -> list[str]:
        try:
            payload = json.loads(self.get_text(f"{SUGGEST_URL}?drugnm={quote(query)}"))
        except json.JSONDecodeError:
            return []
        return [str(row.get("drug_name", "")).strip() for row in payload if row.get("drug_name")]

    def search(self, query: str, catalog_name: str) -> list[SearchCandidate]:
        form = [(key, query if value == "{query}" else value) for key, value in FORM_PAIRS]
        document = self.get_text(SEARCH_URL, data=urlencode(form).encode("ascii"))
        return parse_candidates(document, catalog_name)

    def detail_image(self, candidate: SearchCandidate) -> str:
        try:
            payload = json.loads(self.get_text(f"{DETAIL_AJAX_URL}?drug_cd={quote(candidate.code)}", referer=candidate.source_url))
            detail = payload[0] if isinstance(payload, list) and payload else {}
            if isinstance(detail, dict):
                urls = [str(detail.get("pack_img") or "")]
                urls.extend(str(detail.get("drug_pic") or "").split("|"))
                for image_url in urls:
                    if is_kpic_image(image_url.strip()):
                        return image_url.strip()
        except (json.JSONDecodeError, RuntimeError):
            pass
        document = self.get_text(candidate.source_url)
        match = re.search(
            r"<meta\s+property=[\"']og:image[\"']\s+content=[\"']([^\"']+)",
            document,
            re.I,
        )
        if not match:
            return candidate.image_url
        image_url = html.unescape(match.group(1)).strip()
        return image_url if is_kpic_image(image_url) else candidate.image_url


def load_json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    preferred = [
        "document_id", "id", "name", "capacity", "category", "price",
        "official_item_name", "official_manufacturer", "official_item_seq",
        "official_source_type", "official_source_url", "official_match_score",
        "official_match_status", "image_kind", "image_url", "image_source_url",
        "image_rights_status", "enrichment_status",
    ]
    fields = list(dict.fromkeys(preferred + [key for row in rows for key in row]))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def choose_suggestion(product_name: str, suggestions: list[str]) -> tuple[str, int]:
    if not suggestions:
        return "", 0
    ranked = sorted(
        ((suggestion, score_name(product_name, suggestion)) for suggestion in suggestions),
        key=lambda item: item[1],
        reverse=True,
    )
    return ranked[0]


def link_product(product: dict[str, Any], record: dict[str, Any]) -> None:
    product.update(
        {
            "official_item_name": record["kpic_name"],
            "official_manufacturer": record["manufacturer"],
            "official_item_seq": record["kpic_code"],
            "official_source_type": "약학정보원 의약품 상세정보",
            "official_source_url": record["source_url"],
            "official_match_score": record["match_score"],
            "official_match_status": "confirmed",
            "official_checked_at": record["checked_at"],
            "image_kind": "package",
            "image_url": record["image_url"],
            "image_source_url": record["source_url"],
            "image_rights_status": IMAGE_RIGHTS_STATUS,
            "image_checked_at": record["checked_at"],
            "enrichment_status": "image_linked",
        }
    )


def make_summary(products: list[dict[str, Any]], matches: list[dict[str, Any]], processed: int, changed: int) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for row in matches:
        status = str(row.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return {
        "generated_at": now_iso(),
        "product_count": len(products),
        "processed_in_run": processed,
        "linked_in_run": changed,
        "match_record_count": len(matches),
        "status_counts": counts,
        "displayable_image_count": sum(
            bool(row.get("image_url")) and row.get("image_rights_status") == IMAGE_RIGHTS_STATUS
            for row in products
        ),
        "source": "약학정보원",
        "source_policy": "상세 페이지의 공유용 상품 이미지를 원격 참조하며 원본 파일을 복제하지 않음",
    }


def hydrate_missing_images(args: argparse.Namespace) -> dict[str, Any]:
    products: list[dict[str, Any]] = load_json(args.input, [])
    matches: list[dict[str, Any]] = load_json(args.matches, [])
    products_by_id = {str(row.get("id") or row.get("document_id") or ""): row for row in products}
    client = KpicClient(args.delay)
    processed = 0
    changed = 0

    def checkpoint() -> None:
        write_json_atomic(args.matches, matches)
        if not args.dry_run:
            write_json_atomic(args.input, products)
            write_csv(args.csv, products)

    for record in matches:
        if record.get("status") != "image_missing":
            continue
        if score_name(str(record.get("catalog_name") or ""), str(record.get("kpic_name") or "")) < args.confirm_score:
            record["status"] = "review_required"
            continue
        candidate = SearchCandidate(
            code=str(record.get("kpic_code") or ""),
            name=str(record.get("kpic_name") or ""),
            manufacturer=str(record.get("manufacturer") or ""),
            image_url="",
            source_url=str(record.get("source_url") or ""),
            score=int(record.get("match_score") or 0),
        )
        processed += 1
        try:
            image_url = client.detail_image(candidate)
        except RuntimeError as exc:
            record["error"] = str(exc)
            continue
        if image_url:
            record["image_url"] = image_url
            record["status"] = "confirmed"
            record["checked_at"] = now_iso()
            product = products_by_id.get(str(record.get("catalog_product_id") or ""))
            if product is not None:
                link_product(product, record)
                changed += 1
        if processed % args.checkpoint_every == 0:
            checkpoint()
            print(json.dumps({"processed": processed, "linked": changed}, ensure_ascii=False), flush=True)
    checkpoint()
    summary = make_summary(products, matches, processed, changed)
    write_json_atomic(args.summary, summary)
    return summary


def collect(args: argparse.Namespace) -> dict[str, Any]:
    if args.hydrate_missing_images:
        return hydrate_missing_images(args)
    products: list[dict[str, Any]] = load_json(args.input, [])
    if not products:
        raise ValueError(f"상품 데이터가 없습니다: {args.input}")
    existing = load_json(args.matches, [])
    matches_by_id = {str(row.get("catalog_product_id", "")): row for row in existing}
    client = KpicClient(args.delay)
    stop = args.start + args.limit if args.limit is not None else None
    selected = products[args.start:stop]
    changed = 0
    processed = 0

    def checkpoint() -> None:
        ordered = [matches_by_id[key] for key in sorted(matches_by_id)]
        write_json_atomic(args.matches, ordered)
        if not args.dry_run:
            write_json_atomic(args.input, products)
            write_csv(args.csv, products)

    for product in selected:
        product_id = str(product.get("id") or product.get("document_id") or "")
        product_name = str(product.get("name") or "").strip()
        if not product_id or not product_name or (product_id in matches_by_id and not args.force):
            continue
        if args.force and product.get("image_rights_status") == IMAGE_RIGHTS_STATUS:
            for field in (
                "official_item_name", "official_manufacturer", "official_item_seq",
                "official_source_type", "official_source_url", "official_match_score",
                "official_checked_at", "image_kind", "image_url", "image_source_url",
                "image_checked_at",
            ):
                product[field] = ""
            product["official_match_status"] = "pending"
            product["image_rights_status"] = "미확인"
            product["enrichment_status"] = "pending"

        suggestions: list[str] = []
        error = ""
        try:
            for query in query_variants(product_name):
                suggestions.extend(client.suggestions(query))
                if suggestions:
                    break
        except RuntimeError as exc:
            error = str(exc)
        suggestions = list(dict.fromkeys(suggestions))
        suggestion, suggestion_score = choose_suggestion(product_name, suggestions)
        record: dict[str, Any] = {
            "catalog_product_id": product_id,
            "catalog_name": product_name,
            "status": "not_found",
            "suggestion": suggestion,
            "suggestion_score": suggestion_score,
            "kpic_code": "",
            "kpic_name": "",
            "manufacturer": "",
            "image_url": "",
            "source_url": "",
            "match_score": 0,
            "checked_at": now_iso(),
            "error": error,
        }

        if suggestion and suggestion_score >= args.minimum_suggestion_score and not error:
            try:
                candidates = client.search(suggestion, product_name)
                if candidates:
                    candidate = max(candidates, key=lambda item: item.score)
                    record.update(
                        {
                            "status": "confirmed" if candidate.score >= args.confirm_score and candidate.image_url else "review_required",
                            "kpic_code": candidate.code,
                            "kpic_name": candidate.name,
                            "manufacturer": candidate.manufacturer,
                            "image_url": client.detail_image(candidate) if candidate.image_url and candidate.score >= args.confirm_score else "",
                            "source_url": candidate.source_url,
                            "match_score": candidate.score,
                        }
                    )
                    if candidate.score >= args.confirm_score and not record["image_url"]:
                        record["status"] = "image_missing"
            except RuntimeError as exc:
                record["status"] = "error"
                record["error"] = str(exc)

        matches_by_id[product_id] = record
        processed += 1
        if record["status"] == "confirmed":
            link_product(product, record)
            changed += 1
        if processed % args.checkpoint_every == 0:
            checkpoint()
            print(json.dumps({"processed": processed, "linked": changed, "last": product_name}, ensure_ascii=False), flush=True)

    checkpoint()
    all_matches = list(matches_by_id.values())
    summary = make_summary(products, all_matches, processed, changed)
    write_json_atomic(args.summary, summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="약학정보원에서 정확히 매칭되는 의약품의 포장 이미지 미리보기를 연결합니다.")
    parser.add_argument("--input", type=Path, default=Path("data/enrichment-queue.json"))
    parser.add_argument("--csv", type=Path, default=Path("data/enrichment-queue.csv"))
    parser.add_argument("--matches", type=Path, default=Path("data/kpic-image-matches.json"))
    parser.add_argument("--summary", type=Path, default=Path("data/kpic-image-summary.json"))
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--delay", type=float, default=0.35)
    parser.add_argument("--minimum-suggestion-score", type=int, default=90)
    parser.add_argument("--confirm-score", type=int, default=96)
    parser.add_argument("--checkpoint-every", type=int, default=10)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--hydrate-missing-images", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(collect(parse_args()), ensure_ascii=False, indent=2))
