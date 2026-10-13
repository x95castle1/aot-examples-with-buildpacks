"""Small stdlib Docker API client for isolated benchmark containers."""
import http.client
import json
import socket
from urllib.parse import quote


class UnixConnection(http.client.HTTPConnection):
    def __init__(self, path, timeout=120):
        super().__init__('localhost', timeout=timeout)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


class Docker:
    def __init__(self, path='/var/run/docker.sock'):
        self.path = path

    def request(self, method, route, body=None, raw=False, allow_missing=False):
        connection = UnixConnection(self.path)
        try:
            connection.request(method, '/v1.44' + route,
                               json.dumps(body).encode() if body is not None else None,
                               {'Content-Type': 'application/json'})
            response = connection.getresponse()
            content = response.read()
            if response.status == 404 and allow_missing:
                return None
            if response.status >= 400:
                raise RuntimeError(f'Docker {method} {route}: {response.status} {content.decode(errors="replace")}')
            if raw:
                return content
            return json.loads(content) if content else None
        finally:
            connection.close()

    def image(self, name):
        return self.request('GET', f'/images/{quote(name, safe="")}/json')

    def remove(self, container):
        self.request('DELETE', f'/containers/{container}?force=true', allow_missing=True)

    def logs(self, container):
        content = self.request('GET', f'/containers/{container}/logs?stdout=true&stderr=true', raw=True)
        # Docker multiplexed streams have an eight-byte header per frame.
        chunks = []
        while len(content) >= 8 and content[0] in (0, 1, 2) and content[1:4] == b'\0\0\0':
            length = int.from_bytes(content[4:8], 'big')
            chunks.append(content[8:8 + length])
            content = content[8 + length:]
        return b''.join(chunks).decode(errors='replace') if chunks else content.decode(errors='replace')
