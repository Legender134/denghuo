"""Preference and migration I/O must leave published status and exit responsive."""
import unittest
from unittest.mock import patch

import test_service_liveness as fixtures


class WorkspaceLivenessTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.ServiceLivenessTests.setUpClass.__func__)
    setUp = fixtures.ServiceLivenessTests.setUp
    release_and_join = fixtures.ServiceLivenessTests.release_and_join
    background = fixtures.ServiceLivenessTests.background
    gate = fixtures.ServiceLivenessTests.gate
    assert_snapshot_returns = fixtures.ServiceLivenessTests.assert_snapshot_returns

    def test_cold_preferences_disk_read_does_not_block_status(self):
        from companion.play_state import PlayPreferences
        entered, release, wait = self.gate()
        original = PlayPreferences.__init__
        def delayed(instance, *args, **kwargs):
            wait()
            original(instance, *args, **kwargs)
        with patch.object(PlayPreferences, '__init__', delayed):
            done, _, errors = self.background(self.session.play_settings, 'cold-preferences')
            self.assertTrue(entered.wait(.5))
            self.assert_snapshot_returns()
            release.set()
            self.assertTrue(done.wait(2))
            self.assertEqual(errors, [])

    def test_preference_write_does_not_own_session_lock(self):
        prefs = self.session.play_preferences
        entered, release, wait = self.gate()
        original = prefs.update
        def delayed(*args, **kwargs):
            wait()
            return original(*args, **kwargs)
        with patch.object(prefs, 'update', delayed):
            done, _, errors = self.background(lambda: self.session.update_play_settings(
                {'settings': {'offset_x': 77}, 'revision': prefs.generation}), 'preference-write')
            self.assertTrue(entered.wait(.5))
            self.assert_snapshot_returns()
            release.set()
            self.assertTrue(done.wait(2))
            self.assertEqual(errors, [])
        self.assertEqual(prefs.values['offset_x'], 77)

    def test_migration_read_can_wait_while_exit_still_respects_deadline(self):
        entered, release, wait = self.gate()
        original = self.session.backups.snapshot
        def delayed(*args, **kwargs):
            wait()
            return original(*args, **kwargs)
        with patch.object(self.session.backups, 'snapshot', delayed):
            done, _, errors = self.background(self.session.migration_status, 'migration-read')
            self.assertTrue(entered.wait(.5))
            state = self.assert_snapshot_returns()
            self.assertTrue(state['backup_health']['pending'])
            exited, results, failures = self.background(lambda: self.session.prepare_shutdown(.05), 'bounded-exit')
            self.assertTrue(exited.wait(.5))
            self.assertEqual(failures, [])
            self.assertEqual(results[0]['state'], 'timeout')
            release.set()
            self.assertTrue(done.wait(2))
            self.assertEqual(errors, [])

    def test_partial_migration_lock_failure_releases_previous_locks(self):
        prefs = self.session.play_preferences
        knowledge = self.session.knowledge
        class UnavailableLock:
            def __enter__(self):
                raise ValueError('preference access failed')
            def __exit__(self, *_):
                return False
        with patch.object(prefs, 'lock', UnavailableLock()), self.assertRaisesRegex(ValueError, 'access failed'):
            self.session.migration_status()
        def read():
            with knowledge.lock:
                return knowledge.status()
        done, _, errors = self.background(read, 'knowledge-after-migration-error')
        self.assertTrue(done.wait(.5), 'failed migration retained a prior category lock')
        self.assertEqual(errors, [])
