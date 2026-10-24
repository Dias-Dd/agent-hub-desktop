"""Offline real-Harness workspace probe: session lifecycle + confined file writes, no prompt/model call."""
import json,os,tempfile,time
from pathlib import Path
from hub.deepseek_harness import ACP,installation,patch_text,PERMISSION_PLUGIN
PROBE=r'''
const fs=require('node:fs');
exports.name='hub-offline-write-probe';exports.inject=['fs','sandboxPolicy','workingDirectory'];
exports.apply=(ctx,config)=>{ctx.on('session/created',async session=>{
 const policy=ctx.sandboxPolicy.resolve({session});const result={sessionId:session.id,policy,workingDirectory:ctx.workingDirectory.get(session),checks:[]};
 for(const item of config.files){try{const target=await ctx.fs.resolve(item.path);await ctx.fs.writeText(target,'hub-offline-probe',undefined,undefined,policy);result.checks.push({name:item.name,written:true,content:fs.readFileSync(item.path,'utf8')});}catch(error){result.checks.push({name:item.name,written:false,code:error.code,error:String(error.message)});}}
 fs.writeFileSync(config.record,JSON.stringify(result));
 });};
'''
def main():
 exe,cli=installation();results=[]
 probe_root=Path(__file__).resolve().parents[1]/'data'/'offline-probes';probe_root.mkdir(parents=True,exist_ok=True)
 with tempfile.TemporaryDirectory(prefix='hub-write-probe-',dir=probe_root) as directory:
  root=Path(directory);home=root/'home';home.mkdir();original=root/'original';original.mkdir();moved=root/'moved';moved.mkdir();outside=root/'outside';outside.mkdir()
  plugin=root/'permission.cjs';plugin.write_text(PERMISSION_PLUGIN,encoding='utf8');probe=root/'probe.cjs';probe.write_text(PROBE,encoding='utf8');session=None
  for index,(mode,target) in enumerate([('workspace-write',original),('workspace-write',moved),('read-only',moved),('danger-full-access',moved)]):
   record=root/f'permission-{index}.json';report=root/f'probe-{index}.json';patch=root/f'patch-{index}.yaml'
   rows=patch_text('offline-test','test',workspace_root=str(target),sandbox_mode=mode,permission_plugin=str(plugin),permission_record=str(record))
   files=[{'name':'inside','path':str(target/f'probe-{index}.txt')},{'name':'outside','path':str(outside/f'probe-{index}.txt')}]
   rows+='- '+json.dumps({'insert':[{'id':'hub-offline-write-probe','name':str(probe),'config':{'record':str(report),'files':files}}]})+'\n';patch.write_text(rows,encoding='utf8')
   env=dict(os.environ,ELECTRON_RUN_AS_NODE='1',DSH_HOME=str(home),DSH_PERMISSION_MODE=mode,DEEPSEEK_API_KEY='offline-probe-no-model-request')
   client=ACP([str(exe),'--expose-internals',str(cli),'--profile','acp','--patch',str(patch)],str(original),env)
   try:
    client.request('initialize',{'protocolVersion':1,'clientCapabilities':{},'clientInfo':{'name':'hub-offline-probe','version':'1'}})
    view=client.request('session/resume' if session else 'session/new',{'cwd':str(original),'mcpServers':[],**({'sessionId':session} if session else {})})
    if session:assert view.get('sessionId',session)==session
    else:session=view['sessionId']
    for _ in range(100):
     if report.exists():break
     time.sleep(.05)
    if not report.exists():raise RuntimeError('Probe did not finish: '+str(client.errors[-6:]))
    result=json.loads(report.read_text());expected=[True,False] if mode=='workspace-write' else [False,False] if mode=='read-only' else [True,True]
    assert result['sessionId']==session and Path(result['workingDirectory'])==target,result
    assert [r['written'] for r in result['checks']]==expected,result
    assert result['policy']['mode']==mode and Path(result['policy']['workspaceRoot'])==target,result
    results.append({'mode':mode,'same_session':True,'workspace_changed':index>0,'writes':[r['written'] for r in result['checks']]})
    client.request('session/close',{'sessionId':session})
   finally:client.close()
 print(json.dumps({'ok':True,'model_requests':0,'checks':results}))
if __name__=='__main__':main()
