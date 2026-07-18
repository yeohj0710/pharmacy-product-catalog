from __future__ import annotations

import argparse
import hashlib
import io
import json
import textwrap
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = "Mozilla/5.0 (compatible; pharmacy-product-catalog-image-review/1.0)"
SEARCH_HOSTS = {
    "search.naver.com",
    "search.pstatic.net",
    "www.google.com",
    "google.com",
    "www.bing.com",
    "search.daum.net",
    "search.danawa.com",
}
PLACEHOLDER_MARKERS = ("noimg", "no_image", "placeholder", "19_limited", "default-image")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def valid_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def source_page_is_product_page(value: str) -> bool:
    if not valid_http_url(value):
        return False
    return (urlparse(value).hostname or "").lower() not in SEARCH_HOSTS


def image_url_is_allowed(value: str) -> bool:
    if not valid_http_url(value) or urlparse(value).scheme != "https":
        return False
    lowered = value.lower()
    hostname = (urlparse(value).hostname or "").lower()
    return hostname not in SEARCH_HOSTS and not any(marker in lowered for marker in PLACEHOLDER_MARKERS)


def fetch_source_page(session: requests.Session, url: str) -> dict[str, Any]:
    if not source_page_is_product_page(url):
        return {"status": 0, "final_url": "", "content_type": "", "error": "not_a_product_page"}
    try:
        response = session.get(url, timeout=25, allow_redirects=True)
        result = {
            "status": response.status_code,
            "final_url": response.url,
            "content_type": response.headers.get("content-type", ""),
            "error": "",
        }
        if not source_page_is_product_page(response.url):
            result["error"] = "redirected_to_non_product_page"
        return result
    except requests.RequestException as exc:
        return {"status": 0, "final_url": "", "content_type": "", "error": str(exc)}


