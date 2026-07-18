import unittest

from scripts.audit_catalog_text import audit_products


class CatalogTextAuditTests(unittest.TestCase):
    def test_detects_public_text_corruption_without_flagging_urls_or_raw_provenance(self):
        products = [
            {
                "document_id": "p1",
                "id": "p1",
                "name": "정상 제품",
                "capacity": "10정",
                "official_match_status": "confirmed",
                "official_item_seq": "C1",
                "official_source_url": "https://health.kr/item?drug_cd=C1",
                "official_dosage": "첫 문장.br\n\n50 ? 79",
                "official_ingredients": ["성분 10mg /"],
                "official_interactions": [{"cells": ["설명\n복사"]}],
                "official_additional_data": {
                    "health_kr_raw": {"dosage": "원본brbr<P></P>"}
                },
            }
        ]

        report = audit_products(products)

        self.assertEqual(report["product_count"], 1)
        self.assertGreaterEqual(report["error_count"], 4)
        kinds = {finding["kind"] for finding in report["findings"]}
        self.assertTrue(
            {"literal_br", "malformed_numeric_range", "trailing_ingredient_separator", "copied_ui_label"}
            <= kinds
        )
        self.assertFalse(any("official_source_url" in finding["field"] for finding in report["findings"]))
        self.assertFalse(any("official_additional_data" in finding["field"] for finding in report["findings"]))

    def test_accepts_normalized_structured_product(self):
        products = [
            {
                "document_id": "p1",
                "id": "p1",
                "name": "정상 제품",
                "capacity": "10정",
                "official_match_status": "confirmed",
                "official_item_seq": "C1",
                "official_dosage": "경증 50–79",
                "official_ingredients": ["성분 10mg"],
                "official_interactions": [{"cells": ["설명"]}],
                "official_content": {
                    "schema_version": "1.0",
                    "dosage": {
                        "text": "경증 50–79",
                        "blocks": [{"type": "paragraph", "text": "경증 50–79"}],
                    },
                },
                "official_content_status": "normalized_from_upstream_cache",
            }
        ]

        report = audit_products(products)

        self.assertEqual(report["error_count"], 0)

    def test_audits_other_modal_fields_but_ignores_urls_and_raw_app_fields(self):
        product = {
            "document_id": "p1",
            "id": "p1",
            "name": "정상 제품",
            "capacity": "10정",
            "official_match_status": "not_applicable",
            "official_permit_date": "2020br\n",
            "official_source_url": "https://health.kr/item?text=10?20",
            "app_etc": "원본br\n보존",
        }

        report = audit_products([product])

        self.assertEqual(report["error_count"], 1)
        self.assertEqual(report["findings"][0]["field"], "official_permit_date")


if __name__ == "__main__":
    unittest.main()
