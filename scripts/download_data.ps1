$ErrorActionPreference = "Stop"

New-Item -ItemType Directory -Force -Path "data/raw" | Out-Null
uvx kaggle competitions download `
    -c expedia-hotel-recommendations `
    -p data/raw

$archive = "data/raw/expedia-hotel-recommendations.zip"
if (Test-Path $archive) {
    Expand-Archive -Path $archive -DestinationPath "data/raw" -Force
}

Write-Host "Expected files: train.csv(.gz), test.csv(.gz), destinations.csv(.gz)"
