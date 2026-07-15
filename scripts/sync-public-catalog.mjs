import { copyFile, mkdir, readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const sourceJson = resolve(root, "data/enrichment-queue.json");
const sourceCsv = resolve(root, "data/enrichment-queue.csv");
const publicDirectory = resolve(root, "public/data");
const publicJson = resolve(publicDirectory, "enrichment-queue.json");
const publicCsv = resolve(publicDirectory, "enrichment-queue.csv");

const products = JSON.parse(await readFile(sourceJson, "utf8"));
if (!Array.isArray(products) || products.length === 0) {
  throw new Error("data/enrichment-queue.json에 상품이 없습니다.");
}
for (const product of products) {
  if (!product || typeof product !== "object" || !product.id || !product.name) {
    throw new Error("공개용 데이터에 id 또는 name이 없는 상품이 있습니다.");
  }
}

await mkdir(publicDirectory, { recursive: true });
await Promise.all([
  copyFile(sourceJson, publicJson),
  copyFile(sourceCsv, publicCsv),
]);

console.log(`공개용 상품 데이터 ${products.length}개를 public/data에 준비했습니다.`);
