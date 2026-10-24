"""Official ACP handshake and model selection only; no session/prompt calls."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hub.integrations import locate,command
from hub.deepseek_harness import ACP
from hub.workbuddy_catalog import acp_arguments,environment,acp_models

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--model',action='append',default=[]);parser.add_argument('--result-file',type=Path);args=parser.parse_args()
 exe=locate('workbuddy')
 if not exe:raise RuntimeError('WorkBuddy not installed')
 client=ACP(command(acp_arguments(exe)),str(Path.cwd()),environment())
 try:
  info=client.request('initialize',{'protocolVersion':1,'clientCapabilities':{},'clientInfo':{'name':'agent-message-hub-probe','version':'0.3'}},timeout=20)
  view=client.request('session/new',{'cwd':str(Path.cwd()),'mcpServers':[]},timeout=20)
  selected={}
  for model in args.model:
   changed=client.request('session/set_config_option',{'sessionId':view['sessionId'],'configId':'model','value':model},timeout=10)
   selected[model]=next((x.get('currentValue') for x in changed.get('configOptions',[]) if x.get('id')=='model'),None)==model
  result={'protocolVersion':info.get('protocolVersion'),'session_created':bool(view.get('sessionId')),'dynamic_models':[m['id'] for m in acp_models(view)],'selection_confirmed':selected,'inference_requested':False}
  if args.result_file:args.result_file.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
  print(json.dumps(result,ensure_ascii=True));return 0 if all(selected.values()) else 1
 finally:client.close()
if __name__=='__main__':raise SystemExit(main())
