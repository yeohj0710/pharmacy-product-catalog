from __future__ import annotations

import glob
import io
import json
import textwrap
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "etc" / "image-review"
CACHE = OUT / "cache"
SHEETS = OUT / "sheets"
CARD_W, CARD_H = 560, 360
COLS, ROWS = 3, 3


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        Path("C:/Windows/Fonts/Pretendard-Bold.otf" if bold else "C:/Windows/Fonts/Pretendard-Regular.otf"),
        Path("C:/Windows/Fonts/malgunbd.ttf" if bold else "C:/Windows/Fonts/malgun.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def candidate_rank(row: dict[str, Any]) -> tuple[int, int, int, int]:
    url = str(row.get("image_url") or "")
    return (
        int(row.get("manual_verified") is True),
        int(row.get("status") == "confirmed"),
        int(bool(url)),
        int(row.get("match_score") or 0),
    )


def load_candidates() -> dict[str, dict[str, Any]]:
    patterns = [
        "data/secondary-image-part-[123].json",
        "data/naver-image-part-[123].json",
        "data/image-manual-review-part-[123].json",
        "etc/secondary-current-part-[123].json",
        "etc/naver-current-part-[123].json",
    ]
    chosen: dict[str, dict[str, Any]] = {}
    for pattern in patterns:
        for filename in glob.glob(str(ROOT / pattern)):
            payload = json.loads(Path(filename).read_text(encoding="utf-8"))
            for row in payload:
                product_id = str(row.get("catalog_product_id") or "")
                url = str(row.get("image_url") or "")
                if not product_id or not url or not url.startswith("https://"):
                    continue
                enriched = {**row, "candidate_file": str(Path(filename).relative_to(ROOT)).replace("\\", "/")}
                if product_id not in chosen or candidate_rank(enriched) > candidate_rank(chosen[product_id]):
                    chosen[product_id] = enriched
    return chosen


def fetch_image(product_id: str, url: str) -> Image.Image | None:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{product_id}.jpg"
    if path.exists():
        try:
            return Image.open(path).convert("RGB")
        except OSError:
            pass
    try:
        response = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        image = Image.open(io.BytesIO(response.content)).convert("RGB")
        image.thumbnail((900, 900))
        image.save(path, "JPEG", quality=90)
        return image
    except Exception:
        return None


def wrapped(text: str, width: int) -> list[str]:
    return textwrap.wrap(text, width=width, break_long_words=True, break_on_hyphens=False) or [""]


def main() -> int:
    products = json.loads((ROOT / "data/enrichment-queue.json").read_text(encoding="utf-8"))
    candidates = load_candidates()
    queue = []
    for product in products:
        if product.get("image_url"):
            continue
        candidate = candidates.get(str(product["id"]))
        if candidate:
            queue.append({"product": product, "candidate": candidate})
    SHEETS.mkdir(parents=True, exist_ok=True)
    title_font, body_font, small_font = font(24, True), font(18), font(14)
    for sheet_index in range(0, len(queue), COLS * ROWS):
        page = Image.new("RGB", (CARD_W * COLS, CARD_H * ROWS), "white")
        draw = ImageDraw.Draw(page)
        for offset, entry in enumerate(queue[sheet_index:sheet_index + COLS * ROWS]):
            product, candidate = entry["product"], entry["candidate"]
            x, y = (offset % COLS) * CARD_W, (offset // COLS) * CARD_H
            draw.rectangle((x, y, x + CARD_W - 1, y + CARD_H - 1), outline="#c8d1dc", width=2)
            draw.text((x + 14, y + 12), f"{sheet_index + offset + 1:03d}  {product['name']}", font=title_font, fill="#111827")
            draw.text((x + 14, y + 48), f"규격 {product['capacity']} · {product['category']}", font=body_font, fill="#475569")
            image = fetch_image(str(product["id"]), str(candidate.get("image_url") or ""))
            image_box = (x + 14, y + 82, x + 234, y + 302)
            draw.rectangle(image_box, fill="#f3f4f6")
            if image:
                fitted = ImageOps.contain(image, (220, 220))
                page.paste(fitted, (x + 14 + (220 - fitted.width) // 2, y + 82 + (220 - fitted.height) // 2))
            else:
                draw.text((x + 60, y + 180), "이미지 로드 실패", font=body_font, fill="#9ca3af")
            cy = y + 88
            for line in wrapped(str(candidate.get("candidate_name") or "제목 없음"), 25)[:6]:
                draw.text((x + 250, cy), line, font=body_font, fill="#1f2937")
                cy += 26
            draw.text((x + 250, y + 252), f"점수 {candidate.get('match_score', 0)} · {candidate.get('status', '')}", font=small_font, fill="#64748b")
            draw.text((x + 14, y + 320), f"ID {product['id']}", font=small_font, fill="#64748b")
        page.save(SHEETS / f"sheet-{sheet_index // (COLS * ROWS) + 1:02d}.jpg", quality=92)
    (OUT / "review-index.json").write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"review_count": len(queue), "sheet_count": (len(queue) + 8) // 9}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
