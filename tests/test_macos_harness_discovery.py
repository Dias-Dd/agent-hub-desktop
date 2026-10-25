import importlib
import os
import subprocess
import sys
from hub.process_job import ProcessJob
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from hub.core import Hub
from hub.cli_paths import which, child_environment
from hub.builtin_adapters._shared.discovery import locate
from hub.builtin_adapters._shared.setup import login

runtime=importlib.import_module('hub.builtin_adapters.deepseek-harness.runtime')

class MacHarnessTests(unittest.TestCase):
    def test_finder_path_and_missing_cli(self):
        with tempfile.TemporaryDirectory() as folder, patch('sys.platform','darwin'), patch('pathlib.Path.home',return_value=Path(folder)), patch.dict(os.environ,{'PATH':'/usr/bin:/bin'}):
            base=Path(folder)/'.local/bin';base.mkdir(parents=True)
            for name,kind in [('agy','antigravity'),('opencode','opencode'),('ori','ori'),('codebuddy','workbuddy')]:
                exe=base/name;exe.write_text('#!/bin/sh\nexit 0\n');exe.chmod(0o700)
                self.assertEqual(locate(kind),str(exe))
            self.assertIsNone(which('hub-nonexistent-cli'))
            self.assertIn(str(base),child_environment({})['PATH'])

    def test_mac_and_windows_dsh_layout(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'DeepSeek Harness.app';contents=root/'Contents'
            for name in ['MacOS/DeepSeek Harness','Resources/runtime/cli/bin/dsh','Resources/app.asar']:
                p=contents/name;p.parent.mkdir(parents=True,exist_ok=True);p.touch();p.chmod(0o700)
            with patch('sys.platform','darwin'):
                exe,cli=runtime.installation({'harness_install':str(root)})
                self.assertEqual(locate('deepseek-harness',str(root)),str(exe))
                self.assertIn('app.asar/dsh/',str(cli))
                self.assertEqual(runtime.installation({'harness_install':str(exe)})[0],exe)
            windows=Path(folder)/'windows';(windows/'resources/runtime/cli/bin').mkdir(parents=True)
            (windows/'DeepSeek Harness.exe').touch();(windows/'resources/runtime/cli/bin/dsh.cmd').touch()
            with patch('sys.platform','win32'):
                self.assertEqual(runtime.installation({'harness_install':str(windows)})[0],windows/'DeepSeek Harness.exe')

    def test_terminal_login_quotes_arguments_without_starting_model(self):
        with tempfile.TemporaryDirectory() as folder,patch('sys.platform','darwin'),patch('hub.builtin_adapters._shared.setup.locate',return_value='/path with space/cli'),patch('hub.builtin_adapters._shared.setup.subprocess.run') as run:
            registry=SimpleNamespace(hub=SimpleNamespace(directory=Path(folder)))
            login(registry,{'cwd':folder},'opencode',{'terminal':True,'login_args':['auth','login','literal;$(id)']})
            call=run.call_args.args[0]
            self.assertEqual(call[:3],['/usr/bin/open','-a','Terminal'])
            script=Path(call[3]);source=script.read_text()
            self.assertIn("'/path with space/cli' auth login 'literal;$(id)'",source)
            self.assertEqual(script.stat().st_mode & 0o777,0o700)

    @unittest.skipIf(os.name=='nt','POSIX only')
    def test_exited_unreaped_cli_cleanup(self):
        proc=subprocess.Popen([sys.executable,'-c','print("done")'],stdout=subprocess.PIPE,text=True,start_new_session=True)
        job=ProcessJob(proc)
        self.assertEqual(proc.stdout.read().strip(),'done')
        job.close();proc.stdout.close()
        self.assertEqual(proc.returncode,0)

    def test_new_mac_workspace_stays_empty_after_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            for _ in range(2):
                h=Hub(folder,seed_defaults=False)
                self.assertEqual(h.db.execute('SELECT count(*) FROM agents').fetchone()[0],0)
                self.assertEqual(set(h.tokens),{'user'})
                h.db.close()

if __name__=='__main__':unittest.main()
