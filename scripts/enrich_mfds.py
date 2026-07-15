from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from rapidfuzz.fuzz import ratio


ENDPOINT = "https://apis.data.go.kr/1471000/DrbEasyDrugInfoService/getDrbEasyDrugList"
SOURCE_PAGE = "https://www.data.go.kr/data/15075057/openapi.do"


def normalize(value: str) -> str:
    value = re.sub(r"\([^)]*\)", "", value.lower())
    return re.sub(r"[^0-9a-z가-힣]", "", value)


def search_name(product: dict[str, Any]) -> str:
    value = product.get("name", "")
    value = re.sub(r"\s+\d+(?:\.\d+)?\s*(?:mg|g|ml|l|정|캡슐|포|병|개|매|ea|t|c)$", "", value, flags=re.I)
    return value.strip()


def items_from_response(payload: dict[str, Any]) -> list[dict[str, Any]]:
    body = payload.get("body") or payload.get("response", {}).get("body") or {}
    items = body.get("items") or []
    if isinstance(items, dict):
        items = items.get("item") or []
    if isinstance(items, dict):
        items = [items]
    return items


def best_match(query: str, items: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, int]:
    query_key = normalize(query)
    scored = [(item, ratio(query_key, normalize(str(item.get("itemName", ""))))) for item in items]
    if not scored:
        return None, 0
    item, score = max(scored, key=lambda pair: pair[1])
    return (item, int(score)) if score >= 78 else (None, int(score))


def main() -> int:
    parser = argparse.ArgumentParser(description="식약처 e약은요 공개 데이터로 제품명과 낱알이미지를 검증합니다.")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--delay", type=float, default=0.18)
    args = parser.parse_args()

    service_key = os.environ.get("DATA_GO_KR_SERVICE_KEY")
    if not service_key:
        print("DATA_GO_KR_SERVICE_KEY 환경 변수가 필요합니다.", file=sys.stderr)
        print(f"활용신청: {SOURCE_PAGE}", file=sys.stderr)
        return 2

    products = json.loads(args.input.read_text(encoding="utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    matched = 0

    for index, product in enumerate(products, start=1):
        query = search_name(product)
        try:
            response = session.get(
                ENDPOINT,
                params={
                    "serviceKey": service_key,
                    "itemName": query,
                    "pageNo": 1,
                    "numOfRows": 20,
                    "type": "json",
                },
                timeout=20,
            )
            response.raise_for_status()
            item, score = best_match(query, items_from_response(response.json()))
        except (requests.RequestException, ValueError) as exc:
            product["official_lookup_error"] = str(exc)
            item, score = None, 0

        product["official_match_score"] = score
        if item:
            product["official_item_name"] = item.get("itemName", "")
            product["official_manufacturer"] = item.get("entpName", "")
            product["official_item_seq"] = item.get("itemSeq", "")
            product["image_url"] = item.get("itemImage", "") or ""
            product["image_source_url"] = SOURCE_PAGE
            product["image_rights_status"] = "식약처 공공데이터·이용허락범위 제한 없음"
            product["verification_status"] = "식약처 제품명 연결"
            matched += 1

        if index % 20 == 0 or index == len(products):
            args.output.write_text(json.dumps(products, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"{index}/{len(products)} · 공식 연결 {matched}개", flush=True)
        time.sleep(args.delay)

    print(f"완료: {matched}/{len(products)}개 제품 연결")
    return 0


if __name__ == "__main__":
    sys.exit(main())
