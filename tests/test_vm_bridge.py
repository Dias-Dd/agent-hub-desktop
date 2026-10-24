import json
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path
from hub.core import HubError
from hub.vm_bridge import VmBridge
from hub.mcp import TOOLS


class Bridge(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bridge = VmBridge(self.root)
        (self.bridge.root / 'status.json').write_text(json.dumps({'updated': time.time(), 'vm': 'Hub'}))

    def test_archived_control_request_remains_queryable(self):
        ident='a'*32;archive=self.bridge.root/'request-history';archive.mkdir()
        (archive/(ident+'.json')).write_text(json.dumps({'control':True,'action':'list'}),encoding='utf-8')
        (self.bridge.results/(ident+'.json')).write_text(json.dumps({'state':'completed','vms':[]}),encoding='utf-8')
        self.assertEqual(self.bridge.control(action='result',request_id=ident)['state'],'completed')

    def test_archived_operation_still_checks_project_and_agent(self):
        ident='b'*32;archive=self.bridge.root/'request-history';archive.mkdir()
        (archive/(ident+'.json')).write_text(json.dumps({'project':'p','agent':'a'}),encoding='utf-8')
        (self.bridge.results/(ident+'.json')).write_text(json.dumps({'state':'completed','output':'proof'}),encoding='utf-8')
        self.assertEqual(self.bridge.call('p','a',self.root,action='result',request_id=ident)['output'],'proof')
        with self.assertRaises(HubError):self.bridge.call('p','other',self.root,action='result',request_id=ident)

    def test_prompt_reports_real_vm_privilege_and_stale_connection(self):
        from types import SimpleNamespace
        from hub.prompt_identity import vm_context
        hub=SimpleNamespace(directory=self.root)
        (self.bridge.root/'status.json').write_text(json.dumps({'updated':time.time(),'connected':True,'command_elevated':True}),encoding='utf-8')
        self.assertIn('当前虚拟机：已连接',vm_context(hub))
        self.assertIn('命令管理员权限：已确认',vm_context(hub))
        (self.bridge.root/'status.json').write_text(json.dumps({'updated':0,'connected':True}),encoding='utf-8')
        self.assertIn('当前虚拟机：未连接',vm_context(hub))
        self.assertIn('待核实',vm_context(hub))

    def test_compact_manager_policy_preserves_git_and_vm_guidance(self):
        from hub.manager_input import POLICY,content
        self.assertIn('project_git',POLICY)
        self.assertIn('integrate',POLICY)
        self.assertIn('project_vm',POLICY)
        self.assertIn('command_elevated',POLICY)
        self.assertIn('pull',POLICY)
        original='用户原始消息'*1000
        self.assertTrue(content(POLICY,original).endswith(original))

    def test_broken_session_does_not_report_ready_or_elevated(self):
        path=self.bridge.root/'status.json'
        path.write_text(json.dumps({'updated':time.time(),'connected':False,'connection_phase':'ready','command_elevated':True,'auto_reconnect':True,'desktop':{'ready':True}}),encoding='utf-8')
        state=self.bridge.status()
        self.assertEqual(state['connection_phase'],'reconnecting')
        self.assertIsNone(state['command_elevated'])
        self.assertFalse(state['desktop']['ready'])
        before=list(self.bridge.requests.glob('*.json'))
        with self.assertRaisesRegex(HubError,'本次操作尚未提交'):
            self.bridge.call('p','a',self.root,action='exec',script='whoami')
        self.assertEqual(before,list(self.bridge.requests.glob('*.json')))

    def test_disconnected_and_stale(self):
        (self.bridge.root / 'status.json').unlink()
        self.assertFalse(self.bridge.status()['connected'])
        with self.assertRaises(HubError):
            self.bridge.call('p', 'a', self.root, action='exec', script='whoami')
        (self.bridge.root / 'status.json').write_text('{"updated":0}')
        self.assertFalse(self.bridge.status()['connected'])

    def test_async_exec_and_result_ownership(self):
        result = self.bridge.call('p', 'a', self.root, action='exec', script='whoami')
        ident = result['request_id']
        job = json.loads((self.bridge.requests / (ident + '.json')).read_text())
        self.assertEqual(job['guest_cwd'], r'C:\HubWorkspace\p\a')
        self.assertEqual(job['script'], 'whoami')
        self.assertEqual(self.bridge.call('p', 'a', self.root, request_id=ident)['state'], 'queued')
        (self.bridge.results / (ident + '.json')).write_text(json.dumps({'state': 'completed', 'output': 'ok'}))
        self.assertEqual(self.bridge.call('p', 'a', self.root, request_id=ident)['output'], 'ok')
        with self.assertRaises(HubError):
            self.bridge.call('p', 'b', self.root, request_id=ident)
        with self.assertRaises(HubError):
            self.bridge.call('other', 'a', self.root, request_id=ident)

    def test_desktop_launch_uses_interactive_worker_and_member_path(self):
        import base64,re
        result=self.bridge.call('p','a',self.root,action='desktop_launch',path='dist/app.exe',value='--about')
        job=json.loads((self.bridge.requests/(result['request_id']+'.json')).read_text())
        self.assertEqual(job['desktop_action'],'desktop_launch')
        encoded=re.search(r"FromBase64String\('([^']+)'\)",job['script']).group(1)
        payload=json.loads(base64.b64decode(encoded))
        self.assertEqual(payload['executable'],r'C:\HubWorkspace\p\a\dist\app.exe')
        self.assertEqual(payload['value'],'--about')
        with self.assertRaises(HubError):self.bridge.call('p','a',self.root,action='desktop_launch',path='../other/app.exe')

    def test_transfers_use_member_cwd(self):
        (self.root / 'hello.txt').write_text('hello')
        result = self.bridge.call('p', 'a', self.root, action='push', path='hello.txt')
        job = json.loads((self.bridge.requests / (result['request_id'] + '.json')).read_text())
        self.assertEqual(job['local_path'], str(self.root / 'hello.txt'))
        self.assertEqual(job['guest_path'], r'C:\HubWorkspace\p\a\hello.txt')
        for path in ('../outside', r'C:\Windows', r'\\server\share', 'file:stream'):
            with self.subTest(path=path), self.assertRaises(HubError):
                self.bridge.call('p', 'a', self.root, action='pull', path=path)

    def test_invalid_requests_and_tool_schema(self):
        for kwargs in ({'action': 'exec', 'script': ''}, {'action': 'exec', 'script': 'x', 'timeout_seconds': True}, {'action': 'mouse'}, {'request_id': '../outside'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(HubError):
                self.bridge.call('p', 'a', self.root, **kwargs)
        tools = [t for t in TOOLS if t[0] == 'project_vm']
        self.assertEqual(len(tools), 1)
        self.assertTrue({'status','exec','push','pull','screenshot','ui_set_value','key','mouse'}.issubset(tools[0][2]['properties']['action']['enum']))

    def test_control_connect_only_writes_protected_handoff(self):
        with patch.object(self.bridge, 'launch_helper'), patch.object(self.bridge, 'protect_credentials', return_value='ENCRYPTED'):
            result=self.bridge.control('connect',vm_name='Hub',username='fixture',password='not-a-real-password')
        source=self.bridge.requests/(result['request_id']+'.json')
        raw=source.read_text()
        self.assertNotIn('not-a-real-password',raw)
        self.assertNotIn('fixture',raw)
        self.assertEqual(json.loads(raw)['credential_encrypted'],'ENCRYPTED')
        self.assertTrue(json.loads(raw)['unattended'])
        self.assertEqual(self.bridge.control('result',request_id=result['request_id'])['state'],'queued')
        with self.assertRaises(HubError):self.bridge.call('p','a',self.root,request_id=result['request_id'])

    def test_unattended_choice_survives_saved_connections(self):
        saved=self.bridge.saved_path('Hub');saved.parent.mkdir(parents=True,exist_ok=True)
        saved.write_text(json.dumps({'vm':'Hub','account':'fixture','credential_encrypted':'ENCRYPTED','unattended':False}),encoding='utf-8')
        self.assertFalse(self.bridge.saved_connections()[0]['unattended'])
        with patch.object(self.bridge,'launch_helper'):
            request=self.bridge.control('connect_saved',vm_name='Hub')
        job=json.loads((self.bridge.requests/(request['request_id']+'.json')).read_text())
        self.assertFalse(job['unattended'])
        with patch.object(self.bridge,'launch_helper'):
            request=self.bridge.control('connect_saved',vm_name='Hub',unattended=True)
        job=json.loads((self.bridge.requests/(request['request_id']+'.json')).read_text())
        self.assertTrue(job['unattended'])

    def test_saved_credentials_reconnect_and_forget_without_exposure(self):
        path=self.bridge.saved_path('Hub');path.parent.mkdir()
        path.write_text(json.dumps({'vm':'Hub','account':'test-user','credential_encrypted':'DPAPI-FIXTURE'}))
        self.assertEqual(self.bridge.saved_connections(),[{'vm':'Hub','account':'test-user','unattended':True}])
        self.assertNotIn('DPAPI-FIXTURE',json.dumps(self.bridge.status()))
        with patch.object(self.bridge,'launch_helper'):
            queued=self.bridge.control('connect_saved',vm_name='Hub')
        job=json.loads((self.bridge.requests/(queued['request_id']+'.json')).read_text())
        self.assertEqual(job['credential_encrypted'],'DPAPI-FIXTURE')
        self.assertTrue(job['remember'])
        self.bridge.control('forget',vm_name='Hub');self.assertFalse(path.exists())

    def test_desktop_results_decode_image_and_report_worker_failure(self):
        queued=self.bridge.call('p','a',self.root,action='screenshot')
        source=self.bridge.requests/(queued['request_id']+'.json')
        job=json.loads(source.read_text());self.assertEqual(job['desktop_action'],'screenshot')
        self.assertNotIn('fixture-password',job['script'])
        result=self.bridge.results/source.name
        result.write_text(json.dumps({'state':'completed','output':json.dumps({'state':'completed','result':{'width':1024,'image_data':'iVBORw0KGgo='}})}))
        data=self.bridge.call('p','a',self.root,request_id=queued['request_id'])
        self.assertEqual(data['image_data'],'iVBORw0KGgo=');self.assertNotIn('image_data',data['result'])
        result.write_text(json.dumps({'state':'completed','output':json.dumps({'state':'failed','error':'Desktop locked'})}))
        self.assertEqual(self.bridge.call('p','a',self.root,request_id=queued['request_id'])['state'],'failed')

    def test_non_ascii_commands_are_safe_for_old_powershell_helpers(self):
        queued=self.bridge.call('p','a',self.root,action='exec',script="Write-Output '中文内容'")
        raw=(self.bridge.requests/(queued['request_id']+'.json')).read_text()
        self.assertTrue(raw.isascii())
        self.assertIn('中文内容',json.loads(raw)['script'])

    def test_explicit_power_off_can_interrupt_a_busy_vm(self):
        (self.bridge.root/'status.json').write_text(json.dumps({'updated':time.time(),'busy':'job','protocol':4}))
        with patch.object(self.bridge,'launch_helper'):
            result=self.bridge.control('power_force',vm_name='Hub')
        job=json.loads((self.bridge.requests/(result['request_id']+'.json')).read_text())
        self.assertEqual(job['action'],'power_force')
        self.assertEqual(json.loads((self.bridge.root/'power-override.json').read_text())['vm'],'Hub')

    def test_disconnected_helper_is_not_connected_guest(self):
        (self.bridge.root/'status.json').write_text(json.dumps({'updated':time.time(),'connected':False,'protocol':2}))
        self.assertTrue(self.bridge.status()['helper_alive'])
        self.assertFalse(self.bridge.status()['connected'])
        with patch.object(self.bridge,'launch_helper'):
            result=self.bridge.control('list')
        self.assertEqual(self.bridge.control('result',request_id=result['request_id'])['state'],'queued')

    def test_controls_do_not_reconnect_a_busy_vm(self):
        (self.bridge.root/'status.json').write_text(json.dumps({'updated':time.time(),'busy':'job'}))
        with self.assertRaises(HubError):self.bridge.control('disconnect')

    def test_live_current_protocol_helper_is_reused_without_uac(self):
        (self.bridge.root/'status.json').write_text(json.dumps({'updated':time.time(),'connected':True,'protocol':4}))
        with patch('ctypes.windll.shell32.ShellExecuteW') as shell:
            self.bridge.launch_helper()
        shell.assert_not_called()


if __name__ == '__main__':
    unittest.main()
