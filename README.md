# 약국 상품 아카이브

운영 사이트: [pharmacy-product-catalog.vercel.app](https://pharmacy-product-catalog.vercel.app)

공개 Firestore `products` 컬렉션에서 약국 상품명, 규격, 분류와 조회 당시 가격을 추출하고 검색하는 로컬 데이터 프로젝트다. **가격을 포함한 원본 필드는 버리지 않는다.** `id`, `name`, `capacity`, `category`, `price`, `etc`, `updated`를 삭제하거나 덮어쓰지 않고, 화면 녹화 OCR 결과는 원본 데이터 대조용으로만 사용한다. 메가팩토리약국 또는 `창고형약국 약값체크` 앱과 제휴·승인 관계가 없다.

## 로컬 보존과 외부 공개

- 로컬 JSON·CSV에는 상품명, 규격, 분류, 가격, 출처와 검수 필드를 모두 보존한다.
- 가격은 추출·녹화 시점에 앱이 표시한 값이며 현재 판매가·재고가 아니다.
- `data/firestore-products.json`, `data/products*.json`, `data/catalog.csv`, `public/data/products.json`, `public/data/catalog.csv`는 로컬 데이터다. Git이나 외부 배포에 포함하지 않는다.
- 원본 앱 화면, 로고, 광고, 재고 사진과 이용 조건을 확인하지 못한 이미지는 공개 파일에 넣지 않는다.
- 외부 공개는 [DATA_POLICY.md](./DATA_POLICY.md)의 공개 게이트를 모두 통과한 뒤 별도 승인한다. 로컬 사이트가 작동한다는 사실은 공개 승인을 뜻하지 않는다.

## 실행

```powershell
npm install
npm run dev
```

사이트는 `data/enrichment-queue.json`을 정본으로 사용한다. `npm run catalog:sync`가 검색·다운로드용 파일을 `public/data/enrichment-queue.json`과 CSV로 복사한다.

## 정확한 원본 데이터 추출

`scripts/extract_firestore_catalog.py`는 APK 리소스의 Firebase 설정을 실행 중에만 읽고 공개 `products` 컬렉션을 페이지 단위로 가져온다. API 키는 파일, 로그, JSON, CSV에 저장하지 않는다.

처음 준비할 때는 Python 가상환경을 만들고 Google Play의 `com.hiddenwave.yakcheck` 11.0.0(버전 코드 9) 기준 APK를 `etc\apk\com.hiddenwave.yakcheck-9.apk`에 둔다. 기준 APK SHA-256은 `975E77E6F6933EE5C78FEF7DC755A62A77E95120197C18391EA8240479E354DA`다. 다른 파일을 쓸 때는 `--apk <경로>`를 지정하고 출처·버전·해시를 다시 기록한다. 제3자 APK는 Git이나 배포 파일에 포함하지 않는다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-extraction.txt
.\.venv\Scripts\python.exe scripts\extract_firestore_catalog.py
```

추출 스크립트는 다음 파일을 만든다.

- `data/firestore-products.json`: Firestore 타입과 원본 필드를 모두 보존한 로컬 정본
- `data/products.json`: 원본 필드와 검색·표시용 파생 필드를 함께 담은 로컬 JSON
- `data/catalog.csv`: Excel에서 열 수 있는 전체 상품 CSV
- `public/data/products.json`: 로컬 사이트가 읽는 JSON
- `public/data/catalog.csv`: 사이트에서 내려받는 CSV
- `data/firestore-extraction-report.json`: 문서 수, 필드 누락, 중복과 개인정보 패턴 검사 결과

스크립트는 개인정보 가능 패턴이나 중복 문서 ID를 찾으면 로컬 정본과 검사 보고서만 저장하고 `public/data` 파일은 만들지 않는다. 전체 데이터 파일은 Git에 포함하지 않는다.

## 화면 녹화 OCR 대조

OCR 오인식을 줄이기 위해 전체 목록을 서로 다른 시작 시점으로 두 번 읽고, 짧은 코스메틱 목록을 분류 기준으로 사용한다.

```powershell
$env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK='True'
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe scripts\extract_catalog.py "전체 제품 목록.mp4" --output data --interval 1 --scale 0.6
.\.venv\Scripts\python.exe scripts\extract_catalog.py "전체 제품 목록.mp4" --output etc\pass2 --interval 1 --start 0.5 --end 471.5 --scale 0.6
.\.venv\Scripts\python.exe scripts\extract_catalog.py "코스메틱 제품 목록.mp4" --output etc\cosmetic-pass --interval 0.75 --scale 0.6
.\.venv\Scripts\python.exe scripts\finalize_catalog.py data\products.raw.json etc\pass2\products.raw.json --cosmetic-reference etc\cosmetic-pass\products.raw.json --expected 776
```

OCR 결과는 기본적으로 `etc/ocr-final/`에 생성된다. `normalized_name`을 Firestore 결과와 비교하면 오인식과 누락을 찾을 수 있다. `data/products.json`과 `public/data/products.json`은 Firestore 정본이므로 OCR 출력 경로로 지정하지 않는다.

## 로컬 사이트와 공개 차단

```powershell
npm run dev
npm run build:local
```

개발 서버와 `build:local`은 776개 전체 가격 데이터를 포함한다. 일반 `npm run build`는 공개 승인 전 실수로 배포하지 못하도록 실패한다. 외부 배포 전에는 `DATA_POLICY.md`의 공개 게이트를 모두 확인하고 별도 승인을 기록해야 한다.

각 열의 뜻은 [DATA_DICTIONARY.md](./DATA_DICTIONARY.md)에 정리했다.

## 제품 상세정보와 이미지 연결

약학정보원에서 정확히 일치하는 의약품은 성분, 효능·효과, 용법·용량, 사용상의 주의사항, 저장방법, 제조사, 제형, 투여경로, 포장단위와 원문 링크를 별도 필드로 저장한다. 일치 여부가 모호하거나 규격·제형이 충돌하면 `review_required`로 격리하고 상세정보와 이미지를 표시하지 않는다.

약학정보원에 이미지가 없거나 약학정보원 대상이 아닌 상품은 다나와·네이버 검색 결과를 보조 조사한다. 검색 결과 이미지는 파일로 복제하지 않고 출처 페이지가 연결된 원격 미리보기로만 사용한다. 짧거나 일반적인 상품명은 자동 확정하지 않는다. 자세한 출처·권리 기준은 [DATA_POLICY.md](./DATA_POLICY.md)에 적었다.

```powershell
npm run kpic:images
npm run kpic:details:merge
npm run images:secondary
npm run images:secondary:merge
npm run images:naver
```

공공데이터포털의 식약처·식품안전관리인증원 공식 API도 별도 수집기로 지원한다. 허가정보, e약은요, 건강기능식품, HACCP 이미지 등의 API를 사용하려면 인증키가 필요하다.

공공데이터포털에서 `15095677`, `15075057`, `15057639`, `15095679`, `15056760`, `15095680`, `15056939`, `15073875`, `15033307`의 활용을 신청하고 발급받은 일반 인증키를 현재 PowerShell 세션에 넣는다. 인증키는 저장소 파일에 쓰지 않는다.

```powershell
$env:DATA_GO_KR_SERVICE_KEY='발급받은 인증키'
npm run official:check
npm run official:batch -- --start 0 --limit 25
npm run official:all
npm run official:materialize
```

`official:batch`는 기본 25개씩 처리하고 제품마다 중간 저장한다. `official:all`은 776개 전체를 이어서 처리하며 이미 확정된 제품은 건너뛴다. 공식 제품명이 같거나 3점 이내 후보가 여럿이면 자동 반영하지 않고 `review_required`로 남긴다. GPT Pro 또는 사람이 검수할 입력은 `npm run official:review`로 만들며, 작업 지침은 [docs/GPT_PRO_HANDOFF.md](./docs/GPT_PRO_HANDOFF.md)에 있다.

## 공개 전 주의

전체 데이터와 가격을 외부에 공개하기 전에 [DATA_POLICY.md](./DATA_POLICY.md)의 공개 게이트를 모두 확인한다. 특히 앱 이용약관·취득 경위, 데이터베이스제작자 권리, 비영리 연구 목적 예외의 조건, 이미지 재사용 근거, 가격 오인 방지 표시와 정정·삭제 연락처를 검토한다. 로컬 저장소는 공개 배포되지 않은 상태다.
