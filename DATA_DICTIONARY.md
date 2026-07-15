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
| `image_url` | 이용 조건을 확인한 제품 이미지 URL |
| `image_source_url` | 이미지와 공식 제품 정보를 확인한 원본 페이지 URL |
| `image_rights_status` | 이미지 출처와 이용 조건 확인 상태 |

`price`와 `displayed_price_krw`는 2026년 7월 15일 조회값이다. 현재 판매가, 재고 또는 구매 가능 여부로 사용하지 않는다.
