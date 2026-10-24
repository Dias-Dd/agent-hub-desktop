import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from desktop.onboarding_service import SetupService
from hub.core import HubError


class OnboardingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.service=SetupService(self.temp.name)

    def tearDown(self):
        self.service.close();self.temp.cleanup()

    def custom(self):
        folder=Path(self.temp.name)/'adapters/custom/test-login';folder.mkdir(parents=True)
        (folder/'adapter.json').write_text(json.dumps({'version':1,'protocol':'hub-module-v1','id':'test-login','name':'Test module','entrypoint':'adapter.py','capabilities':{'tools':True,'resume':False,'streaming':False},'models':[],'setup':{'website':'https://example.com/'}}),encoding='utf-8')
        (folder/'adapter.py').write_text('''from pathlib import Path
def execute(host,run): raise AssertionError('inference must never run')
def setup_status(registry,connection):
 return {'state':'ready' if (registry.hub.directory/'logged-in').exists() else 'login','message':'Login needed'}
def setup_login(registry,connection): (registry.hub.directory/'login-opened').touch()
def probe(registry,connection): return {'models':[{'id':'test-model','efforts':['default']}]}
''',encoding='utf-8')
        self.service.connections();return 'custom-test-login'

    def test_new_install_has_no_fake_deepseek_agents(self):
        self.assertEqual(self.service.agents(),[])
        self.assertEqual(self.service.hub.db.execute('SELECT count(*) FROM agents WHERE enabled=1').fetchone()[0],0)
        self.assertFalse(self.service.hub.db.execute("SELECT 1 FROM sqlite_master WHERE name='executions'").fetchone())
        self.assertEqual(self.service.registry.instances,{})

    def test_login_required_opens_real_module_login_and_does_not_probe(self):
        ident=self.custom();result=self.service.probe(ident)
        self.assertTrue(result['login_required'])
        self.assertTrue((Path(self.temp.name)/'login-opened').exists())
        self.assertNotIn(ident,self.service.verified)

    def test_full_custom_flow_requires_consent_and_manager_then_persists(self):
        ident=self.custom();(Path(self.temp.name)/'logged-in').touch()
        self.assertEqual(self.service.probe(ident)['models'][0]['id'],'test-model')
        with self.assertRaises(HubError):self.service.add_agent(ident,'test-model','Worker',False)
        agent=self.service.add_agent(ident,'test-model','Worker',True)
        with self.assertRaises(HubError):self.service.complete(False,'missing',True)
        result=self.service.complete(False,agent['id'],True)
        self.assertEqual(result['manager'],agent['id'])
        from hub.manager_identity import resolve
        self.assertEqual(resolve(self.service.hub),agent['id'])
        self.assertEqual(self.service.registry.instances,{})
        self.assertFalse(self.service.hub.db.execute("SELECT 1 FROM sqlite_master WHERE name='executions'").fetchone())

    def test_skips_are_explicit_and_vm_must_actually_connect(self):
        with self.assertRaises(HubError):self.service.complete(True,'',False)
        marker=self.service.complete(True,'',True)
        self.assertTrue(marker['agent_skipped']);self.assertTrue(marker['vm_skipped'])
        self.assertIsNone(marker['manager'])

    def test_service_excludes_live_main_app(self):
        with self.assertRaisesRegex(HubError,'托盘退出'):SetupService(self.temp.name)

    def test_missing_harness_no_process_is_started(self):
        with patch('desktop.onboarding_service.locate',return_value=None),patch('subprocess.Popen') as spawn:
            result=self.service.inspect('opencode-local')
            self.assertEqual(result['state'],'missing');spawn.assert_not_called()

    def test_public_model_list_cannot_replace_authentication(self):
        with patch('desktop.onboarding_service.locate',return_value='opencode.exe'),patch('subprocess.run',return_value=subprocess.CompletedProcess([],0,'0 credentials','')),patch.object(self.service,'open_login') as login:
            result=self.service.probe('opencode-local')
            self.assertTrue(result['login_required']);login.assert_called_once_with('opencode-local')

    def test_existing_runs_tests_and_agents_are_not_recovered_or_reset(self):
        h=self.service.hub
        h.db.execute('CREATE TABLE executions(id TEXT,agent TEXT,status TEXT,provider TEXT)')
        h.db.execute("INSERT INTO executions VALUES('keep','deepseek-1','running','test')")
        h.db.execute('CREATE TABLE integration_test_results(id TEXT PRIMARY KEY,body TEXT)')
        h.db.execute('INSERT INTO integration_test_results VALUES(?,?)',('keep-test',json.dumps({'id':'keep-test','status':'testing','run_id':'keep'})))
        h.db.execute("UPDATE agents SET status='running',enabled=1 WHERE id='deepseek-1'")
        self.service.close();self.service=SetupService(self.temp.name)
        self.assertEqual(self.service.hub.db.execute("SELECT status FROM executions WHERE id='keep'").fetchone()[0],'running')
        self.assertEqual(self.service.hub.db.execute("SELECT status FROM agents WHERE id='deepseek-1'").fetchone()[0],'running')
        self.assertEqual(json.loads(self.service.hub.db.execute('SELECT body FROM integration_test_results').fetchone()[0])['status'],'testing')

    @unittest.skipUnless(os.name=='nt','DPAPI requires Windows')
    def test_deepseek_credential_is_dpapi_and_not_plaintext(self):
        secret='test-not-a-real-api-key-12345'
        self.service.save_deepseek_key(secret)
        self.assertNotIn(secret.encode(),(Path(self.temp.name)/'deepseek-key.dpapi').read_bytes())
        self.assertEqual(self.service.server.deepseek.key(),secret)

    def test_vm_job_waits_for_queued_and_running(self):
        from desktop.onboarding import Wizard
        wizard=Wizard.__new__(Wizard);wizard.service=self.service
        with patch.object(self.service.vm,'control',side_effect=[{'request_id':'a'*32,'state':'queued'},{'state':'queued'},{'state':'running'},{'state':'completed','vms':[{'name':'Test VM'}]}]),patch('time.sleep'):
            self.assertEqual(wizard.vm_job('list')['vms'][0]['name'],'Test VM')

    def test_unsafe_module_websites_rejected(self):
        for url in ('file:///C:/test','http://example.com','https://user:password@example.com'):
            with self.assertRaises(HubError):self.service.open_url(url)


