from __future__ import annotations

import argparse
import csv
import html
import json
import re
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


SEARCH_URL = "https://search.danawa.com/dsearch.php?query="
USER_AGENT = "Mozilla/5.0 (compatible; pharmacy-product-catalog/1.0; +https://pharmacy-product-catalog.vercel.app)"
RIGHTS_STATUS = "source_preview"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


def normalize(value: Any) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(value or ""))).lower()
    text = re.sub(r"소비기한\s*\d+(?:[/.-]\d+)+", " ", text)
    text = re.sub(r"\b\d+\s*(?:개|세트|박스|병|통)\b", " ", text)
    return re.sub(r"[^0-9a-z가-힣]", "", text)


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def match_score(catalog_name: str, candidate_name: str) -> int:
    target, candidate = normalize(catalog_name), normalize(candidate_name)
    if not target or not candidate:
        return 0
    if target == candidate:
        return 100
    score = round(SequenceMatcher(None, target, candidate).ratio() * 100)
    if len(target) >= 5 and target in candidate and len(target) / len(candidate) >= 0.42:
        score = max(score, 96)
    catalog_tokens = [normalize(token) for token in re.findall(r"[0-9a-zA-Z가-힣]+", catalog_name)]
    distinctive = [token for token in catalog_tokens if len(token) >= 3 and token not in {"식물성", "플러스", "프리미엄"}]
    if distinctive and len(target) >= 6:
        covered = sum(len(token) for token in distinctive if token in candidate)
        total = sum(len(token) for token in distinctive)
        strong_terms = [token for token in distinctive if token in candidate]
        if total and covered / total >= 0.8 and (len(strong_terms) >= 2 or max(map(len, strong_terms), default=0) >= 6):
            score = max(score, 92)
    return score


def valid_image_url(value: str) -> str:
    url = html.unescape(value.strip())
    if url.startswith("//"):
        url = f"https:{url}"
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    if parsed.scheme != "https" or not parsed.hostname:
        return ""
    if any(marker in parsed.path.lower() for marker in ("noimg", "nodata", "spinner", "loader", "logo")):
        return ""
    return url


def parse_results(document: str, catalog_name: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    pattern = re.compile(
        r"<div\b[^>]*class=[\"'][^\"']*thumb_image[^\"']*[\"'][^>]*>"
        r"[\s\S]*?<img\b[^>]*?src=[\"']([^\"']+)[\"'][^>]*>"
        r"[\s\S]*?<p\b[^>]*class=[\"'][^\"']*prod_name[^\"']*[\"'][^>]*>"
        r"[\s\S]*?<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>([\s\S]*?)</a>",
        re.I,
    )
    for image_value, result_url, name_value in pattern.findall(document):
        image_url = valid_image_url(image_value)
        if not image_url:
            continue
        name = clean_text(name_value)
        output.append(
            {
                "candidate_name": name,
                "image_url": image_url,
                "result_url": html.unescape(result_url).strip(),
                "match_score": match_score(catalog_name, name),
            }
        )
    return output


class SearchClient:
    def __init__(self, delay: float, timeout: float = 20.0, retries: int = 3) -> None:
        self.delay = max(delay, 0.0)
        self.timeout = timeout
        self.retries = max(retries, 1)
        self.last_request_at = 0.0

    def search(self, query: str) -> tuple[str, str]:
        url = f"{SEARCH_URL}{quote(query)}"
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
        raise RuntimeError(f"상품 이미지 검색 실패: {type(last_error).__name__}") from last_error


def load_json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(dict.fromkeys([key for row in rows for key in row]))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def collect(args: argparse.Namespace) -> dict[str, Any]:
    products: list[dict[str, Any]] = load_json(args.input, [])
    missing = [row for row in products if not row.get("image_url")]
    selected = missing[args.start : args.start + args.limit if args.limit is not None else None]
    existing: list[dict[str, Any]] = load_json(args.matches, [])
    by_id = {str(row.get("catalog_product_id") or ""): row for row in existing}
    client = SearchClient(args.delay)
    processed = 0
    linked = 0

    def checkpoint() -> None:
        records = [by_id[key] for key in sorted(by_id)]
        write_json_atomic(args.matches, records)
        if args.materialize:
            write_json_atomic(args.input, products)
            write_csv(args.csv, products)

    for product in selected:
        product_id = str(product.get("id") or product.get("document_id") or "")
        if product_id in by_id and not args.force:
            continue
        name = str(product.get("name") or "").strip()
        record = {
            "catalog_product_id": product_id,
            "catalog_name": name,
            "status": "not_found",
            "candidate_name": "",
            "image_url": "",
            "source_url": "",
            "result_url": "",
            "match_score": 0,
            "checked_at": now_iso(),
            "error": "",
        }
        try:
            document, source_url = client.search(name)
            candidates = parse_results(document, name)
            if candidates:
                candidate = max(candidates, key=lambda row: int(row["match_score"]))
                record.update(candidate)
                record["source_url"] = source_url
                record["status"] = "review_required"
        except RuntimeError as exc:
            record["status"] = "error"
            record["error"] = str(exc)
        by_id[product_id] = record
        processed += 1
        if processed % args.checkpoint_every == 0:
            checkpoint()
            print(json.dumps({"processed": processed, "linked": linked}, ensure_ascii=False), flush=True)
    checkpoint()
    records = list(by_id.values())
    status_counts: dict[str, int] = {}
    for record in records:
        status = str(record.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    summary = {
        "generated_at": now_iso(),
        "missing_image_count": len(missing),
        "processed_in_run": processed,
        "linked_in_run": linked,
        "record_count": len(records),
        "status_counts": status_counts,
        "source": "다나와 상품 검색",
        "source_policy": "검색 결과의 상품 썸네일을 원격 미리보기로만 참조하며 원본 파일을 복제하지 않음",
    }
    write_json_atomic(args.summary, summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="약학정보원 이미지가 없는 상품의 외부 카탈로그 미리보기를 조사합니다.")
    parser.add_argument("--input", type=Path, default=Path("data/enrichment-queue.json"))
    parser.add_argument("--csv", type=Path, default=Path("data/enrichment-queue.csv"))
    parser.add_argument("--matches", type=Path, default=Path("data/secondary-image-matches.json"))
    parser.add_argument("--summary", type=Path, default=Path("data/secondary-image-summary.json"))
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--delay", type=float, default=0.6)
    parser.add_argument("--confirm-score", type=int, default=92)
    parser.add_argument("--checkpoint-every", type=int, default=10)
    parser.add_argument("--materialize", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(collect(parse_args()), ensure_ascii=False, indent=2))
