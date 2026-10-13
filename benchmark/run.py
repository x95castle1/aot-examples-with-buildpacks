#!/usr/bin/env python3
"""Compare fresh buildpack containers; startup includes Docker container start."""
import argparse
import csv
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import random
import statistics
import sys
import time
import uuid

from common import QUOTE, request, verify, wait_ready
from display import format_table, report_link
from docker_api import Docker

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = sorted(path.parent.name for path in (ROOT / 'examples').glob('*/example.json'))


def percentile(values, percent):
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def working_set(stats):
    memory = stats['memory_stats']
    usage = memory.get('usage')
    if not isinstance(usage, int) or usage <= 0:
        raise ValueError('Docker did not report container memory')
    inactive = memory.get('stats', {}).get('inactive_file',
               memory.get('stats', {}).get('total_inactive_file', 0))
    return max(0, usage - inactive) / 1024**2


def summarize(records):
    return {'runs': len(records),
            'ready_ms_median': statistics.median(r['ready_ms'] for r in records),
            'ready_ms_p95': percentile([r['ready_ms'] for r in records], 95),
            'first_quote_ms_median': statistics.median(r['first_quote_ms'] for r in records),
            'ready_container_memory_mib_median': statistics.median(r['ready_container_memory_mib'] for r in records),
            'container_cpu_seconds_mean': statistics.mean(r['container_cpu_seconds'] for r in records)}


def measure(docker, config, network, args, directory, label):
    container = None
    try:
        result = docker.request('POST', '/containers/create', {
            'Image': config['image'], 'ExposedPorts': {'8080/tcp': {}},
            'Labels': {'dev.aot-buildpacks.benchmark': label},
            'HostConfig': {'NanoCpus': 1000000000, 'Memory': 512 * 1024**2,
                           'Init': True, 'NetworkMode': network}})
        container = result['Id']
        started = time.perf_counter()
        docker.request('POST', f'/containers/{container}/start')
        inspect = docker.request('GET', f'/containers/{container}/json')
        host = inspect['NetworkSettings']['Networks'][network]['IPAddress']

        def check_running():
            state = docker.request('GET', f'/containers/{container}/json')['State']
            if not state.get('Running'):
                detail = '\n'.join(docker.logs(container).splitlines()[-12:])
                raise RuntimeError(
                    f'{config["name"]} exited before readiness '
                    f'(status={state.get("Status")}, exit={state.get("ExitCode")}, '
                    f'OOMKilled={state.get("OOMKilled", False)}).\n{detail}')

        ready = wait_ready(host, 8080, config, args.timeout, check_running=check_running)
        ready_ms = (time.perf_counter() - started) * 1000
        quote = request(host, 8080, '/quotes', '{"quantities":{"1":2,"2":1}}')
        first_quote_ms = (time.perf_counter() - started) * 1000
        if quote != QUOTE:
            raise ValueError('Incorrect first quote response')
        # Sample after the first quote, before the rest of the correctness checks.
        stats = docker.request('GET', f'/containers/{container}/stats?stream=false&one-shot=true')
        memory = working_set(stats)
        outputs = verify(host, 8080, args.iterations)
        return {'example': config['name'], 'ready_ms': ready_ms, 'first_quote_ms': first_quote_ms,
                'ready_container_memory_mib': memory,
                'container_cpu_seconds': stats['cpu_stats']['cpu_usage']['total_usage'] / 1e9,
                'ready': ready, 'verified_outputs': outputs}
    finally:
        if container:
            try:
                (directory / f'{label}.log').write_text(docker.logs(container))
            finally:
                docker.remove(container)


