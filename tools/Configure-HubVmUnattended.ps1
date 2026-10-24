param([Parameter(Mandatory=$true)][PSCredential]$Credential,[bool]$Enabled=$true)
$ErrorActionPreference='Stop'
# This script is deployed and invoked inside the selected Hyper-V guest only.
$computer=Get-CimInstance Win32_ComputerSystem
if($computer.Manufacturer -ne 'Microsoft Corporation' -or $computer.Model -ne 'Virtual Machine'){throw 'Unattended setup must run inside the selected Hyper-V guest.'}
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
if(-not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Guest administrator token required for unattended setup.'}
$root='C:\ProgramData\AgentHubDesktop'
New-Item -ItemType Directory -Path $root -Force|Out-Null
$winlogon='HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon'
$system='HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System'
$marker=Join-Path $root 'unattended.json'
$backup=Join-Path $root 'unattended-before.json'

if(-not ('HubLogonSecret' -as [type])){
Add-Type @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Security;
public static class HubLogonSecret {
 [StructLayout(LayoutKind.Sequential)] struct Unicode { public ushort Length,MaximumLength; public IntPtr Buffer; }
 [StructLayout(LayoutKind.Sequential)] struct Attributes { public uint Length; public IntPtr RootDirectory,ObjectName; public uint Flags; public IntPtr SecurityDescriptor,SecurityQualityOfService; }
 [DllImport("advapi32.dll")] static extern uint LsaOpenPolicy(IntPtr system,ref Attributes attributes,uint access,out IntPtr policy);
 [DllImport("advapi32.dll")] static extern uint LsaStorePrivateData(IntPtr policy,ref Unicode key,ref Unicode value);
 [DllImport("advapi32.dll",EntryPoint="LsaStorePrivateData")] static extern uint DeletePrivateData(IntPtr policy,ref Unicode key,IntPtr value);
 [DllImport("advapi32.dll")] static extern uint LsaClose(IntPtr policy);
 [DllImport("advapi32.dll")] static extern uint LsaNtStatusToWinError(uint status);
 static void Check(uint status) { if(status!=0)throw new Win32Exception((int)LsaNtStatusToWinError(status)); }
 public static void Store(SecureString password,bool enabled) {
  var attributes=new Attributes();attributes.Length=(uint)Marshal.SizeOf(typeof(Attributes));
  IntPtr handle=IntPtr.Zero,secret=IntPtr.Zero;
  string name="DefaultPassword";
  var key=new Unicode();key.Buffer=Marshal.StringToHGlobalUni(name);key.Length=(ushort)(name.Length*2);key.MaximumLength=(ushort)(key.Length+2);
  try {
   Check(LsaOpenPolicy(IntPtr.Zero,ref attributes,0x20,out handle));
   if(enabled){
    secret=Marshal.SecureStringToGlobalAllocUnicode(password);
    var value=new Unicode();value.Buffer=secret;value.Length=checked((ushort)(password.Length*2));value.MaximumLength=checked((ushort)(value.Length+2));
    Check(LsaStorePrivateData(handle,ref key,ref value));
   }else{
    uint result=DeletePrivateData(handle,ref key,IntPtr.Zero);
    if(result!=0 && LsaNtStatusToWinError(result)!=2)Check(result);
   }
  } finally {if(secret!=IntPtr.Zero)Marshal.ZeroFreeGlobalAllocUnicode(secret);Marshal.FreeHGlobal(key.Buffer);if(handle!=IntPtr.Zero)LsaClose(handle);}
 }
}
'@
}
function Write-Settings($path,$value){
 [IO.File]::WriteAllText("$path.tmp",($value|ConvertTo-Json -Depth 8 -Compress),[Text.UTF8Encoding]::new($false))
 Move-Item -LiteralPath "$path.tmp" -Destination $path -Force
}
function Get-Value($path,$name){
 $key=Get-Item -LiteralPath $path -ErrorAction SilentlyContinue
 $exists=$key -and $key.GetValueNames() -contains $name
 @{path=$path;name=$name;exists=[bool]$exists;value=$(if($exists){$key.GetValue($name)}else{$null});kind=$(if($exists){$key.GetValueKind($name).ToString()}else{'String'})}
}
function Restore-Values($rows){
 foreach($row in $rows){
  if($row.exists){New-Item -Path $row.path -Force|Out-Null;New-ItemProperty -LiteralPath $row.path -Name $row.name -Value $row.value -PropertyType $row.kind -Force|Out-Null}
  else{Remove-ItemProperty -LiteralPath $row.path -Name $row.name -ErrorAction SilentlyContinue}
 }
}
if(-not $Enabled){
 if(Test-Path -LiteralPath $marker){
  $owned=Get-Content -LiteralPath $marker -Raw -Encoding UTF8|ConvertFrom-Json
  if($owned.enabled){
   New-ItemProperty -LiteralPath $winlogon -Name AutoAdminLogon -Value '0' -PropertyType String -Force|Out-Null
   [HubLogonSecret]::Store($Credential.Password,$false)
   if(Test-Path -LiteralPath $backup){$before=Get-Content -LiteralPath $backup -Raw -Encoding UTF8|ConvertFrom-Json;Restore-Values $before.registry}
   # Never restore a previous automatic-login flag without its previous secret.
   New-ItemProperty -LiteralPath $winlogon -Name AutoAdminLogon -Value '0' -PropertyType String -Force|Out-Null
   Write-Settings $marker @{enabled=$false;account=$identity.Name;updated=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()}
   # Restore the original power plan, which Hub never modified.
   if($before.power_plan){& powercfg.exe /setactive $before.power_plan|Out-Null}
   if($before.hub_power_plan){& powercfg.exe /delete $before.hub_power_plan|Out-Null}
   Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue
  }
 }
 return [pscustomobject]@{enabled=$false;configured=$true}
}

if($Credential.Password.Length -eq 0){throw 'A Windows password (not a PIN) is required for automatic logon.'}
$userSid=$identity.User.Value
if(-not(Test-Path -LiteralPath $backup)){
 $registry=@((Get-Value $winlogon 'DefaultUserName'),(Get-Value $winlogon 'DefaultDomainName'),(Get-Value $system 'InactivityTimeoutSecs'),(Get-Value $winlogon 'AutoLogonCount'))
 $active=& powercfg.exe /getactivescheme
 $power=([regex]::Match(($active -join ' '),'[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}')).Value
 if(-not $power){throw 'Cannot read the original guest power plan.'}
 # A separate plan makes disabling reversible, without altering the original plan.
 $duplicated=& powercfg.exe /duplicatescheme $power
 $ownedPlan=([regex]::Match(($duplicated -join ' '),'[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}')).Value
 if($LASTEXITCODE -ne 0 -or -not $ownedPlan){throw 'Cannot create guest unattended power plan.'}
 Write-Settings $backup @{registry=$registry;power_plan=$power;hub_power_plan=$ownedPlan}
}
$before=Get-Content -LiteralPath $backup -Raw -Encoding UTF8|ConvertFrom-Json
Write-Settings $marker @{enabled=$true;configured=$false;account=$identity.Name;sid=$userSid;updated=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()}
[HubLogonSecret]::Store($Credential.Password,$true)
$account=$identity.Name.Split('\',2)
if($account.Count -ne 2){throw 'Cannot resolve the guest Windows account name.'}
New-ItemProperty -LiteralPath $winlogon -Name DefaultUserName -Value $account[1] -PropertyType String -Force|Out-Null
New-ItemProperty -LiteralPath $winlogon -Name DefaultDomainName -Value $account[0] -PropertyType String -Force|Out-Null
Remove-ItemProperty -LiteralPath $winlogon -Name DefaultPassword -ErrorAction SilentlyContinue
Remove-ItemProperty -LiteralPath $winlogon -Name AutoLogonCount -ErrorAction SilentlyContinue
New-ItemProperty -LiteralPath $winlogon -Name AutoAdminLogon -Value '1' -PropertyType String -Force|Out-Null
New-Item -Path $system -Force|Out-Null
New-ItemProperty -LiteralPath $system -Name InactivityTimeoutSecs -Value 0 -PropertyType DWord -Force|Out-Null
& powercfg.exe /setactive $before.hub_power_plan|Out-Null
if($LASTEXITCODE -ne 0){throw 'Cannot activate guest unattended power plan.'}
foreach($setting in @('standby-timeout-ac','standby-timeout-dc','hibernate-timeout-ac','hibernate-timeout-dc','monitor-timeout-ac','monitor-timeout-dc')){
 & powercfg.exe /change $setting 0|Out-Null
 if($LASTEXITCODE -ne 0){throw 'Cannot configure guest power timeout.'}
}
Write-Settings $marker @{enabled=$true;account=$identity.Name;sid=$userSid;autologon=$true;no_sleep=$true;updated=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()}
[pscustomobject]@{enabled=$true;configured=$true;account=$identity.Name;credential_storage='Windows LSA secret';takes_effect='Automatic logon on next Windows startup; desktop settings at service start.'}
