# 약국 상품 아카이브

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

사이트는 `public/data/products.json`을 읽는다. 디렉터리 이름이 `public`이어도 외부 공개 승인을 뜻하지 않는다. 이 파일은 Git과 배포 산출물에 포함하지 않는다.

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

## 식약처 정보와 이미지 연결

공공데이터포털에서 [의약품개요정보(e약은요)](https://www.data.go.kr/data/15075057/openapi.do) 활용신청을 한 뒤 일반 인증키를 환경 변수에 넣는다.

```powershell
$env:DATA_GO_KR_SERVICE_KEY='발급받은 인증키'
.\.venv\Scripts\python.exe scripts\enrich_mfds.py data\products.json public\data\products.json
```

e약은요는 공급실적이 있는 일반의약품의 제품 정보와 낱알이미지를 제공한다. 건강기능식품, 화장품과 생활용품은 별도 공식 출처가 필요하다.

## 공개 전 주의

전체 데이터와 가격을 외부에 공개하기 전에 [DATA_POLICY.md](./DATA_POLICY.md)의 공개 게이트를 모두 확인한다. 특히 앱 이용약관·취득 경위, 데이터베이스제작자 권리, 비영리 연구 목적 예외의 조건, 이미지 재사용 근거, 가격 오인 방지 표시와 정정·삭제 연락처를 검토한다. 로컬 저장소는 공개 배포되지 않은 상태다.
