import type { Product } from "../../types/catalog.ts";

export interface ExportField {
  key: keyof Product & string;
  label: string;
}

export const EXPORT_FIELDS = [
  { key: "document_id", label: "Firestore 문서 ID" },
  { key: "id", label: "원본 상품 ID" },
  { key: "name", label: "상품명" },
  { key: "capacity", label: "규격" },
  { key: "category", label: "분류" },
  { key: "price", label: "원본 가격" },
  { key: "etc", label: "원본 비고" },
  { key: "app_id", label: "앱 상품 ID" },
  { key: "app_name", label: "앱 상품명" },
  { key: "app_capacity", label: "앱 규격" },
  { key: "app_category", label: "앱 분류" },
  { key: "app_price", label: "앱 가격" },
  { key: "app_etc", label: "앱 비고" },
  { key: "document_create_time", label: "문서 생성 시각" },
  { key: "document_update_time", label: "문서 갱신 시각" },
  { key: "specification", label: "표시 규격" },
  { key: "displayed_price_krw", label: "표시 가격(원)" },
  { key: "normalized_name", label: "정규화 상품명" },
  { key: "normalized_capacity", label: "정규화 규격" },
  { key: "source_order", label: "원본 순서" },
  { key: "source_type", label: "출처 유형" },
  { key: "price_status", label: "가격 상태" },
  { key: "verification_status", label: "확인 상태" },
  { key: "image_url", label: "이미지 URL" },
  { key: "image_source_url", label: "이미지 출처 URL" },
  { key: "image_rights_status", label: "이미지 권리 상태" },
  { key: "duplicate_group_id", label: "중복 후보 그룹 ID" },
  { key: "duplicate_group_size", label: "중복 후보 그룹 크기" },
  { key: "official_item_name", label: "공식 제품명" },
  { key: "official_manufacturer", label: "공식 제조사·업체" },
  { key: "official_item_seq", label: "공식 품목 식별자" },
  { key: "official_source_type", label: "공식 정보 출처" },
  { key: "official_source_url", label: "공식 레코드 URL" },
  { key: "official_match_score", label: "공식 정보 매칭 점수" },
  { key: "official_match_status", label: "공식 정보 매칭 상태" },
  { key: "official_checked_at", label: "공식 정보 확인 시각" },
  { key: "official_product_key", label: "공식 제품 내부 키" },
  { key: "official_domain", label: "공식 제품 영역" },
  { key: "official_barcode", label: "공식 바코드" },
  { key: "official_standard_codes", label: "공식 표준코드" },
  { key: "official_report_number", label: "공식 신고·보고번호" },
  { key: "official_udi_di", label: "의료기기 UDI-DI" },
  { key: "official_category", label: "공식 제품 분류" },
  { key: "official_dosage_form", label: "공식 제형" },
  { key: "official_route", label: "공식 투여 경로" },
  { key: "official_atc_code", label: "ATC 코드" },
  { key: "official_pack_unit", label: "공식 포장단위" },
  { key: "official_storage", label: "저장방법" },
  { key: "official_valid_term", label: "유효기간" },
  { key: "official_appearance", label: "성상" },
  { key: "official_efficacy", label: "효능·효과" },
  { key: "official_dosage", label: "용법·용량" },
  { key: "official_precautions", label: "사용상의 주의사항" },
  { key: "official_professional_precautions", label: "전문가 주의사항" },
  { key: "official_ingredients", label: "전체 성분" },
  { key: "official_active_ingredients", label: "유효성분" },
  { key: "official_consumer_guidance", label: "소비자 복약정보" },
  { key: "official_images", label: "공식 이미지 목록" },
  { key: "official_license", label: "공식 데이터 이용허락" },
  { key: "official_upstream_updated_at", label: "공식 데이터 수정일" },
  { key: "official_raw_sha256", label: "공식 원문 SHA-256" },
  { key: "official_content_status", label: "공식 상세정보 상태" },
  { key: "lookup_status", label: "공식 조회 상태" },
  { key: "match_alternatives", label: "공식 매칭 후보" },
  { key: "image_kind", label: "이미지 종류" },
  { key: "image_checked_at", label: "이미지 확인 시각" },
  { key: "enrichment_status", label: "데이터 보강 상태" },
] as const satisfies readonly ExportField[];

export type ExportFieldKey = (typeof EXPORT_FIELDS)[number]["key"];

function valueAsText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function selectedFields(fields?: readonly ExportFieldKey[]): readonly ExportField[] {
  if (!fields) return EXPORT_FIELDS;
  const requested = new Set(fields);
  return EXPORT_FIELDS.filter((field) => requested.has(field.key));
}

export function sanitizeCsvCell(value: unknown): string {
  let text = valueAsText(value);
  if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`;
  if (/[",\r\n]/.test(text)) text = `"${text.replace(/"/g, '""')}"`;
  return text;
}

export function createCsv(
  products: readonly Product[],
  fields?: readonly ExportFieldKey[],
): Blob {
  const columns = selectedFields(fields);
  const rows = [
    columns.map((field) => sanitizeCsvCell(field.label)).join(","),
    ...products.map((product) =>
      columns.map((field) => sanitizeCsvCell(product[field.key])).join(","),
    ),
  ];
  return new Blob(["\uFEFF", rows.join("\r\n")], {
    type: "text/csv;charset=utf-8",
  });
}

export function createJson(
  products: readonly Product[],
  fields?: readonly ExportFieldKey[],
): Blob {
  const columns = selectedFields(fields);
  const output = products.map((product) =>
    Object.fromEntries(columns.map((field) => [field.key, product[field.key]])),
  );
  return new Blob([JSON.stringify(output, null, 2)], {
    type: "application/json;charset=utf-8",
  });
}

export function createExportFilename(
  scope: string,
  format: "csv" | "json",
  date = new Date(),
): string {
  const safeScope = scope.trim().replace(/[^0-9A-Za-z가-힣_-]+/g, "_") || "전체";
  const day = [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getDate()).padStart(2, "0"),
  ].join("-");
  return `창고형_약국_상품_${safeScope}_${day}.${format}`;
}

export function downloadBlob(blob: Blob, filename: string): void {
  if (typeof document === "undefined" || typeof URL.createObjectURL !== "function") {
    throw new Error("파일 다운로드는 브라우저에서만 실행할 수 있습니다.");
  }
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.hidden = true;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
