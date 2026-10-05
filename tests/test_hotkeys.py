import ctypes
from ctypes import wintypes
import os
from queue import Queue
import unittest
from companion.hotkeys import Hotkeys


@unittest.skipUnless(os.name=='nt','Windows hotkey component')
class HotkeyTests(unittest.TestCase):
    def test_registered_commands_dispatch_and_stop_releases_keys(self):
        commands=Queue();keys=Hotkeys(commands)
        self.addCleanup(keys.stop)
        self.assertTrue(keys.ready.wait(3))
        kind,available=commands.get(timeout=3)
        self.assertEqual(kind,'hotkeys')
        if not available:self.skipTest('All optional shortcut keys are occupied by another running application')
        mapping={'B':(1,'capture'),'L':(2,'show'),'H':(3,'library'),'T':(4,'backups')}
        user=ctypes.WinDLL('user32',use_last_error=True)
        user.PostThreadMessageW.argtypes=[wintypes.DWORD,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
        user.RegisterHotKey.argtypes=[wintypes.HWND,ctypes.c_int,wintypes.UINT,wintypes.UINT]
        user.UnregisterHotKey.argtypes=[wintypes.HWND,ctypes.c_int]
        for chord in available.split(', '):
            if not chord:continue
            key=chord[-1];identity,command=mapping[key]
            self.assertTrue(user.PostThreadMessageW(keys.thread_id,0x0312,identity,0))
            self.assertEqual(commands.get(timeout=3),(command,None))
        keys.stop();keys.stop()
        self.assertFalse(keys.thread.is_alive())
        for chord in available.split(', '):
            if not chord:continue
            self.assertTrue(user.RegisterHotKey(None,901,0x4003,ord(chord[-1])))
            self.assertTrue(user.UnregisterHotKey(None,901))