def fetch_image(session: requests.Session, url: str) -> tuple[dict[str, Any], Image.Image | None]:
    result: dict[str, Any] = {
        "status": 0,
        "final_url": "",
        "content_type": "",
        "byte_count": 0,
        "width": 0,
        "height": 0,
        "format": "",
        "sha256": "",
        "error": "",
    }
    if not image_url_is_allowed(url):
        result["error"] = "disallowed_or_invalid_image_url"
        return result, None
    try:
        response = session.get(url, timeout=30, allow_redirects=True)
        result.update(
            status=response.status_code,
            final_url=response.url,
            content_type=response.headers.get("content-type", ""),
            byte_count=len(response.content),
        )
        if not image_url_is_allowed(response.url):
            result["error"] = "redirected_to_disallowed_image_url"
            return result, None
        if response.status_code < 200 or response.status_code >= 400:
            result["error"] = f"http_{response.status_code}"
            return result, None
        if str(result["content_type"]).lower().startswith("text/html"):
            result["error"] = "non_image_content_type"
            return result, None
        image = Image.open(io.BytesIO(response.content))
        image.load()
        result.update(
            width=image.width,
            height=image.height,
            format=image.format or "",
            sha256=hashlib.sha256(response.content).hexdigest(),
        )
        return result, image.convert("RGB")
    except (requests.RequestException, OSError, ValueError) as exc:
        result["error"] = str(exc)
        return result, None


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        Path("C:/Windows/Fonts/Pretendard-Bold.otf" if bold else "C:/Windows/Fonts/Pretendard-Regular.otf"),
        Path("C:/Windows/Fonts/malgunbd.ttf" if bold else "C:/Windows/Fonts/malgun.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def wrap(value: str, width: int, lines: int) -> list[str]:
    return textwrap.wrap(value, width=width, break_long_words=True, break_on_hyphens=False)[:lines]


def build_sheets(records: list[dict[str, Any]], images: dict[str, Image.Image], directory: Path) -> int:
    candidates = [row for row in records if row["image_check"]["width"] > 0]
    directory.mkdir(parents=True, exist_ok=True)
    card_w, card_h, cols, rows = 640, 430, 3, 3
    title_font = load_font(22, True)
    body_font = load_font(17)
    small_font = load_font(14)
    for offset in range(0, len(candidates), cols * rows):
        sheet = Image.new("RGB", (card_w * cols, card_h * rows), "white")
        draw = ImageDraw.Draw(sheet)
        for card_index, record in enumerate(candidates[offset:offset + cols * rows]):
            x = (card_index % cols) * card_w
            y = (card_index // cols) * card_h
            draw.rectangle((x, y, x + card_w - 1, y + card_h - 1), outline="#cbd5e1", width=2)
            draw.text((x + 14, y + 12), f"{record['catalog_product_id']}  {record['catalog_name']}", font=title_font, fill="#111827")
            draw.text((x + 14, y + 44), f"규격 {record['catalog_capacity']} · {record['catalog_category']}", font=body_font, fill="#475569")
            image = images.get(record["catalog_product_id"])
            if image:
                fitted = ImageOps.contain(image, (250, 250))
                sheet.paste(fitted, (x + 14 + (250 - fitted.width) // 2, y + 82 + (250 - fitted.height) // 2))
            cy = y + 86
            for line in wrap(record["candidate_name"], 30, 5):
                draw.text((x + 282, cy), line, font=body_font, fill="#1f2937")
                cy += 24
            evidence = " / ".join(record.get("match_evidence") or [])
            cy += 6
            for line in wrap(evidence, 34, 6):
                draw.text((x + 282, cy), line, font=small_font, fill="#475569")
                cy += 20
            check = record["image_check"]
            draw.text((x + 14, y + 350), f"{check['width']}×{check['height']} · {record['source_tier']} · score {record['match_score']}", font=small_font, fill="#334155")
            draw.text((x + 14, y + 378), urlparse(record["source_url"]).netloc, font=small_font, fill="#64748b")
        sheet.save(directory / f"sheet-{offset // (cols * rows) + 1:02d}.jpg", quality=94)
    return (len(candidates) + cols * rows - 1) // (cols * rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--sheets", type=Path, required=True)
    args = parser.parse_args()

    queue = read_json(args.queue)
    results = read_json(args.results)
    if not isinstance(queue, list) or not isinstance(results, list):
        raise ValueError("queue와 results의 최상위 값은 배열이어야 합니다.")
    queue_ids = [str(row.get("catalog_product_id") or "") for row in queue]
    result_ids = [str(row.get("catalog_product_id") or "") for row in results]
    if result_ids != queue_ids or len(result_ids) != len(set(result_ids)):
        raise ValueError("results의 ID·순서가 queue와 다르거나 중복되었습니다.")

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    audited: list[dict[str, Any]] = []
    images: dict[str, Image.Image] = {}
    for queued, result in zip(queue, results, strict=True):
        status = str(result.get("status") or "")
        product_id = str(result.get("catalog_product_id") or "")
        source_url = str(result.get("result_url") or result.get("source_url") or "")
        image_url = str(result.get("image_url") or "")
        source_check = fetch_source_page(session, source_url) if status == "confirmed" else {"status": 0, "final_url": "", "content_type": "", "error": ""}
        image_check, image = fetch_image(session, image_url) if status == "confirmed" else ({"status": 0, "final_url": "", "content_type": "", "byte_count": 0, "width": 0, "height": 0, "format": "", "sha256": "", "error": ""}, None)
        if image:
            images[product_id] = image
        failures: list[str] = []
        if status not in {"confirmed", "review_required", "not_found"}:
            failures.append("invalid_status")
        if status == "confirmed":
            if not source_page_is_product_page(source_url):
                failures.append("source_is_not_product_page")
            if (source_check["status"] < 200 or source_check["status"] >= 400) and source_check["status"] not in {401, 403, 429}:
                failures.append("source_page_unreachable")
            if image_check["error"]:
                failures.append("invalid_image_response")
            if image_check["width"] < 150 or image_check["height"] < 150:
                failures.append("image_too_small")
            if not result.get("candidate_name") or not result.get("match_evidence"):
                failures.append("missing_match_evidence")
        elif image_url or source_url:
            failures.append("unconfirmed_row_has_candidate_urls")
        audited.append(
            {
                **result,
                "catalog_name": str(queued.get("catalog_name") or ""),
                "catalog_capacity": str(queued.get("catalog_capacity") or ""),
                "catalog_category": str(queued.get("catalog_category") or ""),
                "source_url": source_url,
                "source_check": source_check,
                "image_check": image_check,
                "automated_failures": failures,
                "automated_valid": not failures,
            }
        )

    confirmed_hashes: dict[str, list[str]] = {}
    for row in audited:
        digest = str(row["image_check"].get("sha256") or "")
        if digest:
            confirmed_hashes.setdefault(digest, []).append(row["catalog_product_id"])
    duplicate_groups = [ids for ids in confirmed_hashes.values() if len(ids) > 1]
    duplicate_ids = {product_id for ids in duplicate_groups for product_id in ids}
    for row in audited:
        if row["catalog_product_id"] in duplicate_ids:
            row["automated_failures"].append("duplicate_image_content_in_batch")
            row["automated_valid"] = False

    sheet_count = build_sheets(audited, images, args.sheets)
    summary = {
        "queue_count": len(queue),
        "result_count": len(results),
        "confirmed_count": sum(row.get("status") == "confirmed" for row in audited),
        "review_required_count": sum(row.get("status") == "review_required" for row in audited),
        "not_found_count": sum(row.get("status") == "not_found" for row in audited),
        "automated_valid_count": sum(row.get("status") == "confirmed" and row["automated_valid"] for row in audited),
        "automated_failure_count": sum(not row["automated_valid"] for row in audited),
        "duplicate_image_groups": duplicate_groups,
        "sheet_count": sheet_count,
    }
    write_json(args.audit, {"summary": summary, "records": audited})
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if summary["automated_failure_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
