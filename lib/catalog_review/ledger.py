"""Deterministic review ledgers and strict catalog batch validation."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from urllib.parse import urlparse

from .baseline import canonical_json_sha256


FIELD_DECISIONS = {
    "pending",
    "verified",
    "corrected",
    "not_applicable",
    "verified_exception",
}
REVIEW_DIMENSIONS = (
    "identity",
    "capacity",
    "category",
    "price_preservation",
    "official_match",
    "official_content",
    "image",
    "provenance",
)
FINAL_DECISIONS = {
    "pending",
    "approved",
    "corrected",
    "rejected",
    "exception_approved",
}

RECORD_KEYS = {
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
}
FIELD_REVIEW_KEYS = {
    "original_value_sha256",
    "decision",
    "applicability",
    "method",
    "evidence_ids",
    "reviewer",
    "reviewed_at",
    "reason",
}
DIMENSION_REVIEW_KEYS = {
    "decision",
    "evidence_ids",
    "reviewer",
    "reviewed_at",
    "reason",
}
PASS_REVIEW_KEYS = {"decision", "reviewer", "reviewed_at", "reason"}
CORRECTION_KEYS = {
    "field",
    "before_value",
    "after_value",
    "reason",
    "evidence_ids",
    "reviewer",
    "reviewed_at",
}
EVIDENCE_KEYS = {
    "evidence_id",
    "opened_source_url",
    "source_type",
    "accessed_at",
    "note",
}
ASSIGNMENT_KEYS = {
    "batch_id",
    "batch_number",
    "batch_count",
    "source_order_start",
    "source_order_end",
    "product_count",
    "baseline_count",
    "baseline_sha256",
    "field_union_sha256",
    "assigned_product_ids",
}


def value_sha256(value: object) -> str:
    """Return a semantic hash for a JSON value without retaining the value."""
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def field_union_sha256(field_union: Sequence[str]) -> str:
    """Hash the ordered canonical field contract used by an assignment."""
    payload = json.dumps(
        list(field_union),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _pending_pass(reviewer: str) -> dict:
    return {
        "decision": "pending",
        "reviewer": reviewer,
        "reviewed_at": "",
        "reason": "",
    }


def make_review_record(
    product: dict,
    field_union: Sequence[str],
    baseline_sha256: str = "abc",
    reviewer: str = "agent-1",
) -> dict:
    """Create a hash-only review scaffold covering the complete field union."""
    product_id = product.get("id")
    source_order = product.get("source_order")
    if not isinstance(product_id, str) or not product_id.strip():
        raise ValueError("product must have a non-empty string ID")
    if isinstance(source_order, bool) or not isinstance(source_order, int):
        raise ValueError("product must have an integer source_order")
    if len(set(field_union)) != len(field_union):
        raise ValueError("field_union contains duplicate field names")

    field_reviews = {}
    for field in field_union:
        official_content_not_applicable = (
            field == "official_content"
            and (
                field not in product
                or product.get("official_match_status") != "confirmed"
            )
        )
        field_reviews[field] = {
            "original_value_sha256": value_sha256(product.get(field)),
            "decision": (
                "not_applicable" if official_content_not_applicable else "pending"
            ),
            "applicability": (
                "not_applicable"
                if official_content_not_applicable
                else "applicable"
            ),
            "method": (
                "conditional_rule" if official_content_not_applicable else "unreviewed"
            ),
            "evidence_ids": [],
            "reviewer": reviewer,
            "reviewed_at": "",
            "reason": (
                "official_content applies only to confirmed official matches"
                if official_content_not_applicable
                else ""
            ),
        }

    dimensions = {
        dimension: {
            "decision": "pending",
            "evidence_ids": [],
            "reviewer": reviewer,
            "reviewed_at": "",
            "reason": "",
        }
        for dimension in REVIEW_DIMENSIONS
    }
    return {
        "schema_version": "1.0",
        "catalog_product_id": product_id,
        "source_order": source_order,
        "baseline_sha256": baseline_sha256,
        "field_reviews": field_reviews,
        "dimensions": dimensions,
        "corrections": [],
        "evidence": [],
        "first_pass": _pending_pass(reviewer),
        "second_pass": _pending_pass(""),
        "final_decision": "pending",
    }


def split_batch_sizes(items: Sequence[object], batch_count: int) -> list[int]:
    """Return balanced batch sizes, assigning remainders to earlier batches."""
    if isinstance(batch_count, bool) or not isinstance(batch_count, int) or batch_count <= 0:
        raise ValueError("batch_count must be a positive integer")
    base_size, remainder = divmod(len(items), batch_count)
    return [base_size + (1 if index < remainder else 0) for index in range(batch_count)]


def _require_exact_keys(value: dict, expected: set[str], label: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(f"invalid {label} keys: missing={missing}, extra={extra}")


def _is_opened_url(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _validate_baseline_for_batch(baseline_rows: Sequence[dict]) -> None:
    if not baseline_rows:
        raise ValueError("canonical baseline must not be empty")
    ids = []
    for expected_order, product in enumerate(baseline_rows, start=1):
        if not isinstance(product, dict):
            raise ValueError("canonical baseline products must be objects")
        product_id = product.get("id")
        if not isinstance(product_id, str) or not product_id.strip():
            raise ValueError("canonical baseline contains an invalid product ID")
        ids.append(product_id)
        if product.get("source_order") != expected_order:
            raise ValueError("canonical baseline source_order does not match file order")
    if len(set(ids)) != len(ids):
        raise ValueError("canonical baseline contains duplicate product IDs")


def _validate_assignment(
    assignment: dict,
    baseline_rows: Sequence[dict],
    field_union: Sequence[str],
    expected_batch_id: str | None,
) -> tuple[list[dict], list[str]]:
    _require_exact_keys(assignment, ASSIGNMENT_KEYS, "assignment")
    batch_number = assignment["batch_number"]
    batch_count = assignment["batch_count"]
    if (
        isinstance(batch_number, bool)
        or not isinstance(batch_number, int)
        or isinstance(batch_count, bool)
        or not isinstance(batch_count, int)
        or batch_count <= 0
        or not 1 <= batch_number <= batch_count
    ):
        raise ValueError("assignment has invalid batch number or count")

    canonical_batch_id = f"batch-{batch_number:02d}"
    if assignment["batch_id"] != canonical_batch_id:
        raise ValueError("assignment batch_id does not match batch_number")
    if expected_batch_id is not None and assignment["batch_id"] != expected_batch_id:
        raise ValueError("assignment batch_id does not match queue filename")

    sizes = split_batch_sizes(baseline_rows, batch_count)
    expected_start = 1 + sum(sizes[: batch_number - 1])
    expected_end = expected_start + sizes[batch_number - 1] - 1
    assigned_products = list(baseline_rows[expected_start - 1 : expected_end])
    expected_ids = [product["id"] for product in assigned_products]
    expected_hash = canonical_json_sha256(list(baseline_rows))

    if assignment["baseline_sha256"] != expected_hash:
        raise ValueError("assignment does not match the canonical baseline SHA-256")
    if assignment["field_union_sha256"] != field_union_sha256(field_union):
        raise ValueError("assignment does not match the canonical field union")
    expected_metadata = {
        "source_order_start": expected_start,
        "source_order_end": expected_end,
        "product_count": len(assigned_products),
        "baseline_count": len(baseline_rows),
        "assigned_product_ids": expected_ids,
    }
    for key, expected_value in expected_metadata.items():
        if assignment[key] != expected_value:
            raise ValueError(f"assignment {key} does not match canonical baseline")
    return assigned_products, expected_ids


def _validate_evidence(record: dict, label: str) -> dict[str, dict]:
    evidence_entries = record["evidence"]
    if not isinstance(evidence_entries, list):
        raise ValueError(f"{label} evidence must be an array")
    evidence_by_id = {}
    for index, evidence in enumerate(evidence_entries):
        _require_exact_keys(evidence, EVIDENCE_KEYS, f"{label} evidence {index}")
        evidence_id = evidence["evidence_id"]
        if not isinstance(evidence_id, str) or not evidence_id.strip():
            raise ValueError(f"{label} has an invalid evidence ID")
        if evidence_id in evidence_by_id:
            raise ValueError(f"{label} has duplicate evidence ID {evidence_id!r}")
        evidence_by_id[evidence_id] = evidence
    return evidence_by_id


def _validate_passes_and_dimensions(
    record: dict, label: str, allow_pending: bool
) -> None:
    dimensions = record["dimensions"]
    _require_exact_keys(dimensions, set(REVIEW_DIMENSIONS), f"{label} dimensions")
    for dimension_name, dimension in dimensions.items():
        _require_exact_keys(
            dimension,
            DIMENSION_REVIEW_KEYS,
            f"{label} dimension {dimension_name}",
        )
        decision = dimension["decision"]
        if decision not in FINAL_DECISIONS:
            raise ValueError(f"{label} dimension {dimension_name} has invalid decision")
        if decision == "pending" and not allow_pending:
            raise ValueError(f"{label} has a pending decision")

    for pass_name in ("first_pass", "second_pass"):
        pass_review = record[pass_name]
        _require_exact_keys(pass_review, PASS_REVIEW_KEYS, f"{label} {pass_name}")
        decision = pass_review["decision"]
        if decision not in FINAL_DECISIONS:
            raise ValueError(f"{label} {pass_name} has invalid decision")
        if decision == "pending" and not allow_pending:
            raise ValueError(f"{label} has a pending decision")

    final_decision = record["final_decision"]
    if final_decision not in FINAL_DECISIONS:
        raise ValueError(f"{label} has invalid final decision")
    if final_decision == "pending" and not allow_pending:
        raise ValueError(f"{label} has a pending decision")


def _validate_record(
    record: dict,
    baseline_product: dict,
    field_union: Sequence[str],
    baseline_sha256: str,
    allow_pending: bool,
) -> int:
    product_id = baseline_product["id"]
    label = f"product {product_id!r}"
    _require_exact_keys(record, RECORD_KEYS, label)
    if record["schema_version"] != "1.0":
        raise ValueError(f"{label} has unsupported schema_version")
    if record["catalog_product_id"] != product_id:
        raise ValueError(f"{label} does not match canonical product ID")
    if record["source_order"] != baseline_product["source_order"]:
        raise ValueError(f"{label} does not match canonical source_order")
    if record["baseline_sha256"] != baseline_sha256:
        raise ValueError(f"{label} does not match canonical baseline")

    field_reviews = record["field_reviews"]
    if not isinstance(field_reviews, dict):
        raise ValueError(f"{label} field_reviews must be an object")
    expected_fields = set(field_union)
    actual_fields = set(field_reviews)
    unknown_fields = sorted(actual_fields - expected_fields)
    if unknown_fields:
        raise ValueError(f"{label} has unknown field names: {unknown_fields}")
    missing_fields = sorted(expected_fields - actual_fields)
    if missing_fields:
        raise ValueError(f"{label} has missing field reviews: {missing_fields}")

    evidence_by_id = _validate_evidence(record, label)
    pending_field_count = 0
    for field in field_union:
        field_review = field_reviews[field]
        _require_exact_keys(field_review, FIELD_REVIEW_KEYS, f"{label} field {field}")
        expected_original_hash = value_sha256(baseline_product.get(field))
        if field_review["original_value_sha256"] != expected_original_hash:
            raise ValueError(f"{label} field {field!r} original mismatch")
        decision = field_review["decision"]
        if decision not in FIELD_DECISIONS:
            raise ValueError(f"{label} field {field!r} has invalid decision")
        applicability = field_review["applicability"]
        if applicability not in {"applicable", "not_applicable"}:
            raise ValueError(f"{label} field {field!r} has invalid applicability")
        official_content_not_applicable = (
            field == "official_content"
            and (
                field not in baseline_product
                or baseline_product.get("official_match_status") != "confirmed"
            )
        )
        if official_content_not_applicable and (
            applicability != "not_applicable" or decision != "not_applicable"
        ):
            raise ValueError(f"{label} official_content must be not_applicable")
        if not official_content_not_applicable and decision == "not_applicable":
            raise ValueError(f"{label} field {field!r} cannot be not_applicable")
        evidence_ids = field_review["evidence_ids"]
        if not isinstance(evidence_ids, list) or not all(
            isinstance(item, str) for item in evidence_ids
        ):
            raise ValueError(f"{label} field {field!r} has invalid evidence_ids")
        unknown_evidence = sorted(set(evidence_ids) - set(evidence_by_id))
        if unknown_evidence:
            raise ValueError(
                f"{label} field {field!r} references unknown evidence: {unknown_evidence}"
            )
        if decision == "pending":
            pending_field_count += 1
            if not allow_pending:
                raise ValueError(f"{label} field {field!r} has a pending decision")

    corrections = record["corrections"]
    if not isinstance(corrections, list):
        raise ValueError(f"{label} corrections must be an array")
    correction_fields = []
    for index, correction in enumerate(corrections):
        _require_exact_keys(correction, CORRECTION_KEYS, f"{label} correction {index}")
        field = correction["field"]
        if field not in expected_fields:
            raise ValueError(f"{label} correction has unknown field {field!r}")
        if field in correction_fields:
            raise ValueError(f"{label} has duplicate correction for field {field!r}")
        correction_fields.append(field)
        if correction["before_value"] != baseline_product.get(field):
            raise ValueError(f"{label} correction before_value mismatch for field {field!r}")
        if correction["after_value"] == correction["before_value"]:
            raise ValueError(f"{label} correction must change field {field!r}")
        if field_reviews[field]["decision"] != "corrected":
            raise ValueError(f"{label} correction field {field!r} is not marked corrected")
        correction_evidence_ids = correction["evidence_ids"]
        if not isinstance(correction_evidence_ids, list):
            raise ValueError(f"{label} correction evidence_ids must be an array")
        opened_evidence = [
            evidence_by_id[evidence_id]
            for evidence_id in correction_evidence_ids
            if evidence_id in evidence_by_id
            and _is_opened_url(evidence_by_id[evidence_id]["opened_source_url"])
        ]
        if not opened_evidence:
            raise ValueError(f"{label} correction requires at least one opened source URL")

    marked_corrected = {
        field
        for field, review in field_reviews.items()
        if review["decision"] == "corrected"
    }
    if marked_corrected != set(correction_fields):
        raise ValueError(f"{label} corrected field decisions do not match corrections")

    _validate_passes_and_dimensions(record, label, allow_pending)
    return pending_field_count


def validate_batch(
    batch: dict,
    baseline_rows: Sequence[dict],
    field_union: Sequence[str],
    *,
    allow_pending: bool = False,
    expected_batch_id: str | None = None,
) -> dict:
    """Validate a batch against its immutable baseline and assigned range."""
    if not isinstance(batch, dict) or set(batch) != {
        "schema_version",
        "assignment",
        "products",
    }:
        raise ValueError("batch must contain only schema_version, assignment, and products")
    if batch["schema_version"] != "1.0":
        raise ValueError("batch has unsupported schema_version")
    if len(set(field_union)) != len(field_union):
        raise ValueError("canonical field union contains duplicates")
    _validate_baseline_for_batch(baseline_rows)
    assigned_products, expected_ids = _validate_assignment(
        batch["assignment"], baseline_rows, field_union, expected_batch_id
    )

    records = batch["products"]
    if not isinstance(records, list):
        raise ValueError("batch products must be an array")
    actual_ids = [
        record.get("catalog_product_id") if isinstance(record, dict) else None
        for record in records
    ]
    duplicate_ids = sorted(
        product_id
        for product_id, count in Counter(actual_ids).items()
        if product_id is not None and count > 1
    )
    if duplicate_ids:
        raise ValueError(f"duplicate product ID in batch: {duplicate_ids}")
    assigned_id_set = set(expected_ids)
    outside_ids = [product_id for product_id in actual_ids if product_id not in assigned_id_set]
    if outside_ids:
        raise ValueError(f"product outside assigned range: {outside_ids}")
    missing_ids = [product_id for product_id in expected_ids if product_id not in actual_ids]
    if missing_ids:
        raise ValueError(f"missing product from batch: {missing_ids}")
    if actual_ids != expected_ids:
        raise ValueError("batch products are not in assigned canonical order")

    baseline_hash = canonical_json_sha256(list(baseline_rows))
    pending_field_count = 0
    for record, baseline_product in zip(records, assigned_products, strict=True):
        pending_field_count += _validate_record(
            record,
            baseline_product,
            field_union,
            baseline_hash,
            allow_pending,
        )
    return {
        "batch_id": batch["assignment"]["batch_id"],
        "product_count": len(records),
        "field_review_count": len(records) * len(field_union),
        "pending_field_count": pending_field_count,
        "source_order_start": batch["assignment"]["source_order_start"],
        "source_order_end": batch["assignment"]["source_order_end"],
    }


__all__ = [
    "FIELD_DECISIONS",
    "FINAL_DECISIONS",
    "REVIEW_DIMENSIONS",
    "field_union_sha256",
    "make_review_record",
    "split_batch_sizes",
    "validate_batch",
    "value_sha256",
]
