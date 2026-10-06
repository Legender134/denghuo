"""Optional Windows hotkeys; commands never manipulate the game."""
import ctypes
from ctypes import wintypes
import os
import threading

DEFAULT_BINDINGS = {'capture': 'Ctrl+Alt+B', 'show': 'Ctrl+Alt+L', 'library': 'Ctrl+Alt+H',
                    'backups': 'Ctrl+Alt+T', 'play_toggle': 'Ctrl+Alt+G', 'quick': 'Ctrl+Alt+Q'}


def normalize_chord(value):
    if not isinstance(value, str) or len(value) > 60:
        raise ValueError('快捷键格式不正确')
    if not value.strip():
        return ''
    parts = [p.strip().upper() for p in value.split('+')]
    modifiers = parts[:-1]
    key = parts[-1]
    if (not modifiers or len(modifiers) != len(set(modifiers))
            or not set(modifiers) <= {'CTRL', 'ALT', 'SHIFT'}
            or not set(modifiers) & {'CTRL', 'ALT'}):
        raise ValueError('快捷键需含Ctrl或Alt，可加Shift；不使用Windows键')
    if not (len(key) == 1 and 'A' <= key <= 'Z'):
        if not (key.startswith('F') and key[1:].isdigit() and 1 <= int(key[1:]) <= 12):
            raise ValueError('快捷键末尾请选择A–Z或F1–F12')
        key = 'F' + str(int(key[1:]))
    return '+'.join([m.title() for m in ('CTRL', 'ALT', 'SHIFT') if m in modifiers] + [key])


def chord_values(chord):
    normalized = normalize_chord(chord)
    if not normalized:
        return None
    parts = normalized.split('+')
    modifiers = 0x4000 | sum({'Ctrl': 2, 'Alt': 1, 'Shift': 4}[p] for p in parts[:-1])
    key = parts[-1]
    return modifiers, ord(key) if len(key) == 1 else 0x70 + int(key[1:]) - 1


class Hotkeys:
    def __init__(self, commands, bindings=None):
        if os.name != 'nt':
            raise OSError('Windows快捷键仅在Windows可用')
        self.commands = commands
        self.bindings = {**DEFAULT_BINDINGS, **(bindings or {})}
        self.mapping = {i: (normalize_chord(chord), command) for i, (command, chord)
                        in enumerate(self.bindings.items(), 1) if normalize_chord(chord)}
        self.unavailable = []
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
        mapping = self.mapping
        registered=[]
        try:
            for identity,(chord,command) in mapping.items():
                modifiers, key = chord_values(chord)
                if user.RegisterHotKey(None,identity,modifiers,key):
                    registered.append(identity)
                else:
                    self.unavailable.append(chord)
            self.commands.put(('hotkeys', ', '.join(mapping[i][0] for i in registered)))
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
