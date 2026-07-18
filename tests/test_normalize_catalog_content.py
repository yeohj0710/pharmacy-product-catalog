import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from scripts.normalize_catalog_content import normalize_products


class NormalizeCatalogContentTests(unittest.TestCase):
    def test_rebuilds_confirmed_content_from_upstream_cache(self):
        product = {
            "document_id": "p1",
            "id": "p1",
            "name": "테스트약",
            "app_name": "테스트약 원문",
            "capacity": "10정",
            "official_match_status": "confirmed",
            "official_item_seq": "CODE1",
            "official_checked_at": "2026-07-16T10:00:00+09:00",
            "official_source_url": "https://health.kr/product/CODE1",
            "official_efficacy": "기존 효능br",
            "official_dosage": "기존 용법.br\n\n다음 용법",
            "official_precautions": "기존 주의",
            "official_ingredients": ["성분 10mg /"],
            "official_active_ingredients": ["성분 10mg /"],
            "official_interactions": [{"cells": ["상호작용 설명\n\n복사"]}],
            "official_additional_data": {"kept": "value"},
        }
        original_identity = {
            key: deepcopy(product[key])
            for key in ("document_id", "id", "name", "app_name", "capacity", "official_source_url")
        }
        source = {
            "drug_code": "CODE1",
            "effect": "첫 효능brbr<P></P>둘째 효능",
            "dosage": (
                "표를 참조한다.brbr<P></P>"
                "<TABLE><TR><TD>구분</TD><TD>용량</TD></TR>"
                "<TR><TD>경증</TD><TD>10 mg</TD></TR></TABLE>"
            ),
            "caution": "첫 주의brbr<P></P>둘째 주의",
            "stmt": "실온 보관",
        }

        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            cache_file = cache / f"{hashlib.sha256(b'CODE1').hexdigest()}.json"
            cache_file.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
            report = normalize_products([product], cache)

        self.assertEqual(report["product_count"], 1)
        self.assertEqual(report["confirmed_count"], 1)
        self.assertEqual(report["source_cache_count"], 1)
        self.assertEqual(product["official_efficacy"], "첫 효능\n\n둘째 효능")
        self.assertEqual(product["official_dosage"], "표를 참조한다.\n\n구분 | 용량\n경증 | 10 mg")
        self.assertEqual(product["official_precautions"], "첫 주의\n\n둘째 주의")
        self.assertEqual(product["official_storage"], "실온 보관")
        self.assertEqual(product["official_ingredients"], ["성분 10mg"])
        self.assertEqual(product["official_active_ingredients"], ["성분 10mg"])
        self.assertEqual(product["official_interactions"][0]["cells"], ["상호작용 설명"])
        self.assertEqual(
            product["official_content"]["dosage"]["blocks"][1],
            {"type": "table", "headers": ["구분", "용량"], "rows": [["경증", "10 mg"]]},
        )
        self.assertEqual(product["official_content_status"], "normalized_from_upstream_cache")
        self.assertEqual(product["official_additional_data"]["kept"], "value")
        self.assertEqual(
            product["official_additional_data"]["health_kr_source_sha256"],
            hashlib.sha256(
                json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        )
        for key, value in original_identity.items():
            self.assertEqual(product[key], value)

    def test_nonmatched_product_is_included_without_inventing_official_content(self):
        product = {
            "document_id": "p2",
            "id": "p2",
            "name": " 일반  상품 ",
            "capacity": " 1개 ",
            "category": "의료기기",
            "etc": "",
            "official_match_status": "not_applicable",
        }

        with tempfile.TemporaryDirectory() as directory:
            report = normalize_products([product], Path(directory))

        self.assertEqual(report["product_count"], 1)
        self.assertEqual(report["confirmed_count"], 0)
        self.assertEqual(product["name"], "일반 상품")
        self.assertEqual(product["capacity"], "1개")
        self.assertNotIn("official_content", product)

    def test_missing_cache_preserves_existing_structured_tables(self):
        dosage = {
            "text": "구분 | 용량\n경증 | 5 mg",
            "blocks": [
                {"type": "table", "headers": ["구분", "용량"], "rows": [["경증", "5 mg"]]}
            ],
        }
        product = {
            "document_id": "p3",
            "id": "p3",
            "name": "테스트약",
            "capacity": "10정",
            "official_match_status": "confirmed",
            "official_item_seq": "MISSING",
            "official_dosage": dosage["text"],
            "official_content": {
                "schema_version": "1.0",
                "normalization_version": "catalog-text-v1",
                "dosage": dosage,
            },
            "official_content_status": "normalized_from_upstream_cache",
        }

        with tempfile.TemporaryDirectory() as directory:
            normalize_products([product], Path(directory))

        self.assertEqual(product["official_content"]["dosage"], dosage)
        self.assertEqual(product["official_content_status"], "normalized_from_upstream_cache")


if __name__ == "__main__":
    unittest.main()
