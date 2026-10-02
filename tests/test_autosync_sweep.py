#!/usr/bin/env python3
"""
The library sweep — the safety net under the webhook.

What it must get right, and what each test is guarding:

  * it acts on exactly two findings, `missing` and `incomplete`, and leaves
    everything else alone;
  * it builds the **source** path from the service's own folder name, which is
    not the folder name on this side. A show filed here as "Alpha Bravo" is
    "ALPHA BRAVO (2020)" there, and deriving one from the other pointed a
    real sync at a path that did not exist;
  * it refuses a path the service supplies that sits outside a configured root;
  * it counts its budget in transfers, not titles — one incomplete series can
    be missing sixteen seasons;
  * it never raises, and it is never gated on test mode.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from models.database import DatabaseManager
from services.autosync_sweep import MAX_TRANSFERS_PER_RUN, AutoSyncSweep


class _Config:
    def __init__(self, values):
        self.values = values

    def get(self, key, default=''):
        return self.values.get(key, default)


ROOTS = _Config({
    'MOVIE_PATH': '/remote/Movies', 'MOVIE_DEST_PATH': '/local/movies',
    'TVSHOW_PATH': '/remote/TV Shows', 'TVSHOW_DEST_PATH': '/local/tv_shows',
    'ANIME_PATH': '/remote/Anime', 'ANIME_DEST_PATH': '/local/anime',
})


class _Adapter:
    def __init__(self, enabled=True, auto_sync=True, interval=15):
        self._enabled, self._auto, self._interval = enabled, auto_sync, interval

    def sweep_enabled(self):
        return self._enabled

    def sweep_auto_sync(self):
        return self._auto

    def sweep_interval_minutes(self):
        return self._interval


class _Index:
    """Stands in for MediaIndex, returning a library view we control."""

    def __init__(self, view, adapter=None):
        self.view = view
        self.adapter = adapter if adapter is not None else _Adapter()

    def _adapter(self, source):
        return self.adapter if source == 'sonarr' else None

    def library_view(self, source, refresh=False):
        return self.view


class _Coordinator:
    def __init__(self, succeed=True):
        self.calls = []
        self.succeed = succeed

    def start_transfer(self, transfer_id, source_path, dest_path, operation_type,
                       media_type, folder_name, season_name):
        self.calls.append({'source': source_path, 'dest': dest_path,
                           'media_type': media_type, 'folder': folder_name,
                           'season': season_name})
        return self.succeed, 'started' if self.succeed else 'refused'


def item(**kw):
    base = {
        'title': 'Example Show', 'sync_state': 'never', 'service_has_files': True,
        'service_episode_file_count': 10, 'media_type': 'anime',
        'local_folder': 'Example Show', 'service_path': '/remote/Anime/EXAMPLE SHOW (2020)',
        'seasons': [],
    }
    base.update(kw)
    return base


def view(items, counts=None, live=True):
    return {'live': live, 'total': len(items), 'items': items,
            'counts': counts or {}, 'source': 'sonarr'}


def season(number, there=10, here=False):
    return {'season_number': number, 'specials': number == 0,
            'episode_file_count': there, 'files_here': 10 if here else 0,
            'synced_here': here, 'counts_towards_state': bool(there and number > 0)}


class SweepDecisionTests(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = DatabaseManager(os.path.join(tmp.name, 'sweep.db'))

    def sweep(self, items, adapter=None, coordinator=None, counts=None):
        return AutoSyncSweep(
            self.db, None, _Index(view(items, counts), adapter),
            coordinator=coordinator or _Coordinator(), config=ROOTS)

    # -- what it acts on -----------------------------------------------------

    def test_a_title_missing_here_is_fetched(self):
        coordinator = _Coordinator()
        result = self.sweep([item()], coordinator=coordinator)._sweep_source('sonarr')
        self.assertEqual(len(coordinator.calls), 1)
        self.assertEqual(result['decisions'][0]['finding'], 'missing')

    def test_only_the_missing_seasons_are_fetched(self):
        coordinator = _Coordinator()
        rows = [item(sync_state='partial',
                     seasons=[season(1, here=True), season(2), season(3)])]
        self.sweep(rows, coordinator=coordinator)._sweep_source('sonarr')
        self.assertEqual([c['season'] for c in coordinator.calls],
                         ['Season 02', 'Season 03'])

    def test_nothing_is_fetched_for_states_that_are_not_gaps(self):
        for state in ('synced', 'no_files', 'orphan', 'unknown'):
            with self.subTest(state=state):
                coordinator = _Coordinator()
                self.sweep([item(sync_state=state)],
                           coordinator=coordinator)._sweep_source('sonarr')
                self.assertEqual(coordinator.calls, [])

    def test_a_title_the_service_holds_no_files_for_is_left_alone(self):
        coordinator = _Coordinator()
        self.sweep([item(service_has_files=False)],
                   coordinator=coordinator)._sweep_source('sonarr')
        self.assertEqual(coordinator.calls, [])

    # -- the paths -----------------------------------------------------------

    def test_the_source_uses_the_services_own_folder_name(self):
        """The bug this exists to prevent, caught against the real library.

        The remote folder was "ALPHA BRAVO (2020)" while the local one was
        "Alpha Bravo". Building the source from the local name aimed the sync
        at a directory that did not exist.
        """
        coordinator = _Coordinator()
        self.sweep([item(local_folder='Alpha Bravo',
                         service_path='/remote/Anime/ALPHA BRAVO (2020)')],
                   coordinator=coordinator)._sweep_source('sonarr')
        call = coordinator.calls[0]
        self.assertEqual(call['source'], '/remote/Anime/ALPHA BRAVO (2020)')
        self.assertEqual(call['dest'], '/local/anime/Alpha Bravo')

    def test_a_path_outside_every_configured_root_is_refused(self):
        """An address the service supplied is not a reason to read anywhere."""
        coordinator = _Coordinator()
        result = self.sweep([item(media_type='', local_folder='',
                                  service_path='/somewhere/else/A Show')],
                            coordinator=coordinator)._sweep_source('sonarr')
        self.assertEqual(coordinator.calls, [])
        self.assertEqual(result['decisions'][0]['action'], 'skipped')

    def test_the_library_is_read_from_the_service_path_when_unknown_here(self):
        """A title never synced has no local folder to learn a library from."""
        coordinator = _Coordinator()
        self.sweep([item(media_type='', local_folder='',
                         service_path='/remote/TV Shows/A Show (2024)')],
                   coordinator=coordinator)._sweep_source('sonarr')
        self.assertEqual(coordinator.calls[0]['dest'], '/local/tv_shows/A Show (2024)')

    # -- restraint -----------------------------------------------------------

    def test_it_only_reports_when_syncing_is_switched_off(self):
        coordinator = _Coordinator()
        result = self.sweep([item()], adapter=_Adapter(auto_sync=False),
                            coordinator=coordinator)._sweep_source('sonarr')
        self.assertEqual(coordinator.calls, [])
        self.assertEqual(result['decisions'][0]['action'], 'reported')

    def test_the_budget_is_counted_in_transfers_not_titles(self):
        """One incomplete series can be missing sixteen seasons."""
        coordinator = _Coordinator()
        rows = [item(sync_state='partial',
                     seasons=[season(n) for n in range(1, 17)])]
        self.sweep(rows, coordinator=coordinator)._sweep_source('sonarr')
        self.assertEqual(len(coordinator.calls), MAX_TRANSFERS_PER_RUN)

    def test_what_was_held_back_is_said_out_loud(self):
        coordinator = _Coordinator()
        rows = [item(sync_state='partial',
                     seasons=[season(n) for n in range(1, 17)])]
        result = self.sweep(rows, coordinator=coordinator)._sweep_source('sonarr')
        self.assertIn('held back', result['decisions'][0]['detail'])

    def test_a_sweep_of_a_service_that_did_not_answer_changes_nothing(self):
        coordinator = _Coordinator()
        sweep = AutoSyncSweep(self.db, None,
                              _Index(view([item()], live=False)),
                              coordinator=coordinator, config=ROOTS)
        result = sweep._sweep_source('sonarr')
        self.assertFalse(result['ok'])
        self.assertEqual(coordinator.calls, [])

    def test_a_connector_with_sweeping_off_is_not_swept(self):
        coordinator = _Coordinator()
        result = self.sweep([item()], adapter=_Adapter(enabled=False),
                            coordinator=coordinator)._sweep_source('sonarr')
        self.assertFalse(result['ok'])
        self.assertEqual(coordinator.calls, [])

    # -- it must not fall over -----------------------------------------------

    def test_a_coordinator_that_raises_does_not_take_the_sweep_down(self):
        class Exploding:
            def start_transfer(self, *a, **k):
                raise RuntimeError('boom')

        result = self.sweep([item()], coordinator=Exploding())._sweep_source('sonarr')
        self.assertEqual(result['decisions'][0]['action'], 'failed')

    def test_run_once_never_raises(self):
        class Exploding:
            def _adapter(self, source):
                raise RuntimeError('boom')

        sweep = AutoSyncSweep(self.db, None, Exploding(), config=ROOTS)
        self.assertIsInstance(sweep.run_once(sources=['sonarr']), dict)

    def test_test_mode_does_not_stop_it(self):
        """Reads and decisions are exactly what is worth exercising in test mode.

        The transfer it starts inherits `--dry-run` from `TEST_MODE` like any
        other, so the decision is real and the write is not.
        """
        coordinator = _Coordinator()
        with patch.dict(os.environ, {'TEST_MODE': '1'}):
            self.sweep([item()], coordinator=coordinator)._sweep_source('sonarr')
        self.assertEqual(len(coordinator.calls), 1)

    def test_the_sweep_source_is_never_consulted_for_test_mode(self):
        import inspect

        from services import autosync_sweep
        self.assertNotIn('test_mode_enabled', inspect.getsource(autosync_sweep))


class SweepLoggingTests(unittest.TestCase):
    """Every automated action has to be legible to whoever reads it at 3am."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = DatabaseManager(os.path.join(tmp.name, 'sweep_log.db'))

    def test_each_decision_reads_as_a_sentence(self):
        from services.autosync_sweep import SweepDecision
        decision = SweepDecision('sonarr', 'Example Show', 'incomplete',
                                 'season(s) 3 there, not here')
        decision.action = 'queued'
        decision.transfer_ids = ['sweep_1']
        self.assertEqual(decision.line(),
                         'Example Show — season(s) 3 there, not here → 1 sync(s) started')

    def test_a_reported_finding_says_it_did_nothing(self):
        from services.autosync_sweep import SweepDecision
        decision = SweepDecision('sonarr', 'Example Show', 'missing', '10 file(s) there')
        self.assertIn('reported only', decision.line())

    def _recorded(self):
        import activity_log
        from models.activity import Activity

        store = Activity(self.db)
        activity_log.set_store(store)
        self.addCleanup(activity_log.set_store, None)

        AutoSyncSweep(self.db, None, _Index(view([item()])),
                      coordinator=_Coordinator(), config=ROOTS).run_once(sources=['sonarr'])
        return store.query(limit=50)['entries']

    def test_the_run_is_recorded_against_the_sweep_and_not_a_person(self):
        entries = self._recorded()
        actions = {e['action'] for e in entries}
        self.assertIn('sweep.run', actions)
        self.assertIn('sweep.sync_started', actions)
        for entry in entries:
            self.assertEqual(entry['actor_kind'], 'automated')
            self.assertEqual(entry['actor_name'], 'library-sweep',
                             'a sync the sweep started must be tellable apart '
                             'from one a webhook started')

    def test_the_summary_says_what_was_found_and_what_was_done(self):
        run = next(e for e in self._recorded() if e['action'] == 'sweep.run')
        self.assertIn('missing or incomplete', run['summary'])
        self.assertIn('sync(s) started', run['summary'])


