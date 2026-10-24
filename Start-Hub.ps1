param([int]$Port = 8765, [switch]$NoSim = $true)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$hubArgs = @('-m', 'hub.supervisor', '--data', (Join-Path $PSScriptRoot 'data'), '--port', "$Port")
if ($NoSim) { $hubArgs += '--no-sim' }
python @hubArgs
