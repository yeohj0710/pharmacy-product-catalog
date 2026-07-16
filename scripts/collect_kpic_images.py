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

OCR_REPLACEMENTS = {"현탄액": "현탁액", "씨럽": "시럽", "캅셀": "캡슐"}
DOSAGE_FORMS = (
    "구강붕해필름", "나잘스프레이", "비강스프레이", "필름코팅정", "구강붕해정",
    "연질캡슐", "경질캡슐", "장용정", "발포정",
    "카타플라스마", "현탁액", "점비액", "점안액", "내복액", "에어로졸",
    "에어로솔", "스프레이", "트로키", "캡슐", "시럽", "과립", "연고",
    "크림", "좌약", "필름", "패취", "파스", "겔", "액", "정", "산",
)
INDICATION_SUFFIXES = (
    "해열진통제", "해열진통", "진통해열", "종합감기약", "종합감기",
    "감기약", "진통제", "소화제", "비염약", "알레르기약", "상처치료제",
)

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


def corrected_text(value: Any) -> str:
    text = html.unescape(str(value or "")).lower()
    for before, after in OCR_REPLACEMENTS.items():
        text = text.replace(before, after)
    return text


def normalize(value: Any) -> str:
    text = corrected_text(value)
    text = re.sub(r"\([^)]*\)", "", text)
    return re.sub(r"[^0-9a-z가-힣]", "", text)


def identity_normalize(value: Any) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", corrected_text(value))


def significant_parentheticals(value: Any) -> set[str]:
    output: set[str] = set()
    for group in re.findall(r"\(([^)]*)\)", corrected_text(value)):
        normalized = re.sub(r"[^0-9a-z가-힣]", "", group)
        if normalized and not re.fullmatch(r"\d+(?:\.\d+)?(?:mg|g|ml|정|캡슐|포|병|개)", normalized):
            output.add(normalized)
    return output


def strength_tokens(value: Any) -> set[str]:
    text = corrected_text(value).replace("㎎", "mg").replace("㎖", "ml")
    return {
        f"{number}{unit.lower()}"
        for number, unit in re.findall(r"(?<![0-9.])(\d+(?:\.\d+)?)\s*(mg|mcg|μg|g|ml|%)(?![a-z])", text, re.I)
    }


def dosage_family(value: Any) -> str:
    text = normalize(value)
    families = (
        ("capsule", ("연질캡슐", "경질캡슐", "캡슐")),
        ("tablet", ("필름코팅정", "구강붕해정", "장용정", "발포정", "츄정", "트로키", "정제", "정")),
        ("suppository", ("좌약",)),
        ("topical", ("카타플라스마", "연고", "크림", "겔", "파스", "패취")),
        ("spray", ("나잘스프레이", "비강스프레이", "스프레이", "에어로졸", "에어로솔")),
        ("ophthalmic", ("점안액",)),
        ("nasal", ("점비액",)),
        ("liquid", ("현탁액", "내복액", "시럽", "액")),
        ("powder", ("과립", "산")),
        ("film", ("구강붕해필름", "필름")),
    )
    for family, forms in families:
        if any(form in text for form in forms):
            return family
    return ""


def capacity_family(value: Any) -> str:
    text = corrected_text(value).strip()
    if re.search(r"\d+\s*(?:c|caps?|캡슐)\b", text, re.I):
        return "capsule"
    if re.search(r"\d+\s*(?:t|tabs?|정)\b", text, re.I):
        return "tablet"
    if re.search(r"\d+\s*(?:환)\b", text, re.I):
        return "pill"
    return ""


def comparable_core(value: Any) -> str:
    core = normalize(value)
    core = re.sub(r"\d+(?:\.\d+)?(?:mg|mcg|g|ml|%)$", "", core)
    changed = True
    while changed:
        changed = False
        for suffix in (*INDICATION_SUFFIXES, *DOSAGE_FORMS):
            normalized_suffix = normalize(suffix)
            if len(core) >= len(normalized_suffix) + 2 and core.endswith(normalized_suffix):
                core = core[: -len(normalized_suffix)]
                changed = True
                break
    return core


