from __future__ import annotations

import argparse
import copy
import hashlib
import html as html_std
import json
import os
import re
import sys
import time
import urllib.parse
from collections.abc import Iterable
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import requests
from lxml import etree
from lxml import html as lxml_html

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.catalog_text_normalization import normalize_health_text, parse_health_rich_text


BASE_URL = "https://health.kr"
SEARCH_PAGE = f"{BASE_URL}/searchDrug/search_total_result.asp"
SEARCH_AJAX = f"{BASE_URL}/searchDrug/ajax/ajax_commonSearch.asp"
AUTOCOMPLETE_URL = f"{BASE_URL}/include/drug.asp"
DETAIL_AJAX = f"{BASE_URL}/searchDrug/ajax/ajax_result_drug2.asp"
DETAIL_PAGE = f"{BASE_URL}/searchDrug/result_drug.asp"
ALLOWED_IMAGE_HOSTS = {"health.kr", "www.health.kr", "common.health.kr"}
PIPELINE_VERSION = "health-kr-776-v1"

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORK_DIR = ROOT / "etc" / "health-enrichment"
DEFAULT_CACHE = DEFAULT_WORK_DIR / "cache"

ORIGINAL_FIELDS = (
    "document_id",
    "document_create_time",
    "document_update_time",
    "id",
    "name",
    "capacity",
    "category",
    "price",
    "etc",
    "updated",
    "app_id",
    "app_name",
    "app_capacity",
    "app_category",
    "app_price",
    "app_etc",
    "app_updated",
    "specification",
    "displayed_price_krw",
    "normalized_name",
    "normalized_capacity",
    "source_order",
    "source_type",
    "recorded_at",
    "price_status",
    "verification_status",
    "duplicate_group_id",
    "duplicate_group_size",
)

OFFICIAL_DEFAULTS: dict[str, Any] = {
    "official_item_name": "",
    "official_manufacturer": "",
    "official_item_seq": "",
    "official_source_type": "",
    "official_source_url": "",
    "official_match_score": 0,
    "official_match_status": "",
    "official_checked_at": "",
    "official_domain": "",
    "official_product_key": "",
    "official_barcode": "",
    "official_standard_codes": [],
    "official_report_number": "",
    "official_udi_di": "",
    "official_english_name": "",
    "official_category": "",
    "official_classification_code": "",
    "official_dosage_form": "",
    "official_route": "",
    "official_atc_code": "",
    "official_kpic_atc": "",
    "official_pack_unit": "",
    "official_storage": "",
    "official_valid_term": "",
    "official_appearance": "",
    "official_permit_date": "",
    "official_insurance": "",
    "official_insurance_detail": "",
    "official_insurance_history": [],
    "official_reimbursement_criteria": "",
    "official_efficacy": "",
    "official_dosage": "",
    "official_precautions": "",
    "official_professional_precautions": "",
    "official_ingredients": [],
    "official_active_ingredients": [],
    "official_additives": [],
    "official_consumer_guidance": {},
    "official_patient_guidance": "",
    "official_medication_guide": "",
    "official_medication_summary": "",
    "official_identification": "",
    "official_interactions": [],
    "official_same_ingredient_products": [],
    "official_manufacturer_details": {},
    "official_insert_pdf_url": "",
    "official_dur_contraindications": "",
    "official_dur_age": "",
    "official_dur_pregnancy": "",
    "official_dur_senior": "",
    "official_dur_max_dose": "",
    "official_dur_max_period": "",
    "official_dur_split_dosage": "",
    "official_images": [],
    "official_pictograms": [],
    "official_section_evidence": {},
    "official_additional_data": {},
    "official_content": {},
    "official_content_status": "",
    "official_upstream_updated_at": "",
}

STATUS_TO_ENRICHMENT = {
    "confirmed": "official_details_linked",
    "review_required": "official_review_required",
    "not_found": "not_found",
    "not_applicable": "not_applicable",
}

NON_DRUG_CATEGORIES = {
    "의료기기",
    "코스메틱",
    "건강보조식품",
    "건강기능식품",
    "영양제",
    "유산균",
    "숙취",
    "다이어트",
    "드링크",
    "이벤트",
}

NON_DRUG_NAME_WORDS = (
    "혈압계",
    "체온계",
    "마스크",
    "칫솔",
    "치실",
    "샴푸",
    "염색",
    "크림톤",
    "에어졸",
    "살충",
    "컴배트",
    "콘돔",
    "밴드",
    "파스텔",
    "식물성멜라토닌",
    "바세린",
    "듀렉스",
    "듀럭스",
    "윙크퍼펙트",
    "윙크리얼핏",
    "핑거가드",
    "투약병",
    "시카케어",
    "케어리브",
    "큐어반",
    "반창고",
    "습윤밴드",
    "테이핑",
    "세정제",
    "가그린",
    "폴리덴트",
    "클리덴트",
    "인사덴트",
    "여성청결제",
    "실리콘",
    "모스케어",
    "모스키토",
    "홈키파",
    "비타하임",
    "크림캔디",
    "오메가3",
    "루테인",
    "아스타잔틴",
    "프로바이오틱스",
    "쏘팔메토",
    "밀크씨슬",
    "코큐텐",
    "콜라겐",
    "프로폴리스",
    "보스웰리아",
    "글루타치온",
    "홍삼",
    "산양유",
    "카무트",
    "올리브유",
    "올리브오일",
    "대마종자유",
    "침향환",
    "찜질팩",
)

PROMO_WORDS = (
    "해열진통",
    "해열소염",
    "종합감기약",
    "종합감기",
    "코감기",
    "목감기",
    "알레르기",
    "고함량",
    "고용량",
    "이벤트",
    "구강치아",
    "혈행개선",
    "수면유도제",
    "멘탈관리듀얼솔루션",
    "부드럽고효과빠른변비약",
    "식물성변비약",
    "액상스틱형",
    "어린이멀미약",
)

DISTINGUISHER_WORDS = (
    "플러스",
    "골드",
    "프리미엄",
    "알파",
    "포르테",
    "액티브",
    "메타",
    "제트",
    "모이스쳐",
)

GENERIC_PRODUCT_TERMS = {
    "디오스민",
    "로페라미드",
    "트리메부틴",
    "미녹시딜",
    "비오틴",
    "아세트아미노펜",
    "이부프로펜",
    "나프록센",
    "엽산",
    "철분",
    "쌍화탕",
    "갈근탕",
    "우황청심원",
}

IMPORTANT_PAREN_TERMS = {
    "나프록센",
    "이부프로펜",
    "아세트아미노펜",
    "미녹시딜",
    "사향",
    "영묘향",
}

OBJECTIVE_VERIFIED_CODES = {
    "20250812_104252": "A11ADDDDD0017",
    "20250812_114721": "A11ADDDDD0017",
}

CATALOG_PREFIXES = (
    "부채표",
    "유한",
    "보령",
    "광동",
    "동아",
    "대웅",
    "일동",
    "종근당",
    "한미",
    "녹십자",
    "삼진",
    "태극",
    "신신",
    "현대",
    "동화",
    "제일",
    "조아",
    "경남",
    "경방",
    "명인",
    "삼성",
    "정우",
    "한솔",
    "일양",
    "한풍",
    "한신",
    "아이월드",
)

PREFIX_MANUFACTURER_ALIASES = {
    "부채표": ("동화약품",),
    "한신": ("한국신약",),
}

TYPO_REPLACEMENTS = {
    "챕프": "챔프",
    "챔프노트": "챔프노즈",
    "고햠량": "고함량",
    "비타민하이렉스": "하이렉스",
    "점안액30관": "점안액",
    "메가트루골": "메가트루골드",
    "메가트루633": "메가트루육삼삼",
    "무조날S": "무조날에스",
    "액티넘EX": "액티넘이엑스",
    "포비스틱": "포스틱",
}

