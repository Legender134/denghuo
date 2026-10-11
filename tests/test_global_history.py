"""Default automatic global history uses only explicit synthetic game roots."""
import gzip
from http.client import HTTPConnection
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
import zipfile

# Set both profile roots before importing application modules; never discover a real save root.
_profile = tempfile.TemporaryDirectory(prefix='lamp-global-history-profile-')
os.environ['APPDATA'] = str(Path(_profile.name)/'roaming')
os.environ['LOCALAPPDATA'] = str(Path(_profile.name)/'local')

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

    def test_each_status_rechecks_object_bytes_even_when_size_and_mtime_are_unchanged(self):
        row = self.tick()['history'][0]
        original = {name: (self.saves/name).read_bytes() for name in files.FILES}
        object_path = history.folder(self.session.backups, self.saves)/'objects'/(row['files']['badges.dat']['sha256']+'.dat')
        raw = object_path.read_bytes()
        stamp = object_path.stat()
        object_path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
        os.utime(object_path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        status = self.session.global_history_status()
        self.assertEqual(status['health']['state'], 'blocked')
        self.assertEqual(status['history'][0]['files']['badges.dat']['integrity'], 'damaged')
        object_path.write_bytes(raw)
        os.utime(object_path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        self.assertTrue(self.session.global_history_status()['health']['protected'])
        self.assertEqual({name: (self.saves/name).read_bytes() for name in files.FILES}, original)

    def test_storage_change_during_last_manifest_read_is_not_reported_as_valid_history(self):
        row = self.tick()['history'][0]
        manager = self.session.backups
        actual_read, actual_check = files.read, manager.ensure_storage
        changed = [False]
        def read_then_change(path):
            raw = actual_read(path)
            if path.name == row['id'] + '.json':
                changed[0] = True
            return raw
        def check_storage():
            if changed[0]:
                raise ValueError('受控备份存储身份变化')
            return actual_check()
        with patch.object(files, 'read', side_effect=read_then_change), patch.object(manager, 'ensure_storage', side_effect=check_storage):
            with self.assertRaisesRegex(ValueError, '存储身份变化'):
                history.records(manager, self.saves)
        self.assertTrue(self.session.global_history_status()['health']['protected'])

    def test_bounded_confirmation_checks_bytes_instead_of_trusting_manifest_mtime(self):
        old = self.tick()['history'][0]
        self.write_globals(total=2)
        current = self.tick()['history'][0]
        directory = history.folder(self.session.backups, self.saves)
        os.utime(directory/(old['id']+'.json'), (2000000000, 2000000000))
        before = {name: (self.saves/name).read_bytes() for name in files.FILES}
        result = history.capture(self.session.backups, self.saves, deadline=time.monotonic()+3)
        self.assertTrue(result['protected'])
        self.assertEqual(result['snapshot_id'], current['id'])
        path = directory/'objects'/(current['files']['rankings.dat']['sha256']+'.dat')
        raw, stamp = path.read_bytes(), path.stat()
        path.write_bytes(bytes([raw[0] ^ 1])+raw[1:])
        os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        with self.assertRaisesRegex(ValueError, '字节变化'):
            history.capture(self.session.backups, self.saves, deadline=time.monotonic()+3)
        self.assertEqual({name: (self.saves/name).read_bytes() for name in files.FILES}, before)

    def test_bounded_current_copy_confirmation_does_not_hide_older_history_damage(self):
        old = self.tick()['history'][0]
        self.write_globals(total=2)
        current = self.tick()['history'][0]
        directory = history.folder(self.session.backups, self.saves)
        damaged = directory/(old['id']+'.json')
        damaged.write_bytes(b'{preserved damaged older manifest')
        result = history.capture(self.session.backups, self.saves, deadline=time.monotonic()+3)
        self.assertTrue(result['protected'])
        self.assertEqual(result['snapshot_id'], current['id'])
        self.assertEqual(history.raw_files(self.session.backups, self.saves, current),
                         {name: (self.saves/name).read_bytes() for name in files.FILES})
        status = self.session.global_history_status()
        self.assertEqual(status['health']['state'], 'blocked')
        self.assertEqual([row['id'] for row in status['damaged_rows']], [old['id']])
        self.assertEqual(damaged.read_bytes(), b'{preserved damaged older manifest')

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

    def test_real_512_limit_local_retention_restores_quota_and_keeps_archive_usable(self):
        from companion import global_history_maintenance as maintenance
        self.tick()
        first = history.records(self.session.backups, self.saves)[0]
        directory = history.folder(self.session.backups, self.saves)
        template = {key: first[key] for key in ('format', 'kind', 'library', 'sequence', 'time', 'files')}
        for sequence in range(2, history.MAX_SNAPSHOTS+1):
            raw = files.encode({**template, 'sequence': sequence, 'time': self.now+sequence})
            (directory/(files.digest(raw)+'.json')).write_bytes(raw)
        originals = slot_fixtures.BackupDestinationTests.files(directory)
        self.write_globals('BOSS_SLAIN_2', 2)
        with self.assertRaisesRegex(ValueError, '512份'):
            history.capture(self.session.backups, self.saves)
        preview = history.maintenance_preview(self.session.backups, self.saves, self.saves)
        self.assertEqual(preview['records'], 512)
        self.assertEqual(preview['disk_bytes_released'], 0)
        self.assertEqual(len(preview['originals']), 514)
        result = history.maintain(self.session.backups, self.saves, self.saves,
            {'expected': preview['expected'], 'confirmed': True}, lambda: None)
        self.assertTrue(result['health']['protected'])
        self.assertEqual(result['active_after']['count'], 1)
        self.assertEqual(result['disk_bytes_released'], 0)
        archived = maintenance.archive_directory(self.session.backups, self.saves, result['archive_id'])
        self.assertEqual(slot_fixtures.BackupDestinationTests.files(archived), originals)
        status = history.status(self.session.backups, self.saves, self.saves)
        self.assertEqual(status['storage']['active_count'], 1)
        self.assertEqual(status['storage']['archived_count'], 512)
        self.assertGreater(status['storage']['total_local_bytes'], sum(map(len, originals.values())))
        archive_view = history.status(self.session.backups, self.saves, self.saves, result['archive_id'])
        self.assertEqual(len(archive_view['history']), 512)
        self.assertEqual(archive_view['storage']['active_count'], 1)
        raw, _ = history.archive_export(self.session.backups, self.saves, result['archive_id'])
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            for name, value in originals.items():
                self.assertEqual(archive.read('history/'+name), value)
        raw, _ = history.export(self.session.backups, self.saves, first['id'], ['rankings.dat'], result['archive_id'])
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            self.assertIn('global/rankings.dat', archive.namelist())
        view = history.preview(self.session.backups, self.saves, self.saves, first['id'],
                               ['rankings.dat'], result['archive_id'])
        history.restore(self.session.backups, self.saves, self.saves, {'id': first['id'],
            'selected': ['rankings.dat'], 'archive': result['archive_id'], 'expected': view['expected'],
            'confirmed': True, 'version': files.VERSION, 'version_confirmed': True,
            'choices': {'rankings.dat': 'replace'}}, lambda: None)
        self.assertEqual((self.saves/'rankings.dat').read_bytes(),
                         history.raw_files(self.session.backups, self.saves, first, ['rankings.dat'], result['archive_id'])['rankings.dat'])
        self.assertEqual(slot_fixtures.BackupDestinationTests.files(archived), originals)
        self.assertFalse(list(self.saves.glob('game*')))

    def test_damaged_manifest_is_visible_without_blocking_healthy_rows_and_rebuild_retains_it(self):
        first = self.tick()['history'][0]
        self.write_globals('BOSS_SLAIN_2', 2)
        second = self.tick()['history'][0]
        directory = history.folder(self.session.backups, self.saves)
        damaged_raw = b'{original manifest deliberately damaged'
        (directory/(first['id']+'.json')).write_bytes(damaged_raw)
        status = self.session.global_history_status()
        self.assertEqual([row['id'] for row in status['history']], [second['id']])
        self.assertEqual(status['damaged_rows'][0]['id'], first['id'])
        self.assertFalse(status['health']['protected'])
        raw, _ = history.export(self.session.backups, self.saves, second['id'])
        self.assertTrue(zipfile.is_zipfile(BytesIO(raw)))
        raw, _ = history.damaged_export(self.session.backups, self.saves, first['id'])
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            self.assertEqual(archive.read('damaged-manifest/'+first['id']+'.json'), damaged_raw)
        with self.assertRaisesRegex(ValueError, '损坏清单'):
            history.capture(self.session.backups, self.saves)
        view = history.maintenance_preview(self.session.backups, self.saves, self.saves)
        self.assertGreater(view['damaged_count'], 0)
        result = history.maintain(self.session.backups, self.saves, self.saves,
            {'expected': view['expected'], 'confirmed': True}, lambda: None)
        self.assertTrue(result['health']['protected'])
        retained = history.status(self.session.backups, self.saves, self.saves, result['archive_id'])
        self.assertEqual(retained['damaged_rows'][0]['sha256'], files.digest(damaged_raw))
        raw, _ = history.damaged_export(self.session.backups, self.saves, first['id'], result['archive_id'])
        self.assertTrue(zipfile.is_zipfile(BytesIO(raw)))

    def test_selected_healthy_rankings_survives_bad_badge_object_for_all_actions(self):
        from companion import migration
        row = self.tick()['history'][0]
        original = {name: (self.saves/name).read_bytes() for name in files.FILES}
        object_path = history.folder(self.session.backups, self.saves)/'objects'/(row['files']['badges.dat']['sha256']+'.dat')
        damaged = b'bad badge object retained exactly'
        object_path.write_bytes(damaged)
        self.write_globals('BOSS_SLAIN_2', 2)
        current_badges = (self.saves/'badges.dat').read_bytes()
        status = self.session.global_history_status()
        actual = status['history'][0]['files']
        self.assertFalse(actual['badges.dat']['valid'])
        self.assertEqual(actual['badges.dat']['integrity'], 'damaged')
        self.assertTrue(actual['rankings.dat']['valid'])
        with self.assertRaisesRegex(ValueError, '字节变化'):
            history.export(self.session.backups, self.saves, row['id'])
        raw, _ = self.session.global_history_action(self.request('export', row, selected=['rankings.dat']))
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            self.assertEqual(archive.read('global/rankings.dat'), original['rankings.dat'])
            self.assertNotIn('global/badges.dat', archive.namelist())
        raw, _ = self.session.global_history_action(self.request('portable-export', row,
            selected=['rankings.dat'], version=files.VERSION, version_confirmed=True))
        self.assertEqual([entry['key'] for entry in migration.import_preview(self.session, raw)['rows']], ['global:rankings.dat'])
        view = self.session.global_history_action(self.request('restore-preview', row, selected=['rankings.dat']))
        self.session.global_history_action(self.request('restore', row, selected=['rankings.dat'],
            expected=view['expected'], confirmed=True, version=files.VERSION, version_confirmed=True,
            choices={'rankings.dat': 'replace'}))
        self.assertEqual((self.saves/'rankings.dat').read_bytes(), original['rankings.dat'])
        self.assertEqual((self.saves/'badges.dat').read_bytes(), current_badges)
        self.assertEqual(object_path.read_bytes(), damaged)
        with self.assertRaisesRegex(ValueError, '字节变化'):
            history.preview(self.session.backups, self.saves, self.saves, row['id'], ['badges.dat'])

    def test_maintenance_confirmation_binds_all_originals_current_source_and_directory_identity(self):
        self.tick()
        manager = self.session.backups
        view = history.maintenance_preview(manager, self.saves, self.saves)
        self.write_globals('BOSS_SLAIN_2', 2)
        with self.assertRaisesRegex(ValueError, '重新预览'):
            history.maintain(manager, self.saves, self.saves, {'expected': view['expected'], 'confirmed': True}, lambda: None)
        view = history.maintenance_preview(manager, self.saves, self.saves)
        directory = history.folder(manager, self.saves)
        object_path = next((directory/'objects').iterdir())
        object_path.write_bytes(b'externally changed original')
        with self.assertRaisesRegex(ValueError, '重新预览'):
            history.maintain(manager, self.saves, self.saves, {'expected': view['expected'], 'confirmed': True}, lambda: None)
        view = history.maintenance_preview(manager, self.saves, self.saves)
        original_identity = directory.stat().st_ino
        retained = directory.with_name('retained-test-original')
        directory.rename(retained)
        directory.mkdir()
        self.assertNotEqual(directory.stat().st_ino, original_identity)
        with self.assertRaises(ValueError):
            history.maintain(manager, self.saves, self.saves, {'expected': view['expected'], 'confirmed': True}, lambda: None)
        self.assertEqual((retained/'objects'/object_path.name).read_bytes(), b'externally changed original')

    def test_capture_deadline_and_pending_restore_are_checked_before_empty_source(self):
        import time
        manager = self.session.backups
        with self.assertRaises(TimeoutError):
            history.capture(manager, self.saves, deadline=time.monotonic()-1)
        for path in self.saves.iterdir():
            path.unlink()
        with patch.object(files, 'pending', return_value={'state': 'pending'}):
            with self.assertRaisesRegex(ValueError, '未完成的全局进度恢复'):
                history.capture(manager, self.saves)
            self.assertEqual(history.status(manager, self.saves, self.saves)['health']['state'], 'blocked')

    def test_completed_archives_survive_actual_destination_copy_and_need_fresh_restore_preview(self):
        first = self.tick()['history'][0]
        source_bytes = {name: (self.saves/name).read_bytes() for name in files.FILES}
        request = {'library': first['library'], 'context': self.session.backup_context}
        preview = self.session.global_history_action({**request, 'action': 'maintenance-preview'})
        result = self.session.global_history_action({**request, 'action': 'maintenance',
            'expected': preview['expected'], 'confirmed': True})
        self.assertTrue(result['health']['protected'])
        archive_id = result['archive_id']
        old_directory = history._directory(self.session.backups, self.saves, archive_id)
        originals = slot_fixtures.BackupDestinationTests.files(old_directory)
        old_preview = self.session.global_history_action({**request, 'action': 'restore-preview',
            'id': first['id'], 'archive': archive_id, 'selected': ['rankings.dat']})
        target = self.base/'copied-backup-disk'
        target.mkdir()
        destination_request = {'backup_root': str(target), 'context': self.session.backup_context,
                               'expected_settings_revision': self.session.settings_revision}
        destination_preview = self.session.backup_destination_action({**destination_request, 'action': 'preview'})
        self.session.backup_destination_action({**destination_request, 'action': 'apply',
            'expected': destination_preview['expected'], 'confirmed': True})
        self.session.backups.closed_check = Mock()
        request['context'] = self.session.backup_context
        current_directory = history._directory(self.session.backups, self.saves, archive_id)
        self.assertNotEqual(current_directory.stat().st_ino, old_directory.stat().st_ino)
        status = self.session.global_history_status(first['library'], archive=archive_id)
        self.assertEqual(status['history'][0]['id'], first['id'])
        self.assertEqual(slot_fixtures.BackupDestinationTests.files(old_directory), originals)
        self.assertEqual(slot_fixtures.BackupDestinationTests.files(current_directory), originals)
        raw, _ = self.session.global_history_action({**request, 'action': 'archive-export', 'archive': archive_id})
        self.assertTrue(zipfile.is_zipfile(BytesIO(raw)))
        new_preview = self.session.global_history_action({**request, 'action': 'restore-preview',
            'id': first['id'], 'archive': archive_id, 'selected': ['rankings.dat']})
        self.assertNotEqual(old_preview['expected'], new_preview['expected'])
        self.write_globals('BOSS_SLAIN_2', 2)
        with self.assertRaisesRegex(ValueError, '已变化'):
            self.session.global_history_action({**request, 'action': 'restore', 'id': first['id'],
                'archive': archive_id, 'selected': ['rankings.dat'], 'expected': old_preview['expected'],
                'confirmed': True, 'version': files.VERSION, 'version_confirmed': True,
                'choices': {'rankings.dat': 'replace'}})
        new_preview = self.session.global_history_action({**request, 'action': 'restore-preview',
            'id': first['id'], 'archive': archive_id, 'selected': ['rankings.dat']})
        self.session.global_history_action({**request, 'action': 'restore', 'id': first['id'],
            'archive': archive_id, 'selected': ['rankings.dat'], 'expected': new_preview['expected'],
            'confirmed': True, 'version': files.VERSION, 'version_confirmed': True,
            'choices': {'rankings.dat': 'replace'}})
        self.assertEqual((self.saves/'rankings.dat').read_bytes(), source_bytes['rankings.dat'])
        self.assertEqual(slot_fixtures.BackupDestinationTests.files(current_directory), originals)

    def test_bad_archive_receipt_is_isolated_from_active_history_and_other_archives(self):
        from companion import global_history_maintenance as maintenance
        self.tick()
        archive_ids = []
        for _ in range(2):
            view = history.maintenance_preview(self.session.backups, self.saves, self.saves)
            result = history.maintain(self.session.backups, self.saves, self.saves,
                {'expected': view['expected'], 'confirmed': True}, lambda: None)
            archive_ids.append(result['archive_id'])
        bad_journal = self.session.backups.scope(self.saves)/maintenance.ARCHIVES/archive_ids[0]/'journal.json'
        bad_journal.write_bytes(b'original broken journal bytes')
        status = self.session.global_history_status()
        self.assertTrue(status['health']['protected'])
        self.assertEqual({row['state'] for row in status['archives']}, {'completed', 'damaged'})
        damaged = next(row for row in status['archives'] if row['state'] == 'damaged')
        self.assertIsNone(damaged['count'])
        self.assertIsNone(damaged['bytes'])
        self.assertFalse(status['storage']['archived_count_complete'])
        self.assertGreater(status['storage']['total_local_bytes'], status['storage']['active_bytes'])
        healthy = self.session.global_history_status(archive=archive_ids[1])
        self.assertEqual(len(healthy['history']), 1)
        raw, _ = history.archive_export(self.session.backups, self.saves, archive_ids[1])
        self.assertTrue(zipfile.is_zipfile(BytesIO(raw)))
        with self.assertRaises(ValueError):
            history.archive_export(self.session.backups, self.saves, archive_ids[0])
        self.assertEqual(bad_journal.read_bytes(), b'original broken journal bytes')

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
