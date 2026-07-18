from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.catalog_review.baseline import canonical_json_sha256, field_schema, validate_baseline
from lib.catalog_review.ledger import (
    BATCH_SET_LOCK_NAME,
    BATCH_SET_MANIFEST_NAME,
    CANONICAL_BATCH_COUNT,
    CANONICAL_PRODUCT_COUNT,
    batch_set_sha256,
    field_union_sha256,
    make_review_record,
    split_batch_sizes,
    validate_batch,
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


def _new_output_temp(target: Path, role: str) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=f".{role}", dir=target.parent
    )
    os.close(descriptor)
    return Path(temporary_name)


def _write_json_file(path: Path, payload: object) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _acquire_batch_set_lock(output_dir: Path) -> tuple[Path, int, bytes]:
    output_dir.mkdir(parents=True, exist_ok=True)
    lock_path = output_dir / BATCH_SET_LOCK_NAME
    lock_contents = f"pid={os.getpid()} token={uuid.uuid4().hex}\n".encode("ascii")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    try:
        descriptor = os.open(lock_path, flags)
    except FileExistsError as error:
        raise RuntimeError(
            f"batch set generation already in progress; lock file exists: {lock_path}"
        ) from error
    try:
        os.write(descriptor, lock_contents)
        os.fsync(descriptor)
    except Exception:
        os.close(descriptor)
        lock_path.unlink(missing_ok=True)
        raise
    return lock_path, descriptor, lock_contents


def _release_batch_set_lock(
    lock_path: Path, descriptor: int, lock_contents: bytes
) -> None:
    os.close(descriptor)
    try:
        current_contents = lock_path.read_bytes()
    except FileNotFoundError:
        return
    if current_contents == lock_contents:
        lock_path.unlink(missing_ok=True)


def _validate_staged_batch_set(
    staged_batches: list[tuple[Path, dict]],
    baseline: list[dict],
    field_union: list[str],
) -> None:
    ordered_ids = []
    if len(staged_batches) != CANONICAL_BATCH_COUNT:
        raise ValueError("staged batch set must contain exactly four batches")
    for batch_number, (staged_path, expected_batch) in enumerate(
        staged_batches, start=1
    ):
        staged_batch = _load_json(staged_path)
        if not isinstance(staged_batch, dict):
            raise ValueError(f"staged batch {batch_number} must be a JSON object")
        expected_batch_id = f"batch-{batch_number:02d}"
        validate_batch(
            staged_batch,
            baseline,
            field_union,
            allow_pending=True,
            expected_batch_id=expected_batch_id,
        )
        if staged_batch != expected_batch:
            raise ValueError(f"staged batch {batch_number} changed during serialization")
        ordered_ids.extend(
            record["catalog_product_id"] for record in staged_batch["products"]
        )
    if ordered_ids != [product["id"] for product in baseline]:
        raise ValueError("staged batch set does not exactly cover the canonical baseline")


def _publish_staged_batch_set(
    staged_targets: list[tuple[Path, Path]],
    temporary_paths: list[Path],
    retained_recovery_paths: set[Path],
) -> None:
    backups: dict[Path, Path | None] = {}
    target_existed: dict[Path, bool] = {}
    for _, target in staged_targets:
        existed = target.exists()
        target_existed[target] = existed
        backup_path = None
        if existed:
            backup_path = _new_output_temp(target, "backup")
            temporary_paths.append(backup_path)
            shutil.copy2(target, backup_path)
        backups[target] = backup_path

    attempted_targets: list[Path] = []
    try:
        for staged_path, target in staged_targets:
            attempted_targets.append(target)
            staged_path.replace(target)
    except Exception as publish_error:
        rollback_errors: list[tuple[Path, Exception]] = []
        for target in reversed(attempted_targets):
            backup_path = backups[target]
            try:
                if target_existed[target]:
                    assert backup_path is not None
                    backup_path.replace(target)
                else:
                    target.unlink(missing_ok=True)
            except Exception as rollback_error:
                rollback_errors.append((target, rollback_error))
                if backup_path is not None and backup_path.exists():
                    retained_recovery_paths.add(backup_path)
        if rollback_errors:
            rollback_details = "; ".join(
                f"{target.name}: {type(error).__name__}: {error}"
                for target, error in rollback_errors
            )
            retained_paths = ", ".join(
                str(path) for path in sorted(retained_recovery_paths)
            ) or "none"
            raise RuntimeError(
                "batch set publish failed and rollback was incomplete; "
                f"publish error: {type(publish_error).__name__}: {publish_error}; "
                f"rollback errors: {rollback_details}; "
                f"retained recovery paths: {retained_paths}"
            ) from publish_error
        raise


