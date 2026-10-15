$ErrorActionPreference = 'Stop'
$frontendPath = Join-Path $PSScriptRoot '..\frontend'
Push-Location $frontendPath
try {
    & npm.cmd install
    if ($LASTEXITCODE -ne 0) { throw 'Cài dependency frontend thất bại.' }
} finally { Pop-Location }
Write-Host 'Frontend dependencies are installed.' -ForegroundColor Green
