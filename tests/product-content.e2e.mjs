import assert from "node:assert/strict";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const BASE_URL = process.env.BASE_URL || "http://127.0.0.1:3000";
const REPORT_PATH = path.resolve(
  ROOT,
  process.env.CONTENT_BROWSER_REPORT || "etc/text-normalization/product-content-browser-local.json",
);
const CURRENT_PATH = path.resolve(ROOT, "data/enrichment-queue.json");
const MANIFEST_PATH = path.resolve(ROOT, "data/portable/v1/manifest.json");
const DAMAGED_TEXT = /(?:^|[가-힣0-9.!?\]\)])br(?=\s*(?:\n|$))|�|\d\s*\?\s*\d|\[\d+\s*\?\s*[가-힣A-Za-z]/im;

const readJson = async (file) => JSON.parse(await readFile(file, "utf8"));
const keyOf = (product) => String(product.document_id || product.id || "").trim();

async function waitForCount(page, count) {
  await page.waitForFunction((expected) => {
    const text = document.querySelector(".result-bar strong")?.textContent || "";
    return Number(text.replace(/\D/g, "")) === expected;
  }, count);
}

function expectedTableCount(product) {
  return Object.values(product.official_content || {}).reduce((total, section) => {
    if (!section || !Array.isArray(section.blocks)) return total;
    return total + section.blocks.filter((block) => block.type === "table").length;
  }, 0);
}

function expectedTables(product) {
  return Object.values(product.official_content || {}).flatMap((section) => {
    if (!section || !Array.isArray(section.blocks)) return [];
    return section.blocks
      .filter((block) => block.type === "table")
      .map((block) => ({ headers: block.headers, rows: block.rows }));
  });
}

async function verifyProduct(page, search, product) {
  const result = { product_id: keyOf(product), name: product.name, status: "passed", checks: {} };
  try {
    await search.fill(result.product_id);
    await waitForCount(page, 1);
    const row = page.locator(".product-table tbody tr");
    assert.equal(await row.count(), 1);
    await row.locator(".product-name-button").click();
    const dialog = page.getByRole("dialog");
    await dialog.getByRole("heading", { name: product.name, exact: true }).waitFor();
    const visibleText = (await dialog.textContent()) || "";
    assert.doesNotMatch(visibleText, DAMAGED_TEXT);
    result.checks.noDamagedText = true;

    if (product.official_match_status === "confirmed") {
      await dialog.getByRole("heading", { name: "약학정보원 제품 정보", exact: true }).waitFor();
      const canonicalTables = expectedTables(product);
      const renderedTables = await dialog.locator(".official-table-scroll table").evaluateAll((tables) => tables.map((table) => ({
        headers: [...table.querySelectorAll("thead th")].map((cell) => cell.textContent?.trim() || ""),
        rows: [...table.querySelectorAll("tbody tr")].map((row) => [...row.querySelectorAll(":scope > th, :scope > td")].map((cell) => cell.textContent?.trim() || "")),
      })));
      assert.deepEqual(renderedTables, canonicalTables);
      result.checks.structuredContent = {
        sections: Object.values(product.official_content || {}).filter((section) => section?.blocks).length,
        tables: renderedTables.length,
      };
      if (product.official_source_url) {
        const source = dialog.getByRole("link", { name: "약학정보원 제품 원문", exact: true });
        assert.equal(await source.getAttribute("href"), new URL(product.official_source_url).href);
        result.checks.officialSource = true;
      }
    }
    await dialog.getByRole("button", { name: "상품 상세 닫기" }).click();
  } catch (error) {
    result.status = "failed";
    result.error = { message: error.message, stack: error.stack };
    const close = page.getByRole("button", { name: "상품 상세 닫기" });
    if (await close.count()) await close.click({ timeout: 1000 }).catch(() => {});
  }
  return result;
}

async function main() {
  const [products, canonicalManifest] = await Promise.all([
    readJson(CURRENT_PATH),
    readJson(MANIFEST_PATH),
  ]);
  assert.equal(products.length, 776);
  const report = {
    status: "running",
    started_at: new Date().toISOString(),
    config: { base_url: BASE_URL },
    summary: {
      products: products.length,
      confirmed: products.filter((product) => product.official_match_status === "confirmed").length,
      structured: products.filter((product) => product.official_content?.schema_version === "1.0").length,
      expected_tables: products.reduce((total, product) => total + expectedTableCount(product), 0),
    },
    checks: {},
    products: [],
    errors: [],
  };
  let browser;
  try {
    browser = await chromium.launch({ headless: process.env.HEADLESS !== "false" });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    page.setDefaultTimeout(15000);
    await page.goto(BASE_URL, { waitUntil: "domcontentloaded" });
    await waitForCount(page, 776);
    const served = await page.evaluate(async () => {
      const [catalogResponse, productsResponse, manifestResponse] = await Promise.all([
        fetch("/data/enrichment-queue.json", { cache: "no-store" }),
        fetch("/data/portable/v1/products.json", { cache: "no-store" }),
        fetch("/data/portable/v1/manifest.json", { cache: "no-store" }),
      ]);
      const portableBytes = await productsResponse.arrayBuffer();
      const digest = await crypto.subtle.digest("SHA-256", portableBytes);
      const sha256 = [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, "0")).join("");
      return {
        catalog: await catalogResponse.json(),
        manifest: await manifestResponse.json(),
        portableSha256: sha256,
      };
    });
    assert.deepEqual(served.catalog, products);
    assert.equal(served.manifest.product_count, 776);
    assert.equal(served.manifest.files["products.json"].sha256, canonicalManifest.files["products.json"].sha256);
    assert.equal(served.portableSha256, canonicalManifest.files["products.json"].sha256);
    report.checks.servedData = { count: served.catalog.length, portableSha256: served.portableSha256 };

    const search = page.getByRole("searchbox", { name: "상품명, 규격, 분류 또는 비고 검색" });
    for (const [index, product] of products.entries()) {
      const result = await verifyProduct(page, search, product);
      report.products.push(result);
      if (result.status === "failed") report.errors.push({ product_id: result.product_id, ...result.error });
      if ((index + 1) % 25 === 0 || index + 1 === products.length) {
        console.log(`Content QA: ${index + 1}/${products.length}, failures=${report.errors.length}`);
      }
    }
    report.status = report.errors.length ? "failed" : "passed";
  } catch (error) {
    report.status = "failed";
    report.errors.push({ message: error.message, stack: error.stack });
  } finally {
    await browser?.close().catch(() => {});
    report.finished_at = new Date().toISOString();
    report.summary.passed = report.products.filter((product) => product.status === "passed").length;
    report.summary.failed = report.products.filter((product) => product.status === "failed").length;
    await mkdir(path.dirname(REPORT_PATH), { recursive: true });
    await writeFile(REPORT_PATH, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  }
  console.log(JSON.stringify({ report: REPORT_PATH, status: report.status, summary: report.summary, errors: report.errors }, null, 2));
  if (report.status !== "passed") process.exitCode = 1;
}

await main();
