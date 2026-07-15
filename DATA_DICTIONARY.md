# 데이터 필드 설명

`data/firestore-products.json`은 Firestore의 타입과 원본 값을 보존하는 로컬 정본이다. `data/products.json`과 `data/catalog.csv`는 원본 필드와 검색·표시용 파생 필드를 함께 제공한다. 원본 필드가 빈 문자열이어도 삭제하지 않는다.

## 원본 필드

| 필드 | 의미 |
|---|---|
| `document_id` | Firestore 문서 ID |
| `id` | 원본 상품 식별자 |
| `name` | 원본 상품명 |
| `capacity` | 원본 용량·규격 |
| `category` | 원본 상품 분류 |
| `price` | 원본 가격 문자열. 숫자 변환 없이 그대로 보존 |
| `etc` | 원본 비고. 빈 문자열도 보존 |
| `updated` | 원본 갱신일 문자열 |
| `document_create_time` | Firestore 문서 생성 시각 |
| `document_update_time` | Firestore 문서 갱신 시각 |
| `app_id` ~ `app_updated` | 7개 원본 필드를 앱 출처 필드로 구분해 손실 없이 복사한 값 |

## 파생 필드

| 필드 | 의미 |
|---|---|
| `specification` | 사이트 호환용 규격. 원본 `capacity`를 복사하며 원본은 변경하지 않음 |
| `displayed_price_krw` | 정렬·표시용 원화 정수. 원본 `price`도 함께 보존 |
| `normalized_name` | OCR 대조와 검색용으로 공백·기호를 제거한 상품명 |
| `normalized_capacity` | OCR 대조용으로 공백·기호를 제거한 규격 |
| `source_order` | 문서 ID 순으로 정렬한 로컬 목록 순서 |
| `source_type` | 데이터 조회 경로 |
| `recorded_at` | 데이터 조회 날짜 |
| `price_status` | 가격의 조회 시점과 비확정 상태 |
| `verification_status` | 원본 확인 상태 |
| `image_url` | 제품 이미지 URL. 원격 미리보기는 파일로 복제하지 않음 |
| `image_source_url` | 이미지나 제품 정보를 확인한 원본 페이지 URL |
| `image_rights_status` | `official_source_preview`, `source_preview`, `미확인` 등 이미지 표시 기준 |

`price`와 `displayed_price_krw`는 2026년 7월 15일 조회값이다. 현재 판매가, 재고 또는 구매 가능 여부로 사용하지 않는다.

## 공식 출처 조사 큐

`scripts/enrichment_schema.py`는 `data/products.json`을 변경하지 않고 다음 별도 파일을 만든다.

- `data/enrichment-queue.json`: 원본 상품 필드와 조사 상태를 함께 보관하는 정본 큐
- `data/enrichment-queue.csv`: 사람이 검토하고 필터링할 수 있는 CSV 큐
- `data/enrichment-summary.json`: 누락 필드와 중복 상품 집계

