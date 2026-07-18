param([switch]$Production)

$ErrorActionPreference = "Stop"

$root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$workRoot = [System.IO.Path]::GetFullPath((Join-Path $root "etc\health-enrichment"))
$runId = [Guid]::NewGuid().ToString("N")
$stage = [System.IO.Path]::GetFullPath((Join-Path $workRoot "private-deploy-$runId"))
$archive = [System.IO.Path]::GetFullPath((Join-Path $workRoot "private-deploy-$runId.zip"))
$jsonSource = Join-Path $root "data\enrichment-queue.json"
$csvSource = Join-Path $root "data\enrichment-queue.csv"
$publicDataSource = Join-Path $root "public\data"
$publicJsonSource = Join-Path $publicDataSource "enrichment-queue.json"
$publicCsvSource = Join-Path $publicDataSource "enrichment-queue.csv"
$portableDataSource = Join-Path $root "data\portable\v1"
$portablePublicSource = Join-Path $publicDataSource "portable\v1"
$publicationApprovalSource = Join-Path $root "data\publication-approval.json"
$projectLink = Join-Path $root ".vercel\project.json"
$approvedCodeOverlays = @(
    "app\catalog-client.tsx",
    "app\data-policy\page.tsx",
    "app\globals.css",
    "components\catalog\ActiveFilterChips.tsx",
    "components\catalog\ExportDialog.tsx",
    "components\catalog\FilterPanel.tsx",
    "components\catalog\ProductImage.tsx",
    "components\catalog\ProductModal.tsx",
    "data\catalog-text-corrections.json",
    "data\publication-approval.json",
    "hooks\use-catalog-state.ts",
    "lib\catalog\catalog.ts",
    "lib\catalog\text.ts",
    "lib\catalog_text_normalization.py",
    "package.json",
    "package-lock.json",
    "scripts\check-publication-gate.mjs",
    "scripts\apply_catalog_text_corrections.py",
    "scripts\audit_catalog_text.py",
    "scripts\export_portable_catalog.py",
    "scripts\normalize_catalog_content.py",
    "scripts\sync-public-catalog.mjs",
    "types\catalog.ts"
)
$stablePreviewAlias = "pharmacy-product-catalog-yeohj0710-yeohj0710s-projects.vercel.app"
$shortPreviewAlias = "pharmacy-archive-yeohj.vercel.app"

function Assert-PrivateDeployPath([string]$Path) {
    $full = [System.IO.Path]::GetFullPath($Path)
    if (-not $full.StartsWith($workRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Private deployment path is outside the allowed work directory: $full"
    }
}

foreach ($path in @($jsonSource, $csvSource, $publicJsonSource, $publicCsvSource, $portableDataSource, $portablePublicSource, $projectLink) + ($approvedCodeOverlays | ForEach-Object { Join-Path $root $_ })) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Required private deployment file is missing: $path"
    }
}

$products = Get-Content -LiteralPath $jsonSource -Encoding UTF8 -Raw | ConvertFrom-Json
if ($products.Count -ne 776) {
    throw "Product JSON must contain 776 rows. Actual: $($products.Count)"
}

if ($Production) {
    if (-not (Test-Path -LiteralPath $publicationApprovalSource)) {
        throw "Production publication approval is missing: $publicationApprovalSource"
    }
    $approval = Get-Content -LiteralPath $publicationApprovalSource -Encoding UTF8 -Raw | ConvertFrom-Json
    $canonicalHash = (Get-FileHash -LiteralPath $jsonSource -Algorithm SHA256).Hash.ToLowerInvariant()
    $portableManifest = Get-Content -LiteralPath (Join-Path $portableDataSource "manifest.json") -Encoding UTF8 -Raw | ConvertFrom-Json
    if (
        $approval.approved -ne $true -or
        $approval.scope -ne "production" -or
        $approval.product_count -ne 776 -or
        $approval.public_url -ne "https://pharmacy-product-catalog.vercel.app/" -or
        $approval.canonical_sha256 -ne $canonicalHash -or
        $approval.portable_products_sha256 -ne $portableManifest.files.'products.json'.sha256
    ) {
        throw "Production publication approval does not match the current canonical and portable data."
    }
}

Assert-PrivateDeployPath $stage
Assert-PrivateDeployPath $archive
New-Item -ItemType Directory -Force -Path $workRoot | Out-Null

