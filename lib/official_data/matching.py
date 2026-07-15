from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .normalize import dosage_form, normalize_capacity, normalize_company, normalize_name, similarity, strength_tokens


@dataclass
class MatchResult:
    status: str
    score: int
    score_components: dict[str, int]
    official_product_key: str = ""
    alternatives: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)


def score_candidate(catalog: dict[str, Any], official: dict[str, Any]) -> MatchResult:
    catalog_name = catalog.get("name", "")
    official_name = official.get("item_name", "")
    left, right = normalize_name(catalog_name), normalize_name(official_name)
    ratio = similarity(catalog_name, official_name)
    name_points = 60 if left and left == right else round(60 * ratio)

    company_left = normalize_company(catalog.get("manufacturer_hint", ""))
    company_right = normalize_company(official.get("manufacturer", ""))
    company_points = 0
    if company_left and company_right:
        company_points = 20 if company_left == company_right or company_left in company_right or company_right in company_left else 0

    capacity_left = normalize_capacity(catalog.get("capacity", ""))
    capacity_right = normalize_capacity(official.get("pack_unit", ""))
    capacity_points = 15 if capacity_left and capacity_right and capacity_left == capacity_right else 0

    form_left = dosage_form(catalog_name)
    explicit_form = dosage_form(official.get("dosage_form", "")) or str(official.get("dosage_form", ""))
    form_right = explicit_form or dosage_form(official_name)
    form_points = 5 if form_left and form_right and form_left == form_right else 0

    nested_identifiers = official.get("identifiers", {})
    catalog_identifiers = {
        "item_seq": str(catalog.get("official_item_seq", "") or catalog.get("item_seq", "")).strip(),
        "barcode": str(catalog.get("official_barcode", "") or catalog.get("barcode", "")).strip(),
        "udi_di": str(catalog.get("official_udi_di", "") or catalog.get("udi_di", "")).strip(),
        "report_number": str(catalog.get("official_report_number", "") or catalog.get("report_number", "")).strip(),
    }
    official_identifiers = {
        "item_seq": str(official.get("item_seq", "") or nested_identifiers.get("item_seq", "")).strip(),
        "barcode": str(official.get("barcode", "") or nested_identifiers.get("barcode", "")).strip(),
        "udi_di": str(official.get("udi_di", "") or nested_identifiers.get("udi_di", "")).strip(),
        "report_number": str(official.get("report_number", "") or nested_identifiers.get("report_number", "")).strip(),
    }
    identifier_matches = [
        key for key, value in catalog_identifiers.items()
        if value and official_identifiers.get(key) and value == official_identifiers[key]
    ]
    if identifier_matches:
        components = {"identifier": 100, "name": name_points, "manufacturer": company_points, "capacity": capacity_points, "dosage_form": form_points}
        return MatchResult("confirmed", 100, components, str(official.get("official_product_key", "")))

    conflicts: list[str] = []
    if form_left and form_right and form_left != form_right:
        conflicts.append(f"제형 충돌: 판매명 {form_left}, 공식 품목 {form_right}")
    catalog_strengths = strength_tokens(catalog_name)
    official_strengths = strength_tokens(official_name)
    if catalog_strengths and official_strengths and catalog_strengths.isdisjoint(official_strengths):
        conflicts.append(f"함량 충돌: 판매명 {', '.join(sorted(catalog_strengths))}, 공식 품목 {', '.join(sorted(official_strengths))}")

    score = name_points + company_points + capacity_points + form_points
    status = "confirmed" if score >= 95 else "review_required" if score >= 80 else "rejected"
    if conflicts and status == "confirmed":
        status = "review_required"
    return MatchResult(
        status,
        score,
        {"name": name_points, "manufacturer": company_points, "capacity": capacity_points, "dosage_form": form_points},
        str(official.get("official_product_key", "")),
        conflicts=conflicts,
    )


def choose_candidate(catalog: dict[str, Any], candidates: list[dict[str, Any]]) -> MatchResult:
    if not candidates:
        return MatchResult("not_found", 0, {})
    scored = [(score_candidate(catalog, candidate), candidate) for candidate in candidates]
    scored.sort(key=lambda pair: pair[0].score, reverse=True)
    best_result, best_candidate = scored[0]
    alternatives = [
        {
            "official_product_key": result.official_product_key,
            "item_name": candidate.get("item_name", ""),
            "manufacturer": candidate.get("manufacturer", ""),
            "pack_unit": candidate.get("pack_unit", ""),
            "score": result.score,
            "score_components": result.score_components,
            "source_domain": candidate.get("source_domain", ""),
            "source_dataset_id": candidate.get("source_dataset_id", ""),
            "source_url": candidate.get("source_url", ""),
            "item_seq": candidate.get("item_seq", ""),
            "barcode": candidate.get("barcode", ""),
            "udi_di": candidate.get("udi_di", ""),
            "report_number": candidate.get("report_number", ""),
            "dosage_form": candidate.get("dosage_form", ""),
        }
        for result, candidate in scored[:10]
    ]
    exact_name_conflict = sum(
        normalize_name(candidate.get("item_name", "")) == normalize_name(catalog.get("name", ""))
        for _, candidate in scored
    ) > 1
    exact_name_unique = sum(
        normalize_name(candidate.get("item_name", "")) == normalize_name(catalog.get("name", ""))
        for _, candidate in scored
    ) == 1 and normalize_name(best_candidate.get("item_name", "")) == normalize_name(catalog.get("name", ""))
    close_competitor = len(scored) > 1 and scored[1][0].score >= best_result.score - 3
    identifier_matches = [(result, candidate) for result, candidate in scored if result.score_components.get("identifier") == 100]
    if len(identifier_matches) == 1:
        identifier_result, _ = identifier_matches[0]
        identifier_result.alternatives = alternatives
        return identifier_result
    if len(identifier_matches) > 1:
        identifier_result, _ = identifier_matches[0]
        return MatchResult(
            "review_required", 100, identifier_result.score_components,
            identifier_result.official_product_key, alternatives,
            ["같은 공식 식별자와 연결되는 후보가 여러 개입니다."],
        )
    if exact_name_conflict or (best_result.status == "confirmed" and close_competitor):
        return MatchResult(
            "review_required",
            best_result.score,
            best_result.score_components,
            best_result.official_product_key,
            alternatives,
            ["동점 또는 근접한 공식 후보가 여러 개입니다."],
        )
    if exact_name_unique and not close_competitor and not best_result.conflicts:
        best_result.status = "confirmed"
        best_result.score = max(best_result.score, 95)
        best_result.score_components["unique_exact_name"] = 35
        best_result.alternatives = alternatives
        return best_result
    if exact_name_unique and best_result.conflicts:
        return MatchResult(
            "review_required", max(best_result.score, 80), best_result.score_components,
            best_result.official_product_key, alternatives, best_result.conflicts,
        )
    if best_result.status == "rejected":
        return MatchResult("not_found", best_result.score, best_result.score_components, alternatives=alternatives)
    best_result.alternatives = alternatives
    return best_result
