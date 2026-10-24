import unittest,subprocess,shutil,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class ConsoleRecovery(unittest.TestCase):
 def test_disconnected_only_and_no_other_console_user(self):
  source=(ROOT/'tools/HubDesktopAgent.ps1').read_text(encoding='utf-8-sig')
  fn=source[source.index('function Restore-ConsoleDesktop'):source.index('function Screen-Space')]
  fn=fn.replace('[Security.Principal.WindowsIdentity]::GetCurrent().User.Value',"'fixture'").replace('[Diagnostics.Process]::GetCurrentProcess().SessionId','2').replace('[HubScreenDpi]::WTSGetActiveConsoleSessionId()','1').replace('& "$env:SystemRoot\\System32\\tscon.exe" $own /dest:console 2>&1|Out-Null',"$script:calls++;$global:LASTEXITCODE=0")
  # Keep native executable out of the fixture even when source uses a single separator.
  lines=fn.splitlines();lines=["  $script:calls++;$global:LASTEXITCODE=0" if 'tscon.exe' in line else line for line in lines];fn='\n'.join(lines)
  code=fn+"""
$ErrorActionPreference='Stop'
$preferenceFile='fixture';$Root='fixture';$script:calls=0
function Get-Content {param($LiteralPath,[switch]$Raw,$Encoding) '{"enabled":true,"sid":"fixture"}'}
function Read-SessionInfo {param($id,$info) if($info -eq 8){return $script:state};return $script:user}
function Write-Result {param($path,$value) throw $value.error}
$script:state=0;$script:user='';Restore-ConsoleDesktop
if($script:calls){throw 'active RDP stolen'}
$script:state=4;$script:user='someone';Restore-ConsoleDesktop
if($script:calls){throw 'occupied console stolen'}
$script:user='';Restore-ConsoleDesktop
if($script:calls -ne 1){throw 'disconnected desktop not restored'}
'PASS'
"""
  result=subprocess.run([shutil.which('powershell'),'-NoProfile','-Command',code],capture_output=True,text=True,timeout=20)
  self.assertEqual(result.returncode,0,result.stderr)
  self.assertIn('PASS',result.stdout)
 def test_setup_preserves_credential_object_and_global_policy(self):
  source=(ROOT/'tools/Start-HubVmBridge.ps1').read_text(encoding='utf-8-sig')
  self.assertIn('scriptblock]::Create((Get-Content',source)
  self.assertIn('-Credential $login -Enabled $enabled',source)
  self.assertNotIn('Set-ExecutionPolicy',source)
