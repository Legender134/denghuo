"""Native display support. Reads game window metadata, only styles our own windows."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os

NOACTIVATE, TOOLWINDOW, LAYERED, TRANSPARENT = 0x08000000, 0x80, 0x80000, 0x20


class WindowsDisplay:
    def __init__(self):
        if os.name != 'nt':
            raise OSError('游玩显示仅支持Windows')
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        u = self.user
        u.GetForegroundWindow.restype = wintypes.HWND
        u.GetAncestor.argtypes, u.GetAncestor.restype = [wintypes.HWND, wintypes.UINT], wintypes.HWND
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        u.IsWindow.argtypes = [wintypes.HWND]
        u.IsIconic.argtypes = [wintypes.HWND]
        u.IsWindowVisible.argtypes = [wintypes.HWND]
        u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.UINT]
        u.SetForegroundWindow.argtypes = [wintypes.HWND]
        u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        self.get_style = getattr(u, 'GetWindowLongPtrW', u.GetWindowLongW)
        self.set_style = getattr(u, 'SetWindowLongPtrW', u.SetWindowLongW)
        self.get_style.argtypes, self.get_style.restype = [wintypes.HWND, ctypes.c_int], ctypes.c_ssize_t
        self.set_style.argtypes, self.set_style.restype = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t], ctypes.c_ssize_t
        self.last_game = None

    def hwnd(self, widget):
        return self.user.GetAncestor(widget.winfo_id(), 2)

    def foreground(self):
        return self.user.GetForegroundWindow()

    def process(self, hwnd):
        pid = wintypes.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value

    def is_own(self, hwnd):
        return bool(hwnd and self.process(hwnd) == os.getpid())

    def game(self):
        hwnd = self.foreground()
        title, kind = ctypes.create_unicode_buffer(512), ctypes.create_unicode_buffer(128)
        self.user.GetWindowTextW(hwnd, title, len(title))
        self.user.GetClassNameW(hwnd, kind, len(kind))
        # An Edge page with a matching title must never be mistaken for the game.
        if (title.value.startswith('Shattered Pixel Dungeon')
                and kind.value in ('GLFW30', 'LWJGL') and not self.is_own(hwnd)):
            rect = self.rect(hwnd)
            if rect:
                self.last_game = {'hwnd': hwnd, 'pid': self.process(hwnd), 'title': title.value, 'rect': rect}
                return self.last_game
        return None

    def remembered_game(self):
        game = self.last_game
        if not game or self.process(game['hwnd']) != game['pid']:
            return None
        rect = self.rect(game['hwnd'])
        return {**game, 'rect': rect} if rect else None

    def rect(self, hwnd):
        if not hwnd or not self.user.IsWindow(hwnd) or self.user.IsIconic(hwnd) or not self.user.IsWindowVisible(hwnd):
            return None
        rect, origin = wintypes.RECT(), wintypes.POINT()
        if not self.user.GetClientRect(hwnd, ctypes.byref(rect)) or not self.user.ClientToScreen(hwnd, ctypes.byref(origin)):
            return None
        if rect.right < 100 or rect.bottom < 100:
            return None
        return origin.x, origin.y, origin.x + rect.right, origin.y + rect.bottom

    def passive(self, widget, click_through=True):
        hwnd = self.hwnd(widget)
        if not self.is_own(hwnd):
            raise OSError('拒绝修改其他程序的窗口')
        original = self.get_style(hwnd, -20)
        style = (original | NOACTIVATE | TOOLWINDOW | LAYERED) & ~0x40000  # APPWINDOW
        style = style | TRANSPARENT if click_through else style & ~TRANSPARENT
        ctypes.set_last_error(0)
        if not self.set_style(hwnd, -20, style) and ctypes.get_last_error():
            raise ctypes.WinError(ctypes.get_last_error())
        self.user.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x37)  # FRAMECHANGED, no move/size/z/activate
        return hwnd

    def show(self, widget, x, y, width, height):
        hwnd = self.hwnd(widget)
        if not self.is_own(hwnd):
            raise OSError('拒绝修改其他程序的窗口')
        if not self.user.SetWindowPos(hwnd, wintypes.HWND(-1), x, y, width, height, 0x50):
            raise ctypes.WinError(ctypes.get_last_error())

    def style(self, widget):
        return self.get_style(self.hwnd(widget), -20)

    def return_to_game(self, game):
        """Return after an explicit lookup close, only while our app has focus."""
        if not game or not self.is_own(self.foreground()):
            return False
        hwnd = game['hwnd']
        if not self.user.IsWindow(hwnd) or self.process(hwnd) != game['pid']:
            return False
        title, kind = ctypes.create_unicode_buffer(512), ctypes.create_unicode_buffer(128)
        self.user.GetWindowTextW(hwnd, title, len(title))
        self.user.GetClassNameW(hwnd, kind, len(kind))
        if not title.value.startswith('Shattered Pixel Dungeon') or kind.value not in ('GLFW30', 'LWJGL'):
            return False
        if self.user.IsIconic(hwnd):
            self.user.ShowWindow(hwnd, 9)  # SW_RESTORE; no style or game setting changes.
        return bool(self.user.SetForegroundWindow(hwnd))