if __name__ == '__main__':
    unittest.main()


class OneClickSyncTests(unittest.TestCase):
    """The Sync button: a person names a title, and exactly its gap is fetched.

    Report-first is the default — `sweep_auto_sync` starts off — because a
    library can hold titles that are deliberately not kept here, and a machine
    cannot tell restraint from an oversight. The button is how a person says
    "this one, though".
    """

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = DatabaseManager(os.path.join(tmp.name, 'click.db'))

    def sweep(self, items, coordinator=None, live=True):
        return AutoSyncSweep(
            self.db, None, _Index(view(items, live=live)),
            coordinator=coordinator or _Coordinator(), config=ROOTS)

    def test_reporting_is_the_default(self):
        """An unset toggle must mean watch, not act."""
        from services.connectors.adapters.sonarr import SonarrConnector
        connector = SonarrConnector({'sweep_enabled': 'true'}, lambda name: 'k')
        self.assertFalse(connector.sweep_auto_sync())

    def test_a_click_fetches_every_outstanding_season_with_no_budget(self):
        """The sweep rations itself; a person who named the title did not ask
        for rationing."""
        coordinator = _Coordinator()
        rows = [item(external_id='550', sync_state='partial',
                     seasons=[season(n) for n in range(1, 17)])]
        result = self.sweep(rows, coordinator=coordinator).sync_one('sonarr', '550')
        self.assertTrue(result['success'])
        self.assertEqual(result['transfers_started'], 16)

    def test_a_click_on_a_synced_title_is_refused_with_a_reason(self):
        result = self.sweep([item(external_id='550', sync_state='synced')]) \
            .sync_one('sonarr', '550')
        self.assertFalse(result['success'])
        self.assertIn('already here', result['error'])

    def test_a_click_on_an_unknown_title_says_so(self):
        result = self.sweep([item(external_id='550')]).sync_one('sonarr', '999')
        self.assertFalse(result['success'])
        self.assertIn('No such title', result['error'])

    def test_the_decision_is_derived_fresh_not_trusted_from_the_page(self):
        """A tab open for hours must not fetch what arrived meanwhile."""
        coordinator = _Coordinator()
        # The page believed this was partial; by now everything is here.
        result = self.sweep([item(external_id='550', sync_state='synced')],
                            coordinator=coordinator).sync_one('sonarr', '550')
        self.assertFalse(result['success'])
        self.assertEqual(coordinator.calls, [])

    def test_a_click_and_a_sweep_build_identical_paths(self):
        """One planner serves both, so they cannot drift apart."""
        clicked, swept = _Coordinator(), _Coordinator()
        rows = lambda: [item(external_id='550', sync_state='partial',
                             seasons=[season(3)])]
        self.sweep(rows(), coordinator=clicked).sync_one('sonarr', '550')
        sweep = AutoSyncSweep(self.db, None, _Index(view(rows())),
                              coordinator=swept, config=ROOTS)
        sweep._sweep_source('sonarr')
        self.assertEqual(clicked.calls[0]['source'], swept.calls[0]['source'])
        self.assertEqual(clicked.calls[0]['dest'], swept.calls[0]['dest'])

    def test_a_click_is_recorded_as_a_transfer_start_not_as_the_sweep(self):
        import activity_log
        from models.activity import Activity

        store = Activity(self.db)
        activity_log.set_store(store)
        self.addCleanup(activity_log.set_store, None)

        self.sweep([item(external_id='550')]).sync_one('sonarr', '550')
        entries = store.query(limit=10)['entries']
        actions = {e['action'] for e in entries}
        self.assertIn('transfer.start', actions)
        self.assertNotIn('sweep.sync_started', actions,
                         'a click is a person acting, not the sweep')


