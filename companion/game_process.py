"""Read-only identification of supported desktop and direct Java game launches.

This is a save-operation guard, not an adversarial process authentication boundary.
Custom launchers, missing metadata and opaque Java argument files are unknown.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from datetime import datetime
import json
import ntpath
import os
from pathlib import Path
import re
import subprocess
import sys
from zipfile import ZipFile, BadZipFile

GAME_MAIN = 'com.shatteredpixel.shatteredpixeldungeon.desktop.DesktopLauncher'
NATIVE_NAMES = {'shattered pixel dungeon.exe', 'shatteredpd.exe'}
JAVA_NAMES = {'java.exe', 'javaw.exe'}
MAIN_CLASS = re.compile(r'[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*\Z', re.ASCII)


def absolute_windows_path(value):
    if not isinstance(value, str) or '\x00' in value:
        return False
    drive, tail = ntpath.splitdrive(value)
    return bool(drive and tail.startswith(('\\', '/')))


def game_window_pids():
    if sys.platform != 'win32':
        raise OSError('游戏窗口检查仅支持Windows')
    user = ctypes.WinDLL('user32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes, user.EnumWindows.restype = [callback_type, wintypes.LPARAM], wintypes.BOOL
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    matches, errors = set(), []
    def inspect(hwnd, _):
        try:
            kind = ctypes.create_unicode_buffer(128)
            user.GetClassNameW(hwnd, kind, len(kind))
            if kind.value not in ('GLFW30', 'LWJGL'):
                return True
            pid = wintypes.DWORD()
            if not user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)) or not pid.value:
                raise OSError('无法读取游戏窗口所属进程')
            # GetWindowText sends WM_GETTEXT for our own windows. The UI thread
            # may be waiting for the Session lock held by this restore guard.
            if pid.value == os.getpid():
                return True
            title = ctypes.create_unicode_buffer(512)
            user.GetWindowTextW(hwnd, title, len(title))
            if title.value.startswith('Shattered Pixel Dungeon'):
                matches.add(pid.value)
        except Exception as exc:
            errors.append(exc)
        return True
    callback = callback_type(inspect)
    ctypes.set_last_error(0)
    if not user.EnumWindows(callback, 0) or errors:
        raise OSError('无法完整检查游戏窗口')
    return matches


def windows_arguments(command):
    if not isinstance(command, str) or not command.strip() or len(command) > 32768 or '\x00' in command:
        raise ValueError('启动命令不可读')
    # Consecutive-quote semantics differ between Java launchers and Windows parsers.
    if '"""' in command:
        raise ValueError('启动引号语法超出可确认范围')
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    shell.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    kernel.LocalFree.argtypes, kernel.LocalFree.restype = [wintypes.HLOCAL], wintypes.HLOCAL
    count = ctypes.c_int()
    pointer = shell.CommandLineToArgvW(command, ctypes.byref(count))
    if not pointer:
        raise ValueError('启动命令无法解析')
    try:
        if not 1 <= count.value <= 2048:
            raise ValueError('启动参数数量超出可确认范围')
        return [pointer[index] for index in range(count.value)]
    finally:
        kernel.LocalFree(ctypes.cast(pointer, wintypes.HLOCAL))


def java_entry(arguments):
    """Parse the supported standard Java operand arities, never application args."""
    operands = {'-cp', '-classpath', '--class-path', '-p', '--module-path', '--upgrade-module-path',
                '--add-modules', '--limit-modules', '--add-opens', '--add-exports', '--add-reads'}
    flags = {'-server', '-client', '-ea', '-da', '-esa', '-dsa', '-enableassertions', '-disableassertions',
             '-enablesystemassertions', '-disablesystemassertions', '--enable-preview', '--dry-run',
             '-showversion', '--show-version', '-verbose', '-version', '--version', '-help', '--help', '-?'}
    index, argfiles = 0, True
    while index < len(arguments):
        arg = arguments[index]
        if not isinstance(arg, str) or len(arg) > 32768:
            return 'unknown', '', '启动参数不完整'
        if arg.startswith('@') and argfiles:
            return 'unknown', '', '参数文件没有可信启动时记录'
        if arg == '--disable-@files':
            argfiles = False
        elif arg == '-jar':
            if index + 1 >= len(arguments) or arguments[index + 1].startswith('@') and argfiles:
                return 'unknown', '', 'JAR入口不可确认'
            return 'jar', arguments[index + 1], ''
        elif arg in ('-m', '--module') or arg.startswith('--module=') or arg in ('--source', '--patch-module'):
            return 'unknown', '', '模块、源码或替换模块启动尚未支持'
        elif arg in operands:
            index += 1
            if index >= len(arguments) or arguments[index].startswith('@') and argfiles:
                return 'unknown', '', 'Java选项缺少可确认的参数'
        elif '=' in arg and arg.split('=', 1)[0] in operands:
            pass
        elif (arg in flags or arg.startswith(('-D', '-X', '-XX:', '-ea:', '-da:', '-enableassertions:',
                                               '-disableassertions:', '-verbose:', '-agentlib:jdwp='))):
            pass
        elif arg.startswith('-'):
            return 'unknown', '', 'Java启动选项尚未支持'
        elif MAIN_CLASS.fullmatch(arg):
            return 'class', arg, ''
        else:
            return 'unknown', '', 'Java入口格式尚未支持'
        index += 1
    return 'none', '', '没有直接Java应用入口'


