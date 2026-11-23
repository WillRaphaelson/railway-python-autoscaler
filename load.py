"""Bounded external request generator; run only against your own demo."""
from concurrent.futures import ThreadPoolExecutor
import argparse
import collections
import json
import threading
import time
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('url', help='Your deployed /work?ms=1000 endpoint')
    parser.add_argument('--seconds', type=int, default=120)
    parser.add_argument('--concurrency', type=int, default=12)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 300 or not 1 <= args.concurrency <= 24:
        parser.error('Use 1–300 seconds and 1–24 workers')
    end, lock = time.monotonic() + args.seconds, threading.Lock()
    counts, durations, errors = collections.Counter(), [], 0

    def work():
        nonlocal errors
        while time.monotonic() < end:
            start = time.monotonic()
            try:
                with urllib.request.urlopen(args.url, timeout=15) as response:
                    payload = json.load(response)
                if payload.get('status') != 'ok' or not payload.get('replica_id'):
                    raise ValueError('Unexpected application response')
                with lock:
                    counts[payload['replica_id']] += 1
                    durations.append((time.monotonic() - start) * 1000)
            except (OSError, ValueError):
                with lock:
                    errors += 1
                time.sleep(.2)

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        list(pool.map(lambda _: work(), range(args.concurrency)))
    durations.sort()
    print(json.dumps({'requests_ok': len(durations), 'errors': errors,
        'seconds': args.seconds, 'concurrency': args.concurrency,
        'replicas_serving': dict(counts),
        'p95_ms': durations[max(0, int(len(durations) * .95) - 1)] if durations else None}, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