FORM_GROUPS = {
    "tablet": ("정", "정제", "장용정", "서방정", "츄어블", "츄어블정", "구강붕해정", "현탁정"),
    "capsule": ("캡슐", "경질캡슐", "연질캡슐", "서방캡슐"),
    "liquid": ("액", "액제", "시럽", "시럽제", "현탁액", "내복액", "외용액", "엘릭서", "드링크"),
    "ointment": ("연고", "안연고"),
    "cream": ("크림",),
    "gel": ("겔", "겔제", "젤", "젤제"),
    "ophthalmic": ("점안액", "점안제", "점비액", "안겔", "안연고"),
    "powder": ("산", "산제", "과립", "과립제", "엑스과립", "현탁용분말"),
    "spray": ("스프레이", "나잘스프레이", "인후스프레이", "비강분무액", "분무", "에어로솔", "폼"),
    "patch": ("패취", "패치", "플라스타", "카타플라스마"),
    "suppository": ("좌제",),
    "pill": ("환", "환제"),
    "film": ("구강용해필름", "필름"),
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def normalize_name(value: str) -> str:
    value = value or ""
    for wrong, right in TYPO_REPLACEMENTS.items():
        value = value.replace(wrong, right)
    value = re.sub(r"(?i)비타민\s*C", "비타민씨", value)
    value = re.sub(r"(?i)비타민\s*D", "비타민디", value)
    value = re.sub(r"(?i)비타민\s*B", "비타민비", value)
    value = re.sub(r"(?i)비타민\s*E", "비타민이", value)
    return re.sub(r"[^0-9A-Za-z가-힣+]", "", value).lower()


def core_name(value: str) -> str:
    value = normalize_name(value)
    for word in PROMO_WORDS:
        value = value.replace(normalize_name(word), "")
    for wrong, right in TYPO_REPLACEMENTS.items():
        wrong_token = re.sub(r"[^0-9A-Za-z가-힣+]", "", wrong).lower()
        right_token = re.sub(r"[^0-9A-Za-z가-힣+]", "", right).lower()
        value = value.replace(wrong_token, right_token)
    value = re.sub(r"\d+(?:[.,]\d+)?(?:mg|mcg|g|ml|l|iu|정|캡슐|포|병|개|c|s|t|v|ea|매|롤)$", "", value, flags=re.I)
    return value


def comparison_cores(value: str) -> list[str]:
    raw_parts = [value]
    raw_parts.extend(part for part in re.split(r"[/／]", value or "") if part.strip())
    values: list[str] = []
    for part in raw_parts:
        base = core_name(part)
        if base and base not in values:
            values.append(base)
        formless = strip_form_tokens(base)
        if form_less_valid(formless) and formless not in values:
            values.append(formless)
        for prefix in CATALOG_PREFIXES:
            token = normalize_name(prefix)
            if base.startswith(token) and len(base) - len(token) >= 3:
                stripped = base[len(token) :]
                if stripped not in values:
                    values.append(stripped)
                stripped_formless = strip_form_tokens(stripped)
                if form_less_valid(stripped_formless) and stripped_formless not in values:
                    values.append(stripped_formless)
    return list(dict.fromkeys(values))


def form_less_valid(value: str) -> bool:
    return bool(value and len(value) >= 2)


def strip_form_tokens(value: str) -> str:
    compact = value or ""
    tokens = sorted(
        {normalize_name(word) for words in FORM_GROUPS.values() for word in words},
        key=len,
        reverse=True,
    )
    for token in tokens:
        if not token:
            continue
        if len(token) > 1:
            compact = compact.replace(token, "")
    for token in tokens:
        if len(token) == 1 and compact.endswith(token):
            compact = compact[: -len(token)]
            break
    return compact


def brand_cores(value: str) -> list[str]:
    without_parentheses = re.sub(r"\([^)]*\)", "", value or "")
    return list(dict.fromkeys(strip_form_tokens(item) for item in comparison_cores(without_parentheses) if strip_form_tokens(item)))


def leading_catalog_prefix(value: str) -> str:
    compact = normalize_name(value)
    for prefix in sorted(CATALOG_PREFIXES, key=len, reverse=True):
        if compact.startswith(normalize_name(prefix)):
            return prefix
    return ""


def manufacturer_matches_prefix(prefix: str, manufacturer: str) -> bool:
    if not prefix or not manufacturer:
        return True
    manufacturer_compact = normalize_name(manufacturer)
    accepted = (prefix, *PREFIX_MANUFACTURER_ALIASES.get(prefix, ()))
    return any(normalize_name(value) in manufacturer_compact for value in accepted)


def make_search_variants(name: str, capacity: str = "") -> list[str]:
    original = name or ""
    corrected = original
    for wrong, right in TYPO_REPLACEMENTS.items():
        corrected = corrected.replace(wrong, right)
    capacity_free = corrected.replace(capacity or "\0", " ")
    parenthetical_free = re.sub(r"\([^)]*\)", " ", capacity_free)
    capacity_free = re.sub(
        r"(?<!\d)\d+(?:[.,]\d+)?\s*(?:mg|mcg|g|ml|l|iu|정|캡슐|포|병|개|c|ea|매|롤)\b",
        " ",
        capacity_free,
        flags=re.I,
    )
    vitamin_korean = re.sub(r"(?i)비타민\s*C", "비타민씨", capacity_free)
    vitamin_korean = re.sub(r"(?i)비타민\s*D", "비타민디", vitamin_korean)
    vitamin_korean = re.sub(r"(?i)비타민\s*B", "비타민비", vitamin_korean)
    vitamin_korean = re.sub(r"(?i)비타민\s*E", "비타민이", vitamin_korean)
    promo_free = capacity_free
    for word in PROMO_WORDS:
        promo_free = promo_free.replace(word, " ")
    seeds = [original, corrected, capacity_free, parenthetical_free, vitamin_korean, promo_free]
    compact = [normalize_name(seed) for seed in seeds]
    core = core_name(corrected)
    comparable = comparison_cores(corrected)
    compact.extend(comparable)
    for search_core in comparable or [core]:
        if len(search_core) >= 5:
            compact.extend([search_core[: max(4, len(search_core) - 1)], search_core[:4], search_core[:3]])
    variants = []
    for value in compact:
        if len(value) >= 2 and value not in variants:
            variants.append(value)
    return variants[:8]


def clean_text(value: Any) -> str:
    return normalize_health_text(value)


def clean_public(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): clean_public(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean_public(item) for item in value]
    if isinstance(value, str):
        return clean_text(value)
    return value


def split_upstream(value: str, separators: Iterable[str] = ("</br>", "<br>", "@", "#")) -> list[str]:
    text = value or ""
    for separator in separators:
        text = text.replace(separator, "\n")
    values = []
    for part in text.splitlines():
        cleaned = clean_text(part)
        if cleaned and cleaned not in values:
            values.append(cleaned)
    return values


def split_ingredients(value: str) -> tuple[list[str], list[dict]]:
    ingredients: list[str] = []
    details: list[dict] = []
    for record in (value or "").split("|"):
        if not record.strip():
            continue
        match = re.search(r"ingd_code=([^\"'&>]+)", record)
        code = urllib.parse.unquote(match.group(1)) if match else ""
        cleaned = clean_text(record.replace("@", " / "))
        if cleaned and cleaned not in ingredients:
            ingredients.append(cleaned)
        if cleaned:
            details.append(
                {
                    "label": cleaned,
                    "ingredient_code": code,
                    "source_url": f"{BASE_URL}/searchIngredient/detail.asp?ingd_code={urllib.parse.quote(code)}" if code else "",
                }
            )
    return ingredients, details


def detect_form_group(value: str) -> str:
    # Parentheses commonly contain an ingredient or traditional prescription name
    # (for example, 정정보환(온신산)); they must not override the product's main form.
    compact = core_name(re.sub(r"\([^)]*\)", " ", value or ""))
    matches: list[tuple[int, str]] = []
    pack = extract_pack_count(value)
    if pack:
        pack_group = {"정": "tablet", "캡슐": "capsule"}.get(pack[1], "")
        if pack_group:
            matches.append((100, pack_group))
    for group, words in FORM_GROUPS.items():
        for word in words:
            token = normalize_name(word)
            if not token:
                continue
            matched = compact.endswith(token) if len(token) == 1 else token in compact
            if matched:
                matches.append((len(token), group))
    return max(matches)[1] if matches else ""


def detect_form_conflict(catalog_name: str, official_form: str, official_name: str = "") -> str:
    source_group = detect_form_group(catalog_name)
    official_group = detect_form_group(f"{official_name} {official_form}")
    if source_group and official_group and source_group != official_group:
        if {source_group, official_group} <= {"liquid", "ophthalmic"} and "점안" in normalize_name(catalog_name):
            return ""
        if {source_group, official_group} <= {"ointment", "ophthalmic"} and "안연고" in normalize_name(official_form):
            return ""
        return f"제형 충돌: 카탈로그 {source_group}, 약학정보원 {official_group}"
    return ""


def extract_strengths(value: str) -> set[str]:
    normalized = str(value or "")
    for korean, unit in (
        ("마이크로그램", "mcg"),
        ("밀리그램", "mg"),
        ("밀리리터", "ml"),
        ("그램", "g"),
    ):
        normalized = normalized.replace(korean, unit)
    matches = re.findall(r"(?i)(\d+(?:[.,]\d+)?)\s*(mg|mcg|g|ml|iu|%)", normalized)
    return {f"{number.replace(',', '')}{unit.lower()}" for number, unit in matches}


def extract_pack_count(value: str) -> tuple[str, str] | None:
    match = re.search(r"(\d+)\s*(정|캡슐|포|병|개|매|롤|관|바이알|cap|c|t|v|ea)\b", value or "", flags=re.I)
    if not match:
        return None
    unit = match.group(2).lower()
    unit = {"c": "캡슐", "cap": "캡슐", "t": "정", "v": "바이알", "ea": "개"}.get(unit, unit)
    return match.group(1), unit


def generic_product_name(value: str) -> bool:
    compact = core_name(re.sub(r"\([^)]*\)", "", value or ""))
    if any(compact.startswith(normalize_name(prefix)) for prefix in CATALOG_PREFIXES):
        return False
    form_tokens = sorted(
        {normalize_name(word) for words in FORM_GROUPS.values() for word in words},
        key=len,
        reverse=True,
    )
    changed = True
    while changed:
        changed = False
        for token in form_tokens:
            if token and compact.endswith(token):
                compact = compact[: -len(token)]
                changed = True
                break
    compact = re.sub(r"약$", "", compact)
    return compact in {normalize_name(term) for term in GENERIC_PRODUCT_TERMS}


def score_candidate(
    row: dict,
    candidate: dict,
    existing_code: str = "",
    detail: dict | None = None,
) -> tuple[int, list[str], list[str]]:
    catalog_name = str(row.get("name") or "")
    source_values = comparison_cores(catalog_name)
    official_name = str((detail or {}).get("drug_name") or candidate.get("drug_name") or "")
    official_values = comparison_cores(official_name)
    reasons: list[str] = []
    conflicts: list[str] = []
    paren_conflicts: list[str] = []
    paren_contents = [clean_text(value) for value in re.findall(r"\(([^)]*)\)", catalog_name) if clean_text(value)]
    if paren_contents:
        paren_free_values = comparison_cores(re.sub(r"\([^)]*\)", " ", catalog_name))
        if detail is None:
            source_values.extend(value for value in paren_free_values if value not in source_values)
        else:
            comparison_blob = normalize_name(
                " ".join(
                    [
                        official_name,
                        clean_text(detail.get("sunb", "")),
                        clean_text(candidate.get("ingr_mg", "")),
                        clean_text(candidate.get("list_sunb_name", "")),
                    ]
                )
            )
            all_resolved = True
            for content in paren_contents:
                normalized_content = normalize_name(content)
                ignorable_pack_note = bool(re.fullmatch(r"(?:소환|대환|소|대|병|파랑|빨강|노랑|\d+(?:[.,]\d+)?(?:mg|g|ml|%))", normalized_content, re.I))
                if normalized_content and normalized_content in comparison_blob:
                    reasons.append(f"괄호 구분 성분 일치: {content}")
                elif ignorable_pack_note:
                    continue
                elif normalized_content in {normalize_name(value) for value in IMPORTANT_PAREN_TERMS}:
                    paren_conflicts.append(f"괄호 구분 성분 불일치: {content}")
                    all_resolved = False
                else:
                    all_resolved = False
            if all_resolved:
                source_values.extend(value for value in paren_free_values if value not in source_values)
    if not source_values or not official_values:
        return 0, reasons, ["제품명 비교 불가"]

    comparisons = [
        (SequenceMatcher(None, source, official).ratio(), source, official)
        for source in source_values
        for official in official_values
    ]
    similarity, source, official = max(comparisons, key=lambda item: item[0])
    exact_pair = next(((s, o) for s in source_values for o in official_values if s == o), None)
    containment_pairs = [
        (s, o)
        for s in source_values
        for o in official_values
        if min(len(s), len(o)) >= 3 and (s in o or o in s)
    ]
    if exact_pair:
        source, official = exact_pair
        score = 94
        reasons.append("핵심 제품명 일치")
    elif containment_pairs:
        source, official = max(containment_pairs, key=lambda pair: SequenceMatcher(None, pair[0], pair[1]).ratio())
        similarity = SequenceMatcher(None, source, official).ratio()
        score = min(92, 82 + int(similarity * 10))
        reasons.append("핵심 제품명 포함 일치")
    else:
        score = int(similarity * 78)
        if similarity >= 0.72:
            reasons.append("핵심 제품명 유사")

    if paren_conflicts:
        conflicts.extend(paren_conflicts)
        score -= 45

    normalized_catalog = normalize_name(catalog_name)
    normalized_official = normalize_name(official_name)
    source_prefix = leading_catalog_prefix(catalog_name)
    official_prefix = leading_catalog_prefix(official_name)
    if source_prefix and official_prefix and source_prefix != official_prefix:
        conflicts.append(f"제품사 표기 충돌: 카탈로그 {source_prefix}, 약학정보원 {official_prefix}")
        score -= 45
    for word in DISTINGUISHER_WORDS:
        token = normalize_name(word)
        if (token in normalized_catalog) != (token in normalized_official):
            conflicts.append(f"제품 구분어 충돌: {word}")
            score -= 35

    source_brands = brand_cores(catalog_name)
    official_brands = brand_cores(official_name)
    if source_brands and official_brands and not any(source == official for source in source_brands for official in official_brands):
        detail_context = normalize_name(
            " ".join(
                str((detail or {}).get(field) or "")
                for field in ("drug_box", "charact", "charact_new")
            )
        )
        catalog_suffixes = [
            source[len(official) :]
            for source in source_brands
            for official in official_brands
            if len(official) >= 3 and source.startswith(official) and len(source) > len(official)
        ]
        meaningful_catalog_suffixes = [
            suffix
            for suffix in catalog_suffixes
            if suffix
            and not re.fullmatch(r"\d+(?:[.,]\d+)?(?:mg|g|ml|mcg|iu|%)", suffix, re.I)
            and not (suffix.isdigit() and suffix in normalized_official)
            and normalize_name(suffix) not in detail_context
        ]
        if meaningful_catalog_suffixes:
            shortest = min(meaningful_catalog_suffixes, key=len)
            conflicts.append(f"카탈로그에만 있는 구분어: {shortest}")
            score -= 35
        catalog_prefixes = [
            source[: -len(official)]
            for source in source_brands
            for official in official_brands
            if len(official) >= 3 and source.endswith(official) and len(source) > len(official)
        ]
        meaningful_catalog_prefixes = [
            prefix
            for prefix in catalog_prefixes
            if prefix
            and not re.fullmatch(r"\d+(?:[.,]\d+)?(?:mg|g|ml|mcg|iu|%)", prefix, re.I)
            and not (prefix.isdigit() and prefix in normalized_official)
            and normalize_name(prefix) not in detail_context
        ]
        if meaningful_catalog_prefixes:
            shortest = min(meaningful_catalog_prefixes, key=len)
            conflicts.append(f"카탈로그에만 있는 앞 구분어: {shortest}")
            score -= 35
        suffixes = [
            official[len(source) :]
            for source in source_brands
            for official in official_brands
            if len(source) >= 3 and official.startswith(source) and len(official) > len(source)
        ]
        meaningful_suffixes = [
            suffix
            for suffix in suffixes
            if suffix
            and not re.fullmatch(r"\d+(?:[.,]\d+)?(?:mg|g|ml|mcg|iu|%)", suffix, re.I)
            and not (suffix.isdigit() and suffix in normalized_catalog)
        ]
        if meaningful_suffixes:
            shortest = min(meaningful_suffixes, key=len)
            conflicts.append(f"공식 제품에만 있는 구분어: {shortest}")
            score -= 35
        prefixes = [
            official[: -len(source)]
            for source in source_brands
            for official in official_brands
            if len(source) >= 3 and official.endswith(source) and len(official) > len(source)
        ]
        meaningful_prefixes = [
            prefix
            for prefix in prefixes
            if prefix
            and not re.fullmatch(r"\d+(?:[.,]\d+)?(?:mg|g|ml|mcg|iu|%)", prefix, re.I)
            and not (prefix.isdigit() and prefix in normalized_catalog)
        ]
        if meaningful_prefixes:
            shortest = min(meaningful_prefixes, key=len)
            conflicts.append(f"공식 제품에만 있는 앞 구분어: {shortest}")
            score -= 35
        middle_containment = [
            (source[: source.index(official)], source[source.index(official) + len(official) :])
            for source in source_brands
            for official in official_brands
            if len(official) >= 3
            and official in source
            and source.index(official) > 0
            and source.index(official) + len(official) < len(source)
        ]
        if middle_containment:
            prefix, suffix = min(middle_containment, key=lambda pair: len(pair[0]) + len(pair[1]))
            conflicts.append(f"카탈로그명 중간 부분문자열만 일치: {prefix}|{suffix}")
            score -= 45
        official_middle_containment = [
            (official[: official.index(source)], official[official.index(source) + len(source) :])
            for source in source_brands
            for official in official_brands
            if len(source) >= 3
            and source in official
            and official.index(source) > 0
            and official.index(source) + len(source) < len(official)
        ]
        if official_middle_containment:
            prefix, suffix = min(
                official_middle_containment,
                key=lambda pair: len(pair[0]) + len(pair[1]),
            )
            conflicts.append(f"공식 제품명 중간 부분문자열만 일치: {prefix}|{suffix}")
            score -= 45

    if "수출용" in normalized_official and "수출용" not in normalized_catalog:
        conflicts.append("카탈로그에 없는 수출용 제품")
        score -= 50

    if generic_product_name(catalog_name):
        conflicts.append("일반 성분명 또는 처방명만으로 제조사 제품을 특정할 수 없음")
        score -= 40

    code = str((detail or {}).get("drug_code") or candidate.get("drug_code") or "")
    if existing_code and code == existing_code:
        score += 8
        reasons.append("기존 제품 코드 원문 재검증")

    official_form = str((detail or {}).get("drug_form") or candidate.get("drug_form") or "")
    catalog_form_values = [
        str(row.get(field) or "") for field in ("name", "capacity", "specification")
    ]
    form_conflict = next(
        (
            conflict
            for value in catalog_form_values
            if (conflict := detect_form_conflict(value, official_form, official_name))
        ),
        "",
    )
    if form_conflict:
        conflicts.append(form_conflict)
        score -= 45
    elif any(detect_form_group(value) for value in catalog_form_values) and detect_form_group(
        f"{official_name} {official_form}"
    ):
        score += 3
        reasons.append("제형 일치")

    source_name_group = detect_form_group(str(row.get("name") or ""))
    source_capacity = " ".join(
        str(row.get(field) or "") for field in ("capacity", "specification")
    )
    if source_name_group in {"tablet", "capsule", "pill"} and re.search(
        r"\d+(?:[.,]\d+)?\s*m[lL]\b", source_capacity
    ):
        conflicts.append("카탈로그 제품명 제형과 용량 단위 충돌")
        score -= 35

    source_strengths = extract_strengths(row.get("name", ""))
    official_name_strengths = extract_strengths(official_name)
    official_detail_strengths = (
        extract_strengths(clean_text(detail.get("sunb", ""))) if detail else set()
    )
    strength_matches = 0
    strength_conflicts: list[tuple[str, list[str]]] = []
    for source_strength in source_strengths:
        unit_match = re.search(r"([a-z]+|%)$", source_strength, re.I)
        unit = unit_match.group(1).lower() if unit_match else ""
        official_same_unit = {
            value
            for value in official_name_strengths
            if value.lower().endswith(unit)
        }
        if not official_same_unit and unit != "ml":
            official_same_unit = {
                value
                for value in official_detail_strengths
                if value.lower().endswith(unit)
            }
        if not official_same_unit:
            continue
        if source_strength in official_same_unit:
            strength_matches += 1
        else:
            strength_conflicts.append((source_strength, sorted(official_same_unit)))
    if strength_matches:
        score += 3
        reasons.append("함량 일치")
    if strength_conflicts:
        conflicts.append(
            "함량 충돌: "
            + ", ".join(
                f"카탈로그 {source}, 약학정보원 {official}"
                for source, official in strength_conflicts
            )
        )
        score -= 35

    if detail:
        source_pack = extract_pack_count(row.get("capacity", "") or row.get("specification", ""))
        official_pack_text = clean_text(detail.get("drug_box", ""))
        if source_pack and official_pack_text:
            number, unit = source_pack
            compact_pack = re.sub(r"\s+", "", official_pack_text).lower()
            direct_match = re.search(rf"(?<!\d){re.escape(number)}{re.escape(unit)}", compact_pack, flags=re.I)
            multiplied_match = re.search(
                rf"{re.escape(unit)}(?:[/당])?[x×*]?{re.escape(number)}(?!\d)|{re.escape(unit)}[^,;]{{0,12}}[x×*]{re.escape(number)}(?!\d)",
                compact_pack,
                flags=re.I,
            )
            if direct_match or multiplied_match:
                score += 3
                reasons.append("포장단위 일치")
            elif unit in compact_pack:
                # A pharmacy row can be a retail bundle while health.kr records the
                # licensed container. Product identity is determined by name, form,
                # strength and manufacturer; bundle count remains retail metadata.
                reasons.append("판매단위와 허가 포장단위 차이")
        source_measures = extract_strengths(str(row.get("capacity") or row.get("specification") or ""))
        official_pack_measures = extract_strengths(official_pack_text)
        if source_measures and official_pack_measures:
            if source_measures & official_pack_measures:
                score += 2
                reasons.append("용량 규격 일치")
            else:
                conflicts.append(
                    f"용량 규격 충돌: 카탈로그 {sorted(source_measures)}, 약학정보원 포장 {sorted(official_pack_measures)}"
                )
                score -= 20

    manufacturer = str((detail or {}).get("upso_name") or candidate.get("upso_name_kfda") or "").split("|")[0]
    if source_prefix and manufacturer and not manufacturer_matches_prefix(source_prefix, manufacturer):
        conflicts.append(f"제품사·제조사 충돌: 카탈로그 {source_prefix}, 약학정보원 {manufacturer}")
        score -= 45
    if manufacturer:
        reasons.append("제조사 원문 확인")
    return max(0, min(100, score)), list(dict.fromkeys(reasons)), conflicts


def valid_official_image(url: str) -> bool:
    parsed = urllib.parse.urlparse(url or "")
    return (
        parsed.scheme in {"http", "https"}
        and (parsed.hostname or "").lower() in ALLOWED_IMAGE_HOSTS
        and not re.search(r"placeholder|no[_-]?image|ready|none", parsed.path, re.I)
    )


def normalize_official_url(url: str, base: str = BASE_URL) -> str:
    if not url:
        return ""
    joined = urllib.parse.urljoin(base, html_std.unescape(url.strip()))
    parsed = urllib.parse.urlparse(joined)
    if parsed.hostname in ALLOWED_IMAGE_HOSTS or parsed.hostname in {"health.kr", "www.health.kr"}:
        joined = urllib.parse.urlunparse(parsed._replace(scheme="https", netloc=parsed.hostname or "health.kr"))
    return joined


class HealthKrClient:
    def __init__(self, cache_dir: Path = DEFAULT_CACHE, min_interval: float = 0.18):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CodexHealthKrVerifier/1.0",
                "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
            }
        )
        self.min_interval = min_interval
        self.last_request_at = 0.0
        self.csrf_token = ""

    def _cache_path(self, namespace: str, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.cache_dir / namespace / f"{digest}.json"

    def _load_cache(self, namespace: str, key: str) -> Any | None:
        path = self._cache_path(namespace, key)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def _save_cache(self, namespace: str, key: str, value: Any) -> None:
        atomic_write_json(self._cache_path(namespace, key), value)

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(5):
            delay = self.min_interval - (time.monotonic() - self.last_request_at)
            if delay > 0:
                time.sleep(delay)
            try:
                response = self.session.request(method, url, timeout=kwargs.pop("timeout", 35), **kwargs)
                self.last_request_at = time.monotonic()
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise requests.HTTPError(f"retryable HTTP {response.status_code}", response=response)
                if 400 <= response.status_code < 500:
                    raise RuntimeError(f"HTTP {response.status_code}: {method} {url}")
                response.raise_for_status()
                response.encoding = "utf-8"
                return response
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                time.sleep(min(8.0, 0.7 * (2**attempt)))
        raise RuntimeError(f"health.kr request failed: {method} {url}: {last_error}")

    def bootstrap_search(self, query: str = "약") -> None:
        response = self._request("POST", SEARCH_PAGE, data={"search_word": query, "search_flag": "all"})
        match = re.search(r'window\.csrfToken\s*=\s*"([^"]+)"', response.text)
        if not match:
            raise RuntimeError("health.kr CSRF token not found")
        self.csrf_token = match.group(1)

    def search(self, query: str) -> list[dict]:
        query = normalize_name(query)
        cached = self._load_cache("search", query)
        if cached is not None:
            return cached
        if not self.csrf_token:
            self.bootstrap_search(query)
        for refresh in range(2):
            response = self._request(
                "POST",
                SEARCH_AJAX,
                params={"search_word": query, "csrf_token": self.csrf_token, "search_flag": "all"},
                data={"csrf_token": self.csrf_token},
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "X-CSRF-Token": self.csrf_token,
                    "Referer": SEARCH_PAGE,
                    "Origin": BASE_URL,
                },
            )
            try:
                data = response.json()
            except requests.JSONDecodeError:
                data = []
            if isinstance(data, list):
                self._save_cache("search", query, data)
                return data
            if refresh == 0:
                self.csrf_token = ""
                self.bootstrap_search(query)
        self._save_cache("search", query, [])
        return []

    def autocomplete(self, query: str) -> list[str]:
        query = normalize_name(query)
        cached = self._load_cache("autocomplete", query)
        if cached is not None:
            return cached
        response = self._request("GET", AUTOCOMPLETE_URL, params={"drugnm": query})
        suggestions: list[str] = []
        try:
            document = lxml_html.fromstring(response.text)
            for node in document.xpath("//a"):
                value = clean_text(node.text_content())
                if value and value not in suggestions:
                    suggestions.append(value)
        except (ValueError, TypeError, etree.ParserError):
            pass
        self._save_cache("autocomplete", query, suggestions[:30])
        return suggestions[:30]

    def detail(self, code: str) -> dict | None:
        cached = self._load_cache("detail", code)
        if cached is not None:
            return cached or None
        response = self._request("GET", DETAIL_AJAX, params={"drug_cd": code})
        try:
            data = response.json()
        except requests.JSONDecodeError:
            data = []
        value = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else None
        self._save_cache("detail", code, value or {})
        return value

    def json_endpoint(self, namespace: str, url: str, params: dict[str, Any]) -> Any:
        key = url + "?" + urllib.parse.urlencode(sorted((str(k), str(v)) for k, v in params.items()))
        cached = self._load_cache(namespace, key)
        if cached is not None:
            return cached
        try:
            response = self._request("GET", url, params=params)
            data = response.json()
        except (RuntimeError, requests.JSONDecodeError):
            data = []
        self._save_cache(namespace, key, data)
        return data

    def structured_page(self, namespace: str, url: str) -> dict:
        cached = self._load_cache(namespace, url)
        if cached is not None:
            return cached
        response = self._request("GET", url)
        structured = parse_public_page(response.text, response.url)
        self._save_cache(namespace, url, structured)
        return structured

    def image_exists(self, url: str) -> bool:
        cached = self._load_cache("image_probe", url)
        if cached is not None:
            return bool(cached.get("valid"))
        valid = False
        try:
            response = self._request("HEAD", url, allow_redirects=True)
            content_type = response.headers.get("Content-Type", "").lower()
            valid = response.status_code == 200 and (not content_type or content_type.startswith("image/"))
        except RuntimeError:
            try:
                response = self._request(
                    "GET",
                    url,
                    allow_redirects=True,
                    stream=True,
                    headers={"Range": "bytes=0-1023"},
                )
                content_type = response.headers.get("Content-Type", "").lower()
                valid = response.status_code in {200, 206} and content_type.startswith("image/")
                response.close()
            except RuntimeError:
                valid = False
        self._save_cache("image_probe", url, {"valid": valid, "checked_at": now_iso()})
        return valid