class OnboardingLayoutTests(unittest.TestCase):
    def test_footer_buttons_at_high_dpi_in_minimum_window(self):
        import tkinter as tk
        from desktop.onboarding import Wizard
        for scaling in (1.0, 1.5, 2.0):
            with self.subTest(scaling=scaling), tempfile.TemporaryDirectory() as folder:
                root=tk.Tk(); root.tk.call('tk','scaling',scaling)
                service=SetupService(folder); wizard=Wizard(root,service)
                try:
                    root.geometry('640x540')
                    for page in range(6):
                        wizard.show(page);root.update()
                        for button in wizard.footer.winfo_children():
                            if button.winfo_ismapped():
                                self.assertGreater(button.winfo_height(),15)
                                self.assertGreaterEqual(button.winfo_rooty(),root.winfo_rooty())
                                self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),root.winfo_rooty()+root.winfo_height())
                        self.assertGreater(wizard.canvas.winfo_height(),50)
                finally: root.destroy();service.close()

    def test_pages_can_scroll_and_footer_stays_reachable(self):
        import tkinter as tk
        from desktop.onboarding import Wizard
        with tempfile.TemporaryDirectory() as folder:
            service=SetupService(folder);root=tk.Tk();wizard=Wizard(root,service)
            try:
                for language in ('zh-CN','en'):
                    wizard.change_language(language)
                    for width,height in ((860,690),(640,540),(1024,600)):
                        root.geometry(f'{width}x{height}');root.update()
                        for page in (0,1,2,3,4,5):
                            wizard.show(page);root.update()
                            self.assertTrue(wizard.footer.winfo_ismapped())
                            self.assertGreater(wizard.footer.winfo_height(),25)
                            self.assertLessEqual(wizard.footer.winfo_y()+wizard.footer.winfo_height(),root.winfo_height())
                            self.assertGreater(wizard.canvas.winfo_height(),80)
                            wizard.canvas.yview_moveto(1);root.update()
                            self.assertAlmostEqual(wizard.canvas.yview()[1],1,places=2)
                    if language=='en':self.assertEqual(root.title(),'Agent Hub · First-time setup')
            finally:root.destroy();service.close()


if __name__=='__main__':unittest.main()
