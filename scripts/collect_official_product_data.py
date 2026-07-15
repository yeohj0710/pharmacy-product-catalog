from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.official_data.client import DataGoClient, MissingServiceKey, PublicApiError
from lib.official_data.matching import choose_candidate
from lib.official_data.schema import make_match_record, utc_now, validate_official_record
from lib.official_data.sources import SOURCES, extract_items, merge_official_records, parse_source_record


TERMINAL_STATUSES = {"confirmed", "not_found", "not_applicable"}
DISCOVERY_SOURCES = tuple(source for source in SOURCES.values() if source.discovery)


def read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def candidate_view(record: dict[str, Any]) -> dict[str, Any]:
    provenance = record.get("provenance", {})
    identifiers = record.get("identifiers", {})
    return {
        "official_product_key": record["official_product_key"],
        "item_name": record["item_name"],
        "manufacturer": record.get("manufacturer", ""),
        "pack_unit": record.get("content", {}).get("pack_unit", ""),
        "dosage_form": record.get("classification", {}).get("dosage_form", ""),
        "item_seq": identifiers.get("item_seq", ""),
        "barcode": identifiers.get("barcode", ""),
        "udi_di": identifiers.get("udi_di", ""),
        "report_number": identifiers.get("report_number", ""),
        "source_domain": record.get("source_domain", ""),
        "source_dataset_id": provenance.get("source_dataset_id", ""),
        "source_url": provenance.get("source_url", ""),
    }


def product_summary(products: list[dict[str, Any]], matches: dict[str, dict[str, Any]], official: dict[str, dict[str, Any]], client: DataGoClient | None = None) -> dict[str, Any]:
    statuses = Counter(match.get("status", "pending") for match in matches.values())
    return {
        "generated_at": utc_now(),
        "product_count": len(products),
        "processed_count": len(matches),
        "remaining_count": max(0, len(products) - len(matches)),
        "match_status_counts": dict(sorted(statuses.items())),
        "official_product_count": len(official),
        "official_product_with_image_count": sum(bool(record.get("images")) for record in official.values()),
        "official_product_with_efficacy_count": sum(bool(record.get("content", {}).get("efficacy")) for record in official.values()),
        "official_product_with_dosage_count": sum(bool(record.get("content", {}).get("dosage")) for record in official.values()),
        "api_calls": client.api_calls if client else 0,
        "cache_hits": client.cache_hits if client else 0,
    }


def discover_candidates(client: DataGoClient, product: dict[str, Any], *, force: bool) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    errors: list[dict[str, str]] = []
    for source in DISCOVERY_SOURCES:
        query_parameter = source.query_parameters[0]
        try:
            payload = client.request_json(source, {query_parameter: product["name"]}, force=force)
            for item in extract_items(payload):
                try:
                    record = parse_source_record(source, item)
                    grouped[record["official_product_key"]].append(record)
                except ValueError as error:
                    errors.append({"source": source.key, "error": str(error)})
        except PublicApiError as error:
            errors.append({"source": source.key, "error": str(error)})
    return [merge_official_records(records) for records in grouped.values()], errors


def enrich_confirmed_drug(client: DataGoClient, record: dict[str, Any], *, force: bool) -> dict[str, Any]:
    if record.get("source_domain") != "drug":
        return record
    item_seq = record.get("identifiers", {}).get("item_seq", "")
    if not item_seq:
        return record
    matching: list[dict[str, Any]] = []
    for source_key in ("drug_detail", "drug_ingredients"):
        source = SOURCES[source_key]
        try:
            payload = client.request_json(source, {source.query_parameters[0]: item_seq}, force=force)
            details = [parse_source_record(source, item) for item in extract_items(payload)]
        except (PublicApiError, ValueError):
            continue
        matching.extend(
            detail for detail in details
            if detail["official_product_key"] == record["official_product_key"]
        )
    return merge_official_records([record, *matching]) if matching else record