def parse_public_page(source: str, source_url: str) -> dict:
    try:
        document = lxml_html.fromstring(source)
    except (ValueError, TypeError, etree.ParserError):
        return {"source_url": source_url, "title": "", "text": "", "tables": [], "links": []}
    for node in document.xpath("//script|//style|//noscript|//header|//footer|//*[@id='top']|//*[@id='nav_cont']|//*[@id='lnb']"):
        parent = node.getparent()
        if parent is not None:
            parent.remove(node)
    roots = document.xpath("//*[@id='articles_sub'] | //*[@id='contens'] | //main")
    root = roots[0] if roots else document
    title_nodes = root.xpath(".//h1|.//h2|.//h3")
    title = clean_text(title_nodes[0].text_content()) if title_nodes else ""
    tables: list[dict] = []
    for table in root.xpath(".//table"):
        rows: list[list[str]] = []
        for tr in table.xpath(".//tr"):
            cells = [clean_text(cell.text_content()) for cell in tr.xpath("./th|./td")]
            if any(cells):
                rows.append(cells)
        if rows:
            tables.append({"rows": rows})
    links: list[dict] = []
    for anchor in root.xpath(".//a[@href]"):
        href = normalize_official_url(anchor.get("href", ""), source_url)
        label = clean_text(anchor.text_content())
        if href and (href.startswith("https://health.kr") or href.startswith("https://www.health.kr") or href.startswith("https://common.health.kr")):
            item = {"label": label, "url": href}
            if item not in links:
                links.append(item)
    text = clean_text(root.text_content())
    return {"source_url": source_url, "title": title, "text": text, "tables": tables, "links": links}


