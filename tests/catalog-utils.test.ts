import assert from "node:assert/strict";
import test from "node:test";

// @ts-expect-error Node 22 strip-types executes explicit .ts module specifiers.
import { catalogSummary, filterProducts, paginateProducts, sortProducts, validateProducts } from "../lib/catalog/catalog.ts";
// @ts-expect-error Node 22 strip-types executes explicit .ts module specifiers.
import { EXPORT_FIELDS, createCsv, createExportFilename, createJson, sanitizeCsvCell } from "../lib/catalog/download.ts";
// @ts-expect-error Node 22 strip-types executes explicit .ts module specifiers.
import { compactOfficialText, dedupeLabeledText, formatConsumerGuidance } from "../lib/catalog/text.ts";
import type { CatalogFilters, Product } from "../types/catalog.ts";

function product(overrides: Partial<Product> = {}): Product {
  const base: Product = {
    document_id: "doc-1",
    id: "id-1",
    name: "노스카나겔",
    capacity: "20g",
    category: "상처",
    price: "12000",
    etc: "",
    updated: "20250701",
    app_id: "id-1",
    app_name: "노스카나겔",
    app_capacity: "20g",
    app_category: "상처",
    app_price: "12000",
    app_etc: "",
    app_updated: "20250701",
    document_create_time: "2025-07-01T00:00:00Z",
    document_update_time: "2025-07-01T00:00:00Z",
    specification: "20g",
    displayed_price_krw: 12000,
    normalized_name: "노스카나겔",
    normalized_capacity: "20g",
    source_order: 1,
    source_type: "공개 Firestore products 컬렉션",
    recorded_at: "2026-07-15",
    price_status: "2026-07-15 조회 당시 앱 데이터값",
    verification_status: "Firestore 원본 확인",
    image_url: "",
    image_source_url: "",
    image_rights_status: "미확인",
  };
  return { ...base, ...overrides };
}

const allFilters: CatalogFilters = {
  q: "",
  categories: [],
  priceMin: undefined,
  priceMax: undefined,
  updatedFrom: "",
  updatedTo: "",
  note: "all",
  official: "all",
  image: "all",
};

test("compactOfficialText removes repeated blank lines without changing the source data", () => {
  const source = "(시럽제)\r\n\r\n성인 : 1회 20 mL\n \n소아 : 1회\n\n\n11세 이상 ~ 15세 미만 13 mL";
  assert.equal(
    compactOfficialText(source),
    "(시럽제)\n성인 : 1회 20 mL\n소아 : 1회\n11세 이상 ~ 15세 미만 13 mL",
  );
  assert.equal(source.includes("\r\n\r\n"), true);
});

test("formatConsumerGuidance renders only semantic guidance fields", () => {
  assert.equal(
    formatConsumerGuidance({
      summary: "기침과 가래 증상을 완화합니다.",
      guide: "충분한 수분을 섭취하세요.",
      source_url: "https://health.kr/example",
      full_text: "의약품 상세정보 메뉴와 페이지 전체 원문",
      unknown: "표시하면 안 되는 수집기 내부 값",
    }),
    "무슨 약인가요\n기침과 가래 증상을 완화합니다.\n\n어떻게 복용하나요\n충분한 수분을 섭취하세요.",
  );
});

test("dedupeLabeledText removes repeated official aliases", () => {
  assert.deepEqual(
    dedupeLabeledText([
      ["소비자 복약정보", "무슨 약인가요\n기침을 완화합니다.\n어떻게 복용하나요\n물을 드세요."],
      ["복약 안내", "기침을 완화합니다."],
      ["의약품 설명", "기침을 완화합니다."],
      ["복약지도", "물을 드세요."],
      ["별도 안내", "졸음에 주의하세요."],
    ]),
    [
      ["소비자 복약정보", "무슨 약인가요\n기침을 완화합니다.\n어떻게 복용하나요\n물을 드세요."],
      ["별도 안내", "졸음에 주의하세요."],
    ],
  );
});

