import unittest

from scripts.collect_kpic_images import (
    is_kpic_image,
    first_kpic_image,
    clear_kpic_product_match,
    link_product,
    parse_candidates,
    query_variants,
    record_is_safe_match,
    safe_name_match,
    score_name,
    validated_match_score,
)


class KpicImageTests(unittest.TestCase):
    def test_parse_search_result_extracts_code_name_company_and_pack_image(self):
        document = """
        <table><tr>
          <td class="img"><img src="https://common.health.kr/shared/images/ext_images/pack_img/P_1_00.jpg" alt="포장이미지"></td>
          <td class="txtL" onclick="javascript:drug_detailHref('1')">테스트연고</td>
          <td>성분</td><td>효능</td><td>테스트제약</td>
        </tr></table>
        """
        candidates = parse_candidates(document, "테스트연고")
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].code, "1")
        self.assertEqual(candidates[0].manufacturer, "테스트제약")
        self.assertEqual(candidates[0].score, 100)

    def test_known_ocr_spelling_is_normalized(self):
        self.assertEqual(score_name("어린이타이레놀현탄액", "어린이타이레놀현탁액"), 100)

    def test_distinctive_brand_token_can_match_official_dosage_form(self):
        self.assertEqual(score_name("부채표 판콜에스", "판콜에스내복액"), 96)

    def test_concatenated_indication_suffix_produces_dosage_form_query(self):
        self.assertIn("챔프시럽", query_variants("챔프시럽해열진통"))

    def test_exact_product_prefix_with_indication_suffix_is_safe(self):
        self.assertTrue(safe_name_match("챔프시럽해열진통", "챔프시럽"))

    def test_significant_parenthetical_qualifier_conflict_is_rejected(self):
        self.assertFalse(safe_name_match("광동우황청심원(사향)액", "광동우황청심원(영묘향)액"))

    def test_strength_conflict_is_rejected(self):
        self.assertFalse(safe_name_match("테스트정100mg", "테스트정200mg"))

    def test_capacity_form_rejects_capsule_to_syrup_match(self):
        self.assertFalse(safe_name_match("훼로모아", "훼로모아시럽", "120C"))

    def test_capacity_form_rejects_tablet_to_gel_match(self):
        self.assertFalse(safe_name_match("스트롱조인트", "조아스트롱조인트겔", "240정"))

    def test_short_exact_core_with_compatible_form_gets_confirmable_score(self):
        self.assertEqual(validated_match_score("폴시드", "폴시드정", "120정"), 98)
        self.assertEqual(validated_match_score("젠빅", "젠빅연질캡슐", "120캡슐"), 98)

    def test_generic_dosage_form_does_not_create_a_false_match(self):
        self.assertLess(score_name("피톤치드 에어로졸", "로게인5%폼에어로졸"), 96)

    def test_common_ingredient_alone_does_not_create_a_product_match(self):
        self.assertLess(
            score_name("식물성 멜라토닌 멜라잇 플러스", "바이헬스멜라토닌구강붕해필름3.3mg"),
            96,
        )

    def test_only_kpic_https_product_image_hosts_are_allowed(self):
        self.assertTrue(is_kpic_image("https://common.health.kr/shared/images/ext_images/pack_img/P_1.jpg"))
        self.assertTrue(is_kpic_image("https://common.health.kr/shared/images/sb_photo/big3/1.jpg"))
        self.assertFalse(is_kpic_image("https://example.com/P_1.jpg"))
        self.assertFalse(is_kpic_image("http://common.health.kr/shared/images/ext_images/pack_img/P_1.jpg"))

    def test_multiple_kpic_image_urls_are_split_before_linking(self):
        first = "https://common.health.kr/shared/images/ext_images/pack_img/P_1.jpg"
        second = "https://common.health.kr/shared/images/ext_images/pack_img/P_2.jpg"
        self.assertEqual(first_kpic_image(f"{first}@{second}"), first)
        self.assertFalse(is_kpic_image(f"{first}@{second}"))

    def test_official_match_is_linked_without_an_image(self):
        product = {"id": "p1", "name": "테스트정"}
        link_product(
            product,
            {
                "kpic_name": "테스트정",
                "manufacturer": "테스트제약",
                "kpic_code": "CODE1",
                "source_url": "https://health.kr/searchDrug/result_drug.asp?drug_cd=CODE1",
                "match_score": 100,
                "checked_at": "2026-07-15T00:00:00+09:00",
                "image_url": "",
            },
        )
        self.assertEqual(product["official_match_status"], "confirmed")
        self.assertNotIn("image_url", product)

    def test_force_clear_removes_stale_kpic_details(self):
        product = {
            "official_source_type": "약학정보원 의약품 상세정보",
            "official_match_status": "confirmed",
            "official_content_status": "complete",
            "official_efficacy": "이전 효능",
            "official_images": [{"url": "https://common.health.kr/wrong.jpg"}],
        }
        clear_kpic_product_match(product)
        self.assertEqual(product["official_match_status"], "pending")
        self.assertNotIn("official_content_status", product)
        self.assertNotIn("official_efficacy", product)
        self.assertNotIn("official_images", product)

    def test_legacy_missing_image_record_must_pass_current_safety_rules(self):
        unsafe = {
            "catalog_name": "훼로모아",
            "catalog_capacity": "120C",
            "kpic_name": "훼로모아시럽",
            "kpic_code": "WRONG",
        }
        safe = {
            "catalog_name": "훼로모아",
            "catalog_capacity": "120C",
            "kpic_name": "훼로모아캡슐",
            "kpic_code": "RIGHT",
        }
        self.assertFalse(record_is_safe_match(unsafe))
        self.assertTrue(record_is_safe_match(safe))


if __name__ == "__main__":
    unittest.main()