def flatten_table_rows(page: dict) -> list[dict]:
    output: list[dict] = []
    for table_index, table in enumerate(page.get("tables", [])):
        rows = table.get("rows", [])
        if not rows:
            continue
        headers = rows[0]
        header_like = len(headers) > 1 and all(headers) and len(set(headers)) == len(headers)
        data_rows = rows[1:] if header_like else rows
        for row in data_rows:
            if header_like and len(row) == len(headers):
                output.append({headers[i]: row[i] for i in range(len(headers))})
            else:
                output.append({"table_index": table_index, "cells": row})
    return output


def parse_manufacturer(value: str) -> dict:
    parts = (value or "").split("|")
    parts += [""] * (6 - len(parts))
    return {
        "name": clean_text(parts[0]),
        "english_name": clean_text(parts[1]),
        "address": clean_text(parts[2]),
        "phone": clean_text(parts[3]),
        "fax": clean_text(parts[4]),
        "website": clean_text(parts[5]),
    }


def parse_insurance_history(value: str) -> list[dict]:
    history: list[dict] = []
    for row in (value or "").split("^"):
        if not row.strip():
            continue
        parts = row.split("|", 1)
        history.append({"code": clean_text(parts[0]), "detail": clean_text(parts[1] if len(parts) > 1 else "")})
    return history


