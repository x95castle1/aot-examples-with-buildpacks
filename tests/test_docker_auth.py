"""Registry authentication reaches pack without leaking unrelated logins or helper settings."""
import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import docker_auth


class DockerAuthTest(unittest.TestCase):
    def test_desktop_helper_credentials_are_resolved_for_container(self):
        credentials = {'Username': 'example-user', 'Secret': 'example-secret'}
        result = subprocess.CompletedProcess([], 0, json.dumps(credentials), '')
        with patch.object(docker_auth.shutil, 'which', return_value='/helper'), \
                patch.object(docker_auth.subprocess, 'run', return_value=result) as get:
            resolved = docker_auth.resolve({'credsStore': 'desktop'}, 'docker.io')
        self.assertEqual({'auth': base64.b64encode(b'example-user:example-secret').decode()}, resolved)
        self.assertEqual(['/helper', 'get'], get.call_args.args[0])
        self.assertEqual('https://index.docker.io/v1/', get.call_args.kwargs['input'])

    def test_identity_token_uses_docker_token_format(self):
        result = subprocess.CompletedProcess([], 0, json.dumps({'Username': '<token>', 'Secret': 'example-token'}), '')
        with patch.object(docker_auth.shutil, 'which', return_value='/helper'), \
                patch.object(docker_auth.subprocess, 'run', return_value=result):
            self.assertEqual({'identitytoken': 'example-token'}, docker_auth.resolve({'credsStore': 'desktop'}, 'docker.io'))

    def test_exports_only_relevant_registries_with_private_permissions(self):
        with tempfile.TemporaryDirectory() as location:
            root = Path(location)
            source = root / 'host-config.json'
            source.write_text(json.dumps({'credsStore': 'desktop', 'auths': {
                'https://index.docker.io/v1/': {'auth': 'hub-login'},
                'registry.example.com': {'identitytoken': 'builder-login'},
                'unrelated.example.com': {'auth': 'unrelated-login'}}}))
            output = root / 'pack-config'
            docker_auth.prepare(output, 'registry.example.com/java-builder:latest', source)
            config = json.loads((output / 'config.json').read_text())
            self.assertEqual({'auths': {'https://index.docker.io/v1/': {'auth': 'hub-login'},
                                       'registry.example.com': {'identitytoken': 'builder-login'}}}, config)
            self.assertEqual(0o700, output.stat().st_mode & 0o777)
            self.assertEqual(0o600, (output / 'config.json').stat().st_mode & 0o777)

    def test_missing_login_can_use_public_registries(self):
        self.assertIsNone(docker_auth.resolve({}, 'docker.io'))

    def test_bad_helper_output_is_not_in_error(self):
        result = subprocess.CompletedProcess([], 0, 'example-sensitive-output', '')
        with patch.object(docker_auth.shutil, 'which', return_value='/helper'), \
                patch.object(docker_auth.subprocess, 'run', return_value=result):
            with self.assertRaisesRegex(ValueError, '^Docker credential helper returned invalid JSON$'):
                docker_auth.resolve({'credsStore': 'desktop'}, 'docker.io')


if __name__ == '__main__':
    unittest.main()
