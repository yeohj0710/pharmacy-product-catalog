import assert from "node:assert/strict";
import test from "node:test";

// @ts-expect-error Node 22 strip-types executes explicit .ts module specifiers.
import { catalogSummary, filterProducts, paginateProducts, sortProducts, validateProducts } from "../lib/catalog/catalog.ts";
// @ts-expect-error Node 22 strip-types executes explicit .ts module specifiers.
import { EXPORT_FIELDS, createCsv, createExportFilename, createJson, sanitizeCsvCell } from "../lib/catalog/download.ts";
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

test("validateProducts validates all fields, positive prices, and unique IDs", () => {
  const valid = [product(), product({ id: "id-2", document_id: "doc-2", source_order: 2 })];
  assert.equal(validateProducts(valid).length, 2);
  assert.throws(() => validateProducts({}), /배열/);
  assert.throws(() => validateProducts([product({ displayed_price_krw: 0 })]), /양수/);
  assert.throws(() => validateProducts([product(), product({ document_id: "doc-2" })]), /중복 상품 ID/);
  assert.throws(() => validateProducts([product(), product({ id: "id-2" })]), /중복 Firestore 문서 ID/);
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
