"""Controlled slow I/O must not own the session's published state lock."""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from companion.engine import Catalog
from companion.service import DEFAULTS, Session, SettingsConflict


class ServiceLivenessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='lamp-service-liveness-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / 'saves'
        self.root.mkdir()
        self.config = self.base / 'profile' / 'settings.json'
        self.config.parent.mkdir()
        self.config.write_text(json.dumps({'save_root': str(self.root)}))
        self.session = Session(self.config, self.catalog)
        self.session.refresh()
        self.threads = []
        self.releases = []
        self.addCleanup(self.release_and_join)

    def release_and_join(self):
        self.session.stop.set()
        for event in self.releases:
            event.set()
        for thread in self.threads:
            thread.join(3)
            self.assertFalse(thread.is_alive(), thread.name)
        for name in ('_shutdown_thread', '_shutdown_receipt_thread'):
            thread = getattr(self.session, name, None)
            if thread is not None:
                thread.join(3)
                self.assertFalse(thread.is_alive(), name)

    def background(self, function, name):
        done, result, errors = threading.Event(), [], []
        def run():
            try:
                result.append(function())
            except Exception as exc:
                errors.append(exc)
            finally:
                done.set()
        thread = threading.Thread(target=run, name=name, daemon=True)
        self.threads.append(thread)
        thread.start()
        return done, result, errors

    def gate(self):
        entered, release = threading.Event(), threading.Event()
        self.releases.append(release)
        def wait():
            entered.set()
            if not release.wait(3):
                raise AssertionError('controlled I/O was not released')
        return entered, release, wait

    def assert_snapshot_returns(self):
        done, rows, errors = self.background(self.session.snapshot, 'state-reader')
        self.assertTrue(done.wait(.5), 'status waited for disk I/O')
        self.assertEqual(errors, [])
        return rows[0]

    def write_save(self, hp=20):
        folder = self.root / 'game1'
        folder.mkdir(exist_ok=True)
        game = {'depth': 2, 'branch': 0, 'version': 922, 'generated_levels': [2], 'seed': 9,
                'hero': {'class': 'MAGE', 'HP': hp, 'HT': 40, 'STR': 10, 'lvl': 2,
                         'inventory': [], 'buffs': []}}
        level = {'__className': 'com.shatteredpixel.shatteredpixeldungeon.levels.SewerLevel',
                 'version': 922, 'width': 4, 'height': 4, 'map': [4] * 16,
                 'visited': [False] * 16, 'mapped': [False] * 16}
        (folder / 'game.dat').write_text(json.dumps(game))
        (folder / 'depth2.dat').write_text(json.dumps({'level': level}))

    def test_snapshot_never_calls_health_or_storage(self):
        with patch.object(self.session.backups, 'health_status', side_effect=AssertionError('snapshot touched disk')):
            self.assert_snapshot_returns()

    def test_slow_monitor_keeps_snapshot_and_shutdown_bounded(self):
        entered, release, wait = self.gate()
        actual_tick = self.session.backups.tick
        def tick(*args, **kwargs):
            with self.session.backups.lock:
                wait()
                return actual_tick(*args, **kwargs)
        with patch.object(self.session.backups, 'tick', side_effect=tick):
            monitor, _, errors = self.background(self.session.run, 'save-monitor')
            self.assertTrue(entered.wait(2))
            status = self.assert_snapshot_returns()
            self.assertFalse(status['backup_health']['last_save_protected'])
            finished, rows, failures = self.background(lambda: self.session.prepare_shutdown(.05), 'exit-request')
            self.assertTrue(finished.wait(.5), 'exit budget started after the monitor released its lock')
            self.assertIsNotNone(self.session._shutdown_deadline)
            self.assertFalse(rows[0]['ok'])
            self.assertIn(rows[0]['state'], ('timeout', 'partial'))
            self.assertEqual(failures, [])
            self.session.stop.set()
            release.set()
            self.assertTrue(monitor.wait(2))
            self.assertEqual(errors, [])

    def test_explicit_health_checks_disk_outside_state_lock(self):
        entered, release, wait = self.gate()
        actual = self.session.backups.health_status
        def health(*args):
            wait()
            return actual(*args)
        with patch.object(self.session.backups, 'health_status', side_effect=health):
            done, _, errors = self.background(self.session.backup_health, 'explicit-health')
            self.assertTrue(entered.wait(2))
            self.assert_snapshot_returns()
            release.set()
            self.assertTrue(done.wait(2))
            self.assertEqual(errors, [])

    def test_lazy_disk_reads_do_not_hold_state_lock(self):
        from companion.play_state import PlayPreferences
        from companion.rules import NumericRules
        for attribute, constructor, target in (
                ('play_preferences', PlayPreferences, 'companion.play_state.PlayPreferences'),
                ('rules', NumericRules, 'companion.service.NumericRules')):
            with self.subTest(attribute=attribute):
                entered, release, wait = self.gate()
                def build(*args):
                    wait()
                    return constructor(*args)
                with patch(target, side_effect=build):
                    done, rows, errors = self.background(lambda: getattr(self.session, attribute), 'lazy-disk-read')
                    self.assertTrue(entered.wait(2))
                    self.assert_snapshot_returns()
                    release.set()
                    self.assertTrue(done.wait(2))
                    self.assertEqual(errors, [])
                    self.assertIs(getattr(self.session, attribute), rows[0])

    def test_old_refresh_cannot_publish_after_settings_change(self):
        from companion.service import list_slots
        entered, release, wait = self.gate()
        other = self.base / 'other-saves'
        other.mkdir()
        def slots(root):
            if threading.current_thread().name == 'old-refresh':
                wait()
                return [{'id': 6, 'valid': False, 'modified': 1, 'error': 'old connection'}]
            return list_slots(root)
        with patch('companion.service.list_slots', side_effect=slots):
            done, _, errors = self.background(self.session.refresh, 'old-refresh')
            self.assertTrue(entered.wait(2))
            self.assert_snapshot_returns()
            self.session.update_settings({'save_root': str(other)}, expected_revision=self.session.settings_revision)
            current = self.session.snapshot()
            release.set()
            self.assertTrue(done.wait(2))
            self.assertEqual(errors, [])
            after = self.session.snapshot()
            for key in ('settings', 'settings_revision', 'backup_context', 'data', 'slots', 'error', 'history', 'revision'):
                self.assertEqual(after[key], current[key], key)

    def test_slow_read_or_analysis_does_not_replace_new_manual_state(self):
        from companion.service import analyze, read_slot
        self.write_save()
        self.session.refresh()
        for name, actual in (('read_slot', read_slot), ('analyze', analyze)):
            with self.subTest(operation=name):
                self.session.update_settings({'mode': 'save'})
                self.write_save(18)
                entered, release, wait = self.gate()
                def operation(*args, **kwargs):
                    result = actual(*args, **kwargs)
                    if threading.current_thread().name == 'old-save-read':
                        wait()
                    return result
                with patch('companion.service.' + name, side_effect=operation):
                    done, _, errors = self.background(self.session.refresh, 'old-save-read')
                    self.assertTrue(entered.wait(2))
                    status = self.assert_snapshot_returns()
                    self.assertTrue(status['stale'])
                    self.assertTrue(status['refresh_pending'])
                    self.session.update_manual({'hp': 7, 'ht': 40})
                    current = self.session.snapshot()
                    release.set()
                    self.assertTrue(done.wait(2))
                    self.assertEqual(errors, [])
                    after = self.session.snapshot()
                    self.assertEqual(after['data'], current['data'])
                    self.assertEqual(after['modified'], current['modified'])
                    self.assertEqual(after['settings']['mode'], 'manual')

    def test_same_connection_newer_refresh_wins(self):
        from companion.service import read_slot
        self.write_save()
        self.session.refresh()
        self.write_save(19)
        entered, release, wait = self.gate()
        def read(*args):
            result = read_slot(*args)
            if threading.current_thread().name == 'old-save-read':
                wait()
            return result
        with patch('companion.service.read_slot', side_effect=read):
            done, _, errors = self.background(self.session.refresh, 'old-save-read')
            self.assertTrue(entered.wait(2))
            self.write_save(11)
            self.session.refresh()
            current = self.session.snapshot()
            release.set()
            self.assertTrue(done.wait(2))
            self.assertEqual(errors, [])
            self.assertEqual(self.session.snapshot()['data']['hero']['hp'], 11)
            self.assertEqual(self.session.snapshot()['history'], current['history'])

    def test_waiting_backup_entry_does_not_hold_state_lock(self):
        self.write_save()
        self.session.backup_action({'action': 'capture'})
        row = self.session.backup_status()['history'][0]
        target = self.base / 'backup-destination'
        target.mkdir()
        entries = [lambda: self.session.backup_status(),
                   lambda: self.session.backup_destination_status(),
                   lambda: self.session.backup_action({'action': 'enable', 'enabled': False}),
                   lambda: self.session.backup_workflow('storage', {'context': self.session.backup_context}),
                   lambda: self.session.backup_library_status(expected_context=self.session.backup_context),
                   lambda: self.session.backup_transfer('preview', {**row, 'context': self.session.backup_context}),
                   lambda: self.session.backup_destination_action({'action': 'preview', 'backup_root': str(target),
                       'expected_settings_revision': self.session.settings_revision, 'context': self.session.backup_context})]
        for index, operation in enumerate(entries):
            with self.subTest(entry=index):
                entered, release, wait = self.gate()
                def hold():
                    with self.session.backups.lock:
                        wait()
                held, _, holder_errors = self.background(hold, 'held-manager')
                self.assertTrue(entered.wait(2))
                started = threading.Event()
                def run():
                    started.set()
                    return operation()
                done, _, errors = self.background(run, 'backup-entry')
                self.assertTrue(started.wait(2))
                self.assert_snapshot_returns()
                release.set()
                self.assertTrue(held.wait(2))
                self.assertTrue(done.wait(2))
                self.assertEqual(holder_errors + errors, [])

    def test_destination_copy_blocks_writes_but_not_status_or_exit(self):
        from companion import backup_destination as destination
        self.write_save()
        self.session.backup_action({'action': 'capture'})
        target = self.base / 'destination'
        target.mkdir()
        payload = {'action': 'preview', 'backup_root': str(target),
                   'expected_settings_revision': self.session.settings_revision, 'context': self.session.backup_context}
        preview = self.session.backup_destination_action(payload)
        manager, original = self.session.backups, self.config.read_bytes()
        entered, release, wait = self.gate()
        actual = destination._copy_file
        def copy_file(*args):
            wait()
            return actual(*args)
        with patch('companion.backup_destination._copy_file', side_effect=copy_file):
            applied, _, errors = self.background(lambda: self.session.backup_destination_action({**payload,
                'action': 'apply', 'expected': preview['expected'], 'confirmed': True}), 'destination-copy')
            self.assertTrue(entered.wait(2))
            updated, _, update_errors = self.background(lambda: self.session.update_settings({'always_on_top': True}), 'queued-settings')
            self.assertFalse(updated.wait(.02))
            self.assert_snapshot_returns()
            finished, rows, failures = self.background(lambda: self.session.prepare_shutdown(.05), 'exit-during-copy')
            self.assertTrue(finished.wait(.5))
            self.assertEqual(failures, [])
            self.assertFalse(rows[0]['ok'])
            release.set()
            self.assertTrue(applied.wait(2))
            self.assertTrue(updated.wait(2))
            self.assertEqual(len(errors), 1)
            self.assertEqual(len(update_errors), 1)
            self.assertIs(self.session.backups, manager)
            self.assertEqual(self.config.read_bytes(), original)
            self.assertFalse((target / 'backups').exists())
            self.assertFalse((target / destination.MARKER).exists())

    def test_migration_io_keeps_snapshot_honest_and_exit_bounded(self):
        self.write_save()
        self.session.backup_action({'action': 'capture'})
        self.session.backup_health()
        entered, release, wait = self.gate()
        knowledge = self.session.knowledge
        actual = knowledge.status
        def status():
            wait()
            return actual()
        with patch.object(knowledge, 'status', side_effect=status):
            done, _, errors = self.background(self.session.migration_status, 'migration-read')
            self.assertTrue(entered.wait(2))
            snapshot = self.assert_snapshot_returns()
            self.assertTrue(snapshot['backup_health']['pending'])
            self.assertFalse(snapshot['backup_health']['last_save_protected'])
            finished, rows, failures = self.background(lambda: self.session.prepare_shutdown(.05), 'exit-during-migration')
            self.assertTrue(finished.wait(.5))
            self.assertFalse(rows[0]['ok'])
            self.assertEqual(failures, [])
            release.set()
            self.assertTrue(done.wait(2))
            self.assertEqual(errors, [])

    def test_slow_receipt_is_bounded_and_written_once(self):
        from companion.backups import atomic_json
        entered, release, wait = self.gate()
        writes = []
        def write(path, value):
            if Path(path).name == 'last-exit.json':
                writes.append(value)
                wait()
            return atomic_json(path, value)
        with patch('companion.backups.atomic_json', side_effect=write):
            done, rows, errors = self.background(lambda: self.session.prepare_shutdown(.05), 'exit-with-slow-receipt')
            self.assertTrue(entered.wait(2))
            self.assertTrue(done.wait(.5), 'receipt writing exceeded the exit budget')
            self.assertEqual(errors, [])
            self.assertIn('receipt_error', rows[0])
            frozen = dict(rows[0])
            release.set()
            self.assertEqual(self.session.prepare_shutdown(.05), frozen)
            self.session._shutdown_receipt_thread.join(2)
            self.assertEqual(len(writes), 1)
            self.assertEqual(self.session._shutdown_result, frozen)
            persisted = json.loads((self.config.parent / 'last-exit.json').read_text())['backup']
            self.assertEqual(persisted, {k: v for k, v in frozen.items() if k != 'receipt_error'})

    def test_receipt_failure_is_explicit_and_frozen(self):
        with patch('companion.backups.atomic_json', side_effect=OSError('controlled receipt failure')) as write:
            with patch('companion.service.logging.exception'):
                result = self.session.prepare_shutdown(.5)
                self.assertIn('receipt_error', result)
                self.assertEqual(self.session.prepare_shutdown(.5), result)
                self.assertEqual(write.call_count, 1)
        self.assertFalse((self.config.parent / 'last-exit.json').exists())

    def test_shutdown_during_settings_replace_rolls_back_without_publishing(self):
        entered, release, wait = self.gate()
        original = self.config.read_bytes()
        revision = self.session.settings_revision
        actual = Path.replace
        blocked = False
        def replace(path, target):
            nonlocal blocked
            if Path(target) == self.config and not blocked:
                blocked = True
                wait()
            return actual(path, target)
        with patch.object(Path, 'replace', replace):
            done, _, errors = self.background(lambda: self.session.update_settings({'always_on_top': True}), 'settings-write')
            self.assertTrue(entered.wait(2))
            self.assertTrue(self.assert_snapshot_returns()['backup_health']['pending'])
            finished, _, failures = self.background(lambda: self.session.prepare_shutdown(.05), 'exit-during-settings')
            self.assertTrue(finished.wait(.5))
            self.assertEqual(failures, [])
            release.set()
            self.assertTrue(done.wait(2))
            self.assertEqual(len(errors), 1)
            self.assertEqual(self.config.read_bytes(), original)
            self.assertEqual(self.session.settings_revision, revision)
            self.assertFalse(self.session.settings['always_on_top'])

    def test_third_party_configuration_is_preserved_after_late_replace(self):
        original = self.config.read_bytes()
        third_party = json.dumps({'save_root': str(self.root), 'slot': 3}).encode()
        actual = Path.replace
        def replace(path, target):
            result = actual(path, target)
            if Path(target) == self.config:
                self.config.write_bytes(third_party)
                self.session.prepare_shutdown(.01)
            return result
        with patch.object(Path, 'replace', replace):
            with self.assertRaises(SettingsConflict):
                self.session.update_settings({'always_on_top': True})
        self.assertEqual(self.config.read_bytes(), third_party)
        self.assertFalse(self.session.settings['always_on_top'])
        self.assertTrue(self.session.config_error)
        self.assertEqual(next(self.config.parent.glob('settings.prior-*.json')).read_bytes(), original)

    def test_oversized_third_party_configuration_marks_rollback_unconfirmed(self):
        original = self.config.read_bytes()
        third_party = b'x' * 65537
        actual = Path.replace
        def replace(path, target):
            result = actual(path, target)
            if Path(target) == self.config:
                self.config.write_bytes(third_party)
            return result
        with patch.object(Path, 'replace', replace):
            with self.assertRaises(SettingsConflict):
                self.session.update_settings({'always_on_top': True})
        self.assertEqual(self.config.read_bytes(), third_party)
        self.assertFalse(self.session.settings['always_on_top'])
        self.assertTrue(self.session.config_error)

        self.assertEqual(next(self.config.parent.glob('settings.prior-*.json')).read_bytes(), original)

    def test_exit_status_and_deadline_callback_do_not_hold_state_lock(self):
        actual = self.session.exit_status
        def check():
            def acquire():
                with self.session.lock:
                    pass
            done, _, errors = self.background(acquire, 'coordinator-state-check')
            self.assertTrue(done.wait(.5), 'coordinator called with the state lock held')
            self.assertEqual(errors, [])
            return actual()
        with patch.object(self.session, 'exit_status', side_effect=check):
            self.session.snapshot()
        from datetime import datetime, timezone
        self.session.settings['stop_at'] = datetime.fromtimestamp(time.time() - 1, timezone.utc).isoformat()
        with patch.object(self.session, 'request_exit', side_effect=lambda *args: check()) as requested:
            self.session.refresh()
            requested.assert_called_once()


if __name__ == '__main__':
    unittest.main()
