import json
import os
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from lib.official_data.client import DataGoClient, MissingServiceKey
from lib.official_data.matching import choose_candidate, score_candidate
from lib.official_data.schema import make_match_record, make_official_record, validate_official_record
from lib.official_data.sources import SOURCES, extract_items, merge_official_records, parse_source_record, record_source_url
from scripts.materialize_official_product_data import content_status, materialize_products
from scripts.collect_official_product_data import collect_batch
from scripts.export_official_review_queue import lookup_status, score_reason


class OfficialSchemaTests(unittest.TestCase):
    def test_official_record_requires_identity_content_and_provenance(self):
        record = make_official_record(
            source_domain="drug",
            source_dataset_id="15095677",
            source_record_id="200808876",
            item_name="테스트정",
        )
        self.assertEqual(record["official_product_key"], "drug:200808876")
        self.assertGreaterEqual(
            set(record["content"]),
            {"efficacy", "dosage", "precautions", "ingredients"},
        )
        self.assertEqual(record["provenance"]["source_dataset_id"], "15095677")
        validate_official_record(record)

    def test_match_record_keeps_catalog_and_official_entities_separate(self):
        match = make_match_record(
            catalog_product_id="retail-1",
            official_product_key="drug:200808876",
            score=97,
            status="confirmed",
            score_components={"name": 60, "capacity": 15, "manufacturer": 17, "dosage_form": 5},
        )
        self.assertEqual(match["catalog_product_id"], "retail-1")
        self.assertEqual(match["official_product_key"], "drug:200808876")
        self.assertEqual(match["status"], "confirmed")


class SourceParserTests(unittest.TestCase):
    def test_extract_items_accepts_data_go_response_shapes(self):
        payload = {"response": {"body": {"items": {"item": [{"ITEM_SEQ": "1"}]}}}}
        self.assertEqual(extract_items(payload), [{"ITEM_SEQ": "1"}])

    def test_easy_drug_parser_maps_consumer_guidance_and_image(self):
        item = {
            "itemSeq": "200808876",
            "itemName": "테스트정",
            "entpName": "테스트제약",
            "efcyQesitm": "<p>통증을 완화합니다.</p>",
            "useMethodQesitm": "<p>1회 1정 복용합니다.</p>",
            "atpnQesitm": "<p>과량 복용하지 마세요.</p>",
            "itemImage": "https://example.go.kr/pill.jpg",
            "updateDe": "20260701",
        }
        record = parse_source_record(SOURCES["easy_drug"], item)
        self.assertEqual(record["official_product_key"], "drug:200808876")
        self.assertEqual(record["content"]["efficacy"], "통증을 완화합니다.")
        self.assertEqual(record["content"]["dosage"], "1회 1정 복용합니다.")
        self.assertEqual(record["images"][0]["kind"], "pill")

    def test_drug_detail_parser_preserves_raw_and_normalized_document_text(self):
        item = {
            "ITEM_SEQ": "200808876",
            "ITEM_NAME": "테스트정",
            "ENTP_NAME": "테스트제약",
            "EE_DOC_DATA": "<DOC><SECTION><ARTICLE>효능 문장</ARTICLE></SECTION></DOC>",
            "UD_DOC_DATA": "<DOC><SECTION><ARTICLE>용법 문장</ARTICLE></SECTION></DOC>",
            "NB_DOC_DATA": "<DOC><SECTION><ARTICLE>주의 문장</ARTICLE></SECTION></DOC>",
            "BIG_PRDT_IMG_URL": "https://example.go.kr/package.jpg",
        }
        record = parse_source_record(SOURCES["drug_detail"], item)
        self.assertEqual(record["content"]["efficacy"], "효능 문장")
        self.assertEqual(record["content_raw"]["efficacy"], item["EE_DOC_DATA"])
        self.assertEqual(record["images"][0]["kind"], "package")
        self.assertEqual(record["field_provenance"]["content.efficacy"]["source_key"], "drug_detail")

    def test_multiple_ingredient_rows_are_merged_without_loss(self):
        first = parse_source_record(SOURCES["drug_ingredients"], {
            "ITEM_SEQ": "200808876", "ITEM_NAME": "테스트정", "MATERIAL_NAME": "성분A",
        })
        second = parse_source_record(SOURCES["drug_ingredients"], {
            "ITEM_SEQ": "200808876", "ITEM_NAME": "테스트정", "MATERIAL_NAME": "성분B",
        })
        merged = merge_official_records([first, second])
        self.assertEqual(merged["content"]["ingredients"], ["성분A", "성분B"])

    def test_record_source_url_identifies_record_without_service_key(self):
        url = record_source_url(SOURCES["drug_detail"], "200808876")
        self.assertIn("item_seq=200808876", url)
        self.assertNotIn("serviceKey", url)