class SweepMemoryTests(unittest.TestCase):
    """A sweep that repeats has to remember what it already did.

    Measured before this existed, on a real library left running overnight: the
    same five seasons queued **34 times in eight hours**, with a Discord message
    every round. The gap never closed, so every run re-derived it, re-announced
    it and re-queued it. Nothing was wrong with the finding — only with saying
    and doing it again.
    """

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = DatabaseManager(os.path.join(tmp.name, 'memory.db'))
        self.announced = []
        patcher = patch.object(
            AutoSyncSweep, '_announce',
            lambda _self, source, decisions, may_act, started:
                self.announced.append(list(decisions)))
        self.addCleanup(patcher.stop)
        patcher.start()

    def run_sweep(self, items, auto_sync=False):
        coordinator = _Coordinator()
        sweep = AutoSyncSweep(
            self.db, None, _Index(view(items), _Adapter(auto_sync=auto_sync)),
            coordinator=coordinator, config=ROOTS)
        return coordinator, sweep._sweep_source('sonarr')

    def gap(self):
        return [item(external_id='550', sync_state='partial',
                     seasons=[season(1, here=True), season(2), season(3)])]

    # -- not saying it again -------------------------------------------------

    def test_a_finding_is_announced_once_not_every_sweep(self):
        for _ in range(4):
            self.run_sweep(self.gap())
        self.assertEqual(len(self.announced), 1,
                         'four sweeps of one unchanged gap is one message')

    def test_a_gap_that_comes_back_is_announced_again(self):
        self.run_sweep(self.gap())
        self.run_sweep([item(external_id='550', sync_state='synced')])   # closed
        self.run_sweep(self.gap())                                        # returned
        self.assertEqual(len(self.announced), 2,
                         'a season that came back is news; one that never left is not')

    def test_a_persisting_finding_is_mentioned_again_after_a_day(self):
        self.run_sweep(self.gap())
        with self.db.get_connection() as conn:
            conn.execute("UPDATE sweep_finding SET notified_at = '2020-01-01T00:00:00+00:00'")
            conn.commit()
        self.run_sweep(self.gap())
        self.assertEqual(len(self.announced), 2, 'a daily reminder, not silence')

    # -- not doing it again --------------------------------------------------

    def test_the_same_gap_is_not_re_queued_every_sweep(self):
        first, _ = self.run_sweep(self.gap(), auto_sync=True)
        self.assertEqual(len(first.calls), 2)
        for _ in range(3):
            again, result = self.run_sweep(self.gap(), auto_sync=True)
            self.assertEqual(again.calls, [])
            self.assertEqual(result['decisions'][0]['action'], 'skipped')

    def test_it_gives_up_after_the_attempt_limit_and_says_so(self):
        self.run_sweep(self.gap(), auto_sync=True)
        _, result = self.run_sweep(self.gap(), auto_sync=True)
        self.assertIn('waiting for a person', result['decisions'][0]['detail'])

    def test_only_the_untried_seasons_are_fetched(self):
        """A season already attempted must not be retried alongside a new one."""
        coordinator, _ = self.run_sweep(self.gap(), auto_sync=True)
        self.assertEqual(len(coordinator.calls), 2)

        wider = [item(external_id='550', sync_state='partial',
                      seasons=[season(1, here=True), season(2), season(3), season(4)])]
        coordinator, _ = self.run_sweep(wider, auto_sync=True)
        self.assertEqual([c['season'] for c in coordinator.calls], ['Season 04'])

    # -- closing the loop ----------------------------------------------------

    def test_a_gap_that_closes_is_resolved(self):
        self.run_sweep(self.gap())
        _, result = self.run_sweep([item(external_id='550', sync_state='synced')])
        self.assertEqual(result['decisions'], [])
        with self.db.get_connection() as conn:
            open_rows = conn.execute(
                'SELECT COUNT(*) FROM sweep_finding WHERE resolved_at IS NULL'
            ).fetchone()[0]
        self.assertEqual(open_rows, 0)

    def test_reporting_never_records_an_attempt(self):
        """Watching must not consume the retries that acting is allowed."""
        for _ in range(3):
            self.run_sweep(self.gap(), auto_sync=False)
        with self.db.get_connection() as conn:
            attempts = [r[0] for r in conn.execute(
                'SELECT sync_attempts FROM sweep_finding')]
        self.assertEqual(set(attempts), {0})

        coordinator, _ = self.run_sweep(self.gap(), auto_sync=True)
        self.assertEqual(len(coordinator.calls), 2,
                         'switching syncing on must still be able to act')

    def test_a_finding_is_remembered_per_season_not_per_title(self):
        self.run_sweep(self.gap())
        with self.db.get_connection() as conn:
            rows = conn.execute(
                'SELECT season_number FROM sweep_finding ORDER BY season_number'
            ).fetchall()
        self.assertEqual([r[0] for r in rows], [2, 3])

    def test_a_database_that_will_not_remember_still_reports(self):
        """Repeating a message is a smaller failure than losing one."""
        sweep = AutoSyncSweep(self.db, None, _Index(view(self.gap())),
                              coordinator=_Coordinator(), config=ROOTS)
        with patch.object(AutoSyncSweep, '_remember',
                          side_effect=Exception('no database')):
            with self.assertRaises(Exception):
                sweep._sweep_source('sonarr')
        # run_once absorbs it rather than letting the loop die
        self.assertIsInstance(sweep.run_once(sources=['sonarr']), dict)
