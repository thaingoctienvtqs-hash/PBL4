$ErrorActionPreference = 'Stop'
$frontendPath = Join-Path $PSScriptRoot '..\frontend'
if (-not (Test-Path -LiteralPath (Join-Path $frontendPath 'node_modules'))) { throw 'Chưa cài frontend. Hãy chạy .\web\scripts\setup_frontend.ps1 trước.' }
Push-Location $frontendPath
try {
    & npm.cmd run dev
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dừng với lỗi.' }
} finally { Pop-Location }