def main_manifest(raw):
    if len(raw) > 65536:
        raise ValueError('JAR入口记录过大')
    lines = raw.decode('utf-8').replace('\r\n', '\n').split('\n')
    unfolded = []
    for line in lines:
        if not line:
            break
        if line.startswith(' '):
            if not unfolded:
                raise ValueError('JAR入口续行不完整')
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    properties = {}
    for line in unfolded:
        key, separator, value = line.partition(': ')
        if not separator or key.casefold() in properties:
            raise ValueError('JAR入口记录不完整')
        properties[key.casefold()] = value.strip()
    return properties.get('main-class')


def jar_identity(path, created=None):
    if not absolute_windows_path(path):
        return 'UNKNOWN', '相对JAR缺少启动时目录'
    try:
        artifact = Path(path)
        before = artifact.stat()
        if not artifact.is_file() or not 0 < before.st_size <= 128 * 1024 * 1024:
            raise ValueError('JAR大小或类型无法确认')
        if created:
            start = datetime.fromisoformat(created.replace('Z', '+00:00')).timestamp()
            if before.st_mtime > start + 1:
                raise ValueError('JAR在进程启动后发生变化')
        with ZipFile(artifact) as archive:
            if len(archive.infolist()) > 25000:
                raise ValueError('JAR目录超出可确认范围')
            entries = [entry for entry in archive.infolist() if entry.filename.upper() == 'META-INF/MANIFEST.MF']
            if len(entries) != 1 or entries[0].file_size > 65536 or entries[0].flag_bits & 1:
                raise ValueError('JAR主入口不可确认')
            entry = main_manifest(archive.read(entries[0]))
        after = artifact.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise ValueError('JAR读取期间发生变化')
        if entry == GAME_MAIN:
            return 'GAME', 'JAR主类是破碎的像素地牢'
        if not entry or not MAIN_CLASS.fullmatch(entry):
            return 'UNKNOWN', 'JAR主入口不可确认'
        return 'UNRELATED', '标准JAR主类是其他应用'
    except (OSError, ValueError, UnicodeError, BadZipFile, RuntimeError, OverflowError):
        return 'UNKNOWN', 'JAR入口不可读或已变化'


def native_identity(path):
    if not absolute_windows_path(path):
        return 'UNKNOWN', '游戏启动器路径不可读'
    try:
        exe = Path(path)
        config = exe.parent / 'app' / (exe.stem + '.cfg')
        with config.open('rb') as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError()
        section, main = '', None
        for line in raw.decode('utf-8-sig').splitlines():
            line = line.strip()
            if line.startswith('[') and line.endswith(']'):
                section = line
            elif section == '[Application]' and line.startswith('app.mainclass='):
                if main is not None:
                    raise ValueError()
                main = line.partition('=')[2].strip()
        if main == GAME_MAIN:
            return 'GAME', '原生启动器配置指向破碎的像素地牢'
        return 'UNKNOWN', '潜在游戏启动器配置无法确认'
    except (OSError, ValueError, UnicodeError):
        return 'UNKNOWN', '潜在游戏启动器配置不可读'