def empty_enrichment(record: dict) -> None:
    for key, value in OFFICIAL_DEFAULTS.items():
        record[key] = copy.deepcopy(value)
    record["match_alternatives"] = []
    record["image_url"] = ""
    record["image_kind"] = ""
    record["image_source_url"] = ""
    record["image_rights_status"] = ""
    record["image_checked_at"] = ""


def classify_image(url: str) -> str:
    path = urllib.parse.urlparse(url).path.lower()
    if "pack_img" in path or "/pack" in path:
        return "package"
    if "sb_photo" in path or "idfy" in path or "drug_pic" in path:
        return "pill"
    if "label" in path:
        return "label"
    return "instruction"


def build_images(
    client: HealthKrClient,
    raw: dict,
    code: str,
    source_url: str,
    checked_at: str,
) -> tuple[list[dict], list[dict], Any]:
    candidates: list[str] = []
    for key in ("pack_img", "drug_pic"):
        for raw_value in str(raw.get(key) or "").split("|"):
            value = normalize_official_url(raw_value)
            if value:
                candidates.append(value)
    idfyidx = raw.get("idfyidx")
    idfy_payload: Any = []
    if idfyidx not in {None, ""}:
        idfy_payload = client.json_endpoint(
            "idfy",
            f"{BASE_URL}/searchDrug/ajax/ajax_result_idfy_delay.asp",
            {"drug_cd": code, "idfyidx": idfyidx},
        )
        for item in idfy_payload if isinstance(idfy_payload, list) else [idfy_payload]:
            if isinstance(item, dict):
                for key, value in item.items():
                    if isinstance(value, str) and ("img" in key.lower() or re.search(r"\.(?:jpg|jpeg|png|gif)(?:\?|$)", value, re.I)):
                        candidates.append(normalize_official_url(value))
    images: list[dict] = []
    seen: set[str] = set()
    for url in candidates:
        if not valid_official_image(url) or url in seen or not client.image_exists(url):
            continue
        seen.add(url)
        images.append(
            {
                "url": url,
                "kind": classify_image(url),
                "source_url": source_url,
                "source_dataset_id": "kpic-drug-detail",
                "license": "",
                "fetched_at": checked_at,
            }
        )
    pictograms: list[dict] = []
    for value in str(raw.get("picto_img") or "").split("|"):
        url = normalize_official_url(value)
        if valid_official_image(url) and url not in seen and client.image_exists(url):
            seen.add(url)
            pictograms.append(
                {
                    "url": url,
                    "source_url": source_url,
                    "source_dataset_id": "kpic-drug-detail",
                    "license": "",
                    "fetched_at": checked_at,
                }
            )
    return images, pictograms, idfy_payload