| 필드 | 의미 |
|---|---|
| `duplicate_group_id` | 정규화 상품명이 같은 상품이 2개 이상일 때 부여하는 안정적인 그룹 ID |
| `duplicate_group_size` | 같은 정규화 상품명을 가진 상품 수. 단독 상품은 `1` |
| `official_item_name` | 공식 공개 출처에 적힌 제품명 |
| `official_manufacturer` | 공식 공개 출처에 적힌 제조사·업체명 |
| `official_item_seq` | 품목기준코드, 보고번호, 품목허가번호 등 공식 레코드 식별자 |
| `official_source_type` | 약학정보원 또는 공식 공공데이터 서비스 이름 |
| `official_source_url` | 제품별 원문 페이지 또는 공식 레코드 URL |
| `official_match_score` | 정규화한 원본 상품명과 공식 제품명의 문자열 유사도. 0~100 |
| `official_match_status` | `pending`, `confirmed`, `review_required`, `not_found`, `not_applicable`, `blocked_missing_key`, `error` 중 하나 |
| `official_checked_at` | 공식 API를 확인한 시각. ISO 8601 |
| `image_kind` | `pill`은 낱알 이미지, `package`는 제품 포장 이미지 |
| `image_url` | 확인된 공식 이미지 URL |
| `image_source_url` | 이미지를 제공한 개별 공식 레코드 URL |
| `image_rights_status` | 이미지 제공기관과 이용허락범위 확인 상태 |
| `image_checked_at` | 이미지 출처와 이용허락범위를 확인한 시각 |
| `enrichment_status` | `pending`, `confirmed`, `review_required`, `not_found` 등 전체 조사 상태 |
| `official_ingredients` | 약학정보원 원문에서 확인한 성분과 함량 목록 |
| `official_efficacy` | 효능·효과 원문 |
| `official_dosage` | 용법·용량 원문 |
| `official_precautions` | 사용상의 주의사항 원문 |
| `official_storage` | 저장방법 |
| `official_dosage_form` | 제형 |
| `official_route` | 투여경로 |
| `official_pack_unit` | 포장단위 |
| `official_images` | 포장·낱알 이미지 URL, 종류와 원문 출처 목록 |
| `official_content_status` | 핵심 상세정보가 모두 있으면 `complete`, 일부만 있으면 `partial` |

자동 확정은 공식 식별자가 같거나, 정규화 상품명이 정확히 같고 경쟁 후보와 제형·함량 충돌이 없을 때만 허용한다. 점수가 95점 이상이어도 3점 이내의 경쟁 후보가 있으면 `review_required`로 보낸다. 80~94점도 `review_required`로 보내며 사람이 확인하기 전에는 기존 제품 데이터나 공개 파일에 합치지 않는다.

## 공식 제품 상세 레코드

공식 제품 상세 레코드는 `data/official-product-details.json`에 저장한다. 판매 SKU와 공식 품목은 여러 판매 SKU가 하나의 공식 품목에 연결될 수 있으므로 별도 엔터티로 관리한다.

| 필드 | 의미 |
|---|---|
| `official_product_key` | `제품영역:공식레코드ID` 형식의 내부 키 |
| `source_domain` | `drug`, `quasi_drug`, `supplement`, `cosmetic`, `medical_device`, `food` 중 하나 |
| `item_name` | 공식 제품명 |
| `manufacturer` | 공식 제조·수입·판매 업체명 |
| `identifiers` | 품목기준코드, 바코드, 표준코드, 품목제조관리번호, UDI-DI |
| `classification` | 제품 분류, 제형, 투여 경로, ATC 코드, 전문·일반 구분 |
| `content` | 성상, 포장단위, 저장방법, 유효기간, 효능, 용법, 주의사항, 성분, 소비자 복약정보 |
| `content_raw` | 효능·용법·주의사항 공식 XML 원문 |
| `images` | 이미지 종류, URL, 출처, 데이터셋 ID, 이용허락, 수집 시각과 해시 |
| `provenance` | 데이터셋 ID, 공식 레코드 ID, 출처 URL, 이용허락, 수집일, 상위 수정일과 원문 해시 |
| `field_provenance` | 효능·용법·성분 등 각 필드가 나온 API, 데이터셋 ID, 공식 레코드 ID와 출처 URL |

## 판매 SKU와 공식 품목 매칭 레코드

`data/product-official-matches.json`은 판매 상품 ID와 공식 제품 키를 연결한다.

| 필드 | 의미 |
|---|---|
| `catalog_product_id` | 원본 판매 상품 ID |
| `official_product_key` | 연결된 공식 제품 키 |
| `score` | 0~100 매칭 점수 |
| `score_components` | 제품명, 제조사, 판매 규격, 제형과 식별자별 점수 |
| `status` | `pending`, `confirmed`, `review_required`, `not_found`, `not_applicable`, `blocked_missing_key`, `error` |
| `alternatives` | 검토할 공식 후보 목록과 후보별 점수 |
| `decision_source` | 자동 확정 또는 사람 검수 여부 |
| `reviewer`, `reviewed_at` | 검수자와 검수 시각 |
