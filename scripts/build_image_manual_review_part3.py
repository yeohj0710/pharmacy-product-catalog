from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = DATA / "image-manual-review-part-3.json"
SUMMARY = DATA / "image-manual-review-part-3-summary.json"
START = 154
END = 230


# 제품명과 제형 또는 포장 수량이 함께 맞는 경우만 수동 확정한다.
# 값은 우선 사용할 후보 소스와 검증 근거다.
CONFIRMED: dict[str, tuple[str, str]] = {
    "20260129_110451": ("secondary", "exact_product_and_cream_form_match"),
    "20260129_110453": ("secondary", "exact_product_and_booster_form_match"),
    "20260129_110518": ("naver", "exact_product_and_ampoule_form_match"),
    "20260129_110533": ("naver", "exact_product_and_100ml_capacity_match"),
    "20260129_111237": ("naver", "exact_product_and_capsule_form_match"),
    "20260129_111721": ("naver", "exact_brand_formula_and_liquid_form_match"),
    "20260129_112030": ("naver", "exact_product_match_with_catalog_spelling_error"),
    "20260129_112042": ("naver", "exact_product_name_match"),
    "20260129_112050": ("secondary", "exact_product_and_60_count_match"),
    "20260129_112106": ("secondary", "exact_product_and_30_sachet_match"),
    "20260129_112134": ("naver", "exact_product_match_with_catalog_typo"),
    "20260129_112139": ("naver", "exact_product_and_capsule_form_match"),
    "20260129_112621": ("naver", "exact_product_and_tablet_form_match"),
    "20260129_113244": ("naver", "exact_product_name_match"),
    "20260129_113323": ("naver", "exact_product_variant_match"),
    "20260129_113630": ("naver", "exact_product_name_match"),
    "20260129_113635": ("secondary", "exact_product_and_10_bottle_match"),
    "20260129_114102": ("secondary", "exact_product_and_30_tablet_match"),
    "20260129_114104": ("naver", "exact_product_name_match"),
}


