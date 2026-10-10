"""Independent local destinations keep byte originals and require fresh confirmation."""
import gzip
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from companion import backup_destination as destinations
from companion.backup_libraries import catalog
from companion.service import Session, SettingsConflict, validate_settings


class BackupDestinationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='denghuo-destination-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.saves = self.base / 'game'
        self.saves.mkdir()
        self.config = self.base / 'assistant' / 'settings.json'
        self.config.parent.mkdir()
        self.config.write_text(json.dumps({'save_root': str(self.saves), 'slot': 1}), encoding='utf-8')
        self.session = Session(self.config)
        self.now = 1700000100
        self.session.backups.clock = lambda: self.now
        self.session.backups.closed_check = lambda: None
        self.target = self.base / '独立本地卷'
        self.target.mkdir()
        self.write_save()

    def write_save(self, hp=20, root=None):
        root = root or self.saves
        folder = root / 'game1'
        folder.mkdir(parents=True, exist_ok=True)
        game = {'depth': 2, 'branch': 0, 'version': 912, 'seed': 11, 'generated_levels': [2],
                'hero': {'class': 'MAGE', 'HP': hp, 'HT': 30, 'STR': 10, 'lvl': 2,
                         'inventory': [], 'buffs': []}}
        level = {'__className': 'com.shatteredpixel.shatteredpixeldungeon.levels.SewerLevel',
                 'version': 912, 'width': 4, 'height': 4, 'map': [4] * 16,
                 'visited': [False] * 16, 'mapped': [False] * 16}
        for name, value in (('game.dat', game), ('depth2.dat', {'level': level})):
            path = folder / name
            path.write_bytes(gzip.compress(json.dumps(value).encode(), mtime=0))
            os.utime(path, (1700000000 + hp, 1700000000 + hp))

    def capture(self, hp=20, root=None):
        self.now += 20
        root = root or self.saves
        self.write_save(hp, root)
        return self.session.backups.capture(root, 1)

    @staticmethod
    def files(root):
        return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}

    def request(self, action='preview', target=None, **extra):
        return {'action': action, 'backup_root': str(self.target if target is None else target),
                'expected_settings_revision': self.session.settings_revision,
                'context': self.session.backup_context, **extra}

    def preview(self, target=None):
        return self.session.backup_destination_action(self.request(target=target))

    def switch(self, target=None):
        preview = self.preview(target)
        return self.session.backup_destination_action(self.request('apply', target,
            expected=preview['expected'], confirmed=True))

    def test_zero_configuration_default_and_explicit_workflow_validation(self):
        self.assertEqual(self.session.settings['backup_root'], '')
        self.assertEqual(self.session.backups.directory, self.config.parent / 'backups')
        before = self.config.read_bytes()
        with self.assertRaisesRegex(ValueError, '预览'):
            self.session.update_settings({'backup_root': str(self.target)})
        for value in ('relative', '../parent', '\\\\server\\share', '//server/share', 1, [], None, 'a\x00b'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_settings({'backup_root': value})
        for payload in (None, [], {'action': {}}, self.request(unknown=True),
                        {'action': 'preview', 'backup_root': str(self.target)}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.session.backup_destination_action(payload)
        preview = self.preview()
        with self.assertRaisesRegex(ValueError, '明确确认'):
            self.session.backup_destination_action(self.request('apply', expected=preview['expected'], confirmed=1))
        self.assertEqual(self.config.read_bytes(), before)
        self.assertEqual(self.files(self.target), {})

    def test_switch_copies_all_libraries_and_retained_evidence_and_resumes_after_restart(self):
        first = self.capture(20)
        self.capture(19)
        manager = self.session.backups
        manager.remove(self.saves, {**first, 'confirm': '移出备份 1'})
        old = self.base / 'older-game'
        self.capture(18, old)
        quarantine = manager.directory.parent / 'backup-quarantine' / manager.scope(self.saves).name
        quarantine.mkdir(parents=True)
        (quarantine / 'damaged-original.zip').write_bytes(b'damaged bytes retained for examination')
        note = self.target / 'personal-notes.txt'
        note.write_bytes(b'User-owned unrelated original')
        source = self.files(self.config.parent)
        game = self.files(self.saves)
        target = self.files(self.target)
        preview = self.preview()
        self.assertEqual(preview['library_count'], 2)
        self.assertEqual(preview['verified_archives'], 2)
        self.assertEqual(self.files(self.target), target)
        revision, context = self.session.settings_revision, self.session.backup_context
        receipt = self.session.backup_destination_action(self.request('apply', expected=preview['expected'], confirmed=True))
        self.assertTrue(receipt['copied'])
        self.assertEqual(receipt['directory'], str(self.target / 'backups'))
        self.assertNotEqual(context, receipt['context'])
        self.assertNotEqual(revision, receipt['settings_revision'])
        for name, raw in source.items():
            if name.startswith(destinations.CONTAINERS):
                self.assertEqual((self.config.parent / name).read_bytes(), raw)
                self.assertEqual((self.target / name).read_bytes(), raw)
        self.assertEqual(note.read_bytes(), b'User-owned unrelated original')
        self.assertEqual(self.files(self.saves), game)
        self.assertEqual(len(catalog(self.session.backups, self.saves)['libraries']), 2)
        loaded = Session(self.config)
        self.assertEqual(loaded.settings['backup_root'], str(self.target))
        self.assertEqual(loaded.backups.directory, self.target / 'backups')
        self.assertTrue(loaded.backup_destination_status()['available'])
        old_source = destinations._tree(self.config.parent)
        self.write_save(17)
        loaded.backups.tick(self.saves, force=True)
        self.assertEqual(len(loaded.backups.history(self.saves)), 2)
        self.assertEqual(destinations._tree(self.config.parent), old_source)

    def test_return_to_populated_default_unions_history_and_preserves_target_metadata(self):
        first = self.capture(20)
        original = self.session.backups.selected(self.saves, first)
        self.session.backups.manage(self.saves, {**first, 'label': '原目的地名称', 'locked': True,
            'expected_metadata_revision': original['metadata_revision']})
        default_metadata = self.session.backups.selected(self.saves, first)
        self.switch()
        current = self.session.backups.selected(self.saves, first)
        self.session.backups.manage(self.saves, {**first, 'label': '另一目的地名称', 'locked': False,
            'expected_metadata_revision': current['metadata_revision']})
        second = self.capture(19)
        source = destinations._tree(self.target)
        preview = self.preview('')
        self.assertIn(self.session.backups.scope(self.saves).name + '/history.json',
                      ' '.join(preview['merged_indexes']))
        receipt = self.session.backup_destination_action(self.request('apply', '',
            expected=preview['expected'], confirmed=True))
        self.assertEqual(self.session.settings['backup_root'], '')
        self.assertEqual(self.session.backups.directory, self.config.parent / 'backups')
        rows = self.session.backups.history(self.saves)
        self.assertEqual({r['id'] for r in rows}, {first['id'], second['id']})
        merged = self.session.backups.selected(self.saves, first)
        self.assertEqual((merged['label'], merged['locked']), ('原目的地名称', True))
        self.assertEqual(merged['metadata_revision'], default_metadata['metadata_revision'])
        self.assertEqual(destinations._tree(self.target), source)
        preserved = Path(receipt['preserved_target_directory'])
        raw = json.loads((preserved / 'backups' / self.session.backups.scope(self.saves).name / 'history.json').read_text())
        self.assertEqual([r['id'] for r in raw], [first['id']])

    def test_settings_context_target_and_same_stat_content_changes_invalidate_confirmation(self):
        row = self.capture()
        preview = self.preview()
        payload = self.request('apply', expected=preview['expected'], confirmed=True)
        with self.assertRaises(SettingsConflict):
            self.session.backup_destination_action({**payload, 'expected_settings_revision': 'old'})
        with self.assertRaisesRegex(ValueError, '连接已变化'):
            self.session.backup_destination_action({**payload, 'context': 'old'})
        other = self.base / 'different-target'
        other.mkdir()
        with self.assertRaisesRegex(ValueError, '已变化'):
            self.session.backup_destination_action({**payload, 'backup_root': str(other)})
        index = self.session.backups.scope(self.saves) / 'history.json'
        stamp = index.stat()
        raw = index.read_bytes()
        self.assertIn(b'"label": ""', raw)
        changed = raw.replace(b'"label": ""', b'"label":"x"')
        self.assertEqual(len(changed), len(raw))
        index.write_bytes(changed)
        os.utime(index, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        before = self.config.read_bytes()
        with self.assertRaisesRegex(ValueError, '已变化'):
            self.session.backup_destination_action(payload)
        self.assertEqual(self.config.read_bytes(), before)
        self.assertEqual(self.files(self.target), {})
        self.assertEqual(self.session.backups.history(self.saves)[0]['id'], row['id'])

    def test_target_content_change_and_unknown_conflict_are_never_overwritten(self):
        row = self.capture()
        self.switch()
        self.capture(19)
        preview = self.preview('')
        index = self.config.parent / 'backups' / self.session.backups.scope(self.saves).name / 'history.json'
        data = json.loads(index.read_text())
        data[0]['label'] = 'target changed after preview'
        index.write_text(json.dumps(data), encoding='utf-8')
        before = self.files(self.config.parent / 'backups')
        with self.assertRaisesRegex(ValueError, '已变化'):
            self.session.backup_destination_action(self.request('apply', '', expected=preview['expected'], confirmed=True))
        self.assertEqual(self.files(self.config.parent / 'backups'), before)
        name = self.session.backups.scope(self.saves).name
        (self.target / 'backups' / name / 'unrecognized.note').write_bytes(b'source-owned')
        (self.config.parent / 'backups' / name / 'unrecognized.note').write_bytes(b'target-owned')
        with self.assertRaisesRegex(ValueError, '已有不同内容'):
            self.preview('')
        self.assertEqual((self.config.parent / 'backups' / name / 'unrecognized.note').read_bytes(), b'target-owned')

    def test_corrupt_active_archive_missing_space_and_unwritable_target_fail_before_copy(self):
        row = self.capture()
        with patch('companion.backup_destination.os.access', return_value=False):
            with self.assertRaisesRegex(ValueError, '不可写'):
                self.preview()
        with patch('companion.backup_destination.shutil.disk_usage', return_value=type('Usage', (), {'free': 0})()):
            with self.assertRaisesRegex(ValueError, '空间不足'):
                self.preview()
        path = self.session.backups.scope(self.saves) / (row['id'] + '.zip')
        path.write_bytes(b'damaged original')
        with self.assertRaises(ValueError):
            self.preview()
        self.assertEqual(path.read_bytes(), b'damaged original')
        self.assertEqual(self.files(self.target), {})

    def test_copy_failure_and_configuration_failure_keep_manager_and_all_target_originals(self):
        self.capture()
        original_manager = self.session.backups
        config = self.config.read_bytes()
        source = destinations._tree(self.config.parent)
        preview = self.preview()
        with patch('companion.backup_destination._copy_file', side_effect=OSError('controlled copy failure')):
            with self.assertRaisesRegex(OSError, 'controlled copy failure'):
                self.session.backup_destination_action(self.request('apply', expected=preview['expected'], confirmed=True))
        self.assertIs(self.session.backups, original_manager)
        self.assertEqual(self.config.read_bytes(), config)
        self.assertEqual(destinations._tree(self.target)['files'], {})
        self.assertEqual(destinations._tree(self.config.parent), source)
        actual_replace = Path.replace
        def replace(path, target):
            if Path(target) == self.config:
                raise OSError('controlled config failure')
            return actual_replace(path, target)
        preview = self.preview()
        with patch.object(Path, 'replace', replace):
            with self.assertRaisesRegex(OSError, 'controlled config failure'):
                self.session.backup_destination_action(self.request('apply', expected=preview['expected'], confirmed=True))
        self.assertIs(self.session.backups, original_manager)
        self.assertEqual(self.config.read_bytes(), config)
        self.assertEqual(destinations._tree(self.target)['files'], {})
        self.assertEqual(destinations._tree(self.config.parent), source)
        self.assertTrue(list(self.target.glob('.denghuo-destination-stage-*')))
        # A failed copy's stages are outside managed containers and do not block retry.
        self.assertTrue(self.switch()['ok'])

    def test_disconnected_media_and_empty_mountpoint_stay_blocked_without_recreation(self):
        self.capture()
        self.switch()
        original_default = destinations._tree(self.config.parent)
        offline = self.base / 'offline-disk-original'
        self.target.rename(offline)
        self.session.backups.tick(self.saves)
        self.assertFalse(self.target.exists())
        self.assertEqual(self.session.backup_health()['state'], 'blocked')
        self.assertFalse(self.session.backup_status()['records_available'])
        self.assertEqual(self.session.settings['backup_root'], str(self.target))
        self.assertEqual(destinations._tree(self.config.parent), original_default)
        # Simulate Linux retaining the empty mountpoint after unmounting the media.
        self.target.mkdir()
        loaded = Session(self.config)
        self.assertFalse(loaded.backup_destination_status()['available'])
        loaded.backups.tick(self.saves)
        with self.assertRaisesRegex(ValueError, '身份'):
            loaded.backups.set_enabled(True)
        with self.assertRaisesRegex(ValueError, '身份'):
            loaded.backups.capture(self.saves, 1)
        final = loaded.prepare_shutdown()
        self.assertFalse(final['ok'])
        self.assertEqual(self.files(self.target), {})
        self.assertEqual(loaded.settings['backup_root'], str(self.target))

    def test_reconnect_original_media_resumes_and_wrong_marker_does_not(self):
        self.capture()
        self.switch()
        marker = self.target / destinations.MARKER
        original = marker.read_bytes()
        marker.write_text(json.dumps({'format': 1, 'id': 'f' * 32}), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '身份'):
            self.session.backups.tick(self.saves, force=True)
        self.assertFalse(self.session.backup_destination_status()['available'])
        marker.write_bytes(original)
        self.write_save(18)
        self.session.backups.tick(self.saves, force=True)
        self.assertTrue(self.session.backup_destination_status()['available'])
        self.assertEqual(len(self.session.backups.history(self.saves)), 2)

    def test_restart_with_offline_paused_media_reloads_pause_before_monitoring_resumes(self):
        self.capture()
        self.session.backups.set_enabled(False)
        self.switch()
        offline = self.base / 'paused-offline-original'
        self.target.rename(offline)
        loaded = Session(self.config)
        self.assertFalse(loaded.backup_destination_status()['available'])
        offline.rename(self.target)
        original = destinations._tree(self.target)
        self.write_save(19)
        loaded.backups.tick(self.saves)
        self.assertFalse(loaded.backups.enabled)
        self.assertEqual(loaded.backup_health()['state'], 'paused')
        self.assertEqual(loaded.backup_health()['error'], '')
        self.assertEqual(destinations._tree(self.target), original)
        self.target.rename(offline)
        ending = Session(self.config)
        offline.rename(self.target)
        self.assertEqual(ending.prepare_shutdown()['state'], 'paused')
        self.assertEqual(destinations._tree(self.target), original)

    def test_explicit_offline_fresh_history_never_reads_or_recreates_old_mountpoint(self):
        old = self.capture()
        self.switch()
        old_registry = destinations.registry(self.config)
        offline = self.base / 'offline-original'
        self.target.rename(offline)
        originals = self.files(offline)
        # A leftover mountpoint may contain unrelated local files: never scan it.
        wrong = self.target / 'backups' / 'personal-file.txt'
        wrong.parent.mkdir(parents=True)
        wrong.write_bytes(b'Unrelated data under empty mountpoint')
        wrong_originals = self.files(self.target)
        replacement = self.base / 'fresh-local-disk'
        replacement.mkdir()
        with self.assertRaisesRegex(ValueError, '不可用|身份'):
            self.preview(replacement)
        actual_tree = destinations._tree
        def tree(base):
            if base == self.target:
                raise AssertionError('offline mountpoint must never be traversed')
            return actual_tree(base)
        with patch('companion.backup_destination._tree', side_effect=tree):
            preview = self.session.backup_destination_action(self.request(target=replacement, start_new=True))
            self.assertTrue(preview['history_not_copied'])
            self.assertTrue(preview['source_unavailable'])
            self.assertEqual((preview['bytes'], preview['file_count'], preview['verified_archives']), (0, 0, 0))
            receipt = self.session.backup_destination_action(self.request('apply', replacement,
                expected=preview['expected'], confirmed=True, start_new=True))
        self.assertFalse(receipt['copied'])
        self.assertTrue(receipt['history_not_copied'])
        self.assertEqual(self.files(self.target), wrong_originals)
        self.assertEqual(self.files(offline), originals)
        self.assertEqual(destinations.registry(self.config)[str(self.target)], old_registry[str(self.target)])
        self.write_save(19)
        self.session.backups.tick(self.saves, force=True)
        rows = self.session.backups.history(self.saves)
        self.assertEqual(len(rows), 1)
        self.assertNotEqual(rows[0]['id'], old['id'])
        # Returning explicitly after the old disk reconnects unions both histories.
        wrong.rename(self.target / 'personal-file-retained.txt')
        self.target.rename(self.base / 'empty-mountpoint-original')
        offline.rename(self.target)
        self.switch()
        self.assertEqual(len(self.session.backups.history(self.saves)), 2)

    def test_offline_fresh_history_requires_boolean_flag_and_repreview_after_reconnect(self):
        self.capture()
        with self.assertRaisesRegex(ValueError, '仍可用'):
            self.session.backup_destination_action(self.request(start_new=True))
        with self.assertRaisesRegex(ValueError, '格式不正确'):
            self.session.backup_destination_action(self.request(start_new='true'))
        self.switch()
        offline = self.base / 'offline-until-confirmation'
        self.target.rename(offline)
        replacement = self.base / 'new-location'
        replacement.mkdir()
        preview = self.session.backup_destination_action(self.request(target=replacement, start_new=True))
        with self.assertRaisesRegex(ValueError, '不可用'):
            self.session.backup_destination_action(self.request('apply', replacement, expected=preview['expected'], confirmed=True))
        offline.rename(self.target)
        with self.assertRaisesRegex(ValueError, '仍可用'):
            self.session.backup_destination_action(self.request('apply', replacement,
                expected=preview['expected'], confirmed=True, start_new=True))
        self.assertEqual(self.files(replacement), {})

    def test_populated_target_configuration_failure_restores_exact_original_tree(self):
        self.capture()
        self.switch()
        self.capture(19)
        default = destinations._tree(self.config.parent)
        current = destinations._tree(self.target)
        manager, config = self.session.backups, self.config.read_bytes()
        preview = self.preview('')
        actual = Path.replace
        def replace(path, target):
            if Path(target) == self.config:
                raise OSError('controlled config failure')
            return actual(path, target)
        with patch.object(Path, 'replace', replace):
            with self.assertRaisesRegex(OSError, 'controlled config failure'):
                self.session.backup_destination_action(self.request('apply', '', expected=preview['expected'], confirmed=True))
        self.assertIs(self.session.backups, manager)
        self.assertEqual(self.config.read_bytes(), config)
        self.assertEqual(destinations._tree(self.config.parent), default)
        self.assertEqual(destinations._tree(self.target), current)

    def test_source_edit_during_copy_is_detected_and_paused_preference_survives_switch(self):
        self.capture()
        preview = self.preview()
        actual = destinations._copy_file
        index = self.session.backups.scope(self.saves) / 'history.json'
        changed = False
        def copy(*args):
            nonlocal changed
            actual(*args)
            if not changed:
                changed = True
                rows = json.loads(index.read_text())
                rows[0]['label'] = 'changed during copy'
                index.write_text(json.dumps(rows), encoding='utf-8')
        with patch('companion.backup_destination._copy_file', side_effect=copy):
            with self.assertRaisesRegex(ValueError, '字节校验失败|内容已变化'):
                self.session.backup_destination_action(self.request('apply', expected=preview['expected'], confirmed=True))
        self.assertEqual(self.session.settings['backup_root'], '')
        self.assertEqual(destinations._tree(self.target)['files'], {})
        self.session.backups.set_enabled(False)
        self.switch()
        self.assertFalse(self.session.backups.enabled)
        self.assertFalse(Session(self.config).backups.enabled)

    def test_same_identity_different_valid_zip_bytes_and_unknown_top_level_are_rejected(self):
        from zipfile import ZipFile
        row = self.capture()
        self.switch()
        original = self.config.parent / 'backups' / self.session.backups.scope(self.saves).name / (row['id'] + '.zip')
        with ZipFile(original, 'a') as archive:
            archive.comment = b'Target original has different zip bytes'
        raw = original.read_bytes()
        with self.assertRaisesRegex(ValueError, '已有不同内容'):
            self.preview('')
        self.assertEqual(original.read_bytes(), raw)
        other = self.base / 'another-destination'
        (other / 'backups').mkdir(parents=True)
        unexpected = other / 'backups' / 'personal.txt'
        unexpected.write_bytes(b'User owned')
        with self.assertRaisesRegex(ValueError, '未识别内容'):
            self.preview(other)
        self.assertEqual(unexpected.read_bytes(), b'User owned')

    def test_symlink_and_save_tree_destinations_are_rejected(self):
        self.capture()
        for target in (self.saves, self.saves / 'game1'):
            with self.assertRaisesRegex(ValueError, '游戏存档'):
                self.preview(target)
        link = self.base / 'linked'
        try:
            link.symlink_to(self.target, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('symlink privileges unavailable')
        with self.assertRaisesRegex(ValueError, '链接'):
            self.preview(link)
        self.assertEqual(self.files(self.target), {})

    def test_preview_and_apply_are_serialized_with_settings_and_shutdown(self):
        self.capture()
        preview = self.preview()
        entered, release, updated = threading.Event(), threading.Event(), threading.Event()
        actual = destinations._copy_file
        failures = []
        def copy(*args):
            entered.set()
            if not release.wait(5):
                raise AssertionError('copy test was not released')
            return actual(*args)
        def apply():
            try:
                self.session.backup_destination_action(self.request('apply', expected=preview['expected'], confirmed=True))
            except Exception as exc:
                failures.append(exc)
        def update():
            try:
                self.session.update_settings({'always_on_top': True})
                updated.set()
            except Exception as exc:
                failures.append(exc)
        with patch('companion.backup_destination._copy_file', side_effect=copy):
            applying = threading.Thread(target=apply)
            applying.start()
            self.assertTrue(entered.wait(5))
            updating = threading.Thread(target=update)
            updating.start()
            self.assertFalse(updated.wait(.1))
            release.set()
            applying.join(5)
            updating.join(5)
        self.assertFalse(applying.is_alive())
        self.assertFalse(updating.is_alive())
        self.assertFalse(failures)
        self.assertTrue(self.session.settings['always_on_top'])
        self.assertEqual(self.session.settings['backup_root'], str(self.target))
        self.session.prepare_shutdown()
        with self.assertRaisesRegex(ValueError, '正在结束'):
            self.preview('')


if __name__ == '__main__':
    unittest.main()
