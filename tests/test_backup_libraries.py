import gzip
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from zipfile import ZipFile
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from companion import backup_libraries as libraries
from companion.backups import BackupLibrary, BackupManager


class BackupLibraryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='denghuo-library-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.old = self.base / 'old-game'
        self.current = self.base / 'current-game'
        self.current.mkdir()
        self.now = 1700000000
        self.manager = BackupManager(self.base / 'assistant/backups', clock=lambda: self.now, closed_check=lambda: None)
        self.rows = [self.capture(hp) for hp in (5, 10, 15, 25)]
        self.identity = self.manager.scope(self.old).name
        fixed = self.manager.selected(self.old, self.rows[0])
        self.manager.manage(self.old, {**self.rows[0], 'locked': True, 'expected_metadata_revision': fixed['metadata_revision']})

    def capture(self, hp):
        self.now += 120
        folder = self.old / 'game1'
        folder.mkdir(parents=True, exist_ok=True)
        game = {'depth': 2, 'version': 920, 'seed': 9, 'generated_levels': [2],
                'hero': {'class': 'MAGE', 'HP': hp, 'HT': 30, 'STR': 10, 'lvl': 2, 'inventory': [], 'buffs': []}}
        level = {'__className': 'com.shatteredpixel.shatteredpixeldungeon.levels.SewerLevel', 'version': 920,
                 'width': 4, 'height': 4, 'map': [4] * 16, 'visited': [False] * 16, 'mapped': [False] * 16}
        for name, value in (('game.dat', game), ('depth2.dat', {'level': level})):
            path = folder / name
            path.write_bytes(gzip.compress(json.dumps(value).encode(), mtime=0))
            os.utime(path, (self.now, self.now))
        return self.manager.capture(self.old, 1)

    def snapshot(self):
        return {path.relative_to(self.base).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.base.rglob('*') if path.is_file()}

    def operate(self, action, payload, identity=None):
        return libraries.operate(self.manager, identity or self.identity, self.current, action, payload)

    def test_discovery_is_read_only_current_empty_old_visible_and_damage_isolated(self):
        broken = self.manager.directory / ('b' * 24)
        broken.mkdir()
        (broken / 'history.json').write_text('preserve broken original')
        before = self.snapshot()
        result = libraries.catalog(self.manager, self.current)
        rows = {row['id']: row for row in result['libraries']}
        self.assertEqual(rows[self.identity]['record_count'], 4)
        self.assertIsNone(rows[self.identity]['source'])
        self.assertEqual(rows[self.identity]['source_status'], 'unregistered')
        self.assertEqual(rows[result['current_library_id']]['record_count'], 0)
        self.assertTrue(rows['b' * 24]['errors'])
        self.assertIsNone(rows['b' * 24]['record_count'])
        self.assertEqual(result['quota']['bytes'], self.manager.storage())
        self.assertGreater(result['quota']['bytes'], 0)
        self.assertEqual(before, self.snapshot())

    def test_preview_and_export_need_no_original_game_directory_and_never_reconnect(self):
        # The indexed scope is sufficient even when its old source is unavailable.
        source = self.base / 'missing-source'
        missing_id = self.manager.scope(source).name
        self.manager.scope(source).mkdir(parents=True)
        raw, _ = self.manager.export(self.old, self.rows[1])
        self.manager.import_archive(source, raw)
        before = self.snapshot()
        details = libraries.details(self.manager, missing_id, self.current)
        self.assertFalse(details['game_operations_available'])
        self.assertEqual([group['kind'] for group in details['groups']], ['active', 'retained', 'quarantine'])
        self.assertFalse(source.exists())
        selected = [{'slot': 1, 'id': self.rows[1]['id']}]
        preview = self.operate('export-preview', {'selected': selected}, missing_id)
        exported, _ = self.operate('batch-export', {'selected': selected, 'expected': preview['expected']}, missing_id)
        with ZipFile(BytesIO(exported)) as archive:
            self.assertEqual(len(json.loads(archive.read('denghuo-transfer.json'))['entries']), 1)
        self.assertEqual(before, self.snapshot())

    def test_retention_preserves_fixed_latest_and_archived_bytes_rejoin_is_explicit(self):
        originals = {row['id']: (self.manager.scope(self.old) / (row['id'] + '.zip')).read_bytes() for row in self.rows}
        observations = {row['id']: row for row in self.manager.history(BackupLibrary(self.identity))}
        game_originals = {path: path.read_bytes() for path in self.old.rglob('*.dat')}
        preview = self.operate('retention-preview', {'policy': {'keep_per_slot': 1}})
        self.assertEqual({row['id'] for row in preview['candidates']}, {self.rows[1]['id'], self.rows[2]['id']})
        with self.assertRaisesRegex(ValueError, '确认'):
            self.operate('archive-retention', {'policy': preview['policy'], 'expected': preview['expected']})
        result = self.operate('archive-retention', {'policy': preview['policy'], 'expected': preview['expected'], 'confirmed': True})
        self.assertEqual((result['archived'], result['deleted']), (2, 0))
        retained = self.manager.retained_status(BackupLibrary(self.identity))
        self.assertEqual(len(retained), 2)
        directory = self.manager.directory.parent / 'backup-recycle' / self.identity
        for row in retained:
            self.assertEqual((directory / row['file']).read_bytes(), originals[row['id']])
        rejoin = self.operate('rejoin-preview', {'file': retained[0]['file']})
        with self.assertRaisesRegex(ValueError, '确认'):
            self.operate('rejoin', {'file': retained[0]['file'], 'expected': rejoin['expected']})
        before_rejoin = observations[retained[0]['id']]
        self.now += 600
        result = self.operate('rejoin', {'file': retained[0]['file'], 'expected': rejoin['expected'], 'confirmed': True})
        self.assertFalse(result['restored'])
        self.assertEqual(len(self.manager.history(BackupLibrary(self.identity))), 3)
        rejoined = self.manager.selected(BackupLibrary(self.identity), before_rejoin)
        self.assertEqual((rejoined['time'], rejoined['last_seen']), (before_rejoin['time'], before_rejoin['last_seen']))
        self.assertEqual(rejoined['imported_at'], self.now)
        next_preview = self.operate('retention-preview', {'policy': {'keep_per_slot': 1}})
        self.assertIn(self.rows[-1]['id'], {row['id'] for row in next_preview['kept']})
        self.assertNotIn(self.rows[-1]['id'], {row['id'] for row in next_preview['candidates']})
        self.assertIn(before_rejoin['id'], {row['id'] for row in next_preview['candidates']})
        self.assertEqual(len(self.manager.retained_status(BackupLibrary(self.identity))), 2)
        for path, raw in game_originals.items():
            self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(list(self.current.iterdir()), [])

    def test_rejoin_preserves_a_newer_real_observation_name_and_fixed_status(self):
        reference = BackupLibrary(self.identity)
        old = self.manager.selected(reference, self.rows[1])
        self.manager.remove(reference, {**old, 'confirm': '移出备份 1'})
        retained = next(row for row in self.manager.retained_status(reference) if row['id'] == old['id'])
        self.now += 600
        self.capture(10)
        observed = self.manager.selected(reference, old)
        self.manager.manage(reference, {**old, 'label': '最近核对', 'locked': True,
                                       'expected_metadata_revision': observed['metadata_revision']})
        self.now += 600
        preview = self.operate('rejoin-preview', {'file': retained['file']})
        self.operate('rejoin', {'file': retained['file'], 'expected': preview['expected'], 'confirmed': True})
        current = self.manager.selected(reference, old)
        self.assertEqual((current['time'], current['last_seen']), (old['time'], observed['last_seen']))
        self.assertEqual(current['label'], '最近核对')
        self.assertTrue(current['locked'])

    def test_legacy_retained_metadata_uses_known_first_observation(self):
        reference = BackupLibrary(self.identity)
        old = self.manager.selected(reference, self.rows[1])
        self.manager.remove(reference, {**old, 'confirm': '移出备份 1'})
        retained = next(row for row in self.manager.retained_status(reference) if row['id'] == old['id'])
        sidecar = self.manager.directory.parent / 'backup-recycle' / self.identity / Path(retained['file']).with_suffix('.json')
        metadata = json.loads(sidecar.read_text(encoding='utf-8'))
        metadata.pop('last_seen')
        sidecar.write_text(json.dumps(metadata), encoding='utf-8')
        self.now += 600
        preview = self.operate('rejoin-preview', {'file': retained['file']})
        self.operate('rejoin', {'file': retained['file'], 'expected': preview['expected'], 'confirmed': True})
        current = self.manager.selected(reference, old)
        self.assertEqual((current['time'], current['last_seen']), (old['time'], old['time']))
        self.assertEqual(current['imported_at'], self.now)

    def test_invalid_retained_observations_keep_archives_and_game_unchanged(self):
        reference = BackupLibrary(self.identity)
        old = self.manager.selected(reference, self.rows[1])
        self.manager.remove(reference, {**old, 'confirm': '移出备份 1'})
        retained = next(row for row in self.manager.retained_status(reference) if row['id'] == old['id'])
        archive = self.manager.directory.parent / 'backup-recycle' / self.identity / retained['file']
        original = archive.read_bytes()
        sidecar = archive.with_suffix('.json')
        metadata = json.loads(sidecar.read_text(encoding='utf-8'))
        game = {path: path.read_bytes() for path in self.old.rglob('*.dat')}
        for value in (None, True, '1700000240', float('nan'), metadata['first_seen'] - 1):
            with self.subTest(last_seen=value):
                sidecar.write_text(json.dumps({**metadata, 'last_seen': value}), encoding='utf-8')
                raw = sidecar.read_bytes()
                with self.assertRaisesRegex(ValueError, '观察时间记录损坏'):
                    self.manager.rejoin(reference, retained)
                self.assertEqual(sidecar.read_bytes(), raw)
                self.assertEqual(archive.read_bytes(), original)
                self.assertNotIn(old['id'], {row['id'] for row in self.manager.history(reference)})
                self.assertTrue(all(path.read_bytes() == data for path, data in game.items()))

    def test_changed_selection_metadata_and_other_library_cannot_reuse_preview(self):
        selected = [{'slot': 1, 'id': self.rows[1]['id']}]
        preview = self.operate('export-preview', {'selected': selected})
        other = self.base / 'other-game'
        raw, _ = self.manager.export(self.old, self.rows[1])
        self.manager.import_archive(other, raw)
        with self.assertRaisesRegex(ValueError, '已变化'):
            self.operate('batch-export', {'selected': selected, 'expected': preview['expected']}, self.manager.scope(other).name)
        current = self.manager.selected(self.old, selected[0])
        self.manager.manage(self.old, {**selected[0], 'label': 'changed', 'expected_metadata_revision': current['metadata_revision']})
        with self.assertRaisesRegex(ValueError, '已变化'):
            self.operate('batch-export', {'selected': selected, 'expected': preview['expected']})
        with self.assertRaisesRegex(ValueError, '已变化'):
            self.operate('batch-export', {'selected': [{'slot': 1, 'id': self.rows[2]['id']}], 'expected': preview['expected']})

    def test_invalid_missing_ids_and_game_operations_are_rejected(self):
        for identity in ('../old-game', '/tmp', 'a' * 64, 'A' * 24, None):
            with self.assertRaises(ValueError):
                libraries.resolve_library(self.manager, identity, self.current)
        with self.assertRaisesRegex(ValueError, '不存在'):
            libraries.resolve_library(self.manager, 'f' * 24, self.current)
        before = self.snapshot()
        for action in ('restore', 'undo', 'capture', 'import', 'reclaim-execute'):
            with self.assertRaisesRegex(ValueError, '不支持'):
                self.operate(action, {})
        self.assertEqual(before, self.snapshot())

    def test_active_undo_target_stays_protected_when_managing_old_library(self):
        row = self.rows[1]
        preview = self.manager.preview(self.old, row)
        self.manager.restore(self.old, {**row, 'confirm': '恢复槽位 1', 'expected_current': preview['expected_current']})
        before_game = {path: path.read_bytes() for path in self.old.rglob('*.dat')}
        preview = self.operate('retention-preview', {'policy': {'keep_per_slot': 1}})
        self.assertEqual({row['id'] for row in preview['candidates']}, {self.rows[2]['id']})
        protected = next(record for record in preview['kept'] if record['id'] == row['id'])
        self.assertTrue(protected['protected'])
        self.assertIn('撤回', protected['reason'])
        self.operate('archive-retention', {'policy': preview['policy'], 'expected': preview['expected'], 'confirmed': True})
        for path, raw in before_game.items():
            self.assertEqual(path.read_bytes(), raw)

    def test_service_keeps_library_management_available_with_broken_connection_settings(self):
        from companion.service import Session
        session = Session.__new__(Session)
        session.lock = threading.RLock()
        session.backups = self.manager
        session.settings = {'save_root': str(self.current)}
        session.config_error = 'Preserve invalid original settings'
        session.backup_context = 'current-connection-generation'
        before = self.snapshot()
        status = session.backup_library_status(expected_context=session.backup_context)
        self.assertIn(self.identity, [row['id'] for row in status['libraries']])
        details = session.backup_library_status(self.identity, session.backup_context)
        self.assertFalse(details['game_operations_available'])
        selected = [{'slot': 1, 'id': self.rows[1]['id']}]
        payload = {'library_id': self.identity, 'selected': selected, 'context': session.backup_context}
        preview = session.backup_library_action({**payload, 'action': 'export-preview'})
        raw, _ = session.backup_library_action({**payload, 'action': 'batch-export', 'expected': preview['expected']})
        self.assertGreater(len(raw), 0)
        session.backup_context = 'different-connection'
        with self.assertRaisesRegex(ValueError, '连接已变化'):
            session.backup_library_action({**payload, 'action': 'batch-export', 'expected': preview['expected']})
        with self.assertRaisesRegex(ValueError, '格式不正确'):
            session.backup_library_action({'action': {}})
        self.assertEqual(session.settings['save_root'], str(self.current))
        self.assertEqual(before, self.snapshot())

    def test_http_library_routes_validate_token_origin_context_and_preview_without_writes(self):
        from companion.panel import PanelBridge
        from companion.server import Server
        from companion.service import Session
        session = Session.__new__(Session)
        session.lock = threading.RLock()
        session.backups = self.manager
        session.settings = {'save_root': str(self.current)}
        session.backup_context = 'current-connection-generation'
        session.panel = PanelBridge()
        server = Server(session)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        before = self.snapshot()
        selected = [{'slot': 1, 'id': self.rows[1]['id']}]
        payload = {'library_id': self.identity, 'context': session.backup_context}

        def request(path, body=None, **extra_headers):
            headers = {'X-Companion-Token': server.token, 'Origin': server.origin,
                       'Content-Type': 'application/json', **extra_headers}
            raw = None if body is None else json.dumps(body).encode()
            with urlopen(Request(server.origin + path, data=raw, headers=headers), timeout=5) as response:
                value = response.read()
                return value if response.headers.get_content_type() != 'application/json' else json.loads(value)

        try:
            catalog = request('/api/backup-libraries?context=' + session.backup_context)
            self.assertIn(self.identity, [row['id'] for row in catalog['libraries']])
            self.assertIn(b'loadBackupLibraries', request('/backup-libraries.js'))
            preview = request('/api/backup-libraries', {**payload, 'action': 'export-preview', 'selected': selected})
            export = {**payload, 'action': 'batch-export', 'selected': selected, 'expected': preview['expected']}
            archive = request('/api/backup-libraries', export)
            with ZipFile(BytesIO(archive)) as exported:
                self.assertEqual(len(json.loads(exported.read('denghuo-transfer.json'))['entries']), 1)
            failures = [
                (export, {'X-Companion-Token': ''}, 403),
                (export, {'Origin': 'https://example.invalid'}, 403),
                ({**export, 'context': 'prior-connection'}, {}, 400),
                ({**export, 'library_id': '../other-library'}, {}, 400),
                ({**export, 'expected': 'stale-preview'}, {}, 400),
                ({**payload, 'action': 'restore'}, {}, 400),
            ]
            for body, headers, status in failures:
                with self.subTest(body=body, headers=headers), self.assertRaises(HTTPError) as caught:
                    request('/api/backup-libraries', body, **headers)
                self.assertEqual(caught.exception.code, status)
            for query in ('', '?context=prior-connection', '?context=' + session.backup_context + '&id=../other'):
                with self.subTest(query=query), self.assertRaises(HTTPError) as caught:
                    request('/api/backup-libraries' + query)
                self.assertEqual(caught.exception.code, 400)
            retention = request('/api/backup-libraries', {**payload, 'action': 'retention-preview', 'policy': {'keep_per_slot': 1}})
            with self.assertRaises(HTTPError) as caught:
                request('/api/backup-libraries', {**payload, 'action': 'archive-retention',
                        'policy': retention['policy'], 'expected': retention['expected']})
            self.assertEqual(caught.exception.code, 400)
            session.backup_context = 'next-connection-generation'
            with self.assertRaises(HTTPError) as caught:
                request('/api/backup-libraries', export)
            self.assertEqual(caught.exception.code, 400)
            self.assertEqual(before, self.snapshot())
            self.assertEqual(session.settings['save_root'], str(self.current))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())


if __name__ == '__main__':
    unittest.main()