class MatchingTests(unittest.TestCase):
    def test_exact_name_company_and_capacity_is_confirmed(self):
        result = score_candidate(
            catalog={"name": "챔프시럽 해열진통", "capacity": "10포", "manufacturer_hint": "동아제약"},
            official={"item_name": "챔프시럽 해열진통", "pack_unit": "10포", "manufacturer": "동아제약(주)"},
        )
        self.assertGreaterEqual(result.score, 95)
        self.assertEqual(result.status, "confirmed")

    def test_same_name_conflict_requires_review(self):
        catalog = {"name": "동일제품", "capacity": "", "manufacturer_hint": ""}
        candidates = [
            {"official_product_key": "drug:1", "item_name": "동일제품", "pack_unit": "10정", "manufacturer": "A"},
            {"official_product_key": "drug:2", "item_name": "동일제품", "pack_unit": "20정", "manufacturer": "B"},
        ]
        result = choose_candidate(catalog, candidates)
        self.assertEqual(result.status, "review_required")
        self.assertEqual(len(result.alternatives), 2)

    def test_unique_exact_name_can_confirm_without_manufacturer_hint(self):
        result = choose_candidate(
            {"name": "복합우루사연질캡슐", "capacity": "60캡슐"},
            [{"official_product_key": "drug:200000001", "item_name": "복합우루사연질캡슐", "manufacturer": "대웅제약"}],
        )
        self.assertEqual(result.status, "confirmed")
        self.assertGreaterEqual(result.score, 95)

    def test_udi_di_exact_match_is_confirmed(self):
        result = choose_candidate(
            {"name": "판매용 이름", "official_udi_di": "UDI-123"},
            [{"official_product_key": "medical_device:1", "item_name": "공식 의료기기", "udi_di": "UDI-123"}],
        )
        self.assertEqual(result.status, "confirmed")
        self.assertEqual(result.score, 100)

    def test_exact_identifier_is_not_downgraded_by_same_name_candidate(self):
        result = choose_candidate(
            {"name": "동일제품", "official_item_seq": "2"},
            [
                {"official_product_key": "drug:1", "item_name": "동일제품", "item_seq": "1"},
                {"official_product_key": "drug:2", "item_name": "동일제품", "item_seq": "2"},
            ],
        )
        self.assertEqual(result.status, "confirmed")
        self.assertEqual(result.official_product_key, "drug:2")

    def test_identifier_match_wins_a_100_point_non_identifier_tie(self):
        result = choose_candidate(
            {
                "name": "동일제품정", "capacity": "10정", "manufacturer_hint": "정확제약",
                "official_item_seq": "RIGHT",
            },
            [
                {
                    "official_product_key": "drug:wrong", "item_name": "동일제품정",
                    "item_seq": "WRONG", "manufacturer": "정확제약", "pack_unit": "10정",
                },
                {
                    "official_product_key": "drug:right", "item_name": "다른표시명",
                    "item_seq": "RIGHT", "manufacturer": "다른제약",
                },
            ],
        )
        self.assertEqual(result.status, "confirmed")
        self.assertEqual(result.official_product_key, "drug:right")

    def test_explicit_dosage_form_conflict_requires_review(self):
        result = choose_candidate(
            {"name": "테스트정"},
            [{"official_product_key": "drug:1", "item_name": "테스트정", "dosage_form": "캡슐"}],
        )
        self.assertEqual(result.status, "review_required")
        self.assertTrue(any("제형 충돌" in conflict for conflict in result.conflicts))


class ClientTests(unittest.TestCase):
    def test_missing_key_blocks_without_cache_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {}, clear=True):
                client = DataGoClient(cache_dir=Path(directory))
                with self.assertRaises(MissingServiceKey):
                    client.request_json(SOURCES["easy_drug"], {"itemName": "테스트정"})
                self.assertEqual(list(Path(directory).rglob("*.json")), [])

    def test_cached_response_avoids_network_and_key_requirement(self):
        with tempfile.TemporaryDirectory() as directory:
            client = DataGoClient(cache_dir=Path(directory), service_key="test-key")
            source = SOURCES["easy_drug"]
            cache_path = client.cache_path(source, {"itemName": "테스트정"})
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({"response": {"body": {"items": []}}}), encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                cached = DataGoClient(cache_dir=Path(directory))
                self.assertEqual(cached.request_json(source, {"itemName": "테스트정"}), {"response": {"body": {"items": []}}})


