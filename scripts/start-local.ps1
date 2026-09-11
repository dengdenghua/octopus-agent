param([switch]$Web, [switch]$NoOpen)
$ErrorActionPreference = 'Stop'
$repoDir = Split-Path $PSScriptRoot -Parent
$stateDir = Join-Path $repoDir '.codex-run'
$pythonPath = Join-Path $repoDir '.venv\Scripts\python.exe'
$frontendDir = Join-Path $repoDir 'frontend'
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
$nodePath = (Get-Command node.exe -ErrorAction SilentlyContinue).Source
$runtimePaths = Join-Path $stateDir 'runtime-paths.json'
if (!$nodePath -and (Test-Path -LiteralPath $runtimePaths)) {
    $nodePath = (Get-Content -LiteralPath $runtimePaths -Raw | ConvertFrom-Json).node
}
if (!(Test-Path -LiteralPath $pythonPath) -or !$nodePath) {
    throw 'Python virtual environment or Node.js is missing. See LOCAL-RUN.md.'
}
$env:PYTHONUTF8 = '1'
if (!$env:OCTOPUS_OPENCODE_BIN -and (Test-Path -LiteralPath $runtimePaths)) {
    $openCodePath = (Get-Content -LiteralPath $runtimePaths -Raw | ConvertFrom-Json).opencode
    if ($openCodePath -and (Test-Path -LiteralPath $openCodePath)) {
        $env:OCTOPUS_OPENCODE_BIN = $openCodePath
    }
}
$env:OCTOPUS_HOME = Join-Path $stateDir 'octopus'
$env:PATH = "$(Split-Path $pythonPath);$(Split-Path $nodePath);$env:PATH"
$env:OCTOPUS_BACKEND_URL = 'http://127.0.0.1:8310'
$env:OCTOPUS_INTERNAL_GATEWAY_BASE_URL = $env:OCTOPUS_BACKEND_URL
$env:ELECTRON_START_URL = 'http://127.0.0.1:3310'

function Test-Endpoint([string]$Url) {
    try { return (Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2).StatusCode -eq 200 }
    catch { return $false }
}
function Start-LocalProcess([string]$Name, [string]$Executable, [string]$Arguments, [string]$Directory) {
    $process = Start-Process -FilePath $Executable -ArgumentList $Arguments -WorkingDirectory $Directory -WindowStyle Hidden -RedirectStandardOutput (Join-Path $stateDir "$Name.out.log") -RedirectStandardError (Join-Path $stateDir "$Name.err.log") -PassThru
    $process.Id | Set-Content -LiteralPath (Join-Path $stateDir "$Name.pid")
    return $process
}
function Wait-Endpoint([string]$Url, $Process, [string]$Name) {
    $deadline = (Get-Date).AddSeconds(120)
    while ((Get-Date) -lt $deadline) {
        if (Test-Endpoint $Url) { return }
        if ($Process.HasExited) { throw "$Name exited. See $stateDir\$Name.err.log" }
        Start-Sleep -Seconds 1
    }
    throw "$Name startup timed out. See $stateDir\$Name.err.log"
}
if (!(Test-Endpoint 'http://127.0.0.1:8310/api/health')) {
    $backend = Start-LocalProcess 'backend' $pythonPath '-m runtime serve --config config.local.yaml --host 127.0.0.1 --port 8310' $repoDir
    Wait-Endpoint 'http://127.0.0.1:8310/api/health' $backend 'backend'
}
if (!(Test-Endpoint 'http://127.0.0.1:3310/@vite/client')) {
    $vitePath = Join-Path $frontendDir 'node_modules\vite\bin\vite.js'
    $frontend = Start-LocalProcess 'frontend' $nodePath ('"' + $vitePath + '" --host 127.0.0.1 --port 3310 --strictPort') $frontendDir
    Wait-Endpoint 'http://127.0.0.1:3310/@vite/client' $frontend 'frontend'
}
Write-Host 'Echo is ready: http://127.0.0.1:3310'
Write-Host "Logs: $stateDir"
if ($NoOpen) { exit 0 }
if ($Web) { Start-Process 'http://127.0.0.1:3310'; exit 0 }
$electronPath = Join-Path $frontendDir 'node_modules\electron\dist\electron.exe'
if (!(Test-Path -LiteralPath $electronPath)) { throw 'Electron is missing. Use Start-Echo.cmd -Web or reinstall frontend dependencies.' }
$desktop = Start-Process -FilePath $electronPath -ArgumentList ('"' + (Join-Path $frontendDir 'electron\main.cjs') + '"') -WorkingDirectory $frontendDir -PassThru
$desktop.Id | Set-Content -LiteralPath (Join-Path $stateDir 'desktop.pid')
