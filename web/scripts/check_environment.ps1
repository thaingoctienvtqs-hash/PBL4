$ErrorActionPreference = 'Stop'

Write-Host 'ArtGuard SQL Server environment check' -ForegroundColor Cyan
Write-Host "Workspace: $PSScriptRoot"

foreach ($commandName in @('git', 'node', 'npm', 'py')) {
    $command = Get-Command $commandName -ErrorAction SilentlyContinue
    if (-not $command) { Write-Host "[MISSING] $commandName"; continue }
    try {
        $version = switch ($commandName) {
            'git' { & git --version 2>&1 }
            'node' { & node --version 2>&1 }
            'npm' { & npm.cmd --version 2>&1 }
            'py' { & py --version 2>&1 }
        }
        if ($LASTEXITCODE -eq 0) { Write-Host "[OK] $commandName`: $version" }
        else { Write-Host "[WARN] $commandName is present but returned exit code $LASTEXITCODE." }
    } catch { Write-Host "[WARN] $commandName is present but could not start." }
}
$sqlcmd = Get-Command sqlcmd -ErrorAction SilentlyContinue
if ($sqlcmd) { Write-Host "[OK] sqlcmd command: $($sqlcmd.Source)" }
else { Write-Host '[INFO] sqlcmd is not available on PATH.' }

$uninstallPaths = @('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*', 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*', 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*')
$ssmsInstalls = Get-ItemProperty -Path $uninstallPaths -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -match '^SQL Server Management Studio' }
if ($ssmsInstalls) {
    foreach ($install in $ssmsInstalls) { Write-Host "[OK] SSMS: $($install.DisplayName) $($install.DisplayVersion)" }
} else { Write-Host '[INFO] SSMS was not found in the common uninstall registry entries.' }

$pythonPath = Join-Path $PSScriptRoot '..\backend\.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $pythonPath) {
    try {
        $version = & $pythonPath --version 2>&1
        if ($LASTEXITCODE -eq 0) { Write-Host "[OK] Backend virtualenv: $version" }
        $pythonBits = & $pythonPath -c "import struct; print(struct.calcsize('P') * 8)" 2>$null
        if ($LASTEXITCODE -eq 0) { Write-Host "[INFO] Backend Python architecture: $pythonBits-bit" }
        $hasPyodbc = & $pythonPath -c "import importlib.util; print(importlib.util.find_spec('pyodbc') is not None)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $hasPyodbc -eq 'True') { Write-Host '[OK] pyodbc is installed in the backend virtualenv.' }
        else { Write-Host '[MISSING] pyodbc in the backend virtualenv. Run setup_backend.ps1 after reviewing requirements.' }
    } catch { Write-Host '[WARN] Backend virtualenv Python could not start.' }
} else {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) { try { & py -3.11 --version } catch { Write-Host '[WARN] Python 3.11 was not available through py.' } }
    else { Write-Host '[MISSING] Python 3.11 and backend virtualenv.' }
}

$architecture = [Runtime.InteropServices.RuntimeInformation]::OSArchitecture
Write-Host "[INFO] OS architecture: $architecture"

$instanceRegistryPath = 'HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\Instance Names\SQL'
$instanceRegistry = Get-ItemProperty -LiteralPath $instanceRegistryPath -ErrorAction SilentlyContinue
if ($instanceRegistry) {
    $instanceProperties = $instanceRegistry.PSObject.Properties | Where-Object { $_.Name -notlike 'PS*' }
    foreach ($property in $instanceProperties) {
        Write-Host "[INFO] SQL instance: $($property.Name) ($($property.Value))"
        $setupPath = "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\$($property.Value)\Setup"
        $setup = Get-ItemProperty -LiteralPath $setupPath -ErrorAction SilentlyContinue
        if ($setup.Version) { Write-Host "[INFO] SQL Server engine version: $($setup.Version)" }
    }
} else { Write-Host '[MISSING] SQL Server instance registry entries were not found.' }

$sqlServices = Get-Service -ErrorAction SilentlyContinue | Where-Object { $_.Name -eq 'MSSQLSERVER' -or $_.Name -like 'MSSQL$*' -or $_.Name -eq 'SQLBrowser' }
if ($sqlServices) { $sqlServices | Select-Object Name, Status, StartType | Format-Table -AutoSize }
else { Write-Host '[MISSING] SQL Server Database Engine services were not found.' }

$sqlProcess = Get-Process -Name sqlservr -ErrorAction SilentlyContinue
if ($sqlProcess) { Write-Host "[OK] sqlservr.exe process IDs: $($sqlProcess.Id -join ', ')" }
else { Write-Host '[INFO] No sqlservr.exe process is visible to this session.' }

$odbcRegistryPath = 'HKLM:\SOFTWARE\ODBC\ODBCINST.INI\ODBC Drivers'
$odbcRegistry = Get-ItemProperty -LiteralPath $odbcRegistryPath -ErrorAction SilentlyContinue
$sqlDrivers = @()
if ($odbcRegistry) {
    $sqlDrivers = @($odbcRegistry.PSObject.Properties | Where-Object { $_.Name -like '*SQL Server*' -and $_.Name -notlike 'PS*' } | ForEach-Object { $_.Name })
}
if ($sqlDrivers.Count -gt 0) {
    foreach ($driver in $sqlDrivers) { Write-Host "[OK] 64-bit ODBC driver: $driver" }
} else { Write-Host '[MISSING] 64-bit SQL Server ODBC driver registry entries were not found.' }

$portOpen = Test-NetConnection -ComputerName 127.0.0.1 -Port 1433 -InformationLevel Quiet -WarningAction SilentlyContinue
if ($portOpen) { Write-Host '[OK] TCP 127.0.0.1:1433 accepts connections.' }
else { Write-Host '[INFO] TCP 127.0.0.1:1433 is closed; confirm the instance port or use DB_INSTANCE.' }

$envFile = Join-Path $PSScriptRoot '..\.env'
if (Test-Path -LiteralPath $envFile) { Write-Host '[OK] web/.env exists; values are not displayed.' }
else { Write-Host '[INFO] Create web/.env from web/.env.example without overwriting an existing file.' }
