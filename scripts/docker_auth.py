#!/usr/bin/env python3
"""Resolve the host's relevant registry logins for a short-lived pack container."""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


def registry(image):
    first = image.split('/')[0]
    return first if '/' in image and ('.' in first or ':' in first or first == 'localhost') else 'docker.io'


def aliases(host):
    if host in ('docker.io', 'index.docker.io', 'registry-1.docker.io'):
        return ['https://index.docker.io/v1/', 'docker.io', 'index.docker.io', 'registry-1.docker.io']
    return [host, 'https://' + host]


def resolve(config, host):
    for server in aliases(host):
        inline = config.get('auths', {}).get(server, {})
        saved = {key: inline[key] for key in ('auth', 'identitytoken') if inline.get(key)}
        if saved:
            return saved
        helper = config.get('credHelpers', {}).get(server, config.get('credsStore'))
        if not helper:
            continue
        if not re.fullmatch(r'[a-zA-Z0-9_.-]+', helper):
            raise ValueError('Invalid Docker credential-helper name')
        executable = shutil.which('docker-credential-' + helper)
        if not executable:
            raise ValueError(f'Docker credential helper docker-credential-{helper} is not available on PATH')
        result = subprocess.run([executable, 'get'], input=server,
                                capture_output=True, text=True, timeout=15)
        if result.returncode:
            continue
        try:
            credentials = json.loads(result.stdout)
        except json.JSONDecodeError:
            raise ValueError('Docker credential helper returned invalid JSON') from None
        username, secret = credentials.get('Username'), credentials.get('Secret')
        if not username or not secret:
            continue
        if username == '<token>':
            return {'identitytoken': secret}
        encoded = base64.b64encode(f'{username}:{secret}'.encode()).decode()
        return {'auth': encoded}
    return None


def prepare(output, builder, source=None):
    source = source or Path(os.environ.get('DOCKER_CONFIG', str(Path.home() / '.docker'))) / 'config.json'
    config = json.loads(source.read_text()) if source.exists() else {}
    auths = {}
    # Export only logins relevant to the builder and the standard lifecycle/run images.
    for host in sorted({'docker.io', registry(builder)}):
        resolved = resolve(config, host)
        if resolved:
            auths[aliases(host)[0]] = resolved
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    output.chmod(0o700)
    destination = output / 'config.json'
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump({'auths': auths}, stream)
    destination.chmod(0o600)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('builder')
    args = parser.parse_args()
    try:
        prepare(args.output, args.builder)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        # Never include config contents or credential-helper output in build logs.
        print('Could not prepare Docker registry authentication. Check your Docker login and credential helper.', file=sys.stderr)
        sys.exit(1)
