import json,subprocess,tempfile,unittest
from pathlib import Path

SCRIPT=r'''param([string]$Source,[string]$FixtureRoot)
$ErrorActionPreference='Stop'
$sourceText=Get-Content -LiteralPath $Source -Raw -Encoding UTF8
$csharp=[regex]::Match($sourceText,"(?s)Add-Type @'\r?\n(.*?)\r?\n'@").Groups[1].Value
Add-Type $csharp
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$func=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Write-Result'},$true)
Invoke-Expression $func.Extent.Text
$path=Join-Path $FixtureRoot 'status.json'
for($i=0;$i -lt 500;$i++){
 Write-Result $path @{updated=$i;name='heartbeat'}
 $row=Get-Content -LiteralPath $path -Raw|ConvertFrom-Json
 if($row.updated -ne $i){throw 'heartbeat was not replaced'}
}
if(@(Get-ChildItem $FixtureRoot -Filter '*.tmp').Count){throw 'temporary file leak'}
@{ok=$true;writes=500}|ConvertTo-Json -Compress
'''
class Atomic(unittest.TestCase):
 def test_repeated_existing_heartbeat_replacement(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);script=root/'test.ps1';script.write_text(SCRIPT,encoding='utf-8-sig')
   p=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),'-Source',str(Path(__file__).parents[1]/'tools/HubDesktopAgent.ps1'),'-FixtureRoot',str(root)],capture_output=True,encoding='utf-8',errors='replace',timeout=30)
   self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertEqual(json.loads(p.stdout)['writes'],500)
