# 상품 데이터 탐색·내보내기 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 776개 상품을 쉽게 검색·필터·정렬·선택하고 원하는 열만 CSV 또는 JSON으로 내려받을 수 있는 로컬 데이터 탐색 사이트를 만든다.

**Architecture:** 정적 `products.json`을 브라우저에서 한 번 읽고 유효성을 검사한 뒤, 순수 함수가 검색·필터·정렬·페이지 구간을 계산한다. 화면 상태는 URL에 저장하고 선택 항목은 현재 탭에만 유지한다. 공식 이미지와 공식 제품 정보는 근거 URL·권리 상태가 확인된 값만 렌더링하며, API 키가 없는 상태에서는 누락을 명시한다.

**Tech Stack:** Next.js 16, React 19, TypeScript, Vinext, Cloudflare Sites 정적 자산, Node test runner

---

## 파일 구조

- `types/catalog.ts`: 상품, 필터, 정렬, 열, 내보내기 형식
- `lib/catalog/catalog.ts`: 데이터 검증, 검색, 필터, 정렬, 페이지 계산, 요약
- `lib/catalog/download.ts`: 필드 선택, CSV 수식 주입 방지, CSV·JSON Blob 생성
- `hooks/use-catalog-state.ts`: URL 상태 읽기·쓰기
- `components/catalog/*.tsx`: 검색 도구, 필터, 표, 카드, 페이지 이동, 상세 모달, 내보내기 모달
- `app/catalog-client.tsx`: 데이터 로딩과 컴포넌트 조합
- `app/globals.css`: 데스크톱·모바일·접근성 스타일
- `scripts/enrichment_schema.py`: 공식 정보·이미지 보강용 필드와 중복 그룹 생성
- `scripts/enrich_public_sources.py`: 공공 API별 보강 후보 생성과 검수 대기 분리
- `tests/catalog-utils.test.ts`: 필터·정렬·다운로드 회귀 테스트
- `tests/rendered-html.test.mjs`: 서버 렌더 결과와 공개 주의문 회귀 테스트

### Task 1: 타입과 순수 데이터 함수

**Files:**
- Create: `types/catalog.ts`
- Create: `lib/catalog/catalog.ts`
- Test: `tests/catalog-utils.test.ts`

- [ ] `Product`, `CatalogFilters`, `SortKey`, `ColumnKey`, `CatalogState`를 정의한다.
- [ ] `validateProducts`가 배열, 고유 ID, 필수 문자열, 양수 가격을 검사하게 한다.
- [ ] `filterProducts`가 검색어, 복수 분류, 가격 범위, 갱신일, 비고, 공식 정보, 이미지 상태를 함께 처리하게 한다.
- [ ] `sortProducts`와 `paginateProducts`를 구현한다.
- [ ] Node test runner로 한글 검색, 경계 가격, 복수 분류, 공식 정보 상태, 정렬 안정성을 검사한다.

### Task 2: 안전한 사용자 지정 다운로드

**Files:**
- Create: `lib/catalog/download.ts`
- Test: `tests/catalog-utils.test.ts`

- [ ] 전체 29개 원본·파생 필드를 내보내기 필드 목록으로 정의한다.
- [ ] CSV 셀이 `=`, `+`, `-`, `@`, 탭, CR로 시작하면 앞에 `'`를 붙인다.
- [ ] 쉼표·따옴표·줄바꿈을 RFC 4180 방식으로 이스케이프하고 UTF-8 BOM을 붙인다.
- [ ] CSV와 JSON 파일명을 `창고형_약국_상품_<범위>_<날짜>`로 만든다.
- [ ] 전체·필터 결과·선택 상품과 사용자 선택 열을 각각 테스트한다.

### Task 3: URL 상태와 데이터 탐색 화면

**Files:**
- Create: `hooks/use-catalog-state.ts`
- Create: `components/catalog/CatalogToolbar.tsx`
- Create: `components/catalog/FilterPanel.tsx`
- Create: `components/catalog/ActiveFilterChips.tsx`
- Create: `components/catalog/ColumnPicker.tsx`
- Create: `components/catalog/CatalogPagination.tsx`
- Create: `components/catalog/ProductTable.tsx`
- Create: `components/catalog/ProductCardList.tsx`
- Create: `components/catalog/SelectionBar.tsx`
- Modify: `app/catalog-client.tsx`

