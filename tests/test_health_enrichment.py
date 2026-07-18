import json
import unittest
from pathlib import Path

from scripts.health_enrichment import (
    OFFICIAL_DEFAULTS,
    clean_text,
    detect_form_conflict,
    extract_pack_count,
    make_search_variants,
    process_record,
    score_candidate,
    search_candidates,
    split_upstream,
    valid_official_image,
)
from scripts.normalize_consumer_guidance import normalize_product


ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = json.loads(
    (ROOT / "etc" / "health-enrichment" / "enrichment-queue.original.json").read_text(encoding="utf-8")
)


class EnrichmentTests(unittest.TestCase):
    def test_consumer_guidance_keeps_semantic_fields_and_moves_raw_page(self):
        product = {
            "official_consumer_guidance": {
                "summary": "무슨 약인지 설명",
                "guide": "복용 안내",
                "source_url": "https://health.kr/take",
                "full_text": "페이지 전체 원문",
            },
            "official_additional_data": {"health_kr_raw": {}},
        }
        self.assertTrue(normalize_product(product))
        self.assertEqual(
            product["official_consumer_guidance"],
            {"summary": "무슨 약인지 설명", "guide": "복용 안내"},
        )
        medication = product["official_additional_data"]["health_kr_raw"]["auxiliary_pages"]["medication"]
        self.assertEqual(medication["source_url"], "https://health.kr/take")
        self.assertEqual(medication["text"], "페이지 전체 원문")

    def test_original_has_776_unique_rows(self):
        self.assertEqual(len(ORIGINAL), 776)
        self.assertEqual(len({row["document_id"] for row in ORIGINAL}), 776)

    def test_all_required_original_fields_are_present(self):
        required = {
            "document_id",
            "name",
            "capacity",
            "category",
            "price",
            "specification",
            "displayed_price_krw",
            "source_order",
        }
        for row in ORIGINAL:
            self.assertTrue(required.issubset(row), row["document_id"])

    def test_clean_text_preserves_paragraphs(self):
        self.assertEqual(clean_text("첫 문단<br><br><P></P>둘째 문단"), "첫 문단\n\n둘째 문단")

    def test_clean_text_preserves_long_source(self):
        source = "1. 경고<br>" + ("주의 문장 " * 1000)
        cleaned = clean_text(source)
        self.assertGreater(len(cleaned), 5000)
        self.assertTrue(cleaned.endswith("주의 문장"))

    def test_clean_text_decodes_tags_once_and_is_idempotent(self):
        source = "비타민 B &lt;SUB&gt;12&lt;/SUB&gt;&lt;br&gt;복용"
        cleaned = clean_text(source)
        self.assertEqual(cleaned, "비타민 B 12\n복용")
        self.assertEqual(clean_text(cleaned), cleaned)

    def test_variants_keep_product_distinguishers(self):
        variants = make_search_variants("산타몬 플러스 120c", "120c")
        self.assertIn("산타몬플러스", variants)

    def test_typo_variant_is_corrected(self):
        variants = make_search_variants("챕프이부펜해열소염", "10포")
        self.assertTrue(any(value.startswith("챔프이부펜") for value in variants))

    def test_vitamin_letter_variant_is_koreanized(self):
        variants = make_search_variants("유한비타민C정1000mg", "600정")
        self.assertTrue(any("비타민씨정" in value for value in variants))

    def test_split_upstream_does_not_join_additives(self):
        value = "미결정셀룰로오스</br>산화티탄</br>스테아르산마그네슘"
        self.assertEqual(split_upstream(value), ["미결정셀룰로오스", "산화티탄", "스테아르산마그네슘"])

    def test_image_domain_is_restricted(self):
        self.assertTrue(valid_official_image("https://common.health.kr/shared/a.jpg"))
        self.assertFalse(valid_official_image("https://shopping.example/a.jpg"))
        self.assertFalse(valid_official_image("https://common.health.kr/shared/noimage.jpg"))

    def test_form_conflict_blocks_confirmation(self):
        row = {"name": "예시시럽", "capacity": "100mL"}
        candidate = {"drug_name": "예시정", "drug_form": "정제", "drug_code": "1"}
        score, _, conflicts = score_candidate(row, candidate)
        self.assertTrue(conflicts)
        self.assertLess(score, 80)

    def test_same_form_has_no_conflict(self):
        self.assertEqual(detect_form_conflict("치젤연고", "연고", "치젤연고"), "")

    def test_single_character_form_is_only_a_suffix(self):
        self.assertEqual(detect_form_conflict("산타몬플러스액", "액제", "산타몬플러스액"), "")

    def test_liquid_and_pill_conflict(self):
        conflict = detect_form_conflict("광동우황청심원(영묘향)액", "환제", "광동우황청심원")
        self.assertIn("제형 충돌", conflict)

    def test_catalog_c_means_capsules(self):
        self.assertEqual(extract_pack_count("120c"), ("120", "캡슐"))

    def test_exact_product_is_not_blocked_by_retail_multipack_count(self):
        row = {
            "name": "까스활명수-큐액",
            "capacity": "75mL×10병",
            "specification": "75mL×10병",
        }
        candidate = {
            "drug_name": "까스활명수큐액",
            "drug_form": "액제",
            "drug_code": "A11A0570A0357",
            "upso_name_kfda": "동화약품",
        }
        detail = {
            **candidate,
            "upso_name": "동화약품",
            "drug_box": "75mL/병",
        }

        score, reasons, conflicts = score_candidate(row, candidate, detail=detail)

        self.assertGreaterEqual(score, 84)
        self.assertFalse(conflicts)
        self.assertIn("판매단위와 허가 포장단위 차이", reasons)

    def test_korean_volume_pack_text_matches_ml_capacity(self):
        row = {
            "name": "마이녹실액5%",
            "capacity": "360ml",
            "specification": "360ml",
        }
        candidate = {
            "drug_name": "마이녹실액5%",
            "drug_form": "액제",
            "drug_code": "A11A3060A0346",
            "upso_name_kfda": "현대약품",
        }
        detail = {
            **candidate,
            "upso_name": "현대약품",
            "drug_box": "마이녹실액5%(미녹시딜) - 360밀리리터/병",
        }

        score, _, conflicts = score_candidate(row, candidate, detail=detail)

        self.assertGreaterEqual(score, 84)
        self.assertFalse(any("용량 규격 충돌" in conflict for conflict in conflicts))

    def test_parenthetical_prescription_name_does_not_override_main_dosage_form(self):
        row = {
            "name": "정정보환(온신산)",
            "capacity": "120포",
            "specification": "120포",
        }
        candidate = {
            "drug_name": "정정보환(온신산)",
            "drug_form": "환제",
            "drug_code": "A11AGGGGG7028",
        }
        detail = {
            **candidate,
            "drug_box": "120포/상자",
        }

        score, _, conflicts = score_candidate(row, candidate, detail=detail)

        self.assertGreaterEqual(score, 84)
        self.assertFalse(any("제형 충돌" in conflict for conflict in conflicts))

    def test_common_latin_brand_letters_match_spoken_official_names(self):
        cases = (
            ("무조날S 네일라카", "6mL", "무조날에스네일라카", "라카"),
            ("액티넘EX골드정", "90정×2병", "액티넘이엑스골드정", "정제"),
            ("성광포비스틱스왑액", "2매×6개입", "성광포스틱스왑액", "약물이 포함된 위생용품"),
        )
        for catalog_name, capacity, official_name, form in cases:
            with self.subTest(catalog_name=catalog_name):
                row = {"name": catalog_name, "capacity": capacity, "specification": capacity}
                candidate = {"drug_name": official_name, "drug_form": form, "drug_code": "1"}
                score, _, conflicts = score_candidate(row, candidate)
                self.assertGreaterEqual(score, 84)
                self.assertFalse(conflicts)

    def test_official_pack_variant_resolves_catalog_flavor_suffix(self):
        row = {"name": "잇치 페이스트 프로폴리스향", "capacity": "140g"}
        candidate = {"drug_name": "잇치페이스트", "drug_form": "페이스트", "drug_code": "1"}
        detail = {
            **candidate,
            "drug_box": "[오리지날향] 120g/튜브, [피톤치드향] 150g/튜브, [프로폴리스향] 140g/튜브",
        }

        score, _, conflicts = score_candidate(row, candidate, detail=detail)

        self.assertGreaterEqual(score, 84)
        self.assertFalse(conflicts)

    def test_detail_evidence_can_clear_preliminary_variant_conflict(self):
        candidate = {"drug_name": "잇치페이스트", "drug_form": "페이스트", "drug_code": "1"}
        detail = {
            **candidate,
            "drug_box": "[오리지날향] 120g/튜브, [프로폴리스향] 140g/튜브",
        }

        class FakeClient:
            def search(self, query):
                return [candidate]

            def autocomplete(self, query):
                return []

            def detail(self, code):
                return detail

            def image_exists(self, url):
                return False

        result = process_record(
            FakeClient(),
            {"document_id": "test", "name": "잇치 페이스트 프로폴리스향", "capacity": "140g"},
            include_aux=False,
        )

        self.assertEqual(result["official_match_status"], "confirmed")
        self.assertEqual(result["official_item_seq"], "1")

    def test_search_candidates_also_uses_raw_app_name(self):
        candidate = {"drug_name": "가넥트액", "drug_form": "액제", "drug_code": "1"}

        class FakeClient:
            def search(self, query):
                return [candidate] if query == "가넥트액" else []

            def autocomplete(self, query):
                return []

        results = search_candidates(
            FakeClient(),
            {
                "name": "동아제약 가넥트액",
                "app_name": "가넥트액",
                "capacity": "100mL×10병",
            },
        )

        self.assertEqual([row["drug_code"] for row in results], ["1"])

    def test_parenthetical_official_prescription_can_match_short_display_name(self):
        row = {"name": "안정액", "capacity": "50ml×10병", "specification": "50ml×10병"}
        candidate = {"drug_name": "안정액(천왕보심단)", "drug_form": "액제", "drug_code": "1"}
        detail = {**candidate, "drug_box": "1병/상자[50mL/병]"}

        score, _, conflicts = score_candidate(row, candidate, detail=detail)

        self.assertGreaterEqual(score, 84)
        self.assertFalse(conflicts)

    def test_package_volume_in_name_is_not_compared_with_ingredient_volume(self):
        row = {"name": "광동우황청심원(사향)액50ml", "capacity": "10병"}
        candidate = {
            "drug_name": "광동우황청심원현탁액",
            "drug_form": "현탁액",
            "drug_code": "1",
            "upso_name_kfda": "광동제약",
        }
        detail = {
            **candidate,
            "upso_name": "광동제약",
            "sunb": "Musk 사향 5mg|생약추출액 30mL",
            "drug_box": "1병/상자[1병(50mL)]",
        }

        score, _, conflicts = score_candidate(row, candidate, detail=detail)

        self.assertGreaterEqual(score, 84)
        self.assertFalse(any("함량 충돌" in conflict for conflict in conflicts))

    def test_short_brand_inside_different_official_name_is_not_confirmed(self):
        row = {"name": "비맥스", "capacity": "120정"}
        candidate = {"drug_name": "에비맥스디정", "drug_form": "정제", "drug_code": "1"}
        detail = {**candidate, "drug_box": "30정/병"}

        score, _, conflicts = score_candidate(row, candidate, detail=detail)

        self.assertLess(score, 84)
        self.assertTrue(any("중간 부분문자열" in conflict for conflict in conflicts))

    def test_capacity_form_blocks_supplement_capsule_to_drug_tablet(self):
        row = {"name": "관절팔팔", "capacity": "30C", "specification": "30C"}
        candidate = {"drug_name": "팔팔정50mg", "drug_form": "정제", "drug_code": "1"}
        score, _, conflicts = score_candidate(row, candidate)
        self.assertTrue(any("제형 충돌" in conflict for conflict in conflicts))
        self.assertLess(score, 80)

    def test_capacity_form_blocks_tablet_to_capsule(self):
        row = {"name": "녹십자 하루케어 멀티비타민V", "capacity": "30정", "specification": "30정"}
        candidate = {"drug_name": "하루케어캡슐", "drug_form": "경질캡슐", "drug_code": "1"}
        score, _, conflicts = score_candidate(row, candidate)
        self.assertTrue(any("제형 충돌" in conflict for conflict in conflicts))
        self.assertLess(score, 80)

    def test_capacity_form_blocks_tablet_to_gel(self):
        row = {"name": "스트롱조인트", "capacity": "240정", "specification": "240정"}
        candidate = {"drug_name": "조아스트롱조인트겔", "drug_form": "겔제", "drug_code": "1"}
        score, _, conflicts = score_candidate(row, candidate)
        self.assertTrue(any("제형 충돌" in conflict for conflict in conflicts))
        self.assertLess(score, 80)

    def test_catalog_only_suffix_blocks_broader_official_name(self):
        row = {"name": "녹십자 하루케어 루테인", "capacity": "30C"}
        candidate = {"drug_name": "하루케어캡슐", "drug_form": "경질캡슐", "drug_code": "1"}
        score, _, conflicts = score_candidate(row, candidate)
        self.assertTrue(any("카탈로그에만 있는 구분어" in conflict for conflict in conflicts))
        self.assertLess(score, 80)

    def test_full_promo_phrase_is_removed_before_shorter_phrase(self):
        row = {"name": "종합감기약 타세놀 콜드캡슐", "capacity": "10캡슐"}
        candidate = {"drug_name": "타세놀콜드캡슐", "drug_form": "경질캡슐", "drug_code": "1"}
        score, _, conflicts = score_candidate(row, candidate)
        self.assertFalse(conflicts)
        self.assertGreaterEqual(score, 80)

    def test_typo_normalization_is_reapplied_after_promo_words_are_removed(self):
        row = {"name": "고함량 비타민 하이렉스", "capacity": "360정"}
        candidate = {"drug_name": "하이렉스정", "drug_form": "정제", "drug_code": "1"}
        detail = {**candidate, "drug_box": "120정/병"}

        score, _, conflicts = score_candidate(row, candidate, detail=detail)

        self.assertGreaterEqual(score, 84)
        self.assertFalse(conflicts)

    def test_trailing_pack_s_is_not_a_product_distinguisher(self):
        row = {"name": "둘코락스좌약5S", "capacity": "5개"}
        candidate = {"drug_name": "둘코락스좌약", "drug_form": "좌제", "drug_code": "1"}
        score, _, conflicts = score_candidate(row, candidate)
        self.assertFalse(any("구분어" in conflict for conflict in conflicts))
        self.assertGreaterEqual(score, 80)

    def test_chewable_is_treated_as_a_tablet_form(self):
        row = {"name": "보나링츄어블", "capacity": "4정"}
        candidate = {"drug_name": "보나링츄어블정", "drug_form": "저작정(츄어블정)", "drug_code": "1"}
        score, _, conflicts = score_candidate(row, candidate)
        self.assertFalse(conflicts)
        self.assertGreaterEqual(score, 80)

    def test_name_form_is_not_hidden_by_duplicate_capacity_fields(self):
        row = {
            "name": "광동우황청심환",
            "capacity": "50mL",
            "specification": "50mL",
        }
        candidate = {
            "drug_name": "광동원방우황청심원현탁액",
            "drug_form": "현탁액",
            "drug_code": "1",
        }
        score, _, conflicts = score_candidate(row, candidate)
        self.assertTrue(any("제형 충돌" in conflict for conflict in conflicts))
        self.assertLess(score, 80)

    def test_explicit_company_prefixes_cannot_disagree(self):
        row = {"name": "광동우황청심환", "capacity": "1환"}
        candidate = {"drug_name": "한풍우황청심원", "drug_form": "환제", "drug_code": "1"}
        score, _, conflicts = score_candidate(row, candidate)
        self.assertTrue(any("제품사 표기 충돌" in conflict for conflict in conflicts))
        self.assertLess(score, 80)

    def test_solid_name_and_liquid_capacity_require_review(self):
        row = {"name": "광동우황청심환", "capacity": "50mL", "specification": "50mL"}
        candidate = {"drug_name": "광동우황청심환", "drug_form": "환제", "drug_code": "1"}
        score, _, conflicts = score_candidate(row, candidate)
        self.assertTrue(any("제품명 제형과 용량 단위 충돌" in conflict for conflict in conflicts))
        self.assertLess(score, 80)

    def test_company_prefix_must_match_official_manufacturer(self):
        row = {"name": "한신갈근탕", "capacity": "10포"}
        candidate = {
            "drug_name": "정우갈근탕엑스과립",
            "drug_form": "과립제",
            "drug_code": "1",
            "upso_name_kfda": "정우신약",
        }
        score, _, conflicts = score_candidate(row, candidate)
        self.assertTrue(any("제품사·제조사 충돌" in conflict for conflict in conflicts))
        self.assertLess(score, 80)

    def test_brand_alias_can_match_official_manufacturer(self):
        row = {"name": "부채표 판콜에스", "capacity": "10병"}
        candidate = {
            "drug_name": "판콜에스내복액",
            "drug_form": "액제",
            "drug_code": "1",
            "upso_name_kfda": "동화약품",
        }
        _, _, conflicts = score_candidate(row, candidate)
        self.assertFalse(any("제품사·제조사 충돌" in conflict for conflict in conflicts))

    def test_herbal_extract_granule_is_a_form_descriptor(self):
        row = {"name": "한신갈근탕", "capacity": "120포"}
        candidate = {
            "drug_name": "한신갈근탕엑스과립",
            "drug_form": "과립",
            "drug_code": "1",
            "upso_name_kfda": "한국신약",
        }
        score, _, conflicts = score_candidate(row, candidate)
        self.assertFalse(conflicts)
        self.assertGreaterEqual(score, 80)

    def test_middle_substring_cannot_define_a_product_match(self):
        row = {"name": "글루타치온실크알부민", "capacity": "30정"}
        candidate = {"drug_name": "타치온정50mg", "drug_form": "정제", "drug_code": "1"}
        score, _, conflicts = score_candidate(row, candidate)
        self.assertTrue(any("중간 부분문자열" in conflict for conflict in conflicts))
        self.assertLess(score, 80)

    def test_bare_numeric_suffix_is_a_product_distinguisher(self):
        row = {"name": "메가트루633", "capacity": "120정"}
        candidate = {"drug_name": "메가트루정", "drug_form": "정제", "drug_code": "1"}
        score, _, conflicts = score_candidate(row, candidate)
        self.assertTrue(any("카탈로그에만 있는 구분어" in conflict for conflict in conflicts))
        self.assertLess(score, 80)

    def test_known_spoken_digit_product_name_matches_official_name(self):
        row = {"name": "메가트루633", "capacity": "120정"}
        candidate = {"drug_name": "메가트루육삼삼정", "drug_form": "정제", "drug_code": "1"}
        score, _, conflicts = score_candidate(row, candidate)
        self.assertFalse(conflicts)
        self.assertGreaterEqual(score, 80)

    def test_numeric_product_marker_present_in_both_names_is_not_dropped(self):
        row = {"name": "메가콘티800", "capacity": "60T"}
        candidate = {"drug_name": "메가콘티800정", "drug_form": "정제", "drug_code": "1"}
        score, _, conflicts = score_candidate(row, candidate)
        self.assertFalse(conflicts)
        self.assertGreaterEqual(score, 80)

    def test_manufacturer_prefix_does_not_hide_product_match(self):
        row = {"name": "부채표 판콜에스", "capacity": "10병"}
        candidate = {"drug_name": "판콜에스내복액", "drug_form": "액제", "drug_code": "1", "upso_name_kfda": "동화약품"}
        score, reasons, conflicts = score_candidate(row, candidate)
        self.assertGreaterEqual(score, 80)
        self.assertTrue(any(value.startswith("핵심 제품명") for value in reasons))
        self.assertFalse(conflicts)

    def test_product_distinguisher_cannot_be_invented(self):
        row = {"name": "비맥스", "capacity": "120정"}
        candidate = {"drug_name": "비맥스골드정", "drug_form": "정제", "drug_code": "1"}
        _, _, conflicts = score_candidate(row, candidate)
        self.assertIn("제품 구분어 충돌: 골드", conflicts)

    def test_product_prefix_distinguisher_cannot_be_invented(self):
        row = {"name": "비맥스", "capacity": "120정"}
        candidate = {"drug_name": "마그비맥스연질캡슐", "drug_form": "연질캡슐", "drug_code": "1"}
        _, _, conflicts = score_candidate(row, candidate)
        self.assertTrue(any("앞 구분어" in value for value in conflicts))

    def test_parenthetical_free_variant_is_searched(self):
        self.assertIn("탁센", make_search_variants("탁센(나프록센)", "10C"))

    def test_export_only_product_is_rejected(self):
        row = {"name": "로페라미드캡슐", "capacity": "10캡슐"}
        candidate = {"drug_name": "대화염산로페라미드캡슐(수출용)", "drug_form": "경질캡슐", "drug_code": "1"}
        _, _, conflicts = score_candidate(row, candidate)
        self.assertIn("카탈로그에 없는 수출용 제품", conflicts)

    def test_generic_name_cannot_choose_a_manufacturer(self):
        row = {"name": "디오스민 캡슐", "capacity": "60캡슐"}
        candidate = {"drug_name": "조아디오스민캡슐", "drug_form": "경질캡슐", "drug_code": "1"}
        _, _, conflicts = score_candidate(row, candidate)
        self.assertTrue(any("제조사 제품을 특정" in value for value in conflicts))

    def test_parenthetical_ingredient_must_match_detail(self):
        row = {"name": "광동우황청심원(영묘향)액", "capacity": "50mL"}
        candidate = {"drug_name": "광동우황청심원", "drug_form": "환제", "drug_code": "1"}
        detail = {"drug_name": "광동우황청심원", "drug_form": "환제", "drug_code": "1", "sunb": "Musk 사향 5mg", "drug_box": "1환"}
        _, _, conflicts = score_candidate(row, candidate, detail=detail)
        self.assertTrue(any("영묘향" in value for value in conflicts))
        self.assertTrue(any("제형 충돌" in value for value in conflicts))

    def test_required_official_types(self):
        self.assertIsInstance(OFFICIAL_DEFAULTS["official_match_score"], int)
        for key in (
            "official_standard_codes",
            "official_ingredients",
            "official_active_ingredients",
            "official_additives",
            "official_interactions",
            "official_same_ingredient_products",
            "official_images",
            "official_pictograms",
        ):
            self.assertIsInstance(OFFICIAL_DEFAULTS[key], list)
        for key in (
            "official_manufacturer_details",
            "official_consumer_guidance",
            "official_section_evidence",
            "official_additional_data",
        ):
            self.assertIsInstance(OFFICIAL_DEFAULTS[key], dict)


if __name__ == "__main__":
    unittest.main()