def build_confirmed_record(
    original: dict,
    candidate: dict,
    raw: dict,
    score: int,
    reasons: list[str],
    conflicts: list[str],
    client: HealthKrClient,
    include_aux: bool = True,
) -> dict:
    record = copy.deepcopy(original)
    empty_enrichment(record)
    code = str(raw.get("drug_code") or candidate.get("drug_code") or "")
    checked_at = now_iso()
    source_url = f"{DETAIL_PAGE}?drug_cd={urllib.parse.quote(code)}"
    manufacturer = parse_manufacturer(str(raw.get("upso_name") or candidate.get("upso_name_kfda") or ""))
    ingredients, ingredient_details = split_ingredients(str(raw.get("sunb") or ""))
    additives = split_upstream(str(raw.get("additives") or ""), separators=("</br>", "<br>", "<br/>", "<br />", "#"))

    aux_pages: dict[str, Any] = {}
    if include_aux:
        for key, slug in (
            ("medication", "result_take.asp"),
            ("same_ingredient", "result_sunb.asp"),
            ("interaction", "result_interaction.asp"),
        ):
            url = f"{BASE_URL}/searchDrug/{slug}?drug_cd={urllib.parse.quote(code)}"
            try:
                aux_pages[key] = client.structured_page(f"page_{key}", url)
            except RuntimeError as exc:
                aux_pages[key] = {"source_url": url, "error": str(exc), "title": "", "text": "", "tables": [], "links": []}
        try:
            insurance_page = client.structured_page(
                "insurance_history",
                f"{BASE_URL}/searchDrug/ajax/ajax_boh_history2.asp?drug_cd={urllib.parse.quote(code)}",
            )
        except RuntimeError as exc:
            insurance_page = {"source_url": "", "error": str(exc), "title": "", "text": "", "tables": [], "links": []}
        aux_pages["insurance_history"] = insurance_page

    images, pictograms, idfy_payload = build_images(client, raw, code, source_url, checked_at)
    insurance_history = parse_insurance_history(str(raw.get("boh_history") or ""))
    same_ingredient = flatten_table_rows(aux_pages.get("same_ingredient", {}))
    interactions = flatten_table_rows(aux_pages.get("interaction", {}))
    medication_page = aux_pages.get("medication", {})
    medication_summary = clean_text(raw.get("medititle", ""))
    medication_guide = clean_text(raw.get("mediguide", ""))
    consumer_guidance = {
        "summary": medication_summary,
        "guide": medication_guide,
    }

    report_number = clean_text(raw.get("fdacode", ""))
    standard_codes = [value for value in split_upstream(report_number, separators=("|", ",")) if value]
    insert_url = normalize_official_url(str(raw.get("insertpaper") or ""), source_url)

    record.update(
        {
            "official_item_name": clean_text(raw.get("drug_name", "")),
            "official_manufacturer": manufacturer.get("name", ""),
            "official_item_seq": code,
            "official_source_type": "약학정보원 의약품 상세정보",
            "official_source_url": source_url,
            "official_match_score": score,
            "official_match_status": "confirmed",
            "official_checked_at": checked_at,
            "official_domain": "health.kr",
            "official_product_key": code,
            "official_barcode": "",
            "official_standard_codes": standard_codes,
            "official_report_number": report_number,
            "official_udi_di": "",
            "official_english_name": clean_text(raw.get("drug_enm", "")),
            "official_category": clean_text(raw.get("cls_code", "")),
            "official_classification_code": clean_text(raw.get("cls_code_num", "")),
            "official_dosage_form": clean_text(raw.get("drug_form", "")),
            "official_route": clean_text(raw.get("dosage_route", "")),
            "official_atc_code": clean_text(raw.get("atc_cd", "")),
            "official_kpic_atc": clean_text(raw.get("kpic_atc", "")),
            "official_pack_unit": clean_text(raw.get("drug_box", "")),
            "official_storage": clean_text(raw.get("stmt", "")),
            "official_valid_term": clean_text(raw.get("valid_term", "")),
            "official_appearance": clean_text(raw.get("charact_new") or raw.get("charact", "")),
            "official_permit_date": clean_text(raw.get("item_permit_date", "")),
            "official_insurance": clean_text(raw.get("boh", "")),
            "official_insurance_detail": clean_text(raw.get("boh_history", "")),
            "official_insurance_history": insurance_history,
            "official_reimbursement_criteria": clean_text(raw.get("reimbursement_criteria", "")),
            "official_efficacy": clean_text(raw.get("effect", "")),
            "official_dosage": clean_text(raw.get("dosage", "")),
            "official_precautions": clean_text(raw.get("caution", "")),
            "official_professional_precautions": "",
            "official_ingredients": ingredients,
            "official_active_ingredients": copy.deepcopy(ingredients),
            "official_additives": additives,
            "official_consumer_guidance": consumer_guidance,
            "official_patient_guidance": medication_summary,
            "official_medication_guide": medication_guide,
            "official_medication_summary": medication_summary,
            "official_identification": clean_text(raw.get("idfyinfo", ""))
            or (json.dumps(clean_public(idfy_payload), ensure_ascii=False) if idfy_payload else ""),
            "official_interactions": interactions,
            "official_same_ingredient_products": same_ingredient,
            "official_manufacturer_details": manufacturer,
            "official_insert_pdf_url": insert_url,
            "official_dur_contraindications": clean_text(raw.get("dur_contra", "")),
            "official_dur_age": clean_text(raw.get("dur_age", "")),
            "official_dur_pregnancy": clean_text(raw.get("dur_preg", "")),
            "official_dur_senior": clean_text(raw.get("dur_senior", "")),
            "official_dur_max_dose": clean_text(raw.get("dur_dose", "")),
            "official_dur_max_period": clean_text(raw.get("dur_period", "")),
            "official_dur_split_dosage": clean_text(raw.get("dur_form", "")),
            "official_images": images,
            "official_pictograms": pictograms,
            "official_upstream_updated_at": clean_text(raw.get("paper_dt", "")),
            "match_alternatives": [],
            "enrichment_status": "official_details_linked",
        }
    )

    verified_fields = [
        field
        for field, value in (
            ("ingredients", record["official_ingredients"]),
            ("efficacy", record["official_efficacy"]),
            ("dosage", record["official_dosage"]),
            ("precautions", record["official_precautions"]),
            ("storage", record["official_storage"]),
            ("manufacturer", record["official_manufacturer"]),
            ("dosage_form", record["official_dosage_form"]),
            ("route", record["official_route"]),
            ("package", record["official_pack_unit"]),
            ("images", record["official_images"]),
        )
        if value
    ]
    source_urls = [source_url]
    source_urls.extend(page.get("source_url", "") for page in aux_pages.values() if isinstance(page, dict))
    source_urls = list(dict.fromkeys(url for url in source_urls if url))
    record["official_section_evidence"] = {
        "detail_page_verified": True,
        "ajax_payload_verified": True,
        "match_reasons": reasons,
        "conflicts": conflicts,
        "source_urls": source_urls,
        "verified_fields": verified_fields,
        "pipeline_version": PIPELINE_VERSION,
    }
    cleaned_raw = clean_public(raw)
    health_kr_raw = dict(cleaned_raw)
    health_kr_raw.update(
        {
            "auxiliary_pages": clean_public(aux_pages),
            "identification_ajax": clean_public(idfy_payload),
            "ingredient_details": ingredient_details,
        }
    )
    record["official_additional_data"] = {
        "health_kr_raw": health_kr_raw
    }
    record["official_content"] = {
        "schema_version": "1.0",
        "normalization_version": "catalog-text-v1",
        "efficacy": parse_health_rich_text(raw.get("effect", "")),
        "dosage": parse_health_rich_text(raw.get("dosage", "")),
        "precautions": parse_health_rich_text(raw.get("caution", "")),
        "consumer_guidance": consumer_guidance,
    }
    required = {"ingredients", "efficacy", "dosage", "precautions", "storage", "manufacturer", "dosage_form", "route", "package"}
    record["official_content_status"] = (
        "normalized_from_upstream_cache"
        if required.issubset(set(verified_fields))
        else "normalized_partial_from_upstream_cache"
    )

    priority = {"package": 0, "label": 1, "pill": 2, "instruction": 3}
    if images:
        representative = sorted(images, key=lambda item: priority.get(item.get("kind", "instruction"), 9))[0]
        record["image_url"] = representative["url"]
        record["image_kind"] = representative["kind"]
        record["image_source_url"] = source_url
        record["image_rights_status"] = "official_source_preview"
        record["image_checked_at"] = checked_at
    return record


