#!/usr/bin/env python3
"""The production Flask process serves the React SPA, not the retired client."""

import tempfile
import unittest
from pathlib import Path

from flask import Flask

from frontend_serving import serve_frontend


class FrontendServingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dist = Path(self.tmp.name)
        test_app = Flask(__name__, static_folder=None)

        @test_app.route('/', defaults={'frontend_path': ''})
        @test_app.route('/<path:frontend_path>')
        def frontend_app(frontend_path):
            return serve_frontend(frontend_path, self.dist)

        self.client = test_app.test_client()

    def write_build(self):
        (self.dist / 'assets').mkdir()
        (self.dist / 'index.html').write_text('<main>React shell</main>')
        (self.dist / 'assets' / 'app.js').write_text('window.dragoncp = true')

    def test_root_and_client_routes_serve_the_react_shell(self):
        self.write_build()

        self.assertIn(b'React shell', self.client.get('/').data)
        self.assertIn(b'React shell', self.client.get('/activity').data)

    def test_built_assets_are_served_with_long_cache_headers(self):
        self.write_build()

        response = self.client.get('/assets/app.js')

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'window.dragoncp', response.data)
        self.assertIn('immutable', response.headers['Cache-Control'])

    def test_unknown_api_paths_do_not_fall_back_to_the_spa(self):
        self.write_build()

        for path in ('/api/not-a-real-endpoint', '/socket.io'):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 404)
                self.assertNotIn(b'React shell', response.data)

    def test_missing_build_fails_with_an_actionable_response(self):
        response = self.client.get('/')

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()['code'], 'FRONTEND_BUILD_MISSING')


if __name__ == '__main__':
    unittest.main()
