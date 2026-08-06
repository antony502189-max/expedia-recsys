param(
    [double]$Hours = 8,
    [int]$Threads = 7,
    [string]$MemoryLimit = "32GB",
    [int]$BatchSize = 50000
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

Write-Host "[overnight] project: $ProjectRoot"
$CurrentBranch = (git branch --show-current).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "could not determine the current Git branch"
}
if ($CurrentBranch -ne "feature/geo-leak-max") {
    Write-Host "[overnight] switching from $CurrentBranch to feature/geo-leak-max"
    git switch feature/geo-leak-max
    if ($LASTEXITCODE -ne 0) {
        throw "git switch feature/geo-leak-max failed"
    }
}

Write-Host "[overnight] pulling feature/geo-leak-max"
git pull --ff-only
if ($LASTEXITCODE -ne 0) {
    throw "git pull failed"
}

Write-Host "[overnight] syncing Python environment"
uv sync
if ($LASTEXITCODE -ne 0) {
    throw "uv sync failed"
}

Write-Host "[overnight] starting $Hours-hour search"
uv run python .\scripts\overnight_max.py `
    --hours $Hours `
    --threads $Threads `
    --memory-limit $MemoryLimit `
    --batch-size $BatchSize

$ExitCode = $LASTEXITCODE
Write-Host "[overnight] exit code: $ExitCode"
Write-Host "[overnight] result: artifacts\overnight_max\LATEST_RESULT.txt"
Write-Host "[overnight] summary: artifacts\overnight_max\latest_summary.json"
exit $ExitCode
