from __future__ import annotations

import hashlib
import html
import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

from .schema import OPEN_DATA_LICENSE, make_image, make_official_record, utc_now


@dataclass(frozen=True)
class SourceSpec:
    key: str
    dataset_id: str
    source_domain: str
    endpoint: str
    query_parameters: tuple[str, ...]
    record_id_fields: tuple[str, ...]
    name_fields: tuple[str, ...]
    manufacturer_fields: tuple[str, ...] = ()
    pack_fields: tuple[str, ...] = ()
    barcode_fields: tuple[str, ...] = ()
    image_fields: tuple[str, ...] = ()
    image_kind: str = ""
    key_name: str = "serviceKey"
    discovery: bool = True
    record_parameter: str = ""

    @property
    def dataset_url(self) -> str:
        return f"https://www.data.go.kr/data/{self.dataset_id}/openapi.do"


SOURCES: dict[str, SourceSpec] = {
    "drug_list": SourceSpec(
        "drug_list", "15095677", "drug",
        "https://apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService07/getDrugPrdtPrmsnInq07",
        ("item_name", "itemName"), ("ITEM_SEQ", "item_seq"), ("ITEM_NAME", "item_name"),
        ("ENTP_NAME", "entp_name"), ("PACK_UNIT", "pack_unit", "TOTAL_CONTENT"),
        ("BAR_CODE", "bar_code"), ("BIG_PRDT_IMG_URL", "big_prdt_img_url"), "package", record_parameter="item_seq",
    ),
    "drug_detail": SourceSpec(
        "drug_detail", "15095677", "drug",
        "https://apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService07/getDrugPrdtPrmsnDtlInq06",
        ("item_seq", "itemSeq"), ("ITEM_SEQ", "item_seq"), ("ITEM_NAME", "item_name"),
        ("ENTP_NAME", "entp_name"), ("PACK_UNIT", "pack_unit", "TOTAL_CONTENT"),
        ("BAR_CODE", "bar_code"), ("BIG_PRDT_IMG_URL", "big_prdt_img_url"), "package", discovery=False, record_parameter="item_seq",
    ),
    "drug_ingredients": SourceSpec(
        "drug_ingredients", "15095677", "drug",
        "https://apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService07/getDrugPrdtMcpnDtlInq07",
        ("item_seq", "itemSeq"), ("ITEM_SEQ", "item_seq"), ("ITEM_NAME", "item_name"),
        ("ENTP_NAME", "entp_name"), discovery=False, record_parameter="item_seq",
    ),
    "easy_drug": SourceSpec(
        "easy_drug", "15075057", "drug",
        "https://apis.data.go.kr/1471000/DrbEasyDrugInfoService/getDrbEasyDrugList",
        ("itemName", "itemSeq"), ("itemSeq", "ITEM_SEQ"), ("itemName", "ITEM_NAME"),
        ("entpName", "ENTP_NAME"), image_fields=("itemImage", "ITEM_IMAGE"), image_kind="pill", record_parameter="itemSeq",
    ),
    "pill_identification": SourceSpec(
        "pill_identification", "15057639", "drug",
        "https://apis.data.go.kr/1471000/MdcinGrnIdntfcInfoService03/getMdcinGrnIdntfcInfoList03",
        ("item_name", "item_seq"), ("ITEM_SEQ", "item_seq"), ("ITEM_NAME", "item_name"),
        ("ENTP_NAME", "entp_name"), barcode_fields=("STD_CD", "std_cd"),
        image_fields=("ITEM_IMAGE", "item_image"), image_kind="pill", record_parameter="item_seq",
    ),
    "quasi_drug": SourceSpec(
        "quasi_drug", "15095679", "quasi_drug",
        "https://apis.data.go.kr/1471000/QdrgPrdtPrmsnInfoService03/getQdrgPrdtPrmsnInfoInq03",
        ("item_name", "itemName"), ("ITEM_SEQ", "item_seq"), ("ITEM_NAME", "item_name"),
        ("ENTP_NAME", "entp_name"), ("PACK_UNIT", "pack_unit"), record_parameter="item_seq",
    ),
    "supplement": SourceSpec(
        "supplement", "15056760", "supplement",
        "https://apis.data.go.kr/1471000/HtfsInfoService03/getHtfsItem01",
        ("prduct", "prdlst_nm"), ("STTEMNT_NO", "PRDLST_REPORT_NO", "sttemnt_no"),
        ("PRDUCT", "PRDLST_NM", "prduct"), ("ENTRPS", "BSSH_NM", "entrps"),
        ("DISPOS", "STDR_STND"), record_parameter="sttemnt_no",
    ),
    "functional_cosmetic_report": SourceSpec(
        "functional_cosmetic_report", "15095680", "cosmetic",
        "https://apis.data.go.kr/1471000/FtnltCosmRptPrdlstInfoService/getRptPrdlstInq",
        ("item_name",), ("ITEM_SEQ", "COSMETIC_REPORT_SEQ"), ("ITEM_NAME",),
        ("ENTP_NAME", "MANUF_NAME"), record_parameter="item_seq",
    ),
    "functional_cosmetic_review": SourceSpec(
        "functional_cosmetic_review", "15056939", "cosmetic",
        "https://apis.data.go.kr/1471057/FtnltCosmSrngPrdlstInfoService04/getSrngPrdlstInq",
        ("item_name",), ("ITEM_SEQ",), ("ITEM_NAME",), ("ENTP_NAME",), ("PACK_UNIT",), record_parameter="item_seq",
    ),
    "medical_device": SourceSpec(
        "medical_device", "15073875", "medical_device",
        "https://apis.data.go.kr/1471000/MdeqStdCdPrdtInfoService03/getMdeqStdCdPrdtInfoInq03",
        ("prdlst_nm", "prdt_nm"), ("UDI_DI", "PRDLST_PRMISN_NO", "PRDLST_SEQ"),
        ("PRDT_NM", "PRDLST_NM", "MODEL_NM"), ("ENTP_NM", "ENTP_NAME"), record_parameter="UDI_DI",
    ),
    "food_image": SourceSpec(
        "food_image", "15033307", "food",
        "https://apis.data.go.kr/B553748/CertImgListServiceV3/getCertImgListServiceV3",
        ("prdlstNm",), ("prdlstReportNo", "PRDLST_REPORT_NO"), ("prdlstNm", "PRDLST_NM"),
        ("manufacture", "company"), ("capacity",), ("barcode",),
        ("imgurl1", "imgUrl1", "productImg"), "package", key_name="ServiceKey", record_parameter="prdlstReportNo",
    ),
}


