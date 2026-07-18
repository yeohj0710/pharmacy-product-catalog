import assert from "node:assert/strict";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const EXPECTED_PRODUCT_COUNT = 776;
const IMAGE_FIELDS = ["image_url", "image_source_url", "image_rights_status", "image_kind", "image_checked_at"];
const BASE_URL = process.env.BASE_URL || "http://127.0.0.1:3000";
const BASELINE_PATH = path.resolve(ROOT, process.env.BASELINE_JSON || "etc/image-research/backups/enrichment-queue.start.json");
const CURRENT_PATH = path.resolve(ROOT, "data/enrichment-queue.json");
const CORRECTIONS_PATH = path.resolve(ROOT, "data/catalog-text-corrections.json");
const OFFICIAL_REVIEW_PATHS = [
  "etc/image-research/official-rematch-review-001-200.json",
  "etc/image-research/official-rematch-review-201-400.json",
  "etc/image-research/official-rematch-review-401-600.json",
  "etc/image-research/official-rematch-review-601-776.json",
].map((file) => path.resolve(ROOT, file));
const REPORT_PATH = path.resolve(ROOT, process.env.IMAGE_BROWSER_REPORT || "etc/image-research/image-browser-report.json");

const hasText = (value) => typeof value === "string" && value.trim().length > 0;
const keyOf = (product) => String(product.document_id || product.id || "").trim();
const readJson = async (file) => JSON.parse(await readFile(file, "utf8"));

function webUrl(value) {
  if (!hasText(value)) return "";
  try {
    const parsed = new URL(value);
    return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : "";
  } catch {
    return "";
  }
}

async function waitForCount(page, count) {
  await page.waitForFunction((expected) => {
    const text = document.querySelector(".result-bar strong")?.textContent || "";
    return Number(text.replace(/\D/g, "")) === expected;
  }, count);
}

async function loadedImage(locator) {
  await locator.waitFor({ state: "visible" });
  return locator.evaluate((image) => new Promise((resolve, reject) => {
    const finish = () => {
      if (image.naturalWidth > 0 && image.naturalHeight > 0) {
        resolve({ currentSrc: image.currentSrc, naturalWidth: image.naturalWidth, naturalHeight: image.naturalHeight });
      } else reject(new Error(`Image failed to load: ${image.currentSrc || image.src}`));
    };
    if (image.complete) return finish();
    const timer = setTimeout(() => reject(new Error(`Timed out loading image: ${image.src}`)), 15000);
    image.addEventListener("load", () => { clearTimeout(timer); finish(); }, { once: true });
    image.addEventListener("error", () => { clearTimeout(timer); reject(new Error(`Image failed to load: ${image.src}`)); }, { once: true });
  }));
}

async function requiredImage(container) {
  return Promise.race([
    loadedImage(container.locator("img")),
    container.locator(".product-image-fallback").waitFor({ state: "visible" }).then(() => {
      throw new Error("The product image was replaced by the browser fallback");
    }),
  ]);
}

async function setImageFilter(page, value, expected) {
  await page.locator(".toolbar-actions .toolbar-button").first().click();
  const panel = page.locator(".filter-panel");
  await panel.getByText("상품 필터", { exact: true }).waitFor();
  await panel.locator(".filter-selects select").nth(2).selectOption(value);
  await panel.getByRole("button", { name: "필터 적용", exact: true }).click();
  await waitForCount(page, expected);
}

async function setOfficialFilter(page, value, expected) {
  await page.locator(".toolbar-actions .toolbar-button").first().click();
  const panel = page.locator(".filter-panel");
  await panel.waitFor({ state: "visible" });
  await panel.locator(".filter-selects select").nth(1).selectOption(value);
  await panel.getByRole("button", { name: "필터 적용", exact: true }).click();
  await waitForCount(page, expected);
}

async function verifyPages(page) {
  await page.getByLabel("페이지당 상품 수").selectOption("100");
  const counts = [];
  for (let pageNumber = 1; pageNumber <= 8; pageNumber += 1) {
    await page.locator(`button[aria-label='${pageNumber}페이지'][aria-current='page']`).waitFor();
    counts.push(await page.locator(".product-table tbody tr").count());
    if (pageNumber < 8) await page.getByRole("button", { name: "다음 페이지" }).click();
  }
  assert.deepEqual(counts, [100, 100, 100, 100, 100, 100, 100, 76]);
  return counts;
}