def prepare_review_batches(
    *,
    baseline_path: Path = DEFAULT_BASELINE,
    manifest_path: Path = DEFAULT_MANIFEST,
    field_schema_path: Path = DEFAULT_FIELD_SCHEMA,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    reviewer: str = "agent-1",
) -> dict:
    output_dir = Path(output_dir)
    lock_path, lock_descriptor, lock_contents = _acquire_batch_set_lock(output_dir)
    try:
        return _prepare_review_batches_locked(
            baseline_path=baseline_path,
            manifest_path=manifest_path,
            field_schema_path=field_schema_path,
            output_dir=output_dir,
            reviewer=reviewer,
        )
    finally:
        _release_batch_set_lock(lock_path, lock_descriptor, lock_contents)


def _prepare_review_batches_locked(
    *,
    baseline_path: Path,
    manifest_path: Path,
    field_schema_path: Path,
    output_dir: Path,
    reviewer: str,
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
    if len(baseline) != CANONICAL_PRODUCT_COUNT or manifest.get(
        "count"
    ) != CANONICAL_PRODUCT_COUNT:
        raise ValueError(
            f"expected exactly {CANONICAL_PRODUCT_COUNT} canonical products; "
            f"baseline has {len(baseline)}, manifest declares {manifest.get('count')!r}"
        )

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

    batch_sizes = split_batch_sizes(baseline, CANONICAL_BATCH_COUNT)
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
                scaffold_timestamp=manifest.get("retrieved_at"),
            )
            for product in assigned_products
        ]
        batch = {
            "schema_version": "1.0",
            "assignment": {
                "batch_id": f"batch-{batch_index:02d}",
                "batch_number": batch_index,
                "batch_count": CANONICAL_BATCH_COUNT,
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

    temporary_paths: list[Path] = []
    retained_recovery_paths: set[Path] = set()
    try:
        staged_batches: list[tuple[Path, dict]] = []
        staged_targets: list[tuple[Path, Path]] = []
        for batch in batches:
            batch_id = batch["assignment"]["batch_id"]
            target = output_dir / f"{batch_id}.json"
            staged_path = _new_output_temp(target, "staged")
            temporary_paths.append(staged_path)
            _write_json_file(staged_path, batch)
            staged_batches.append((staged_path, batch))
            staged_targets.append((staged_path, target))

        _validate_staged_batch_set(staged_batches, baseline, observed_field_union)

        batch_entries = []
        batch_hashes = []
        for staged_path, batch in staged_batches:
            assignment = batch["assignment"]
            batch_hash = _file_sha256(staged_path)
            batch_hashes.append(batch_hash)
            batch_entries.append(
                {
                    "batch_id": assignment["batch_id"],
                    "file_name": f"{assignment['batch_id']}.json",
                    "sha256": batch_hash,
                    "product_count": assignment["product_count"],
                    "source_order_start": assignment["source_order_start"],
                    "source_order_end": assignment["source_order_end"],
                }
            )
        set_manifest = {
            "schema_version": "1.0",
            "complete": True,
            "set_id": batch_set_sha256(baseline_sha256, batch_hashes),
            "generated_at": manifest.get("retrieved_at"),
            "baseline_sha256": baseline_sha256,
            "baseline_count": CANONICAL_PRODUCT_COUNT,
            "batch_count": CANONICAL_BATCH_COUNT,
            "field_union_sha256": field_union_sha256(observed_field_union),
            "batches": batch_entries,
        }
        set_manifest_target = output_dir / BATCH_SET_MANIFEST_NAME
        staged_manifest_path = _new_output_temp(set_manifest_target, "staged")
        temporary_paths.append(staged_manifest_path)
        _write_json_file(staged_manifest_path, set_manifest)
        staged_targets.append((staged_manifest_path, set_manifest_target))

        _publish_staged_batch_set(
            staged_targets, temporary_paths, retained_recovery_paths
        )

        return {
            "batch_count": len(batches),
            "batch_sizes": batch_sizes,
            "product_count": len(ordered_generated_ids),
            "baseline_count": len(baseline_ids),
            "field_review_keys_per_product": len(observed_field_union),
            "baseline_sha256": baseline_sha256,
            "output_dir": str(output_dir),
            "set_manifest": str(set_manifest_target),
            "set_id": set_manifest["set_id"],
        }
    finally:
        for temporary_path in reversed(temporary_paths):
            if temporary_path not in retained_recovery_paths:
                temporary_path.unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create deterministic full-catalog review assignments."
    )
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--field-schema", type=Path, default=DEFAULT_FIELD_SCHEMA)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--reviewer", default="agent-1")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = prepare_review_batches(
        baseline_path=args.baseline,
        manifest_path=args.manifest,
        field_schema_path=args.field_schema,
        output_dir=args.output_dir,
        reviewer=args.reviewer,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
