#!/usr/bin/env python3
"""
Attribution: every consequential action has someone answerable for it.

The properties worth guarding, in the order they matter:

  Automation is never mistaken for a person. A backup that retention pruned and
  a backup a colleague deleted read differently, and the difference survives
  into the stored row rather than being reconstructed later.

  Nobody is attributed by accident. Where no actor can be established the entry
  says `system`, which is a statement that nobody was identified — not a guess
  at who it might have been.

  Recording never breaks the work. A restore that happened is a fact whether or
  not the trail caught it, so a failure to write bookkeeping must not turn into
  a failed request.

  A rename does not rewrite history. Entries keep the name as it read at the
  time and the stable account id beside it, so old entries stay truthful and can
  still be traced to the person they belong to.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import activity_log
from actor import (
    ACTOR_ADMIN,
    ACTOR_AUTOMATED,
    ACTOR_SYSTEM,
    AUTO_RETENTION,
    AUTO_SYNC_SCHEDULER,
    SYSTEM_ACTOR,
    acting_as,
    admin_actor,
    current_actor,
    webhook_actor,
)
from models.activity import ACTIONS, OUTCOME_FAILED, OUTCOME_REFUSED, Activity
from models.database import DatabaseManager
from models.transfer import Transfer


class ActivityTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

        with patch('builtins.print'):
            self.db = DatabaseManager(os.path.join(self._tmp.name, 'activity.db'))

        self.activity = Activity(self.db)
        self.transfers = Transfer(self.db)
        activity_log.set_store(self.activity)
        self.addCleanup(activity_log.set_store, None)

        printer = patch('builtins.print')
        printer.start()
        self.addCleanup(printer.stop)

    def entries(self, **filters):
        return self.activity.query(limit=200, **filters)['entries']

    def only(self, **filters):
        found = self.entries(**filters)
        self.assertEqual(len(found), 1, f"expected exactly one entry, got {len(found)}")
        return found[0]


class ActorResolutionTests(ActivityTestCase):
    def test_a_declared_automation_is_recorded_as_automation(self):
        with acting_as(AUTO_SYNC_SCHEDULER):
            activity_log.record('transfer.start', 'Started a scheduled sync')

        entry = self.only()
        self.assertEqual(entry['actor_kind'], ACTOR_AUTOMATED)
        self.assertEqual(entry['actor_name'], 'auto-sync')
        self.assertIsNone(entry['actor_account_id'])

    def test_with_nobody_declared_the_entry_says_system_not_a_person(self):
        activity_log.record('settings.update', 'Changed a setting')

        entry = self.only()
        self.assertEqual(entry['actor_kind'], ACTOR_SYSTEM)
        self.assertNotEqual(entry['actor_kind'], ACTOR_ADMIN)

    def test_an_explicit_actor_wins(self):
        activity_log.record('auth.login', 'Signed in', actor=admin_actor('priya', 4))

        entry = self.only()
        self.assertEqual(entry['actor_kind'], ACTOR_ADMIN)
        self.assertEqual(entry['actor_name'], 'priya')
        self.assertEqual(entry['actor_account_id'], 4)

    def test_declarations_nest_and_unwind(self):
        self.assertIs(current_actor(), SYSTEM_ACTOR)
        with acting_as(AUTO_SYNC_SCHEDULER):
            self.assertEqual(current_actor().name, 'auto-sync')
            with acting_as(AUTO_RETENTION):
                self.assertEqual(current_actor().name, 'retention')
            self.assertEqual(current_actor().name, 'auto-sync')
        self.assertIs(current_actor(), SYSTEM_ACTOR)

    def test_a_declaration_is_unwound_even_when_the_work_raises(self):
        # Otherwise the next job on this thread inherits the wrong identity.
        with self.assertRaises(RuntimeError):
            with acting_as(AUTO_RETENTION):
                raise RuntimeError('job blew up')
        self.assertIs(current_actor(), SYSTEM_ACTOR)

    def test_each_webhook_kind_names_itself(self):
        for media in ('movies', 'series', 'anime'):
            self.assertEqual(webhook_actor(media).name, f'webhook-{media}')
            self.assertEqual(webhook_actor(media).kind, ACTOR_AUTOMATED)


class RecordingTests(ActivityTestCase):
    def test_the_summary_survives_the_thing_it_describes(self):
        # A deleted backup has no row left to name it; the entry is the only
        # place that says what went.
        activity_log.record(
            'backup.delete', 'Deleted the backup of Example Show S01E01',
            target_type='backup_capture', target_id='cap_9',
            target_label='Example Show S01E01',
            actor=admin_actor('bob', 2),
        )

        entry = self.only()
        self.assertIn('Example Show S01E01', entry['summary'])
        self.assertEqual(entry['target_label'], 'Example Show S01E01')
        self.assertEqual(entry['target_id'], 'cap_9')

    def test_outcomes_are_distinguishable(self):
        activity_log.record('auth.login', 'Signed in', actor=admin_actor('bob', 2))
        activity_log.record_failure('auth.login_failed', 'Failed sign-in attempt')
        activity_log.record_refusal('auth.login_blocked', 'Blocked after repeated failures')

        self.assertEqual(len(self.entries(outcome='ok')), 1)
        self.assertEqual(len(self.entries(outcome=OUTCOME_FAILED)), 1)
        self.assertEqual(len(self.entries(outcome=OUTCOME_REFUSED)), 1)

    def test_detail_round_trips_as_structured_data(self):
        activity_log.record('backup.bulk_delete', 'Deleted 3 backup version(s)',
                            detail={'deleted_count': 3, 'reclaimed_bytes': 1024})

        self.assertEqual(self.only()['detail'], {'deleted_count': 3, 'reclaimed_bytes': 1024})

    def test_a_broken_store_does_not_break_the_action(self):
        class Exploding:
            def record(self, **_):
                raise RuntimeError('database is gone')

        activity_log.set_store(Exploding())
        # The point: this returns rather than raising into the caller's work.
        activity_log.record('backup.restore', 'Restored something')

    def test_recording_is_a_no_op_without_a_store(self):
        activity_log.set_store(None)
        activity_log.record('backup.restore', 'Restored something')

    def test_every_recorded_action_is_in_the_vocabulary(self):
        # A typo at a call site should surface as an unknown action rather than
        # quietly creating a category nobody filters by.
        import re
        used = set()
        for path in sorted(REPO_ROOT.rglob('*.py')):
            parts = set(path.parts)
            if parts & {'venv', 'tests', '__pycache__', 'demo', 'node_modules'}:
                continue
            used |= set(re.findall(r"record\w*\(\s*'([a-z_]+\.[a-z_]+)'", path.read_text()))

        self.assertTrue(used, 'no recorded actions found at all')
        self.assertEqual(sorted(used - set(ACTIONS)), [], 'actions used but never declared')

    def test_reads_are_not_part_of_the_vocabulary(self):
        # Browsing is nobody's business to answer for, and recording it would
        # bury the actions that matter.
        for action in ACTIONS:
            self.assertFalse(
                action.endswith(('.list', '.view', '.browse', '.read', '.get')),
                f'{action} looks like a read',
            )


class ThreadedWorkTests(ActivityTestCase):
    """
    Work that outlives the request that asked for it.

    A restore is accepted and then run on its own thread. The thread has neither
    the request nor a declaration, so resolving the actor there returns `system`
    — which silently attributed every restore to nobody in particular. The actor
    has to be read while the request is still in scope and carried across.
    """

    def test_resolving_an_actor_inside_a_worker_loses_the_person(self):
        # The behaviour that made this a bug rather than a preference.
        import threading
        from flask import Flask, g

        app = Flask(__name__)
        seen = {}

        with app.test_request_context('/'):
            g.current_actor = admin_actor('alice', 1)
            self.assertEqual(current_actor().name, 'alice')

            thread = threading.Thread(target=lambda: seen.update(actor=current_actor()))
            thread.start()
            thread.join()

        self.assertEqual(seen['actor'].kind, ACTOR_SYSTEM)

    def test_an_actor_captured_in_the_request_survives_into_the_worker(self):
        import threading
        from flask import Flask, g

        app = Flask(__name__)

        with app.test_request_context('/'):
            g.current_actor = admin_actor('alice', 1)
            captured = current_actor()          # read while the request is live

        def worker():
            activity_log.record('backup.restore', 'Restored a backup',
                                target_type='backup_capture', target_id='cap_1',
                                actor=captured)

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()

        entry = self.only()
        self.assertEqual(entry['actor_kind'], ACTOR_ADMIN)
        self.assertEqual(entry['actor_name'], 'alice')
        self.assertEqual(entry['actor_account_id'], 1)


class TransferOwnershipTests(ActivityTestCase):
    def make(self, transfer_id, **extra):
        data = {
            'transfer_id': transfer_id, 'media_type': 'tvshows',
            'folder_name': 'Example Show', 'season_name': 'Season 1',
            'source_path': '/src', 'dest_path': '/dst', 'operation_type': 'folder',
        }
        data.update(extra)
        self.transfers.create(data)
        return self.transfers.get(transfer_id)

    def test_a_run_started_by_automation_says_so(self):
        with acting_as(AUTO_SYNC_SCHEDULER):
            row = self.make('transfer_auto')

        self.assertEqual(row['started_by_kind'], ACTOR_AUTOMATED)
        self.assertEqual(row['started_by_name'], 'auto-sync')
        self.assertIsNone(row['started_by_account_id'])

    def test_a_run_can_name_its_starter_explicitly(self):
        row = self.make('transfer_person', started_by=admin_actor('alice', 1))

        self.assertEqual(row['started_by_kind'], ACTOR_ADMIN)
        self.assertEqual(row['started_by_name'], 'alice')
        self.assertEqual(row['started_by_account_id'], 1)

    def test_an_unattributed_run_is_system_rather_than_blank(self):
        # Blank would read as "nobody"; system reads as "nobody was identified".
        row = self.make('transfer_orphan')

        self.assertEqual(row['started_by_kind'], ACTOR_SYSTEM)
        self.assertIsNotNone(row['started_by_name'])

    def test_ownership_comes_back_in_listings(self):
        with acting_as(AUTO_SYNC_SCHEDULER):
            self.make('transfer_listed')

        listed = [t for t in self.transfers.get_all(include_logs=False)
                  if t['transfer_id'] == 'transfer_listed']
        self.assertEqual(listed[0]['started_by_name'], 'auto-sync')


class QueryTests(ActivityTestCase):
    def setUp(self):
        super().setUp()
        activity_log.record('backup.restore', 'Restored a backup',
                            target_type='backup_capture', target_id='cap_1',
                            actor=admin_actor('alice', 1))
        activity_log.record('backup.delete', 'Deleted a backup',
                            target_type='backup_capture', target_id='cap_1',
                            actor=admin_actor('bob', 2))
        with acting_as(AUTO_RETENTION):
            activity_log.record('backup.retention_apply', 'Retention removed 2 old version(s)',
                                target_type='backup_capture')
        with acting_as(AUTO_SYNC_SCHEDULER):
            activity_log.record('transfer.start', 'Started a scheduled sync',
                                target_type='transfer', target_id='transfer_1')

    def test_filter_by_person(self):
        self.assertEqual(len(self.entries(actor_name='alice')), 1)
        self.assertEqual(len(self.entries(actor_account_id=2)), 1)

    def test_filter_by_kind_separates_people_from_automation(self):
        self.assertEqual(len(self.entries(actor_kind=ACTOR_ADMIN)), 2)
        self.assertEqual(len(self.entries(actor_kind=ACTOR_AUTOMATED)), 2)

    def test_filter_by_action_family(self):
        self.assertEqual(len(self.entries(action_group='backup')), 3)
        self.assertEqual(len(self.entries(action='backup.restore')), 1)

    def test_filter_by_what_was_acted_on(self):
        self.assertEqual(len(self.entries(target_type='backup_capture', target_id='cap_1')), 2)

    def test_search_matches_the_summary(self):
        self.assertEqual(len(self.entries(search='Retention')), 1)

    def test_one_thing_reads_as_a_story_in_order(self):
        story = self.activity.for_target('backup_capture', 'cap_1')
        self.assertEqual([e['action'] for e in story], ['backup.restore', 'backup.delete'])

    def test_newest_first_with_a_total_behind_it(self):
        page = self.activity.query(limit=2)
        self.assertEqual(len(page['entries']), 2)
        self.assertEqual(page['total'], 4)

    def test_actors_seen_lists_people_and_automation(self):
        seen = {(a['actor_kind'], a['actor_name']) for a in self.activity.actors_seen()}
        self.assertIn((ACTOR_ADMIN, 'alice'), seen)
        self.assertIn((ACTOR_AUTOMATED, 'retention'), seen)


class RenameTests(ActivityTestCase):
    def test_a_rename_does_not_rewrite_what_was_already_recorded(self):
        # The name is a snapshot; the account id is what still resolves to the
        # person after they are renamed.
        activity_log.record('backup.delete', 'Deleted a backup',
                            actor=admin_actor('priya', 7))

        entry = self.only()
        self.assertEqual(entry['actor_name'], 'priya')
        self.assertEqual(entry['actor_account_id'], 7)

        # Later, under a new name — the old entry is untouched and both are
        # still traceable to account 7.
        activity_log.record('backup.restore', 'Restored a backup',
                            actor=admin_actor('priya.n', 7))

        by_account = self.entries(actor_account_id=7)
        self.assertEqual(len(by_account), 2)
        self.assertEqual({e['actor_name'] for e in by_account}, {'priya', 'priya.n'})


if __name__ == '__main__':
    unittest.main()