def alternative_from(candidate: dict, detail: dict | None, score: int, conflicts: list[str]) -> dict:
    raw = detail or {}
    code = str(raw.get("drug_code") or candidate.get("drug_code") or "")
    manufacturer = parse_manufacturer(str(raw.get("upso_name") or candidate.get("upso_name_kfda") or ""))["name"]
    return {
        "official_item_name": clean_text(raw.get("drug_name") or candidate.get("drug_name", "")),
        "official_item_seq": code,
        "official_manufacturer": manufacturer,
        "official_dosage_form": clean_text(raw.get("drug_form") or candidate.get("drug_form", "")),
        "official_pack_unit": clean_text(raw.get("drug_box", "")),
        "official_source_url": f"{DETAIL_PAGE}?drug_cd={urllib.parse.quote(code)}" if code else "",
        "match_score": score,
        "conflicts": conflicts,
    }


def non_drug_after_exhaustion(row: dict) -> bool:
    category = str(row.get("category") or "").strip()
    name = normalize_name(row.get("name", ""))
    return category in NON_DRUG_CATEGORIES or any(normalize_name(word) in name for word in NON_DRUG_NAME_WORDS)


def search_candidates(client: HealthKrClient, row: dict) -> list[dict]:
    candidates: dict[str, dict] = {}
    suggestions: list[str] = []
    variants = make_search_variants(
        str(row.get("name") or ""), str(row.get("capacity") or "")
    )
    app_name = str(row.get("app_name") or "").strip()
    if app_name:
        variants.extend(
            make_search_variants(app_name, str(row.get("app_capacity") or ""))
        )
    variants = list(dict.fromkeys(variants))
    for query in variants:
        try:
            for candidate in client.search(query):
                if isinstance(candidate, dict) and candidate.get("drug_code"):
                    candidates[str(candidate["drug_code"])] = candidate
            for suggestion in client.autocomplete(query):
                if suggestion not in suggestions:
                    suggestions.append(suggestion)
        except RuntimeError:
            continue
        if len(candidates) >= 25:
            break
    for suggestion in suggestions[:20]:
        try:
            for candidate in client.search(suggestion):
                if isinstance(candidate, dict) and candidate.get("drug_code"):
                    candidates[str(candidate["drug_code"])] = candidate
        except RuntimeError:
            continue
    return list(candidates.values())


