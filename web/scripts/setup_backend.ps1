param([switch]$WithTests)
$ErrorActionPreference = 'Stop'
$backendPath = Join-Path $PSScriptRoot '..\backend'
$venvPython = Join-Path $backendPath '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $venvPython)) {
    $created = $false
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        try { & py -3.11 -m venv (Join-Path $backendPath '.venv'); $created = ($LASTEXITCODE -eq 0) } catch { $created = $false }
        if (-not $created) { try { & py -3 -m venv (Join-Path $backendPath '.venv'); $created = ($LASTEXITCODE -eq 0) } catch { $created = $false } }
    }
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $created -and $pythonCommand) {
        try { & $pythonCommand.Source -m venv (Join-Path $backendPath '.venv'); $created = ($LASTEXITCODE -eq 0) } catch { $created = $false }
    }
    $workspacePython = Join-Path $PSScriptRoot '..\..\.venv311\Scripts\python.exe'
    if (-not $created -and (Test-Path -LiteralPath $workspacePython)) {
        & $workspacePython -m venv (Join-Path $backendPath '.venv')
        $created = ($LASTEXITCODE -eq 0)
    }
    if (-not $created) { throw 'Không tạo được môi trường Python. Hãy cài Python 3.11+ hoặc Python Launcher rồi thử lại.' }
}

$previousPythonUtf8 = $env:PYTHONUTF8
$env:PYTHONUTF8 = '1'
try {
    if ($WithTests) { & $venvPython -m pip install -r (Join-Path $backendPath 'requirements-dev.txt') }
    else { & $venvPython -m pip install -r (Join-Path $backendPath 'requirements.txt') }
    $installExitCode = $LASTEXITCODE
} finally {
    if ($null -eq $previousPythonUtf8) { Remove-Item Env:PYTHONUTF8 -ErrorAction SilentlyContinue }
    else { $env:PYTHONUTF8 = $previousPythonUtf8 }
}
if ($installExitCode -ne 0) { throw 'Cài dependency backend thất bại.' }
Write-Host 'Backend dependencies are installed in web/backend/.venv.' -ForegroundColor Green
