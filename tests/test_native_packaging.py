"""A desktop delivery must carry the helper in its real resource root."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.build_desktop import ROOT, desktop_command, native_resources


class NativePackagingTests(unittest.TestCase):
    def test_builder_includes_only_runtime_helper_in_explicit_resource_root(self):
        helper = Path('controlled native build') / 'NativeCompanion.exe'
        command = desktop_command(Path('delivery'), Path('work'), helper)
        self.assertEqual(command[command.index('--contents-directory') + 1], '_internal')
        self.assertIn(str(helper) + ';native', command)
        self.assertIn(str(helper.with_suffix('.exe.config')) + ';native', command)
        self.assertFalse(any('build-evidence.json' in arg or 'references;' in arg for arg in command))

    def test_missing_or_wrongly_located_helper_stops_delivery(self):
        with tempfile.TemporaryDirectory() as folder:
            app = Path(folder)
            misplaced = app / 'native'
            misplaced.mkdir()
            (misplaced / 'NativeCompanion.exe').write_bytes(b'MZ controlled fixture')
            (misplaced / 'NativeCompanion.exe.config').write_bytes((ROOT / 'native/NativeCompanion.exe.config').read_bytes())
            with self.assertRaisesRegex(ValueError, '预置原生窗口'):
                native_resources(app)

    def test_mismatched_config_or_binary_stops_delivery(self):
        with tempfile.TemporaryDirectory() as folder:
            app = Path(folder)
            resources = app / '_internal/native'
            resources.mkdir(parents=True)
            helper = resources / 'NativeCompanion.exe'
            config = resources / 'NativeCompanion.exe.config'
            helper.write_bytes(b'MZ controlled fixture')
            config.write_bytes(b'old runtime config')
            with self.assertRaisesRegex(ValueError, '配置'):
                native_resources(app)
            config.write_bytes((ROOT / 'native/NativeCompanion.exe.config').read_bytes())
            expected = app / 'newly-compiled.exe'
            expected.write_bytes(b'MZ different controlled fixture')
            with self.assertRaisesRegex(ValueError, '编译结果'):
                native_resources(app, expected)
            expected.write_bytes(helper.read_bytes())
            self.assertEqual(native_resources(app, expected)['helper'], helper)

    def test_preflight_fails_before_packaging_touches_output_or_downloads(self):
        from tools.package_desktop import package
        with tempfile.TemporaryDirectory() as folder:
            app = Path(folder)
            with patch('tools.package_desktop.download') as download:
                with self.assertRaisesRegex(ValueError, '预置原生窗口'):
                    package(app, app, app, app)
                download.assert_not_called()
            self.assertEqual(list(app.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
