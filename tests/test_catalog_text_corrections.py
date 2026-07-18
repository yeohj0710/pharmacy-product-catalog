from __future__ import annotations

import tempfile
import unittest
import hashlib
from pathlib import Path

from scripts.apply_catalog_text_corrections import apply_corrections, refresh_duplicate_groups
from scripts.build_catalog_text_corrections import validate_review_cohort
from scripts.refresh_corrected_official_matches import merge_refresh_result


class CatalogTextCorrectionTests(unittest.TestCase):
    def test_review_cohort_requires_exact_files_hashes_and_unique_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = (Path(directory) / "part-a.json", Path(directory) / "part-b.json")
            paths[0].write_text('[{"document_id":"a"}]', encoding="utf-8")
            paths[1].write_text('[{"document_id":"b"}]', encoding="utf-8")
            hashes = {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
            }
            reviews = [{"document_id": "a"}, {"document_id": "b"}]

            validate_review_cohort(paths, reviews, expected_hashes=hashes, expected_count=2)

            paths[1].write_text('[{"document_id":"changed"}]', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "해시"):
                validate_review_cohort(paths, reviews, expected_hashes=hashes, expected_count=2)

    def test_review_cohort_rejects_missing_or_duplicate_product(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "part.json"
            path.write_text("[]", encoding="utf-8")
            hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()}

            with self.assertRaisesRegex(ValueError, "고유 상품 2개"):
                validate_review_cohort(
                    (path,),
                    [{"document_id": "a"}, {"document_id": "a"}],
                    expected_hashes=hashes,
                    expected_count=2,
                )

    def test_corrects_display_fields_but_preserves_raw_app_fields(self) -> None:
        products = [
            {
                "document_id": "item-1",
                "name": "메디큐어롤반창고중령",
                "app_name": "메디큐어롤반창고중령",
                "capacity": "10cm10cm",
                "app_capacity": "10cm10cm",
                "specification": "10cm10cm",
                "normalized_name": "메디큐어롤반창고중령",
                "normalized_capacity": "10cm10cm",
            }
        ]
        corrections = [
            {
                "document_id": "item-1",
                "original_name": "메디큐어롤반창고중령",
                "corrected_name": "메디큐어롤반창고중형",
                "original_capacity": "10cm10cm",
                "corrected_capacity": "10cm×10m",
                "evidence_urls": ["https://example.com/product"],
                "evidence_text": "포장에 중형 10cm×10m가 표시됨",
                "approved": True,
            }
        ]

        changed = apply_corrections(products, corrections)

        self.assertEqual(changed, 1)
        self.assertEqual(products[0]["name"], "메디큐어롤반창고중형")
        self.assertEqual(products[0]["capacity"], "10cm×10m")
        self.assertEqual(products[0]["specification"], "10cm×10m")
        self.assertEqual(products[0]["normalized_name"], "메디큐어롤반창고중형")
        self.assertEqual(products[0]["normalized_capacity"], "10cm10m")
        self.assertEqual(products[0]["app_name"], "메디큐어롤반창고중령")
        self.assertEqual(products[0]["app_capacity"], "10cm10cm")

    def test_rejects_stale_original_value(self) -> None:
        products = [{"document_id": "item-1", "name": "이미 바뀐 이름", "capacity": "1개"}]
        corrections = [
            {
                "document_id": "item-1",
                "original_name": "이전 이름",
                "corrected_name": "새 이름",
                "original_capacity": "1개",
                "corrected_capacity": "1개",
                "evidence_urls": ["https://example.com/product"],
                "evidence_text": "공식 상품 페이지 확인",
                "approved": True,
            }
        ]

        with self.assertRaisesRegex(ValueError, "원본 상품명"):
            apply_corrections(products, corrections)

    def test_accepts_a_previous_approved_display_name_when_evidence_is_corrected(self) -> None:
        products = [
            {
                "document_id": "item-1",
                "name": "성광포비스틱스왑액",
                "capacity": "2매×6개입",
            }
        ]
        corrections = [
            {
                "document_id": "item-1",
                "original_name": "포비돈스틱스왑액",
                "accepted_previous_names": ["성광포비스틱스왑액"],
                "corrected_name": "성광포스틱스왑액",
                "original_capacity": "6개",
                "corrected_capacity": "2매×6개입",
                "evidence_urls": ["https://health.kr/product"],
                "evidence_text": "제조사와 약학정보원 원문 재확인",
                "approved": True,
            }
        ]

        changed = apply_corrections(products, corrections)

        self.assertEqual(changed, 1)
        self.assertEqual(products[0]["name"], "성광포스틱스왑액")

    def test_rejects_approved_correction_without_evidence(self) -> None:
        products = [{"document_id": "item-1", "name": "오타", "capacity": "1개"}]
        corrections = [
            {
                "document_id": "item-1",
                "original_name": "오타",
                "corrected_name": "정상",
                "original_capacity": "1개",
                "corrected_capacity": "1개",
                "evidence_urls": [],
                "evidence_text": "",
                "approved": True,
            }
        ]

        with self.assertRaisesRegex(ValueError, "근거"):
            apply_corrections(products, corrections)

    def test_official_refresh_preserves_external_image_when_still_unmatched(self) -> None:
        current = {
            "document_id": "item-1",
            "official_match_status": "not_found",
            "image_url": "https://shop.example/product.jpg",
            "image_source_url": "https://shop.example/product",
            "image_rights_status": "external_source_preview",
            "image_kind": "package",
            "image_checked_at": "2026-07-16",
            "enrichment_status": "secondary_image_linked",
        }
        refreshed = {
            **current,
            "official_match_status": "review_required",
            "official_checked_at": "2026-07-17",
            "match_alternatives": [{"official_item_name": "후보"}],
            "image_url": "",
            "image_source_url": "",
            "image_rights_status": "",
            "image_kind": "",
            "image_checked_at": "",
            "enrichment_status": "official_review_required",
        }

        merged = merge_refresh_result(current, refreshed)

        self.assertEqual(merged["official_match_status"], "review_required")
        self.assertEqual(merged["image_url"], "https://shop.example/product.jpg")
        self.assertEqual(merged["image_source_url"], "https://shop.example/product")
        self.assertEqual(merged["enrichment_status"], "secondary_image_linked")

    def test_rebuilds_duplicate_groups_after_names_are_corrected(self) -> None:
        products = [
            {"document_id": "a", "normalized_name": "같은상품", "duplicate_group_id": "", "duplicate_group_size": 1},
            {"document_id": "b", "normalized_name": "같은상품", "duplicate_group_id": "", "duplicate_group_size": 1},
            {"document_id": "c", "normalized_name": "다른상품", "duplicate_group_id": "old", "duplicate_group_size": 2},
        ]

        changed = refresh_duplicate_groups(products)

        self.assertEqual(changed, 3)
        self.assertEqual(products[0]["duplicate_group_id"], products[1]["duplicate_group_id"])
        self.assertEqual(products[0]["duplicate_group_size"], 2)
        self.assertEqual(products[2]["duplicate_group_id"], "")
        self.assertEqual(products[2]["duplicate_group_size"], 1)


if __name__ == "__main__":
    unittest.main()
