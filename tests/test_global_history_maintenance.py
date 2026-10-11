"""Real process-death recovery of local global-history exchanges, on synthetic data."""
from io import BytesIO
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

_profile = tempfile.TemporaryDirectory(prefix='lamp-history-maintenance-profile-')
os.environ['APPDATA'] = str(Path(_profile.name)/'roaming')
os.environ['LOCALAPPDATA'] = str(Path(_profile.name)/'local')

from companion.backups import BackupManager
from companion import global_history as history, global_history_maintenance as maintenance, global_progress as files


KILLED_WORKER = r'''
import json, os, signal, sys
from pathlib import Path
from companion.backups import BackupManager
from companion import global_history as history, global_history_maintenance as maintenance
root, directory, expected, phase = sys.argv[1:]
root = Path(root)
manager = BackupManager(directory, closed_check=lambda: None)
scope = manager.scope(root)
original_sync, original_durable = maintenance._sync, maintenance._durable
def sync(path):
    original_sync(path)
    row = maintenance.pending(manager, root)
    if not row:
        return
    retained = scope / maintenance.ARCHIVES / row['id'] / 'history'
    if retained.exists() and ((phase == 'first-exchange' and not (scope/'global-history').exists())
                             or (phase == 'second-exchange' and (scope/'global-history').exists())):
        os.kill(os.getpid(), signal.SIGKILL)
def durable(path, row):
    original_durable(path, row)
    if phase == 'terminal-receipt' and row['state'] == 'completed' and Path(path).name == 'journal.json':
        os.kill(os.getpid(), signal.SIGKILL)
maintenance._sync, maintenance._durable = sync, durable
history.maintain(manager, root, root, {'expected': expected, 'confirmed': True}, lambda: None)
raise AssertionError('Worker did not reach the requested real kill point')
'''


class GlobalHistoryMaintenanceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='lamp-history-maintenance-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base/'synthetic-game'
        self.root.mkdir()
        self.write_source(1)
        self.manager = BackupManager(self.base/'assistant'/'backups', clock=lambda: 1700000200,
                                     closed_check=lambda: None)
        history.capture(self.manager, self.root)
        self.directory = history.folder(self.manager, self.root)
        self.originals = self.read_tree(self.directory)
        self.game_originals = self.read_tree(self.root)

    def write_source(self, total):
        (self.root/'badges.dat').write_text(json.dumps({'badges': ['BOSS_SLAIN_1']}))
        (self.root/'rankings.dat').write_text(json.dumps({'records': [], 'latest': -1, 'total': total, 'won': 0}))

    @staticmethod
    def read_tree(directory):
        return {path.relative_to(directory).as_posix(): path.read_bytes()
                for path in directory.rglob('*') if path.is_file()}

    def interrupt(self, phase):
        preview = history.maintenance_preview(self.manager, self.root, self.root)
        child = subprocess.run([sys.executable, '-c', KILLED_WORKER, str(self.root),
            str(self.manager.directory), preview['expected'], phase], cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, 'APPDATA': str(self.base/'roaming'), 'LOCALAPPDATA': str(self.base/'local')},
            capture_output=True, text=True, timeout=15)
        self.assertEqual(child.returncode, -signal.SIGKILL, child.stdout+child.stderr)
        row = maintenance.pending(self.manager, self.root)
        self.assertIsNotNone(row)
        self.assertEqual(self.read_tree(self.root), self.game_originals)
        return row

    def service_request(self, action, **extra):
        from companion.service import Session
        if not hasattr(self, 'session'):
            config = self.base/'assistant'/'settings.json'
            config.write_text(json.dumps({'save_root': str(self.root), 'slot': 1}), encoding='utf-8')
            self.session = Session(config)
            self.session.backups.closed_check = lambda: None
            self.addCleanup(self.stop_session)
        return self.session.global_history_action({'action': action, 'context': self.session.backup_context,
            'library': self.session.backups.scope(self.root).name, **extra})

    def stop_session(self):
        self.assertTrue(self.session.exit_coordinator.flush_checkpoints(5))
        self.session.stop.set()

    @unittest.skipUnless(os.name == 'posix', 'The strong-kill acceptance runs in WSL.')
    def test_sigkill_after_first_exchange_can_continue_and_archive_remains_usable(self):
        row = self.interrupt('first-exchange')
        status = history.status(self.manager, self.root, self.root)
        self.assertFalse(status['health']['protected'])
        self.assertTrue(status['pending_maintenance']['can_continue'])
        self.assertGreater(status['storage']['archived_bytes'], 0)
        preview = self.service_request('maintenance-recovery-preview')
        result = self.service_request('maintenance-continue', expected=preview['expected'], confirmed=True)
        self.assertTrue(result['health']['protected'])
        self.assertIsNone(maintenance.pending(self.manager, self.root))
        retained = maintenance.archive_directory(self.manager, self.root, row['id'])
        self.assertEqual(self.read_tree(retained), self.originals)
        raw, _ = history.archive_export(self.manager, self.root, row['id'])
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            for name, value in self.originals.items():
                self.assertEqual(archive.read('history/'+name), value)
        self.assertEqual(self.read_tree(self.root), self.game_originals)

    @unittest.skipUnless(os.name == 'posix', 'The strong-kill acceptance runs in WSL.')
    def test_sigkill_after_second_exchange_can_cancel_without_replacing_game_files(self):
        self.interrupt('second-exchange')
        preview = self.service_request('maintenance-recovery-preview')
        self.assertTrue(preview['can_cancel'])
        result = self.service_request('maintenance-cancel', expected=preview['expected'], confirmed=True)
        self.assertEqual(result['direction'], 'cancel')
        self.assertEqual(self.read_tree(self.directory), self.originals)
        self.assertEqual(self.read_tree(self.root), self.game_originals)
        self.assertIsNone(maintenance.pending(self.manager, self.root))
        self.assertGreater(history.status(self.manager, self.root, self.root)['storage']['maintenance_bytes'], 0)

    @unittest.skipUnless(os.name == 'posix', 'The strong-kill acceptance runs in WSL.')
    def test_sigkill_between_terminal_receipt_and_pointer_stays_discoverable(self):
        row = self.interrupt('terminal-receipt')
        self.assertEqual(row['state'], 'continuing')
        preview = history.maintenance_recovery_preview(self.manager, self.root, self.root)
        history.recover_maintenance(self.manager, self.root, self.root,
            {'expected': preview['expected'], 'confirmed': True}, 'continue', lambda: None)
        status = history.status(self.manager, self.root, self.root)
        self.assertEqual(status['archives'][0]['id'], row['id'])
        self.assertIsNone(status['pending_maintenance'])
        self.assertTrue(status['health']['protected'])

    @unittest.skipUnless(os.name == 'posix', 'The strong-kill acceptance runs in WSL.')
    def test_interruption_source_change_requires_new_preview_and_safe_cancel(self):
        self.interrupt('first-exchange')
        stale = history.maintenance_recovery_preview(self.manager, self.root, self.root)
        self.write_source(2)
        changed = self.read_tree(self.root)
        with self.assertRaisesRegex(ValueError, '重新预览'):
            history.recover_maintenance(self.manager, self.root, self.root,
                {'expected': stale['expected'], 'confirmed': True}, 'continue', lambda: None)
        preview = history.maintenance_recovery_preview(self.manager, self.root, self.root)
        self.assertFalse(preview['can_continue'])
        self.assertTrue(preview['can_cancel'])
        history.recover_maintenance(self.manager, self.root, self.root,
            {'expected': preview['expected'], 'confirmed': True}, 'cancel', lambda: None)
        self.assertEqual(self.read_tree(self.directory), self.originals)
        self.assertEqual(self.read_tree(self.root), changed)

    @unittest.skipUnless(os.name == 'posix', 'The strong-kill acceptance runs in WSL.')
    def test_external_new_history_bytes_reject_both_directions_and_empty_source_stays_pending(self):
        row = self.interrupt('first-exchange')
        for name in ('badges.dat', 'rankings.dat'):
            (self.root/name).unlink()
        with self.assertRaisesRegex(ValueError, '未完成的全局历史维护'):
            history.capture(self.manager, self.root)
        self.directory.mkdir()
        external = self.directory/('0'*64+'.json')
        external.write_bytes(b'new external bytes after interruption')
        preview = history.maintenance_recovery_preview(self.manager, self.root, self.root)
        self.assertFalse(preview['can_continue'])
        self.assertFalse(preview['can_cancel'])
        for direction in ('continue', 'cancel'):
            with self.assertRaises(ValueError):
                history.recover_maintenance(self.manager, self.root, self.root,
                    {'expected': preview['expected'], 'confirmed': True}, direction, lambda: None)
        self.assertEqual(external.read_bytes(), b'new external bytes after interruption')
        retained = self.manager.scope(self.root)/maintenance.ARCHIVES/row['id']/'history'
        self.assertEqual(self.read_tree(retained), self.originals)
        self.assertEqual(history.status(self.manager, self.root, self.root)['health']['state'], 'blocked')

    def test_unrecognized_history_or_unavailable_storage_never_moves_originals(self):
        unknown = self.directory/'user-note.txt'
        unknown.write_bytes(b'user owned original')
        before = self.read_tree(self.directory)
        with self.assertRaisesRegex(ValueError, '未识别'):
            history.maintenance_preview(self.manager, self.root, self.root)
        self.assertEqual(self.read_tree(self.directory), before)
        with patch.object(self.manager, 'ensure_storage', side_effect=ValueError('磁盘离线')):
            with self.assertRaisesRegex(ValueError, '磁盘离线'):
                history.maintenance_preview(self.manager, self.root, self.root)
        self.assertEqual(self.read_tree(self.directory), before)

    def test_real_64_mib_orphan_only_history_rotates_without_deleting_original_bytes(self):
        manager = BackupManager(self.base/'large-library-backups', closed_check=lambda: None)
        directory = history.folder(manager, self.root)
        objects = directory/'objects'
        objects.mkdir(parents=True)
        hashes = {}
        for index in range(4):
            raw = bytes([65+index])*files.MAX_BYTES
            digest = files.digest(raw)
            (objects/(digest+'.dat')).write_bytes(raw)
            hashes[digest+'.dat'] = {'sha256': digest, 'bytes': len(raw)}
        self.assertEqual(history.usage(directory)['bytes'], 64*1024*1024)
        with self.assertRaisesRegex(ValueError, '64 MiB'):
            history.capture(manager, self.root)
        preview = history.maintenance_preview(manager, self.root, self.root)
        self.assertEqual(preview['records'], 0)
        self.assertEqual(preview['bytes'], 64*1024*1024)
        self.assertEqual(len(preview['originals']), 4)
        result = history.maintain(manager, self.root, self.root,
            {'expected': preview['expected'], 'confirmed': True}, lambda: None)
        self.assertTrue(result['health']['protected'])
        self.assertEqual(result['active_after']['count'], 1)
        self.assertEqual(result['disk_bytes_released'], 0)
        retained = maintenance.archive_directory(manager, self.root, result['archive_id'])/'objects'
        self.assertEqual({path.name for path in retained.iterdir()}, set(hashes))
        for path in retained.iterdir():
            raw = path.read_bytes()
            self.assertEqual({'bytes': len(raw), 'sha256': files.digest(raw)}, hashes[path.name])
        status = history.status(manager, self.root, self.root)
        self.assertEqual(status['storage']['archived_bytes'], 64*1024*1024)
        self.assertGreater(status['storage']['total_local_bytes'], 64*1024*1024)
        self.assertEqual(self.read_tree(self.root), self.game_originals)


if __name__ == '__main__':
    unittest.main()
