"""Real disk boundaries must not own exit status or cancellation."""
from pathlib import Path
import json
import tempfile
import threading
import unittest
from unittest.mock import patch

from companion import session_exit
from companion.service import Session


class ExitPersistenceLivenessTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='denghuo-exit-liveness-')
        self.directory = Path(self.temporary.name)
        self.empty_saves = self.directory / 'empty-synthetic-saves'
        self.empty_saves.mkdir()
        (self.directory / 'settings.json').write_text(
            json.dumps({'save_root': str(self.empty_saves), 'slot': 'auto'}), encoding='utf-8')
        self.sessions, self.releases, self.threads = [], [], []
        self.session = self.new_session()
        self.coordinator = self.session.exit_coordinator

    def tearDown(self):
        for release in self.releases:
            release.set()
        for thread in self.threads:
            thread.join(5)
            self.assertFalse(thread.is_alive())
        for session in self.sessions:
            self.assertTrue(session.exit_coordinator.flush_checkpoints(5))
            session.stop.set()
        self.temporary.cleanup()

    def new_session(self):
        session = Session(self.directory / 'settings.json')
        self.sessions.append(session)
        return session

    def report(self, revision=1, raw='unfinished raw', dirty=True, identity='web-aaaaaaaa'):
        return self.session.report_exit_surface(identity, revision, dirty,
            draft={'raw': raw}, kind='web', label='synthetic editing surface')

    def flush(self):
        self.assertTrue(self.coordinator.flush_checkpoints(5))

    def run_async(self, call):
        done, result = threading.Event(), {}
        def run():
            try:
                result['value'] = call()
            except Exception as exc:
                result['error'] = exc
            finally:
                done.set()
        thread = threading.Thread(target=run, daemon=True)
        self.threads.append(thread)
        thread.start()
        return done, result

    def promptly(self, call):
        done, result = self.run_async(call)
        self.assertTrue(done.wait(1), 'in-memory operation waited for held disk I/O')
        if 'error' in result:
            raise result['error']
        return result['value']

    def hold_atomic(self, directory):
        entered, release = threading.Event(), threading.Event()
        self.releases.append(release)
        original = session_exit.atomic_json
        def held(path, value):
            if Path(path).parent == directory:
                entered.set()
                if not release.wait(8):
                    raise AssertionError('disk hold was not released')
            return original(path, value)
        return entered, release, patch('companion.session_exit.atomic_json', side_effect=held)

    def hold_clear(self):
        entered, release = threading.Event(), threading.Event()
        self.releases.append(release)
        original = Path.unlink
        directory = self.session.exit_recovery.directory
        def held(path, *args, **kwargs):
            if path.parent == directory and path.suffix == '.json':
                entered.set()
                if not release.wait(8):
                    raise AssertionError('unlink hold was not released')
            return original(path, *args, **kwargs)
        return entered, release, patch.object(Path, 'unlink', held)

    def test_automatic_checkpoint_does_not_block_snapshot_start_cancel_or_shutdown(self):
        entered, release, held = self.hold_atomic(self.session.exit_recovery.directory)
        with held:
            state = self.promptly(self.report)
            self.assertTrue(entered.wait(2))
            own, = state['participants']
            self.assertTrue(own['recovery_pending'])
            self.assertFalse(own['recovery_saved'])
            self.assertFalse(own['has_recovery_draft'])
            self.promptly(self.session.snapshot)
            request = self.promptly(lambda: self.session.request_exit('web-aaaaaaaa'))
            cancelled = self.promptly(lambda: self.session.acknowledge_exit(
                request['id'], 'web-aaaaaaaa', 'cancel', 1))
            self.assertEqual(cancelled['phase'], 'cancelled')
            # The final backup owns its own deadline and does not join draft I/O.
            result = self.promptly(self.session.prepare_shutdown)
            self.assertEqual(result['state'], 'no-save')
            self.assertFalse(release.is_set())
            release.set()
            self.flush()

    def test_discard_wait_allows_cancel_and_requeues_same_revision_dirty_after_unlink(self):
        self.report(); self.flush()
        self.report(identity='web-bbbbbbbb'); self.flush()
        request = self.session.request_exit('web-aaaaaaaa')
        entered, release, held = self.hold_clear()
        with held:
            done, result = self.run_async(lambda: self.session.acknowledge_exit(
                request['id'], 'web-aaaaaaaa', 'discard', 1))
            self.assertTrue(entered.wait(2))
            self.promptly(self.session.snapshot)
            cancelled = self.promptly(lambda: self.session.acknowledge_exit(
                request['id'], 'web-bbbbbbbb', 'cancel', 2))
            self.assertEqual(cancelled['phase'], 'cancelled')
            own = next(row for row in cancelled['participants'] if row['surface_id'] == 'web-aaaaaaaa')
            self.assertTrue(own['dirty']); self.assertTrue(own['recovery_pending'])
            release.set()
            self.assertTrue(done.wait(3)); self.flush()
        self.assertIsInstance(result.get('error'), ValueError)
        self.assertEqual(self.coordinator.status()['phase'], 'cancelled')
        self.assertTrue(all(row['ack'] is None for row in self.coordinator.status()['participants']))
        identity = self.session.exit_recovery.identity('web-aaaaaaaa')
        self.assertEqual(self.session.exit_recovery.load(identity)['draft'], {'raw': 'unfinished raw'})
        self.assertTrue(self.coordinator.status()['participants'][0]['recovery_saved'])

    def test_cancel_does_not_wait_for_local_revision_to_match_a_pending_report(self):
        entered, release, held = self.hold_atomic(self.session.exit_recovery.directory)
        with held:
            self.report(); self.assertTrue(entered.wait(2))
            for local_revision in (0, 2):
                request = self.session.request_exit('web-aaaaaaaa')
                cancelled = self.promptly(lambda: self.session.acknowledge_exit(
                    request['id'], 'web-aaaaaaaa', 'cancel', local_revision))
                self.assertEqual(cancelled['phase'], 'cancelled')
                own, = cancelled['participants']
                self.assertEqual(own['revision'], 1)
                self.assertTrue(own['dirty']); self.assertIsNone(own['ack'])
            release.set(); self.flush()
        identity = self.session.exit_recovery.identity('web-aaaaaaaa')
        self.assertEqual(self.session.exit_recovery.load(identity)['draft'], {'raw': 'unfinished raw'})

    def test_unchanged_heartbeat_during_clear_does_not_invalidate_decision_or_resurrect(self):
        self.report(); self.flush()
        self.report(identity='web-bbbbbbbb'); self.flush()
        request = self.session.request_exit('web-aaaaaaaa')
        entered, release, held = self.hold_clear()
        with held:
            done, result = self.run_async(lambda: self.session.acknowledge_exit(
                request['id'], 'web-aaaaaaaa', 'discard', 1))
            self.assertTrue(entered.wait(2))
            for _ in range(50):
                self.report()
            with self.coordinator.lock:
                self.assertEqual(len(self.coordinator._persistence), 0)
            release.set()
            self.assertTrue(done.wait(3)); self.flush()
        self.assertNotIn('error', result)
        self.assertEqual(self.coordinator.status()['participants'][0]['ack'], 'discard')
        self.assertFalse(self.session.exit_recovery.contains(self.session.exit_recovery.identity('web-aaaaaaaa')))

    def test_cancellation_restoration_keeps_a_slot_despite_clean_window_churn(self):
        self.report(); self.flush()
        request = self.session.request_exit('web-aaaaaaaa')
        entered, release, held = self.hold_clear()
        with held:
            done, result = self.run_async(lambda: self.session.acknowledge_exit(
                request['id'], 'web-aaaaaaaa', 'discard', 1))
            self.assertTrue(entered.wait(2))
            for number in range(100):
                identity = 'web-' + format(number, '08x')
                self.report(dirty=False, identity=identity)
                self.session.unregister_exit_surface(identity, 1, False)
            cancelled = self.promptly(lambda: self.session.acknowledge_exit(
                request['id'], 'web-aaaaaaaa', 'cancel', 1))
            own, = cancelled['participants']
            self.assertTrue(own['recovery_pending'])
            self.assertEqual(own['recovery_error'], '')
            with self.coordinator.lock:
                self.assertLessEqual(len(self.coordinator._persistence), 32)
            release.set(); self.assertTrue(done.wait(3)); self.flush()
        self.assertIsInstance(result.get('error'), ValueError)
        identity = self.session.exit_recovery.identity('web-aaaaaaaa')
        self.assertEqual(self.session.exit_recovery.load(identity)['draft'], {'raw': 'unfinished raw'})

    def test_new_raw_report_during_clear_rejects_old_ack_and_preserves_new_revision(self):
        self.report(); self.flush()
        request = self.session.request_exit('web-aaaaaaaa')
        entered, release, held = self.hold_clear()
        with held:
            done, result = self.run_async(lambda: self.session.acknowledge_exit(
                request['id'], 'web-aaaaaaaa', 'discard', 1))
            self.assertTrue(entered.wait(2))
            self.promptly(lambda: self.report(2, 'new raw'))
            release.set()
            self.assertTrue(done.wait(3)); self.flush()
        self.assertIsInstance(result.get('error'), ValueError)
        self.assertIsNone(self.coordinator.status()['participants'][0]['ack'])
        identity = self.session.exit_recovery.identity('web-aaaaaaaa')
        self.assertEqual(self.session.exit_recovery.load(identity)['draft'], {'raw': 'new raw'})

    def test_late_offline_copy_is_retained_and_cannot_ack_restarted_request(self):
        self.report(); self.flush()
        self.session.unregister_exit_surface('web-aaaaaaaa', 1, True)
        request = self.session.request_exit('native')
        entered, release, held = self.hold_atomic(self.session.exit_drafts.directory)
        with held:
            done, result = self.run_async(lambda: self.coordinator.resolve_offline(
                request['id'], 'web-aaaaaaaa', 'save', 1))
            self.assertTrue(entered.wait(2))
            self.promptly(self.session.snapshot)
            self.promptly(lambda: self.session.acknowledge_exit(request['id'], 'web-aaaaaaaa', 'cancel', 1))
            second = self.promptly(lambda: self.session.request_exit('native'))
            self.promptly(lambda: self.report(2, 'edited while copy pending'))
            release.set()
            self.assertTrue(done.wait(3)); self.flush()
        self.assertIsInstance(result.get('error'), ValueError)
        saved, = self.session.exit_drafts.list()
        self.assertEqual(self.session.exit_drafts.load(saved['id'])['draft'], {'raw': 'unfinished raw'})
        state = self.coordinator.status()
        self.assertEqual(state['id'], second['id']); self.assertEqual(state['phase'], 'confirming')
        self.assertIsNone(state['participants'][0]['ack'])
        identity = self.session.exit_recovery.identity('web-aaaaaaaa')
        self.assertEqual(self.session.exit_recovery.load(identity)['draft'], {'raw': 'edited while copy pending'})

    def test_coalesced_reports_bound_jobs_and_capture_immutable_latest_input(self):
        entered, release, held = self.hold_atomic(self.session.exit_recovery.directory)
        with held:
            self.report(); self.assertTrue(entered.wait(2))
            original_worker = self.coordinator._persistence_worker
            for revision in range(2, 202):
                draft = {'raw': str(revision)}
                self.coordinator.report('web-aaaaaaaa', revision, True, draft=draft)
                draft['raw'] = 'mutated caller object'
            with self.coordinator.lock:
                self.assertIs(self.coordinator._persistence_worker, original_worker)
                self.assertEqual(len(self.coordinator._persistence), 1)
                self.assertEqual(self.coordinator._persistence[0]['draft'], {'raw': '201'})
            release.set(); self.flush()
        identity = self.session.exit_recovery.identity('web-aaaaaaaa')
        self.assertEqual(self.session.exit_recovery.load(identity)['draft'], {'raw': '201'})

    def test_clean_register_unregister_churn_has_bounded_queue_and_truthful_capacity(self):
        entered, release, held = self.hold_atomic(self.session.exit_recovery.directory)
        failures = []
        with held:
            self.report(); self.assertTrue(entered.wait(2))
            for number in range(100):
                identity = 'web-' + format(number, '08x')
                state = self.report(dirty=False, identity=identity)
                own = next(row for row in state['participants'] if row['surface_id'] == identity)
                if own['recovery_error']:
                    failures.append(own)
                self.session.unregister_exit_surface(identity, 1, False)
            with self.coordinator.lock:
                self.assertLessEqual(len(self.coordinator._persistence), 32)
            self.assertTrue(failures)
            self.assertTrue(all(not row['recovery_saved'] and not row['recovery_pending'] for row in failures))
            self.assertIn('队列已满', failures[0]['recovery_error'])
            release.set(); self.flush()

    def test_late_automatic_write_is_followed_by_clear_and_never_overwrites_new_session(self):
        other = self.new_session()
        entered, release, held = self.hold_atomic(self.session.exit_recovery.directory)
        with held:
            self.report(); self.assertTrue(entered.wait(2))
            self.promptly(lambda: self.report(2, dirty=False))
            self.session.unregister_exit_surface('web-aaaaaaaa', 2, False)
            other.report_exit_surface('web-aaaaaaaa', 1, True, draft={'raw': 'other session'}, kind='web')
            release.set(); self.flush()
            self.assertTrue(other.exit_coordinator.flush_checkpoints(5))
            self.assertTrue(other.exit_status()['participants'][0]['recovery_saved'], other.exit_status())
        rows = self.session.list_exit_drafts()
        self.assertEqual(len(rows), 1)
        self.assertEqual(other.load_exit_draft(rows[0]['id'])['draft'], {'raw': 'other session'})
        self.assertEqual(self.coordinator.status()['participants'], [])

    def test_failed_old_write_cannot_replace_new_revision_pending_or_success_state(self):
        entered, release = threading.Event(), threading.Event()
        newer_entered, newer_release = threading.Event(), threading.Event()
        self.releases.extend((release, newer_release))
        original = session_exit.atomic_json
        def held(path, value):
            if value['revision'] == 1:
                entered.set()
                if not release.wait(8):
                    raise AssertionError('first hold not released')
                raise OSError('synthetic old write failure')
            newer_entered.set()
            if not newer_release.wait(8):
                raise AssertionError('newer hold not released')
            return original(path, value)
        with patch('companion.session_exit.atomic_json', side_effect=held):
            self.report(); self.assertTrue(entered.wait(2))
            self.report(2, 'latest raw')
            release.set(); self.assertTrue(newer_entered.wait(2))
            own, = self.coordinator.status()['participants']
            self.assertTrue(own['recovery_pending'])
            self.assertFalse(own['recovery_saved'])
            self.assertEqual(own['recovery_error'], '')
            newer_release.set(); self.flush()
        own, = self.coordinator.status()['participants']
        self.assertTrue(own['recovery_saved']); self.assertFalse(own['recovery_pending'])
        self.assertEqual(own['recovery_error'], '')

    def test_reregistered_surface_cannot_receive_old_generation_completion(self):
        entered, release = threading.Event(), threading.Event()
        newer_entered, newer_release = threading.Event(), threading.Event()
        self.releases.extend((release, newer_release))
        original = session_exit.atomic_json
        def held(path, value):
            current_entered, current_release = ((entered, release) if value['revision'] == 1
                                                else (newer_entered, newer_release))
            current_entered.set()
            if not current_release.wait(8):
                raise AssertionError('generation hold not released')
            return original(path, value)
        with patch('companion.session_exit.atomic_json', side_effect=held):
            self.report(); self.assertTrue(entered.wait(2))
            old_surface = self.coordinator.surfaces['web-aaaaaaaa']
            self.session.unregister_exit_surface('web-aaaaaaaa', 2, False)
            self.report(2, 'new generation raw')
            self.assertIsNot(self.coordinator.surfaces['web-aaaaaaaa'], old_surface)
            release.set(); self.assertTrue(newer_entered.wait(2))
            own, = self.coordinator.status()['participants']
            self.assertTrue(own['recovery_pending']); self.assertFalse(own['recovery_saved'])
            newer_release.set(); self.flush()
        identity = self.session.exit_recovery.identity('web-aaaaaaaa')
        self.assertEqual(self.session.exit_recovery.load(identity)['draft'], {'raw': 'new generation raw'})


if __name__ == '__main__':
    unittest.main()