def safe_name_match(catalog_name: Any, official_name: Any, catalog_capacity: Any = "") -> bool:
    left_identity = identity_normalize(catalog_name)
    right_identity = identity_normalize(official_name)
    if not left_identity or not right_identity:
        return False
    left_qualifiers = significant_parentheticals(catalog_name)
    right_qualifiers = significant_parentheticals(official_name)
    if left_qualifiers != right_qualifiers and (left_qualifiers or right_qualifiers):
        return False
    left_strengths = strength_tokens(catalog_name)
    right_strengths = strength_tokens(official_name)
    if left_strengths and right_strengths and left_strengths.isdisjoint(right_strengths):
        return False
    catalog_form = dosage_family(catalog_name)
    official_form = dosage_family(official_name)
    expected_form = capacity_family(catalog_capacity)
    if catalog_form and official_form and catalog_form != official_form:
        return False
    if expected_form and official_form and expected_form != official_form:
        return False
    if left_identity == right_identity:
        return True
    left = normalize(catalog_name)
    right = normalize(official_name)
    if left == right:
        return True
    left_core = comparable_core(catalog_name)
    right_core = comparable_core(official_name)
    minimum_core_length = 2 if expected_form and expected_form == official_form else 3
    if left_core and left_core == right_core and len(left_core) >= minimum_core_length:
        return True
    if min(len(left), len(right)) >= 4 and (left in right or right in left):
        longer, shorter = (left, right) if len(left) >= len(right) else (right, left)
        extra = longer.replace(shorter, "", 1)
        allowed_extra = comparable_core(extra) == "" or extra in {normalize(item) for item in INDICATION_SUFFIXES}
        return allowed_extra
    return False


def validated_match_score(catalog_name: Any, official_name: Any, catalog_capacity: Any = "") -> int:
    raw_score = score_name(str(catalog_name or ""), str(official_name or ""))
    if not safe_name_match(catalog_name, official_name, catalog_capacity):
        return raw_score
    if identity_normalize(catalog_name) == identity_normalize(official_name):
        return 100
    if comparable_core(catalog_name) == comparable_core(official_name):
        return max(raw_score, 98)
    return raw_score


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
    corrected = corrected_text(name).strip()
    candidates.append(corrected)
    candidates.append(
        re.sub(
            r"\s+\d+(?:\.\d+)?\s*(?:정|캡슐|포|병|개|ml|mL|g|mg|T|C|P)$",
            "",
            corrected,
        ).strip()
    )
    compact = re.sub(r"\s+", "", corrected)
    for form in DOSAGE_FORMS:
        start = 0
        while True:
            index = compact.find(form, start)
            if index < 0:
                break
            end = index + len(form)
            prefix = compact[:end]
            remainder = compact[end:]
            if len(normalize(prefix)) >= 3 and (
                len(form) >= 2
                or not remainder
                or any(remainder.startswith(suffix) for suffix in INDICATION_SUFFIXES)
            ):
                candidates.append(prefix)
            start = end
    for suffix in INDICATION_SUFFIXES:
        if compact.endswith(suffix):
            candidates.append(compact[: -len(suffix)])
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
    if "@" in url or "|" in url:
        return False
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


def first_kpic_image(value: Any) -> str:
    for candidate in re.split(r"[@|]", str(value or "")):
        image_url = candidate.strip()
        if is_kpic_image(image_url):
            return image_url
    return ""


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
                pack_image = first_kpic_image(detail.get("pack_img"))
                if pack_image:
                    return pack_image
                pill_image = first_kpic_image(detail.get("drug_pic"))
                if pill_image:
                    return pill_image
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


def sanitize_match_images(matches: list[dict[str, Any]]) -> None:
    for record in matches:
        record["image_url"] = first_kpic_image(record.get("image_url"))


def choose_suggestion(product_name: str, suggestions: list[str]) -> tuple[str, int]:
    if not suggestions:
        return "", 0
    ranked = sorted(
        ((suggestion, score_name(product_name, suggestion)) for suggestion in suggestions),
        key=lambda item: item[1],
        reverse=True,
    )
    return ranked[0]


def choose_candidate(
    candidates: list[SearchCandidate],
    product_name: str,
    capacity: str,
    confirm_score: int,
) -> tuple[SearchCandidate | None, str, str]:
    unique: dict[str, SearchCandidate] = {}
    for candidate in candidates:
        candidate.score = validated_match_score(product_name, candidate.name, capacity)
        previous = unique.get(candidate.code)
        if previous is None or candidate.score > previous.score:
            unique[candidate.code] = candidate
    ranked = sorted(unique.values(), key=lambda item: item.score, reverse=True)
    if not ranked:
        return None, "not_found", "no_search_result"
    safe = [
        candidate for candidate in ranked
        if candidate.score >= confirm_score and safe_name_match(product_name, candidate.name, capacity)
    ]
    if not safe:
        return ranked[0], "review_required", "name_or_dosage_conflict"
    top = safe[0]
    competitors = [candidate for candidate in safe[1:] if candidate.score >= top.score - 1]
    if competitors:
        return top, "review_required", "ambiguous_candidates"
    return top, "confirmed", "unique_safe_candidate"


