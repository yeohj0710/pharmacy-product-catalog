import json
import tempfile
import unittest
from pathlib import Path

from scripts.merge_kpic_details import merge_files


class MergeKpicDetailsTests(unittest.TestCase):
    def test_complete_details_and_official_image_are_merged(self):
        product = {"id": "p1", "name": "테스트정", "price": "1000", "displayed_price_krw": 1000}
        record = {
            "catalog_product_id": "p1",
            "kpic_code": "CODE1",
            "kpic_name": "테스트정",
            "status": "collected",
            "match_score": 100,
            "source_url": "https://health.kr/searchDrug/result_drug.asp?drug_cd=CODE1",
            "content": {
                "ingredients": ["성분 10mg"],
                "efficacy": "효능",
                "dosage": "용법",
                "precautions": "주의",
                "storage": "보관",
                "manufacturer": "제약사",
                "dosage_form": "정제",
                "route": "경구",
                "package": "10정",
                "images": {
                    "primary_url": "https://common.health.kr/shared/images/ext_images/pack_img/p_CODE1.jpg",
                    "primary_type": "package",
                },
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "queue.json"
            part_path = root / "part.json"
            input_path.write_text(json.dumps([product], ensure_ascii=False), encoding="utf-8")
            part_path.write_text(json.dumps([record], ensure_ascii=False), encoding="utf-8")
            rows, summary = merge_files(input_path, [part_path])

        merged = rows[0]
        self.assertEqual(merged["price"], "1000")
        self.assertEqual(merged["official_efficacy"], "효능")
        self.assertEqual(merged["official_dosage"], "용법")
        self.assertEqual(merged["official_active_ingredients"], ["성분 10mg"])
        self.assertEqual(merged["image_rights_status"], "official_source_preview")
        self.assertEqual(summary["status_counts"]["merged"], 1)

    def test_review_record_does_not_merge_unverified_content(self):
        product = {
            "id": "p1",
            "name": "테스트정",
            "official_efficacy": "이전에 잘못 연결된 효능",
            "official_dosage": "이전에 잘못 연결된 용법",
            "image_url": "https://common.health.kr/shared/images/ext_images/pack_img/wrong.jpg",
            "image_source_url": "https://health.kr/wrong",
            "image_rights_status": "official_source_preview",
        }
        record = {
            "catalog_product_id": "p1",
            "status": "review_required",
            "match_score": 90,
            "content": {"efficacy": "잘못 연결된 효능"},
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "queue.json"
            part_path = root / "part.json"
            input_path.write_text(json.dumps([product], ensure_ascii=False), encoding="utf-8")
            part_path.write_text(json.dumps([record], ensure_ascii=False), encoding="utf-8")
            rows, _ = merge_files(input_path, [part_path])

        self.assertEqual(rows[0]["official_match_status"], "review_required")
        self.assertNotIn("official_efficacy", rows[0])
        self.assertNotIn("official_dosage", rows[0])
        self.assertEqual(rows[0]["image_url"], "")


if __name__ == "__main__":
    unittest.main()
