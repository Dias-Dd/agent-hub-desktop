import json,subprocess,tempfile,unittest,os,hashlib
from pathlib import Path

@unittest.skipUnless(os.name=='nt','Windows PowerShell process identity test')
class LaunchIdentity(unittest.TestCase):
 def test_new_pid_and_hash_distinguish_old_instance_and_failed_launch(self):
  root=Path(__file__).resolve().parents[1]
  source=(root/'tools/HubDesktopAgent.ps1').read_text(encoding='utf-8-sig')
  body=source.split("} elseif($request.action -eq 'desktop_launch') {",1)[1].split("} elseif($request.action -eq 'screenshot') {",1)[0]
  with tempfile.TemporaryDirectory() as directory:
   folder=Path(directory);script=folder/'probe.ps1'
   prefix=r"""param([string]$Root)
$ErrorActionPreference='Stop'
New-Item -ItemType Directory -Path (Join-Path $Root 'results') -Force | Out-Null
$program=Join-Path $PSHOME 'powershell.exe'
$old=Start-Process -FilePath $program -ArgumentList '-NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 20"' -PassThru -WindowStyle Hidden
$newPid=$null
try {
 $file=[IO.FileInfo](Join-Path $Root 'running.json')
 $request=@{executable=$program;value='-NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 20"'}
"""
   middle=r"""
 $newPid=$result.pid
 $running=$result
 if($running.exited){throw 'New probe unexpectedly exited'}
 if(-not(@($running.existing_instances | ForEach-Object {$_.pid}) -contains $old.Id)){throw 'Old instance not reported'}
 $file=[IO.FileInfo](Join-Path $Root 'failed.json')
 $request=@{executable=$program;value='-NoProfile -WindowStyle Hidden -Command "exit 7"'}
"""
   suffix=r"""
 @{running=$running;failed=$result;old_pid=$old.Id} | ConvertTo-Json -Depth 8 -Compress
} finally {
 Stop-Process -Id $old.Id -Force -ErrorAction SilentlyContinue
 if($newPid){Stop-Process -Id $newPid -Force -ErrorAction SilentlyContinue}
}
"""
   script.write_text(prefix+body+middle+body+suffix,encoding='utf-8-sig')
   result=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),'-Root',directory],capture_output=True,encoding='utf-8',errors='replace',timeout=30)
   self.assertEqual(result.returncode,0,result.stderr)
   data=json.loads(result.stdout.strip().splitlines()[-1]);running=data['running'];failed=data['failed']
   self.assertNotEqual(running['pid'],data['old_pid']);self.assertTrue(running['artifact_unchanged'])
   self.assertEqual(running['sha256'],hashlib.sha256(Path(running['executable']).read_bytes()).hexdigest())
   self.assertTrue(failed['exited']);self.assertEqual(failed['exit_code'],7)
   self.assertNotEqual(failed['pid'],running['pid']);self.assertIn('pre-existing',failed['note'])
