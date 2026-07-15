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

test("renders the Korean catalog shell and historical-price notice", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /<html lang="ko">/);
  assert.match(html, /약국 상품 아카이브/);
  assert.match(html, /현재 판매가나 재고가 아닙니다/);
  assert.match(html, /메가팩토리약국.*제휴·승인 관계가 없는/);
  assert.doesNotMatch(html, /codex-preview|SkeletonPreview|Your site is taking shape/);
});

test("renders the data policy with source and publication limits", async () => {
  const response = await render("/data-policy");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /데이터 보존·공개 기준/);
  assert.match(html, /현재 판매가, 현재 재고 또는 구매 가능 여부/);
  assert.match(html, /전체 데이터의 외부 공개, 공개 API 제공 또는 상업적 이용 전/);
  assert.match(html, /data\.go\.kr\/data\/15075057/);
});

const localCatalogUrl = new URL("../public/data/products.json", import.meta.url);

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
    assert.doesNotMatch(JSON.stringify(product), /G:\\\\내 드라이브/i);
  }
});
