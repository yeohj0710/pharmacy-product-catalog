// Runs `npm run catalog:sync` only when its inputs/outputs changed since the
// last successful run. The full chain (4 Python checks + public sync) costs
// several cold Python starts per `npm run dev`/`build`; when nothing relevant
// changed it is pure overhead. Cache lives in node_modules/.cache, so fresh
// clones and CI/Vercel always run the real thing. Force with `npm run catalog:sync`.
import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { mkdirSync, readFileSync, statSync, writeFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const cacheFile = join(root, "node_modules", ".cache", "catalog-sync-fingerprint.json");

const trackedFiles = [
  "package.json",
  "data/enrichment-queue.json",
  "data/enrichment-queue.csv",
  "data/catalog-text-corrections.json",
  "lib/catalog_text_normalization.py",
  "scripts/apply_catalog_text_corrections.py",
  "scripts/normalize_catalog_content.py",
  "scripts/audit_catalog_text.py",
  "scripts/export_portable_catalog.py",
  "scripts/sync-public-catalog.mjs",
];
const trackedDirs = ["data/portable/v1", "public/data"];

function listDir(dir) {
  const out = [];
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return out;
  }
  for (const entry of entries) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) out.push(...listDir(path));
    else out.push(path);
  }
  return out;
}

function fingerprint() {
  const files = [
    ...trackedFiles.map((f) => join(root, f)),
    ...trackedDirs.flatMap((d) => listDir(join(root, d))),
  ].sort();
  const hash = createHash("sha256");
  for (const file of files) {
    let stat;
    try {
      stat = statSync(file);
    } catch {
      hash.update(`${file}|missing\n`);
      continue;
    }
    hash.update(`${file}|${stat.size}|${stat.mtimeMs}\n`);
  }
  return hash.digest("hex");
}

const before = fingerprint();
let cached = null;
try {
  cached = JSON.parse(readFileSync(cacheFile, "utf8")).fingerprint;
} catch {}

if (cached === before) {
  console.log("[catalog:sync] inputs unchanged - skipped (force with `npm run catalog:sync`)");
  process.exit(0);
}

const result = spawnSync("npm run catalog:sync", {
  cwd: root,
  stdio: "inherit",
  shell: true,
});
if (result.status !== 0) process.exit(result.status ?? 1);

mkdirSync(dirname(cacheFile), { recursive: true });
writeFileSync(cacheFile, JSON.stringify({ fingerprint: fingerprint() }));
