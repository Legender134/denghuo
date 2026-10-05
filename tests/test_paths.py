import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from companion.paths import data_directory, migrate_data


class DataPathTests(unittest.TestCase):
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
