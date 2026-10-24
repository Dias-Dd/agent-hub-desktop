"""Guest setup tests: Windows registry/LSA/power operations are mocked."""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT=Path(__file__).resolve().parents[1]/'tools/Configure-HubVmUnattended.ps1'
SHELL=shutil.which('pwsh') or shutil.which('powershell')

@unittest.skipUnless(SHELL,'Windows PowerShell unavailable')
class GuestSetup(unittest.TestCase):
    def run_ps(self,text):
        with tempfile.TemporaryDirectory() as folder:
            script=Path(folder)/'test.ps1'
            script.write_text('try {\n'+text+'\n} catch { Write-Error ($_.Exception.Message+\" | \"+$_.ScriptStackTrace);exit 1 }',encoding='utf-8-sig')
            result=subprocess.run([SHELL,'-NoProfile','-ExecutionPolicy','Bypass','-File',str(script)],capture_output=True,encoding='utf-8',errors='replace',timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            return result.stdout

    def test_native_lsa_wrapper_compiles_without_storing_credentials(self):
        source=SCRIPT.read_text(encoding='utf-8-sig')
        csharp=re.search(r"Add-Type @'\n(.*?)\n'@",source,re.S)[1]
        output=self.run_ps("Add-Type @'\n"+csharp+"\n'@\n[HubLogonSecret].GetMethod('Store').GetParameters().Length\n")
        self.assertIn('2',output)

    def test_enable_disable_with_mocked_guest_system_operations(self):
        source=SCRIPT.read_text(encoding='utf-8-sig')
        # Only the administrator check is replaced; hypervisor identity still
        # comes through the real setup guard, using the mocked VM description.
        source=re.sub(r"if\(-not \(\[Security.Principal.WindowsPrincipal\].*?Guest administrator token required for unattended setup\.'\}\n",'',source)
        with tempfile.TemporaryDirectory() as folder:
            source=source.replace("$root='C:\\ProgramData\\AgentHubDesktop'","$root='"+folder.replace("'","''")+"'")
            setup=Path(folder)/'setup.ps1';setup.write_text(source,encoding='utf-8-sig')
            output=self.run_ps(r'''
$ErrorActionPreference='Stop'
Add-Type 'public static class HubLogonSecret {public static bool Enabled; public static void Store(System.Security.SecureString password,bool enabled){Enabled=enabled;}}'
$global:hubTestWrites=@();$global:hubTestPower=@()
function Get-CimInstance { @{Manufacturer='Microsoft Corporation';Model='Virtual Machine'} }
function New-Item { param($Path,[switch]$Force) if($Path -notlike 'HKLM:*'){Microsoft.PowerShell.Management\New-Item -Path $Path -ItemType Directory -Force} }
function Get-Item { param($LiteralPath,$ErrorAction) return $null }
function New-ItemProperty { param($LiteralPath,$Name,$Value,$PropertyType,[switch]$Force) $global:hubTestWrites+=@{name=$Name;value=$Value} }
function Remove-ItemProperty {param($LiteralPath,$Name,$ErrorAction) $global:hubTestWrites+=@{name=$Name;removed=$true} }
function powercfg.exe {
 $global:hubTestPower+=($args -join ' ');$global:LASTEXITCODE=0
 if($args[0] -eq '/getactivescheme'){'00000000-0000-0000-0000-000000000001'}
 elseif($args[0] -eq '/duplicatescheme'){'00000000-0000-0000-0000-000000000002'}
}
$credential=[PSCredential]::new('fixture',(ConvertTo-SecureString 'fixture-secret-only' -AsPlainText -Force))
''' + "\n$result=& '"+str(setup).replace("'","''")+"' -Credential $credential -Enabled $true\n"+r'''
if(-not $result.configured -or -not [HubLogonSecret]::Enabled){throw 'enable failed'}
if($global:hubTestWrites|Where-Object {$_.name -eq 'DefaultPassword' -and -not $_.removed}){throw 'plaintext password written'}
if(-not ($global:hubTestWrites|Where-Object {$_.name -eq 'AutoAdminLogon' -and $_.value -eq '1'})){throw 'automatic logon flag missing'}
if(($global:hubTestPower|Where-Object {$_ -like '/change * 0'}).Count -ne 6){throw 'sleep/display configuration missing'}
''' + "\n$result=& '"+str(setup).replace("'","''")+"' -Credential $credential -Enabled $false\n"+r'''
if(-not $result.configured -or [HubLogonSecret]::Enabled){throw 'disable failed'}
if($global:hubTestPower -notcontains '/setactive 00000000-0000-0000-0000-000000000001'){throw 'original power plan not restored'}
'PASS guest enable/disable with all system writes mocked'
''')
            self.assertIn('PASS',output)
            for file in Path(folder).glob('*.json'):
                self.assertNotIn('fixture-secret-only',file.read_text(encoding='utf-8-sig'))

if __name__=='__main__':unittest.main()