try {
    & git -C $root archive --format=zip "--output=$archive" HEAD
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create a deployment copy from the current Git commit."
    }

    Expand-Archive -LiteralPath $archive -DestinationPath $stage
    New-Item -ItemType Directory -Force -Path (Join-Path $stage ".vercel") | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $stage "data") | Out-Null
    Copy-Item -LiteralPath $projectLink -Destination (Join-Path $stage ".vercel\project.json")
    Copy-Item -LiteralPath $jsonSource -Destination (Join-Path $stage "data\enrichment-queue.json")
    Copy-Item -LiteralPath $csvSource -Destination (Join-Path $stage "data\enrichment-queue.csv")
    New-Item -ItemType Directory -Force -Path (Join-Path $stage "data\portable") | Out-Null
    Copy-Item -LiteralPath $portableDataSource -Destination (Join-Path $stage "data\portable\v1") -Recurse
    $stagePublicData = Join-Path $stage "public\data"
    if (Test-Path -LiteralPath $stagePublicData) {
        Remove-Item -LiteralPath $stagePublicData -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path (Split-Path $stagePublicData -Parent) | Out-Null
    New-Item -ItemType Directory -Force -Path $stagePublicData | Out-Null
    Copy-Item -LiteralPath $publicJsonSource -Destination (Join-Path $stagePublicData "enrichment-queue.json")
    Copy-Item -LiteralPath $publicCsvSource -Destination (Join-Path $stagePublicData "enrichment-queue.csv")
    New-Item -ItemType Directory -Force -Path (Join-Path $stagePublicData "portable") | Out-Null
    Copy-Item -LiteralPath $portablePublicSource -Destination (Join-Path $stagePublicData "portable\v1") -Recurse
    foreach ($relativePath in $approvedCodeOverlays) {
        $source = Join-Path $root $relativePath
        $destination = Join-Path $stage $relativePath
        New-Item -ItemType Directory -Force -Path (Split-Path $destination -Parent) | Out-Null
        Copy-Item -LiteralPath $source -Destination $destination
    }

    $sourceHash = (Get-FileHash -LiteralPath $jsonSource -Algorithm SHA256).Hash
    $stageHash = (Get-FileHash -LiteralPath (Join-Path $stage "data\enrichment-queue.json") -Algorithm SHA256).Hash
    if ($sourceHash -ne $stageHash) {
        throw "Staged JSON does not match the canonical JSON."
    }
    $publicHash = (Get-FileHash -LiteralPath (Join-Path $stagePublicData "enrichment-queue.json") -Algorithm SHA256).Hash
    if ($sourceHash -ne $publicHash) {
        throw "Staged public JSON does not match the canonical JSON. Run npm run catalog:sync first."
    }

    if ($Production) {
        Push-Location $stage
        try {
            $env:CATALOG_PUBLIC_DEPLOY_ACKNOWLEDGED = "1"
            & node scripts/check-publication-gate.mjs
            if ($LASTEXITCODE -ne 0) {
                throw "Staged production publication gate failed."
            }
            & python scripts/export_portable_catalog.py --check
            if ($LASTEXITCODE -ne 0) {
                throw "Staged portable package check failed."
            }
        }
        finally {
            Remove-Item Env:CATALOG_PUBLIC_DEPLOY_ACKNOWLEDGED -ErrorAction SilentlyContinue
            Pop-Location
        }
    }

    if ($Production) {
        Write-Host "Deploying public production with 776 products. JSON SHA-256: $($sourceHash.ToLowerInvariant())"
        & npx.cmd --yes vercel@56.2.1 deploy $stage --prod --build-env "CATALOG_PUBLIC_DEPLOY_ACKNOWLEDGED=1" --yes
    }
    else {
        Write-Host "Deploying private preview with 776 products. JSON SHA-256: $($sourceHash.ToLowerInvariant())"
        & npx.cmd --yes vercel@56.2.1 deploy $stage --build-env "CATALOG_LOCAL_BUILD=1" --yes
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Vercel deployment failed."
    }

    if (-not $Production) {
        & npx.cmd --yes vercel@56.2.1 alias set $stablePreviewAlias $shortPreviewAlias
        if ($LASTEXITCODE -ne 0) {
            throw "Could not update the short private preview alias."
        }
    }
}
finally {
    foreach ($path in @($stage, $archive)) {
        Assert-PrivateDeployPath $path
        if (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Recurse -Force
        }
    }
}
