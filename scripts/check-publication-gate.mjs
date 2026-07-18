import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const localBuild = process.env.CATALOG_LOCAL_BUILD === "1";
const publicDeployAcknowledged = process.env.CATALOG_PUBLIC_DEPLOY_ACKNOWLEDGED === "1";

if (!localBuild && !publicDeployAcknowledged) {
  console.error([
    "\n빌드를 중단했습니다: 776개 전체 가격 데이터는 외부 공개 승인을 받지 않았습니다.",
    "로컬 검증 빌드만 필요하면 `npm run build:local`을 사용하세요.",
    "개인용 Vercel 프리뷰는 로그인 보호를 확인한 뒤 `npm run deploy:private`로 배포하세요.",
    "공개 배포 전에는 DATA_POLICY.md의 공개 게이트를 먼저 통과해야 합니다.\n",
  ].join("\n"));
  process.exit(1);
}

if (publicDeployAcknowledged) {
  const root = process.cwd();
  const [approval, canonicalBytes, portableManifest] = await Promise.all([
    readFile(resolve(root, "data/publication-approval.json"), "utf8").then(JSON.parse),
    readFile(resolve(root, "data/enrichment-queue.json")),
    readFile(resolve(root, "data/portable/v1/manifest.json"), "utf8").then(JSON.parse),
  ]);
  const canonicalSha256 = createHash("sha256").update(canonicalBytes).digest("hex");
  const portableSha256 = portableManifest?.files?.["products.json"]?.sha256;
  const valid = approval?.approved === true
    && approval?.scope === "production"
    && approval?.product_count === 776
    && approval?.public_url === "https://pharmacy-product-catalog.vercel.app/"
    && approval?.canonical_sha256 === canonicalSha256
    && approval?.portable_products_sha256 === portableSha256;
  if (!valid) {
    console.error("빌드를 중단했습니다: 프로덕션 승인 기록이 현재 정식 데이터와 일치하지 않습니다.");
    process.exit(1);
  }
}
