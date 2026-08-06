param(
    [double]$Hours = 6,
    [int]$Threads = 7,
    [string]$MemoryLimit = "32GB",
    [int]$BatchSize = 50000,
    [int]$MaxNewSubmissions = 5
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

Write-Host "[deep-6h] project: $ProjectRoot"
$CurrentBranch = (git branch --show-current).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "could not determine the current Git branch"
}
if ($CurrentBranch -ne "feature/geo-leak-max") {
    Write-Host "[deep-6h] switching from $CurrentBranch to feature/geo-leak-max"
    git switch feature/geo-leak-max
    if ($LASTEXITCODE -ne 0) {
        throw "git switch feature/geo-leak-max failed"
    }
}

Write-Host "[deep-6h] pulling feature/geo-leak-max"
git pull --ff-only
if ($LASTEXITCODE -ne 0) {
    throw "git pull failed"
}

Write-Host "[deep-6h] syncing Python environment"
uv sync
if ($LASTEXITCODE -ne 0) {
    throw "uv sync failed"
}

Write-Host "[deep-6h] starting adaptive $Hours-hour search"
uv run python .\scripts\deep_6h.py `
    --hours $Hours `
    --threads $Threads `
    --memory-limit $MemoryLimit `
    --batch-size $BatchSize `
    --max-new-submissions $MaxNewSubmissions

$ExitCode = $LASTEXITCODE
Write-Host "[deep-6h] exit code: $ExitCode"
Write-Host "[deep-6h] result: artifacts\deep_6h\LATEST_RESULT.txt"
Write-Host "[deep-6h] summary: artifacts\deep_6h\latest_summary.json"
Write-Host "[deep-6h] submission: artifacts\submission_deep_6h_best.csv"
exit $ExitCode
