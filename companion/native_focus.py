"""Explicit child-window focus return; passive-window ownership stays unchanged."""
import ctypes


def return_to_game(native, game, child_pid):
    foreground = native.foreground()
    if not foreground or native.process(foreground) != child_pid:
        return False
    hwnd = game['hwnd']
    if not native.user.IsWindow(hwnd) or native.process(hwnd) != game['pid']:
        return False
    title, kind = ctypes.create_unicode_buffer(512), ctypes.create_unicode_buffer(128)
    native.user.GetWindowTextW(hwnd, title, len(title))
    native.user.GetClassNameW(hwnd, kind, len(kind))
    if not title.value.startswith('Shattered Pixel Dungeon') or kind.value not in ('GLFW30', 'LWJGL'):
        return False
    if native.user.IsIconic(hwnd):
        native.user.ShowWindow(hwnd, 9)
    return bool(native.user.SetForegroundWindow(hwnd))
