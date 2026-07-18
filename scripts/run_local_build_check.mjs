import { spawnSync } from "node:child_process";
import { statSync } from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const startedAt = Date.now();
const npm = process.platform === "win32" ? "npm.cmd" : "npm";
const result = spawnSync(npm, ["run", "build"], {
  cwd: root,
  env: process.env,
  stdio: "inherit",
  shell: process.platform === "win32",
});

if (result.status === 0) process.exit(0);

const expectedArtifacts = ["dist/server/index.js", "dist/client/.vite/manifest.json"];
const freshArtifacts = expectedArtifacts.every((relativePath) => {
  try {
    return statSync(path.join(root, relativePath)).mtimeMs >= startedAt - 2_000;
  } catch {
    return false;
  }
});
const windowsLibuvAssertion = process.platform === "win32" && [3221226505, -1073740791].includes(result.status);

if (windowsLibuvAssertion && freshArtifacts) {
  console.warn("vinext completed and wrote fresh build artifacts; ignored the known Windows libuv shutdown assertion.");
  process.exit(0);
}

if (result.error) console.error(result.error);
process.exit(result.status ?? 1);