- [ ] `q`, `categories`, `priceMin`, `priceMax`, `updatedFrom`, `updatedTo`, `note`, `official`, `image`, `sort`, `cols`, `page`, `pageSize`, `product`를 URL과 동기화한다.
- [ ] 검색 입력에 `type=search`, 이름, 레이블, 자동완성 방지, 지우기 버튼을 넣는다.
- [ ] 필터 패널에서 복수 분류, 가격, 갱신일, 비고, 공식 정보, 이미지 상태를 조정한다.
- [ ] 활성 필터를 칩으로 보여 주고 조건별 삭제와 전체 초기화를 제공한다.
- [ ] 25·50·100개 페이지 이동과 결과 범위를 표시한다.
- [ ] 데스크톱은 의미론적 표, 모바일은 카드로 표시하고 같은 선택 상태를 공유한다.
- [ ] 표시 열 선택과 다운로드 열 선택을 분리한다.

### Task 4: 상세 모달과 내보내기 모달

**Files:**
- Create: `components/catalog/ProductModal.tsx`
- Create: `components/catalog/ExportDialog.tsx`
- Modify: `app/catalog-client.tsx`
- Modify: `app/globals.css`

- [ ] 상세 모달 헤더와 닫기 버튼을 스크롤 본문 밖에 고정한다.
- [ ] ESC 닫기, 초점 가두기, 닫은 뒤 초점 복귀, 배경 스크롤 차단을 유지한다.
- [ ] 공식 이미지는 HTTPS와 허용 출처만 표시하고 폭·높이·지연 로딩을 지정한다.
- [ ] 내보내기 모달에서 범위, 형식, 필드 그룹, 전체 선택·해제를 제공한다.
- [ ] 완료 상태를 `aria-live=polite`로 알리고 생성한 Blob URL을 해제한다.

### Task 5: 보강 스키마와 이미지 안전 규칙

**Files:**
- Create: `scripts/enrichment_schema.py`
- Create: `scripts/enrich_public_sources.py`
- Modify: `DATA_DICTIONARY.md`
- Modify: `DATA_POLICY.md`

- [ ] 제조사, 공식 제품명, 품목코드, 공식 URL, 매칭 점수·상태, 이미지 종류·출처·권리 상태·확인일 필드를 정의한다.
- [ ] 정규화 상품명+규격 중복 그룹과 보강 상태를 생성한다.
- [ ] 자동 확정은 정확 일치 또는 95점 이상만 허용하고, 85~94점은 검수 대기로 저장한다.
- [ ] 공공 API 키가 없으면 기존 값을 바꾸지 않고 누락 요약 파일만 만든다.
- [ ] 재사용 근거가 없는 제조사·검색 결과 이미지는 복사하지 않는다.

### Task 6: UI 스타일과 접근성

**Files:**
- Modify: `app/globals.css`
- Modify: `app/layout.tsx`

- [ ] 최대 폭 1200px 중심 정렬과 16px 이상 본문 글자 크기를 유지한다.
- [ ] 모든 대화형 요소에 `:focus-visible`을 제공한다.
- [ ] 숫자 열에 `font-variant-numeric: tabular-nums`를 적용한다.
- [ ] 모달에 `overscroll-behavior: contain`, 모바일 하단 막대에 safe-area 여백을 적용한다.
- [ ] 본문 바로가기 링크와 계층적인 제목을 제공한다.
- [ ] `prefers-reduced-motion`에서 애니메이션을 끈다.

### Task 7: 검증과 로컬 배포 준비

**Files:**
- Modify: `tests/rendered-html.test.mjs`
- Modify: `package.json`

- [ ] `node --experimental-strip-types --test tests/catalog-utils.test.ts`를 실행한다.
- [ ] `npm run lint`를 실행한다.
- [ ] `npm run build:local`을 실행한다.
- [ ] 저장된 HTML에서 한국어 제목, 과거 가격 주의문, 다운로드 기능, 데이터 정책 링크를 검사한다.
- [ ] 데스크톱과 모바일에서 검색, 필터, 선택, CSV·JSON 다운로드, 모달 닫기를 브라우저로 검증한다.
- [ ] 공개 배포는 승인 매니페스트가 없으면 계속 차단한다.
