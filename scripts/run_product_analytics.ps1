param(
    [int]$Threads = 7,
    [string]$MemoryLimit = "32GB",
    [switch]$BuildMarts
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

Write-Host "[product-analytics] project: $ProjectRoot"
Write-Host "[product-analytics] branch: $(git branch --show-current)"

uv sync --group dev
if ($LASTEXITCODE -ne 0) { throw "uv sync failed" }

if (-not (Test-Path ".\data\processed\train.parquet")) {
    Write-Host "[product-analytics] prepared train parquet is missing; running prepare"
    uv run expedia-recsys --threads $Threads --memory-limit $MemoryLimit prepare
    if ($LASTEXITCODE -ne 0) { throw "source preparation failed" }
}

uv run ruff check .
if ($LASTEXITCODE -ne 0) { throw "ruff failed" }

uv run pytest
if ($LASTEXITCODE -ne 0) { throw "pytest failed" }

Write-Host "[product-analytics] reconciling raw CSV and prepared Parquet"
uv run expedia-analytics --threads $Threads --memory-limit $MemoryLimit reconcile-sources
if ($LASTEXITCODE -ne 0) { throw "source reconciliation failed" }

Write-Host "[product-analytics] profiling full sources before freezing mart semantics"
uv run expedia-analytics --threads $Threads --memory-limit $MemoryLimit profile --deep
if ($LASTEXITCODE -ne 0) { throw "source profiling failed" }

Write-Host "[product-analytics] reconciliation: artifacts\analytics\source_reconciliation.json"
Write-Host "[product-analytics] source profile: artifacts\analytics\source_profile.json"
Write-Host "[product-analytics] source profile summary: artifacts\analytics\source_profile.md"

if (-not $BuildMarts) {
    Write-Host "[product-analytics] source-audit phase complete"
    Write-Host "[product-analytics] marts were not built because their semantics are still under audit"
    Write-Host "[product-analytics] rerun with -BuildMarts only after the profile is reviewed"
    exit 0
}

uv run expedia-analytics --threads $Threads --memory-limit $MemoryLimit build
if ($LASTEXITCODE -ne 0) { throw "analytics build failed" }

uv run expedia-analytics validate
if ($LASTEXITCODE -ne 0) { throw "analytics validation failed" }

uv run expedia-analytics inspect
Write-Host "[product-analytics] database: data\analytics\expedia_analytics.duckdb"
Write-Host "[product-analytics] parquet marts: data\marts"
Write-Host "[product-analytics] manifest: artifacts\analytics\build_manifest.json"
