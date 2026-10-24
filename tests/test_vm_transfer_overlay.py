import json,subprocess,tempfile,unittest
from pathlib import Path
SCRIPT=r"""param([string]$BridgeSource,[string]$FixtureRoot)
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($BridgeSource,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$func=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Copy-HubSourceToVm'},$true)
Invoke-Expression $func.Extent.Text
function Invoke-Command {param($Session,[object[]]$ArgumentList,$ScriptBlock) & $ScriptBlock @ArgumentList}
function Copy-Item {param($LiteralPath,$Destination,$ToSession,[switch]$Force,$ErrorAction) if(-not $script:skipCopy){Microsoft.PowerShell.Management\Copy-Item -LiteralPath $LiteralPath -Destination $Destination -Force}}
$src=Join-Path $FixtureRoot 'crates';$dest=Join-Path $FixtureRoot 'guest/crates'
New-Item -ItemType Directory -Path (Join-Path $src 'core/src') -Force|Out-Null
New-Item -ItemType Directory -Path (Join-Path $dest 'core/src') -Force|Out-Null
[IO.File]::WriteAllText((Join-Path $src 'core/src/lib.rs'),'new content 123')
[IO.File]::WriteAllText((Join-Path $dest 'core/src/lib.rs'),'old')
[IO.File]::WriteAllText((Join-Path $dest 'keep.txt'),'preserve unrelated')
[IO.File]::WriteAllBytes((Join-Path $src 'core/src/data[1].bin'),[byte[]](0,255,128,65))
$r=Copy-HubSourceToVm $src $dest 'mock'
if(-not $r.verified -or $r.files -ne 2){throw 'not verified'}
if([IO.File]::ReadAllText((Join-Path $dest 'core/src/lib.rs')) -ne 'new content 123'){throw 'stale content'}
if(Test-Path (Join-Path $dest 'crates')){throw 'nested directory copy'}
if(-not (Test-Path (Join-Path $dest 'keep.txt'))){throw 'deleted unrelated file'}
[IO.File]::WriteAllText((Join-Path $src 'core/src/lib.rs'),'file overwrite')
$r=Copy-HubSourceToVm (Join-Path $src 'core/src/lib.rs') (Join-Path $dest 'core/src/lib.rs') 'mock'
if([IO.File]::ReadAllText((Join-Path $dest 'core/src/lib.rs')) -ne 'file overwrite'){throw 'file stale'}
$script:skipCopy=$true;[IO.File]::WriteAllText((Join-Path $src 'core/src/lib.rs'),'not copied');$caught=$false
try{Copy-HubSourceToVm $src $dest 'mock'|Out-Null}catch{if($_.Exception.Message -like '*Transfer content mismatch*'){$caught=$true}else{throw}}
if(-not $caught){throw 'silent false success'}
@{ok=$true;cases=@('existing directory overlay','single file replace','no nested directory','unrelated files retained','hash mismatch reported')}|ConvertTo-Json -Compress
"""
class Transfer(unittest.TestCase):
 def test_powershell_overlay_and_verification_without_vm(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);script=root/'test.ps1';script.write_text(SCRIPT,encoding='utf-8-sig')
   result=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),'-BridgeSource',str(Path(__file__).parents[1]/'tools/Start-HubVmBridge.ps1'),'-FixtureRoot',str(root)],capture_output=True,encoding='utf-8',errors='replace',timeout=30)
   self.assertEqual(result.returncode,0,result.stdout+result.stderr);self.assertTrue(json.loads(result.stdout)['ok'])
