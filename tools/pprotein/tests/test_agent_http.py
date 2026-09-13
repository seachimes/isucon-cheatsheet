import os
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request


@unittest.skipUnless(os.environ.get('PPROTEIN_TEST_AGENT'), 'set PPROTEIN_TEST_AGENT to a native binary')
class AgentHTTP(unittest.TestCase):
    def test_health_logs_and_no_agent_cpu_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'access.log'
            log.write_text('previous log\n')
            with socket.socket() as s:
                s.bind(('127.0.0.1', 0))
                port = s.getsockname()[1]
            env = dict(os.environ, AGENT_PORT=str(port), PPROTEIN_HTTPLOG=str(log),
                       PPROTEIN_SLOWLOG=str(log), PPROTEIN_GIT_REPOSITORY=tmp)
            proc = subprocess.Popen([os.environ['PPROTEIN_TEST_AGENT']], env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            base = f'http://127.0.0.1:{port}'
            try:
                for _ in range(50):
                    try:
                        with urllib.request.urlopen(base + '/healthz', timeout=1) as r:
                            self.assertEqual(r.status, 204)
                        break
                    except OSError:
                        time.sleep(0.1)
                else:
                    self.fail('agent did not start')
                for kind in ['httplog', 'slowlog']:
                    with urllib.request.urlopen(base + f'/debug/log/{kind}?seconds=0') as r:
                        self.assertEqual(r.status, 200)
                        self.assertEqual(r.read(), b'')
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(base + '/debug/pprof/profile')
                self.assertEqual(error.exception.code, 404)
                error.exception.close()
                self.assertEqual(log.read_text(), 'previous log\n')
            finally:
                proc.terminate()
                proc.wait(timeout=5)


@unittest.skipUnless(os.environ.get('PPROTEIN_TEST_UI'), 'set PPROTEIN_TEST_UI to a native UI binary')
class UIHTTP(unittest.TestCase):
    def test_ui_and_target_settings_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            with socket.socket() as s:
                s.bind(('127.0.0.1', 0))
                port = s.getsockname()[1]
            proc = subprocess.Popen([os.environ['PPROTEIN_TEST_UI']], cwd=tmp,
                                    env=dict(os.environ, PORT=str(port)),
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            base = f'http://127.0.0.1:{port}'
            try:
                for _ in range(50):
                    try:
                        with urllib.request.urlopen(base, timeout=1) as r:
                            self.assertEqual(r.status, 200)
                            self.assertIn(b'<html', r.read())
                        break
                    except OSError:
                        time.sleep(0.1)
                else:
                    self.fail('UI did not start')
                targets = [{'Type': 'httplog', 'Label': 'test', 'Duration': 1,
                            'URL': 'http://127.0.0.1:19103/debug/log/httplog'}]
                req = urllib.request.Request(base + '/api/group/targets',
                    data=json.dumps(targets).encode(), headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(req) as r:
                    self.assertLess(r.status, 300)
                with urllib.request.urlopen(base + '/api/group/targets') as r:
                    self.assertEqual(json.load(r), targets)
            finally:
                proc.terminate()
                proc.wait(timeout=5)
