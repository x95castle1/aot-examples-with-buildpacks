"""Shared catalog contract; no application code is imported from another example."""
import http.client
import json
import time

PRODUCT = {"id": 1, "name": "Keyboard", "priceCents": 9900}
QUOTE_BODY = '{"quantities":{"1":2,"2":1}}'
QUOTE = {"subtotalCents": 22300, "discountCents": 2230, "totalCents": 20070}


def checksum(iterations):
    value, mask = 0x1234ABCD, (1 << 64) - 1
    for _ in range(iterations):
        value ^= value << 13 & mask
        value ^= value >> 7
        value ^= value << 17 & mask
    return value if value < 1 << 63 else value - (1 << 64)


def request(host, port, route, body=None, status=200):
    connection = http.client.HTTPConnection(host, port, timeout=2)
    try:
        connection.request('POST' if body else 'GET', route, body,
                           {'Content-Type': 'application/json'} if body else {})
        response = connection.getresponse()
        content = response.read()
        if response.status != status:
            raise ValueError(f'{route}: expected HTTP {status}, got {response.status}: {content!r}')
        return json.loads(content) if status == 200 else None
    finally:
        connection.close()


def verify_ready(response, config):
    expected = {'ready': True, 'productCount': 8, 'catalogLabel': 'Catalog',
                'springAot': config['spring_aot'], 'generatedInitializer': config['spring_aot']}
    for key, value in expected.items():
        if response.get(key) != value:
            raise ValueError(f'Readiness {key}: expected {value}, got {response.get(key)}')
    if str(response.get('javaVersion', '')).split('.')[0] != '25' or response.get('springBootVersion') != '4.1.1':
        raise ValueError('Expected Java 25 and Spring Boot 4.1.1')


def wait_ready(host, port, config, timeout, check_running=None):
    deadline, last = time.monotonic() + timeout, None
    while time.monotonic() < deadline:
        if check_running:
            check_running()
        try:
            response = request(host, port, '/ready')
        except (OSError, http.client.HTTPException, ValueError) as error:
            last = error
            time.sleep(.02)
            continue
        # A wrong mode is a failure, not a readiness condition to wait out.
        verify_ready(response, config)
        return response
    raise TimeoutError(f'No verified readiness within {timeout}s: {last}')


def cases(iterations):
    return [('/products/1', None, PRODUCT), ('/quotes', QUOTE_BODY, QUOTE),
            (f'/compute?iterations={iterations}', None,
             {'iterations': iterations, 'checksum': checksum(iterations)}),
            ('/native-metadata', None, {'policy': 'ten-percent', 'catalogResource': True})]


def verify(host, port, iterations, show=None):
    outputs = {}
    for route, body, expected in cases(iterations):
        actual = request(host, port, route, body)
        if actual != expected:
            raise ValueError(f'{route}: expected {expected!r}, got {actual!r}')
        outputs[route] = actual
        if show:
            show(route, body, actual)
    for route in ('/products/99', '/missing'):
        request(host, port, route, status=404)
    request(host, port, '/compute?iterations=0', status=400)
    request(host, port, '/quotes', '{"quantities":{"1":0}}', status=400)
    return outputs
