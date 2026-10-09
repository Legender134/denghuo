import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from companion.paths import data_directory, migrate_data


class DataPathTests(unittest.TestCase):
    def test_first_install_copies_raw_exit_drafts_and_preserves_incompatible_originals(self):
        from companion.session_exit import ExitDraftStore
        from companion.service import Session
        with tempfile.TemporaryDirectory(prefix='denghuo-raw-draft-migration-') as directory:
            root = Path(directory); source = root / 'old'; source.mkdir()
            (source / 'settings.json').write_text(json.dumps({'save_root': str(root / 'saves'),
                'slot': 'auto', 'mode': 'save', 'reveal': False}), encoding='utf-8')
            store = ExitDraftStore(source / 'exit-drafts')
            saved = store.save('web-12345678', 'workspace', '未计算的输入',
                {'format': 1, 'numeric': {'hp': '不是数字', 'level': '-'}, 'open_plan': {'name': '原名', 'note': '原备注'}})
            valid_path = store.directory / (saved['id'] + '.json')
            valid_raw = valid_path.read_bytes()
            invalid_path = store.directory / ('a' * 32 + '.json')
            invalid_raw = b'{"format":900,"raw":"incompatible original"}'
            invalid_path.write_bytes(invalid_raw)
            destination = root / 'new'; report = migrate_data(destination, [source])
            self.assertEqual(report['copied_exit_drafts'], [valid_path.name])
            self.assertEqual(report['unavailable_exit_drafts'][0]['file'], invalid_path.name)
            self.assertEqual((destination / 'exit-drafts' / valid_path.name).read_bytes(), valid_raw)
            self.assertEqual((destination / 'exit-drafts-preserved' / invalid_path.name).read_bytes(), invalid_raw)
            self.assertEqual(valid_path.read_bytes(), valid_raw); self.assertEqual(invalid_path.read_bytes(), invalid_raw)
            loaded = Session(destination / 'settings.json')
            self.assertEqual(len(loaded.exit_drafts.list()), 1); self.assertIsNone(loaded.data)

    def test_frozen_data_is_independent_of_resource_and_executable_locations(self):
        with patch('companion.paths.sys.frozen',True,create=True), patch.dict('os.environ',{'LOCALAPPDATA':'C:/用户数据'}):
            self.assertEqual(data_directory(),Path('C:/用户数据/Denghuo'))
            with patch('companion.paths.ROOT',Path('C:/temporary-unpack')):
                self.assertEqual(data_directory(),Path('C:/用户数据/Denghuo'))

    def test_migration_copies_all_backups_and_preserves_both_old_and_existing_data(self):
        with tempfile.TemporaryDirectory(prefix='denghuo-migrate-') as directory:
            root=Path(directory);source=root/'旧版'/'内置数据';source.mkdir(parents=True)
            settings={'save_root':str(root/'offline-saves'),'slot':3,'mode':'save','reveal':False}
            (source/'settings.json').write_text(json.dumps(settings),encoding='utf-8')
            archive=source/'backups'/'scope'/'retained.zip';archive.parent.mkdir(parents=True);archive.write_bytes(b'original archive bytes')
            destination=root/'应用数据'
            report=migrate_data(destination,[root/'missing',source])
            self.assertEqual(report['copied_files'],1)
            self.assertEqual((destination/'backups/scope/retained.zip').read_bytes(),archive.read_bytes())
            self.assertTrue(archive.exists());self.assertEqual(json.loads((destination/'settings.json').read_text()),settings)
            (destination/'settings.json').write_text('keep current user settings')
            self.assertIsNone(migrate_data(destination,[source]))
            self.assertEqual((destination/'settings.json').read_text(),'keep current user settings')

    def test_failed_migration_never_publishes_partial_destination(self):
        with tempfile.TemporaryDirectory(prefix='denghuo-migrate-failure-') as directory:
            root=Path(directory);source=root/'old';source.mkdir()
            raw=json.dumps({'save_root':str(root),'slot':1,'mode':'save','reveal':False})
            (source/'settings.json').write_text(raw)
            destination=root/'new'
            with patch('companion.paths.shutil.copy2',side_effect=OSError('controlled copy failure')):
                with self.assertRaises(OSError):migrate_data(destination,[source])
            self.assertFalse(destination.exists())
            self.assertEqual((source/'settings.json').read_text(),raw)

    def test_migration_retains_library_and_shared_play_preferences_without_applying_a_draft(self):
        from companion.service import Session
        with tempfile.TemporaryDirectory(prefix='denghuo-workspace-migrate-') as directory:
            root=Path(directory);source=root/'old';source.mkdir()
            settings={'save_root':str(root/'synthetic-saves'),'slot':'auto','mode':'save','reveal':False}
            (source/'settings.json').write_text(json.dumps(settings),encoding='utf-8')
            session=Session(source/'settings.json')
            plan=session.knowledge.save('手动草稿','manual',None,{'hp':3,'ht':30,'buffs':['Poison']})
            session.play_preferences.update({'offset_y':140})
            original_library=(source/'knowledge.json').read_bytes()
            original_play=(source/'play-mode.json').read_bytes()
            destination=root/'new'
            report=migrate_data(destination,[source])
            self.assertEqual(set(report['copied_preferences']),{'knowledge.json','play-mode.json'})
            loaded=Session(destination/'settings.json')
            self.assertEqual(loaded.knowledge.reopen(plan['id'])['result']['hero']['hp'],3)
            self.assertIsNone(loaded.data)
            self.assertEqual(loaded.settings['mode'],'save')
            self.assertEqual(loaded.play_preferences.values['offset_y'],140)
            self.assertEqual((destination/'knowledge.json').read_bytes(),original_library)
            self.assertEqual((source/'knowledge.json').read_bytes(),original_library)
            self.assertEqual((source/'play-mode.json').read_bytes(),original_play)
