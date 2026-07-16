from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.collect_secondary_images import match_score, normalize, now_iso, valid_image_url, write_json_atomic


SEARCH_URL = "https://search.naver.com/search.naver?where=image&sm=tab_jum&query="
USER_AGENT = "Mozilla/5.0 (compatible; pharmacy-product-catalog/1.0; +https://pharmacy-product-catalog.vercel.app)"


def parse_image_results(document: str, catalog_name: str) -> list[dict[str, Any]]:
    marker = '[{"type":"image"'
    start = document.find(marker)
    if start < 0:
        return []
    try:
        payload, _ = json.JSONDecoder().raw_decode(document[start:])
    except json.JSONDecodeError:
        return []
    output: list[dict[str, Any]] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        image_url = valid_image_url(str(row.get("viewerThumb") or row.get("thumb") or ""))
        result_url = str(row.get("link") or "").strip()
        title = str(row.get("title") or "").strip()
        if not image_url or not result_url or not title:
            continue
        output.append(
            {
                "candidate_name": title,
                "image_url": image_url,
                "result_url": result_url,
                "match_score": match_score(catalog_name, title),
                "rank": int(row.get("rank") or len(output) + 1),
                "source_name": str(row.get("source") or ""),
            }
        )
    return output


def safe_candidate(catalog_name: str, candidate: dict[str, Any]) -> bool:
    target = normalize(catalog_name)
    title = normalize(candidate.get("candidate_name"))
    return len(target) >= 5 and target in title


def automatic_candidate_status(candidate: dict[str, Any]) -> str:
    return "review_required" if candidate.get("image_url") else "not_found"


class NaverImageClient:
    def __init__(self, delay: float, timeout: float = 20.0, retries: int = 3) -> None:
        self.delay = max(delay, 0.0)
        self.timeout = timeout
        self.retries = max(retries, 1)
        self.last_request_at = 0.0

    def search(self, query: str) -> tuple[str, str]:
        url = f"{SEARCH_URL}{quote(f'{query} 제품')}"
        elapsed = time.monotonic() - self.last_request_at
        if self.last_request_at and elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                self.last_request_at = time.monotonic()
                request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*"})
                with urlopen(request, timeout=self.timeout) as response:
                    return response.read().decode("utf-8", errors="replace"), url
            except (HTTPError, URLError, TimeoutError) as exc:
                last_error = exc
                if attempt + 1 < self.retries:
                    time.sleep(2**attempt)
        raise RuntimeError(f"네이버 이미지 검색 실패: {type(last_error).__name__}") from last_error


def collect(args: argparse.Namespace) -> dict[str, Any]:
    products = json.loads(args.input.read_text(encoding="utf-8"))
    missing = [row for row in products if not row.get("image_url")]
    selected = missing[args.start : args.start + args.limit if args.limit is not None else None]
    existing = json.loads(args.matches.read_text(encoding="utf-8")) if args.matches.exists() else []
    by_id = {str(row.get("catalog_product_id") or ""): row for row in existing}
    client = NaverImageClient(args.delay)
    processed = 0

    def checkpoint() -> None:
        write_json_atomic(args.matches, [by_id[key] for key in sorted(by_id)])

    for product in selected:
        product_id = str(product.get("id") or product.get("document_id") or "")
        if product_id in by_id and not args.force:
            continue
        name = str(product.get("name") or "").strip()
        record: dict[str, Any] = {
            "catalog_product_id": product_id,
            "catalog_name": name,
            "status": "not_found",
            "candidate_name": "",
            "image_url": "",
            "source_url": "",
            "result_url": "",
            "match_score": 0,
            "rank": 0,
            "source_name": "",
            "checked_at": now_iso(),
            "error": "",
        }
        try:
            document, source_url = client.search(name)
            candidates = parse_image_results(document, name)
            record["source_url"] = source_url
            if candidates:
                candidate = max(candidates, key=lambda row: (safe_candidate(name, row), int(row["match_score"]), -int(row["rank"])))
                record.update(candidate)
                record["status"] = automatic_candidate_status(candidate)
        except RuntimeError as exc:
            record["status"] = "error"
            record["error"] = str(exc)
        by_id[product_id] = record
        processed += 1
        if processed % args.checkpoint_every == 0:
            checkpoint()
            print(json.dumps({"processed": processed, "status": record["status"]}, ensure_ascii=False), flush=True)
    checkpoint()
    records = list(by_id.values())
    summary = {
        "generated_at": now_iso(),
        "missing_image_count": len(missing),
        "processed_in_run": processed,
        "record_count": len(records),
        "status_counts": dict(Counter(str(row.get("status") or "unknown") for row in records)),
        "source": "네이버 이미지 검색",
        "source_policy": "검색 결과 썸네일을 원격 미리보기로만 참조하고 원문 링크를 함께 저장함",
    }
    write_json_atomic(args.summary, summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="이미지가 없는 상품을 네이버 이미지 검색에서 보조 조사합니다.")
    parser.add_argument("--input", type=Path, default=Path("data/enrichment-queue.json"))
    parser.add_argument("--matches", type=Path, default=Path("data/naver-image-matches.json"))
    parser.add_argument("--summary", type=Path, default=Path("data/naver-image-summary.json"))
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--delay", type=float, default=0.6)
    parser.add_argument("--checkpoint-every", type=int, default=10)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(collect(parse_args()), ensure_ascii=False, indent=2))
