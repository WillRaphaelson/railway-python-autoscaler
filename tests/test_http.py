from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
import api
import autoscaler


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), api.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_address[1])
        self.secret = patch.object(api, 'METRICS_TOKEN', 'test-secret')
        self.secret.start()
        autoscaler.STOP.clear()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.secret.stop()

    def get(self, path, token=None):
        req = urllib.request.Request(self.url+path, headers={'Authorization':'Bearer '+token} if token else {})
        with urllib.request.urlopen(req) as response:
            return json.load(response)

    def test_health_and_validation(self):
        self.assertEqual(self.get('/health')['status'], 'ok')
        with self.assertRaises(urllib.error.HTTPError) as err:
            self.get('/work?ms=9000')
        self.assertEqual(err.exception.code, 400)

    def test_metrics_require_secret(self):
        with self.assertRaises(urllib.error.HTTPError) as err:
            self.get('/_load')
        self.assertEqual(err.exception.code, 403)
        self.assertEqual(self.get('/_load','test-secret')['inflight'],0)

    def test_concurrent_work_is_observable_and_excludes_health_checks(self):
        with ThreadPoolExecutor(max_workers=3) as pool:
            tasks = [pool.submit(self.get, '/work?ms=400') for _ in range(3)]
            deadline = time.time()+2
            while self.get('/_load','test-secret')['inflight'] != 3:
                self.assertLess(time.time(),deadline)
                time.sleep(.01)
            mean, ids = autoscaler.sample_load(self.url+'/_load','test-secret',count=2,spacing=0)
            self.assertEqual(mean,3)
            self.assertEqual(ids,{'local-api'})
            self.assertTrue(all(t.result()['status']=='ok' for t in tasks))
        self.assertEqual(self.get('/_load','test-secret')['inflight'],0)

    def test_stale_and_invalid_samples_rejected(self):
        for bad in ({'inflight':0,'replica_id':'a','sampled_at':0},
                    {'inflight':float('nan'),'replica_id':'a','sampled_at':time.time()},
                    {'inflight':False,'replica_id':'a','sampled_at':time.time()}):
            with patch.object(autoscaler,'json_request',return_value=bad):
                with self.assertRaises(RuntimeError):
                    autoscaler.sample_load(self.url,'test-secret',count=1,spacing=0)

    def test_api_errors_are_not_treated_as_success(self):
        client=autoscaler.Railway('secret','env','app','controller')
        with patch.object(autoscaler,'json_request',return_value={'errors':[{'message':'denied'}]}):
            with self.assertRaises(RuntimeError): client.scale(2)
        with patch.object(autoscaler,'json_request',return_value={'data':{'serviceInstanceUpdate':True}}) as call:
            client.scale(2)
            sent=call.call_args.kwargs['payload']['variables']
            self.assertEqual(sent['input'],{'numReplicas':2})
            self.assertEqual(call.call_args.kwargs['headers']['Project-Access-Token'],'secret')