REVIEW_REASONS = {
    "20260129_110519": "candidate_does_not_identify_the_exact_50g_product",
    "20260129_110842": "candidate_does_not_confirm_the_1g_five_sachet_product",
    "20260129_110918": "candidate_is_paint_not_the_catalog_product",
    "20260129_110940": "candidate_is_paint_not_the_catalog_product",
    "20260129_111233": "candidate_does_not_confirm_the_360_capsule_package",
    "20260129_111242": "catalog_is_270_capsules_but_candidate_is_5_percent_liquid",
    "20260129_111250": "catalog_is_180_capsules_but_candidate_is_topical_product",
    "20260129_111258": "catalog_is_360_capsules_but_candidate_is_topical_gel",
    "20260129_111340": "comparison_article_does_not_identify_the_240ml_item",
    "20260129_111346": "no_candidate_found",
    "20260129_111414": "candidate_is_unrelated_and_does_not_match_the_60g_foam",
    "20260129_111420": "candidate_does_not_confirm_the_60g_variant",
    "20260129_111437": "candidate_is_a_different_fromfarm_product",
    "20260129_111453": "catalog_is_360ml_liquid_but_candidate_is_gel",
    "20260129_111459": "catalog_is_60ml_liquid_but_candidate_is_gel",
    "20260129_111516": "generic_ingredient_result_does_not_identify_the_composite_catalog_item",
    "20260129_111718": "candidate_compares_multiple_formula_variants",
    "20260129_111725": "catalog_is_liquid_but_candidate_is_pill",
    "20260129_111727": "catalog_is_liquid_but_candidate_is_pill",
    "20260129_111729": "catalog_is_bottled_liquid_but_candidate_is_pill",
    "20260129_111732": "catalog_is_bottled_liquid_but_candidate_is_pill",
    "20260129_111735": "candidate_formula_and_liquid_package_do_not_match",
    "20260129_112046": "candidate_is_a_different_probiotic_product",
    "20260129_112103": "candidate_is_generic_or_unrelated",
    "20260129_112109": "candidate_is_a_pet_probiotic_or_different_product",
    "20260129_112117": "candidate_is_a_different_named_variant_pronic",
    "20260129_112348": "generic_name_does_not_identify_brand_or_package",
    "20260129_112351": "generic_ingredient_result_does_not_identify_product",
    "20260129_112354": "candidate_is_unrelated",
    "20260129_112356": "candidate_is_unrelated",
    "20260129_112359": "candidate_shows_multiple_products_and_not_the_exact_package",
    "20260129_112608": "same_name_has_multiple_catalog_packages_and_candidate_does_not_disambiguate",
    "20260129_112619": "candidate_does_not_confirm_the_exact_capsule_product",
    "20260129_112638": "candidate_is_unrelated",
    "20260129_112644": "candidate_is_a_different_product",
    "20260129_112656": "candidate_is_a_different_generic_formula",
    "20260129_112658": "candidate_is_paint_not_the_catalog_product",
    "20260129_112701": "same_name_has_multiple_catalog_packages_and_candidate_does_not_disambiguate",
    "20260129_113153": "candidate_is_a_different_product",
    "20260129_113156": "candidate_title_does_not_confirm_variant_or_120_tablet_package",
    "20260129_113213": "candidate_is_a_watch_or_unrelated_product",
    "20260129_113223": "candidate_is_unrelated",
    "20260129_113241": "candidate_is_unrelated",
    "20260129_113301": "candidate_is_a_different_variant_or_power_strip",
    "20260129_113317": "candidate_only_identifies_the_G_variant_not_the_catalog_variant",
    "20260129_113326": "candidate_only_identifies_the_G_variant_not_the_catalog_variant",
    "20260129_113330": "candidate_only_identifies_the_G_variant_not_the_catalog_variant",
    "20260129_113619": "candidate_is_unrelated",
    "20260129_113648": "candidate_does_not_confirm_brand_and_60_tablet_package",
    "20260129_113703": "candidate_is_unrelated",
    "20260129_113710": "candidate_brand_does_not_match_harucare",
    "20260129_113732": "candidate_is_a_different_vitamin_C_product",
    "20260129_113958": "catalog_is_20_sachets_but_candidate_is_140_sachets",
    "20260129_114009": "catalog_is_120_tablets_but_candidate_is_30_sachets",
    "20260129_114011": "catalog_is_120_sachets_but_candidate_is_100_sachets",
    "20260129_114110": "catalog_is_36_tablets_but_candidate_is_90_tablets",
    "20260129_114113": "candidate_is_a_bra_or_unrelated_product",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def source_kind(filename: str) -> str:
    return "naver" if filename.startswith("naver-") else "secondary"


def collect_candidates() -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = {}
    paths = sorted(DATA.glob("secondary-image-part-*.json")) + sorted(DATA.glob("naver-image-part-*.json"))
    for path in paths:
        if "summary" in path.name:
            continue
        for row in load(path):
            item = dict(row)
            item["_source_kind"] = source_kind(path.name)
            item["_source_file"] = path.name
            output.setdefault(str(row.get("catalog_product_id") or ""), []).append(item)
    return output


def has_candidate(row: dict[str, Any]) -> bool:
    return bool(row.get("candidate_name") and row.get("image_url"))


def choose_candidate(product_id: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    usable = [candidate for candidate in candidates if has_candidate(candidate)]
    if not usable:
        return candidates[0] if candidates else {}
    if product_id in CONFIRMED:
        preferred_kind = CONFIRMED[product_id][0]
        preferred = [candidate for candidate in usable if candidate["_source_kind"] == preferred_kind]
        if preferred:
            return max(preferred, key=lambda candidate: int(candidate.get("match_score") or 0))
    # 검토 대상은 네이버 원문 후보를 우선 보여주되 자동 확정하지 않는다.
    return max(
        usable,
        key=lambda candidate: (
            candidate["_source_kind"] == "naver",
            int(candidate.get("match_score") or 0),
        ),
    )


def main() -> None:
    queue = load(DATA / "enrichment-queue.json")
    missing = [row for row in queue if not str(row.get("image_url") or "").strip()]
    products = missing[START:END]
    if len(products) != 76:
        raise RuntimeError(f"expected 76 products, got {len(products)}")
    candidates_by_id = collect_candidates()
    records: list[dict[str, Any]] = []
    for product in products:
        product_id = str(product.get("document_id") or product.get("id") or "")
        candidate = choose_candidate(product_id, candidates_by_id.get(product_id, []))
        confirmed = product_id in CONFIRMED and has_candidate(candidate)
        review_reason = (
            CONFIRMED[product_id][1]
            if confirmed
            else REVIEW_REASONS.get(
                product_id,
                "no_candidate_found" if not has_candidate(candidate) else "exact_variant_or_capacity_not_confirmed",
            )
        )
        records.append(
            {
                "catalog_product_id": product_id,
                "catalog_name": product.get("name", ""),
                "candidate_name": candidate.get("candidate_name", ""),
                "image_url": candidate.get("image_url", ""),
                "source_url": candidate.get("source_url", ""),
                "result_url": candidate.get("result_url", ""),
                "match_score": int(candidate.get("match_score") or 0),
                "status": "confirmed" if confirmed else "review_required",
                "manual_verified": confirmed,
                "review_reason": review_reason,
            }
        )
    write(OUTPUT, records)
    counts = Counter(record["status"] for record in records)
    summary = {
        "generated_at": now_iso(),
        "missing_image_count": len(missing),
        "slice": {"start": START, "end_exclusive": END, "record_count": len(records)},
        "status_counts": dict(counts),
        "manual_verified_count": sum(record["manual_verified"] for record in records),
        "candidate_present_count": sum(bool(record["image_url"]) for record in records),
        "source_files": [
            path.name
            for path in sorted(DATA.glob("*-image-part-*.json"))
            if "summary" not in path.name
        ],
    }
    write(SUMMARY, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
