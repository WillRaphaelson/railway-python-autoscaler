from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import unittest
import urllib.request


class ShutdownTest(unittest.TestCase):
    def test_sigterm_allows_handoff_and_finishes_accepted_work(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        process = subprocess.Popen([sys.executable, 'api.py'],
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, 'PORT': str(port)},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        base = 'http://127.0.0.1:' + str(port)
        def get(path):
            with urllib.request.urlopen(base + path, timeout=4) as response:
                return json.load(response)
        try:
            deadline = time.monotonic() + 4
            while True:
                try:
                    get('/health')
                    break
                except OSError:
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(.03)
            with ThreadPoolExecutor(max_workers=1) as pool:
                request = pool.submit(get, '/work?ms=1000')
                time.sleep(.1)
                process.send_signal(signal.SIGTERM)
                self.assertEqual(get('/health')['status'], 'ok')
                self.assertEqual(request.result()['status'], 'ok')
            self.assertEqual(process.wait(timeout=8), 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
