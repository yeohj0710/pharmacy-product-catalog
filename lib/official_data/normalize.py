from __future__ import annotations

import re
from difflib import SequenceMatcher


COMPANY_MARKERS = ("주식회사", "(주)", "㈜", "유한회사", "제약회사")
DOSAGE_FORMS = ("연질캡슐", "경질캡슐", "캡슐", "시럽", "현탁액", "액", "정", "환", "산", "과립", "크림", "연고", "겔", "스프레이", "패치")


def compact(value: object) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", str(value or "").casefold())


def normalize_company(value: object) -> str:
    text = str(value or "")
    for marker in COMPANY_MARKERS:
        text = text.replace(marker, "")
    return compact(text)


def normalize_name(value: object) -> str:
    text = str(value or "")
    text = re.sub(r"\((?:증정|기획|리뉴얼|색상|파랑|빨강)[^)]*\)", "", text)
    return compact(text)


def normalize_capacity(value: object) -> str:
    text = str(value or "").casefold()
    text = text.replace("캡슐", "cap").replace("정", "tab").replace("포", "sachet")
    return compact(text)


def dosage_form(value: object) -> str:
    text = str(value or "").replace(" ", "")
    for form in DOSAGE_FORMS:
        if form in text:
            return form
    return ""


def strength_tokens(value: object) -> set[str]:
    text = str(value or "").casefold().replace("밀리그램", "mg").replace("마이크로그램", "mcg").replace("그램", "g")
    matches = re.findall(r"(?<![0-9])([0-9]+(?:\.[0-9]+)?)\s*(mg|mcg|μg|ug|g|%)", text)
    return {f"{number}{unit.replace('μg', 'mcg').replace('ug', 'mcg')}" for number, unit in matches}


def similarity(left: object, right: object) -> float:
    a, b = normalize_name(left), normalize_name(right)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()
