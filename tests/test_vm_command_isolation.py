import json,subprocess,tempfile,unittest
from pathlib import Path

SCRIPT=r'''param([string]$BridgeSource,[string]$FixtureRoot)
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($BridgeSource,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$func=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Invoke-HubChildCommand'},$true)
Invoke-Expression $func.Extent.Text
$r=Invoke-HubChildCommand $FixtureRoot 'Write-Output "before exit";exit 0' 10
if($r.exit_code -ne 0 -or $r.output -notmatch 'before exit'){throw 'explicit exit lost result'}
$r=Invoke-HubChildCommand $FixtureRoot 'Write-Output "second command";exit 7' 10
if($r.exit_code -ne 7 -or $r.output -notmatch 'second command'){throw 'exit broke caller'}
$r=Invoke-HubChildCommand $FixtureRoot 'throw "failure evidence"' 10
if($r.exit_code -ne 1 -or $r.output -notmatch 'failure evidence'){throw 'error missing'}
$r=Invoke-HubChildCommand $FixtureRoot '$env:HUB_ISOLATION_PROBE="child";Write-Output "中文输出"' 10
if($env:HUB_ISOLATION_PROBE -or $r.output -notmatch '中文输出'){throw 'environment leak or broken UTF8'}
$caught=$false
try{Invoke-HubChildCommand $FixtureRoot 'Start-Sleep -Seconds 20' 1}catch{if($_.Exception.Message -like '*timed out*'){$caught=$true}else{throw}}
if(-not $caught){throw 'timeout did not stop process'}
$r=Invoke-HubChildCommand $FixtureRoot 'Write-Output "still alive"' 10
if($r.output -notmatch 'still alive'){throw 'timeout broke caller'}
@{ok=$true;cases=6}|ConvertTo-Json -Compress
'''

class Isolation(unittest.TestCase):
 def test_exit_timeout_and_errors_do_not_kill_caller(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);script=root/'test.ps1';script.write_text(SCRIPT,encoding='utf-8-sig')
   p=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),'-BridgeSource',str(Path(__file__).parents[1]/'tools/Start-HubVmBridge.ps1'),'-FixtureRoot',str(root)],capture_output=True,encoding='utf-8',errors='replace',timeout=40)
   self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertTrue(json.loads(p.stdout)['ok'])
