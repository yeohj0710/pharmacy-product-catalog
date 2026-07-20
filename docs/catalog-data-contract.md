# 약국 상품 카탈로그 데이터 계약 v1

## 다른 프로젝트에서는 portable/v1만 읽습니다

재사용 경로는 `data/portable/v1/`입니다. 애플리케이션 내부 호환용인 `data/enrichment-queue.json`의 필드 구조를 다른 프로젝트가 직접 의존하지 않도록 합니다.

- `products.json`: 776개 상품의 JSON 배열
- `products.ndjson`: 검색 색인, 임베딩, AI API 배치 입력을 위한 한 줄 한 상품 형식
- `schema.json`: 상품 한 건의 JSON Schema Draft 2020-12 계약
- `manifest.json`: 상품 수, 공식 정보 수, 이미지 수와 파일별 SHA-256
- `README.md`: 패키지 사용 원칙과 버전 변경 규칙

웹 배포 후에는 `/data/portable/v1/` 아래에서 같은 파일을 받을 수 있습니다.

## 한 상품의 안정적인 구조

`schema_version`과 `product_id`는 최상위에 있습니다. 나머지 데이터는 용도별로 분리합니다.

- `display`: 상품명, 규격, 분류, 기록 가격, 비고, 원본 순서
- `media.primary_image`: 이미지 URL, 실제 상품 페이지 URL, 이미지 종류, 권리 확인 상태
- `medicine.identity`: 약학정보원 품목명·품목코드·제조사·제형·투여 경로·포장단위
- `medicine.content`: 정규화 문자열과 순서가 보존된 문단·표 블록
- `medicine.ingredients`: 유효성분, 전체 성분, 첨가제
- `quality`: 공식 매칭 상태, 본문 정규화 상태, 이미지 권리 상태
- `provenance`: 카탈로그 수집 출처와 기록일
- `ai_context`: AI API에 바로 전달할 수 있는 정규화 사실과 출처 링크

`quality.official_match_status`가 `confirmed`가 아니면 `medicine`은 `null`입니다. 카탈로그 상품명만 보고 의약품 정보를 추정해서 채우지 않습니다.

## 문단과 표를 처리하는 방법

`medicine.content.<section>`은 다음 두 값을 제공합니다.

```json
{
  "text": "사람이 읽거나 검색할 수 있는 전체 일반 텍스트",
  "blocks": [
    { "type": "paragraph", "text": "문단" },
    {
      "type": "table",
      "headers": ["구분", "용량"],
      "rows": [["경증", "10 mg"]]
    }
  ]
}
```

검색·임베딩에는 `text`를 사용합니다. 화면에서 표를 표시하거나 셀 단위 계산이 필요하면 `blocks`를 사용합니다. `blocks`를 다시 HTML로 파싱하거나 `br` 문자열을 치환할 필요가 없습니다.

## AI API 입력 예시

Python에서 NDJSON을 읽는 예시입니다.

```python
import json
from pathlib import Path

records = [
    json.loads(line)
    for line in Path("data/portable/v1/products.ndjson").read_text(encoding="utf-8").splitlines()
]
prompt_input = records[0]["ai_context"]
source_url = records[0]["medicine"]["source"]["url"] if records[0]["medicine"] else None
```

TypeScript에서 JSON을 읽는 예시입니다.

```ts
import products from "./data/portable/v1/products.json" with { type: "json" };

const confirmed = products.filter((product) => product.quality.official_match_status === "confirmed");
const contexts = confirmed.map((product) => ({
  id: product.product_id,
  input: product.ai_context,
  source: product.medicine?.source.url,
}));
```

AI가 생성한 요약·분류·답변은 원문 데이터에 덮어쓰지 않습니다. 생성 결과에는 사용한 `product_id`, 모델, 프롬프트 버전, 생성 시각과 출처 URL을 함께 저장합니다.

## 재생성과 검증 명령

```powershell
npm run catalog:text:normalize
npm run catalog:text:audit
npm run catalog:portable:export
npm run catalog:sync
```

`npm run catalog:sync`는 다음 조건 중 하나라도 어기면 실패합니다.

- 상품 수가 776개가 아님
- 정규화 결과가 정식 데이터에 반영되지 않음
- 공개 필드에 HTML, `br`, 손상된 숫자 범위, 대체 문자 또는 보이지 않는 문자가 남음
- portable 파일의 SHA-256이 manifest와 다름
- JSON과 NDJSON의 상품 내용 또는 순서가 다름
- portable 파일이 현재 정식 데이터에서 다시 생성한 결과와 다름

## 호환성과 버전 변경

v1 안에서는 기존 필드를 삭제하거나 의미를 바꾸지 않습니다. 선택 필드 추가만 허용합니다. 필드 삭제, 자료형 변경 또는 의미 변경이 필요하면 `data/portable/v2/`와 새 `schema_version`을 만듭니다.

약학정보원 원문 캐시는 재생성 근거로만 사용하며 portable 패키지에는 HTML 원문을 넣지 않습니다. 약학정보원 자료를 다른 프로젝트에서 공개하거나 상업적으로 사용하기 전에는 데이터 기준 페이지(`app/data-policy/page.tsx`, 운영 경로 `/data-policy`)의 이용 조건과 권리 확인 절차를 다시 확인해야 합니다.
