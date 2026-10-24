import json,tempfile,time,threading,unittest
from pathlib import Path
from unittest.mock import patch
from hub.vm_bridge import VmBridge
from hub.core import HubError

class Stability(unittest.TestCase):
 def test_stale_heartbeat_with_live_process_never_relaunches(self):
  with tempfile.TemporaryDirectory() as folder:
   b=VmBridge(folder);(b.root/'status.json').write_text(json.dumps({'updated':time.time()-45,'helper_pid':123,'protocol':4,'connected':True}),encoding='utf-8')
   with patch.object(VmBridge,'_process_alive',return_value=True),patch.object(b,'_launch_helper_process') as start:
    state=b.status();b.launch_helper()
    self.assertTrue(state['helper_alive']);self.assertFalse(state['connected']);self.assertEqual(state['connection_phase'],'helper_busy');start.assert_not_called()

 def test_parallel_launches_share_one_elevation_during_startup(self):
  with tempfile.TemporaryDirectory() as folder:
   calls=[]
   with patch.object(VmBridge,'_launch_helper_process',side_effect=lambda:calls.append(1)):
    threads=[threading.Thread(target=VmBridge(folder).launch_helper) for _ in range(8)]
    for t in threads:t.start()
    for t in threads:t.join()
   self.assertEqual(len(calls),1);self.assertEqual(VmBridge(folder).status()['connection_phase'],'booting')

 def test_thumbnail_poll_cannot_request_uac(self):
  with tempfile.TemporaryDirectory() as folder:
   b=VmBridge(folder)
   with patch.object(b,'launch_helper') as launch:
    with self.assertRaises(HubError):b.control('thumbnail',vm_name='Hub')
    launch.assert_not_called()

 def test_atomic_status_gap_uses_last_known_process(self):
  with tempfile.TemporaryDirectory() as folder:
   b=VmBridge(folder);p=b.root/'status.json';p.write_text(json.dumps({'updated':time.time(),'helper_pid':123,'protocol':4,'connected':True}),encoding='utf-8')
   with patch.object(VmBridge,'_process_alive',return_value=True):
    b.status();p.unlink();state=b.status()
   self.assertTrue(state['helper_alive']);self.assertTrue(state['connected'])

 def test_consumed_thumbnail_queue_race_does_not_kill_worker(self):
  import subprocess,os
  if os.name!='nt':self.skipTest('PowerShell fixture')
  source=(Path(__file__).parents[1]/'tools/Start-HubVmBridge.ps1').read_text(encoding='utf-8-sig')
  body=source.split('            try {$job=Get-Content',1)[1].split('            $actor=',1)[0]
  code='try {$job=Get-Content'+body
  with tempfile.TemporaryDirectory() as folder:
   script=Path(folder)/'race.ps1'
   script.write_text("$ErrorActionPreference='Stop'\n$passed=0\nforeach($n in 1..2){$file=[IO.FileInfo](Join-Path $PSScriptRoot 'removed.json');$resultPath='unused';\n"+code+"\n$passed++}\nif($passed -ne 0){throw 'Missing request executed'};Write-Output 'PASS'",encoding='utf-8-sig')
   r=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script)],capture_output=True,encoding='utf-8',errors='replace',timeout=10)
   self.assertEqual(r.returncode,0,r.stderr);self.assertIn('PASS',r.stdout)