def report(folder, configs, summaries, metadata):
    rows = [('Mode', 'Median startup', 'p95 startup', 'Median container memory')]
    for config in configs:
        result = summaries[config['name']]
        rows.append((config['label'], f'{result["ready_ms_median"]:,.0f} ms',
                     f'{result["ready_ms_p95"]:,.0f} ms',
                     f'{result["ready_container_memory_mib_median"]:.2f} MiB'))
    print('\nBuildpack application results\n')
    print(format_table(rows))
    print('\nStartup includes container start. Memory is container working set near readiness.\n')
    print(f'Report: {report_link(folder / "report.html")}\n')
    table = ''.join('<tr>' + ''.join(f'<td>{html.escape(cell)}</td>' for cell in row) + '</tr>' for row in rows)
    links = ' · '.join(f'<a href="artifacts/{html.escape(path.name)}">{html.escape(path.name)}</a>'
                       for path in sorted((folder / 'artifacts').iterdir()) if path.is_file())
    (folder / 'report.html').write_text(f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Buildpack application comparison</title><style>body{{background:#151a1f;color:#ddd;font:16px system-ui;max-width:1100px;margin:40px auto;padding:0 20px}}table{{border-collapse:collapse;width:100%}}td{{padding:12px;border-bottom:1px solid #43484d;text-align:right}}td:first-child{{text-align:left}}tr:first-child{{color:#ffe0a3;font-weight:bold}}a{{color:#ffe0a3}}</style></head>
<body><h1>Buildpack application results</h1><table>{table}</table>
<p>Fresh containers; one CPU and 512 MiB each. Startup includes Docker container-start and the CNB launcher,
then HTTP readiness polling every 20 ms. Image pulls, builds and container creation are excluded.
Memory is sampled just after the first verified quote response.
Memory is container working set (usage minus inactive file pages), sampled near readiness, not application process RSS.
CPU time covers all container processes through that sample. These results differ in scope from the Dockerfile project's process-only benchmarks.
Default OS page cache stays enabled. p95 is descriptive at this sample count.</p>
<p>{args_escape(metadata['runs'])} measured starts and {args_escape(metadata['warmups'])} warmups per image;
order shuffled with seed 42. Native uses Serial GC; JVM uses G1. Runtime versions are reported in the raw responses.
Buildpacks select their own JVM/compiler patch versions. Builder and image IDs are recorded with the evidence.</p>
<p>{links}</p></body></html>''')


def args_escape(value):
    return html.escape(str(value))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--example', choices=[*EXAMPLES, 'all'], required=True)
    parser.add_argument('--image', help='Override the single-example image')
    parser.add_argument('--network', required=True)
    parser.add_argument('--runs', type=int, default=10)
    parser.add_argument('--warmups', type=int, default=2)
    parser.add_argument('--iterations', type=int, default=100000)
    parser.add_argument('--timeout', type=float, default=120)
    args = parser.parse_args()
    if args.runs < 1 or args.warmups < 0 or not 1 <= args.iterations <= 10000000 or args.timeout <= 0:
        parser.error('runs >= 1, warmups >= 0, iterations 1..10000000 and timeout > 0 required')
    if args.example == 'all' and args.image:
        parser.error('--image is only valid for a single example')
    names = EXAMPLES if args.example == 'all' else [args.example]
    configs = [json.loads((ROOT / 'examples' / name / 'example.json').read_text()) for name in names]
    if args.image:
        configs[0]['image'] = args.image
    folder = Path('/results') / ('comparison' if args.example == 'all' else args.example) / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    directory = folder / 'artifacts'
    directory.mkdir(parents=True)
    docker = Docker()
    metadata = {'runs': args.runs, 'warmups': args.warmups, 'iterations': args.iterations,
                'seed': 42, 'cpu_limit': 1, 'memory_limit_mib': 512, 'examples': configs, 'images': {}}
    records = {name: [] for name in names}
    session = uuid.uuid4().hex[:12]
    try:
        for config in configs:
            image = docker.image(config['image'])
            metadata['images'][config['name']] = {key: image.get(key) for key in ('Id', 'RepoDigests', 'Architecture', 'Os', 'Size')}
            metadata['images'][config['name']]['buildpack_metadata'] = image.get('Config', {}).get('Labels', {}).get('io.buildpacks.build.metadata')
            build_artifacts = Path('/results') / config['name'] / 'build-artifacts'
            if build_artifacts.exists():
                import shutil
                for path in build_artifacts.iterdir():
                    if path.is_file():
                        shutil.copyfile(path, directory / f'{config["name"]}-{path.name}')
        for number in range(args.warmups):
            for config in configs:
                measure(docker, config, args.network, args, directory, f'{session}-{config["name"]}-warmup-{number}')
        order = random.Random(42)
        with (directory / 'runs.jsonl').open('w') as raw:
            for number in range(1, args.runs + 1):
                shuffled = configs.copy()
                order.shuffle(shuffled)
                for config in shuffled:
                    time.sleep(.1)
                    record = measure(docker, config, args.network, args, directory, f'{session}-{config["name"]}-{number}')
                    record['run'] = number
                    records[config['name']].append(record)
                    raw.write(json.dumps(record) + '\n');raw.flush()
                    print(f'{config["label"]} {number}/{args.runs}: {record["ready_ms"]:.2f} ms', flush=True)
        summaries = {name: summarize(values) for name, values in records.items()}
        (directory / 'summary.json').write_text(json.dumps(summaries, indent=2) + '\n')
        (directory / 'environment.json').write_text(json.dumps(metadata, indent=2) + '\n')
        with (directory / 'runs.csv').open('w', newline='') as output:
            fields = ['example', 'run', 'ready_ms', 'first_quote_ms', 'ready_container_memory_mib', 'container_cpu_seconds']
            writer = csv.DictWriter(output, fieldnames=fields, extrasaction='ignore');writer.writeheader()
            for values in records.values():
                writer.writerows(values)
        report(folder, configs, summaries, metadata)
    except (Exception, KeyboardInterrupt) as error:
        (directory / 'failure.json').write_text(json.dumps({'error': str(error)}, indent=2) + '\n')
        (directory / 'environment.json').write_text(json.dumps(metadata, indent=2) + '\n')
        (directory / 'summary.json').unlink(missing_ok=True)
        print(f'Benchmark failed: {error}\nEvidence: {directory}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
