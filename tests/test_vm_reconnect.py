"""Exercise the bridge state machine with mocked Hyper-V/remoting commands."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SHELL=shutil.which('powershell') or shutil.which('pwsh')

@unittest.skipUnless(SHELL,'PowerShell unavailable')
class Recovery(unittest.TestCase):
    def test_recovery_backoff_authentication_and_user_stop(self):
        script=r'''
$env:PSModulePath=(Join-Path $PSHOME 'Modules')+';'+(Join-Path $env:ProgramFiles 'WindowsPowerShell\Modules')
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile('__SOURCE__',[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'source parse failed'}
foreach($name in @('Update-VmConnection')){
 $fn=$ast.Find({param($a) $a -is [Management.Automation.Language.FunctionDefinitionAst] -and $a.Name -eq $name},$true)
 Invoke-Expression $fn.Extent.Text
}
function Now {$script:clock}
function Publish-Status {}
function Get-VM {param($Name,$ErrorAction) $script:powerQueries++;@{State=$script:power}}
function Get-ReconnectCredential {
 if($script:behavior -eq 'decrypt'){throw 'decrypt failed'}
 [PSCredential]::new('fixture',(ConvertTo-SecureString 'fixture-only' -AsPlainText -Force))
}
function Connect-Guest {param($Name,$Login,$Unattended,$Recovering)
 $script:attempts++
 if(-not $Recovering){throw 'recovery must not boot or redeploy'}
 if($script:behavior -eq 'auth'){throw '凭据无效'}
 if($script:behavior -eq 'network'){throw 'Windows updating'}
 $script:session=@{State='Opened'};$script:connectionPhase='ready'
}
function Scenario {
 $script:session=@{State='Broken'};$script:autoReconnectEnabled=$true;$script:lastConnectionCipher='encrypted-fixture'
 $script:lastUnattended=$true;$script:busyId=$null;$script:VmName='Hub';$script:clock=100;$script:nextReconnect=0
 $script:reconnectDelay=3;$script:connectionPhase='ready';$script:desktopReady=$true;$script:behavior='success'
 $script:attempts=0;$script:powerQueries=0;$script:power='Running';$script:vmPowerState='Running'
}
Scenario;Update-VmConnection
if($attempts -ne 1 -or $session.State -ne 'Opened'){throw ("broken connection not recovered: attempts=$attempts phase=$connectionPhase error=$connectionError")}
Update-VmConnection;if($attempts -ne 1){throw 'healthy connection reconnected'}
Scenario;$script:power='Off';Update-VmConnection
if($attempts -ne 0 -or $connectionPhase -ne 'waiting_windows'){throw 'powered-off VM must not be started'}
Scenario;$script:autoReconnectEnabled=$false;Update-VmConnection
if($attempts -or $powerQueries){throw 'manual disconnect not respected'}
Scenario;$script:behavior='auth';Update-VmConnection;Update-VmConnection
if($attempts -ne 1 -or $autoReconnectEnabled -or $connectionPhase -ne 'credentials_required'){throw 'bad credentials retried'}
Scenario;$script:behavior='decrypt';Update-VmConnection
if($attempts -or $autoReconnectEnabled -or $connectionPhase -ne 'credentials_required'){throw 'bad encrypted credentials retried'}
Scenario;$script:behavior='network';Update-VmConnection
if($attempts -ne 1 -or $nextReconnect -ne 103 -or $reconnectDelay -ne 6){throw 'first retry backoff incorrect'}
$script:clock=101;Update-VmConnection;if($attempts -ne 1){throw 'busy loop retry'}
$script:clock=104;Update-VmConnection
if($attempts -ne 2 -or $nextReconnect -ne 110 -or $reconnectDelay -ne 12){throw 'second backoff incorrect'}
$script:clock=111;$script:behavior='success';Update-VmConnection
if($session.State -ne 'Opened' -or $reconnectDelay -ne 3){throw 'connection did not recover after update'}
# Check the actual publisher cannot report ready for a broken session.
$fn=$ast.Find({param($a) $a -is [Management.Automation.Language.FunctionDefinitionAst] -and $a.Name -eq 'Publish-Status'},$true)
Invoke-Expression $fn.Extent.Text
function Update-DesktopHealth {}
function Save-Json {param($Path,$Value) $script:published=$Value}
$script:root='.';$script:nextPowerPoll=(Get-Date).AddSeconds(20);$script:vmPowerState='Running'
$script:session=@{State='Broken'};$script:connectionPhase='ready';$script:autoReconnectEnabled=$true
Publish-Status
if($published.connected -or $published.connection_phase -ne 'reconnecting' -or $published.desktop.ready){throw 'stale ready state exposed'}
# Verify encrypted reconnect credentials use native Windows PowerShell modules,
# even if the launching process supplied an incompatible PowerShell 7 path.
$env:PSModulePath='C:\Program Files\PowerShell\7\Modules'
$assignment=$ast.Find({param($a) $a -is [Management.Automation.Language.AssignmentStatementAst] -and $a.Left.Extent.Text -eq '$env:PSModulePath'},$true)
Invoke-Expression $assignment.Extent.Text
$fn=$ast.Find({param($a) $a -is [Management.Automation.Language.FunctionDefinitionAst] -and $a.Name -eq 'Get-ReconnectCredential'},$true)
Invoke-Expression $fn.Extent.Text
Add-Type -AssemblyName System.Security
$bytes=[Text.Encoding]::UTF8.GetBytes('{"username":"fixture","password":"fixture-only"}')
$cipher=[Convert]::ToBase64String([Security.Cryptography.ProtectedData]::Protect($bytes,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser))
$credential=Get-ReconnectCredential $cipher
if($credential.UserName -ne 'fixture' -or $credential.GetNetworkCredential().Password -ne 'fixture-only'){throw 'protected credential roundtrip failed'}
$credential.Password.Dispose();[Array]::Clear($bytes,0,$bytes.Length)
'PASS recovery, retry backoff, credentials, user stop and truthful status'

'''.replace('__SOURCE__',str(ROOT/'tools/Start-HubVmBridge.ps1').replace("'","''"))
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'test.ps1';target.write_text(script,encoding='utf-8-sig')
            result=subprocess.run([SHELL,'-NoProfile','-ExecutionPolicy','Bypass','-File',str(target)],capture_output=True,encoding='utf-8',errors='replace',timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('PASS',result.stdout)

if __name__=='__main__':unittest.main()
