param(
    [int]$Threads = 0,
    [string]$MemoryLimit = "auto",
    [switch]$SkipLegacyReconciliation,
    [switch]$SkipProfile,
    [switch]$ResumeLatest,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

function Get-GitChanges {
    return @(git status --porcelain)
}

function Repair-GeneratedUvLock {
    $Changes = @(Get-GitChanges)
    if ($Changes.Count -eq 1 -and $Changes[0] -match 'uv\.lock$') {
        Write-Host "[product-analytics] restoring generated uv.lock drift"
        git restore --source=HEAD --staged --worktree -- uv.lock
        if ($LASTEXITCODE -ne 0) { throw "failed to restore uv.lock" }
    }
}

function Assert-CleanWorkingTree {
    $Changes = @(Get-GitChanges)
    if ($Changes.Count -gt 0) {
        Write-Host "[product-analytics] dirty working tree:" -ForegroundColor Red
        $Changes | ForEach-Object { Write-Host $_ -ForegroundColor Red }
        throw "working tree must be clean before validation or build"
    }
}

try {
    $ComputerSystem = Get-CimInstance Win32_ComputerSystem
    $LogicalProcessors = [int]$ComputerSystem.NumberOfLogicalProcessors
    $TotalMemoryGB = [int][Math]::Floor(
        [double]$ComputerSystem.TotalPhysicalMemory / 1GB
    )
} catch {
    $LogicalProcessors = [Environment]::ProcessorCount
    $TotalMemoryGB = 32
}

if ($Threads -le 0) {
    $Threads = [Math]::Max(1, $LogicalProcessors)
}

if ($MemoryLimit.Trim().ToLowerInvariant() -eq "auto") {
    $ReservedMemoryGB = [Math]::Max(
        4,
        [int][Math]::Ceiling($TotalMemoryGB * 0.20)
    )
    $DuckDBMemoryGB = [Math]::Max(4, $TotalMemoryGB - $ReservedMemoryGB)
    $MemoryLimit = "${DuckDBMemoryGB}GB"
}

Write-Host "[product-analytics] project: $ProjectRoot"
Write-Host "[product-analytics] branch: $(git branch --show-current)"
Write-Host "[product-analytics] logical processors: $LogicalProcessors"
Write-Host "[product-analytics] physical memory: ${TotalMemoryGB}GB"
Write-Host "[product-analytics] DuckDB threads: $Threads"
Write-Host "[product-analytics] DuckDB memory limit: $MemoryLimit"

Repair-GeneratedUvLock
Assert-CleanWorkingTree

Write-Host "[product-analytics] syncing locked environment"
uv sync --frozen --group dev
if ($LASTEXITCODE -ne 0) { throw "uv sync failed" }

Write-Host "[product-analytics] static checks"
uv run --frozen ruff check .
if ($LASTEXITCODE -ne 0) { throw "ruff failed" }

if (-not $SkipTests) {
    uv run --frozen pytest
    if ($LASTEXITCODE -ne 0) { throw "pytest failed" }
}

Repair-GeneratedUvLock
Assert-CleanWorkingTree

if ($ResumeLatest) {
    Write-Host "[product-analytics] resuming latest successful build"
    uv run --frozen expedia-analytics validate-final
    if ($LASTEXITCODE -ne 0) { throw "final analytics validation failed" }

    Write-Host "[product-analytics] object registry"
    uv run --frozen expedia-analytics inspect-final
    if ($LASTEXITCODE -ne 0) { throw "final analytics inspection failed" }

    Repair-GeneratedUvLock
    Assert-CleanWorkingTree

    $Latest = Get-Content ".\data\analytics\LATEST_BUILD.json" | ConvertFrom-Json
    Write-Host "[product-analytics] completed without rebuilding"
    Write-Host "[product-analytics] build id: $($Latest.build_id)"
    Write-Host "[product-analytics] database: $($Latest.database)"
    Write-Host "[product-analytics] marts: $($Latest.marts)"
    Write-Host "[product-analytics] manifest: $($Latest.manifest)"
    exit 0
}

if (-not $SkipLegacyReconciliation) {
    if ((Test-Path ".\data\processed\train.parquet") -and
        (Test-Path ".\data\processed\destinations.parquet")) {
        Write-Host "[product-analytics] reconciling legacy prepared sources"
        uv run --frozen expedia-analytics --threads $Threads --memory-limit $MemoryLimit reconcile-sources
        if ($LASTEXITCODE -ne 0) { throw "legacy source reconciliation failed" }
    } else {
        Write-Host "[product-analytics] legacy Parquet is absent; final build uses raw CSV directly"
    }
}

if (-not $SkipProfile) {
    if ((Test-Path ".\data\processed\train.parquet") -and
        (Test-Path ".\data\processed\destinations.parquet")) {
        Write-Host "[product-analytics] deep source profile"
        uv run --frozen expedia-analytics --threads $Threads --memory-limit $MemoryLimit profile --deep
        if ($LASTEXITCODE -ne 0) { throw "source profile failed" }
    }
}

Repair-GeneratedUvLock
Assert-CleanWorkingTree

$BuildId = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
Write-Host "[product-analytics] immutable final build: $BuildId"
uv run --frozen expedia-analytics --threads $Threads --memory-limit $MemoryLimit `
    build-final --build-id $BuildId
if ($LASTEXITCODE -ne 0) { throw "final analytics build failed" }

Write-Host "[product-analytics] validating latest build"
uv run --frozen expedia-analytics validate-final
if ($LASTEXITCODE -ne 0) { throw "final analytics validation failed" }

Write-Host "[product-analytics] object registry"
uv run --frozen expedia-analytics inspect-final
if ($LASTEXITCODE -ne 0) { throw "final analytics inspection failed" }

Repair-GeneratedUvLock
Assert-CleanWorkingTree

Write-Host "[product-analytics] completed"
Write-Host "[product-analytics] build id: $BuildId"
Write-Host "[product-analytics] pointer: data\analytics\LATEST_BUILD.json"
Write-Host "[product-analytics] database: data\analytics\$BuildId\expedia_analytics.duckdb"
Write-Host "[product-analytics] marts: data\marts\$BuildId"
Write-Host "[product-analytics] manifest: artifacts\analytics\$BuildId\build_manifest.json"
