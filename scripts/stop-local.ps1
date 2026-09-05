$ErrorActionPreference = 'Stop'
$repoDir = Split-Path $PSScriptRoot -Parent
$stateDir = Join-Path $repoDir '.codex-run'
function Stop-ProcessTree([int]$ProcessId) {
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcessId" | ForEach-Object { Stop-ProcessTree $_.ProcessId }
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}
foreach ($name in @('desktop', 'frontend', 'backend')) {
    $pidPath = Join-Path $stateDir "$name.pid"
    if (!(Test-Path -LiteralPath $pidPath)) { continue }
    $processIdValue = [int](Get-Content -LiteralPath $pidPath)
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$processIdValue"
    if ($process) {
        $belongsToRepo = ($process.ExecutablePath -and $process.ExecutablePath.StartsWith($repoDir + '\', [StringComparison]::OrdinalIgnoreCase)) -or ($process.CommandLine -and $process.CommandLine.Contains($repoDir + '\'))
        if (!$belongsToRepo) { Write-Warning "Skipping reused PID $processIdValue ($name)."; continue }
        Stop-ProcessTree $processIdValue
        Write-Host "Stopped $name"
    }
    Remove-Item -LiteralPath $pidPath
}
