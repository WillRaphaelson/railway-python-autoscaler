"""Single-region, single-controller Railway autoscaling demonstration."""
from collections import deque
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import math
import os
import signal
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from policy import Decision, Policy

API = 'https://backboard.railway.com/graphql/v2'
STOP = threading.Event()
LOCK = threading.Lock()
STATE = {'status': 'Starting', 'events': [], 'observed_replicas': [], 'history': []}
EVENTS = deque(maxlen=80)
HISTORY = deque(maxlen=180)


def event(kind, **values):
    record = {'at': time.time(), 'event': kind, **values}
    with LOCK:
        EVENTS.appendleft(record)
        STATE['events'] = list(EVENTS)
    print(json.dumps(record), flush=True)


def json_request(url, *, headers=None, payload=None, timeout=10):
    raw = json.dumps(payload).encode() if payload is not None else None
    request_headers = {'User-Agent': 'railway-python-autoscaler/1.0', 'Accept': 'application/json', **(headers or {})}
    req = urllib.request.Request(url, data=raw, headers=request_headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


class Railway:
    def __init__(self, token, environment, target, controller):
        self.token, self.environment, self.target, self.controller = token, environment, target, controller

    def query(self, document, variables):
        result = json_request(API, headers={
            'Content-Type': 'application/json', 'Project-Access-Token': self.token,
        }, payload={'query': document, 'variables': variables})
        if result.get('errors') or 'data' not in result:
            # Never log request headers, tokens, or an unfiltered API response.
            raise RuntimeError('Railway API rejected the operation')
        return result['data']

    def counts(self):
        data = self.query('''query ($environment: String!) {
          environment(id: $environment) { config }
        }''', {'environment': self.environment})
        config = data['environment']['config']
        if isinstance(config, str):
            config = json.loads(config)
        services = config['services']
        # Use the regional configuration, as the current Railway CLI does.
        # The legacy top-level numReplicas field can disagree with running capacity.
        regions = services[self.target]['deploy']['multiRegionConfig']
        active = {region: value for region, value in regions.items() if value is not None}
        if len(active) != 1:
            raise RuntimeError('This example requires exactly one target region')
        self.region, value = next(iter(active.items()))
        current = value['numReplicas']
        own_regions = services[self.controller]['deploy']['multiRegionConfig']
        own = sum(value['numReplicas'] for value in own_regions.values() if value is not None)
        if isinstance(current, bool) or not isinstance(current, int) or current < 1:
            raise RuntimeError('Invalid configured replica count')
        return current, own

    def scale(self, count):
        current, own = self.counts()
        if own != 1 or abs(count - current) != 1:
            raise RuntimeError('Hold: capacity changed before the write')
        patch = {'services': {self.target: {'deploy': {
            'multiRegionConfig': {self.region: {'numReplicas': count}},
        }}}}
        data = self.query('''mutation ($environment: String!, $patch: EnvironmentConfig) {
          environmentPatchCommit(environmentId: $environment, patch: $patch,
            commitMessage: "Python autoscaler replica adjustment")
        }''', {'environment': self.environment, 'patch': patch})
        if not data.get('environmentPatchCommit'):
            raise RuntimeError('Replica patch was not committed')


def sample_load(url, token, count=8, spacing=0.12):
    values, ids = [], set()
    for _ in range(count):
        value = json_request(url, headers={'Authorization': 'Bearer ' + token}, timeout=5)
        load, timestamp = value.get('inflight'), value.get('sampled_at')
        if (isinstance(load, bool) or not isinstance(load, (int, float)) or not math.isfinite(load)
                or load < 0 or not isinstance(timestamp, (int, float))
                or not math.isfinite(timestamp) or abs(time.time() - timestamp) > 15
                or not isinstance(value.get('replica_id'), str) or not value['replica_id']):
            raise RuntimeError('Invalid or stale load observation')
        values.append(float(load))
        ids.add(value['replica_id'])
        if STOP.wait(spacing):
            raise RuntimeError('Stopping')
    return sum(values) / len(values), ids


class StatusHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path == '/health':
            value, status = {'status': 'ok'}, 200
        elif self.path == '/state' and hmac.compare_digest(
                self.headers.get('Authorization', ''), 'Bearer ' + os.environ.get('METRICS_TOKEN', '')) \
                and os.environ.get('METRICS_TOKEN'):
            with LOCK:
                value = dict(STATE)
            status = 200
        else:
            value, status = {'error': 'forbidden'}, 403
        raw = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def main():
    policy = Policy(
        minimum=int(os.environ.get('MIN_REPLICAS', '1')),
        maximum=int(os.environ.get('MAX_REPLICAS', '3')),
        target_inflight=float(os.environ.get('TARGET_INFLIGHT', '4')),
        up_window=float(os.environ.get('SCALE_UP_WINDOW_SECONDS', '10')),
        down_window=float(os.environ.get('SCALE_DOWN_WINDOW_SECONDS', '60')),
        cooldown=float(os.environ.get('COOLDOWN_SECONDS', '30')),
    )
    poll = max(2, float(os.environ.get('POLL_SECONDS', '5')))
    token = os.environ.get('RAILWAY_API_TOKEN', '')
    environment = os.environ.get('RAILWAY_ENVIRONMENT_ID', '')
    target = os.environ.get('TARGET_SERVICE_ID', '')
    own = os.environ.get('RAILWAY_SERVICE_ID', '')
    load_url = os.environ.get('TARGET_LOAD_URL', '')
    metrics_token = os.environ.get('METRICS_TOKEN', '')
    enabled = os.environ.get('SCALING_ENABLED', 'false').lower() == 'true'
    dry_run = os.environ.get('DRY_RUN', 'true').lower() == 'true'
    if not metrics_token or not load_url:
        raise ValueError('METRICS_TOKEN and TARGET_LOAD_URL are required')
    client = Railway(token, environment, target, own)
    decisions = Decision(policy)
    # A restart starts a fresh cooldown rather than immediately changing capacity.
    decisions.changed(time.monotonic())
    seen, requested, failures = {}, None, 0
    with LOCK:
        STATE.update(policy=asdict(policy), enabled=enabled, dry_run=dry_run)
    server = ThreadingHTTPServer(('0.0.0.0', int(os.environ.get('PORT', '8080'))), StatusHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    signal.signal(signal.SIGTERM, lambda *_: STOP.set())
    event('controller_started', enabled=enabled, dry_run=dry_run)
    try:
        while not STOP.is_set():
            started = time.monotonic()
            try:
                mean, observed = sample_load(load_url, metrics_token)
                now = time.monotonic()
                for replica in observed:
                    seen[replica] = now
                seen = {rid: at for rid, at in seen.items() if now - at < 20}
                current = own_count = None
                if token and environment and target and own:
                    current, own_count = client.counts()
                complete = current is not None and len(seen) == current and own_count == 1
                if requested is not None:
                    if current == requested and len(seen) == requested:
                        event('replicas_observed', count=requested)
                        requested = None
                        decisions.changed(now)
                    else:
                        complete = False
                if current is None:
                    desired, reason = None, 'Observe only: add an environment project token'
                    decisions.reset()
                else:
                    desired, reason = decisions.evaluate(current, mean, now, complete=complete)
                if own_count is not None and own_count != 1:
                    reason = 'Hold: run exactly one autoscaler replica'
                if current is not None and desired != current:
                    if enabled and not dry_run:
                        client.scale(desired)
                        requested = desired
                        decisions.changed(now)
                        event('scale_requested', previous=current, desired=desired, mean_inflight=round(mean, 2))
                    else:
                        event('dry_run_decision', previous=current, desired=desired, mean_inflight=round(mean, 2))
                        decisions.changed(now)
                public = {
                    'at': time.time(), 'configured_replicas': current,
                    'observed_count': len(seen), 'mean_inflight': round(mean, 2),
                }
                HISTORY.append(public)
                with LOCK:
                    STATE.update(public, status=reason, observed_replicas=sorted(seen),
                                 pending_replicas=requested, history=list(HISTORY),
                                 enabled=enabled, dry_run=dry_run)
                event('observation', **public, reason=reason)
                failures = 0
            except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
                decisions.reset()
                failures += 1
                detail = 'HTTP ' + str(error.code) if isinstance(error, urllib.error.HTTPError) else type(error).__name__
                reason = 'Hold: observation or API unavailable (' + detail + ')'
                with LOCK:
                    STATE['status'] = reason
                event('hold_on_error', reason=reason)
            # Bounded backoff on errors; never turn missing data into zero load.
            wait = min(60, poll * 2 ** min(failures, 3)) if failures else poll
            STOP.wait(max(0, wait - (time.monotonic() - started)))
    finally:
        server.shutdown()


if __name__ == '__main__':
    main()
