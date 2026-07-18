import json
import tempfile
import unittest
from pathlib import Path

from scripts.export_portable_catalog import build_portable_record, export_package, validate_package


class PortableCatalogTests(unittest.TestCase):
    def test_record_separates_display_official_media_and_provenance(self):
        product = {
            "document_id": "p1",
            "name": "테스트약",
            "capacity": "10정",
            "category": "진통제",
            "displayed_price_krw": 5000,
            "etc": "",
            "source_order": 1,
            "source_type": "Firestore",
            "recorded_at": "2026-07-15",
            "verification_status": "확인",
            "image_url": "https://example.com/product.jpg",
            "image_source_url": "https://example.com/product",
            "image_kind": "package",
            "image_rights_status": "verified",
            "image_checked_at": "2026-07-16T10:00:00+09:00",
            "official_match_status": "confirmed",
            "official_item_name": "테스트정",
            "official_item_seq": "C1",
            "official_manufacturer": "테스트제약",
            "official_source_url": "https://health.kr/product/C1",
            "official_checked_at": "2026-07-16T11:00:00+09:00",
            "official_content_status": "normalized_from_upstream_cache",
            "official_content": {
                "schema_version": "1.0",
                "normalization_version": "catalog-text-v1",
                "efficacy": {
                    "text": "통증을 완화합니다.",
                    "blocks": [{"type": "paragraph", "text": "통증을 완화합니다."}],
                },
                "dosage": {
                    "text": "1일 1회 복용합니다.",
                    "blocks": [{"type": "paragraph", "text": "1일 1회 복용합니다."}],
                },
            },
        }

        record = build_portable_record(product)

        self.assertEqual(record["schema_version"], "1.0")
        self.assertEqual(record["product_id"], "p1")
        self.assertEqual(record["display"]["price_krw"], 5000)
        self.assertEqual(record["media"]["primary_image"]["source_url"], product["image_source_url"])
        self.assertEqual(record["medicine"]["identity"]["item_code"], "C1")
        self.assertEqual(record["medicine"]["content"]["efficacy"]["text"], "통증을 완화합니다.")
        self.assertIn("효능·효과:\n통증을 완화합니다.", record["ai_context"])
        self.assertIn(product["official_source_url"], record["ai_context"])

    def test_unmatched_product_uses_null_instead_of_invented_medicine_data(self):
        record = build_portable_record(
            {
                "document_id": "p2",
                "name": "의료기기",
                "capacity": "1개",
                "category": "의료기기",
                "displayed_price_krw": 10000,
                "etc": "",
                "official_match_status": "not_applicable",
            }
        )

        self.assertIsNone(record["medicine"])
        self.assertEqual(record["quality"]["official_match_status"], "not_applicable")

    def test_export_is_deterministic_and_ndjson_has_one_record_per_product(self):
        products = [
            {
                "document_id": "p1",
                "name": "상품 1",
                "capacity": "1개",
                "category": "기타",
                "displayed_price_krw": 1000,
                "etc": "",
                "official_match_status": "not_applicable",
            },
            {
                "document_id": "p2",
                "name": "상품 2",
                "capacity": "2개",
                "category": "기타",
                "displayed_price_krw": 2000,
                "etc": "",
                "official_match_status": "not_found",
            },
        ]

        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_manifest = export_package(products, Path(first), expected_count=2)
            second_manifest = export_package(products, Path(second), expected_count=2)
            for name in ("products.json", "products.ndjson", "schema.json", "manifest.json", "README.md"):
                self.assertEqual((Path(first) / name).read_bytes(), (Path(second) / name).read_bytes())
                self.assertNotIn(b"\r\n", (Path(first) / name).read_bytes())
            lines = (Path(first) / "products.ndjson").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual([json.loads(line)["product_id"] for line in lines], ["p1", "p2"])
            self.assertEqual(first_manifest["product_count"], 2)
            self.assertEqual(first_manifest, second_manifest)
            self.assertEqual(validate_package(Path(first), expected_count=2)["error_count"], 0)

    def test_validation_detects_hash_or_text_corruption(self):
        products = [{
            "document_id": "p1",
            "name": "상품",
            "capacity": "1개",
            "category": "기타",
            "displayed_price_krw": 1000,
            "etc": "",
            "official_match_status": "not_applicable",
        }]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            export_package(products, output, expected_count=1)
            records = json.loads((output / "products.json").read_text(encoding="utf-8"))
            records[0]["display"]["name"] = "깨진br\n상품"
            (output / "products.json").write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")

            report = validate_package(output, expected_count=1)

        self.assertGreater(report["error_count"], 0)
        self.assertIn("hash_mismatch", {error["kind"] for error in report["errors"]})
        self.assertIn("damaged_text", {error["kind"] for error in report["errors"]})

    def test_production_export_requires_exactly_776_products(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "776"):
                export_package([], Path(directory))

    def test_schema_validation_rejects_malformed_nested_medicine_even_with_valid_hashes(self):
        product = {
            "document_id": "p1",
            "name": "상품",
            "capacity": "1개",
            "category": "기타",
            "displayed_price_krw": 1000,
            "etc": "",
            "official_match_status": "not_applicable",
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            export_package([product], output, expected_count=1)
            records = json.loads((output / "products.json").read_text(encoding="utf-8"))
            records[0]["medicine"] = {}
            (output / "products.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            (output / "products.ndjson").write_text(json.dumps(records[0], ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            import hashlib
            for name in ("products.json", "products.ndjson"):
                manifest["files"][name]["sha256"] = hashlib.sha256((output / name).read_bytes()).hexdigest()
            (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            report = validate_package(output, expected_count=1)

        self.assertIn("schema_validation", {error["kind"] for error in report["errors"]})


if __name__ == "__main__":
    unittest.main()
