"""Small stateless HTTP workload and a public, read-only demonstration view."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
from pathlib import Path
import signal
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

REPLICA = os.environ.get('RAILWAY_REPLICA_ID', 'local-api')
METRICS_TOKEN = os.environ.get('METRICS_TOKEN', '')
STATUS_URL = os.environ.get('AUTOSCALER_STATUS_URL', '')
LOCK = threading.Lock()
INFLIGHT = 0
REQUESTS = 0


def respond(handler, status, body, kind='application/json'):
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    handler.send_response(status)
    handler.send_header('Content-Type', kind)
    handler.send_header('Content-Length', str(len(raw)))
    handler.send_header('Cache-Control', 'no-store')
    handler.send_header('X-Content-Type-Options', 'nosniff')
    handler.end_headers()
    handler.wfile.write(raw)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        global INFLIGHT, REQUESTS
        url = urllib.parse.urlsplit(self.path)
        if url.path == '/health':
            return respond(self, 200, {'status': 'ok', 'replica_id': REPLICA})
        if url.path == '/_load':
            provided = self.headers.get('Authorization', '')
            if not METRICS_TOKEN or not hmac.compare_digest(provided, 'Bearer ' + METRICS_TOKEN):
                return respond(self, 403, {'error': 'forbidden'})
            with LOCK:
                value = {'replica_id': REPLICA, 'inflight': INFLIGHT,
                         'requests': REQUESTS, 'sampled_at': time.time()}
            return respond(self, 200, value)
        if url.path == '/':
            return respond(self, 200, Path(__file__).with_name('dashboard.html').read_bytes(), 'text/html; charset=utf-8')
        if url.path == '/dashboard':
            if not STATUS_URL:
                return respond(self, 200, {'status': 'Configure the controller status URL', 'events': []})
            try:
                req = urllib.request.Request(STATUS_URL, headers={'Authorization': 'Bearer ' + METRICS_TOKEN})
                with urllib.request.urlopen(req, timeout=5) as response:
                    value = json.load(response)
                return respond(self, 200, value)
            except (OSError, ValueError):
                return respond(self, 503, {'status': 'Waiting for the autoscaler', 'events': []})
        if url.path != '/work':
            return respond(self, 404, {'error': 'not found'})
        try:
            delay_ms = int(urllib.parse.parse_qs(url.query).get('ms', ['1000'])[0])
            if not 1 <= delay_ms <= 3000:
                raise ValueError()
        except ValueError:
            return respond(self, 400, {'error': 'ms must be an integer from 1 to 3000'})
        with LOCK:
            if INFLIGHT >= 40:
                return respond(self, 429, {'error': 'demo concurrency limit'})
            INFLIGHT += 1
            REQUESTS += 1
        try:
            # Retained only while a request is active; makes RAM use observable.
            payload = bytearray(2 * 1024 * 1024)
            payload[0] = 1
            time.sleep(delay_ms / 1000)
            respond(self, 200, {'status': 'ok', 'replica_id': REPLICA, 'wait_ms': delay_ms})
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with LOCK:
                INFLIGHT -= 1


class DemoServer(ThreadingHTTPServer):
    request_queue_size = 128


def main():
    server = DemoServer(('0.0.0.0', int(os.environ.get('PORT', '8080'))), Handler)
    server.daemon_threads = False
    def drain():
        # Keep accepting briefly while routing changes propagate, then finish
        # accepted work. Railway's drain allowance must cover both intervals.
        time.sleep(5)
        server.shutdown()
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=drain, daemon=True).start())
    print(json.dumps({'event': 'api_started', 'replica_id': REPLICA}), flush=True)
    server.serve_forever()
    server.server_close()


if __name__ == '__main__':
    main()
