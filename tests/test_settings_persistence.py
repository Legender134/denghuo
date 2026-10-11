"""Shared settings must never overwrite another session's saved connection."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler

from companion.service import Session, SettingsConflict


class SettingsPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / 'first'
        self.other = self.base / 'second'
        self.root.mkdir()
        self.other.mkdir()
        self.config = self.base / 'settings.json'
        self.config.write_text(json.dumps({'save_root': str(self.root), 'slot': 1}), encoding='utf-8')
        self.a, self.b = Session(self.config), Session(self.config)

    def test_old_session_cannot_overwrite_new_root_and_explicit_reload_allows_retry(self):
        original_revision = self.b.settings_revision
        self.a.update_settings({'save_root': str(self.other)}, expected_revision=self.a.settings_revision)
        saved = self.config.read_bytes()
        with self.assertRaisesRegex(SettingsConflict, '磁盘.*更新'):
            self.b.update_settings({'slot': 2}, expected_revision=original_revision)
        self.assertEqual(self.config.read_bytes(), saved)
        self.assertEqual(self.b.settings['save_root'], str(self.root))
        self.assertEqual(self.b.settings['slot'], 1)
        old_context = self.b.backup_context
        receipt = self.b.reload_settings(expected_revision=original_revision)
        self.assertEqual(self.config.read_bytes(), saved)
        self.assertEqual(receipt['settings']['save_root'], str(self.other))
        self.assertNotEqual(receipt['settings_revision'], original_revision)
        self.assertNotEqual(self.b.backup_context, old_context)
        with self.assertRaises(SettingsConflict):
            self.b.update_settings({'slot': 2}, expected_revision=original_revision)
        self.b.update_settings({'slot': 2}, expected_revision=receipt['settings_revision'])
        self.assertEqual(json.loads(self.config.read_bytes())['save_root'], str(self.other))
        self.assertEqual(json.loads(self.config.read_bytes())['slot'], 2)

    def test_storage_lock_blocks_another_session_and_preserves_snapshot_liveness(self):
        saved = self.config.read_bytes()
        with self.a._settings_storage_lock():
            self.assertEqual(self.b.snapshot()['settings']['slot'], 1)
            with self.assertRaisesRegex(SettingsConflict, '正在保存或重新读取'):
                self.b.update_settings({'slot': 2})
            with self.assertRaises(SettingsConflict):
                self.b.reload_settings()
        self.assertEqual(self.config.read_bytes(), saved)
        self.b.update_settings({'slot': 2})
        self.assertEqual(json.loads(self.config.read_bytes())['slot'], 2)

    def test_missing_new_or_invalid_external_configuration_is_never_silently_overwritten(self):
        for raw in (b'{broken', b'x' * 65537):
            self.config.write_bytes(raw)
            with self.assertRaises(ValueError):
                self.b.reload_settings()
            with self.assertRaises(SettingsConflict):
                self.b.update_settings({'slot': 2})
            self.assertEqual(self.config.read_bytes(), raw)
        self.config.unlink()
        with self.assertRaises(SettingsConflict):
            self.b.reload_settings()
        with self.assertRaises(SettingsConflict):
            self.b.update_settings({'slot': 2})
        absent = self.base / 'absent.json'
        first, stale = Session(absent), Session(absent)
        first.update_settings({'save_root': str(self.root), 'slot': 1})
        original = absent.read_bytes()
        with self.assertRaises(SettingsConflict):
            stale.update_settings({'save_root': str(self.other), 'slot': 2})
        self.assertEqual(absent.read_bytes(), original)

    def test_reload_rebinds_backup_manager_and_rejects_shutdown_or_late_inprocess_change(self):
        backup = self.base / 'backup-disk'
        backup.mkdir()
        saved = json.dumps({'save_root': str(self.other), 'slot': 2, 'backup_root': str(backup),
                            'mode': 'manual', 'stop_at': '2000-01-01T00:00:00+08:00'}).encode()
        self.config.write_bytes(saved)
        receipt = self.b.reload_settings(expected_revision=self.b.settings_revision)
        self.assertEqual(receipt['settings']['mode'], 'save')
        self.assertEqual(receipt['settings']['stop_at'], '')
        self.assertEqual(self.b.backups.directory, backup.resolve() / 'backups')
        self.assertEqual(self.config.read_bytes(), saved)
        with self.assertRaises(SettingsConflict):
            self.b.reload_settings(expected_revision='expired')
        self.b._shutdown_requested.set()
        with self.assertRaises(ValueError):
            self.b.reload_settings()

    def test_repair_of_loaded_invalid_file_keeps_original_and_updates_disk_baseline(self):
        raw = b'{broken'
        self.config.write_bytes(raw)
        invalid = Session(self.config)
        self.assertTrue(invalid.config_error)
        invalid.update_settings({'save_root': str(self.root), 'slot': 1})
        self.assertEqual(next(self.base.glob('settings.recovery-*.json')).read_bytes(), raw)
        invalid.update_settings({'slot': 2})
        self.assertEqual(json.loads(self.config.read_bytes())['slot'], 2)

    def test_actual_http_conflict_reload_and_retry_preserve_other_session_changes(self):
        from companion.server import Server
        server = Server(self.b)
        worker = threading.Thread(target=server.serve_forever)
        worker.start()
        opener = build_opener(ProxyHandler({}))
        def request(path, payload, expected=200):
            request = Request(server.origin + path, data=json.dumps(payload).encode(),
                headers={'Content-Type': 'application/json', 'Origin': server.origin,
                         'X-Companion-Token': server.token})
            try:
                with opener.open(request, timeout=5) as response:
                    status, data = response.status, response.read()
            except HTTPError as exc:
                status, data = exc.code, exc.read()
            self.assertEqual(status, expected, data)
            return json.loads(data)
        try:
            revision = self.b.settings_revision
            self.a.update_settings({'save_root': str(self.other)})
            saved = self.config.read_bytes()
            request('/api/settings', {'slot': 3, 'expected_revision': revision}, 409)
            self.assertEqual(self.config.read_bytes(), saved)
            request('/api/settings/reload', {}, 400)
            request('/api/settings/reload', {'expected_revision': 'expired'}, 409)
            current = request('/api/settings/reload', {'expected_revision': revision})
            self.assertEqual(current['settings']['save_root'], str(self.other))
            request('/api/settings', {'slot': 3, 'expected_revision': current['settings_revision']})
            final = json.loads(self.config.read_bytes())
            self.assertEqual(final['save_root'], str(self.other))
            self.assertEqual(final['slot'], 3)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(5)
            self.assertFalse(worker.is_alive())
