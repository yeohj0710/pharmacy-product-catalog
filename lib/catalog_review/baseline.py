"""Validation and hashing for the restored production catalog baseline."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable


def field_schema(rows: list[dict]) -> dict:
    """Return the observed field union and row-width distribution."""
    field_union = sorted({field for row in rows for field in row})
    distribution = dict(sorted(Counter(len(row) for row in rows).items()))
    return {
        "field_union": field_union,
        "row_field_count_distribution": distribution,
    }


def validate_baseline(
    rows: list[dict],
    expected_count: int,
    expected_field_union: Iterable[str] | None = None,
) -> dict:
    """Validate immutable identity, ordering, field, and conditional rules."""
    if len(rows) != expected_count:
        raise ValueError(f"unexpected row count: expected {expected_count}, got {len(rows)}")

    ids: list[str] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"row {index} must be a JSON object")
        product_id = row.get("id")
        if not isinstance(product_id, str) or not product_id.strip():
            raise ValueError("all products must have non-empty string IDs")
        ids.append(product_id)

    duplicate_ids = sorted(product_id for product_id, count in Counter(ids).items() if count > 1)
    if duplicate_ids:
        raise ValueError(f"duplicate product IDs: {duplicate_ids}")

    if any("source_order" in row for row in rows):
        for index, row in enumerate(rows, start=1):
            source_order = row.get("source_order")
            if isinstance(source_order, bool) or not isinstance(source_order, int) or source_order != index:
                raise ValueError(
                    f"source_order must be an integer matching file order; row {index} has {source_order!r}"
                )

    observed_schema = field_schema(rows)
    if expected_field_union is not None:
        expected_fields = set(expected_field_union)
        observed_fields = set(observed_schema["field_union"])
        if observed_fields != expected_fields:
            missing = sorted(expected_fields - observed_fields)
            extra = sorted(observed_fields - expected_fields)
            raise ValueError(f"unexpected field union: missing={missing}, extra={extra}")

        core_fields = expected_fields - {"official_content"}
        for index, row in enumerate(rows, start=1):
            required_fields = (
                expected_fields
                if row.get("official_match_status") == "confirmed"
                else core_fields
            )
            row_fields = set(row)
            if row_fields != required_fields:
                missing = sorted(required_fields - row_fields)
                extra = sorted(row_fields - required_fields)
                raise ValueError(
                    f"unexpected row fields at row {index}: missing={missing}, extra={extra}"
                )

    for index, row in enumerate(rows, start=1):
        has_official_content = "official_content" in row
        is_confirmed = row.get("official_match_status") == "confirmed"
        if has_official_content != is_confirmed:
            raise ValueError(
                "official_content must be present exactly when official_match_status is confirmed "
                f"(row {index})"
            )

    return {"count": len(rows), **observed_schema}


def canonical_json_sha256(rows: list[dict]) -> str:
    """Hash a compact UTF-8 JSON representation while preserving key order."""
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
