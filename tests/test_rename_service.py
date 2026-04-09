#!/usr/bin/env python3

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from models.database import DatabaseManager
from models.webhook import RenameNotification
from services.rename_service import RenameService


class RenameServiceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)

        self.anime_dest = os.path.join(self.tempdir.name, 'anime')
        os.makedirs(self.anime_dest, exist_ok=True)

        db_path = os.path.join(self.tempdir.name, 'rename_service_test.db')
        self.db = DatabaseManager(db_path)
        self.rename_model = RenameNotification(self.db)
        self.service = RenameService(
            {
                'ANIME_DEST_PATH': self.anime_dest,
                'TVSHOW_DEST_PATH': os.path.join(self.tempdir.name, 'tvshows'),
            },
            self.rename_model,
        )

        self.series_folder = 'My Status as an Assassin Obviously Exceeds the Hero\'s (2025)'
        self.series_path = f'/remote/anime/{self.series_folder}'
        self.previous_relative_path = (
            'Season 01/My Status as an Assassin Obviously Exceeds the Hero\'s (2025) - '
            'S01E09 - 009 - The Assassin Sees The Sights [WEBDL-1080p][JA+EN][VARYG-Dragon DB].mkv'
        )
        self.new_relative_path = (
            'Season 01/My Status as an Assassin Obviously Exceeds the Hero\'s (2025) - '
            'S01E09 - 009 - The Assassin Sees The Sights [Anime Dual-Audio WEBDL-1080p][JA+EN][VARYG-Dragon DB].mkv'
        )
        self.previous_local_path = os.path.join(self.anime_dest, self.series_folder, self.previous_relative_path)
        self.new_local_path = os.path.join(self.anime_dest, self.series_folder, self.new_relative_path)
        os.makedirs(os.path.dirname(self.previous_local_path), exist_ok=True)
        with open(self.previous_local_path, 'w', encoding='utf-8') as handle:
            handle.write('test payload')

        self.webhook_data = {
            'eventType': 'Rename',
            'series': {
                'id': 277,
                'title': self.series_folder,
                'path': self.series_path,
            },
            'renamedEpisodeFiles': [
                {
                    'id': 9,
                    'previousPath': f'{self.series_path}/{self.previous_relative_path}',
                    'previousRelativePath': self.previous_relative_path,
                    'path': f'{self.series_path}/{self.new_relative_path}',
                    'relativePath': self.new_relative_path,
                }
            ],
        }

    def test_process_rename_webhook_persists_completed_at(self):
        success, result = self.service.process_rename_webhook(self.webhook_data, 'anime')

        self.assertTrue(success)
        self.assertEqual(result['status'], 'completed')
        self.assertIsNotNone(result.get('completed_at'))

        saved_notification = self.rename_model.get(result['notification_id'])
        self.assertIsNotNone(saved_notification)
        self.assertEqual(saved_notification['status'], 'completed')
        self.assertEqual(saved_notification['success_count'], 1)
        self.assertEqual(saved_notification['failed_count'], 0)
        self.assertIsNotNone(saved_notification.get('completed_at'))
        self.assertEqual(saved_notification['renamed_files'][0]['status'], 'success')
        self.assertFalse(os.path.exists(self.previous_local_path))
        self.assertTrue(os.path.exists(saved_notification['renamed_files'][0]['local_new_path']))

    def test_verify_rename_notification_checks_expected_target_path(self):
        success, result = self.service.process_rename_webhook(self.webhook_data, 'anime')
        self.assertTrue(success)

        verified, verify_result = self.service.verify_rename_notification(result['notification_id'])

        self.assertTrue(verified)
        self.assertEqual(verify_result['status'], 'verified')
        self.assertEqual(verify_result['verified_count'], 1)
        self.assertEqual(verify_result['failed_count'], 0)
        self.assertEqual(verify_result['files'][0]['status'], 'verified')
        self.assertIn('Expected renamed file exists locally', verify_result['files'][0]['message'])

    def test_process_rename_webhook_reports_persistence_failure_after_rename(self):
        with patch.object(self.rename_model, 'update', return_value=False) as mocked_update:
            success, result = self.service.process_rename_webhook(self.webhook_data, 'anime')

        self.assertFalse(success)
        self.assertTrue(result['persistence_error'])
        self.assertTrue(mocked_update.called)
        self.assertFalse(os.path.exists(self.previous_local_path))
        self.assertTrue(os.path.exists(self.new_local_path))


if __name__ == '__main__':
    unittest.main()
