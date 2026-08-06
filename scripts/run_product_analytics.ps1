param(
    [int]$Threads = 7,
    [string]$MemoryLimit = "32GB",
    [switch]$SkipLegacyReconciliation,
    [switch]$SkipProfile
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

Write-Host "[product-analytics] project: $ProjectRoot"
Write-Host "[product-analytics] branch: $(git branch --show-current)"
Write-Host "[product-analytics] syncing locked environment"
uv sync --frozen --group dev
if ($LASTEXITCODE -ne 0) { throw "uv sync failed" }

Write-Host "[product-analytics] static checks"
uv run ruff check .
if ($LASTEXITCODE -ne 0) { throw "ruff failed" }
uv run pytest
if ($LASTEXITCODE -ne 0) { throw "pytest failed" }

if (-not $SkipLegacyReconciliation) {
    if ((Test-Path ".\data\processed\train.parquet") -and
        (Test-Path ".\data\processed\destinations.parquet")) {
        Write-Host "[product-analytics] reconciling legacy prepared sources"
        uv run expedia-analytics --threads $Threads --memory-limit $MemoryLimit reconcile-sources
        if ($LASTEXITCODE -ne 0) { throw "legacy source reconciliation failed" }
    } else {
        Write-Host "[product-analytics] legacy Parquet is absent; final build uses raw CSV directly"
    }
}

if (-not $SkipProfile) {
    if ((Test-Path ".\data\processed\train.parquet") -and
        (Test-Path ".\data\processed\destinations.parquet")) {
        Write-Host "[product-analytics] deep source profile"
        uv run expedia-analytics --threads $Threads --memory-limit $MemoryLimit profile --deep
        if ($LASTEXITCODE -ne 0) { throw "source profile failed" }
    }
}

$BuildId = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
Write-Host "[product-analytics] immutable final build: $BuildId"
uv run expedia-analytics --threads $Threads --memory-limit $MemoryLimit `
    build-final --build-id $BuildId
if ($LASTEXITCODE -ne 0) { throw "final analytics build failed" }

Write-Host "[product-analytics] validating latest build"
uv run expedia-analytics validate-final
if ($LASTEXITCODE -ne 0) { throw "final analytics validation failed" }

Write-Host "[product-analytics] object registry"
uv run expedia-analytics inspect-final
if ($LASTEXITCODE -ne 0) { throw "final analytics inspection failed" }

Write-Host "[product-analytics] completed"
Write-Host "[product-analytics] build id: $BuildId"
Write-Host "[product-analytics] pointer: data\analytics\LATEST_BUILD.json"
Write-Host "[product-analytics] database: data\analytics\$BuildId\expedia_analytics.duckdb"
Write-Host "[product-analytics] marts: data\marts\$BuildId"
Write-Host "[product-analytics] manifest: artifacts\analytics\$BuildId\build_manifest.json"
