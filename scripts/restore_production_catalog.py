from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.catalog_review.baseline import canonical_json_sha256, validate_baseline


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URL = "https://pharmacy-product-catalog.vercel.app/data/enrichment-queue.json"
DEFAULT_OUTPUT = ROOT / "data" / "enrichment-queue.json"
DEFAULT_MANIFEST = ROOT / "etc" / "catalog-verification" / "baseline-manifest.json"
DEFAULT_SCHEMA = ROOT / "schemas" / "catalog-canonical-fields.json"
DEFAULT_NETWORK_TIMEOUT_SECONDS = 30
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
DOWNLOAD_CHUNK_BYTES = 1024 * 1024


def _new_sibling_temp(target: Path, role: str) -> Path:
    """Create a unique temporary file beside a target for same-volume replacement."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=f".{role}",
        dir=target.parent,
    )
    os.close(descriptor)
    return Path(name)


def _paths_alias(first: Path, second: Path) -> bool:
    first = Path(first)
    second = Path(second)
    first_key = os.path.normcase(str(first.resolve(strict=False)))
    second_key = os.path.normcase(str(second.resolve(strict=False)))
    if first_key == second_key:
        return True
    return first.exists() and second.exists() and os.path.samefile(first, second)


def _assert_distinct_paths(**named_paths: Path) -> None:
    items = list(named_paths.items())
    for index, (first_name, first_path) in enumerate(items):
        for second_name, second_path in items[index + 1 :]:
            if _paths_alias(first_path, second_path):
                raise ValueError(
                    f"path collision: {first_name} and {second_name} resolve to the same file"
                )


def _tracked_sibling_temp(
    target: Path,
    role: str,
    named_paths: dict[str, Path],
    temporary_paths: list[Path],
) -> Path:
    candidate = _new_sibling_temp(target, role)
    try:
        _assert_distinct_paths(**named_paths, **{role: candidate})
    except Exception:
        if not any(_paths_alias(candidate, protected) for protected in named_paths.values()):
            candidate.unlink(missing_ok=True)
        raise
    named_paths[role] = candidate
    temporary_paths.append(candidate)
    return candidate


def restore_catalog(
    *,
    url: str = DEFAULT_URL,
    output: Path = DEFAULT_OUTPUT,
    manifest_path: Path = DEFAULT_MANIFEST,
    schema_path: Path = DEFAULT_SCHEMA,
    expected_count: int = 776,
) -> dict:
    """Download, validate, and atomically restore the production baseline."""
    output = Path(output)
    manifest_path = Path(manifest_path)
    schema_path = Path(schema_path)
    named_paths = {"output": output, "manifest": manifest_path, "schema": schema_path}
    _assert_distinct_paths(**named_paths)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_paths: list[Path] = []
    try:
        download_path = _tracked_sibling_temp(
            output,
            "catalog_stage",
            named_paths,
            temporary_paths,
        )
        manifest_download_path = _tracked_sibling_temp(
            manifest_path,
            "manifest_stage",
            named_paths,
            temporary_paths,
        )

        request = Request(url, headers={"User-Agent": "pharmacy-catalog-baseline-restorer/1.0"})
        byte_hasher = hashlib.sha256()
        with urlopen(request, timeout=DEFAULT_NETWORK_TIMEOUT_SECONDS) as response, download_path.open(
            "wb"
        ) as destination:
            status = response.getcode()
            etag = response.headers.get("ETag")
            last_modified = response.headers.get("Last-Modified")
            content_length = response.headers.get("Content-Length")
            if content_length is not None:
                try:
                    declared_size = int(content_length)
                except ValueError as error:
                    raise ValueError("invalid Content-Length header") from error
                if declared_size < 0:
                    raise ValueError("invalid Content-Length header")
                if declared_size > MAX_DOWNLOAD_BYTES:
                    raise ValueError(
                        f"maximum download size is {MAX_DOWNLOAD_BYTES} bytes; "
                        f"Content-Length declared {declared_size}"
                    )

            downloaded_size = 0
            while True:
                chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                downloaded_size += len(chunk)
                if downloaded_size > MAX_DOWNLOAD_BYTES:
                    raise ValueError(
                        f"maximum download size is {MAX_DOWNLOAD_BYTES} bytes; "
                        f"received more than the limit"
                    )
                destination.write(chunk)
                byte_hasher.update(chunk)

        rows = json.loads(download_path.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise ValueError("catalog payload must be a JSON array")

        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        validation = validate_baseline(
            rows,
            expected_count=expected_count,
            expected_field_union=schema["field_union"],
        )
        accepted_counts = set(schema.get("accepted_row_field_counts", []))
        observed_counts = set(validation["row_field_count_distribution"])
        unexpected_counts = sorted(observed_counts - accepted_counts) if accepted_counts else []
        if unexpected_counts:
            raise ValueError(f"unexpected row field counts: {unexpected_counts}")

        manifest = {
            "url": url,
            "http_status": status,
            "etag": etag,
            "last_modified": last_modified,
            "byte_sha256": byte_hasher.hexdigest(),
            "canonical_json_sha256": canonical_json_sha256(rows),
            "count": validation["count"],
            "field_union": validation["field_union"],
            "row_field_count_distribution": {
                str(field_count): row_count
                for field_count, row_count in validation["row_field_count_distribution"].items()
            },
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }

        manifest_download_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        output_existed = output.exists()
        manifest_existed = manifest_path.exists()
        output_backup_path = None
        manifest_backup_path = None
        if output_existed:
            output_backup_path = _tracked_sibling_temp(
                output,
                "catalog_backup",
                named_paths,
                temporary_paths,
            )
            shutil.copy2(output, output_backup_path)
        if manifest_existed:
            manifest_backup_path = _tracked_sibling_temp(
                manifest_path,
                "manifest_backup",
                named_paths,
                temporary_paths,
            )
            shutil.copy2(manifest_path, manifest_backup_path)

        output_replaced = False
        manifest_replace_attempted = False
        try:
            download_path.replace(output)
            output_replaced = True
            manifest_replace_attempted = True
            manifest_download_path.replace(manifest_path)
        except Exception:
            if output_replaced:
                if output_existed:
                    assert output_backup_path is not None
                    output_backup_path.replace(output)
                else:
                    output.unlink(missing_ok=True)
            if manifest_replace_attempted:
                if manifest_existed:
                    assert manifest_backup_path is not None
                    manifest_backup_path.replace(manifest_path)
                else:
                    manifest_path.unlink(missing_ok=True)
            raise
        return manifest
    finally:
        for temporary_path in reversed(temporary_paths):
            temporary_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore the validated production catalog baseline.")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--expected-count", type=int, default=776)
    args = parser.parse_args()

    manifest = restore_catalog(
        url=args.url,
        output=args.output,
        manifest_path=args.manifest,
        schema_path=args.schema,
        expected_count=args.expected_count,
    )
    print(f"Restored {manifest['count']} validated catalog rows to {args.output}")
    print(f"Wrote verification manifest to {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
