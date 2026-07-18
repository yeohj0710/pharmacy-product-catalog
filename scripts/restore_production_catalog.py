from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
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
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    download_path = output.with_name(output.name + ".download")
    manifest_download_path = manifest_path.with_name(manifest_path.name + ".download")

    request = Request(url, headers={"User-Agent": "pharmacy-catalog-baseline-restorer/1.0"})
    try:
        with urlopen(request) as response, download_path.open("wb") as destination:
            status = response.getcode()
            etag = response.headers.get("ETag")
            last_modified = response.headers.get("Last-Modified")
            shutil.copyfileobj(response, destination)

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

        payload_bytes = download_path.read_bytes()
        manifest = {
            "url": url,
            "http_status": status,
            "etag": etag,
            "last_modified": last_modified,
            "byte_sha256": hashlib.sha256(payload_bytes).hexdigest(),
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
        download_path.replace(output)
        manifest_download_path.replace(manifest_path)
        return manifest
    finally:
        download_path.unlink(missing_ok=True)
        manifest_download_path.unlink(missing_ok=True)


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
