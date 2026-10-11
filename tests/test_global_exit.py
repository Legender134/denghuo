"""Final global progress capture and receipt truth, using synthetic files only."""
import copy
import gzip
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from companion import global_history, global_progress
from companion.native_manager import NativeManager
from companion.service import Session
from companion.support import help_status
from tests import test_backup_destination as slot_fixtures


def write_slot(root, hp):
    slot_fixtures.BackupDestinationTests.write_save(SimpleNamespace(saves=root), hp=hp)


class GlobalExitTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='denghuo-global-exit-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / 'synthetic-game'
        self.root.mkdir()
        self.config = self.base / 'assistant' / 'settings.json'
        self.config.parent.mkdir()
        self.config.write_text(json.dumps({'save_root': str(self.root), 'slot': 'auto'}), encoding='utf-8')
        self.session = Session(self.config)
        self.addCleanup(self.stop)
        self.write_globals()

    def stop(self):
        self.session.stop.set()
        if self.session._shutdown_thread:
            self.session._shutdown_thread.join(5)
            self.assertFalse(self.session._shutdown_thread.is_alive())
        if self.session._shutdown_receipt_thread:
            self.session._shutdown_receipt_thread.join(5)
            self.assertFalse(self.session._shutdown_receipt_thread.is_alive())
        self.assertTrue(self.session.exit_coordinator.flush_checkpoints(5))

    def write_globals(self, total=1):
        for name, value in [('badges.dat', {'badges': ['BOSS_SLAIN_1']}),
                            ('rankings.dat', {'records': [], 'latest': -1, 'total': total, 'won': 0})]:
            (self.root / name).write_bytes(gzip.compress(json.dumps(value).encode(), mtime=0))

    def originals(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def assert_global_bytes(self, result):
        global_result = result['global_progress']
        self.assertTrue(global_result['protected'])
        self.assertEqual(global_result['state'], 'protected')
        row = next(row for row in global_history.records(self.session.backups, self.root)
                   if row['id'] == global_result['snapshot_id'])
        self.assertEqual(global_history.raw_files(self.session.backups, self.root, row),
                         {name: (self.root / name).read_bytes() for name in global_progress.FILES})

    def test_exit_before_first_tick_protects_globals_without_any_slot(self):
        before = self.originals()
        result = self.session.prepare_shutdown()
        self.assertEqual((result['ok'], result['state'], result['captured']), (True, 'captured', []))
        self.assert_global_bytes(result)
        self.assertEqual(self.originals(), before)
        self.assertEqual(json.loads((self.config.parent / 'last-exit.json').read_bytes())['backup'], result)
        message = NativeManager.finished_exit_message({'backup_result': result})
        self.assertIn('全局进度：成就、排行', message)
        self.assertNotIn('没有游戏存档', message)

    def test_change_inside_normal_tick_gap_is_captured(self):
        self.session.backups.tick(self.root)
        old = global_history.records(self.session.backups, self.root)[0]['id']
        self.write_globals(total=2)
        before = self.originals()
        result = self.session.prepare_shutdown()
        self.assertTrue(result['ok'])
        self.assertNotEqual(result['global_progress']['snapshot_id'], old)
        self.assert_global_bytes(result)
        self.assertEqual(self.originals(), before)

    def test_slot_recovery_failure_does_not_skip_independent_globals(self):
        write_slot(self.root, hp=20)
        before = self.originals()
        with patch.object(self.session.backups, 'recovery_status', return_value={
                'available': False, 'blocked_slots': [], 'error': '受控槽位恢复关联损坏'}):
            result = self.session.backups.final_capture(self.root, time.monotonic() + 2)
        self.assertEqual((result['ok'], result['state']), (False, 'partial'))
        self.assertIn('槽位恢复关联', result['error'])
        self.assert_global_bytes(result)
        self.assertEqual(self.originals(), before)

    def test_global_capacity_failure_keeps_successful_slot_in_receipt(self):
        write_slot(self.root, hp=20)
        global_history.capture(self.session.backups, self.root)
        self.write_globals(total=2)
        before = self.originals()
        with patch('companion.global_history.MAX_SNAPSHOTS', 1):
            result = self.session.backups.final_capture(self.root, time.monotonic() + 2)
        self.assertEqual((result['ok'], result['state']), (False, 'partial'))
        self.assertEqual([row['slot'] for row in result['captured']], [1])
        self.assertFalse(result['global_progress']['protected'])
        self.assertIn('全局进度', result['error'])
        self.assertEqual(self.originals(), before)

    def test_paused_exit_does_not_create_global_history(self):
        before = self.originals()
        self.session.backups.set_enabled(False)
        result = self.session.prepare_shutdown()
        self.assertEqual((result['state'], result['global_progress']['state']), ('paused', 'paused'))
        self.assertEqual(global_history.records(self.session.backups, self.root), [])
        self.assertEqual(self.originals(), before)

    def test_missing_root_with_existing_global_history_is_not_a_new_empty_default(self):
        global_history.capture(self.session.backups, self.root)
        self.root.rename(self.base / 'preserved-synthetic-game')
        result = self.session.backups.final_capture(self.root, time.monotonic() + 2, allow_missing_default=True)
        self.assertEqual((result['ok'], result['state']), (False, 'unavailable'))
        self.assertEqual(result['global_progress']['state'], 'unavailable')

    def test_native_receipts_name_only_verified_global_files_and_keep_partial_success(self):
        global_result = {'state': 'protected', 'protected': True, 'raw_retained': True,
            'snapshot_id': 'e' * 64, 'files': ['rankings.dat'], 'error': ''}
        partial = {'ok': False, 'state': 'partial', 'captured': [], 'global_progress': global_result,
                   'error': '槽位 1 检查超时'}
        message = NativeManager.finished_exit_message({'backup_result': partial})
        self.assertIn('槽位 1 检查超时', message)
        self.assertIn('已完成的备份：全局进度：排行', message)
        self.assertNotIn('成就', message)
        malformed = {'ok': True, 'state': 'captured', 'captured': [{'slot': 1, 'id': None}],
                     'global_progress': {**global_result, 'snapshot_id': 'bad'}}
        self.assertIn('结果尚未确认', NativeManager.finished_exit_message({'backup_result': malformed}))

    def test_deadline_retains_verified_globals_and_freezes_late_slot_result(self):
        write_slot(self.root, hp=20)
        entered, release = threading.Event(), threading.Event()
        actual_capture = self.session.backups.capture
        def held_capture(root, slot, *, deadline=None):
            entered.set()
            self.assertTrue(release.wait(5))
            return actual_capture(root, slot, deadline=deadline)
        def expire_wait(_):
            self.assertTrue(entered.wait(5))
            return False
        try:
            with (patch.object(self.session.backups, 'capture', side_effect=held_capture),
                  patch('companion.service.time.monotonic', return_value=1000.0),
                  patch.object(self.session._shutdown_done, 'wait', side_effect=expire_wait)):
                result = self.session.prepare_shutdown()
                self.assertEqual((result['ok'], result['state'], result['captured']), (False, 'partial', []))
                self.assertTrue(result['global_progress']['protected'])
                receipt = (self.config.parent / 'last-exit.json').read_bytes()
                frozen = copy.deepcopy(result)
                release.set()
                self.session._shutdown_thread.join(5)
                self.assertFalse(self.session._shutdown_thread.is_alive())
                self.assert_global_bytes(result)
                self.assertEqual(self.session._shutdown_result, frozen)
                self.assertEqual((self.config.parent / 'last-exit.json').read_bytes(), receipt)
        finally:
            release.set()

    def test_help_reports_actual_global_failure_when_slot_is_protected(self):
        write_slot(self.root, hp=20)
        self.session.backups.tick(self.root, force=True)
        row = global_history.records(self.session.backups, self.root)[0]
        path = global_history.folder(self.session.backups, self.root) / (row['id'] + '.json')
        path.write_bytes(b'{damaged preserved manifest')
        original = path.read_bytes()
        self.session.backups.tick(self.root, force=True)
        snap = self.session.snapshot()
        snap['backup_health'] = self.session.backups.health_status(self.root, 1)
        self.assertTrue(snap['backup_health']['last_save_protected'])
        self.assertEqual(snap['backup_health']['global_progress']['state'], 'blocked')
        view = help_status(self.session, snap)
        self.assertTrue(any('成就与排行' in step['title'] and step['page'] == 'backups' for step in view['next_steps']))
        self.assertFalse(view['diagnostic']['backup']['has_problem'])
        self.assertTrue(view['diagnostic']['backup']['global_history']['has_problem'])
        self.assertFalse(view['diagnostic']['backup']['global_history']['last_save_protected'])
        self.assertNotIn(str(self.base), view['diagnostic_text'])
        self.assertNotIn('damaged preserved manifest', view['diagnostic_text'])
        self.assertEqual(path.read_bytes(), original)

    def test_help_diagnostic_does_not_copy_untrusted_state_or_error_strings(self):
        snap = self.session.snapshot()
        secret = '/private/user/save token-secret'
        snap['backup_health'] = {'state': secret, 'error': secret, 'last_save_protected': 'yes',
            'global_progress': {'state': secret, 'error': secret, 'protected': 'yes', 'files': secret}}
        view = help_status(self.session, snap)
        self.assertNotIn(secret, view['diagnostic_text'])
        self.assertEqual(view['diagnostic']['backup']['state'], 'unknown')
        self.assertEqual(view['diagnostic']['backup']['global_history'], {
            'state': 'unknown', 'has_problem': True, 'last_save_protected': False})


if __name__ == '__main__':
    unittest.main()
