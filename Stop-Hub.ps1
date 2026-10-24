$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$pythonProcesses = Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(w)?\.exe$' -and $_.CommandLine -match 'hub\.(supervisor|server)' }
$expectedData = Join-Path $projectRoot 'data'
$pidFile = Join-Path $expectedData 'service.pid'
# Supervisor PID is persisted on startup; validate executable command before stopping.
$supervisorPidFile = Join-Path $expectedData 'supervisor.pid'
foreach ($hubPidFile in @($supervisorPidFile, $pidFile)) {
    if (Test-Path -LiteralPath $hubPidFile) {
        $hubProcessId = [int](Get-Content -LiteralPath $hubPidFile -Raw)
        $matching = $pythonProcesses | Where-Object { $_.ProcessId -eq $hubProcessId }
        if ($matching) { Stop-Process -Id $hubProcessId -ErrorAction SilentlyContinue }
    }
}
Write-Host 'Stopped the recorded Hub processes. Login task, if installed, remains registered.'
