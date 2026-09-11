$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$port = 8310
$hostName = "127.0.0.1"
$configPath = Join-Path $repoRoot "config.local.yaml"
$frontendDist = Join-Path $repoRoot "frontend\dist"
$logDir = Join-Path $repoRoot "data\logs"
$outLog = Join-Path $logDir "echo-full-8310.out.log"
$errLog = Join-Path $logDir "echo-full-8310.err.log"
$pythonPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) { throw "Project Python environment is missing: $pythonPath" }

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($listener -and $listener.OwningProcess) {
    $backendProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
    if ($backendProcess.CommandLine -notmatch '-m\s+runtime\s+serve') { throw "Port 8310 is occupied by a different service" }
    Write-Host "Stopping process $($listener.OwningProcess) on port $port..."
    Stop-Process -Id $listener.OwningProcess -Force
    Start-Sleep -Seconds 1
}

$env:OCTOPUS_WEBUI_DIST = $frontendDist
$env:ECHO_ENV = "development"
$env:OCTOPUS_DEPLOYMENT_MODE = "local"

Write-Host "Starting full Octopus backend on http://${hostName}:$port ..."
$proc = Start-Process `
    -FilePath $pythonPath `
    -ArgumentList @("-m", "runtime", "serve", "--config", ('"{0}"' -f $configPath), "--host", $hostName, "--port", "$port") `
    -WorkingDirectory $repoRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog `
    -PassThru

$active = $null
for ($startupAttempt = 0; $startupAttempt -lt 30; $startupAttempt++) {
    $active = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($active) { break }
    Start-Sleep -Seconds 1
}
if (-not $active) {
    Write-Error "Backend did not start on port $port. See $errLog"
}

$commandLine = Get-CimInstance Win32_Process -Filter "ProcessId=$($active.OwningProcess)" |
    Select-Object -ExpandProperty CommandLine
$status = $null
for ($attempt = 1; $attempt -le 5; $attempt++) {
    try {
        $status = Invoke-RestMethod -Uri "http://${hostName}:$port/api/health" -TimeoutSec 5
        break
    } catch {
        Start-Sleep -Seconds 1
    }
}

if (-not $status) {
    Write-Error "Backend started, but /api/health did not respond. See $errLog"
}

Write-Host "PID: $($active.OwningProcess)"
Write-Host "Command: $commandLine"
Write-Host "Health check passed"
Write-Host "Logs: $errLog"
exit 0