def classify_process(record, windows=(), parse_arguments=windows_arguments):
    pid, name = record['pid'], record['name'].casefold()
    if pid in windows:
        return 'GAME', '已观察到游戏窗口'
    if name in NATIVE_NAMES:
        return native_identity(record.get('path'))
    if name not in JAVA_NAMES:
        # A direct game main-class can be run by a renamed Java executable.
        if GAME_MAIN not in (record.get('command') or ''):
            return 'UNRELATED', '其他程序'
    if not absolute_windows_path(record.get('path')):
        return 'UNKNOWN', 'Java进程路径不可读'
    try:
        args = parse_arguments(record.get('command'))
    except (OSError, ValueError, TypeError, AttributeError):
        return 'UNKNOWN', 'Java进程启动命令不可读'
    kind, entry, reason = java_entry(args[1:])
    if kind == 'class':
        return ('GAME', '直接Java主类是破碎的像素地牢') if entry == GAME_MAIN else ('UNRELATED', '标准Java主类是其他应用')
    if kind == 'jar':
        return jar_identity(entry, record.get('created'))
    if kind == 'none':
        return 'UNRELATED', reason
    return 'UNKNOWN', reason


def read_processes(window_pids):
    wanted = ','.join(str(pid) for pid in sorted(window_pids))
    command = """[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$ErrorActionPreference='Stop'
try {
  $windows=@(WINDOW_PIDS)
  $rows=@(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
    $_.Name -in @('java.exe','javaw.exe','Shattered Pixel Dungeon.exe','ShatteredPD.exe') -or
    $_.ProcessId -in $windows
  } | ForEach-Object {
    $created=if ($_.CreationDate) {$_.CreationDate.ToUniversalTime().ToString('o')} else {$null}
    [ordered]@{pid=[int]$_.ProcessId;name=$_.Name;path=$_.ExecutablePath;command=$_.CommandLine;created=$created}
  })
  [ordered]@{schema=1;ok=$true;candidates=$rows} | ConvertTo-Json -Depth 5 -Compress
} catch { [Console]::Error.WriteLine('Game process inspection failed'); exit 1 }
""".replace('WINDOW_PIDS', wanted)
    powershell = Path(os.environ.get('SystemRoot') or os.environ.get('WINDIR') or 'C:/Windows') / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    try:
        response = subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-Command', command],
            capture_output=True, text=True, encoding='utf-8-sig', timeout=8,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if response.returncode or len(response.stdout) > 2 * 1024 * 1024:
            raise ValueError()
        envelope = json.loads(response.stdout)
        if (not isinstance(envelope, dict) or type(envelope.get('schema')) is not int or envelope.get('schema') != 1 or envelope.get('ok') is not True
                or not isinstance(envelope.get('candidates'), list) or len(envelope['candidates']) > 2048):
            raise ValueError()
        rows, seen = envelope['candidates'], set()
        for row in rows:
            if (not isinstance(row, dict) or type(row.get('pid')) is not int or not 1 <= row['pid'] <= 2 ** 32 - 1
                    or row['pid'] in seen or not isinstance(row.get('name'), str) or not 0 < len(row['name']) <= 260
                    or any(ord(char) < 32 for char in row['name'])
                    or any(row.get(key) is not None and not isinstance(row.get(key), str) for key in ('path', 'command', 'created'))):
                raise ValueError()
            seen.add(row['pid'])
        if window_pids - seen:
            raise ValueError()
        return rows
    except (OSError, subprocess.TimeoutExpired, ValueError, UnicodeError, TypeError, RecursionError) as exc:
        raise ValueError('无法完整检查游戏是否关闭，当前存档尚未改变；请稍后重试') from exc


def confirm_game_closed():
    if sys.platform != 'win32':
        raise ValueError('自动回档的游戏关闭检查目前仅支持 Windows')
    try:
        windows = game_window_pids()
    except (OSError, AttributeError) as exc:
        raise ValueError('无法检查游戏窗口，当前存档尚未改变；请稍后重试') from exc
    rows = read_processes(windows)
    blocked = []
    for row in rows:
        state, reason = classify_process(row, windows)
        if state != 'UNRELATED':
            blocked.append((row, state, reason))
    if not blocked:
        return
    known = [row for row, state, _ in blocked if state == 'GAME']
    if known:
        description = '、'.join(f'{row["name"]}（PID {row["pid"]}）' for row in known[:5])
        raise ValueError('请先完全退出破碎的像素地牢，再恢复或撤回。检测到游戏进程：' + description)
    description = '；'.join(f'{row["name"]}（PID {row["pid"]}）：{reason}' for row, _, reason in blocked[:5])
    raise ValueError('尚无法确认潜在游戏进程是否已关闭，当前存档尚未改变。' + description + '；请关闭该实例后重试。')