def collect_batch(args: argparse.Namespace) -> int:
    products = read_json(args.input, [])
    if not isinstance(products, list) or not products:
        raise SystemExit(f"상품 입력 파일을 읽을 수 없습니다: {args.input}")
    matches_list = read_json(args.matches, [])
    official_list = read_json(args.official, [])
    matches = {record["catalog_product_id"]: record for record in matches_list}
    official = {record["official_product_key"]: record for record in official_list}
    client = DataGoClient(cache_dir=args.cache, requests_per_second=args.requests_per_second)

    if args.report_only:
        write_json_atomic(args.summary, product_summary(products, matches, official))
        print(json.dumps(product_summary(products, matches, official), ensure_ascii=False))
        return 0

    if args.check:
        try:
            payload = client.request_json(SOURCES["easy_drug"], {"itemName": "타이레놀정500밀리그람"}, force=args.force)
        except MissingServiceKey:
            summary = product_summary(products, matches, official, client)
            summary.update({"status": "blocked_missing_key", "required_environment_variable": "DATA_GO_KR_SERVICE_KEY", "outputs_untouched": True})
            write_json_atomic(args.summary, summary)
            print(json.dumps(summary, ensure_ascii=False))
            return 0
        summary = product_summary(products, matches, official, client)
        summary.update({"status": "ready", "sample_item_count": len(extract_items(payload))})
        write_json_atomic(args.summary, summary)
        print(json.dumps(summary, ensure_ascii=False))
        return 0

    if not client.service_key:
        summary = product_summary(products, matches, official, client)
        summary.update({"status": "blocked_missing_key", "required_environment_variable": "DATA_GO_KR_SERVICE_KEY", "outputs_untouched": True})
        write_json_atomic(args.summary, summary)
        print(json.dumps(summary, ensure_ascii=False))
        return 0

    start = max(0, args.start)
    stop = min(len(products), start + max(1, args.limit))
    batch_errors: list[dict[str, Any]] = []
    for index in range(start, stop):
        product = products[index]
        product_id = str(product.get("id") or product.get("document_id") or "")
        existing = matches.get(product_id)
        if existing and existing.get("status") in TERMINAL_STATUSES and not args.force:
            continue
        try:
            candidates, errors = discover_candidates(client, product, force=args.force)
            result = choose_candidate(product, [candidate_view(candidate) for candidate in candidates])
            chosen = next((candidate for candidate in candidates if candidate["official_product_key"] == result.official_product_key), None)
            if result.status == "confirmed" and chosen:
                chosen = enrich_confirmed_drug(client, chosen, force=args.force)
                validate_official_record(chosen)
                official[chosen["official_product_key"]] = chosen
            match = make_match_record(
                catalog_product_id=product_id,
                official_product_key=result.official_product_key,
                score=result.score,
                status=result.status,
                score_components=result.score_components,
                alternatives=result.alternatives,
            )
            match["source_errors"] = errors
            match["conflicts"] = result.conflicts
            match["source_order"] = index + 1
            matches[product_id] = match
        except MissingServiceKey:
            batch_errors.append({"catalog_product_id": product_id, "error": "blocked_missing_key"})
            break
        except Exception as error:  # keep the batch resumable and record the product-specific failure
            matches[product_id] = make_match_record(
                catalog_product_id=product_id,
                official_product_key="",
                score=0,
                status="error",
            )
            matches[product_id]["notes"] = f"{type(error).__name__}: {error}"
            batch_errors.append({"catalog_product_id": product_id, "error": type(error).__name__})
        write_json_atomic(args.matches, sorted(matches.values(), key=lambda row: row.get("source_order", 10**9)))
        write_json_atomic(args.official, sorted(official.values(), key=lambda row: row["official_product_key"]))

    summary = product_summary(products, matches, official, client)
    summary.update({"status": "batch_complete", "batch_start": start, "batch_stop": stop, "batch_errors": batch_errors})
    write_json_atomic(args.summary, summary)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="공식 공공데이터를 25개 단위로 수집하고 판매 SKU에 매칭합니다.")
    command.add_argument("--input", type=Path, default=ROOT / "data/enrichment-queue.json")
    command.add_argument("--official", type=Path, default=ROOT / "data/official-product-details.json")
    command.add_argument("--matches", type=Path, default=ROOT / "data/product-official-matches.json")
    command.add_argument("--summary", type=Path, default=ROOT / "data/official-data-summary.json")
    command.add_argument("--cache", type=Path, default=ROOT / "etc/official-source-cache")
    command.add_argument("--start", type=int, default=0)
    command.add_argument("--limit", type=int, default=25)
    command.add_argument("--requests-per-second", type=float, default=1.5)
    command.add_argument("--force", action="store_true")
    command.add_argument("--check", action="store_true")
    command.add_argument("--report-only", action="store_true")
    return command


if __name__ == "__main__":
    raise SystemExit(collect_batch(parser().parse_args()))
