import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import unittest
import urllib.error
import urllib.request

from comms.c2 import ROOT, BoundedServer, C2, make_handler
from scripts.fetch_imagery import jpeg_dimensions, verify_bytes


class ImageryTests(unittest.TestCase):
    def test_offline_bundle_is_complete_georeferenced_and_hash_pinned(self):
        manifest = json.loads((ROOT / 'web/imagery/metadata.json').read_text())
        self.assertEqual(manifest['imagery_kind'], 'historical-satellite-mosaic')
        self.assertFalse(manifest['network_at_runtime'])
        self.assertEqual(manifest['year'], 2016)
        self.assertEqual(manifest['crs'], 'EPSG:3857')
        self.assertIn('Copernicus', manifest['attribution'])
        self.assertIn('by/4.0', manifest['license']['url'])
        cells = {(t['x'], t['y']) for t in manifest['tiles']}
        self.assertEqual(cells, {(x, y) for x in range(6299, 6302) for y in range(12590, 12593)})
        for tile in manifest['tiles']:
            raw = (ROOT / 'web' / tile['path'].lstrip('/')).read_bytes()
            verify_bytes(raw, tile, manifest['tile_size'])
            self.assertEqual(jpeg_dimensions(raw), (256, 256))
            with self.assertRaises(ValueError):
                verify_bytes(raw[:-1], tile, manifest['tile_size'])

    def test_imagery_helper_verifies_without_downloading(self):
        result = subprocess.run([sys.executable, 'scripts/fetch_imagery.py', '--verify'],
                                cwd=ROOT, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Verified 9 historical satellite tiles', result.stdout)


class ImageryHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c2 = C2(b'z' * 32, udp_port=0)
        cls.server = BoundedServer(('127.0.0.1', 0), make_handler(cls.c2, 1))
        cls.server.RequestHandlerClass = make_handler(cls.c2, cls.server.server_port)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.c2.sock.close()

    def test_manifest_and_original_tiles_served_with_no_external_redirects(self):
        with urllib.request.urlopen(self.url + '/imagery/metadata.json', timeout=2) as response:
            self.assertEqual(response.headers.get_content_type(), 'application/json')
            self.assertIn("img-src 'self'", response.headers['Content-Security-Policy'])
            manifest = json.load(response)
        for tile in manifest['tiles']:
            with urllib.request.urlopen(self.url + tile['path'], timeout=2) as response:
                self.assertEqual(response.geturl(), self.url + tile['path'])
                self.assertEqual(response.headers.get_content_type(), 'image/jpeg')
                self.assertEqual(hashlib.sha256(response.read()).hexdigest(), tile['sha256'])
        with urllib.request.urlopen(self.url + '/geoview.js', timeout=2) as response:
            self.assertEqual(response.headers.get_content_type(), 'text/javascript')

    def test_imagery_route_cannot_expose_project_or_runtime_files(self):
        for route in ['/imagery/../comms/c2.py', '/imagery/%2e%2e/.runtime/transport.key',
                      '/imagery/LICENSE.txt', '/imagery/tile-15-0-0.jpg', '/imagery/metadata.json?url=https://example.com']:
            with self.subTest(route=route), self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(self.url + route, timeout=2)
            self.assertEqual(error.exception.code, 404)


if __name__ == '__main__':
    unittest.main()
