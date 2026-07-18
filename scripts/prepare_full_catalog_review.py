from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.catalog_review.baseline import canonical_json_sha256, field_schema, validate_baseline
from lib.catalog_review.ledger import (
    field_union_sha256,
    make_review_record,
    split_batch_sizes,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = ROOT / "data" / "enrichment-queue.json"
DEFAULT_MANIFEST = ROOT / "etc" / "catalog-verification" / "baseline-manifest.json"
DEFAULT_FIELD_SCHEMA = ROOT / "schemas" / "catalog-canonical-fields.json"
DEFAULT_OUTPUT_DIR = ROOT / "etc" / "catalog-verification" / "batches"
EXPECTED_FIELD_COUNT = 95


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"required input does not exist: {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON in {path}: {error}") from error


def _write_json_atomically(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(path)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary_path.unlink(missing_ok=True)
        raise


def prepare_review_batches(
    *,
    baseline_path: Path = DEFAULT_BASELINE,
    manifest_path: Path = DEFAULT_MANIFEST,
    field_schema_path: Path = DEFAULT_FIELD_SCHEMA,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    batch_count: int = 4,
    reviewer: str = "agent-1",
) -> dict:
    baseline = _load_json(Path(baseline_path))
    manifest = _load_json(Path(manifest_path))
    canonical_fields = _load_json(Path(field_schema_path))
    if not isinstance(baseline, list):
        raise ValueError("baseline must be a JSON array")
    if not isinstance(manifest, dict):
        raise ValueError("baseline manifest must be a JSON object")
    if not isinstance(canonical_fields, dict):
        raise ValueError("canonical field schema must be a JSON object")

    observed_field_union = field_schema(baseline)["field_union"]
    declared_field_union = canonical_fields.get("field_union")
    if not isinstance(declared_field_union, list):
        raise ValueError("canonical field schema must contain field_union")
    if observed_field_union != declared_field_union:
        raise ValueError("baseline field union does not match canonical field schema")
    if len(observed_field_union) != EXPECTED_FIELD_COUNT:
        raise ValueError(
            f"expected {EXPECTED_FIELD_COUNT} canonical fields, got {len(observed_field_union)}"
        )
    validate_baseline(
        baseline,
        expected_count=manifest.get("count"),
        expected_field_union=observed_field_union,
    )

    baseline_sha256 = canonical_json_sha256(baseline)
    if manifest.get("canonical_json_sha256") != baseline_sha256:
        raise ValueError("baseline bytes do not match baseline manifest canonical SHA-256")
    if manifest.get("field_union") != observed_field_union:
        raise ValueError("baseline manifest field union does not match canonical baseline")

    batch_sizes = split_batch_sizes(baseline, batch_count)
    batches = []
    ordered_generated_ids = []
    offset = 0
    for batch_index, batch_size in enumerate(batch_sizes, start=1):
        assigned_products = baseline[offset : offset + batch_size]
        source_order_start = offset + 1
        source_order_end = offset + batch_size
        assigned_product_ids = [product["id"] for product in assigned_products]
        records = [
            make_review_record(
                product,
                observed_field_union,
                baseline_sha256=baseline_sha256,
                reviewer=reviewer,
            )
            for product in assigned_products
        ]
        batch = {
            "schema_version": "1.0",
            "assignment": {
                "batch_id": f"batch-{batch_index:02d}",
                "batch_number": batch_index,
                "batch_count": batch_count,
                "source_order_start": source_order_start,
                "source_order_end": source_order_end,
                "product_count": batch_size,
                "baseline_count": len(baseline),
                "baseline_sha256": baseline_sha256,
                "field_union_sha256": field_union_sha256(observed_field_union),
                "assigned_product_ids": assigned_product_ids,
            },
            "products": records,
        }
        batches.append(batch)
        ordered_generated_ids.extend(assigned_product_ids)
        offset += batch_size

    baseline_ids = [product["id"] for product in baseline]
    if ordered_generated_ids != baseline_ids:
        raise RuntimeError("generated batch IDs do not exactly cover the canonical baseline")

    output_dir = Path(output_dir)
    for batch in batches:
        batch_id = batch["assignment"]["batch_id"]
        _write_json_atomically(output_dir / f"{batch_id}.json", batch)

    return {
        "batch_count": len(batches),
        "batch_sizes": batch_sizes,
        "product_count": len(ordered_generated_ids),
        "baseline_count": len(baseline_ids),
        "field_review_keys_per_product": len(observed_field_union),
        "baseline_sha256": baseline_sha256,
        "output_dir": str(output_dir),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create deterministic full-catalog review assignments."
    )
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--field-schema", type=Path, default=DEFAULT_FIELD_SCHEMA)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--batch-count", type=int, default=4)
    parser.add_argument("--reviewer", default="agent-1")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = prepare_review_batches(
        baseline_path=args.baseline,
        manifest_path=args.manifest,
        field_schema_path=args.field_schema,
        output_dir=args.output_dir,
        batch_count=args.batch_count,
        reviewer=args.reviewer,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
