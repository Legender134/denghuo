import json
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

from companion.game_process import (GAME_MAIN, absolute_windows_path, classify_process,
    confirm_game_closed, java_entry, main_manifest, read_processes, windows_arguments)


class GameProcessTests(unittest.TestCase):
    def record(self, *args, name='java.exe', path='C:\\Java\\bin\\java.exe', pid=77):
        return {'pid': pid, 'name': name, 'path': path, 'command': json.dumps([path, *args]), 'created': None}

    def classify(self, record, windows=()):
        return classify_process(record, windows, parse_arguments=json.loads)

    def test_standard_other_java_main_and_no_entry_do_not_block_because_of_name(self):
        self.assertEqual(self.classify(self.record('-cp', 'C:\\tools\\classes', 'tool.Main'))[0], 'UNRELATED')
        self.assertEqual(self.classify(self.record())[0], 'UNRELATED')
        self.assertEqual(self.classify(self.record(name='PixelEditor.exe', path='C:\\tools\\PixelEditor.exe'))[0], 'UNRELATED')

    def test_game_main_after_real_option_operands_is_detected(self):
        for options in (['-cp', 'C:\\games\\classes'], ['--class-path=C:\\games\\classes'],
                        ['--add-opens', 'java.base/java.lang=ALL-UNNAMED', '-Xmx1g']):
            self.assertEqual(self.classify(self.record(*options, GAME_MAIN, '@application-notes'))[0], 'GAME')

    def test_string_properties_classpath_operands_and_application_arguments_are_not_main(self):
        self.assertEqual(self.classify(self.record('-Dnote=' + GAME_MAIN, '-cp', 'C:\\tools', 'tool.Main', GAME_MAIN))[0], 'UNRELATED')
        self.assertEqual(java_entry(['-cp', GAME_MAIN, 'tool.Main'])[0:2], ('class', 'tool.Main'))
        self.assertEqual(self.classify(self.record('tool.Main', '-jar', 'C:\\games\\game.jar'))[0], 'UNRELATED')

    def test_unknown_or_missing_information_is_not_misreported_as_game_or_allowed(self):
        for record in (self.record('@C:\\opaque.args'), self.record('@relative.args'),
                       self.record('--source', '17', 'game.java'), self.record('--unrecognized', GAME_MAIN),
                       self.record('-cp'), self.record(path=None)):
            self.assertEqual(self.classify(record)[0], 'UNKNOWN')
        unreadable = self.record()
        unreadable['command'] = None
        self.assertEqual(self.classify(unreadable)[0], 'UNKNOWN')

    def test_window_identity_blocks_background_or_renamed_launcher_independent_of_java_args(self):
        record = self.record(name='renamed.exe', path=None)
        self.assertEqual(self.classify(record, {77})[0], 'GAME')

    def test_relative_and_drive_relative_jars_are_unknown_never_resolved_against_assistant_cwd(self):
        for jar in ('game.jar', '..\\game.jar', 'C:game.jar', '\\game.jar'):
            self.assertFalse(absolute_windows_path(jar))
            self.assertEqual(self.classify(self.record('-jar', jar))[0], 'UNKNOWN')
        self.assertTrue(absolute_windows_path('C:\\Games\\renamed.bin'))
        self.assertTrue(absolute_windows_path('\\\\server\\share\\renamed.jar'))

    def test_jar_continuations_main_section_and_property_names_match_official_manifest(self):
        manifest = ('Manifest-Version: 1.0\r\nMain-Class: ' + GAME_MAIN[:-4] + '\r\n ' + GAME_MAIN[-4:]
                    + '\r\nImplementation-Version: 922\r\n\r\nName: later.class\r\nMain-Class: tool.Main\r\n').encode()
        self.assertEqual(main_manifest(manifest), GAME_MAIN)
        self.assertEqual(main_manifest(b'Manifest-Version: 1.0\nmain-class: tool.Main\n\n'), 'tool.Main')
        with self.assertRaises(ValueError):
            main_manifest(b'Main-Class: tool.Main\nMain-Class: another.Main\n\n')

    def test_empty_scan_requires_explicit_success_envelope_and_typed_fields(self):
        good = {'schema': 1, 'ok': True, 'candidates': []}
        with patch('companion.game_process.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=json.dumps(good))):
            self.assertEqual(read_processes(set()), [])
        invalid = ['', '[]', '"java.exe"', json.dumps({**good, 'schema': True}), json.dumps({**good, 'ok': False}),
                   json.dumps({**good, 'candidates': [self.record(pid=True)]}),
                   json.dumps({**good, 'candidates': [self.record(), self.record()]})]
        for stdout in invalid:
            with self.subTest(stdout=stdout), patch('companion.game_process.subprocess.run',
                    return_value=SimpleNamespace(returncode=0, stdout=stdout)), self.assertRaises(ValueError):
                read_processes(set())
        with patch('companion.game_process.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=json.dumps(good))), self.assertRaises(ValueError):
            read_processes({77})

    def test_closed_check_names_only_confirmed_game_and_unknown_reason_separately(self):
        java = self.record('-cp', 'C:\\classes', GAME_MAIN)
        with patch('companion.game_process.sys.platform', 'win32'), patch('companion.game_process.game_window_pids', return_value=set()), \
                patch('companion.game_process.read_processes', return_value=[java]), patch('companion.game_process.windows_arguments', side_effect=json.loads):
            # Default function argument is bound at definition; inject the classifier parser directly.
            with patch('companion.game_process.classify_process', return_value=('GAME', 'direct main')):
                with self.assertRaisesRegex(ValueError, '检测到游戏进程.*PID 77'):
                    confirm_game_closed()
            with patch('companion.game_process.classify_process', return_value=('UNKNOWN', '命令不可读')):
                with self.assertRaisesRegex(ValueError, '尚无法确认.*命令不可读'):
                    confirm_game_closed()
            with patch('companion.game_process.classify_process', return_value=('UNRELATED', 'other tool')):
                confirm_game_closed()

    @unittest.skipUnless(sys.platform == 'win32', 'real Windows CommandLineToArgvW')
    def test_real_windows_unicode_and_quoted_classpath(self):
        command = '"C:\\Program Files\\Java\\bin\\java.exe" -cp "C:\\中文 游戏\\classes" ' + GAME_MAIN + ' "application arguments"'
        parsed = windows_arguments(command)
        self.assertEqual(parsed[2], 'C:\\中文 游戏\\classes')
        self.assertEqual(java_entry(parsed[1:])[0:2], ('class', GAME_MAIN))
        with self.assertRaises(ValueError):
            windows_arguments('java.exe """opaque"')


if __name__ == '__main__':
    unittest.main()
