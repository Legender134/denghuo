"""Synthetic global progress only; no installed game or personal save reads."""
import copy
import errno
import gzip
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zipfile import ZipFile

from companion import global_progress as global_files, migration
from companion.backups import BackupManager
from companion.service import Session
from companion.server import Server


def badges(names=('UNLOCK_MAGE', 'VICTORY'), compressed=True):
    raw = json.dumps({'badges': list(names)}, indent=2).encode()
    return gzip.compress(raw, mtime=123456789) if compressed else raw


def rankings():
    record = {'__className': global_files.RECORD_CLASS, 'win': True, 'score': 54321,
              'class': 'MAGE', 'tier': 4, 'level': 28, 'depth': 26, 'ascending': True,
              'custom_seed': '', 'daily': False, 'date': '2026-10-10', 'version': 'v4.0.2',
              'gameID': 'synthetic-record', 'gameData': {'version': 922, 'seed': 987654321}}
    return json.dumps({'records': [record], 'latest': 0, 'total': 75, 'won': 9,
                       'latest_daily': {**record, 'daily': True},
                       'daily_history_dates': [1234567], 'daily_history_scores': [54321]}, indent=2).encode()


class GlobalProgressTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='denghuo-global-progress-'))
        self.source = self.session('source')
        self.target = self.session('target')
        self.originals = {'badges.dat': badges(), 'rankings.dat': rankings()}
        for name, raw in self.originals.items():
            (Path(self.source.settings['save_root']) / name).write_bytes(raw)

    def session(self, name):
        profile, root = self.base / name / 'profile', self.base / name / 'saves'
        profile.mkdir(parents=True); root.mkdir()
        config = profile / 'settings.json'
        # Configure synthetic root BEFORE Session can discover saves.
        config.write_text(json.dumps({'save_root': str(root), 'slot': 1}), encoding='utf-8')
        session = Session(config_path=config)
        session.backups = BackupManager(profile / 'backups', closed_check=lambda: None)
        return session

    def bundle(self, names=None, version='4.0.2'):
        names = names or list(self.originals)
        payload = {'selected': ['global:' + name for name in names], 'global_version': version,
                   'global_version_confirmed': version != 'unknown'}
        preview = migration.export_preview(self.source, payload)
        return migration.export_bundle(self.source, {**payload, 'expected': preview['expected']})[0]

    def payload(self, raw, choices=None, **extra):
        preview = migration.import_preview(self.target, raw)
        keys = [row['key'] for row in preview['rows']]
        return {'selected': keys, 'expected': preview['expected'], 'confirmed': True,
                'global_confirmed': True, 'global_choices': choices or {key: 'replace' for key in keys}, **extra}

    def rewrite(self, raw, change):
        with ZipFile(BytesIO(raw)) as archive:
            contents = {name: archive.read(name) for name in archive.namelist()}
        change(contents)
        manifest = migration.read_json(contents[migration.INDEX])
        manifest['members'] = {name: {'bytes': len(value), 'sha256': migration.checksum(value)}
                               for name, value in contents.items() if name != migration.INDEX}
        contents[migration.INDEX] = migration.encode(manifest)
        return migration._zip(contents)

    def test_explicit_two_file_new_machine_roundtrip_keeps_exact_gzip_and_json_bytes(self):
        raw = self.bundle()
        preview = migration.import_preview(self.target, raw)
        self.assertEqual(len(preview['rows']), 2)
        self.assertTrue(all(row['source_version'] == '4.0.2' and not row['target_exists'] for row in preview['rows']))
        self.assertEqual(preview['rows'][1]['summary']['total'], 75)
        with ZipFile(BytesIO(raw)) as archive:
            self.assertEqual(archive.read('global/badges.dat'), self.originals['badges.dat'])
        result = migration.import_bundle(self.target, raw, self.payload(raw))
        self.assertEqual((result['success_count'], result['failure_count']), (2, 0))
        for name, original in self.originals.items():
            self.assertEqual((Path(self.target.settings['save_root']) / name).read_bytes(), original)
            self.assertEqual((Path(self.source.settings['save_root']) / name).read_bytes(), original)
        self.assertIsNone(global_files.pending(self.target.backups, self.target.settings['save_root']))

    def test_existing_conflicts_default_unresolved_then_keep_or_explicit_replace_with_originals(self):
        before = badges(('UNLOCK_ROGUE',), compressed=False)
        target = Path(self.target.settings['save_root']) / 'badges.dat'; target.write_bytes(before)
        raw = self.bundle(['badges.dat'])
        preview = migration.import_preview(self.target, raw)
        self.assertTrue(preview['rows'][0]['target_exists'])
        with self.assertRaisesRegex(ValueError, '逐份'):
            migration.import_bundle(self.target, raw, self.payload(raw, global_choices={}))
        result = migration.import_bundle(self.target, raw, self.payload(raw, {'global:badges.dat': 'keep'}))
        self.assertEqual(target.read_bytes(), before)
        self.assertFalse(result['results'][0]['saved'])
        result = migration.import_bundle(self.target, raw, self.payload(raw))
        retained = Path(result['results'][0]['retained_directory'])
        self.assertEqual((retained / 'before-badges.dat').read_bytes(), before)
        self.assertEqual(target.read_bytes(), self.originals['badges.dat'])

    def test_global_confirmation_is_distinct_and_no_other_category_written_on_missing_guard(self):
        raw = self.bundle(['badges.dat'])
        payload = self.payload(raw, global_confirmed=False)
        with self.assertRaisesRegex(ValueError, '单独'):
            migration.import_bundle(self.target, raw, payload)
        self.assertFalse((Path(self.target.settings['save_root']) / 'badges.dat').exists())
        self.assertFalse((self.target.backups.scope(self.target.settings['save_root']) / global_files.INDEX).exists())

    def test_game_open_and_offline_original_backup_directory_reject_before_game_write(self):
        raw = self.bundle()
        payload = self.payload(raw)
        def open_game():
            raise ValueError('请关闭游戏')
        self.target.backups.closed_check = open_game
        result = migration.import_bundle(self.target, raw, payload)
        self.assertEqual(result['failure_count'], 2)
        self.assertFalse(list(Path(self.target.settings['save_root']).iterdir()))
        self.target.backups.closed_check = lambda: None
        def offline():
            raise ValueError('备份盘离线')
        self.target.backups.storage_check = offline
        with self.assertRaisesRegex(ValueError, '离线'):
            migration.import_bundle(self.target, raw, payload)
        self.assertFalse(list(Path(self.target.settings['save_root']).iterdir()))

    def test_unknown_or_unsupported_declared_version_cannot_be_imported(self):
        for version in ('unknown', '9.0.0'):
            with self.subTest(version=version):
                raw = self.bundle(version='unknown')
                if version != 'unknown':
                    def change(contents):
                        metadata = json.loads(contents['global-progress.json'])
                        metadata.update(version=version, version_basis='user-declared')
                        contents['global-progress.json'] = migration.encode(metadata)
                    raw = self.rewrite(raw, change)
                preview = migration.import_preview(self.target, raw)
                self.assertTrue(all(not row['valid'] and '版本' in row['error'] for row in preview['rows']))
                result = migration.import_bundle(self.target, raw, self.payload(raw))
                self.assertEqual(result['failure_count'], 2)
                self.assertFalse(list(Path(self.target.settings['save_root']).iterdir()))
        with self.assertRaisesRegex(ValueError, '明确核对'):
            migration.export_preview(self.source, {'selected': ['global:badges.dat'], 'global_version': '4.0.2'})

    def test_changed_source_and_target_even_same_size_and_mtime_invalidate_preview(self):
        selected = ['global:badges.dat']
        payload = {'selected': selected, 'global_version': '4.0.2', 'global_version_confirmed': True}
        source = Path(self.source.settings['save_root']) / 'badges.dat'
        source.write_bytes(badges(('BOSS_SLAIN_1',), compressed=False))
        preview = migration.export_preview(self.source, payload)
        original_stat = source.stat()
        source.write_bytes(badges(('BOSS_SLAIN_2',), compressed=False))
        self.assertEqual(source.stat().st_size, original_stat.st_size)
        os.utime(source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        with self.assertRaisesRegex(ValueError, '变化'):
            migration.export_bundle(self.source, {**payload, 'expected': preview['expected']})
        raw = self.bundle(['badges.dat'])
        target = Path(self.target.settings['save_root']) / 'badges.dat'
        target.write_bytes(badges(('BOSS_SLAIN_1',), compressed=False))
        payload = self.payload(raw)
        original_stat = target.stat()
        changed = badges(('BOSS_SLAIN_2',), compressed=False)
        target.write_bytes(changed); os.utime(target, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        self.assertEqual(target.stat().st_size, original_stat.st_size)
        with self.assertRaisesRegex(ValueError, '变化'):
            migration.import_bundle(self.target, raw, payload)
        self.assertEqual(target.read_bytes(), changed)

    def test_unsafe_names_traversal_and_unsupported_filetypes_never_extract(self):
        raw = self.bundle(['badges.dat'])
        for name in ('global/settings.dat', '../badges.dat', 'global/../badges.dat', '/badges.dat'):
            with self.subTest(name=name):
                def change(contents):
                    contents[name] = contents.pop('global/badges.dat')
                with self.assertRaises(ValueError):
                    migration.import_preview(self.target, self.rewrite(raw, change))
        self.assertFalse(list(Path(self.target.settings['save_root']).iterdir()))

    def test_hardlinked_or_nonregular_known_targets_are_rejected_without_changing_originals(self):
        raw = self.bundle(['badges.dat'])
        root = Path(self.target.settings['save_root'])
        outside = self.base / 'synthetic-outside-original.dat'; outside.write_bytes(badges())
        os.link(outside, root / 'badges.dat')
        with self.assertRaisesRegex(ValueError, '普通文件'):
            migration.import_preview(self.target, raw)
        self.assertEqual(outside.read_bytes(), badges())
        other = self.session('directory-target')
        (Path(other.settings['save_root']) / 'badges.dat').mkdir()
        with self.assertRaisesRegex(ValueError, '普通文件'):
            migration.import_preview(other, raw)

    def test_malformed_bounded_structures_and_gzip_bomb_are_rejected(self):
        invalid = [b'{"badges":[1]}', b'{"badges":[],"version":922}', b'{"badges":[],"badges":[]}',
                   b'{"badges":NaN}', b'\x1f\x8bmalformed', b'[]',
                   gzip.compress(b' ' * (global_files.MAX_BYTES + 1), mtime=0)]
        for data in invalid:
            with self.subTest(data=data[:30]):
                with self.assertRaises(ValueError):
                    global_files.validate('badges.dat', data)
        original = json.loads(rankings())
        for change in (lambda value: value.update(won=True), lambda value: value.update(records=[{}]),
                       lambda value: value.update(latest_daily={}),
                       lambda value: value.update(daily_history_scores=[]),
                       lambda value: value['records'][0].update(win=1),
                       lambda value: value['records'][0].update(__className='evil.Record')):
            value = copy.deepcopy(original); change(value)
            with self.assertRaises(ValueError):
                global_files.validate('rankings.dat', json.dumps(value).encode())
        with patch.object(global_files, 'MAX_BYTES', 10):
            with self.assertRaises(ValueError):
                global_files.validate('badges.dat', badges())

    def test_unknown_local_files_never_scanned_and_malformed_known_file_disabled(self):
        root = Path(self.source.settings['save_root'])
        (root / 'private-unrelated.dat').write_bytes(b'private ignored sentinel')
        (root / 'badges.dat').write_bytes(b'broken')
        rows = migration.status(self.source)['rows']
        self.assertFalse(next(row for row in rows if row['key'] == 'global:badges.dat')['valid'])
        self.assertFalse(any('private' in row['key'] for row in rows))
        with self.assertRaises(ValueError):
            self.bundle(['badges.dat'])

    def test_failure_after_first_publish_restores_both_originals_and_keeps_backups(self):
        before = badges(('UNLOCK_ROGUE',), False)
        path = Path(self.target.settings['save_root']) / 'badges.dat'; path.write_bytes(before)
        raw = self.bundle(); payload = self.payload(raw)
        original_write = global_files._write_new
        def fail_second_publish(path, data):
            if path.name == 'publish-rankings.dat':
                raise OSError('synthetic failure after first publish')
            return original_write(path, data)
        with patch.object(global_files, '_write_new', side_effect=fail_second_publish):
            result = migration.import_bundle(self.target, raw, payload)
        self.assertEqual(result['failure_count'], 2)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse((path.parent / 'rankings.dat').exists())
        self.assertIsNone(global_files.pending(self.target.backups, str(path.parent)))
        retained = list(self.target.backups.scope(str(path.parent)).glob('global-progress-*'))
        self.assertEqual(len([item for item in retained if item.is_dir()]), 1)

    def test_interrupt_requires_explicit_recovery_and_changed_external_bytes_are_never_overwritten(self):
        before = badges(('UNLOCK_ROGUE',), False)
        path = Path(self.target.settings['save_root']) / 'badges.dat'; path.write_bytes(before)
        raw = self.bundle(); payload = self.payload(raw)
        original_write = global_files._write_new
        def interrupt(path, data):
            if path.name == 'publish-rankings.dat':
                raise KeyboardInterrupt('synthetic process interruption')
            return original_write(path, data)
        with patch.object(global_files, '_write_new', side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                migration.import_bundle(self.target, raw, payload)
        self.assertEqual(path.read_bytes(), self.originals['badges.dat'])
        preview = migration.global_recovery_preview(self.target)
        self.assertTrue(preview['pending'])
        self.assertTrue(migration.status(self.target)['global_recovery']['pending'])
        blocked = migration.import_preview(self.target, raw)
        self.assertTrue(all(not row['valid'] for row in blocked['rows']))
        with self.assertRaises(ValueError):
            migration.global_recovery(self.target, {'expected': preview['expected'], 'confirmed': False})
        changed = badges(('HAPPY_END',), False); path.write_bytes(changed)
        with self.assertRaisesRegex(ValueError, '其他程序'):
            migration.global_recovery(self.target, {'expected': preview['expected'], 'confirmed': True})
        self.assertEqual(path.read_bytes(), changed)
        path.write_bytes(self.originals['badges.dat'])
        fresh = migration.global_recovery_preview(self.target)
        result = migration.global_recovery(self.target, {'expected': fresh['expected'], 'confirmed': True})
        self.assertFalse(result['pending'])
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse((path.parent / 'rankings.dat').exists())

    def test_post_preview_target_race_checked_before_any_game_mutation(self):
        raw = self.bundle(); payload = self.payload(raw)
        changed = badges(('HAPPY_END',), False)
        root = Path(self.target.settings['save_root'])
        calls = 0
        def race():
            nonlocal calls
            calls += 1
            if calls == 1:
                (root / 'badges.dat').write_bytes(changed)
        self.target.backups.closed_check = race
        result = migration.import_bundle(self.target, raw, payload)
        self.assertEqual(result['failure_count'], 2)
        self.assertEqual((root / 'badges.dat').read_bytes(), changed)
        self.assertFalse((root / 'rankings.dat').exists())

    def test_real_subprocess_exit_same_volume_existing_and_new_targets_recover_in_new_session(self):
        raw = self.bundle(); package = self.base / 'global-transfer.zip'; package.write_bytes(raw)
        before = badges(('UNLOCK_ROGUE',), False)
        program = '''
import errno, os, sys
from pathlib import Path
from companion import global_progress as files, migration
from companion.backups import BackupManager
from companion.service import Session
config, package = map(Path, sys.argv[1:])
session = Session(config_path=config)
session.backups = BackupManager(config.parent / 'backups', closed_check=lambda: None)
game_root = Path(session.settings['save_root']).resolve()
backup_root = session.backups.scope(session.settings['save_root']).resolve()
original_replace = Path.replace
def same_volume(source, target):
    target = Path(target)
    if source.resolve().is_relative_to(game_root) != target.resolve().is_relative_to(game_root):
        raise OSError(errno.EXDEV, 'synthetic different game/backup volumes')
    return original_replace(source, target)
Path.replace = same_volume
raw = package.read_bytes()
preview = migration.import_preview(session, raw)
original = files._write_new
def abrupt(path, raw):
    if path.name == 'publish-rankings.dat':
        os._exit(17)
    return original(path, raw)
files._write_new = abrupt
selected = [row['key'] for row in preview['rows']]
migration.import_bundle(session, raw, {'selected': selected, 'confirmed': True,
    'expected': preview['expected'], 'global_confirmed': True,
    'global_choices': {key: 'replace' for key in selected}})
'''
        for exists in (True, False):
            with self.subTest(existing_target=exists):
                target = self.session('real-crash-' + str(exists))
                target_root = Path(target.settings['save_root']).resolve()
                if exists:
                    (target_root / 'badges.dat').write_bytes(before)
                result = subprocess.run([sys.executable, '-B', '-c', program, str(target.config_path), str(package)],
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 17, result.stderr)
                self.assertEqual((target_root / 'badges.dat').read_bytes(), self.originals['badges.dat'])
                fresh = Session(config_path=target.config_path)
                fresh.backups = BackupManager(target.config_path.parent / 'backups', closed_check=lambda: None)
                preview = fresh.migration_action('global-recovery-preview')
                self.assertTrue(preview['pending'])
                original_replace = Path.replace
                def same_volume(source, destination):
                    destination = Path(destination)
                    if source.resolve().is_relative_to(target_root) != destination.resolve().is_relative_to(target_root):
                        raise OSError(errno.EXDEV, 'synthetic different game/backup volumes')
                    return original_replace(source, destination)
                with patch.object(Path, 'replace', new=same_volume):
                    recovered = fresh.migration_action('global-recovery', {'expected': preview['expected'], 'confirmed': True})
                if exists:
                    self.assertEqual((target_root / 'badges.dat').read_bytes(), before)
                else:
                    self.assertFalse((target_root / 'badges.dat').exists())
                    self.assertEqual((Path(recovered['temporary_directory']) / 'withdrawn-badges.dat').read_bytes(), self.originals['badges.dat'])
                self.assertFalse((target_root / 'rankings.dat').exists())

    def test_os_lock_rejects_second_assistant_process_and_releases_without_cleanup(self):
        raw = self.bundle(['badges.dat']); payload = self.payload(raw)
        program = '''
import sys
from pathlib import Path
from companion import global_progress as files
from companion.backups import BackupManager
from companion.service import Session
config = Path(sys.argv[1])
session = Session(config_path=config)
manager = BackupManager(config.parent / 'backups', closed_check=lambda: None)
with files._transaction_lock(manager, session.settings['save_root']):
    print('locked', flush=True)
    input()
'''
        process = subprocess.Popen([sys.executable, '-B', '-c', program, str(self.target.config_path)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), 'locked')
            result = migration.import_bundle(self.target, raw, payload)
            self.assertEqual(result['failure_count'], 1)
            self.assertIn('另一个助手', result['results'][0]['error'])
            self.assertFalse((Path(self.target.settings['save_root']) / 'badges.dat').exists())
        finally:
            _, stderr = process.communicate('\n', timeout=10)
        self.assertEqual(process.returncode, 0, stderr)
        result = migration.import_bundle(self.target, raw, self.payload(raw))
        self.assertEqual(result['success_count'], 1)

    def test_interrupted_new_target_recovery_retains_withdrawn_bytes_and_rejects_stale_context(self):
        raw = self.bundle(['badges.dat']); payload = self.payload(raw)
        original_journal = global_files._journal
        def interrupt_complete(manager, root, value):
            if value['state'] == 'complete':
                raise KeyboardInterrupt('synthetic interruption before completing journal')
            return original_journal(manager, root, value)
        with patch.object(global_files, '_journal', side_effect=interrupt_complete):
            with self.assertRaises(KeyboardInterrupt):
                migration.import_bundle(self.target, raw, payload)
        preview = migration.global_recovery_preview(self.target)
        self.target.backup_context = 'synthetic-rebound-context'
        with self.assertRaisesRegex(ValueError, '变化'):
            migration.global_recovery(self.target, {'expected': preview['expected'], 'confirmed': True})
        fresh = migration.global_recovery_preview(self.target)
        result = migration.global_recovery(self.target, {'expected': fresh['expected'], 'confirmed': True})
        self.assertFalse((Path(self.target.settings['save_root']) / 'badges.dat').exists())
        withdrawn = list(Path(result['temporary_directory']).glob('withdrawn-badges.dat'))
        self.assertEqual(len(withdrawn), 1)
        self.assertEqual(withdrawn[0].read_bytes(), self.originals['badges.dat'])

    def test_http_requires_separate_global_confirmation_and_conflict_headers(self):
        raw = self.bundle(['badges.dat'])
        server = Server(self.target)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            headers = {'Content-Type': 'application/zip', 'X-Companion-Token': server.token}
            with urlopen(Request(server.origin + '/api/migration/preview', data=raw, headers=headers)) as response:
                preview = json.load(response)
            headers.update({'X-Companion-Migration-Digest': preview['expected'],
                            'X-Companion-Migration-Selection': json.dumps(['global:badges.dat']),
                            'X-Companion-Migration-Confirmed': 'true'})
            for extras in ({}, {'X-Companion-Migration-Global-Confirmed': 'true'},
                           {'X-Companion-Migration-Global-Confirmed': 'true', 'X-Companion-Migration-Global-Choices': '{"global:badges.dat":"invalid"}'}):
                with self.assertRaises(HTTPError) as failure:
                    urlopen(Request(server.origin + '/api/migration/import', data=raw, headers={**headers, **extras}))
                self.assertEqual(failure.exception.code, 400)
                self.assertFalse((Path(self.target.settings['save_root']) / 'badges.dat').exists())
            headers.update({'X-Companion-Migration-Global-Confirmed': 'true',
                            'X-Companion-Migration-Global-Choices': '{"global:badges.dat":"replace"}'})
            with urlopen(Request(server.origin + '/api/migration/import', data=raw, headers=headers)) as response:
                result = json.load(response)
            self.assertEqual(result['success_count'], 1)
            self.assertEqual((Path(self.target.settings['save_root']) / 'badges.dat').read_bytes(), self.originals['badges.dat'])
            with urlopen(Request(server.origin + '/api/migration/global-recovery-preview', data=b'{}',
                                 headers={'Content-Type': 'application/json', 'X-Companion-Token': server.token})) as response:
                self.assertFalse(json.load(response)['pending'])
        finally:
            server.shutdown(); server.server_close(); thread.join(3)

    def test_cross_volume_backup_destination_never_renames_across_game_and_backup_roots(self):
        raw = self.bundle()
        existing = self.session('cross-existing')
        empty = self.session('cross-empty-interrupted')
        original = badges(('BOSS_SLAIN_1',), compressed=False)
        (Path(existing.settings['save_root']) / 'badges.dat').write_bytes(original)
        sessions = [self.target, existing, empty]
        game_roots = [Path(session.settings['save_root']).resolve() for session in sessions]
        backup_roots = [session.backups.scope(session.settings['save_root']).resolve() for session in sessions]
        original_replace, original_write = Path.replace, global_files._write_new
        game_renames = []
        def volume(path):
            path = path.resolve()
            for index, root in enumerate(game_roots):
                if path.is_relative_to(root):
                    return 'game-' + str(index)
            for index, root in enumerate(backup_roots):
                if path.is_relative_to(root):
                    return 'backup-' + str(index)
            return 'other'
        def replace_same_volume(source, target):
            target = Path(target)
            if volume(source) != volume(target):
                raise OSError(errno.EXDEV, 'synthetic separate game/backup volumes')
            if target.parent.resolve() in game_roots and target.name in global_files.FILES:
                self.assertEqual(source.parent.parent.resolve(), target.parent.resolve())
                self.assertTrue(source.parent.name.startswith('.denghuo-global-progress-'))
                game_renames.append((str(source), str(target)))
            return original_replace(source, target)
        def apply_to(session):
            preview = migration.import_preview(session, raw)
            keys = [row['key'] for row in preview['rows']]
            return migration.import_bundle(session, raw, {'selected': keys, 'expected': preview['expected'],
                'confirmed': True, 'global_confirmed': True, 'global_choices': {key: 'replace' for key in keys}})
        with patch.object(Path, 'replace', new=replace_same_volume):
            self.assertEqual(apply_to(self.target)['success_count'], 2)
            def fail_second(path, data):
                if path.name == 'publish-rankings.dat':
                    raise OSError('synthetic failure after first same-volume publish')
                return original_write(path, data)
            with patch.object(global_files, '_write_new', side_effect=fail_second):
                result = apply_to(existing)
            self.assertEqual(result['failure_count'], 2)
            self.assertEqual((Path(existing.settings['save_root']) / 'badges.dat').read_bytes(), original)
            def interrupt_second(path, data):
                if path.name == 'publish-rankings.dat':
                    raise KeyboardInterrupt('synthetic crash after new target published')
                return original_write(path, data)
            with patch.object(global_files, '_write_new', side_effect=interrupt_second):
                with self.assertRaises(KeyboardInterrupt):
                    apply_to(empty)
            preview = migration.global_recovery_preview(empty)
            recovered = migration.global_recovery(empty, {'expected': preview['expected'], 'confirmed': True})
            self.assertFalse((Path(empty.settings['save_root']) / 'badges.dat').exists())
            self.assertEqual((Path(recovered['temporary_directory']) / 'withdrawn-badges.dat').read_bytes(), self.originals['badges.dat'])
        self.assertGreaterEqual(len(game_renames), 4)

    def test_same_named_or_unsafe_transaction_temporary_is_preserved_and_error_stays_handled(self):
        raw = self.bundle(['badges.dat'])
        original_unlinked = global_files.unlinked
        for unsafe in (False, True):
            with self.subTest(unsafe_path=unsafe):
                target = self.session('temporary-collision-' + str(unsafe))
                root = Path(target.settings['save_root'])
                before = badges(('BOSS_SLAIN_1',), compressed=False)
                (root / 'badges.dat').write_bytes(before)
                temporary = root / ('.denghuo-global-progress-' + '1'*32)
                temporary.mkdir(); sentinel = temporary / 'user-owned-sentinel.txt'; sentinel.write_bytes(b'preserve this exact user collision')
                preview = migration.import_preview(target, raw)
                def check_path(path):
                    if unsafe and Path(path) == temporary:
                        raise ValueError('synthetic reparse path rejected')
                    return original_unlinked(path)
                with patch.object(global_files.uuid, 'uuid4', return_value=SimpleNamespace(hex='1'*32)), \
                        patch.object(global_files, 'unlinked', side_effect=check_path):
                    result = migration.import_bundle(target, raw, {'selected': ['global:badges.dat'], 'expected': preview['expected'],
                        'confirmed': True, 'global_confirmed': True, 'global_choices': {'global:badges.dat': 'replace'}})
                self.assertEqual(result['failure_count'], 1)
                self.assertIn('全局进度导入失败', result['results'][0]['error'])
                self.assertNotIn('UnboundLocalError', result['results'][0]['error'])
                self.assertEqual((root / 'badges.dat').read_bytes(), before)
                self.assertEqual(sentinel.read_bytes(), b'preserve this exact user collision')

    def test_ordinary_slot_capture_and_restore_leave_global_files_untouched(self):
        root = Path(self.source.settings['save_root']); folder = root / 'game1'; folder.mkdir()
        game = {'depth': 2, 'version': 922, 'seed': 1, 'generated_levels': [2],
                'hero': {'class': 'MAGE', 'HP': 20, 'HT': 30, 'STR': 10, 'lvl': 2, 'inventory': [], 'buffs': []}}
        level = {'__className': 'com.shatteredpixel.shatteredpixeldungeon.levels.SewerLevel', 'version': 922,
                 'width': 4, 'height': 4, 'map': [4]*16, 'visited': [False]*16, 'mapped': [False]*16}
        for name, value in [('game.dat', game), ('depth2.dat', {'level': level})]:
            (folder / name).write_bytes(gzip.compress(json.dumps(value).encode(), mtime=0))
        captured = self.source.backups.capture(str(root), 1)
        game['hero']['HP'] = 9
        (folder / 'game.dat').write_bytes(gzip.compress(json.dumps(game).encode(), mtime=0))
        self.source.backups.restore(str(root), {'slot': 1, 'id': captured['id'], 'confirm': '恢复槽位 1'})
        for name, original in self.originals.items():
            self.assertEqual((root / name).read_bytes(), original)
        undo = self.source.backups.undo_status(str(root))[0]
        self.source.backups.undo(str(root), {'slot': 1, 'id': undo['id'], 'confirm': '撤回槽位 1'})
        for name, original in self.originals.items():
            self.assertEqual((root / name).read_bytes(), original)

    def test_portable_equipment_reference_metadata_redacts_text_and_preserves_identity_numbers(self):
        params = {'id_a': 'items.weapon.melee.sword', 'id_b': 'items.weapon.melee.sword',
                  'level_a': 1, 'level_b': 2, 'strength': 14}
        note = {'title': r'提醒 C:\Users\someone\private', 'body': '计算前核对 token=secret-value，保留说明', 'scope': 'specific_item'}
        item = {'id': params['id_a'], 'name': r'剑 D:\private\stats.txt', 'effect_id': 'items.weapon.enchantments.blazing', 'user_note': note}
        saved = self.source.knowledge.save('装备参考', 'equipment', None, params,
            source={'mode': 'manual', 'references': {'a': item, 'b': {**item, 'id': params['id_b'], 'user_note': None}}})
        key = 'plan:' + saved['id']
        preview = migration.export_preview(self.source, {'selected': [key]})
        raw = migration.export_bundle(self.source, {'selected': [key], 'expected': preview['expected']})[0]
        imported_preview = migration.import_preview(self.target, raw)
        result = migration.import_bundle(self.target, raw, {'selected': [key], 'expected': imported_preview['expected'], 'confirmed': True})
        self.assertEqual(result['success_count'], 1)
        imported = self.target.knowledge.status()['plans'][0]
        self.assertEqual(imported['params'], saved['params'])
        reference = imported['origin']['references']['a']
        self.assertEqual(reference['id'], item['id']); self.assertEqual(reference['effect_id'], item['effect_id'])
        self.assertEqual(reference['user_note']['scope'], 'specific_item')
        self.assertIn('[本机路径已省略]', reference['name'])
        self.assertIn('[本机路径已省略]', reference['user_note']['title'])
        self.assertNotIn('secret-value', reference['user_note']['body'])
        self.assertIsNone(imported['origin']['references']['b']['user_note'])
        self.assertEqual(self.source.knowledge.status()['plans'][0]['origin']['references']['a'], item)


if __name__ == '__main__':
    unittest.main()
