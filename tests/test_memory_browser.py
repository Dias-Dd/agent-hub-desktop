"""Collect real Blink/JS garbage: visible DOM counts alone miss detached render leaks."""
import json
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path

import test_nine_browser as base
from hub.browser_cdp import WebSocket
from hub.browser_render import spawn_browser
from hub.process_job import ProcessJob


@unittest.skipUnless(base.m.EDGE.exists(), 'Edge unavailable')
class Memory(unittest.TestCase):
    def test_paginated_refresh_releases_old_nodes(self):
        server = base.Server(('127.0.0.1', 0), base.Fixture)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        browser = page = job = None
        with tempfile.TemporaryDirectory(prefix='hub-memory-', ignore_cleanup_errors=True) as folder:
            process = spawn_browser([str(base.m.EDGE), '--headless=new', '--disable-gpu',
                '--no-first-run', '--no-proxy-server', '--remote-debugging-port=0',
                '--disable-background-networking', '--disable-extensions',
                '--disable-background-timer-throttling', '--disable-renderer-backgrounding',
                '--disable-backgrounding-occluded-windows',
                '--user-data-dir=' + folder, 'about:blank'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                job = ProcessJob(process)
                port_file = Path(folder) / 'DevToolsActivePort'
                deadline = time.monotonic() + 12
                while not port_file.exists() and time.monotonic() < deadline:
                    time.sleep(.05)
                port, path = port_file.read_text().splitlines()[:2]
                browser = WebSocket('ws://127.0.0.1:' + port + path)
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                targets = json.load(opener.open('http://127.0.0.1:' + port + '/json/list'))
                page = WebSocket(next(t['webSocketDebuggerUrl'] for t in targets if t['type'] == 'page'))
                page.sock.settimeout(60)
                def evaluate(expression):
                    result = page.call('Runtime.evaluate', {'expression': expression,
                        'returnByValue': True, 'awaitPromise': True})
                    self.assertNotIn('exceptionDetails', result, str(result))
                    return result.get('result', {}).get('value')
                page.call('Page.navigate', {'url': f'http://127.0.0.1:{server.server_port}/'})
                page.call('Page.bringToFront')
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if evaluate("document.getElementById('result')?.textContent.startsWith('PASS')"):
                        break
                    time.sleep(.1)
                self.assertTrue(evaluate("document.getElementById('result')?.textContent.startsWith('PASS')"))
                evaluate("HubDesktop.store.stopPolling();window.fixture=HubDesktop.store.rawState;true")
                samples = []
                for batch in range(5):
                    evaluate("""(async()=>{const H=HubDesktop;for(let i=0;i<100;i++){
                      const s=structuredClone(window.fixture);
                      s.messages=Array.from({length:100},(_,j)=>({id:'m'+j,sender:'deepseek-1',
                        recipient:'user',body:'回报'.repeat(1000)+j+(j===99?' '+Math.random():''),
                        status:'completed',created:j}));s.project={progress:i};
                      H.store.rawState=s;H.store._notify();await new Promise(r=>setTimeout(r,5));
                    }return true})()""")
                    page.call('HeapProfiler.collectGarbage')
                    samples.append({**page.call('Memory.getDOMCounters'),
                        **page.call('Runtime.getHeapUsage')})
                print('memory checkpoints:', json.dumps(samples))
                # Old bug retained ~140,200 DOM nodes and 10,100 listeners per batch.
                self.assertLess(samples[-1]['nodes'] - samples[0]['nodes'], 10000)
                self.assertLess(samples[-1]['jsEventListeners'] - samples[0]['jsEventListeners'], 1000)
                self.assertLess(samples[-1]['embedderHeapUsedSize'] - samples[0]['embedderHeapUsedSize'], 8_000_000)
                self.assertTrue(evaluate("(()=>{document.querySelector('#messages button').click();return document.querySelectorAll('#messages > article').length===60})()"))
            finally:
                if browser:
                    try:
                        browser.call('Browser.close')
                    except Exception:
                        pass
                    browser.close()
                if page:
                    page.close()
                if job:
                    job.close()
                if process.poll() is None:
                    process.kill()
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == '__main__':
    unittest.main()
