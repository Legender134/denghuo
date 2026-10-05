"""Double-click entrypoint, including errors that happen during imports."""
import ctypes
import os
import sys

try:
    if sys.version_info < (3, 10):
        raise RuntimeError('灯火需要 Python 3.10 或更新版本。')
    from companion.__main__ import entrypoint
except Exception as exc:
    message = '灯火无法加载：' + str(exc) + '\n请确认 Python 版本，并将整个助手文件夹保留完整。'
    if os.name == 'nt':
        ctypes.windll.user32.MessageBoxW(None, message, '灯火 · 启动失败', 0x10)
    elif sys.stderr is not None:
        print(message, file=sys.stderr)
    raise SystemExit(1)

raise SystemExit(entrypoint())
