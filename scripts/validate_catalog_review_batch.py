from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.catalog_review.baseline import canonical_json_sha256, field_schema
from lib.catalog_review.ledger import (
    BATCH_SET_MANIFEST_NAME,
    CANONICAL_BATCH_COUNT,
    CANONICAL_PRODUCT_COUNT,
    batch_set_sha256,
    field_union_sha256,
    validate_batch,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = ROOT / "data" / "enrichment-queue.json"
DEFAULT_MANIFEST = ROOT / "etc" / "catalog-verification" / "baseline-manifest.json"
DEFAULT_FIELD_SCHEMA = ROOT / "schemas" / "catalog-canonical-fields.json"


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"required input does not exist: {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON in {path}: {error}") from error


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except FileNotFoundError as error:
        raise ValueError(f"batch set marker references missing file: {path.name}") from error
    return digest.hexdigest()


def _validate_current_batch_set(
    queue_dir: Path,
    baseline_sha256: str,
    field_union: list[str],
) -> dict:
    marker_path = queue_dir / BATCH_SET_MANIFEST_NAME
    marker = _load_json(marker_path)
    expected_marker_keys = {
        "schema_version",
        "complete",
        "set_id",
        "generated_at",
        "baseline_sha256",
        "baseline_count",
        "batch_count",
        "field_union_sha256",
        "batches",
    }
    if not isinstance(marker, dict) or set(marker) != expected_marker_keys:
        raise ValueError("batch set marker has invalid keys")
    if marker["schema_version"] != "1.0" or marker["complete"] is not True:
        raise ValueError("batch set marker is not complete")
    if marker["baseline_sha256"] != baseline_sha256:
        raise ValueError("batch set marker does not match canonical baseline")
    if marker["baseline_count"] != CANONICAL_PRODUCT_COUNT:
        raise ValueError("batch set marker has noncanonical baseline count")
    if marker["batch_count"] != CANONICAL_BATCH_COUNT:
        raise ValueError("batch set marker has noncanonical batch count")
    if marker["field_union_sha256"] != field_union_sha256(field_union):
        raise ValueError("batch set marker does not match canonical field union")
    if not isinstance(marker["generated_at"], str) or not marker["generated_at"].strip():
        raise ValueError("batch set marker generated_at must be a non-empty string")
    entries = marker["batches"]
    if not isinstance(entries, list) or len(entries) != CANONICAL_BATCH_COUNT:
        raise ValueError("batch set marker must list exactly four batches")

    expected_entry_keys = {
        "batch_id",
        "file_name",
        "sha256",
        "product_count",
        "source_order_start",
        "source_order_end",
    }
    batch_hashes = []
    for batch_number, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict) or set(entry) != expected_entry_keys:
            raise ValueError(f"batch set marker entry {batch_number} has invalid keys")
        batch_id = f"batch-{batch_number:02d}"
        file_name = f"{batch_id}.json"
        start = (batch_number - 1) * 194 + 1
        end = batch_number * 194
        expected_values = {
            "batch_id": batch_id,
            "file_name": file_name,
            "product_count": 194,
            "source_order_start": start,
            "source_order_end": end,
        }
        for key, expected_value in expected_values.items():
            if entry[key] != expected_value:
                raise ValueError(
                    f"batch set marker entry {batch_number} has invalid {key}"
                )
        batch_path = queue_dir / file_name
        actual_hash = _file_sha256(batch_path)
        if entry["sha256"] != actual_hash:
            raise ValueError(f"batch set marker hash mismatch for {file_name}")
        batch_hashes.append(actual_hash)

    expected_set_id = batch_set_sha256(baseline_sha256, batch_hashes)
    if marker["set_id"] != expected_set_id:
        raise ValueError("batch set marker set_id mismatch")
    return marker


def validate_queue_file(
    *,
    queue_path: Path,
    baseline_path: Path = DEFAULT_BASELINE,
    manifest_path: Path = DEFAULT_MANIFEST,
    field_schema_path: Path = DEFAULT_FIELD_SCHEMA,
    allow_pending: bool = False,
) -> dict:
    queue_path = Path(queue_path)
    baseline = _load_json(Path(baseline_path))
    manifest = _load_json(Path(manifest_path))
    canonical_fields = _load_json(Path(field_schema_path))
    if not isinstance(baseline, list):
        raise ValueError("baseline must be a JSON array")
    if not isinstance(manifest, dict):
        raise ValueError("baseline manifest must be a JSON object")
    if not isinstance(canonical_fields, dict):
        raise ValueError("canonical field schema must be a JSON object")

    field_union = canonical_fields.get("field_union")
    if not isinstance(field_union, list):
        raise ValueError("canonical field schema must contain field_union")
    if field_schema(baseline)["field_union"] != field_union:
        raise ValueError("baseline field union does not match canonical field schema")
    baseline_sha256 = canonical_json_sha256(baseline)
    if manifest.get("canonical_json_sha256") != baseline_sha256:
        raise ValueError("baseline does not match baseline manifest canonical SHA-256")
    if manifest.get("count") != len(baseline):
        raise ValueError("baseline count does not match baseline manifest")

    _validate_current_batch_set(queue_path.parent, baseline_sha256, field_union)
    batch = _load_json(queue_path)
    if not isinstance(batch, dict):
        raise ValueError("review queue must be a JSON object")

    return validate_batch(
        batch,
        baseline,
        field_union,
        allow_pending=allow_pending,
        expected_batch_id=queue_path.stem,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a review queue against its canonical baseline assignment."
    )
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--field-schema", type=Path, default=DEFAULT_FIELD_SCHEMA)
    parser.add_argument("--allow-pending", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = validate_queue_file(
        queue_path=args.queue,
        baseline_path=args.baseline,
        manifest_path=args.manifest,
        field_schema_path=args.field_schema,
        allow_pending=args.allow_pending,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