test("validateProducts validates all fields, positive prices, and unique IDs", () => {
  const valid = [product(), product({ id: "id-2", document_id: "doc-2", source_order: 2 })];
  assert.equal(validateProducts(valid).length, 2);
  assert.throws(() => validateProducts({}), /배열/);
  assert.throws(() => validateProducts([product({ displayed_price_krw: 0 })]), /양수/);
  assert.throws(() => validateProducts([product(), product({ document_id: "doc-2" })]), /중복 상품 ID/);
  assert.throws(() => validateProducts([product(), product({ id: "id-2" })]), /중복 Firestore 문서 ID/);
});

test("validateProducts accepts enrichment match alternatives", () => {
  const valid = product({
    match_alternatives: [
      {
        official_item_seq: "200001",
        official_item_name: "매칭 후보 상품",
        official_match_score: 82,
      },
    ],
  });

  assert.equal(validateProducts([valid]).length, 1);
});

test("filterProducts combines Korean search, multiple categories, inclusive price and date bounds", () => {
  const products = [
    product(),
    product({
      id: "id-2",
      document_id: "doc-2",
      source_order: 2,
      name: "애크논크림",
      normalized_name: "애크논크림",
      category: "피부",
      app_name: "애크논크림",
      app_category: "피부",
      displayed_price_krw: 15000,
      price: "15000",
      app_price: "15000",
      updated: "20250715",
      app_updated: "20250715",
    }),
    product({
      id: "id-3",
      document_id: "doc-3",
      source_order: 3,
      name: "비타민C 1000",
      normalized_name: "비타민C1000",
      category: "비타민",
      app_name: "비타민C 1000",
      app_category: "비타민",
      displayed_price_krw: 20000,
      price: "20000",
      app_price: "20000",
      updated: "20250720",
      app_updated: "20250720",
    }),
  ];

  assert.deepEqual(
    filterProducts(products, { ...allFilters, q: "애크논" }).map((item) => item.id),
    ["id-2"],
  );
  assert.deepEqual(
    filterProducts(products, {
      ...allFilters,
      categories: ["상처", "피부"],
      priceMin: 12000,
      priceMax: 15000,
      updatedFrom: "2025-07-01",
      updatedTo: "2025-07-15",
    }).map((item) => item.id),
    ["id-1", "id-2"],
  );
});

test("filterProducts handles note, official information, and image states", () => {
  const products = [
    product({ official_match_status: "미연결", official_match_score: 82 }),
    product({
      id: "id-2",
      document_id: "doc-2",
      source_order: 2,
      etc: "약사 확인 필요",
      official_item_seq: "200001",
      image_url: "https://example.com/product.jpg",
      image_rights_status: "공식 공개·재사용 가능",
    }),
  ];

  assert.deepEqual(filterProducts(products, { ...allFilters, note: "with" }).map((item) => item.id), ["id-2"]);
  assert.deepEqual(filterProducts(products, { ...allFilters, official: "linked" }).map((item) => item.id), ["id-2"]);
  assert.deepEqual(filterProducts(products, { ...allFilters, image: "without" }).map((item) => item.id), ["id-1"]);
});

test("filterProducts distinguishes KPIC listing states and official source preview images", () => {
  const products = [
    product({
      official_match_status: "confirmed",
      image_url: "https://common.health.kr/product.jpg",
      image_source_url: "https://health.kr/product/1",
      image_rights_status: "official_source_preview",
    }),
    product({ id: "id-2", document_id: "doc-2", source_order: 2, official_match_status: "not_found", official_match_reason: "검색 후보 없음" }),
    product({ id: "id-3", document_id: "doc-3", source_order: 3, official_match_status: "not_applicable" }),
    product({ id: "id-4", document_id: "doc-4", source_order: 4, official_match_status: "review_required" }),
  ];

  assert.deepEqual(filterProducts(products, { ...allFilters, official: "confirmed" }).map((item) => item.id), ["id-1"]);
  assert.deepEqual(filterProducts(products, { ...allFilters, official: "not_found" }).map((item) => item.id), ["id-2"]);
  assert.deepEqual(filterProducts(products, { ...allFilters, official: "not_applicable" }).map((item) => item.id), ["id-3"]);
  assert.deepEqual(filterProducts(products, { ...allFilters, official: "review_required" }).map((item) => item.id), ["id-4"]);
  assert.deepEqual(filterProducts(products, { ...allFilters, image: "with" }).map((item) => item.id), ["id-1"]);
  assert.equal(catalogSummary(products).officialLinked, 1);
  assert.equal(catalogSummary(products).withImage, 1);
});