def first_value(item: dict[str, Any], fields: tuple[str, ...]) -> str:
    for field in fields:
        value = item.get(field)
        if value not in (None, "", []):
            return str(value).strip()
    return ""


def record_source_url(source: SourceSpec, record_id: str) -> str:
    parameter = source.record_parameter or source.query_parameters[0]
    return f"{source.endpoint}?{urllib.parse.urlencode({parameter: record_id})}"


def extract_items(payload: Any) -> list[dict[str, Any]]:
    node = payload
    for key in ("response", "body", "items"):
        if isinstance(node, dict) and key in node:
            node = node[key]
    if isinstance(node, dict) and "item" in node:
        node = node["item"]
    if isinstance(node, dict):
        return [node]
    if isinstance(node, list):
        return [item for item in node if isinstance(item, dict)]
    return []


def text_content(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    raw = str(value)
    try:
        root = ET.fromstring(raw)
        text = " ".join(part.strip() for part in root.itertext() if part.strip())
    except ET.ParseError:
        text = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _field(item: dict[str, Any], *names: str) -> str:
    return first_value(item, tuple(names))


def parse_source_record(source: SourceSpec, item: dict[str, Any], *, fetched_at: str | None = None) -> dict[str, Any]:
    record_id = first_value(item, source.record_id_fields)
    item_name = first_value(item, source.name_fields)
    if not record_id or not item_name:
        raise ValueError(f"{source.key} 응답에 공식 레코드 ID 또는 제품명이 없습니다.")
    fetched_at = fetched_at or utc_now()
    source_url = record_source_url(source, record_id)
    record = make_official_record(
        source_domain=source.source_domain,
        source_dataset_id=source.dataset_id,
        source_record_id=record_id,
        item_name=item_name,
    )
    record["manufacturer"] = first_value(item, source.manufacturer_fields)
    record["identifiers"].update({
        "item_seq": record_id if source.source_domain in {"drug", "quasi_drug", "cosmetic"} else "",
        "barcode": first_value(item, source.barcode_fields),
        "report_number": record_id if source.source_domain in {"supplement", "food"} else "",
        "udi_di": record_id if source.source_domain == "medical_device" else "",
    })
    raw_content = {
        "efficacy": _field(item, "EE_DOC_DATA", "ee_doc_data"),
        "dosage": _field(item, "UD_DOC_DATA", "ud_doc_data"),
        "precautions": _field(item, "NB_DOC_DATA", "nb_doc_data"),
        "professional_precautions": _field(item, "PN_DOC_DATA", "pn_doc_data"),
    }
    consumer = {
        "efficacy": text_content(_field(item, "efcyQesitm", "EFCY_QESITM")),
        "dosage": text_content(_field(item, "useMethodQesitm", "USE_METHOD_QESITM")),
        "warning": text_content(_field(item, "atpnWarnQesitm", "ATPN_WARN_QESITM")),
        "precautions": text_content(_field(item, "atpnQesitm", "ATPN_QESITM")),
        "interactions": text_content(_field(item, "intrcQesitm", "INTRC_QESITM")),
        "side_effects": text_content(_field(item, "seQesitm", "SE_QESITM")),
        "storage": text_content(_field(item, "depositMethodQesitm", "DEPOSIT_METHOD_QESITM")),
    }
    record["content_raw"].update(raw_content)
    record["content"].update({
        "appearance": text_content(_field(item, "CHART", "SUNGSANG", "sungsang")),
        "pack_unit": first_value(item, source.pack_fields),
        "storage": text_content(_field(item, "STORAGE_METHOD", "PRSRV_PD", "depositMethodQesitm")),
        "valid_term": _field(item, "VALID_TERM", "DISTB_PD", "PRSRV_PD"),
        "efficacy": text_content(raw_content["efficacy"]) or consumer["efficacy"] or text_content(_field(item, "MAIN_FNCTN", "EE_NAME")),
        "dosage": text_content(raw_content["dosage"]) or consumer["dosage"] or text_content(_field(item, "SRV_USE", "USAGE_DOSAGE")),
        "precautions": text_content(raw_content["precautions"]) or consumer["precautions"] or text_content(_field(item, "INTAKE_HINT1")),
        "professional_precautions": text_content(raw_content["professional_precautions"]),
        "ingredients": [value for value in [_field(item, "MATERIAL_NAME", "INGR_NAME", "ADIT_INGR", "RAWMTRL")] if value],
        "active_ingredients": [value for value in [_field(item, "MAIN_ITEM_INGR", "ITEM_INGR_NAME", "MAIN_INGR")] if value],
        "consumer_guidance": {key: value for key, value in consumer.items() if value},
    })
    record["classification"].update({
        "category": _field(item, "CLASS_NAME", "CLASS_NO", "PRDLST_NM"),
        "dosage_form": _field(item, "FORM_CODE_NAME", "DRUG_SHAPE", "MODEL_NM"),
        "route": _field(item, "ROUTE_NAME", "METHOD_QESITM"),
        "atc_code": _field(item, "ATC_CODE"),
        "professional_or_general": _field(item, "ETC_OTC_CODE"),
    })
    image_url = first_value(item, source.image_fields)
    if image_url.startswith("https://"):
        record["images"].append(make_image(
            url=image_url,
            kind=source.image_kind,
            source_url=source_url,
            source_dataset_id=source.dataset_id,
            fetched_at=fetched_at,
        ))
    raw = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    record["provenance"].update({
        "source_url": source_url,
        "dataset_url": source.dataset_url,
        "license": OPEN_DATA_LICENSE,
        "fetched_at": fetched_at,
        "upstream_updated_at": _field(item, "UPDATE_DE", "updateDe", "LAST_UPDT_DTM"),
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
    })
    for section in ("identifiers", "classification", "content", "content_raw"):
        for key, value in record[section].items():
            if value not in (None, "", [], {}):
                record["field_provenance"][f"{section}.{key}"] = {
                    "source_key": source.key,
                    "source_dataset_id": source.dataset_id,
                    "source_record_id": record_id,
                    "source_url": source_url,
                }
    return record


def merge_official_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        raise ValueError("병합할 공식 제품 레코드가 없습니다.")
    merged = json.loads(json.dumps(records[0], ensure_ascii=False))
    for record in records[1:]:
        for key in ("item_name", "manufacturer"):
            merged[key] = merged.get(key) or record.get(key, "")
        for section in ("identifiers", "classification", "content"):
            for key, value in record.get(section, {}).items():
                current = merged[section].get(key)
                if isinstance(value, list) and value:
                    merged[section][key] = list(dict.fromkeys([*(current or []), *value]))
                elif isinstance(value, dict) and value:
                    merged[section][key] = {**value, **(current or {})}
                elif value not in (None, "") and current in (None, ""):
                    merged[section][key] = value
        for key, value in record.get("content_raw", {}).items():
            if value and not merged["content_raw"].get(key):
                merged["content_raw"][key] = value
        known_images = {image.get("url") for image in merged.get("images", [])}
        merged["images"].extend(image for image in record.get("images", []) if image.get("url") not in known_images)
        for field, provenance in record.get("field_provenance", {}).items():
            merged.setdefault("field_provenance", {}).setdefault(field, provenance)
        merged.setdefault("additional_provenance", []).append(record.get("provenance", {}))
    return merged
