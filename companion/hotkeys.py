"""Optional Windows hotkeys; commands never manipulate the game."""
import ctypes
from ctypes import wintypes
import os
import threading


class Hotkeys:
    def __init__(self, commands):
        if os.name != 'nt':
            raise OSError('Windows快捷键仅在Windows可用')
        self.commands = commands
        self.ready = threading.Event()
        self.stopped = threading.Event()
        self.thread_id = None
        self.thread = threading.Thread(target=self.run, name='lamp-hotkeys', daemon=True)
        self.thread.start()

    def run(self):
        user = ctypes.WinDLL('user32', use_last_error=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        user.RegisterHotKey.argtypes=[wintypes.HWND,ctypes.c_int,wintypes.UINT,wintypes.UINT]
        user.GetMessageW.argtypes=[ctypes.POINTER(wintypes.MSG),wintypes.HWND,wintypes.UINT,wintypes.UINT]
        user.PeekMessageW.argtypes=[ctypes.POINTER(wintypes.MSG),wintypes.HWND,wintypes.UINT,wintypes.UINT,wintypes.UINT]
        user.UnregisterHotKey.argtypes=[wintypes.HWND,ctypes.c_int]
        self.thread_id = kernel.GetCurrentThreadId()
        message = wintypes.MSG()
        user.PeekMessageW(ctypes.byref(message),None,0,0,0)
        mapping = {1:('B','capture'),2:('L','show'),3:('H','library'),4:('T','backups')}
        registered=[]
        try:
            for identity,(key,command) in mapping.items():
                if user.RegisterHotKey(None,identity,0x4000|0x0002|0x0001,ord(key)):
                    registered.append(identity)
            self.commands.put(('hotkeys', ', '.join('Ctrl+Alt+'+mapping[i][0] for i in registered)))
            self.ready.set()
            while not self.stopped.is_set():
                result=user.GetMessageW(ctypes.byref(message),None,0,0)
                if result<=0:break
                if message.message==0x0312 and message.wParam in registered:
                    self.commands.put((mapping[message.wParam][1],None))
        finally:
            for identity in registered:user.UnregisterHotKey(None,identity)
            self.ready.set()

    def stop(self):
        self.stopped.set()
        self.ready.wait(1)
        if self.thread_id is not None:
            ctypes.WinDLL('user32').PostThreadMessageW(self.thread_id,0x0012,0,0)
        self.thread.join(timeout=2)