class MaterializationTests(unittest.TestCase):
    def test_confirmed_match_adds_rich_fields_without_replacing_retail_fields(self):
        products = [{"id": "retail-1", "name": "판매명", "price": "9900", "official_match_status": "pending"}]
        matches = [{"catalog_product_id": "retail-1", "official_product_key": "drug:1", "score": 98, "status": "confirmed"}]
        official = [make_official_record(source_domain="drug", source_dataset_id="15095677", source_record_id="1", item_name="공식명")]
        official[0]["manufacturer"] = "제조사"
        official[0]["content"].update({"efficacy": "효능", "dosage": "용법", "precautions": "주의"})
        result = materialize_products(products, matches, official)
        self.assertEqual(result[0]["name"], "판매명")
        self.assertEqual(result[0]["price"], "9900")
        self.assertEqual(result[0]["official_item_name"], "공식명")
        self.assertEqual(result[0]["official_dosage"], "용법")

    def test_review_match_does_not_copy_candidate_content(self):
        products = [{"id": "retail-1", "name": "판매명"}]
        matches = [{"catalog_product_id": "retail-1", "official_product_key": "drug:1", "score": 90, "status": "review_required"}]
        official = [make_official_record(source_domain="drug", source_dataset_id="15095677", source_record_id="1", item_name="후보명")]
        result = materialize_products(products, matches, official)
        self.assertEqual(result[0]["official_match_status"], "review_required")
        self.assertEqual(result[0].get("official_item_name", ""), "")

    def test_content_completion_uses_domain_specific_core_fields(self):
        device = make_official_record(
            source_domain="medical_device",
            source_dataset_id="15073875",
            source_record_id="UDI-1",
            item_name="테스트 의료기기",
        )
        device["manufacturer"] = "테스트 업체"
        device["identifiers"]["udi_di"] = "UDI-1"
        self.assertEqual(content_status(device), "complete")


class RunnerTests(unittest.TestCase):
    def test_missing_key_writes_blocked_summary_without_product_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "input.json"
            official_path = root / "official.json"
            matches_path = root / "matches.json"
            summary_path = root / "summary.json"
            input_path.write_text(json.dumps([{"id": "retail-1", "name": "테스트정", "capacity": "10정"}], ensure_ascii=False), encoding="utf-8")
            args = Namespace(
                input=input_path,
                official=official_path,
                matches=matches_path,
                summary=summary_path,
                cache=root / "cache",
                start=0,
                limit=25,
                requests_per_second=10.0,
                force=False,
                check=False,
                report_only=False,
            )
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(collect_batch(args), 0)
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "blocked_missing_key")
            self.assertFalse(official_path.exists())
            self.assertFalse(matches_path.exists())

    def test_missing_key_with_partial_cache_still_reports_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "input.json"
            summary_path = root / "summary.json"
            cache_path = root / "cache/15075057/easy_drug/cached.json"
            input_path.write_text(json.dumps([{"id": "retail-1", "name": "테스트정"}], ensure_ascii=False), encoding="utf-8")
            cache_path.parent.mkdir(parents=True)
            cache_path.write_text("{}", encoding="utf-8")
            args = Namespace(
                input=input_path, official=root / "official.json", matches=root / "matches.json",
                summary=summary_path, cache=root / "cache", start=0, limit=25,
                requests_per_second=10.0, force=False, check=False, report_only=False,
            )
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(collect_batch(args), 0)
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "blocked_missing_key")
            self.assertTrue(summary["outputs_untouched"])


class ReviewExportTests(unittest.TestCase):
    def test_lookup_status_preserves_internal_match_meaning(self):
        self.assertEqual(lookup_status("confirmed"), "found")
        self.assertEqual(lookup_status("review_required"), "found")
        self.assertEqual(lookup_status("not_found"), "not_found")
        self.assertEqual(lookup_status("blocked_missing_key"), "blocked")
        self.assertEqual(lookup_status("pending"), "pending")

    def test_score_reason_names_components_for_reviewers(self):
        reason = score_reason({"score_components": {"name": 60, "capacity": 15}})
        self.assertEqual(reason, "제품명 60점, 규격 15점")

    def test_schema_statuses_match_runtime_statuses(self):
        root = Path(__file__).resolve().parents[1]
        internal = json.loads((root / "schemas/official-match.schema.json").read_text(encoding="utf-8"))
        review = json.loads((root / "schemas/gpt-pro-official-review-row.schema.json").read_text(encoding="utf-8"))
        expected = {
            "pending", "confirmed", "review_required", "not_found",
            "not_applicable", "blocked_missing_key", "error",
        }
        self.assertEqual(set(internal["properties"]["status"]["enum"]), expected)
        self.assertEqual(set(review["properties"]["match_status"]["enum"]), expected)


if __name__ == "__main__":
    unittest.main()
