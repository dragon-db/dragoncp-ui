#!/usr/bin/env python3
"""The production Flask process serves the React SPA, not the retired client."""

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from frontend_serving import serve_frontend
import start


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


class FrontendBuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.frontend = Path(self.tmp.name) / 'frontend'
        (self.frontend / 'src').mkdir(parents=True)
        (self.frontend / 'dist').mkdir()
        (self.frontend / 'node_modules').mkdir()
        (self.frontend / 'package.json').write_text('{}', encoding='utf-8')
        (self.frontend / 'package-lock.json').write_text('{"lockfileVersion": 3}', encoding='utf-8')
        (self.frontend / 'index.html').write_text('<main></main>', encoding='utf-8')
        (self.frontend / 'vite.config.ts').write_text('export default {}', encoding='utf-8')
        (self.frontend / 'src' / 'main.tsx').write_text('export {}', encoding='utf-8')
        (self.frontend / 'dist' / 'index.html').write_text('<main>built</main>', encoding='utf-8')
        self.digest_file = (
            self.frontend / 'node_modules' / '.dragoncp-package-lock.sha256'
        )

    def test_changed_lockfile_runs_npm_ci_and_records_digest_after_success(self):
        self.digest_file.write_text('outdated\n', encoding='utf-8')

        with patch.object(start.shutil, 'which', return_value='/usr/bin/npm'), \
                patch.object(start.subprocess, 'run') as run:
            self.assertTrue(start.build_frontend(self.frontend))

        self.assertEqual(
            [call.args[0] for call in run.call_args_list],
            [['/usr/bin/npm', 'ci'], ['/usr/bin/npm', 'run', 'build']],
        )
        expected = hashlib.sha256(
            (self.frontend / 'package-lock.json').read_bytes()
        ).hexdigest()
        self.assertEqual(self.digest_file.read_text(encoding='utf-8').strip(), expected)

    def test_failed_npm_ci_does_not_record_the_new_digest(self):
        self.digest_file.write_text('outdated\n', encoding='utf-8')
        failure = subprocess.CalledProcessError(1, ['npm', 'ci'])

        with patch.object(start.shutil, 'which', return_value='/usr/bin/npm'), \
                patch.object(start.subprocess, 'run', side_effect=failure):
            self.assertFalse(start.build_frontend(self.frontend))

        self.assertEqual(self.digest_file.read_text(encoding='utf-8').strip(), 'outdated')


if __name__ == '__main__':
    unittest.main()