def process_record(client: HealthKrClient, original: dict, include_aux: bool = True) -> dict:
    existing_code = str(original.get("official_item_seq") or "")
    ranked: list[tuple[int, dict, dict | None, list[str], list[str]]] = []

    objective_code = OBJECTIVE_VERIFIED_CODES.get(str(original.get("document_id") or ""))
    if objective_code:
        detail = client.detail(objective_code)
        if detail:
            candidate = {
                "drug_code": objective_code,
                "drug_name": detail.get("drug_name", ""),
                "drug_form": detail.get("drug_form", ""),
                "upso_name_kfda": str(detail.get("upso_name", "")).split("|")[0],
            }
            score, reasons, conflicts = score_candidate(original, candidate, objective_code, detail)
            reasons.append("목표 문서에 명시된 약학정보원 제품 코드 재검증")
            return build_confirmed_record(
                original,
                candidate,
                detail,
                max(95, score),
                list(dict.fromkeys(reasons)),
                conflicts,
                client,
                include_aux,
            )

    if existing_code:
        detail = client.detail(existing_code)
        if detail:
            candidate = {
                "drug_code": existing_code,
                "drug_name": detail.get("drug_name", ""),
                "drug_form": detail.get("drug_form", ""),
                "upso_name_kfda": str(detail.get("upso_name", "")).split("|")[0],
            }
            score, reasons, conflicts = score_candidate(original, candidate, existing_code, detail)
            if score >= 80 and not conflicts:
                return build_confirmed_record(original, candidate, detail, score, reasons, conflicts, client, include_aux)
            ranked.append((score, candidate, detail, reasons, conflicts))

    for candidate in search_candidates(client, original):
        code = str(candidate.get("drug_code") or "")
        preliminary, _, preliminary_conflicts = score_candidate(original, candidate, existing_code)
        detail = client.detail(code) if code and (preliminary >= 38 or existing_code == code) else None
        score, reasons, conflicts = score_candidate(original, candidate, existing_code, detail)
        # Detail fields can resolve a preliminary conflict (for example a flavor
        # suffix listed in drug_box), so only retain preliminary conflicts when
        # no detail record could be loaded.
        conflicts = list(
            dict.fromkeys(conflicts if detail is not None else preliminary_conflicts)
        )
        ranked.append((score, candidate, detail, reasons, conflicts))

    deduped: dict[str, tuple[int, dict, dict | None, list[str], list[str]]] = {}
    for entry in ranked:
        code = str((entry[2] or {}).get("drug_code") or entry[1].get("drug_code") or "")
        if code and (code not in deduped or entry[0] > deduped[code][0]):
            deduped[code] = entry
    ranked = sorted(deduped.values(), key=lambda item: item[0], reverse=True)

    if ranked:
        top = ranked[0]
        second_score = ranked[1][0] if len(ranked) > 1 else 0
        source_cores = comparison_cores(original.get("name", ""))
        official_cores = comparison_cores((top[2] or {}).get("drug_name") or top[1].get("drug_name", ""))
        containment = any(
            source and official and (source in official or official in source)
            for source in source_cores
            for official in official_cores
        )
        safe_margin = top[0] - second_score >= 6 or containment
        if top[0] >= 84 and safe_margin and not top[4] and top[2]:
            return build_confirmed_record(original, top[1], top[2], top[0], top[3], top[4], client, include_aux)

    if ranked and ranked[0][0] >= 45:
        status = "review_required"
    elif non_drug_after_exhaustion(original):
        status = "not_applicable"
    else:
        status = "not_found"
    record = copy.deepcopy(original)
    empty_enrichment(record)
    record["official_match_status"] = status
    record["official_checked_at"] = now_iso()
    record["official_content_status"] = ""
    record["enrichment_status"] = STATUS_TO_ENRICHMENT[status]
    record["match_alternatives"] = [alternative_from(candidate, detail, score, conflicts) for score, candidate, detail, _, conflicts in ranked[:8]]
    return record


def verify_original_fields(original: list[dict], result: list[dict]) -> None:
    if len(original) != 776 or len(result) != 776:
        raise ValueError(f"expected 776 rows, got original={len(original)} result={len(result)}")
    for index, (before, after) in enumerate(zip(original, result)):
        if before.get("document_id") != after.get("document_id"):
            raise ValueError(f"document order changed at index {index}")
        for key in ORIGINAL_FIELDS:
            if key not in after or before.get(key) != after.get(key):
                raise ValueError(f"original field changed: {before.get('document_id')} {key}")


def run(args: argparse.Namespace) -> None:
    input_path = Path(args.input)
    checkpoint_path = Path(args.checkpoint)
    state_path = checkpoint_path.with_suffix(checkpoint_path.suffix + ".state.json")
    original = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(original, list) or len(original) != 776:
        raise ValueError("input must be a 776-object JSON array")

    if args.resume and checkpoint_path.exists() and state_path.exists():
        result = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        state = json.loads(state_path.read_text(encoding="utf-8"))
        next_index = int(state.get("next_index", 0))
    else:
        result = copy.deepcopy(original)
        next_index = 0

    client = HealthKrClient(Path(args.cache_dir), min_interval=args.min_interval)
    end = min(len(original), args.limit if args.limit else len(original))
    for index in range(next_index, end):
        row = original[index]
        started = time.monotonic()
        try:
            result[index] = process_record(client, row, include_aux=not args.no_aux)
            status = result[index].get("official_match_status", "")
            item = result[index].get("official_item_name", "")
            print(f"[{index + 1:03d}/776] {row.get('document_id')} {row.get('name')} -> {status} {item} ({time.monotonic() - started:.1f}s)", flush=True)
        except Exception as exc:
            print(f"[{index + 1:03d}/776] ERROR {row.get('document_id')} {row.get('name')}: {type(exc).__name__}: {exc}", flush=True)
            raise
        checkpoint_every = max(1, args.checkpoint_every)
        if (index + 1) % checkpoint_every == 0 or index + 1 == end:
            atomic_write_json(checkpoint_path, result)
            atomic_write_json(
                state_path,
                {"pipeline_version": PIPELINE_VERSION, "next_index": index + 1, "updated_at": now_iso()},
            )

    if end == len(original):
        verify_original_fields(original, result)
        atomic_write_json(checkpoint_path, result)
        atomic_write_json(state_path, {"pipeline_version": PIPELINE_VERSION, "next_index": 776, "complete": True, "updated_at": now_iso()})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(ROOT / "data" / "enrichment-queue.json"))
    parser.add_argument("--checkpoint", default=str(DEFAULT_WORK_DIR / "enrichment-checkpoint.json"))
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE))
    parser.add_argument("--min-interval", type=float, default=0.18)
    parser.add_argument("--checkpoint-every", type=int, default=10)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--no-aux", action="store_true")
    return parser


if __name__ == "__main__":
    run(build_parser().parse_args())
