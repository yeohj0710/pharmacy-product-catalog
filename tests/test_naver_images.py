import json
import unittest

from scripts.collect_naver_images import parse_image_results, safe_candidate


class NaverImageTests(unittest.TestCase):
    def test_embedded_image_payload_is_parsed(self):
        payload = [
            {
                "type": "image",
                "title": "동아제약 테스트 상품 30정",
                "link": "https://example.com/product",
                "viewerThumb": "https://search.pstatic.net/common/product.jpg",
                "rank": 1,
                "source": "블로그",
            }
        ]
        document = f"before: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}; after"
        rows = parse_image_results(document, "테스트 상품")
        self.assertEqual(len(rows), 1)
        self.assertTrue(safe_candidate("테스트 상품", rows[0]))

    def test_short_ambiguous_name_is_not_safe(self):
        candidate = {"candidate_name": "판피린 프라하 여행", "match_score": 96}
        self.assertFalse(safe_candidate("판피린", candidate))


if __name__ == "__main__":
    unittest.main()
