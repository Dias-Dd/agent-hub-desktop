param([switch]$Remove)
$ErrorActionPreference = 'Stop'
$taskName = 'AgentMessageHub-v01'
if ($Remove) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    exit
}
$scriptPath = Join-Path $PSScriptRoot 'Start-Hub.ps1'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$scriptPath`"" -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)
$settings = New-ScheduledTaskSettingsSet -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description 'Local Agent Message Hub supervisor; simulation only by default' -Force
Write-Host 'Installed per-user logon task. No real model calls enabled.'
