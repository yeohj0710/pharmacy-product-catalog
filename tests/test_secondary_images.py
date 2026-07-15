import unittest

from scripts.collect_secondary_images import match_score, parse_results, valid_image_url


class SecondaryImageTests(unittest.TestCase):
    def test_matching_product_result_is_extracted(self):
        document = """
        <li class="prod_item searched"><div class="thumb_image"><a href="https://example.com/item">
        <img src="//img.example.com/product.jpg" alt="상품"></a></div>
        <div><p class="prod_name"><a href="https://example.com/item">헬씨허그 <b>식물성</b> <b>멜라토닌</b> 함유 <b>멜라잇 플러스</b> 30정</a></p></div></li>
        """
        rows = parse_results(document, "식물성 멜라토닌 멜라잇 플러스")
        self.assertEqual(len(rows), 1)
        self.assertGreaterEqual(rows[0]["match_score"], 92)
        self.assertEqual(rows[0]["image_url"], "https://img.example.com/product.jpg")

    def test_unrelated_product_is_not_confirmed(self):
        self.assertLess(match_score("멜라잇 플러스", "로게인 에어로졸"), 92)

    def test_short_name_inside_unrelated_listing_is_not_confirmed(self):
        self.assertLess(match_score("우루사", "나나코스타 왁스 우루사라 300그램"), 92)
        self.assertLess(match_score("판피린", "판피린 프라하"), 92)

    def test_placeholder_image_is_rejected(self):
        self.assertEqual(valid_image_url("https://img.example.com/noImg_160.gif"), "")

    def test_real_image_wins_over_onerror_placeholder(self):
        document = """
        <li class="prod_item searched">
          <div class="thumb_image">
            <img src="//img.example.com/product.jpg"
                 onerror="this.src='//img.danawa.com/new/noData/img/noImg_160.gif';" />
          </div>
          <p class="prod_name"><a href="https://example.com/item">멜라잇 플러스 30정</a></p>
        </li>
        """
        rows = parse_results(document, "멜라잇 플러스")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["image_url"], "https://img.example.com/product.jpg")


if __name__ == "__main__":
    unittest.main()
