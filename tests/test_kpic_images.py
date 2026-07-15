import unittest

from scripts.collect_kpic_images import is_kpic_image, parse_candidates, score_name


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


if __name__ == "__main__":
    unittest.main()
