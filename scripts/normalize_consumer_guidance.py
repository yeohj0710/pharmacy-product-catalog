from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ALLOWED_KEYS = {
    "summary",
    "efficacy",
    "guide",
    "dosage",
    "warning",
    "precautions",
    "interactions",
    "side_effects",
    "storage",
}


def normalize_product(product: dict[str, Any]) -> bool:
    guidance = product.get("official_consumer_guidance")
    if not isinstance(guidance, dict):
        return False

    source_url = guidance.get("source_url")
    full_text = guidance.get("full_text")
    if source_url or full_text:
        additional = product.setdefault("official_additional_data", {})
        health_raw = additional.setdefault("health_kr_raw", {})
        auxiliary = health_raw.setdefault("auxiliary_pages", {})
        medication = auxiliary.setdefault("medication", {})
        if source_url and not medication.get("source_url"):
            medication["source_url"] = source_url
        if full_text and not medication.get("text"):
            medication["text"] = full_text

    normalized = {
        key: value
        for key, value in guidance.items()
        if key in ALLOWED_KEYS and isinstance(value, str) and value.strip()
    }
    if normalized == guidance:
        return False
    product["official_consumer_guidance"] = normalized
    return True


def normalize_file(path: Path) -> int:
    products = json.loads(path.read_text(encoding="utf-8"))
    changed = sum(normalize_product(product) for product in products)
    path.write_text(json.dumps(products, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed


def main() -> int:
    paths = [ROOT / "data/enrichment-queue.json", ROOT / "public/data/enrichment-queue.json"]
    for path in paths:
        if path.exists():
            print(f"{path.relative_to(ROOT)}: {normalize_file(path)}개 정리")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
