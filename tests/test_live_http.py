import json,tempfile,threading,time,unittest,subprocess
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from hub.server import build

class HttpLive(unittest.TestCase):
 def test_authenticated_sse_arrives_before_completion_and_denies_other_project(self):
  with tempfile.TemporaryDirectory() as directory:
   s=build(directory,0,False);thread=threading.Thread(target=s.serve_forever);thread.start();base='http://127.0.0.1:'+str(s.server_port)
   headers={'Authorization':'Bearer '+s.hub.tokens['user']}
   try:
    project=s.projects.create('user','live');other=s.projects.create('user','other')
    with s.hub.tx():
     s.hub.db.execute("INSERT INTO tasks(id,agent,title,assigned_by,created,project_id) VALUES('live-task','deepseek-4','discussion','user',?,?)",(time.time(),project['id']))
     s.hub.db.execute("INSERT INTO executions(id,task_id,agent,status,purpose,provider,created,session_scope) VALUES('live-run','live-task','deepseek-4','running','discussion','deepseek',?,?)",(time.time(),'hub-project:'+project['id']))
    s.live.update('live-run','first public chunk')
    url=base+'/api/reply-stream?run=live-run'
    for request_headers in ({'X-Hub-Project':project['id']},{**headers,'X-Hub-Project':other['id']}):
     with self.assertRaises(HTTPError) as error:urlopen(Request(url,headers=request_headers),timeout=3)
     self.assertEqual(error.exception.code,403)
    with urlopen(Request(url,headers={**headers,'X-Hub-Project':project['id']}),timeout=3) as response:
     def event():
      while True:
       line=response.readline()
       if line.startswith(b'data: '):return json.loads(line[6:])
       if not line:raise AssertionError('stream ended before event')
     first=event();self.assertEqual(first['text'],'first public chunk');self.assertEqual(first['status'],'running')
     s.live.update('live-run',' + next')
     with s.hub.tx():s.hub.db.execute("UPDATE executions SET status='completed' WHERE id='live-run'")
     last=event();self.assertEqual(last['text'],'first public chunk + next')
     self.assertEqual(s.hub.db.execute('SELECT count(*) FROM planning_sessions').fetchone()[0],0)
   finally:
    s.stop_event.set();s.worker.join(5);s.shutdown();thread.join(5);s.quota_monitor.close();s.integrations.close();s.deepseek.close();s.codex.close();s.antigravity.close();s.server_close();s.hub.db.close();s.guard.close()
 def test_partial_json_public_report_parser(self):
  script=r"""const vm=require('vm'),fs=require('fs');const H={$:()=>({}),bind(){},store:{subscribe(){}}};const context={window:{HubDesktop:H,addEventListener(){}}};vm.runInNewContext(fs.readFileSync('hub/static/live-ui.js','utf8'),context);const visible=H.visibleLiveReply;const report='第一行\n第二行 "引号" '+String.fromCharCode(92)+'目录🙂';const raw=JSON.stringify({done:false,tasks:[{instruction:'"report":"fake"'}],report});for(let i=1;i<=raw.length;i++){const value=visible(raw.slice(0,i));if(!report.startsWith(value))throw Error('incorrect partial decode at '+i+' : '+value);}if(visible(raw)!==report)throw Error('complete decode');if(visible('```json'+String.fromCharCode(10)+raw)!==report)throw Error('fence decode');if(visible('plain reply')!=='plain reply')throw Error('plain reply');console.log('PASS partial JSON, escaping, nested fields, Unicode and code fences');"""
  result=subprocess.run(['node','-e',script],capture_output=True,text=True,timeout=10);self.assertEqual(result.returncode,0,result.stderr)