test("sortProducts is stable and paginateProducts clamps page ranges", () => {
  const products = [
    product({ id: "id-a", document_id: "doc-a", name: "같은 상품", source_order: 2 }),
    product({ id: "id-b", document_id: "doc-b", name: "같은 상품", source_order: 1 }),
    product({ id: "id-c", document_id: "doc-c", name: "다른 상품", source_order: 3 }),
  ];

  assert.deepEqual(sortProducts(products, "name").map((item) => item.id), ["id-a", "id-b", "id-c"]);
  assert.deepEqual(sortProducts(products, "source").map((item) => item.id), ["id-b", "id-a", "id-c"]);
  const page = paginateProducts(products, 99, 2);
  assert.deepEqual(page.items.map((item) => item.id), ["id-c"]);
  assert.deepEqual({ page: page.page, totalPages: page.totalPages, from: page.from, to: page.to }, { page: 2, totalPages: 2, from: 3, to: 3 });
});

test("catalogSummary calculates true median and availability counts", () => {
  const products = [
    product({ displayed_price_krw: 10000 }),
    product({ id: "id-2", document_id: "doc-2", source_order: 2, displayed_price_krw: 20000, etc: "메모", official_item_seq: "1", image_url: "https://example.com/a.jpg", image_rights_status: "공식 공개·재사용 가능" }),
  ];
  assert.deepEqual(catalogSummary(products), {
    total: 2,
    categoryCount: 1,
    minPrice: 10000,
    maxPrice: 20000,
    medianPrice: 15000,
    withNote: 1,
    officialLinked: 1,
    withImage: 1,
  });
});

test("CSV export includes retail and official-detail fields, UTF-8 BOM, RFC 4180 escaping, and formula protection", async () => {
  assert.equal(EXPORT_FIELDS.length, 67);
  assert.ok(EXPORT_FIELDS.some((field) => field.key === "official_dosage" && field.label === "용법·용량"));
  assert.equal(sanitizeCsvCell("=2+2"), "'=2+2");
  assert.equal(sanitizeCsvCell("-1"), "'-1");
  assert.equal(sanitizeCsvCell('쉼표, 따옴표"'), '"쉼표, 따옴표"""');

  const blob = createCsv([product({ name: "=HYPERLINK(\"https://bad.example\")" })], ["name", "price"]);
  const bytes = new Uint8Array(await blob.arrayBuffer());
  assert.deepEqual([...bytes.slice(0, 3)], [0xef, 0xbb, 0xbf]);
  const csv = await blob.text();
  assert.ok(csv.startsWith("상품명,원본 가격\r\n"));
  assert.match(csv, /'=HYPERLINK/);
});

test("JSON export supports all, filtered, selected products and selected fields", async () => {
  const all = [product(), product({ id: "id-2", document_id: "doc-2", source_order: 2 })];
  const filtered = filterProducts(all, { ...allFilters, q: "노스카나" });
  const selected = all.filter((item) => item.id === "id-2");

  assert.equal((JSON.parse(await createJson(all).text()) as unknown[]).length, 2);
  assert.equal((JSON.parse(await createJson(filtered).text()) as unknown[]).length, 2);
  assert.deepEqual(JSON.parse(await createJson(selected, ["id", "name"]).text()), [{ id: "id-2", name: "노스카나겔" }]);
});

test("export filename follows the Korean scope and date convention", () => {
  assert.equal(
    createExportFilename("필터 결과", "csv", new Date(2026, 6, 15)),
    "창고형_약국_상품_필터_결과_2026-07-15.csv",
  );
});
