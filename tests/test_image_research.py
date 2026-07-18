import unittest

from scripts.audit_catalog_images import is_search_url, source_page_status, unauthorized_protected_changes
from scripts.validate_image_research_batch import fetch_image, fetch_source_page, image_url_is_allowed, source_page_is_product_page


class FakeResponse:
    status_code = 200
    headers = {"content-type": "image/jpeg"}
    content = b"not-used-after-redirect-check"

    def __init__(self, url):
        self.url = url


class FakeSession:
    def __init__(self, final_url):
        self.final_url = final_url

    def get(self, *_args, **_kwargs):
        return FakeResponse(self.final_url)


class ImageResearchValidationTests(unittest.TestCase):
    def test_search_pages_and_search_thumbnails_are_rejected(self):
        self.assertFalse(source_page_is_product_page("https://search.naver.com/search.naver?query=test"))
        self.assertFalse(source_page_is_product_page("https://search.danawa.com/dsearch.php?query=test"))
        self.assertFalse(image_url_is_allowed("https://search.pstatic.net/common/product.jpg"))

    def test_actual_product_and_cdn_urls_are_allowed(self):
        self.assertTrue(source_page_is_product_page("https://brand.example.com/products/exact-item"))
        self.assertTrue(image_url_is_allowed("https://cdn.example.com/products/exact-item.png"))

    def test_placeholder_urls_are_rejected(self):
        self.assertFalse(image_url_is_allowed("https://cdn.example.com/images/no_image.png"))
        self.assertFalse(image_url_is_allowed("https://cdn.example.com/placeholder/product.jpg"))

    def test_http_only_image_url_is_rejected(self):
        self.assertFalse(image_url_is_allowed("http://brand.example.com/product.jpg"))

    def test_invalid_source_page_is_rejected_without_network_request(self):
        result = source_page_status("https://search.naver.com/search.naver?query=test")
        self.assertEqual(result["status"], 0)
        self.assertEqual(result["error"], "invalid_or_search_page_url")

    def test_redirect_to_search_page_is_rejected(self):
        result = fetch_source_page(FakeSession("https://search.naver.com/search.naver?query=test"), "https://brand.example.com/item")
        self.assertEqual(result["error"], "redirected_to_non_product_page")

    def test_redirect_to_search_thumbnail_is_rejected(self):
        result, image = fetch_image(FakeSession("https://search.pstatic.net/common/product.jpg"), "https://cdn.example.com/product.jpg")
        self.assertEqual(result["error"], "redirected_to_disallowed_image_url")
        self.assertIsNone(image)

    def test_audit_recognizes_search_thumbnail_hosts(self):
        self.assertTrue(is_search_url("https://search.pstatic.net/common/product.jpg"))

    def test_audit_accepts_only_fields_listed_by_content_normalization(self):
        before = {"official_dosage": "깨진br", "official_item_name": "정상약"}
        after = {"official_dosage": "깨진 문자 제거", "official_item_name": "다른 약"}

        changes = unauthorized_protected_changes(
            before,
            after,
            {"official_dosage", "official_item_name"},
            {"official_dosage"},
        )

        self.assertEqual(changes, ["official_item_name"])


if __name__ == "__main__":
    unittest.main()
