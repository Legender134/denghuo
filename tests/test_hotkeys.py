import ctypes
from ctypes import wintypes
import os
from queue import Queue
import unittest
from companion.hotkeys import Hotkeys, normalize_chord, chord_values


class BindingTests(unittest.TestCase):
    def test_canonical_chords_and_function_keys(self):
        self.assertEqual(normalize_chord(' shift + alt + ctrl + q '),'Ctrl+Alt+Shift+Q')
        self.assertEqual(chord_values('Alt+F12'),(0x4001,0x7B))
        self.assertEqual(normalize_chord('Ctrl+F01'),'Ctrl+F1')
        self.assertEqual(chord_values('Ctrl+Q'),(0x4002,ord('Q')))
        self.assertIsNone(chord_values(''))

    def test_invalid_chords_fail_before_registration(self):
        for value in ('Q','Shift+Q','Win+Q','Ctrl+Ctrl+Q','Ctrl+F13','Ctrl+1','Ctrl++Q',None):
            with self.subTest(value=value),self.assertRaises(ValueError):normalize_chord(value)


@unittest.skipUnless(os.name=='nt','Windows hotkey component')
class HotkeyTests(unittest.TestCase):
    def test_registered_commands_dispatch_and_stop_releases_keys(self):
        commands=Queue();keys=Hotkeys(commands)
        self.addCleanup(keys.stop)
        self.assertTrue(keys.ready.wait(3))
        kind,available=commands.get(timeout=3)
        self.assertEqual(kind,'hotkeys')
        if not available:self.skipTest('All optional shortcut keys are occupied by another running application')
        mapping={chord:(identity,command) for identity,(chord,command) in keys.mapping.items()}
        user=ctypes.WinDLL('user32',use_last_error=True)
        user.PostThreadMessageW.argtypes=[wintypes.DWORD,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
        user.RegisterHotKey.argtypes=[wintypes.HWND,ctypes.c_int,wintypes.UINT,wintypes.UINT]
        user.UnregisterHotKey.argtypes=[wintypes.HWND,ctypes.c_int]
        for chord in available.split(', '):
            if not chord:continue
            identity,command=mapping[chord]
            self.assertTrue(user.PostThreadMessageW(keys.thread_id,0x0312,identity,0))
            self.assertEqual(commands.get(timeout=3),(command,None))
        keys.stop();keys.stop()
        self.assertFalse(keys.thread.is_alive())
        for chord in available.split(', '):
            if not chord:continue
            self.assertTrue(user.RegisterHotKey(None,901,*chord_values(chord)))
            self.assertTrue(user.UnregisterHotKey(None,901))
