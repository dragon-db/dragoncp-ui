#!/usr/bin/env python3
"""
What the WebSocket diagnostics card reads: each live connection, and the
transport it uses now rather than the one it opened with.
"""

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import websocket  # noqa: E402


def fake_socketio(upgraded_by_sid):
    """A Socket.IO server whose engine sockets say whether they upgraded."""
    sockets = {f"eio-{sid}": SimpleNamespace(upgraded=up) for sid, up in upgraded_by_sid.items()}
    manager = SimpleNamespace(eio_sid_from_sid=lambda sid, namespace: f"eio-{sid}")
    return SimpleNamespace(server=SimpleNamespace(manager=manager, eio=SimpleNamespace(sockets=sockets)))


class DescribeConnectionsTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(websocket.websocket_connections.clear)
        patcher = patch.object(websocket, '_socketio', None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.now = datetime(2026, 10, 21, 12, 0, 0)

    def add(self, sid, *, connected_ago, idle, transport='polling', timeout=1800):
        with websocket.websocket_connections_lock:
            websocket.websocket_connections[sid] = {
                'connected_at': self.now - timedelta(seconds=connected_ago),
                'last_activity': self.now - timedelta(seconds=idle),
                'timeout_seconds': timeout,
                'username': 'admin',
                'transport': transport,
            }

    def test_rows_count_in_seconds_and_keep_the_minute_fields(self):
        self.add('abcdefgh12345', connected_ago=3725, idle=95)
        [row] = websocket.describe_connections(self.now)
        self.assertEqual(row['session_id'], 'abcdefgh...')
        self.assertEqual(row['connected_seconds'], 3725)
        self.assertEqual(row['idle_seconds'], 95)
        self.assertEqual(row['timeout_seconds'], 1800)
        # The browser closes it five minutes before the server's backstop.
        self.assertEqual(row['idle_limit_seconds'], 1500)
        self.assertEqual(row['connected_minutes_ago'], 62)
        self.assertEqual(row['last_activity_minutes_ago'], 1)
        self.assertEqual(row['timeout_minutes'], 30)
        self.assertEqual(row['username'], 'admin')

    def test_most_recently_used_comes_first(self):
        self.add('quietsid0000', connected_ago=600, idle=500)
        self.add('busysid00000', connected_ago=900, idle=5)
        rows = websocket.describe_connections(self.now)
        self.assertEqual([r['session_id'] for r in rows], ['busysid0...', 'quietsid...'])

    def test_an_upgraded_connection_reports_websocket(self):
        # Every browser opens over polling, so the transport saved at connect
        # is "polling" even once it has moved to WebSocket.
        self.add('upgradedsid1', connected_ago=60, idle=1)
        self.add('stucksid0000', connected_ago=60, idle=2)
        with patch.object(websocket, '_socketio',
                          fake_socketio({'upgradedsid1': True, 'stucksid0000': False})):
            rows = {r['session_id']: r['transport'] for r in websocket.describe_connections(self.now)}
        self.assertEqual(rows, {'upgraded...': 'websocket', 'stucksid...': 'polling'})

    def test_a_transport_layer_that_cannot_answer_falls_back_to_the_opening_one(self):
        self.add('oddsid000000', connected_ago=60, idle=1)
        broken = SimpleNamespace(server=SimpleNamespace(
            manager=SimpleNamespace(eio_sid_from_sid=lambda *_: (_ for _ in ()).throw(KeyError()))))
        with patch.object(websocket, '_socketio', broken):
            [row] = websocket.describe_connections(self.now)
        self.assertEqual(row['transport'], 'polling')


if __name__ == '__main__':
    unittest.main()
