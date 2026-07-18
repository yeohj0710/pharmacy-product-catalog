import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render(path = "/") {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}-${path}`);
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(
    new Request(`http://localhost${path}`, { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("renders the Korean catalog shell and concise price guidance", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /<html lang="ko">/);
  assert.match(html, /약국 상품 아카이브/);
  assert.match(html, /실제 판매 가격이나 재고와 다를 수 있습니다/);
  assert.doesNotMatch(html, /조회 당시 앱 가격|앱 데이터 갱신일|조회 날짜/);
  assert.match(html, /공개 자료의 출처를 확인해 정리한/);
  assert.doesNotMatch(html, /메가팩토리약국|창고형약국 약값체크/);
  assert.match(html, /검색 조건을 조합하고 필요한 상품과 필드를 골라 내려받을 수 있습니다/);
  assert.match(html, /데이터 받기/);
  assert.doesNotMatch(html, /codex-preview|SkeletonPreview|Your site is taking shape/);
});

test("renders the data policy with source and publication limits", async () => {
  const response = await render("/data-policy");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /데이터 보존·공개 기준/);
  assert.match(html, /실제 판매 가격·재고와 다를 수 있으므로/);
  assert.match(html, /전체 데이터의 외부 공개, 공개 API 제공 또는 상업적 이용 전/);
  assert.match(html, /data\.go\.kr\/data\/15075057/);
  assert.match(html, /공개 자료 제공기관이나 검색 서비스의 공식·제휴 서비스가 아닙니다/);
  assert.doesNotMatch(html, /메가팩토리약국|창고형약국 약값체크/);
});

const localCatalogUrl = new URL("../public/data/enrichment-queue.json", import.meta.url);
const globalCssUrl = new URL("../app/globals.css", import.meta.url);
const productModalUrl = new URL("../components/catalog/ProductModal.tsx", import.meta.url);
const exportDialogUrl = new URL("../components/catalog/ExportDialog.tsx", import.meta.url);
const productImageUrl = new URL("../components/catalog/ProductImage.tsx", import.meta.url);
const packageJsonUrl = new URL("../package.json", import.meta.url);
const vercelConfigUrl = new URL("../vercel.json", import.meta.url);

test("Vercel builds and serves the static Next.js export", async () => {
  const packageJson = JSON.parse(await readFile(packageJsonUrl, "utf8"));
  const vercelConfig = JSON.parse(await readFile(vercelConfigUrl, "utf8"));
  assert.equal(packageJson.scripts["vercel-build"], "npm run prebuild && npm run build:static");
  assert.equal(vercelConfig.buildCommand, "npm run vercel-build");
  assert.equal(vercelConfig.outputDirectory, "out");
  assert.equal(vercelConfig.cleanUrls, true);
});

test("product modal renders official information as an always-visible document", async () => {
  const source = await readFile(productModalUrl, "utf8");
  assert.doesNotMatch(source, /<details|<summary/);
  assert.match(source, /official-detail-group/);
  assert.match(source, /약학정보원 제품 원문/);
  assert.match(source, /제품 이미지 출처/);
  assert.match(source, /product\.official_source_url/);
  assert.match(source, /product\.image_source_url/);
  assert.match(source, /rel="noopener noreferrer"/);
  assert.match(source, /compactOfficialText/);
  assert.match(source, /value\.trim\(\)\.length > 0/);
  assert.match(source, /효능·효과/);
  assert.match(source, /용법·용량/);
  assert.match(source, /유효성분/);
});

test("product modal keeps official information in a compact reading layout", async () => {
  const css = await readFile(globalCssUrl, "utf8");
  const shellRule = css.match(/\.modal-shell\s*\{([^}]+)\}/)?.[1] ?? "";
  const groupsRule = css.match(/\.official-detail-groups\s*\{([^}]+)\}/)?.[1] ?? "";
  const itemRule = css.match(/\.official-detail-item\s*\{([^}]+)\}/)?.[1] ?? "";
  const copyRule = css.match(/\.official-detail-item > p, \.official-rich-text p\s*\{([^}]+)\}/)?.[1] ?? "";
  assert.match(shellRule, /width:\s*min\(840px,\s*100%\)/);
  assert.match(groupsRule, /gap:\s*14px/);
  assert.match(itemRule, /padding:\s*17px 18px 19px/);
  assert.match(copyRule, /line-height:\s*1\.7/);
});