async function verifyProduct(page, search, product) {
  const result = { key: keyOf(product), name: product.name, status: "passed", checks: {} };
  try {
    await search.fill(result.key);
    await waitForCount(page, 1);
    const row = page.locator(".product-table tbody tr");
    assert.equal(await row.count(), 1);
    assert.equal((await row.locator(".product-name-button > span > strong").textContent())?.trim(), product.name);
    assert.equal((await row.locator("td").nth(1).textContent())?.trim(), product.capacity || product.specification || "미입력");

    if (hasText(product.image_url)) {
      result.checks.thumbnail = await requiredImage(row.locator(".product-name-button"));
    } else {
      assert.equal(await row.locator(".product-image img").count(), 0);
      assert.equal(await row.locator(".product-image-fallback").count(), 1);
      result.checks.thumbnailFallback = true;
    }

    await row.locator(".product-name-button").click();
    const dialog = page.getByRole("dialog");
    await dialog.getByRole("heading", { name: product.name, exact: true }).waitFor();
    assert.equal((await dialog.locator(".modal-spec").textContent())?.trim(), product.capacity || product.specification || "규격 미입력");
    if (hasText(product.image_url)) {
      result.checks.modalImage = await requiredImage(dialog);
    } else {
      assert.equal(await dialog.locator(".product-image.large img").count(), 0);
      assert.equal(await dialog.locator(".product-image-fallback.large").count(), 1);
      result.checks.modalFallback = true;
    }

    for (const [label, url] of [
      ["약학정보원 제품 원문", webUrl(product.official_source_url)],
      ["제품 이미지 출처", webUrl(product.image_source_url)],
    ]) {
      if (!url || (label === "제품 이미지 출처" && url === webUrl(product.official_source_url))) continue;
      const link = dialog.getByRole("link", { name: label, exact: true });
      assert.equal(await link.getAttribute("href"), url);
      await link.click({ trial: true });
      result.checks[label] = url;
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
  const [baseline, current, corrections, ...officialReviewParts] = await Promise.all([
    readJson(BASELINE_PATH),
    readJson(CURRENT_PATH),
    readJson(CORRECTIONS_PATH),
    ...OFFICIAL_REVIEW_PATHS.map(readJson),
  ]);
  assert.equal(current.length, EXPECTED_PRODUCT_COUNT);
  const baselineByKey = new Map(baseline.map((product) => [keyOf(product), product]));
  const correctedKeys = new Set(corrections.filter((row) => row.approved).map(keyOf));
  const officiallyReviewedKeys = new Set(officialReviewParts.flat().map(keyOf));
  const changed = current.filter((product) =>
    correctedKeys.has(keyOf(product))
    || officiallyReviewedKeys.has(keyOf(product))
    || IMAGE_FIELDS.some((field) => product[field] !== baselineByKey.get(keyOf(product))?.[field]));
  const withImages = current.filter((product) => hasText(product.image_url)).length;
  const report = {
    status: "running",
    startedAt: new Date().toISOString(),
    config: { baseUrl: BASE_URL, baselinePath: BASELINE_PATH, currentPath: CURRENT_PATH, reportPath: REPORT_PATH },
    summary: { currentProducts: current.length, correctedProducts: correctedKeys.size, officiallyReviewedProducts: officiallyReviewedKeys.size, changedProducts: changed.length, changedWithImages: changed.filter((p) => hasText(p.image_url)).length, changedWithoutImages: changed.filter((p) => !hasText(p.image_url)).length, withImages, withoutImages: current.length - withImages },
    checks: {}, products: [], errors: [],
  };
  let browser;
  try {
    browser = await chromium.launch({ headless: process.env.HEADLESS !== "false" });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    page.setDefaultTimeout(15000);
    await page.goto(BASE_URL, { waitUntil: "domcontentloaded" });
    await waitForCount(page, EXPECTED_PRODUCT_COUNT);
    const browserData = await page.evaluate(async () => (await fetch("/data/enrichment-queue.json", { cache: "no-store" })).json());
    assert.deepEqual(browserData, current);
    report.checks.browserData = { count: browserData.length, matchesCurrentData: true };
    report.checks.pageCounts = await verifyPages(page);
    const officialCounts = Object.fromEntries(
      ["confirmed", "not_found", "not_applicable", "review_required"]
        .map((status) => [status, current.filter((product) => product.official_match_status === status).length]),
    );
    for (const [status, count] of Object.entries(officialCounts)) await setOfficialFilter(page, status, count);
    await setOfficialFilter(page, "all", current.length);
    report.checks.officialFilters = { all: current.length, ...officialCounts };
    await setImageFilter(page, "with", withImages);
    await setImageFilter(page, "without", current.length - withImages);
    await setImageFilter(page, "all", current.length);
    report.checks.imageFilters = { all: current.length, with: withImages, without: current.length - withImages };
    const search = page.getByRole("searchbox", { name: "상품명, 규격, 분류 또는 비고 검색" });
    for (const [index, product] of changed.entries()) {
      const result = await verifyProduct(page, search, product);
      report.products.push(result);
      if (result.status === "failed") report.errors.push({ key: result.key, ...result.error });
      if ((index + 1) % 25 === 0 || index + 1 === changed.length) {
        console.log(`Browser QA: ${index + 1}/${changed.length}, failures=${report.errors.length}`);
      }
    }
    report.status = report.errors.length ? "failed" : "passed";
  } catch (error) {
    report.status = "failed";
    report.errors.push({ message: error.message, stack: error.stack });
  } finally {
    await browser?.close().catch(() => {});
    report.completedAt = new Date().toISOString();
    report.summary.passedProducts = report.products.filter((p) => p.status === "passed").length;
    report.summary.failedProducts = report.products.filter((p) => p.status === "failed").length;
    await mkdir(path.dirname(REPORT_PATH), { recursive: true });
    await writeFile(REPORT_PATH, `${JSON.stringify(report, null, 2)}\n`, "utf8");
    console.log(JSON.stringify({ report: REPORT_PATH, status: report.status, summary: report.summary, errors: report.errors.slice(0, 5) }, null, 2));
  }
  if (report.status !== "passed") process.exitCode = 1;
}

await main();
process.exit(process.exitCode || 0);
