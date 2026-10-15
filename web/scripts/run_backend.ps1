$ErrorActionPreference = 'Stop'
$backendPath = Join-Path $PSScriptRoot '..\backend'
$venvPython = Join-Path $backendPath '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) { throw 'Chưa cài backend. Hãy chạy .\web\scripts\setup_backend.ps1 trước.' }
Push-Location $backendPath
try {
    & $venvPython -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
    if ($LASTEXITCODE -ne 0) { throw 'Backend dừng với lỗi.' }
} finally { Pop-Location }