def clear_kpic_product_match(product: dict[str, Any]) -> None:
    source_type = str(product.get("official_source_type") or "")
    source_url = str(product.get("official_source_url") or "")
    if "약학정보원" not in source_type and "health.kr" not in source_url:
        return
    for field in tuple(product):
        if field.startswith("official_"):
            product.pop(field, None)
    product["official_match_status"] = "pending"
    if product.get("image_rights_status") == IMAGE_RIGHTS_STATUS:
        product.update(
            {
                "image_kind": "",
                "image_url": "",
                "image_source_url": "",
                "image_rights_status": "미확인",
                "image_checked_at": "",
            }
        )
    product["enrichment_status"] = "pending"


def record_is_safe_match(
    record: dict[str, Any],
    product: dict[str, Any] | None = None,
    minimum_score: int = 96,
) -> bool:
    capacity = record.get("catalog_capacity") or (product or {}).get("capacity") or ""
    return (
        bool(record.get("kpic_code"))
        and validated_match_score(record.get("catalog_name"), record.get("kpic_name"), capacity)
        >= minimum_score
        and safe_name_match(record.get("catalog_name"), record.get("kpic_name"), capacity)
    )


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
            "enrichment_status": "official_match_linked",
        }
    )
    if record.get("image_url") and is_kpic_image(str(record["image_url"])):
        product.update(
            {
                "image_kind": "package",
                "image_url": record["image_url"],
                "image_source_url": record["source_url"],
                "image_rights_status": IMAGE_RIGHTS_STATUS,
                "image_checked_at": record["checked_at"],
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
    sanitize_match_images(matches)
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
        product = products_by_id.get(str(record.get("catalog_product_id") or ""))
        if not record_is_safe_match(record, product, args.confirm_score):
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
    sanitize_match_images(existing)
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
        if args.force:
            clear_kpic_product_match(product)

        suggestions: list[str] = []
        error = ""
        try:
            for query in query_variants(product_name):
                suggestions.extend(client.suggestions(query))
        except RuntimeError as exc:
            error = str(exc)
        suggestions = list(dict.fromkeys(suggestions))
        suggestion, suggestion_score = choose_suggestion(product_name, suggestions)
        record: dict[str, Any] = {
            "catalog_product_id": product_id,
            "catalog_name": product_name,
            "catalog_capacity": str(product.get("capacity") or ""),
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
            "decision_reason": "",
        }

        if not error:
            try:
                candidates: list[SearchCandidate] = []
                ranked_suggestions = sorted(
                    list(dict.fromkeys([*suggestions, *query_variants(product_name)])),
                    key=lambda item: score_name(product_name, item),
                    reverse=True,
                )
                for candidate_query in ranked_suggestions[: args.max_suggestions]:
                    if score_name(product_name, candidate_query) < args.minimum_suggestion_score:
                        continue
                    candidates.extend(client.search(candidate_query, product_name))
                candidate, status, reason = choose_candidate(
                    candidates,
                    product_name,
                    str(product.get("capacity") or ""),
                    args.confirm_score,
                )
                if candidate:
                    image_url = client.detail_image(candidate) if status == "confirmed" and candidate.image_url else ""
                    record.update(
                        {
                            "status": status,
                            "kpic_code": candidate.code,
                            "kpic_name": candidate.name,
                            "manufacturer": candidate.manufacturer,
                            "image_url": image_url,
                            "source_url": candidate.source_url,
                            "match_score": candidate.score,
                            "decision_reason": reason,
                        }
                    )
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
    parser.add_argument("--minimum-suggestion-score", type=int, default=70)
    parser.add_argument("--confirm-score", type=int, default=96)
    parser.add_argument("--max-suggestions", type=int, default=5)
    parser.add_argument("--checkpoint-every", type=int, default=10)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--hydrate-missing-images", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(collect(parse_args()), ensure_ascii=False, indent=2))
