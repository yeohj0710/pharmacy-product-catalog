import copy
import hashlib
import io
import json
import unittest
from pathlib import Path
from unittest import mock

from lib.catalog_review.baseline import canonical_json_sha256
from lib.catalog_review.ledger import (
    FIELD_DECISIONS,
    REVIEW_DIMENSIONS,
    make_review_record,
    split_batch_sizes,
    validate_batch,
)


ROOT = Path(__file__).resolve().parents[1]


class CatalogReviewLedgerTests(unittest.TestCase):
    def setUp(self):
        self.field_union = [
            "id",
            "name",
            "source_order",
            "official_match_status",
            "official_content",
        ]
        self.baseline = [
            {
                "id": "p-1",
                "name": "First",
                "source_order": 1,
                "official_match_status": "confirmed",
                "official_content": {"efficacy": "content"},
            },
            {
                "id": "p-2",
                "name": "Second",
                "source_order": 2,
                "official_match_status": "not_applicable",
            },
            {
                "id": "p-3",
                "name": "Third",
                "source_order": 3,
                "official_match_status": "not_applicable",
            },
            {
                "id": "p-4",
                "name": "Fourth",
                "source_order": 4,
                "official_match_status": "not_applicable",
            },
        ]
        self.baseline_sha256 = canonical_json_sha256(self.baseline)

    def make_batch(self, *, batch_number=1, products=None):
        sizes = split_batch_sizes(self.baseline, batch_count=2)
        start = 1 + sum(sizes[: batch_number - 1])
        end = start + sizes[batch_number - 1] - 1
        assigned = self.baseline[start - 1 : end]
        if products is None:
            products = [
                make_review_record(
                    product,
                    self.field_union,
                    baseline_sha256=self.baseline_sha256,
                    reviewer="agent-1",
                )
                for product in assigned
            ]
        return {
            "schema_version": "1.0",
            "assignment": {
                "batch_id": f"batch-{batch_number:02d}",
                "batch_number": batch_number,
                "batch_count": 2,
                "source_order_start": start,
                "source_order_end": end,
                "product_count": len(assigned),
                "baseline_count": len(self.baseline),
                "baseline_sha256": self.baseline_sha256,
                "field_union_sha256": hashlib.sha256(
                    json.dumps(
                        self.field_union,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
                "assigned_product_ids": [product["id"] for product in assigned],
            },
            "products": products,
        }

    def make_canonical_batch(self, *, batch_number=1, batch_count=4):
        baseline = [
            {
                "id": f"p-{source_order}",
                "source_order": source_order,
                "official_match_status": "not_applicable",
            }
            for source_order in range(1, 777)
        ]
        field_union = ["id", "official_match_status", "source_order"]
        baseline_sha256 = canonical_json_sha256(baseline)
        sizes = split_batch_sizes(baseline, batch_count=batch_count)
        start = 1 + sum(sizes[: batch_number - 1])
        end = start + sizes[batch_number - 1] - 1
        assigned = baseline[start - 1 : end]
        batch = {
            "schema_version": "1.0",
            "assignment": {
                "batch_id": f"batch-{batch_number:02d}",
                "batch_number": batch_number,
                "batch_count": batch_count,
                "source_order_start": start,
                "source_order_end": end,
                "product_count": len(assigned),
                "baseline_count": len(baseline),
                "baseline_sha256": baseline_sha256,
                "field_union_sha256": hashlib.sha256(
                    json.dumps(
                        field_union,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
                "assigned_product_ids": [product["id"] for product in assigned],
            },
            "products": [
                make_review_record(
                    product,
                    field_union,
                    baseline_sha256=baseline_sha256,
                    reviewer="agent-1",
                )
                for product in assigned
            ],
        }
        return batch, baseline, field_union

    def validate_fixture_batch(self, batch, *, allow_pending=False):
        return validate_batch(
            batch,
            self.baseline,
            self.field_union,
            allow_pending=allow_pending,
            expected_batch_count=2,
        )

    def mark_complete(self, batch):
        for product in batch["products"]:
            for field_review in product["field_reviews"].values():
                if field_review["decision"] == "pending":
                    field_review.update(
                        {
                            "decision": "verified",
                            "method": "baseline_comparison",
                            "reviewed_at": "2026-07-18T12:00:00+09:00",
                            "reason": "Matched the opened source.",
                        }
                    )
            for dimension in product["dimensions"].values():
                dimension.update(
                    {
                        "decision": "approved",
                        "reviewed_at": "2026-07-18T12:00:00+09:00",
                        "reason": "Dimension reviewed.",
                    }
                )
            for pass_name in ("first_pass", "second_pass"):
                product[pass_name].update(
                    {
                        "decision": "approved",
                        "reviewed_at": "2026-07-18T12:00:00+09:00",
                        "reason": "Pass complete.",
                    }
                )
            product["final_decision"] = "approved"
        return batch

    def test_declares_required_field_decisions_and_dimensions(self):
        self.assertEqual(
            FIELD_DECISIONS,
            {
                "pending",
                "verified",
                "corrected",
                "not_applicable",
                "verified_exception",
            },
        )
        self.assertEqual(
            REVIEW_DIMENSIONS,
            (
                "identity",
                "capacity",
                "category",
                "price_preservation",
                "official_match",
                "official_content",
                "image",
                "provenance",
            ),
        )

    def test_make_review_record_covers_every_field_with_hash_only_scaffolds(self):
        product = self.baseline[1]
        record = make_review_record(
            product,
            self.field_union,
            baseline_sha256="abc",
            reviewer="agent-1",
        )

        self.assertEqual(set(record["field_reviews"]), set(self.field_union))
        self.assertEqual(record["catalog_product_id"], "p-2")
        self.assertEqual(record["baseline_sha256"], "abc")
        self.assertEqual(set(record["dimensions"]), set(REVIEW_DIMENSIONS))
        required_review_keys = {
            "original_value_sha256",
            "decision",
            "applicability",
            "method",
            "evidence_ids",
            "reviewer",
            "reviewed_at",
            "reason",
        }
        for field_review in record["field_reviews"].values():
            self.assertEqual(set(field_review), required_review_keys)
        serialized = json.dumps(record, ensure_ascii=False)
        self.assertNotIn('"original_value"', serialized)
        self.assertNotIn('"content": "content"', serialized)

    def test_official_content_is_not_applicable_when_absent_or_unconfirmed(self):
        absent = make_review_record(
            self.baseline[1], self.field_union, baseline_sha256="abc", reviewer="agent-1"
        )
        present_but_unconfirmed = make_review_record(
            {
                **self.baseline[1],
                "official_content": {"stale": "must not be reviewed as applicable"},
            },
            self.field_union,
            baseline_sha256="abc",
            reviewer="agent-1",
        )

        for record in (absent, present_but_unconfirmed):
            review = record["field_reviews"]["official_content"]
            self.assertEqual(review["applicability"], "not_applicable")
            self.assertEqual(review["decision"], "not_applicable")

    def test_official_content_is_applicable_for_a_confirmed_match(self):
        record = make_review_record(
            self.baseline[0], self.field_union, baseline_sha256="abc", reviewer="agent-1"
        )
        review = record["field_reviews"]["official_content"]
        self.assertEqual(review["applicability"], "applicable")
        self.assertEqual(review["decision"], "pending")

    def test_split_batch_sizes_is_accurate_and_balanced(self):
        self.assertEqual(
            split_batch_sizes(list(range(776)), batch_count=4),
            [194, 194, 194, 194],
        )
        self.assertEqual(split_batch_sizes(list(range(10)), batch_count=4), [3, 3, 2, 2])

    def test_canonical_776_product_ranges_are_fixed(self):
        expected_ranges = [(1, 194), (195, 388), (389, 582), (583, 776)]
        for batch_number, expected_range in enumerate(expected_ranges, start=1):
            with self.subTest(batch_number=batch_number):
                batch, baseline, field_union = self.make_canonical_batch(
                    batch_number=batch_number
                )
                summary = validate_batch(
                    batch, baseline, field_union, allow_pending=True
                )
                self.assertEqual(
                    (summary["source_order_start"], summary["source_order_end"]),
                    expected_range,
                )

    def test_validate_batch_rejects_self_declared_widened_canonical_batch(self):
        batch, baseline, field_union = self.make_canonical_batch(batch_count=1)

        with self.assertRaisesRegex(ValueError, "batch_count must be exactly 4"):
            validate_batch(batch, baseline, field_union, allow_pending=True)

    def test_validate_batch_rejects_canonical_batch_number_outside_one_to_four(self):
        batch, baseline, field_union = self.make_canonical_batch()
        batch["assignment"]["batch_number"] = 5
        batch["assignment"]["batch_id"] = "batch-05"

        with self.assertRaisesRegex(ValueError, "batch_number must be between 1 and 4"):
            validate_batch(batch, baseline, field_union, allow_pending=True)

    def test_prepare_cli_does_not_accept_batch_count_override(self):
        from scripts.prepare_full_catalog_review import parse_args

        with mock.patch(
            "sys.argv",
            ["prepare_full_catalog_review.py", "--batch-count", "1"],
        ), mock.patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit):
                parse_args()

    def test_validate_batch_accepts_exact_complete_assignment(self):
        batch = self.mark_complete(self.make_batch())
        summary = self.validate_fixture_batch(batch)
        self.assertEqual(summary["product_count"], 2)
        self.assertEqual(summary["field_review_count"], 10)

    def test_validate_batch_rejects_missing_product(self):
        batch = self.make_batch()
        batch["products"].pop()
        with self.assertRaisesRegex(ValueError, "missing product"):
            self.validate_fixture_batch(batch, allow_pending=True)

    def test_validate_batch_rejects_duplicate_product_id(self):
        batch = self.make_batch()
        batch["products"][1] = copy.deepcopy(batch["products"][0])
        with self.assertRaisesRegex(ValueError, "duplicate product ID"):
            self.validate_fixture_batch(batch, allow_pending=True)

    def test_validate_batch_rejects_unknown_field(self):
        batch = self.make_batch()
        batch["products"][0]["field_reviews"]["invented_field"] = copy.deepcopy(
            batch["products"][0]["field_reviews"]["name"]
        )
        with self.assertRaisesRegex(ValueError, "unknown field"):
            self.validate_fixture_batch(batch, allow_pending=True)

    def test_validate_batch_rejects_pending_decision_unless_allowed(self):
        batch = self.make_batch()
        with self.assertRaisesRegex(ValueError, "pending decision"):
            self.validate_fixture_batch(batch)

        summary = self.validate_fixture_batch(batch, allow_pending=True)
        self.assertEqual(summary["pending_field_count"], 9)

    def test_validate_batch_rejects_correction_without_opened_source_url(self):
        batch = self.mark_complete(self.make_batch())
        record = batch["products"][0]
        record["field_reviews"]["name"]["decision"] = "corrected"
        record["corrections"] = [
            {
                "field": "name",
                "before_value": "First",
                "after_value": "Corrected First",
                "reason": "The source shows a different name.",
                "evidence_ids": ["source-1"],
                "reviewer": "agent-1",
                "reviewed_at": "2026-07-18T12:00:00+09:00",
            }
        ]
        record["evidence"] = [
            {
                "evidence_id": "source-1",
                "opened_source_url": "",
                "source_type": "official",
                "accessed_at": "2026-07-18T12:00:00+09:00",
                "note": "Not actually opened.",
            }
        ]
        with self.assertRaisesRegex(ValueError, "opened source URL"):
            self.validate_fixture_batch(batch)

    def test_validate_batch_rejects_mismatched_original_hash(self):
        batch = self.make_batch()
        batch["products"][0]["field_reviews"]["name"][
            "original_value_sha256"
        ] = "0" * 64
        with self.assertRaisesRegex(ValueError, "original mismatch"):
            self.validate_fixture_batch(batch, allow_pending=True)

    def test_validate_batch_rejects_correction_with_mismatched_before_value(self):
        batch = self.mark_complete(self.make_batch())
        record = batch["products"][0]
        record["field_reviews"]["name"]["decision"] = "corrected"
        record["field_reviews"]["name"]["evidence_ids"] = ["source-1"]
        record["corrections"] = [
            {
                "field": "name",
                "before_value": "Not the baseline value",
                "after_value": "Corrected First",
                "reason": "The source shows a different name.",
                "evidence_ids": ["source-1"],
                "reviewer": "agent-1",
                "reviewed_at": "2026-07-18T12:00:00+09:00",
            }
        ]
        record["evidence"] = [
            {
                "evidence_id": "source-1",
                "opened_source_url": "https://example.test/products/p-1",
                "source_type": "official",
                "accessed_at": "2026-07-18T12:00:00+09:00",
                "note": "Opened product page.",
            }
        ]
        with self.assertRaisesRegex(ValueError, "correction before_value mismatch"):
            self.validate_fixture_batch(batch)

    def test_validate_batch_rejects_product_outside_assigned_range(self):
        batch = self.make_batch()
        batch["products"][1] = make_review_record(
            self.baseline[2],
            self.field_union,
            baseline_sha256=self.baseline_sha256,
            reviewer="agent-1",
        )
        with self.assertRaisesRegex(ValueError, "outside assigned range"):
            self.validate_fixture_batch(batch, allow_pending=True)

    def test_validate_batch_rejects_assignment_that_does_not_match_baseline(self):
        batch = self.make_batch()
        batch["assignment"]["baseline_sha256"] = "f" * 64
        for product in batch["products"]:
            product["baseline_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "canonical baseline"):
            self.validate_fixture_batch(batch, allow_pending=True)

    def test_schema_has_closed_stable_boundaries_and_exact_final_decisions(self):
        schema = json.loads(
            (ROOT / "schemas/catalog-review-ledger.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            set(schema["required"]),
            {
                "schema_version",
                "catalog_product_id",
                "source_order",
                "baseline_sha256",
                "field_reviews",
                "dimensions",
                "corrections",
                "evidence",
                "first_pass",
                "second_pass",
                "final_decision",
            },
        )
        self.assertEqual(
            set(schema["properties"]["final_decision"]["enum"]),
            {"pending", "approved", "corrected", "rejected", "exception_approved"},
        )
        definitions = schema["$defs"]
        for definition in (
            "field_review",
            "dimension_review",
            "correction",
            "evidence",
            "pass_review",
        ):
            self.assertFalse(definitions[definition]["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
