param(
    [int]$Threads = 7,
    [string]$MemoryLimit = "32GB"
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

uv run expedia-analytics --threads $Threads --memory-limit $MemoryLimit build
if ($LASTEXITCODE -ne 0) { throw "analytics build failed" }

uv run expedia-analytics validate
if ($LASTEXITCODE -ne 0) { throw "analytics validation failed" }

uv run expedia-analytics inspect
Write-Host "[product-analytics] database: data\analytics\expedia_analytics.duckdb"
Write-Host "[product-analytics] parquet marts: data\marts"
Write-Host "[product-analytics] manifest: artifacts\analytics\build_manifest.json"
