"""Default automatic global history uses only explicit synthetic game roots."""
import gzip
from http.client import HTTPConnection
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import zipfile

from companion import global_history as history, global_progress as files
from companion.service import Session
from tests import test_backup_destination as slot_fixtures


class GlobalHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='lamp-global-history-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.saves = self.base/'synthetic-game'
        self.saves.mkdir()
        self.config = self.base/'assistant'/'settings.json'
        self.config.parent.mkdir()
        self.config.write_text(json.dumps({'save_root': str(self.saves), 'slot': 1}), encoding='utf-8')
        self.session = Session(self.config)
        self.addCleanup(self.stop)
        self.now = 1700000100
        self.session.backups.clock = lambda: self.now
        self.session.backups.closed_check = Mock()
        self.write_globals()

    def stop(self):
        self.assertTrue(self.session.exit_coordinator.flush_checkpoints(5))
        self.session.stop.set()

    def write_globals(self, badge='BOSS_SLAIN_1', total=1):
        for name, value in (('badges.dat', {'badges': [badge]}),
                            ('rankings.dat', {'records': [], 'latest': -1, 'total': total, 'won': 0})):
            (self.saves/name).write_bytes(gzip.compress(json.dumps(value).encode(), mtime=0))

    def tick(self):
        self.now += 11
        self.session.backups.tick(self.saves)
        return self.session.global_history_status()

    def request(self, action, row, **extra):
        return {'action': action, 'context': self.session.backup_context,
                'library': row['library'], 'id': row['id'], **extra}

    def restore(self, row, choices=None):
        preview = self.session.global_history_action(self.request('restore-preview', row))
        choices = choices or {item['name']: 'replace' for item in preview['files']}
        return self.session.global_history_action(self.request('restore', row, expected=preview['expected'],
            confirmed=True, version=files.VERSION, version_confirmed=True, choices=choices))

    def test_default_tick_without_any_slot_preserves_exact_global_raw_bytes_and_exports(self):
        original = {name: (self.saves/name).read_bytes() for name in files.FILES}
        status = self.tick()
        self.assertTrue(status['health']['protected'])
        self.assertTrue(status['health']['raw_retained'])
        self.assertEqual(len(status['history']), 1)
        self.assertFalse(list(self.saves.glob('game*')))
        row = status['history'][0]
        self.assertEqual(history.raw_files(self.session.backups, self.saves, row), original)
        raw, filename = self.session.global_history_action(self.request('export', row))
        self.assertTrue(filename.endswith('.zip'))
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            for name, value in original.items():
                self.assertEqual(archive.read('global/'+name), value)
        self.assertIn('没有来源版本', status['version_notice'])
        self.assertEqual(self.session.backups.history(self.saves), [])

    def test_content_deduplication_ignores_mtime_and_shares_unchanged_raw_objects(self):
        initial = self.tick()
        for _ in range(3):
            os.utime(self.saves/'badges.dat', (self.now, self.now))
            status = self.tick()
            self.assertEqual(len(status['history']), 1)
            self.assertEqual(status['storage']['bytes'], initial['storage']['bytes'])
        self.write_globals('BOSS_SLAIN_2')
        changed = self.tick()
        self.assertEqual(len(changed['history']), 2)
        objects = list((Path(changed['directory'])/'objects').glob('*.dat'))
        self.assertEqual(len(objects), 3)
        self.assertTrue(changed['health']['protected'])

    def test_invalid_original_is_retained_warns_and_can_only_restore_valid_selected_files(self):
        bad = b'{controlled damaged ranking original'
        (self.saves/'rankings.dat').write_bytes(bad)
        status = self.tick()
        self.assertEqual(status['health']['state'], 'warning')
        self.assertFalse(status['health']['protected'])
        self.assertTrue(status['health']['raw_retained'])
        row = status['history'][0]
        self.assertEqual(history.raw_files(self.session.backups, self.saves, row)['rankings.dat'], bad)
        raw, _ = self.session.global_history_action(self.request('export', row))
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            self.assertEqual(archive.read('global/rankings.dat'), bad)
        with self.assertRaisesRegex(ValueError, '损坏'):
            self.restore(row)
        result = self.restore(row, {'badges.dat': 'replace', 'rankings.dat': 'keep'})
        self.assertEqual(result['restored'], ['badges.dat'])
        self.assertEqual((self.saves/'rankings.dat').read_bytes(), bad)

    def test_capacity_stops_new_changes_without_deleting_or_claiming_protection(self):
        initial = self.tick()
        originals = slot_fixtures.BackupDestinationTests.files(Path(initial['directory']))
        with patch.object(history, 'MAX_STORAGE', initial['storage']['bytes']):
            self.assertTrue(self.tick()['health']['protected'])
            self.write_globals('BOSS_SLAIN_2')
            status = self.tick()
            self.assertEqual(self.session.backups.global_health['state'], 'blocked')
            self.assertFalse(status['health']['protected'])
            self.assertEqual(len(status['history']), 1)
            self.assertIn('64 MiB', self.session.backups.global_health['error'])
            self.assertEqual(status['health']['state'], 'blocked')
        self.assertEqual(slot_fixtures.BackupDestinationTests.files(Path(initial['directory'])), originals)
        with patch.object(history, 'MAX_SNAPSHOTS', 1):
            self.tick()
            self.assertFalse(self.session.backups.global_health['protected'])
            self.assertIn('512份', self.session.backups.global_health['error'])
        self.assertEqual(len(self.session.global_history_status()['history']), 1)

    def test_pause_and_memory_only_snapshot_immediately_retract_protection(self):
        self.tick()
        with patch.object(Path, 'open', side_effect=AssertionError('UI snapshot tried disk I/O')):
            self.assertTrue(self.session.snapshot()['backup_health']['global_progress']['protected'])
        self.session.backups.set_enabled(False)
        self.write_globals('BOSS_SLAIN_2')
        self.now += 11
        self.session.backups.tick(self.saves)
        with patch.object(Path, 'open', side_effect=AssertionError('UI snapshot tried disk I/O')):
            health = self.session.snapshot()['backup_health']['global_progress']
            self.assertEqual(health['state'], 'paused')
            self.assertFalse(health['protected'])
        self.assertEqual(len(self.session.global_history_status()['history']), 1)

    def test_changed_source_during_read_retries_without_publishing_a_false_snapshot(self):
        original_read, changed = files.read, [False]
        def read(path):
            value = original_read(path)
            if Path(path) == self.saves/'badges.dat' and not changed[0]:
                changed[0] = True
                self.write_globals('BOSS_SLAIN_2')
            return value
        with patch.object(files, 'read', read):
            self.tick()
        self.assertFalse(self.session.backups.global_health['protected'])
        self.assertIn('正在变化', self.session.backups.global_health['error'])
        self.assertEqual(self.session.global_history_status()['history'], [])
        self.assertTrue(self.tick()['health']['protected'])

    def test_restore_needs_fresh_hashes_version_confirmation_and_per_file_choices(self):
        row = self.tick()['history'][0]
        self.write_globals('BOSS_SLAIN_2', 2)
        before = {name: (self.saves/name).read_bytes() for name in files.FILES}
        preview = self.session.global_history_action(self.request('restore-preview', row))
        valid = self.request('restore', row, expected=preview['expected'], confirmed=True,
            version=files.VERSION, version_confirmed=True, choices={'badges.dat': 'replace', 'rankings.dat': 'keep'})
        for override in ({'confirmed': False}, {'version': 'unknown'}, {'version_confirmed': False},
                         {'choices': {'badges.dat': 'replace'}}, {'choices': {'badges.dat': 'keep', 'rankings.dat': 'keep'}}):
            with self.subTest(override=override), self.assertRaises(ValueError):
                self.session.global_history_action({**valid, **override})
            self.assertEqual({name: (self.saves/name).read_bytes() for name in files.FILES}, before)
        self.write_globals('BOSS_SLAIN_3', 2)
        with self.assertRaisesRegex(ValueError, '已变化'):
            self.session.global_history_action(valid)
        current_badges = (self.saves/'badges.dat').read_bytes()
        result = self.restore(row, valid['choices'])
        self.assertEqual((self.saves/'rankings.dat').read_bytes(), before['rankings.dat'])
        self.assertEqual((Path(result['retained_directory'])/'before-badges.dat').read_bytes(), current_badges)
        self.assertEqual((self.saves/'badges.dat').read_bytes(), history.raw_files(self.session.backups, self.saves, row)['badges.dat'])
        self.assertFalse(list(self.saves.glob('game*')))

    def test_game_running_and_corrupt_stored_object_never_write_game_originals(self):
        row = self.tick()['history'][0]
        original = {name: (self.saves/name).read_bytes() for name in files.FILES}
        self.session.backups.closed_check.side_effect = ValueError('游戏仍运行')
        with self.assertRaisesRegex(ValueError, '仍运行'):
            self.restore(row)
        self.session.backups.closed_check.side_effect = None
        object_path = history.folder(self.session.backups, self.saves)/'objects'/(row['files']['badges.dat']['sha256']+'.dat')
        object_path.write_bytes(b'controlled corrupted retained bytes')
        status = self.session.global_history_status()
        self.assertFalse(status['health']['protected'])
        self.assertEqual(status['health']['state'], 'blocked')
        with self.assertRaisesRegex(ValueError, '字节变化'):
            self.restore(row)
        self.assertEqual({name: (self.saves/name).read_bytes() for name in files.FILES}, original)

    def test_old_library_is_browsable_exportable_and_recovers_to_the_current_root_only(self):
        row = self.tick()['history'][0]
        original_root = self.saves
        original = {name: (original_root/name).read_bytes() for name in files.FILES}
        stale_request = self.request('export', row)
        target = self.base/'another-synthetic-game'
        target.mkdir()
        self.session.update_settings({'save_root': str(target)})
        with self.assertRaisesRegex(ValueError, '连接已变化'):
            self.session.global_history_action(stale_request)
        status = self.session.global_history_status(row['library'])
        self.assertFalse(status['current_library'])
        self.assertEqual(status['history'][0]['id'], row['id'])
        self.restore(row, {'badges.dat': 'replace', 'rankings.dat': 'keep'})
        self.assertEqual((target/'badges.dat').read_bytes(), original['badges.dat'])
        self.assertFalse((target/'rankings.dat').exists())
        self.assertEqual({name: (original_root/name).read_bytes() for name in files.FILES}, original)
        self.assertEqual(self.session.settings['save_root'], str(target))

    def test_history_portable_export_roundtrips_existing_migration_with_exact_selected_bytes(self):
        from companion import migration
        row = self.tick()['history'][0]
        original = {name: (self.saves/name).read_bytes() for name in files.FILES}
        request = self.request('portable-export', row, selected=list(files.FILES),
                               version=files.VERSION, version_confirmed=True)
        for override in ({'selected': []}, {'selected': ['badges.dat']*2}, {'selected': ['game.dat']},
                         {'version': 'unknown'}, {'version_confirmed': False}):
            with self.subTest(override=override), self.assertRaises(ValueError):
                self.session.global_history_action({**request, **override})
        raw, filename = self.session.global_history_action(request)
        self.assertTrue(filename.endswith('.zip'))
        self.write_globals('BOSS_SLAIN_2', 2)
        before = {name: (self.saves/name).read_bytes() for name in files.FILES}
        preview = migration.import_preview(self.session, raw)
        self.assertEqual({item['key'] for item in preview['rows']}, {'global:'+name for name in files.FILES})
        self.assertTrue(all(item['valid'] and item['source_version'] == files.VERSION for item in preview['rows']))
        keys = [item['key'] for item in preview['rows']]
        result = migration.import_bundle(self.session, raw, {'expected': preview['expected'], 'confirmed': True,
            'selected': keys, 'global_confirmed': True,
            'global_choices': {'global:badges.dat': 'replace', 'global:rankings.dat': 'keep'}})
        self.assertEqual(result['failure_count'], 0)
        self.assertEqual((self.saves/'badges.dat').read_bytes(), original['badges.dat'])
        self.assertEqual((self.saves/'rankings.dat').read_bytes(), before['rankings.dat'])
        # Invalid history can still be exported raw; the compatible package may include only valid files.
        (self.saves/'rankings.dat').write_bytes(b'controlled invalid ranking')
        invalid = self.tick()['history'][0]
        with self.assertRaises(ValueError):
            self.session.global_history_action({**request, 'id': invalid['id']})
        selected_raw, _ = self.session.global_history_action({**request, 'id': invalid['id'], 'selected': ['badges.dat']})
        self.assertEqual([item['key'] for item in migration.import_preview(self.session, selected_raw)['rows']], ['global:badges.dat'])

    def test_slot_restore_and_undo_do_not_restore_or_write_global_files(self):
        self.tick()
        slot_fixtures.BackupDestinationTests.write_save(self, 20)
        captured = self.session.backups.capture(self.saves, 1)
        self.write_globals('BOSS_SLAIN_2', 2)
        slot_fixtures.BackupDestinationTests.write_save(self, 13)
        originals = {name: (self.saves/name).read_bytes() for name in files.FILES}
        self.session.backups.restore(self.saves, {'slot': 1, 'id': captured['id'], 'confirm': '恢复槽位 1'})
        self.assertEqual({name: (self.saves/name).read_bytes() for name in files.FILES}, originals)
        undo = self.session.backups.undo_status(self.saves)[0]
        self.session.backups.undo(self.saves, {'slot': 1, 'id': undo['id'], 'confirm': '撤回槽位 1'})
        self.assertEqual({name: (self.saves/name).read_bytes() for name in files.FILES}, originals)

    def test_http_routes_serve_read_only_history_and_exact_zip_export(self):
        from companion.server import Server
        row = self.tick()['history'][0]
        server = Server(self.session, 0)
        worker = threading.Thread(target=server.serve_forever)
        worker.start()
        try:
            connection = HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            connection.request('GET', '/api/global-history', headers={'Host': f'127.0.0.1:{server.server_port}'})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read())['history'][0]['id'], row['id'])
            connection.close()
            connection = HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            connection.request('POST', '/api/global-history', json.dumps(self.request('portable-export', row,
                selected=['badges.dat'], version=files.VERSION, version_confirmed=True)), headers={
                'Content-Type': 'application/json', 'X-Companion-Token': server.token, 'Origin': server.origin})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.getheader('Content-Type'), 'application/zip')
            with zipfile.ZipFile(BytesIO(response.read())) as archive:
                self.assertIn('denghuo-migration.json', archive.namelist())
                self.assertNotIn('global/rankings.dat', archive.namelist())
            connection.close()
            connection = HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            connection.request('GET', '/global-history.js', headers={'Host': f'127.0.0.1:{server.server_port}'})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertIn(b'openGlobalHistoryPortable', response.read())
            connection.close()
            connection = HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            connection.request('POST', '/api/global-history', json.dumps(self.request('export', row)), headers={
                'Content-Type': 'application/json', 'X-Companion-Token': server.token, 'Origin': server.origin})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.getheader('Content-Type'), 'application/zip')
            with zipfile.ZipFile(BytesIO(response.read())) as archive:
                self.assertEqual(archive.read('global/badges.dat'), (self.saves/'badges.dat').read_bytes())
            connection.close()
        finally:
            server.shutdown(); worker.join(5); server.server_close()
            self.assertFalse(worker.is_alive())


if __name__ == '__main__':
    unittest.main()
