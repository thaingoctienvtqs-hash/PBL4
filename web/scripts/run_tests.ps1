$ErrorActionPreference = 'Stop'
$backendPath = Join-Path $PSScriptRoot '..\backend'
$frontendPath = Join-Path $PSScriptRoot '..\frontend'
$venvPython = Join-Path $backendPath '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $venvPython)) { throw 'Chưa cài backend. Hãy chạy .\web\scripts\setup_backend.ps1 -WithTests.' }
Push-Location $backendPath
try {
    & $venvPython -m pytest
    if ($LASTEXITCODE -ne 0) { throw 'Backend tests thất bại.' }
} finally { Pop-Location }

Push-Location $frontendPath
try {
    & npm.cmd run typecheck
    if ($LASTEXITCODE -ne 0) { throw 'TypeScript check thất bại.' }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build thất bại.' }
} finally { Pop-Location }
Write-Host 'Backend tests, TypeScript check and frontend build passed.' -ForegroundColor Green
