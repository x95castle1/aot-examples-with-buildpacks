"""Reject fast incorrect apps and keep container memory/cleanup semantics explicit."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'benchmark'))
sys.path.insert(0, str(ROOT / 'scripts'))
import common
import run
from render_k8s import render


class ContractTest(unittest.TestCase):
    def test_checksum_matches_known_java_result(self):
        self.assertEqual(-7520082499104634107, common.checksum(100000))
        self.assertEqual(325410109145977306, common.checksum(1))

    def test_incorrect_fast_quote_is_rejected(self):
        def response(host, port, route, body=None, status=200):
            return common.PRODUCT if route == '/products/1' else {'totalCents': 1}
        with patch.object(common, 'request', side_effect=response):
            with self.assertRaisesRegex(ValueError, '/quotes'):
                common.verify('localhost', 8080, 1)

    def test_wrong_runtime_mode_fails_immediately(self):
        ready = {'ready': True, 'productCount': 8, 'catalogLabel': 'Catalog',
                 'springAot': False, 'generatedInitializer': False,
                 'javaVersion': '25.0.4', 'springBootVersion': '4.1.1'}
        with patch.object(common, 'request', return_value=ready) as request:
            with self.assertRaisesRegex(ValueError, 'springAot'):
                common.wait_ready('localhost', 8080, {'spring_aot': True}, 1)
            self.assertEqual(1, request.call_count)

    def test_exited_container_stops_readiness_polling_before_http(self):
        def exited():
            raise RuntimeError('exited with code 1')

        with patch.object(common, 'request') as request:
            with self.assertRaisesRegex(RuntimeError, 'exited with code 1'):
                common.wait_ready('localhost', 8080, {'spring_aot': False}, 120,
                                  check_running=exited)
            request.assert_not_called()

    def test_jvm_delimiter_and_thread_budget_survive_config_parsing(self):
        import tomllib
        for folder in sorted((ROOT / 'examples').iterdir()):
            if folder.name.startswith('04'):
                continue
            descriptor = tomllib.loads((folder / 'project.toml').read_text())
            environment = {value['name']: value['value'] for value in descriptor['io']['buildpacks']['build']['env']}
            self.assertEqual(' ', environment['BPE_DELIM_JAVA_TOOL_OPTIONS'], folder.name)
            settings = dict(line.strip().split('=', 1) for line in (folder / 'buildpack.env').read_text().splitlines()
                            if line.strip() and not line.startswith('#'))
            self.assertNotIn('BPE_DELIM_JAVA_TOOL_OPTIONS', settings)
            self.assertEqual('50', settings['BPE_OVERRIDE_BPL_JVM_THREAD_COUNT'])

    def test_memory_is_container_working_set(self):
        stats = {'memory_stats': {'usage': 100 * 1024**2,
                                 'stats': {'inactive_file': 20 * 1024**2}}}
        self.assertEqual(80, run.working_set(stats))
        with self.assertRaises(ValueError):
            run.working_set({'memory_stats': {}})

    def test_summary_uses_medians_and_keeps_units(self):
        records = [{'ready_ms': value, 'first_quote_ms': value + 10,
                    'ready_container_memory_mib': value, 'container_cpu_seconds': 2}
                   for value in [1, 3, 100]]
        summary = run.summarize(records)
        self.assertEqual(3, summary['ready_ms_median'])
        self.assertEqual(3, summary['ready_container_memory_mib_median'])
        self.assertEqual(90.3, summary['ready_ms_p95'])

    def test_failed_readiness_logs_and_removes_own_container(self):
        class FakeDocker:
            def __init__(self):
                self.removed = []
            def request(self, method, route, body=None):
                if route == '/containers/create':
                    return {'Id': 'our-container'}
                if route.endswith('/json'):
                    return {'NetworkSettings': {'Networks': {'test-network': {'IPAddress': '10.0.0.2'}}}}
                return None
            def logs(self, container):
                return 'application diagnostic'
            def remove(self, container):
                self.removed.append(container)
        from types import SimpleNamespace
        docker = FakeDocker()
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(run, 'wait_ready', side_effect=TimeoutError('not ready')):
                with self.assertRaises(TimeoutError):
                    run.measure(docker, {'name': 'test', 'image': 'test:local'}, 'test-network',
                                SimpleNamespace(timeout=1), Path(directory), 'test-run')
            self.assertEqual(['our-container'], docker.removed)
            self.assertEqual('application diagnostic', (Path(directory) / 'test-run.log').read_text())

    def test_manifest_image_override_is_rendered_without_applying(self):
        rendered = render('03-spring-jvm-aot-cache', 'registry.example.com/catalog:cache')
        self.assertIn('image: registry.example.com/catalog:cache', rendered)
        self.assertIn('name: catalog-03', rendered)
        self.assertIn('path: /ready', rendered)
        self.assertIn('kind: Service', rendered)
        with self.assertRaises(ValueError):
            render('03-spring-jvm-aot-cache', 'image:local\n  privileged: true')


if __name__ == '__main__':
    unittest.main()
