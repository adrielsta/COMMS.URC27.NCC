import json
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
from comms.c2 import BoundedServer, C2, make_handler, trusted_hosts


class HttpSecurityTests(unittest.TestCase):
    def setUp(self):
        self.c2 = C2(b'x' * 32, udp_port=0)
        self.server = BoundedServer(('127.0.0.1', 0), make_handler(self.c2, 1))
        self.port = self.server.server_port
        self.server.RequestHandlerClass = make_handler(self.c2, self.port)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.c2.sock.close()

    def request(self, path='/api/state', data=None, **headers):
        return urllib.request.urlopen(urllib.request.Request(self.url + path, data=data, headers=headers), timeout=3)

    def test_dns_rebinding_host_and_cross_site_origin_rejected(self):
        for headers in ({'Host': 'attacker.example'}, {'Origin': 'https://attacker.example'}):
            with self.subTest(headers=headers), self.assertRaises(urllib.error.HTTPError) as error:
                self.request(**headers)
            self.assertEqual(error.exception.code, 403)

    def test_csrf_and_content_type_required(self):
        for headers, expected in [({}, 403), ({'X-CSRF-Token': self.c2.csrf}, 415)]:
            with self.subTest(headers=headers), self.assertRaises(urllib.error.HTTPError) as error:
                self.request('/api/faults', data=b'{}', **headers)
            self.assertEqual(error.exception.code, expected)

    def test_bounded_body_and_nonfinite_json(self):
        for body, expected in [(b'x' * 98305, 413), (b'{"loss":NaN}', 400)]:
            with self.subTest(size=len(body)), self.assertRaises(urllib.error.HTTPError) as error:
                self.request('/api/faults', data=body, **{'X-CSRF-Token': self.c2.csrf, 'Content-Type': 'application/json'})
            self.assertEqual(error.exception.code, expected)

    def test_exact_codespaces_host_allowed_only_when_configured(self):
        with patch.dict('os.environ', {'CODESPACE_NAME': 'test-abc', 'GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN': 'app.github.dev'}):
            hosts = trusted_hosts(8080)
            self.assertIn('test-abc-8080.app.github.dev', hosts)
            self.assertNotIn('evil-8080.app.github.dev', hosts)
            handler = make_handler(self.c2, 8080)
        self.server.RequestHandlerClass = handler
        with self.request(Host='test-abc-8080.app.github.dev', Origin='https://test-abc-8080.app.github.dev') as response:
            self.assertEqual(response.status, 200)
            self.assertIn("frame-ancestors 'none'", response.headers['Content-Security-Policy'])
            self.assertTrue(json.load(response)['simulation'])


if __name__ == '__main__':
    unittest.main()
