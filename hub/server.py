import argparse
import gzip
import json
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from .core import Hub, HubError
from .connectors import Calls, CodexProbe
from .locking import acquire
from .setup import Setup
from .codex_runtime import CodexRuntime
from .antigravity import AntigravityRuntime
from .workflows import Workflows
from .coordination import Coordination
from .planning import Planning
from .projects import Projects
from .designs import Designs
from .manager_inbox import ManagerInbox
from .deepseek_runtime import DeepSeekRuntime
from .quota_monitor import QuotaMonitor
from .automation import Automation
from .live_replies import LiveReplies

class Server(ThreadingHTTPServer):
    daemon_threads=True
    allow_reuse_address=True
    # WebKit/Chromium load many deferred assets together; the default backlog
    # of five can reset local connections on macOS during first paint.
    request_queue_size=128

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def respond(self,status,body,kind='application/json'):
        raw=json.dumps(body,ensure_ascii=False,allow_nan=False).encode() if kind=='application/json' else body.encode()
        compressed=kind=='application/json' and len(raw)>32768 and 'gzip' in self.headers.get('Accept-Encoding','').lower()
        if compressed:raw=gzip.compress(raw,compresslevel=1)
        self.send_response(status)
        if compressed:self.send_header('Content-Encoding','gzip')
        self.send_header('Vary','Accept-Encoding')
        self.send_header('Content-Type',kind+'; charset=utf-8')
        self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers();self.write_body(raw)

    def write_body(self,raw):
        try:self.wfile.write(raw)
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass

    def check(self):
        host=self.headers.get('Host','')
        port=self.server.server_address[1]
        if host not in (f'127.0.0.1:{port}',f'localhost:{port}'):
            raise HubError('invalid Host')
        origin=self.headers.get('Origin')
        if origin and origin not in (f'http://127.0.0.1:{port}',f'http://localhost:{port}'):
            raise HubError('invalid Origin')

    def actor(self):
        header=self.headers.get('Authorization','')
        return self.server.hub.auth(header[7:] if header.startswith('Bearer ') else '')

    def do_GET(self):
        try:
            self.check()
            if self.path in ('/i18n.js','/i18n.json'):
                name=self.path[1:]
                body=(Path(__file__).parent/'static'/name).read_text(encoding='utf-8')
                return self.respond(200,body if name.endswith('.js') else json.loads(body),'text/javascript' if name.endswith('.js') else 'application/json')
            if self.path in ('/module-configuration.js','/render-notifications.js','/memory.js','/colors.js','/titlebar.js','/modern.css','/popup.html','/popup.js','/windows.js','/windows.css','/','/setup','/startup.js','/vm-ui.js','/api-client.js','/state-store.js','/app.js','/codex.js','/antigravity.js','/setup.js','/workflow.js','/deepseek.js','/style.css','/design.js','/design.css','/integrations.js','/integrations.css','/automation.js','/project-setup.js','/live-ui.js','/hub-mark.svg'):
                name={'/module-configuration.js':'module-configuration.js','/render-notifications.js':'render-notifications.js','/memory.js':'memory.js','/colors.js':'colors.js','/titlebar.js':'titlebar.js','/modern.css':'modern.css','/popup.html':'popup.html','/popup.js':'popup.js','/windows.js':'windows.js','/windows.css':'windows.css','/startup.js':'startup.js','/vm-ui.js':'vm-ui.js','/hub-mark.svg':'hub-mark.svg','/project-setup.js':'project-setup.js','/live-ui.js':'live-ui.js','/automation.js':'automation.js','/integrations.js':'integrations.js','/integrations.css':'integrations.css','/design.js':'design.js','/design.css':'design.css','/api-client.js':'api-client.js','/state-store.js':'state-store.js','/deepseek.js':'deepseek.js','/workflow.js':'workflow.js','/':'index.html','/setup':'index.html','/setup.js':'setup.js','/codex.js':'codex.js','/antigravity.js':'antigravity.js','/app.js':'app.js','/style.css':'style.css'}[self.path]
                kind={'/module-configuration.js':'text/javascript','/render-notifications.js':'text/javascript','/memory.js':'text/javascript','/colors.js':'text/javascript','/titlebar.js':'text/javascript','/modern.css':'text/css','/popup.html':'text/html','/popup.js':'text/javascript','/windows.js':'text/javascript','/windows.css':'text/css','/startup.js':'text/javascript','/vm-ui.js':'text/javascript','/hub-mark.svg':'image/svg+xml','/project-setup.js':'text/javascript','/live-ui.js':'text/javascript','/automation.js':'text/javascript','/integrations.js':'text/javascript','/integrations.css':'text/css','/design.js':'text/javascript','/design.css':'text/css','/api-client.js':'text/javascript','/state-store.js':'text/javascript','/deepseek.js':'text/javascript','/workflow.js':'text/javascript','/':'text/html','/setup':'text/html','/setup.js':'text/javascript','/codex.js':'text/javascript','/antigravity.js':'text/javascript','/app.js':'text/javascript','/style.css':'text/css'}[self.path]
                self.respond(200,(Path(__file__).parent/'static'/name).read_text(encoding='utf-8'),kind)
            elif self.path.startswith('/api/reply-stream?'):
                self.server.hub.require(self.actor(),{'user'})
                project=self.headers.get('X-Hub-Project');self.server.projects.get(project)
                run=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get('run',[''])[0]
                self.server.live.read(run,project)
                self.send_response(200);self.send_header('Content-Type','text/event-stream; charset=utf-8')
                self.send_header('Cache-Control','no-store');self.send_header('X-Accel-Buffering','no');self.end_headers()
                end=time.monotonic()+20;previous=None
                try:
                    while time.monotonic()<end and not self.server.stop_event.is_set():
                        data=self.server.live.read(run,project);signature=(data['revision'],data['status'])
                        if signature!=previous:
                            self.wfile.write(('data: '+json.dumps(data,ensure_ascii=False)+'\n\n').encode('utf-8'));self.wfile.flush();previous=signature
                        if data['status'] not in ('queued','running','interrupting'):break
                        self.server.stop_event.wait(.15)
                except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError,OSError,HubError):pass
                self.close_connection=True
            elif self.path.startswith('/api/shared/'):

                parts=urllib.parse.unquote(urllib.parse.urlsplit(self.path).path).split('/',4)
                if len(parts)!=5:raise HubError('展示地址无效')
                raw,kind=self.server.automation.asset(parts[3],parts[4])
                self.send_response(200);self.send_header('Content-Type',kind+('; charset=utf-8' if kind.startswith('text/') else ''));self.send_header('Content-Length',str(len(raw)))
                self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
                self.send_header('Referrer-Policy','no-referrer')
                self.send_header('Content-Security-Policy',"default-src 'none'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; script-src 'none'; connect-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'self'; sandbox")
                self.end_headers();self.write_body(raw)
            elif self.path.startswith('/api/design-preview/'):

                ticket=self.path.rsplit('/',1)[-1];item=self.server.design_tickets.get(ticket)
                if not item or item[0]<time.time():self.respond(404,{'error':'preview expired'});return
                raw=item[1].encode('utf-8');self.send_response(200)
                self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(raw)))
                self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
                self.send_header('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; script-src 'none'; connect-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'self'; sandbox allow-same-origin")
                self.end_headers();self.write_body(raw)
            elif self.path=='/favicon.ico':
                self.respond(204,'','image/x-icon')
            elif self.path=='/api/state':
                actor=self.actor();state=self.server.hub.snapshot(actor);state['simulation']=self.server.simulate
                state['all_deepseek']=all(a['connection_id']=='deepseek-default' for a in self.server.integrations.rows('agent_profiles') if a['enabled'])
                state['integrations']=self.server.integrations.snapshot()
                state['real_agents']=sorted(set().union(*(r.real_agents() for r in self.server.workflows.runtimes)))
                state['integration_runs']=[dict(r) for r in self.server.hub.db.execute("SELECT id,agent,status,provider,model,prompt,created,started,finished FROM executions WHERE provider LIKE 'integration:%' ORDER BY created DESC LIMIT 150")]
                profiles={a['id']:a for a in state['integrations']['agents']}
                state['agents']=[{**a,'profile':profiles[a['id']]} for a in state['agents'] if a['id'] in profiles and profiles[a['id']]['enabled']]

                if actor=='user':
                    state['planning']=self.server.planning.snapshot(actor)
                    state['coordination']=self.server.coordination.snapshot(actor)
                    state['workflows']=self.server.workflows.snapshot(actor)
                    state['manager_patrol']=self.server.workflows.patrol_config(actor)
                    state['codex']=self.server.codex.snapshot(actor)
                    state['antigravity']=self.server.antigravity.snapshot(actor)
                    state['deepseek']=self.server.deepseek.status(actor)
                    state['deepseek'].update(self.server.deepseek.snapshot(actor))
                    state['quota_alerts']=[]
                    state=self.server.projects.state(state,self.headers.get('X-Hub-Project'))
                    from .long_term_memory import updates as memory_updates,current as memory_current
                    state['memory_updates']=memory_updates(self.server.hub,state.get('selected_project'))
                    state['memory_revision']=memory_current(self.server.hub)['revision']
                    state['designs']=self.server.designs.snapshot(state.get('selected_project'))
                    state['timers']=self.server.automation.timers(state.get('selected_project'),include_finished=False)
                    state['pending_notifications']=self.server.automation.notifications(state.get('selected_project'))
                    state['quota_overview']=self.server.integrations.quota_overview()
                    state['live_replies']=self.server.live.snapshot(state.get('selected_project'))
                    state['shared_artifacts']=self.server.automation.artifacts(state.get('selected_project'))
                    if state['designs'] and state['designs'][0]['state'] in ('building','review'):
                        review=state['designs'][0];state['project']={'progress':15 if review['state']=='building' else 25,'note':'产品演示制作中；尚未实施真实产品' if review['state']=='building' else '演示已就绪，等待用户确认最终设计；尚未实施真实产品','stage':'design'}
                self.respond(200,state)
            elif self.path=='/health':
                self.actor()
                fresh=time.monotonic()-self.server.last_tick<10
                self.respond(200 if fresh else 503,{'ok':fresh,'supervisor':'running' if fresh else 'stale','simulation':self.server.simulate,'desktop_build':getattr(self.server,'desktop_build',None)})
            else:self.respond(404,{'error':'not found'})
        except HubError as e:self.respond(403,{'error':str(e)})

    def do_POST(self):
        try:
            self.check();actor=self.actor()
        except HubError as e:
            self.respond(403,{'error':str(e)})
            return
        try:
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':raise HubError('application/json required')
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=262144:raise HubError('invalid body length')
            self.connection.settimeout(5)
            data=json.loads(self.rfile.read(length))
            if not isinstance(data,dict):raise HubError('object required')
            if self.path!='/api/action':raise HubError('unknown endpoint')
            action=data.get('action');args=data.get('args',{})
            if not isinstance(args,dict):raise HubError('arguments must be object')
            if actor!='user':
                bound=self.headers.get('X-Hub-Run')
                if bound:
                    with self.server.hub.lock:execution=self.server.hub.db.execute('SELECT * FROM executions WHERE id=? AND agent=?',(bound,actor)).fetchone()
                    if not execution:raise HubError('工具调用不属于当前执行身份')
                    if args.get('run_id',bound)!=bound:raise HubError('工具调用的执行编号不一致')
                    from .module_tools import guard as execution_guard
                    execution_guard(self.server.workflows.runtime(actor),dict(execution))
                with self.server.hub.lock:
                    aligning=self.server.hub.db.execute("SELECT 1 FROM executions WHERE agent=? AND purpose='alignment' AND status IN ('queued','running','interrupting','waiting_quota') LIMIT 1",(actor,)).fetchone()
                if aligning and action!='project_vm':raise HubError('需求对齐阶段平台工具尚未启用，请由用户点击开始计划')
            selected=self.headers.get('X-Hub-Project')
            if actor=='user' and selected and action in ('send','plan_chat','workflow_start','prepare'):
                self.server.projects.get(selected);args={**args,'project_id':selected}
            if action in ('integration_adapters','integration_connection_save','integration_agent_save','integration_agent_archive','integration_probe','integration_quota','integration_model_options','integration_wizard_add','integration_set_manager','integration_quota_refresh','integration_client_model','integration_test_all'):
                method={'integration_adapters':'adapters','integration_connection_save':'save_connection','integration_agent_save':'save_agent','integration_agent_archive':'archive_agent','integration_probe':'probe','integration_quota':'quota','integration_model_options':'probe_model','integration_wizard_add':'wizard_add','integration_set_manager':'set_manager','integration_quota_refresh':'refresh_quota','integration_client_model':'add_client_model','integration_test_all':'test_all'}[action]
                result=getattr(self.server.integrations,method)(actor,**args)
            elif action=='render_settings':
                from .render_settings import action as render_action
                result=render_action(self.server.hub,actor,**args)
            elif action=='notification_settings':
                from .notification_settings import action as notification_action
                result=notification_action(self.server.hub,actor,**args)
            elif action=='memory':
                from .long_term_memory import action as memory_action
                result=memory_action(self.server.hub,actor,**args)
            elif action=='desktop_onboarding':
                from desktop.first_run import action as onboarding_action
                result=onboarding_action(self.server.hub,actor,**args)
            elif action=='integration_submit':
                result=self.server.workflows.runtime(args['agent']).submit(actor,**args)
            elif action=='integration_stop':
                result=self.server.workflows.runtime(args.pop('agent')).stop(actor,**args)
            elif action in ('project_open_directory','project_update','project_delete','project_rename'):result=getattr(self.server.projects,{'project_open_directory':'open_directory','project_update':'update','project_delete':'delete','project_rename':'rename'}[action])(actor,**args)
            elif action=='project_storage':result=self.server.projects.storage(actor,**args)
            elif action=='project_cleanup':result=self.server.projects.cleanup(actor,**args)
            elif action=='project_git_tree':result=self.server.projects.git_tree(actor,**args)
            elif action=='artifact_open_folder':result=self.server.automation.open_folder(actor,**args)
            elif action=='vm_control':
                self.server.hub.require(actor,{'user'})
                from .vm_bridge import VmBridge
                result=VmBridge(self.server.hub.directory).control(**args)
            elif action=='project_browse_directory':result=self.server.projects.browse_directory(actor,**args)
            elif action=='project_create':result=self.server.projects.create(actor,**args)
            elif action=='project_select':result=self.server.projects.select(actor,**args)
            elif action=='project' and args.get('run_id'):result=self.server.workflows.project_progress(actor,**args)
            elif action in ('project_git','project_status','project_assign','report_result','project_complete','project_mailbox','project_set_role','project_cancel_task','project_stop_task','project_queue','project_return_manager','project_schedule_wake'):
                result=getattr(self.server.workflows,action)(actor,**args)
            elif action in ('project_vm','schedule_wake','timer_list','timer_cancel','browser_render','publish_artifact'):
                result=getattr(self.server.automation,action)(actor,**args)
            elif action=='workflow_switch_manager':result=self.server.workflows.switch_manager(actor,**args)
            elif action=='manager_patrol_config':result=self.server.workflows.patrol_config(actor,**args)
            elif action=='workflow_set_patrol':result=self.server.workflows.set_patrol(actor,**args)
            elif action=='workflow_resume':result=self.server.workflows.resume(actor,**args)
            elif action=='workflow_wake':result=self.server.workflows.wake(actor,**args)
            elif action=='plan_recover':result=self.server.planning.recover_result(actor,**args)
            elif action in ('design_start','design_content','design_feedback','design_accept','design_skip'):
                method={'design_skip':'skip','design_start':'start','design_content':'content','design_feedback':'feedback','design_accept':'accept'}[action]
                result=getattr(self.server.designs,method)(actor,**{**args,'project_id':selected or args.get('project_id')})
                if action=='design_content':
                    self.server.design_tickets={k:v for k,v in self.server.design_tickets.items() if v[0]>time.time()}
                    urls={}
                    for page,html in result.pop('html').items():
                        import secrets
                        ticket=secrets.token_urlsafe(32);self.server.design_tickets[ticket]=(time.time()+3600,html);urls[page]='/api/design-preview/'+ticket
                    result['urls']=urls
            elif action in ('manager_message','manager_interrupt'):
                result=getattr(self.server.manager_inbox,'send' if action=='manager_message' else 'interrupt')(actor,**{**args,'project_id':selected or args.get('project_id')})
            elif action=='plan_chat':result=self.server.planning.message(actor,**args)
            elif action=='agent_halt':result=self.server.coordination.halt(actor,**args)
            elif action=='agent_resume':result=self.server.coordination.resume(actor,**args)
            elif action=='send':result=self.server.coordination.send(actor,**args)
            elif action=='workflow_start':result=self.server.workflows.start(actor,**args)
            elif action=='workflow_stop':result=self.server.workflows.stop(actor,**args)
            elif action in ('deepseek_status','deepseek_save_key','deepseek_validate','deepseek_configure_api'):
                result=getattr(self.server.deepseek,action.removeprefix('deepseek_'))(actor,**args)
            elif action=='agent_set_effort':result=self.server.integrations.set_effort(actor,**{**args,'project_id':selected or args.get('project_id')})
            elif action=='deepseek_submit':result=self.server.deepseek.submit(actor,**args)
            elif action=='deepseek_stop':result=self.server.deepseek.stop(actor,**args)
            elif action=='backup_authorize':result=self.server.quota_monitor.authorize(actor,**args)
            elif action=='setup_status':result=self.server.setup.status(actor,**args)
            elif action=='integration_setup':result=self.server.integrations.connection_setup(actor,**args)
            elif action=='integration_module_config':result=self.server.integrations.module_configure(actor,**args)
            elif action=='setup_save':result=self.server.setup.save(actor,**args)
            elif action=='codex_configure':result=self.server.codex.configure(actor,**args)
            elif action=='codex_submit':result=self.server.codex.submit(actor,**args)
            elif action=='codex_stop':result=self.server.codex.stop(actor,**args)
            elif action=='antigravity_configure':result=self.server.antigravity.configure(actor,**args)
            elif action=='antigravity_submit':result=self.server.antigravity.submit(actor,**args)
            elif action=='antigravity_stop':result=self.server.antigravity.stop(actor,**args)
            elif action=='refresh_antigravity':result=self.server.antigravity.refresh(actor,**args)
            elif action=='refresh_openai':
                self.server.hub.require(actor,{'user'})
                result=CodexProbe().run()
                with self.server.hub.tx():
                    self.server.hub.db.execute("INSERT OR REPLACE INTO settings VALUES('openai_limits',?)",(json.dumps({'observed_at':time.time(),'scope':'账号共享；按 bucket 解读，不代表每个 Agent 独立额度','data':result}),))
                    self.server.hub.audit(actor,'quota.official_read',{'provider':'openai'})
            elif action in ('budget','prepare','approve','execute','cancel'):
                raise HubError('旧费用审批接口已停用；请使用当前接入连接的配置')
            else: result=self.server.hub.action(actor,action,args)
            self.respond(200,{'result':result})
        except (HubError,ValueError,TypeError) as e:self.respond(400,{'error':str(e)})
        except Exception:self.respond(500,{'error':'internal error; inspect service state'})

def build(directory,port=8765,simulate=True,prebound=None,seed_defaults=True):
    # Bind first: a second instance cannot reset the first instance's durable state.
    guard=acquire(directory,'service.lock')
    try:
        server=prebound if prebound is not None else Server(('127.0.0.1',port),Handler)
        server.hub=Hub(directory,seed_defaults=seed_defaults)
    except Exception:
        guard.close()
        raise
    server.guard=guard
    server.hub.url='http://127.0.0.1:'+str(server.server_address[1])
    server.calls=Calls(server.hub)
    server.simulate=simulate
    server.setup=Setup(server.hub,simulate)
    (server.hub.directory/'projects').mkdir(exist_ok=True)
    server.codex=CodexRuntime(server.hub)
    server.antigravity=AntigravityRuntime(server.hub)
    server.deepseek=DeepSeekRuntime(server.hub)
    server.codex.models={};server.antigravity.models={}
    server.workflows=Workflows(server.hub,[server.codex,server.antigravity,server.deepseek])
    server.hub.workflows=server.workflows
    server.coordination=Coordination(server.hub,[server.codex,server.antigravity,server.deepseek],server.workflows)
    server.planning=Planning(server.hub,server.antigravity,server.workflows)
    server.projects=Projects(server.hub)
    server.designs=Designs(server.hub,server.planning,server.workflows);server.design_tickets={}
    from .integrations import Integrations
    server.integrations=Integrations(server);server.hub.integrations=server.integrations
    server.automation=Automation(server);server.hub.automation=server.automation
    server.live=LiveReplies(server.hub);server.hub.live=server.live
    server.integrations.start()
    server.manager_inbox=ManagerInbox(server.hub,server.planning,server.workflows,server.coordination)
    server.quota_monitor=QuotaMonitor(server.hub,server.workflows,server.codex,server.antigravity,server.deepseek)
    server.hub.quota_monitor=server.quota_monitor
    server.integrations.start_quota_refresh()
    server.deepseek.start()
    server.codex.start()
    server.antigravity.start()
    server.last_tick=time.monotonic()
    server.stop_event=threading.Event()
    def supervise():
        while not server.stop_event.is_set():
            try:
                server.hub.tick(simulate,set().union(*(r.real_agents() for r in server.workflows.runtimes)))
                server.live.flush()
                server.automation.patrol()
                server.integrations.patrol_changes()
                server.planning.patrol()
                server.manager_inbox.patrol()
                server.coordination.patrol()
                server.quota_monitor.patrol()
                server.workflows.patrol()
                server.projects.tag()
                server.last_tick=time.monotonic()
            except Exception as e:
                with server.hub.tx():server.hub.audit('supervisor','tick.error',{'type':type(e).__name__})
            with server.hub.lock:active=server.hub.db.execute("SELECT 1 FROM executions WHERE status IN ('queued','running','interrupting') LIMIT 1").fetchone()
            server.stop_event.wait(.25 if active else 1)
    server.worker=threading.Thread(target=supervise,daemon=True)
    server.worker.start()
    return server

def main():
    p=argparse.ArgumentParser();p.add_argument('--data',default='data');p.add_argument('--port',type=int,default=8765);p.add_argument('--no-sim',action='store_true')
    args=p.parse_args()
    server=build(args.data,args.port,not args.no_sim)
    print(f'Deskfellows: http://127.0.0.1:{server.server_address[1]}',flush=True)
    print('User token: '+server.hub.tokens['user'],flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:
        server.stop_event.set();server.worker.join(timeout=5);server.quota_monitor.close();server.integrations.close();server.deepseek.close();server.codex.close();server.antigravity.close();server.server_close();server.hub.db.close();server.guard.close()

if __name__=='__main__':main()
