import base64,hashlib,io,json,os,stat,tempfile,threading,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
from hub.core import Hub,HubError
from hub import render_settings as render
from hub.notification_settings import action,allowed,DEFAULTS
from hub.chromium_download import Download,extract

class Settings(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.h=Hub(self.tmp.name,recover=False)
        self.addCleanup(self.tmp.cleanup);self.addCleanup(self.h.db.close)
    def test_browser_selection_persists_and_does_not_silently_fallback(self):
        exe=Path(self.tmp.name)/'browser.exe';exe.touch();exe.chmod(0o755)
        config=render.action(self.h,'user','save',mode='custom',path=str(exe))
        self.assertEqual(config['config']['mode'],'custom');self.assertEqual(render.resolve(self.h),str(exe))
        exe.unlink()
        with self.assertRaises(HubError):render.resolve(self.h)
        self.assertIn('不存在',render.action(self.h,'user')['error'])
        with self.assertRaises(HubError):render.action(self.h,'deepseek-1','save',mode='auto')
    def test_managed_browser_must_be_inside_owned_directory(self):
        root=self.h.directory/'browsers/chromium';root.mkdir(parents=True)
        outside=self.h.directory/'unowned.exe';outside.touch()
        (root/'installed.json').write_text(json.dumps({'path':str(outside)}))
        self.assertIsNone(render.managed(self.h))
        with self.assertRaises(HubError):render.action(self.h,'user','save',mode='managed')
    def test_notification_events_timing_and_explicit_test(self):
        cfg={**DEFAULTS,'when':'background','demo':False,'attention':True}
        action(self.h,'user','save',config=cfg)
        self.assertEqual(action(self.h,'user'),cfg)
        self.assertFalse(allowed(cfg,{'kind':'demo'}))
        self.assertFalse(allowed(cfg,{'kind':'project'},True))
        self.assertTrue(allowed(cfg,{'kind':'project'},False))
        self.assertTrue(allowed(cfg,{'kind':'attention'},False))
        self.assertFalse(allowed({**cfg,'enabled':False},{'kind':'attention'}))
        self.assertTrue(allowed({**cfg,'enabled':False},{'kind':'test'},True))
        with self.assertRaises(HubError):action(self.h,'deepseek-1','save',config=cfg)
        with self.assertRaises(HubError):action(self.h,'user','save',config={**cfg,'enabled':'false'})
        self.assertTrue(action(self.h,'user','test')['queued'])
    def test_selected_browser_really_renders_a_page(self):
        from hub.browser_render import executable
        try:exe=executable()
        except HubError:self.skipTest('No local browser')
        render.action(self.h,'user','save',mode='custom',path=exe)
        self.assertTrue(render.action(self.h,'user','test')['ok'])

class Archives(unittest.TestCase):
    def archive(self,entries):
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as z:
            for name,body in entries:z.writestr(name,body)
        return data.getvalue()
    def test_safe_extract_rejects_traversal_and_escape_links(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ('../outside','/absolute','C:/outside'):
                with self.subTest(name=name),self.assertRaises(HubError):extract(io.BytesIO(self.archive([(name,b'x')])),Path(folder),threading.Event())
            data=io.BytesIO()
            with zipfile.ZipFile(data,'w') as z:
                item=zipfile.ZipInfo('link');item.create_system=3;item.external_attr=(stat.S_IFLNK|0o777)<<16;z.writestr(item,'../../outside')
            with self.assertRaises(HubError):extract(io.BytesIO(data.getvalue()),Path(folder),threading.Event())
    def test_download_verifies_then_installs_and_preserves_old_install_on_failure(self):
        content=self.archive([('chrome-win/chrome.exe',b'fake fixture browser')])
        digest=base64.b64encode(hashlib.md5(content).digest()).decode()
        with tempfile.TemporaryDirectory() as folder:
            def opener(bad=False):
                class Response(io.BytesIO):pass
                class Client:
                    def open(self,url,**kwargs):
                        url=url.full_url if hasattr(url,'full_url') else url
                        if 'LAST_CHANGE' in url:return Response(b'123456')
                        if '/storage/v1/' in url:return Response(json.dumps({'size':len(content),'md5Hash':base64.b64encode(b'x'*16).decode() if bad else digest}).encode())
                        return Response(content)
                return Client()
            job=Download(folder)
            with patch('hub.chromium_download.target',return_value=('Win_x64','chrome-win.zip','chrome-win/chrome.exe')),patch('hub.chromium_download.urllib.request.build_opener',return_value=opener()):job.run()
            self.assertEqual(job.status()['state'],'completed');self.assertTrue(Path(job.status()['path']).is_file())
            original=(job.root/'installed.json').read_bytes()
            with patch('hub.chromium_download.target',return_value=('Win_x64','chrome-win.zip','chrome-win/chrome.exe')),patch('hub.chromium_download.urllib.request.build_opener',return_value=opener(True)):job.run()
            self.assertEqual(job.status()['state'],'failed');self.assertEqual((job.root/'installed.json').read_bytes(),original)
            self.assertFalse(list(job.root.glob('.download-*')))
    def test_cancelled_extract_does_not_publish_an_install(self):
        with tempfile.TemporaryDirectory() as folder:
            cancel=threading.Event();cancel.set()
            with self.assertRaisesRegex(HubError,'取消'):extract(io.BytesIO(self.archive([('file',b'content')])),folder,cancel)

    def test_interrupted_transfer_resumes_verified_range(self):
        from hub.chromium_download import transfer
        content=b'abcdef';requests=[]
        class Response(io.BytesIO):
            def __init__(self,data,status=200,headers=None,fail=False):super().__init__(data);self.status=status;self.headers=headers or {};self.fail=fail
            def read(self,n=-1):
                if self.fail:
                    if self.tell():raise OSError('network interruption')
                    return super().read(3)
                return super().read(n)
        class Client:
            def open(self,request,**kwargs):
                requests.append(request.get_header('Range'))
                return Response(content[:3],fail=True) if len(requests)==1 else Response(content[3:],206,{'Content-Range':'bytes 3-5/6'})
        with tempfile.TemporaryDirectory() as folder:
            archive=Path(folder)/'download';digest,sha=transfer(Client(),'https://storage.googleapis.com/test',archive,len(content),threading.Event(),lambda **kwargs:None)
            self.assertEqual(requests,[None,'bytes=3-']);self.assertEqual(archive.read_bytes(),content)
            self.assertEqual(digest,hashlib.md5(content).digest());self.assertEqual(sha,hashlib.sha256(content).hexdigest())
