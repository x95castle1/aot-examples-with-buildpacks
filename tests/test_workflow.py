"""Check selection, image-build failure propagation and application dispatch without Docker."""
import os
from pathlib import Path
import pty
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.location = tempfile.TemporaryDirectory(prefix='aot-buildpacks-test-')
        self.addCleanup(self.location.cleanup)
        self.bin = Path(self.location.name)
        self.log = self.bin / 'calls'
        self.picks = self.bin / 'picks'
        self.choices = self.bin / 'choices'
        self.env = {**os.environ, 'PATH': f'{self.bin}:/usr/bin:/bin',
                    'LOG': str(self.log), 'PICKS': str(self.picks), 'CHOICES': str(self.choices),
                    'CHOICE': '02-spring-aot', 'PLATFORM': 'linux/arm64'}
        for key in ('EXAMPLE', 'IMAGE', 'MAKEFLAGS', 'MFLAGS', 'MAKEOVERRIDES'):
            self.env.pop(key, None)
        self.executable('docker', 'printf "%s\\n" "$*" >> "$LOG"\n'
                        'case "$*" in *" pack build "*) exit "${BUILD_EXIT:-0}" ;; esac\n')
        # Test output remains in the temporary test directory rather than real results.
        self.executable('tee', '/bin/cat\n')
        self.executable('python3', 'exit 0\n')
        self.executable('fzf', 'echo picked >> "$PICKS"\ncat > "$CHOICES"\necho "$CHOICE"\n')

    def executable(self, name, content):
        path = self.bin / name;path.write_text('#!/bin/sh\n' + content);path.chmod(0o755)

    def make(self, *args, terminal=False):
        if terminal:
            master, slave = pty.openpty()
            try:
                return subprocess.run(['make', *args], cwd=ROOT, env=self.env, stdin=slave,
                                      capture_output=True, text=True, timeout=15)
            finally:
                os.close(master);os.close(slave)
        return subprocess.run(['make', *args], cwd=ROOT, env=self.env, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=15)

    def test_help_needs_no_selection_or_docker(self):
        result = self.make('help')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse(self.log.exists())
        self.assertIn('network\n\nOmit EXAMPLE', result.stdout)

    def test_test_app_builds_then_starts_and_checks_selected_api(self):
        result = self.make('test-app', 'EXAMPLE=02', 'PORT=8088', 'ITERATIONS=3')
        self.assertEqual(0, result.returncode, result.stderr)
        calls = self.log.read_text()
        self.assertIn('pack build aot-buildpacks/02-spring-aot:local', calls)
        self.assertIn('--env-file /workspace/examples/02-spring-aot/buildpack.env', calls)
        self.assertIn('--platform linux/arm64', calls)
        self.assertIn('--env DOCKER_CONFIG=/pack-docker-config pack build', calls)
        self.assertIn('/pack-docker-config:ro', calls)
        self.assertLess(calls.index('pack build'), calls.index('up --detach app'))
        self.assertLess(calls.index('up --detach app'), calls.index('client --example'))
        self.assertIn('--display-url http://localhost:8088 --iterations 3', calls)

    def test_build_failure_stops_before_app_start_and_survives_tee(self):
        self.env['BUILD_EXIT'] = '7'
        result = self.make('test-app', 'EXAMPLE=03')
        self.assertNotEqual(0, result.returncode)
        self.assertNotIn('up --detach', self.log.read_text())
        self.assertIn('Build failed', result.stderr)

    def test_picker_shares_one_selection_across_multiple_goals(self):
        result = self.make('validate', 'clean', terminal=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(['picked'], self.picks.read_text().splitlines())
        self.assertEqual(4, len(self.choices.read_text().splitlines()))
        self.assertIn('examples/02-spring-aot/compose.yaml', self.log.read_text())

    def test_bench_passes_image_and_sampling_options(self):
        result = self.make('bench', 'EXAMPLE=04', 'RUNS=2', 'WARMUPS=0',
                           'IMAGE=registry.example.com/catalog:native')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('--image registry.example.com/catalog:native', self.log.read_text())
        self.assertIn('--runs 2 --warmups 0', self.log.read_text())

    def test_compare_builds_all_four_without_picker(self):
        result = self.make('compare', 'RUNS=1', 'WARMUPS=0')
        self.assertEqual(0, result.returncode, result.stderr)
        calls = self.log.read_text()
        self.assertEqual(4, calls.count('pack build aot-buildpacks/'))
        self.assertIn('benchmark --example all', calls)
        self.assertFalse(self.picks.exists())

    def test_noninteractive_selection_requires_example(self):
        result = self.make('test-app')
        self.assertNotEqual(0, result.returncode)
        self.assertIn('needs a terminal', result.stderr)
        self.assertFalse(self.log.exists())

    def test_invalid_example_runs_nothing(self):
        result = self.make('build', 'EXAMPLE=05')
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(self.log.exists())


if __name__ == '__main__':
    unittest.main()