test("product modal renders normalized medicine tables as semantic tables", async () => {
  const source = await readFile(productModalUrl, "utf8");
  const css = await readFile(globalCssUrl, "utf8");
  assert.match(source, /OfficialContentValue/);
  assert.match(source, /block\.type === "paragraph"/);
  assert.match(source, /<table>/);
  assert.match(source, /scope="col"/);
  assert.match(source, /scope="row"/);
  assert.match(css, /\.official-table-scroll\s*\{/);
  assert.match(css, /overflow-x:\s*auto/);
});

test("dialogs focus their container and product details align complete rows", async () => {
  const css = await readFile(globalCssUrl, "utf8");
  const productModal = await readFile(productModalUrl, "utf8");
  const exportDialog = await readFile(exportDialogUrl, "utf8");
  const modalGridRule = css.match(/\.modal-grid\s*\{([^}]+)\}/)?.[1] ?? "";
  assert.match(productModal, /tabIndex=\{-1\}/);
  assert.match(productModal, /modalRef\.current\?\.focus\(\{ preventScroll: true \}\)/);
  assert.match(exportDialog, /tabIndex=\{-1\}/);
  assert.match(exportDialog, /dialogRef\.current\?\.focus\(\{ preventScroll: true \}\)/);
  assert.match(modalGridRule, /grid-template-columns:\s*180px minmax\(0, 1fr\)/);
  assert.match(modalGridRule, /align-items:\s*start/);
  assert.match(css, /\.detail-list div:last-child:nth-child\(odd\)\s*\{[^}]*grid-column:\s*1 \/ -1/);
  assert.match(css, /\.detail-list div:nth-last-child\(2\):nth-child\(odd\)\s*\{[^}]*border-bottom:\s*0/);
});

test("catalog uses one compact content width and readable control sizes", async () => {
  const css = await readFile(globalCssUrl, "utf8");
  const rootRule = css.match(/:root\s*\{([^}]+)\}/)?.[1] ?? "";
  const heroRule = css.match(/\.hero\s*\{([^}]+)\}/)?.[1] ?? "";
  const catalogRule = css.match(/\.catalog-section\s*\{([^}]+)\}/)?.[1] ?? "";
  const toolbarControlRule = css.match(/\.search-field,\s*\.sort-field\s*\{([^}]+)\}/)?.[1] ?? "";
  const tableCellRule = css.match(/\.product-table th,\s*\.product-table td\s*\{([^}]+)\}/)?.[1] ?? "";
  assert.match(rootRule, /--content-width:\s*1040px/);
  assert.match(heroRule, /width:\s*min\(var\(--content-width\)/);
  assert.match(catalogRule, /width:\s*min\(var\(--content-width\)/);
  assert.match(toolbarControlRule, /height:\s*50px/);
  assert.match(tableCellRule, /padding:\s*11px 14px/);
});

test("product table passes vertical wheel input to the page", async () => {
  const css = await readFile(globalCssUrl, "utf8");
  const rule = css.match(/\.product-table\s*\{([^}]+)\}/)?.[1] ?? "";
  assert.match(rule, /overscroll-behavior-x:\s*contain/);
  assert.match(rule, /overscroll-behavior-y:\s*auto/);
  assert.doesNotMatch(rule, /overscroll-behavior:\s*contain/);
});

test("product image rejects unverified search previews", async () => {
  const source = await readFile(productImageUrl, "utf8");
  assert.doesNotMatch(source, /"source_preview"/);
  assert.match(source, /"official_source_preview"/);
});

test("generated local catalog keeps every Firestore source field and price", { skip: !existsSync(localCatalogUrl) }, async () => {
  const raw = await readFile(localCatalogUrl, "utf8");
  const products = JSON.parse(raw);
  assert.equal(products.length, 776);
  for (const product of products) {
    assert.equal(product.price_status, "2026-07-15 조회 당시 앱 데이터값");
    assert.equal(typeof product.displayed_price_krw, "number");
    assert.ok(product.displayed_price_krw > 0);
    for (const field of ["id", "name", "capacity", "category", "price", "etc", "updated"]) {
      assert.ok(Object.hasOwn(product, field), `${product.document_id}: ${field} 누락`);
    }
    for (const field of ["duplicate_group_size", "official_match_status", "enrichment_status"]) {
      assert.ok(Object.hasOwn(product, field), `${product.document_id}: ${field} 누락`);
    }
    assert.doesNotMatch(JSON.stringify(product), /G:\\\\내 드라이브/i);
  }
});
