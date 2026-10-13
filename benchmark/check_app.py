#!/usr/bin/env python3
"""Wait for the selected application and show verified sample API requests."""
import argparse
import json
from pathlib import Path
import shlex
import sys

from common import verify, wait_ready


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--example', required=True)
    parser.add_argument('--host', default='app')
    parser.add_argument('--display-url', default='http://localhost:8080')
    parser.add_argument('--iterations', type=int, default=100000)
    parser.add_argument('--timeout', type=float, default=120)
    args = parser.parse_args()
    if not 1 <= args.iterations <= 10000000:
        parser.error('iterations must be 1..10000000')
    if args.timeout <= 0:
        parser.error('timeout must be positive')
    config = json.loads((Path(__file__).resolve().parents[1] / 'examples' / args.example / 'example.json').read_text())

    def show(route, body, result):
        curl = ['curl', '-sS', args.display_url.rstrip('/') + route]
        if body:
            curl.extend(['-H', 'Content-Type: application/json', '-d', body])
        print('$ ' + shlex.join(curl), flush=True)
        print(json.dumps(result, indent=2) + '\n', flush=True)

    ready = wait_ready(args.host, 8080, config, args.timeout)
    print(f'\nTesting {args.example}\n', flush=True)
    show('/ready', None, ready)
    verify(args.host, 8080, args.iterations, show)
    print('All sample responses and input-error checks passed. The app is still running.\n')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, TimeoutError) as error:
        print(f'Application check failed: {error}', file=sys.stderr)
        sys.exit(1)
