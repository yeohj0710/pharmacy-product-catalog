from __future__ import annotations

import argparse
import json
import os
import random
import re
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, unquote
from urllib.request import Request, urlopen


SERVICE_KEY_ENV = "DATA_GO_KR_SERVICE_KEY"
RIGHTS_OPEN = "공공데이터포털 이용허락범위 제한 없음"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


def normalize(value: Any) -> str:
    text = re.sub(r"\([^)]*\)", "", str(value or "").lower())
    return re.sub(r"[^0-9a-z가-힣]", "", text)


def search_name(product: dict[str, Any]) -> str:
    text = str(product.get("name") or "").strip()
    return re.sub(
        r"\s+\d+(?:\.\d+)?\s*(?:mg|g|kg|ml|l|정|캡슐|포|병|개|매|ea|t|c)$",
        "",
        text,
        flags=re.I,
    ).strip()


def first_value(item: dict[str, Any], names: Iterable[str]) -> str:
    lowered = {str(key).lower(): value for key, value in item.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def nested_value(payload: Any, path: tuple[str, ...]) -> Any:
    current = payload
    for part in path:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def items_from_payload(payload: Any) -> list[dict[str, Any]]:
    paths = (
        ("response", "body", "items", "item"),
        ("response", "body", "items"),
        ("body", "items", "item"),
        ("body", "items"),
        ("items", "item"),
        ("items",),
        ("data",),
    )
    for path in paths:
        value = nested_value(payload, path)
        if isinstance(value, dict) and "item" in value:
            value = value["item"]
        if isinstance(value, dict):
            return [value]
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


@dataclass
class Candidate:
    source_type: str
    source_dataset_url: str
    source_url: str
    official_item_name: str
    official_manufacturer: str
    official_item_seq: str
    official_capacity: str
    match_score: int = 0
    match_status: str = "rejected"
    exact_name: bool = False
    exact_capacity: bool = False
    image_kind: str = ""
    image_url: str = ""
    image_source_url: str = ""
    image_rights_status: str = ""


class HttpClient:
    def __init__(self, service_key: str, delay: float, timeout: float, retries: int) -> None:
        self.service_key = unquote(service_key.strip())
        self.delay = max(0.0, delay)
        self.timeout = timeout
        self.retries = max(1, retries)
        self.call_count = 0

    def get_json(self, endpoint: str, params: dict[str, Any], key_name: str) -> dict[str, Any]:
        query = dict(params)
        query[key_name] = self.service_key
        url = f"{endpoint}?{urlencode(query)}"
        headers = {"Accept": "application/json", "User-Agent": "pharmacy-catalog-research/1.0"}
        last_error: Exception | None = None

        for attempt in range(self.retries):
            if self.call_count:
                time.sleep(self.delay)
            self.call_count += 1
            try:
                with urlopen(Request(url, headers=headers), timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8-sig"))
            except HTTPError as exc:
                last_error = exc
                if exc.code not in {429, 500, 502, 503, 504} or attempt + 1 >= self.retries:
                    break
                retry_after = exc.headers.get("Retry-After")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
            except (URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt + 1 >= self.retries:
                    break
                wait = 2**attempt
            time.sleep(wait + random.uniform(0.0, 0.25))

        if isinstance(last_error, HTTPError):
            raise RuntimeError(f"HTTP {last_error.code}") from last_error
        raise RuntimeError(type(last_error).__name__ if last_error else "공식 API 응답 없음")


class PublicSourceAdapter:
    source_type = ""
    source_dataset_url = ""
    endpoint = ""
    key_name = "serviceKey"
    query_parameters: tuple[str, ...] = ("item_name",)
    name_fields: tuple[str, ...] = ("item_name", "itemName", "ITEM_NAME")
    manufacturer_fields: tuple[str, ...] = ("entp_name", "entpName", "ENTP_NAME")
    item_seq_fields: tuple[str, ...] = ("item_seq", "itemSeq", "ITEM_SEQ")
    capacity_fields: tuple[str, ...] = (
        "pack_unit",
        "PACK_UNIT",
        "capacity",
        "CAPACITY",
        "prdlst_desc",
    )
    image_fields: tuple[str, ...] = ()
    image_kind = ""
    image_rights_status = ""
    record_id_parameter = "item_seq"
    categories: set[str] | None = None
    excluded_categories: set[str] = set()

    def supports(self, product: dict[str, Any]) -> bool:
        category = str(product.get("category") or "").strip()
        if category in self.excluded_categories:
            return False
        return self.categories is None or category in self.categories

    def base_params(self) -> dict[str, Any]:
        return {"pageNo": 1, "numOfRows": 20, "type": "json"}

    def make_record_url(self, item_seq: str) -> str:
        if not item_seq:
            return self.source_dataset_url
        return f"{self.endpoint}?{urlencode({self.record_id_parameter: item_seq, 'type': 'json'})}"

    def candidate_from_item(self, item: dict[str, Any]) -> Candidate | None:
        name = first_value(item, self.name_fields)
        if not name:
            return None
        item_seq = first_value(item, self.item_seq_fields)
        image_url = first_value(item, self.image_fields)
        return Candidate(
            source_type=self.source_type,
            source_dataset_url=self.source_dataset_url,
            source_url=self.make_record_url(item_seq),
            official_item_name=name,
            official_manufacturer=first_value(item, self.manufacturer_fields),
            official_item_seq=item_seq,
            official_capacity=first_value(item, self.capacity_fields),
            image_kind=self.image_kind if image_url else "",
            image_url=image_url,
            image_source_url=self.make_record_url(item_seq) if image_url else "",
            image_rights_status=self.image_rights_status if image_url else "",
        )

    def search(self, client: HttpClient, product: dict[str, Any]) -> list[Candidate]:
        query = search_name(product)
        best_attempt: list[Candidate] = []
        for parameter in self.query_parameters:
            params = self.base_params()
            params[parameter] = query
            payload = client.get_json(self.endpoint, params, self.key_name)
            candidates = [
                candidate
                for item in items_from_payload(payload)
                if (candidate := self.candidate_from_item(item)) is not None
            ]
            if candidates:
                best_attempt = candidates
                if max(name_score(query, candidate.official_item_name) for candidate in candidates) >= 50:
                    break
        return best_attempt


class DrugPermitAdapter(PublicSourceAdapter):
    source_type = "식약처 의약품 제품 허가정보"
    source_dataset_url = "https://www.data.go.kr/data/15095677/openapi.do"
    endpoint = os.environ.get(
        "DATA_GO_DRUG_PERMIT_ENDPOINT",
        "https://apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService07/getDrugPrdtPrmsnInq07",
    )
    query_parameters = ("item_name", "itemName")
    capacity_fields = ("PACK_UNIT", "pack_unit", "TOTAL_CONTENT", "CHART")
    excluded_categories = {"코스메틱", "의료기기"}


class EasyDrugAdapter(PublicSourceAdapter):
    source_type = "식약처 의약품개요정보(e약은요)"
    source_dataset_url = "https://www.data.go.kr/data/15075057/openapi.do"
    endpoint = "https://apis.data.go.kr/1471000/DrbEasyDrugInfoService/getDrbEasyDrugList"
    query_parameters = ("itemName",)
    name_fields = ("itemName", "ITEM_NAME")
    manufacturer_fields = ("entpName", "ENTP_NAME")
    item_seq_fields = ("itemSeq", "ITEM_SEQ")
    image_fields = ("itemImage", "ITEM_IMAGE")
    image_kind = "pill"
    image_rights_status = RIGHTS_OPEN
    record_id_parameter = "itemSeq"
    excluded_categories = {"코스메틱", "의료기기"}


SUPPLEMENT_CATEGORIES = {
    "건강보조식품",
    "관절",
    "남성",
    "다이어트",
    "비타민",
    "수면",
    "숙취",
    "여성",
    "영양제",
    "유산균",
    "전립선",
    "키즈",
    "혈행개선",
}


class HealthFunctionalFoodAdapter(PublicSourceAdapter):
    source_type = "식약처 건강기능식품정보"
    source_dataset_url = "https://www.data.go.kr/data/15056760/openapi.do"
    endpoint = os.environ.get(
        "DATA_GO_HEALTH_FUNCTIONAL_FOOD_ENDPOINT",
        "https://apis.data.go.kr/1471000/HtfsInfoService03/getHtfsItem01",
    )
    query_parameters = ("prdlst_nm", "item_name")
    name_fields = ("PRDLST_NM", "prdlst_nm", "item_name")
    manufacturer_fields = ("BSSH_NM", "bssh_nm", "ENTP_NAME", "entp_name")
    item_seq_fields = ("PRDLST_REPORT_NO", "prdlst_report_no", "LCNS_NO")
    capacity_fields = ("DISPOS", "STDR_STND", "POG_DAYCNT")
    record_id_parameter = "prdlst_report_no"
    categories = SUPPLEMENT_CATEGORIES


class HaccpImageAdapter(PublicSourceAdapter):
    source_type = "한국식품안전관리인증원 HACCP 제품이미지"
    source_dataset_url = "https://www.data.go.kr/data/15033307/openapi.do"
    endpoint = os.environ.get(
        "DATA_GO_HACCP_IMAGE_ENDPOINT",
        "https://apis.data.go.kr/B553748/CertImgListServiceV3/getCertImgListService",
    )
    key_name = "ServiceKey"
    query_parameters = ("prdlstNm",)
    name_fields = ("prdlstNm", "PRDLST_NM")
    manufacturer_fields = ("manufacture", "company", "MANUFACTURE", "COMPANY")
    item_seq_fields = ("prdlstReportNo", "PRDLST_REPORT_NO")
    capacity_fields = ("capacity", "CAPACITY")
    image_fields = ("imgurl1", "imgUrl1", "productImg", "PRODUCT_IMG", "imageUrl")
    image_kind = "package"
    image_rights_status = RIGHTS_OPEN
    record_id_parameter = "prdlstReportNo"
    categories = SUPPLEMENT_CATEGORIES

    def base_params(self) -> dict[str, Any]:
        return {"pageNo": 1, "numOfRows": 20, "returnType": "json"}


class FunctionalCosmeticAdapter(PublicSourceAdapter):
    source_type = "식약처 기능성화장품 보고품목정보"
    source_dataset_url = "https://www.data.go.kr/data/15095680/openapi.do"
    endpoint = "https://apis.data.go.kr/1471000/FtnltCosmRptPrdlstInfoService/getRptPrdlstInq"
    query_parameters = ("item_name",)
    manufacturer_fields = ("MANUF_NAME", "ENTP_NAME")
    item_seq_fields = ("COSMETIC_REPORT_SEQ", "ITEM_SEQ")
    record_id_parameter = "cosmetic_report_seq"
    categories = {"코스메틱"}


class MedicalDeviceAdapter(PublicSourceAdapter):
    source_type = "식약처 의료기기 품목허가정보"
    source_dataset_url = "https://www.data.go.kr/data/15057456/openapi.do"
    endpoint = os.environ.get(
        "DATA_GO_MEDICAL_DEVICE_ENDPOINT",
        "https://apis.data.go.kr/1471000/MdlpPrdlstPrmisnInfoService05/getMdlpPrdlstPrmisnList04",
    )
    query_parameters = ("prdlst_nm", "item_name")
    name_fields = ("PRDLST_NM", "ITEM_NAME", "prdlst_nm")
    manufacturer_fields = ("ENTP_NM", "ENTP_NAME", "entp_nm")
    item_seq_fields = ("PRDLST_SEQ", "PRDLST_PRMISN_NO", "prdlst_seq")
    capacity_fields = ("MODEL_NM", "model_nm")
    record_id_parameter = "prdlst_seq"
    categories = {"의료기기"}


ADAPTERS: tuple[PublicSourceAdapter, ...] = (
    DrugPermitAdapter(),
    EasyDrugAdapter(),
    HealthFunctionalFoodAdapter(),
    HaccpImageAdapter(),
    FunctionalCosmeticAdapter(),
    MedicalDeviceAdapter(),
)


def name_score(left: str, right: str) -> int:
    return round(100 * SequenceMatcher(None, normalize(left), normalize(right)).ratio())


def score_candidate(product: dict[str, Any], candidate: Candidate) -> Candidate:
    product_name = normalize(product.get("name"))
    candidate_name = normalize(candidate.official_item_name)
    product_capacity = normalize(product.get("capacity") or product.get("specification"))
    candidate_capacity = normalize(candidate.official_capacity)
    candidate.match_score = name_score(product_name, candidate_name)
    candidate.exact_name = bool(product_name and product_name == candidate_name)
    candidate.exact_capacity = bool(
        product_capacity and candidate_capacity and product_capacity == candidate_capacity
    )

    if (candidate.exact_name and candidate.exact_capacity) or candidate.match_score >= 95:
        candidate.match_status = "confirmed"
    elif candidate.match_score >= 85:
        candidate.match_status = "review"
    else:
        candidate.match_status = "rejected"
    return candidate


def best_candidate(candidates: list[Candidate]) -> Candidate | None:
    usable = [candidate for candidate in candidates if candidate.match_status != "rejected"]
    if not usable:
        return None
    rank = {"confirmed": 2, "review": 1, "rejected": 0}
    return max(
        usable,
        key=lambda candidate: (
            rank[candidate.match_status],
            candidate.match_score,
        ),
    )


def best_image_candidate(candidates: list[Candidate]) -> Candidate | None:
    usable = [
        candidate
        for candidate in candidates
        if candidate.match_status == "confirmed" and candidate.image_url
    ]
    return max(usable, key=lambda candidate: candidate.match_score) if usable else None


def merge_product(
    product: dict[str, Any],
    candidate: Candidate | None,
    image_candidate: Candidate | None,
    checked_at: str,
) -> dict[str, Any]:
    row = dict(product)
    if candidate is None:
        row["enrichment_status"] = (
            "confirmed" if row.get("official_match_status") == "confirmed" else "not_found"
        )
        row["official_checked_at"] = row.get("official_checked_at") or checked_at
        return row

    existing_score = int(row.get("official_match_score") or 0)
    existing_confirmed = row.get("official_match_status") == "confirmed"
    if existing_confirmed and existing_score >= candidate.match_score:
        return row

    row.update(
        {
            "official_item_name": candidate.official_item_name,
            "official_manufacturer": candidate.official_manufacturer,
            "official_item_seq": candidate.official_item_seq,
            "official_source_type": candidate.source_type,
            "official_source_url": candidate.source_url,
            "official_match_score": candidate.match_score,
            "official_match_status": candidate.match_status,
            "official_checked_at": checked_at,
            "enrichment_status": (
                "confirmed" if candidate.match_status == "confirmed" else "review_required"
            ),
        }
    )
    if image_candidate is not None:
        row.update(
            {
                "image_kind": image_candidate.image_kind,
                "image_url": image_candidate.image_url,
                "image_source_url": image_candidate.image_source_url,
                "image_rights_status": image_candidate.image_rights_status,
                "image_checked_at": checked_at,
            }
        )
    return row


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def missing_summary(products: list[dict[str, Any]], output: Path) -> dict[str, Any]:
    return {
        "generated_at": now_iso(),
        "status": "blocked_missing_service_key",
        "required_environment_variable": SERVICE_KEY_ENV,
        "product_count": len(products),
        "official_identity_missing_count": sum(not row.get("official_item_seq") for row in products),
        "official_manufacturer_missing_count": sum(
            not row.get("official_manufacturer") for row in products
        ),
        "official_source_url_missing_count": sum(not row.get("official_source_url") for row in products),
        "image_missing_count": sum(not row.get("image_url") for row in products),
        "output_untouched": str(output.as_posix()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="공식 공공데이터를 순차 조회해 조사 큐를 보강합니다.")
    parser.add_argument("--input", type=Path, default=Path("data/enrichment-queue.json"))
    parser.add_argument("--output", type=Path, default=Path("data/enrichment-results.json"))
    parser.add_argument("--summary", type=Path, default=Path("data/enrichment-run-summary.json"))
    parser.add_argument("--delay", type=float, default=0.22)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--checkpoint-every", type=int, default=20)
    args = parser.parse_args()

    products = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(products, list):
        raise ValueError("입력 JSON의 최상위 값은 상품 배열이어야 합니다.")

    service_key = os.environ.get(SERVICE_KEY_ENV, "").strip()
    if not service_key:
        summary = missing_summary(products, args.output)
        atomic_write_json(args.summary, summary)
        print(json.dumps(summary, ensure_ascii=False))
        return 0

    client = HttpClient(service_key, args.delay, args.timeout, args.retries)
    checked_at = now_iso()
    output_rows: list[dict[str, Any]] = []
    source_errors: Counter[str] = Counter()
    source_candidates: Counter[str] = Counter()

    for index, product in enumerate(products, start=1):
        candidates: list[Candidate] = []
        for adapter in ADAPTERS:
            if not adapter.supports(product):
                continue
            try:
                found = [score_candidate(product, item) for item in adapter.search(client, product)]
                candidates.extend(found)
                source_candidates[adapter.source_type] += len(found)
            except RuntimeError:
                source_errors[adapter.source_type] += 1

        chosen = best_candidate(candidates)
        chosen_image = best_image_candidate(candidates)
        row = merge_product(product, chosen, chosen_image, checked_at)
        row["enrichment_candidates"] = [
            asdict(candidate)
            for candidate in sorted(candidates, key=lambda item: item.match_score, reverse=True)
            if candidate.match_status in {"confirmed", "review"}
        ][:10]
        output_rows.append(row)

        if index % args.checkpoint_every == 0 or index == len(products):
            atomic_write_json(args.output, output_rows)
            print(f"{index}/{len(products)} · 공식 API 호출 {client.call_count}회", flush=True)

    status_counts = Counter(str(row.get("enrichment_status") or "") for row in output_rows)
    summary = {
        "generated_at": now_iso(),
        "status": "completed",
        "product_count": len(output_rows),
        "api_call_count": client.call_count,
        "adapter_order": [adapter.source_type for adapter in ADAPTERS],
        "candidate_counts": dict(source_candidates),
        "source_error_counts": dict(source_errors),
        "enrichment_status_counts": dict(status_counts),
        "confirmed_count": status_counts.get("confirmed", 0),
        "review_required_count": status_counts.get("review_required", 0),
        "not_found_count": status_counts.get("not_found", 0),
        "image_count": sum(bool(row.get("image_url")) for row in output_rows),
        "output": str(args.output.as_posix()),
        "service_key_saved": False,
    }
    atomic_write_json(args.summary, summary)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
