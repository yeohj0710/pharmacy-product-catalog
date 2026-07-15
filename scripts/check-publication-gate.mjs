if (process.env.CATALOG_LOCAL_BUILD !== "1") {
  console.error([
    "\n빌드를 중단했습니다: 776개 전체 가격 데이터는 외부 공개 승인을 받지 않았습니다.",
    "로컬 검증 빌드만 필요하면 `npm run build:local`을 사용하세요.",
    "공개 배포 전에는 DATA_POLICY.md의 공개 게이트를 먼저 통과해야 합니다.\n",
  ].join("\n"));
  process.exit(1);
}
