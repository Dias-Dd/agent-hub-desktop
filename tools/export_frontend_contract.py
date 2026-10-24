"""Export actual HTTP action signatures without starting Hub or reading credentials."""
import ast
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GROUPS={
    'hub/vm_bridge.py':('VmBridge',{'vm_control':'control'}),
    'hub/automation.py':('Automation',{'artifact_open_folder':'open_folder',**{n:n for n in ('project_vm','schedule_wake','timer_list','timer_cancel','browser_render','publish_artifact')}}),
    'hub/integrations.py':('Integrations',{'integration_connection_save':'save_connection','integration_agent_save':'save_agent','integration_agent_archive':'archive_agent','integration_probe':'probe','integration_client_model':'add_client_model','integration_test_all':'test_all','integration_model_options':'probe_model','integration_wizard_add':'wizard_add','integration_set_manager':'set_manager','integration_quota':'quota','integration_quota_refresh':'refresh_quota','agent_set_effort':'set_effort'}),
    'hub/projects.py':('Projects',{'project_create':'create','project_select':'select','project_browse_directory':'browse_directory','project_update':'update','project_delete':'delete','project_rename':'rename','project_open_directory':'open_directory','project_storage':'storage','project_cleanup':'cleanup','project_git_tree':'git_tree'}),
    'hub/core.py':('Hub',{'snapshot':'snapshot','heartbeat':'heartbeat','poll':'poll','ack':'ack','assign':'assign','progress':'progress','project':'project','quota':'quota','enable':'enable'}),
    'hub/coordination.py':('Coordination',{'send':'send','agent_halt':'halt','agent_resume':'resume'}),
    'hub/manager_inbox.py':('ManagerInbox',{'manager_message':'send','manager_interrupt':'interrupt'}),
    'hub/designs.py':('Designs',{'design_start':'start','design_skip':'skip','design_content':'content','design_feedback':'feedback','design_accept':'accept'}),
    'hub/workflows.py':('Workflows',{**{'project_'+n:'project_'+n for n in ('git','status','assign','complete','mailbox','set_role','cancel_task','stop_task','queue','return_manager')},'report_result':'report_result','workflow_start':'start','workflow_stop':'stop','workflow_wake':'wake','workflow_resume':'resume','workflow_set_patrol':'set_patrol','manager_patrol_config':'patrol_config'}),
    'hub/planning.py':('Planning',{'plan_chat':'message','plan_recover':'recover_result'}),
    'hub/setup.py':('Setup',{'setup_status':'status','setup_save':'save'}),
    'hub/codex_runtime.py':('CodexRuntime',{**{'codex_'+n:n for n in ('configure','submit','stop')},'antigravity_submit':'submit','antigravity_stop':'stop'}),
    'hub/antigravity.py':('AntigravityRuntime',{'antigravity_configure':'configure','refresh_antigravity':'refresh'}),
    'hub/deepseek_runtime.py':('DeepSeekRuntime',{'deepseek_status':'status','deepseek_save_key':'save_key','deepseek_validate':'validate','deepseek_configure_api':'configure_api'}),
    'hub/quota_monitor.py':('QuotaMonitor',{'backup_authorize':'authorize'}),
    'hub/connectors.py':('Calls',{n:n for n in ('budget','prepare','approve','execute','cancel')}),
}
RUNTIME_ONLY={'project_git','heartbeat','poll','ack','progress','project','project_status','project_assign','project_complete','project_mailbox','project_set_role','project_cancel_task','project_stop_task','project_queue','project_return_manager','report_result','schedule_wake','timer_list','publish_artifact'}

def export():
    actions={}
    for file,(cls_name,mapping) in GROUPS.items():
        tree=ast.parse((ROOT/file).read_text(encoding='utf-8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==cls_name)
        methods={n.name:n for n in cls.body if isinstance(n,ast.FunctionDef)}
        for action,method in mapping.items():
            fn=methods[method];args=fn.args.args;defaults=[None]*(len(args)-len(fn.args.defaults))+fn.args.defaults
            params=[]
            for arg,default in zip(args,defaults):
                if arg.arg in ('self','actor'):continue
                item={'name':arg.arg,'required':default is None}
                if default is not None:item['default']=ast.literal_eval(default)
                params.append(item)
            actions[action]={'source':file,'method':cls_name+'.'+method,'line':fn.lineno,'parameters':params,'audience':'agent_runtime_only' if action in RUNTIME_ONLY else 'user_dashboard','requires_source_validation':True}
    actions['deepseek_stop']={**actions['codex_stop'],'source':'hub/codex_runtime.py','method':'DeepSeekRuntime.stop (inherited)'}
    actions['integration_submit']={**actions['codex_submit'],'source':'hub/server.py','method':'Workflows.runtime(agent).submit'}
    actions['integration_stop']={**actions['codex_stop'],'source':'hub/server.py','method':'Workflows.runtime(agent).stop','parameters':[{'name':'agent','required':True}]+actions['codex_stop']['parameters']}
    actions['refresh_openai']={'source':'hub/server.py','method':'Handler.do_POST / refresh_openai','parameters':[],'audience':'user_dashboard','requires_source_validation':True}
    result={'version':'hub-v0.1-source-signatures','note':'参数和默认值来自源码；类型、范围、角色与前置条件仍以方法验证为准。这不是完整OpenAPI，也不是所有参数都应暴露给用户。','transport':{'origin':'http://127.0.0.1:8765','read':'GET /api/state','health':'GET /health','write':'POST /api/action','write_body':{'action':'ACTION_NAME','args':{}},'success':{'result':'ACTION_RESULT'},'error':{'error':'MESSAGE'},'authentication':'Authorization: Bearer <local user token>','project_header':'X-Hub-Project: <hub_projects.id>'},'actions':actions}
    path=ROOT/'docs/frontend-actions.json';path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result

if __name__=='__main__':
    result=export();print('Exported',len(result['actions']),'action signatures; no service or model calls.')
