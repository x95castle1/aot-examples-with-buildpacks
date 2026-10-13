#!/usr/bin/env python3
"""Render owned manifests with an image override; never applies them to a cluster."""
from pathlib import Path
import json
import re
import sys


def render(example, image):
    if not re.fullmatch(r'[a-zA-Z0-9._/:@-]+', image):
        raise ValueError('Image must be a container image reference')
    root = Path(__file__).resolve().parents[1]
    directory = root / 'examples' / example
    if directory.parent != root / 'examples' or not (directory / 'example.json').is_file():
        raise ValueError('Unknown example')
    original = json.loads((directory / 'example.json').read_text())['image']
    deployment = (directory / 'k8s/deployment.yaml').read_text()
    service = (directory / 'k8s/service.yaml').read_text()
    return deployment.replace('image: ' + original, 'image: ' + image) + '---\n' + service


if __name__ == '__main__':
    try:
        print(render(*sys.argv[1:]), end='')
    except (ValueError, TypeError) as error:
        print(error, file=sys.stderr)
        sys.exit(2)
