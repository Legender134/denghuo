"""Visible startup failures for console and pythonw launchers."""

import ctypes
import os
from pathlib import Path
import sys
import tempfile
import traceback


def report_failure(exc, root=None):
    from .paths import data_directory
    primary = root / '.local/startup-error.log' if root is not None else data_directory()/'startup-error.log'
    log_path = None
    for candidate in (primary, Path(tempfile.gettempdir()) / 'dungeon-companion-startup-error.log'):
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.write_text(''.join(traceback.format_exception(exc)), encoding='utf-8')
            log_path = candidate
            break
        except OSError:
            continue
    message = f'灯火未能启动：{exc}\n\n'
    message += f'错误详情：{log_path}\n\n' if log_path else '错误日志无法写入，请检查目录权限。\n\n'
    message += ('请完整解压灯火程序，保留 _internal 文件夹后重试。' if getattr(sys, 'frozen', False)
                else '确认 Python 3.10+ 与项目文件完整后重试。若悬浮窗无法使用，可运行：\npython -m companion --no-overlay')
    if sys.stderr is not None:
        print(message, file=sys.stderr)
    elif os.name == 'nt':
        ctypes.windll.user32.MessageBoxW(None, message, '灯火 · 启动失败', 0x10)
    return message
