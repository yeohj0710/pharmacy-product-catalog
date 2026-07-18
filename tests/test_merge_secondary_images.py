import unittest

from scripts.merge_secondary_images import merge_images


class MergeSecondaryImagesTests(unittest.TestCase):
    def test_automatic_secondary_image_is_not_linked(self):
        products = [{"id": "p1", "name": "상품"}]
        records = {
            "p1": {
                "catalog_product_id": "p1",
                "catalog_name": "테스트상품",
                "candidate_name": "테스트상품 30정",
                "status": "confirmed",
                "match_score": 96,
                "image_url": "https://img.example.com/product.jpg",
                "source_url": "https://search.example.com/product",
                "checked_at": "2026-07-15T00:00:00+09:00",
            }
        }
        counts = merge_images(products, records)
        self.assertEqual(counts["not_linked"], 1)
        self.assertNotIn("image_url", products[0])

    def test_manually_verified_secondary_image_is_linked(self):
        products = [{"id": "p1", "name": "테스트상품", "official_source_url": "https://health.kr/product/p1"}]
        records = {
            "p1": {
                "catalog_product_id": "p1",
                "catalog_name": "테스트상품",
                "candidate_name": "테스트상품 30정",
                "status": "confirmed",
                "manual_verified": True,
                "visual_verified": True,
                "image_url": "https://img.example.com/product.jpg",
                "source_url": "https://example.com/product",
                "checked_at": "2026-07-15T00:00:00+09:00",
            }
        }
        counts = merge_images(products, records)
        self.assertEqual(counts["linked"], 1)
        self.assertEqual(products[0]["image_rights_status"], "verified")
        self.assertEqual(products[0]["image_source_url"], "https://example.com/product")
        self.assertEqual(products[0]["official_source_url"], "https://health.kr/product/p1")

    def test_existing_official_image_is_preserved(self):
        products = [{"id": "p1", "image_url": "https://common.health.kr/official.jpg"}]
        records = {
            "p1": {
                "status": "confirmed",
                "match_score": 100,
                "image_url": "https://img.example.com/secondary.jpg",
            }
        }
        merge_images(products, records)
        self.assertEqual(products[0]["image_url"], "https://common.health.kr/official.jpg")

    def test_manually_verified_manufacturer_image_can_replace_small_official_preview(self):
        products = [
            {
                "id": "p1",
                "image_url": "https://common.health.kr/small.jpg",
                "image_rights_status": "official_source_preview",
            }
        ]
        records = {
            "p1": {
                "catalog_product_id": "p1",
                "status": "confirmed",
                "manual_verified": True,
                "visual_verified": True,
                "match_score": 100,
                "image_url": "https://brand.example.com/large.jpg",
                "source_url": "https://brand.example.com/product",
            }
        }

        counts = merge_images(products, records, replace_existing_verified=True)

        self.assertEqual(counts["replaced_verified_image"], 1)
        self.assertEqual(products[0]["image_url"], "https://brand.example.com/large.jpg")
        self.assertEqual(products[0]["image_rights_status"], "verified")

    def test_approved_product_image_can_replace_existing_search_thumbnail(self):
        products = [{"id": "p1", "image_url": "https://search.pstatic.net/common/old.jpg"}]
        records = {
            "p1": {
                "catalog_product_id": "p1",
                "status": "confirmed",
                "manual_verified": True,
                "visual_verified": True,
                "image_url": "https://brand.example.com/product.jpg",
                "source_url": "https://brand.example.com/products/p1",
                "checked_at": "2026-07-16T00:00:00+09:00",
            }
        }
        counts = merge_images(products, records, replace_search_thumbnails=True)
        self.assertEqual(counts["replaced_search_thumbnail"], 1)
        self.assertEqual(products[0]["image_url"], "https://brand.example.com/product.jpg")
        self.assertEqual(products[0]["image_source_url"], "https://brand.example.com/products/p1")

    def test_search_thumbnail_is_preserved_without_explicit_replacement_flag(self):
        products = [{"id": "p1", "image_url": "https://search.pstatic.net/common/old.jpg"}]
        records = {
            "p1": {
                "catalog_product_id": "p1",
                "status": "confirmed",
                "manual_verified": True,
                "visual_verified": True,
                "image_url": "https://brand.example.com/product.jpg",
                "source_url": "https://brand.example.com/products/p1",
            }
        }
        merge_images(products, records)
        self.assertEqual(products[0]["image_url"], "https://search.pstatic.net/common/old.jpg")

    def test_short_or_weak_name_match_is_not_linked(self):
        products = [{"id": "p1", "name": "우루사"}]
        records = {
            "p1": {
                "catalog_product_id": "p1",
                "catalog_name": "우루사",
                "candidate_name": "나나코스타 왁스 우루사라 300그램",
                "status": "confirmed",
                "match_score": 92,
                "image_url": "https://img.example.com/wrong.jpg",
            }
        }
        counts = merge_images(products, records)
        self.assertEqual(counts["not_linked"], 1)
        self.assertNotIn("image_url", products[0])

    def test_naver_exact_title_containment_is_not_linked_without_manual_verification(self):
        products = [{"id": "p1", "name": "테스트 상품"}]
        records = {
            "p1": {
                "catalog_product_id": "p1",
                "catalog_name": "테스트 상품",
                "candidate_name": "동아제약 테스트 상품 30정 상세사진",
                "status": "confirmed",
                "match_score": 65,
                "image_url": "https://search.pstatic.net/common/product.jpg",
                "source_url": "https://search.naver.com/search.naver?where=image&query=test",
            }
        }
        counts = merge_images(products, records)
        self.assertEqual(counts["not_linked"], 1)
        self.assertNotIn("image_url", products[0])

    def test_search_thumbnail_is_not_linked_even_after_manual_verification(self):
        products = [{"id": "p1", "name": "테스트 상품"}]
        records = {
            "p1": {
                "catalog_product_id": "p1",
                "status": "confirmed",
                "manual_verified": True,
                "visual_verified": True,
                "image_url": "https://search.pstatic.net/common/product.jpg",
                "result_url": "https://brand.example.com/product",
            }
        }
        counts = merge_images(products, records)
        self.assertEqual(counts["not_linked"], 1)
        self.assertNotIn("image_url", products[0])

    def test_health_kr_candidate_keeps_official_preview_provenance(self):
        products = [{"id": "p1", "name": "테스트 상품"}]
        records = {
            "p1": {
                "catalog_product_id": "p1",
                "status": "confirmed",
                "manual_verified": True,
                "visual_verified": True,
                "image_url": "https://common.health.kr/shared/images/product.jpg",
                "result_url": "https://www.health.kr/searchDrug/result_drug.asp?drug_cd=p1",
            }
        }
        merge_images(products, records)
        self.assertEqual(products[0]["image_rights_status"], "official_source_preview")
        self.assertEqual(products[0]["image_source_url"], records["p1"]["result_url"])

    def test_search_result_page_cannot_be_used_as_verified_provenance(self):
        products = [{"id": "p1", "name": "테스트 상품"}]
        records = {
            "p1": {
                "catalog_product_id": "p1",
                "status": "confirmed",
                "manual_verified": True,
                "visual_verified": True,
                "image_url": "https://cdn.example.com/product.jpg",
                "result_url": "https://search.naver.com/search.naver?query=test",
            }
        }
        counts = merge_images(products, records)
        self.assertEqual(counts["not_linked"], 1)
        self.assertNotIn("image_url", products[0])

    def test_previous_unverified_preview_is_cleared(self):
        products = [
            {
                "id": "p1",
                "name": "우루사",
                "image_url": "https://img.example.com/wrong.jpg",
                "image_source_url": "https://search.example.com/wrong",
                "image_rights_status": "source_preview",
            }
        ]
        records = {
            "p1": {
                "catalog_product_id": "p1",
                "catalog_name": "우루사",
                "candidate_name": "나나코스타 왁스 우루사라",
                "status": "review_required",
                "match_score": 92,
                "image_url": "https://img.example.com/wrong.jpg",
            }
        }
        counts = merge_images(products, records)
        self.assertEqual(counts["cleared_previous"], 1)
        self.assertEqual(products[0]["image_url"], "")

    def test_unverified_candidate_cannot_be_linked_even_when_preview_is_requested(self):
        products = [{"id": "p1", "name": "테스트 상품"}]
        records = {
            "p1": {
                "catalog_product_id": "p1",
                "status": "review_required",
                "image_url": "https://img.example.com/product.jpg",
                "source_url": "https://search.example.com/product",
            }
        }
        counts = merge_images(products, records, include_unverified_previews=True)
        self.assertEqual(counts["not_linked"], 1)
        self.assertNotIn("image_url", products[0])


if __name__ == "__main__":
    unittest.main()
