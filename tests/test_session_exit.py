import copy
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from companion.backups import BackupManager
from companion.session_exit import ExitCoordinator, ExitDraftStore


class SessionExitTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='denghuo-exit-test-')
        self.addCleanup(self.temporary.cleanup)
        self.store = ExitDraftStore(Path(self.temporary.name) / 'exit-drafts')
        self.finished = threading.Event()
        self.final_calls = []
        self.now = 1000
        def finalize():
            self.final_calls.append(True)
            return {'ok': True, 'state': 'no-save', 'error': ''}
        self.exit = ExitCoordinator(finalize, self.store.save, clock=lambda: self.now,
                                    on_finished=lambda result: self.finished.set())

    def web(self, suffix, revision=0, dirty=False, draft=None):
        identity = 'web-' + suffix * 8
        self.exit.report(identity, revision, dirty, draft=draft, kind='web', label='完整面板')
        return identity

    def test_web_request_waits_for_native_realtime_draft_and_cancel_keeps_session_alive(self):
        delivered = []
        self.exit.register('native', kind='native', label='桌面窗口', notify=delivered.append)
        self.exit.report('native', 1, True, draft={'lookup': {'hero_level': '5'}}, kind='native')
        web = self.web('a')
        request = self.exit.start(web)
        self.exit.acknowledge(request['id'], web, 'clean', 0)
        self.assertEqual(len(delivered), 1)
        self.assertFalse(self.final_calls)
        self.assertEqual(self.exit.status()['phase'], 'confirming')
        self.exit.acknowledge(request['id'], 'native', 'cancel', 1)
        self.assertEqual(self.exit.status()['phase'], 'cancelled')
        self.assertFalse(self.finished.is_set())
        self.assertEqual(self.exit.status()['participants'][0]['dirty'], True)

    def test_new_edit_invalidates_an_old_confirmation_and_old_revision_is_rejected(self):
        a, b = self.web('a'), self.web('b')
        request = self.exit.start(a)
        self.exit.acknowledge(request['id'], a, 'clean', 0)
        self.exit.report(a, 1, True, draft={'hp': '9'})
        self.exit.acknowledge(request['id'], b, 'clean', 0)
        self.assertFalse(self.final_calls)
        with self.assertRaisesRegex(ValueError, '版本'):
            self.exit.acknowledge(request['id'], a, 'discard', 0)
        with self.assertRaisesRegex(ValueError, '未保存'):
            self.exit.acknowledge(request['id'], a, 'clean', 1)
        self.exit.acknowledge(request['id'], a, 'discard', 1)
        self.assertTrue(self.finished.wait(1))
        self.assertEqual(len(self.final_calls), 1)

    def test_offline_dirty_tab_is_preserved_until_explicit_save_and_can_be_loaded(self):
        draft = {'numeric': {'id': 'items.potions.potionofhealing', 'raw': {'hp': '9'}},
                 'settings': {'save_root': 'unavailable-folder', 'slot': 'auto'}}
        source = self.web('a', 4, True, draft)
        self.exit.unregister(source, 4, True, draft=draft)
        self.now += 500
        active = self.web('b')
        request = self.exit.start(active)
        self.exit.acknowledge(request['id'], active, 'clean', 0)
        self.assertFalse(self.finished.is_set())
        self.assertEqual(len(self.exit.status()['participants']), 2)
        result = self.exit.resolve_offline(request['id'], source, 'save', 4)
        loaded = self.store.load(result['saved']['id'])
        self.assertEqual(loaded['draft'], draft)
        self.assertTrue(self.finished.wait(1))
        self.assertEqual(len(self.store.list()), 1)

    def test_offline_save_failure_never_counts_as_permission_to_discard(self):
        source = self.web('a', 1, True, {'raw': {'hp': '9'}})
        self.now += 20
        request = self.exit.start()
        with patch.object(self.exit, 'save_draft', side_effect=OSError('controlled full disk')):
            with self.assertRaises(OSError):
                self.exit.resolve_offline(request['id'], source, 'save', 1)
        self.assertFalse(self.final_calls)
        self.assertEqual(self.exit.status()['phase'], 'confirming')
        self.assertIsNone(self.exit.status()['participants'][0]['ack'])

    def test_cancelled_request_cannot_be_used_for_a_later_exit(self):
        a = self.web('a', 1, True, {'hp': '9'})
        first = self.exit.start(a)
        self.exit.acknowledge(first['id'], a, 'cancel', 1)
        second = self.exit.start(a)
        self.assertNotEqual(first['id'], second['id'])
        with self.assertRaisesRegex(ValueError, '过期'):
            self.exit.acknowledge(first['id'], a, 'discard', 1)
        self.assertFalse(self.final_calls)

    def test_raw_draft_preserves_invalid_inputs_without_applying_them_and_rejects_tokens(self):
        raw = {'lookup': {'hp': '-not-an-integer', 'note': '稍后查\n避免重复升级'},
               'play_settings': {'unknown_hotkey': 'Ctrl+bad-key'}}
        original = copy.deepcopy(raw)
        saved = self.store.save('native', 'native-session', '待完成', raw)
        self.assertEqual(self.store.load(saved['id'])['draft'], original)
        self.assertEqual(raw, original)
        with self.assertRaisesRegex(ValueError, '口令'):
            self.store.save('native', 'native-session', '不要保存认证字段', {'nested': {'token': 'secret'}})
        with self.assertRaises(ValueError):
            self.store.load('../outside')

    def test_no_editing_surface_finalizes_once_and_reports_backup_failure(self):
        self.exit.finalize = lambda: {'ok': False, 'state': 'failed', 'error': '最后一次备份未完成'}
        first = self.exit.start('headless')
        self.assertTrue(self.finished.wait(1))
        second = self.exit.start('headless')
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(second['phase'], 'finished')
        self.assertIn('未完成', second['error'])


