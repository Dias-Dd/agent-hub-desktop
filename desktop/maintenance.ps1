param([Parameter(Mandatory=$true)][string]$InstallDirectory)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath($InstallDirectory).TrimEnd('\')
$names = @('AgentMessageHubDesktop','AgentHubSetup','AgentHubMcp','AgentHubDiagnostics')
function Targets {
    @(Get-Process -Name $names -ErrorAction SilentlyContinue | Where-Object {
        try { [IO.Path]::GetDirectoryName($_.Path).TrimEnd('\') -eq $root } catch { $false }
    })
}
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class HubMaintenanceWindows {
 public delegate bool Callback(IntPtr hwnd, IntPtr data);
 [DllImport("user32.dll")] public static extern bool EnumWindows(Callback callback, IntPtr data);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
 [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr hwnd, uint message, IntPtr wp, IntPtr lp);
}
"@
$items = Targets
$ids = @{}; foreach($item in $items){ $ids[[uint32]$item.Id] = $item.ProcessName }
$callback = [HubMaintenanceWindows+Callback]{ param($window,$data)
    [uint32]$targetId=0
    [void][HubMaintenanceWindows]::GetWindowThreadProcessId($window,[ref]$targetId)
    if($ids.ContainsKey($targetId)) {
        # A normal close hides Agent Hub in the tray. Maintenance must exit it.
        $message = if($ids[$targetId] -eq 'AgentMessageHubDesktop'){0x8014}else{0x10}
        [void][HubMaintenanceWindows]::PostMessage($window,$message,[IntPtr]::Zero,[IntPtr]::Zero)
    }
    return $true
}
[void][HubMaintenanceWindows]::EnumWindows($callback,[IntPtr]::Zero)
$until=[DateTime]::UtcNow.AddSeconds(30)
while((Targets).Count -gt 0 -and [DateTime]::UtcNow -lt $until){ Start-Sleep -Milliseconds 250 }
if((Targets).Count -gt 0){exit 1}
exit 0
