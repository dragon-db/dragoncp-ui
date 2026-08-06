#!/usr/bin/env python3
"""Same-origin serving for the production React application."""

import logging
from pathlib import Path

from flask import abort, jsonify, send_from_directory
from werkzeug.exceptions import NotFound


logger = logging.getLogger('dragoncp.frontend')
FRONTEND_DIST_DIR = Path(__file__).resolve().parent / 'frontend' / 'dist'


def serve_frontend(frontend_path: str, dist_dir: Path = FRONTEND_DIST_DIR):
    """Serve a built file or the SPA shell for an extensionless client route."""
    if frontend_path in {'api', 'socket.io'} or frontend_path.startswith(
        ('api/', 'socket.io/')
    ):
        abort(404)

    if not (dist_dir / 'index.html').is_file():
        logger.error('React frontend build is missing at %s', dist_dir)
        return jsonify({
            'status': 'error',
            'code': 'FRONTEND_BUILD_MISSING',
            'message': (
                'The React frontend has not been built. Run npm ci and npm run '
                'build in frontend/.'
            ),
        }), 503

    if frontend_path:
        try:
            response = send_from_directory(dist_dir, frontend_path)
            if frontend_path.startswith('assets/'):
                response.cache_control.public = True
                response.cache_control.max_age = 31536000
                response.cache_control.immutable = True
            return response
        except NotFound:
            # Missing asset-like paths should be real 404s. Only extensionless
            # navigation paths are TanStack Router routes that need the shell.
            if frontend_path.startswith('assets/') or Path(frontend_path).suffix:
                raise

    response = send_from_directory(dist_dir, 'index.html')
    response.cache_control.no_cache = True
    return response