class FinalCaptureTests(unittest.TestCase):
    def test_missing_default_is_only_allowed_before_any_protected_progress(self):
        missing = self.root / 'never-created-default'
        result = self.manager.final_capture(missing, time.monotonic() + 1, allow_missing_default=True)
        self.assertEqual((result['ok'], result['state']), (True, 'no-save'))
        result = self.manager.final_capture(missing, time.monotonic() + 1)
        self.assertEqual((result['ok'], result['state']), (False, 'unavailable'))
        self.manager.capture(self.root, 1)
        relocated = self.root.with_name('preserved-original-saves')
        self.root.replace(relocated)
        result = self.manager.final_capture(self.root, time.monotonic() + 1, allow_missing_default=True)
        self.assertFalse(result['ok']); self.assertEqual(result['state'], 'unavailable')
        reloaded = BackupManager(self.manager.directory, closed_check=lambda: None)
        self.assertFalse(reloaded.final_capture(self.root, time.monotonic() + 1, allow_missing_default=True)['ok'])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='denghuo-final-capture-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'saves'
        self.folder = self.root / 'game1'
        self.folder.mkdir(parents=True)
        self.manager = BackupManager(Path(self.temporary.name) / 'backups', closed_check=lambda: None)
        self.write(20)

    def write(self, hp):
        game = {'depth': 2, 'branch': 0, 'version': 922, 'generated_levels': [2], 'seed': 9,
                'hero': {'class': 'MAGE', 'HP': hp, 'HT': 40, 'STR': 10, 'lvl': 2,
                         'inventory': [], 'buffs': []}}
        level = {'__className': 'com.shatteredpixel.shatteredpixeldungeon.levels.SewerLevel',
                 'version': 922, 'width': 4, 'height': 4, 'map': [4] * 16,
                 'visited': [False] * 16, 'mapped': [False] * 16}
        (self.folder / 'game.dat').write_bytes(gzip.compress(json.dumps(game).encode()))
        (self.folder / 'depth2.dat').write_bytes(gzip.compress(json.dumps({'level': level}).encode()))

    def hashes(self):
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.folder.iterdir()}

    def test_last_progress_written_inside_ten_second_gap_is_captured_without_touching_original(self):
        first = self.manager.capture(self.root, 1)
        self.write(34)
        original = self.hashes()
        final = self.manager.final_capture(self.root, time.monotonic() + 1)
        self.assertTrue(final['ok'])
        self.assertNotEqual(first['id'], final['captured'][0]['id'])
        metadata, payloads, game, identity = self.manager.checked_archive(self.root, final['captured'][0]['id'], 1)
        self.assertEqual(payloads['game.dat'], (self.folder / 'game.dat').read_bytes())
        self.assertEqual(self.hashes(), original)

    def test_unstable_first_attempt_retries_and_never_uses_a_mixed_snapshot(self):
        actual = self.manager.capture
        calls = []
        def interleaved(root, slot, *, deadline=None):
            calls.append(True)
            if len(calls) == 1:
                self.write(34)
                raise ValueError('游戏正在保存，下一次重试')
            return actual(root, slot, deadline=deadline)
        with patch.object(self.manager, 'capture', side_effect=interleaved):
            result = self.manager.final_capture(self.root, time.monotonic() + 1)
        self.assertTrue(result['ok'])
        self.assertEqual(len(calls), 2)
        _, payloads, game, identity = self.manager.checked_archive(self.root, result['captured'][0]['id'], 1)
        self.assertEqual(payloads['game.dat'], (self.folder / 'game.dat').read_bytes())

    def test_capacity_failure_is_bounded_and_preserves_original_bytes(self):
        before = self.hashes()
        clock, attempts = [1000.0], []
        actual = self.manager.capture
        def fail_at_deadline(root, slot, *, deadline=None):
            attempts.append(slot)
            try:
                return actual(root, slot, deadline=deadline)
            finally:
                # Expire the shared budget after the real capacity check, rather
                # than racing Windows file I/O against a 150 ms wall-clock limit.
                clock[0] = 1000.15
        with (patch('companion.backups.MAX_STORAGE', 1),
              patch('companion.backups.time.monotonic', side_effect=lambda: clock[0]),
              patch.object(self.manager, 'capture', side_effect=fail_at_deadline)):
            result = self.manager.final_capture(self.root, 1000.15)
        self.assertFalse(result['ok'])
        self.assertIn('512 MiB', result['error'])
        self.assertEqual(attempts, [1])
        self.assertEqual(clock[0], 1000.15)
        self.assertEqual(self.hashes(), before)
        self.assertFalse(list(self.manager.directory.rglob('*.zip')))

    def test_paused_backup_is_respected_and_no_save_is_a_normal_exit(self):
        self.manager.set_enabled(False)
        self.assertEqual(self.manager.final_capture(self.root, time.monotonic() + 1)['state'], 'paused')
        self.assertFalse(list(self.manager.directory.rglob('*.zip')))
        self.manager.set_enabled(True)
        empty = self.root / 'empty'
        empty.mkdir()
        self.assertEqual(self.manager.final_capture(empty, time.monotonic() + 1)['state'], 'no-save')


if __name__ == '__main__':
    unittest.main()
