from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.catalog_review.baseline import canonical_json_sha256, field_schema
from lib.catalog_review.ledger import validate_batch


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


def validate_queue_file(
    *,
    queue_path: Path,
    baseline_path: Path = DEFAULT_BASELINE,
    manifest_path: Path = DEFAULT_MANIFEST,
    field_schema_path: Path = DEFAULT_FIELD_SCHEMA,
    allow_pending: bool = False,
) -> dict:
    queue_path = Path(queue_path)
    batch = _load_json(queue_path)
    baseline = _load_json(Path(baseline_path))
    manifest = _load_json(Path(manifest_path))
    canonical_fields = _load_json(Path(field_schema_path))
    if not isinstance(batch, dict):
        raise ValueError("review queue must be a JSON object")
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
