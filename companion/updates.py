"""Optional HTTPS update checks and explicitly requested installer downloads."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from . import __version__
from .backups import unlinked

UPDATE_BASE = 'https://room.riftbuddy.dpdns.org/denghuo/'
MAX_INSTALLER = 256 * 1024 * 1024


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r'(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})', value):
        raise ValueError('更新版本格式不正确')
    return tuple(map(int, value.split('.')))


def validate_manifest(raw):
    if not isinstance(raw, dict) or raw.get('format') != 1 or raw.get('application') != 'denghuo':
        raise ValueError('更新清单不属于灯火')
    version_tuple(raw.get('version'))
    installer = raw.get('installer')
    if (not isinstance(installer, dict) or installer.get('filename') != 'Denghuo-Setup.exe'
            or type(installer.get('size')) is not int or not 1 <= installer['size'] <= MAX_INSTALLER
            or not isinstance(installer.get('sha256'), str)
            or not re.fullmatch('[a-f0-9]{64}', installer['sha256'])):
        raise ValueError('更新安装包信息不正确')
    notes = raw.get('notes', '')
    if not isinstance(notes, str) or len(notes) > 1200:
        raise ValueError('更新说明过长')
    return {'version': raw['version'], 'installer': dict(installer), 'notes': notes}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('更新地址发生变化，请稍后重试')


def open_update(name):
    # Neither a server manifest nor a local HTTP request can choose an executable URL.
    if name not in ('latest.json', 'Denghuo-Setup.exe'):
        raise ValueError('不支持的更新文件')
    request = Request(UPDATE_BASE + name, headers={
        'User-Agent': 'Denghuo/' + __version__, 'Cache-Control': 'no-cache',
        'Accept-Encoding': 'identity'})
    return build_opener(NoRedirect()).open(request, timeout=10)


class Updates:
    def __init__(self, directory, stop, *, opener=open_update, current=__version__, can_install=None):
        self.directory = Path(directory)
        self.stop = stop
        self.opener = opener
        self.current = current
        self.can_install = (os.name == 'nt' and getattr(sys, 'frozen', False)
                            if can_install is None else can_install)
        self.lock = threading.RLock()
        self.worker = None
        self.download_cancel = threading.Event()
        self.release = None
        self.pending_exit = None
        self.state = {'state': 'idle', 'current_version': current, 'latest_version': '',
                      'message': '启动时检查更新', 'notes': '', 'progress': 0,
                      'can_install': self.can_install}

    def _set(self, **values):
        with self.lock:
            self.state.update(values)

    def snapshot(self, exit_state=None):
        with self.lock:
            if self.pending_exit and exit_state and (exit_state.get('id') != self.pending_exit
                    or exit_state.get('phase') == 'cancelled'):
                self.pending_exit = None
                self.state.update(state='ready', message='安装已取消，安装包仍可使用')
            return dict(self.state)

    def _start(self, state, message, work):
        with self.lock:
            if self.stop.is_set():
                raise ValueError('助手正在退出，请下次启动后更新')
            if self.worker is not None and self.worker.is_alive():
                return dict(self.state)
            if self.pending_exit:
                raise ValueError('请先完成或取消退出确认')
            ready_release = self.release if self.state['state'] == 'ready' else None
            self.state.update(state=state, message=message, progress=0)
            if state == 'downloading':
                self.download_cancel.clear()
            def run():
                try:
                    work()
                except Exception as exc:
                    if state == 'downloading' and self._download_cancelled():
                        return
                    if isinstance(exc, (URLError, TimeoutError)):
                        message = '无法连接更新服务，请稍后重试'
                    elif isinstance(exc, OSError):
                        message = '无法保存更新文件，请检查磁盘空间与权限'
                    else:
                        message = str(exc) if isinstance(exc, ValueError) else '更新未完成，请稍后重试'
                    if (state == 'checking' and ready_release is self.release and ready_release
                            and self._verified(self.directory / 'Denghuo-Setup.exe', ready_release['installer'])):
                        self._set(state='ready', progress=100, message=message+'；已校验安装包仍可安装')
                    else:
                        self._set(state='error', message=message)
            self.worker = threading.Thread(target=run, name='application-update', daemon=True)
            self.worker.start()
            return dict(self.state)

    def check(self):
        return self._start('checking', '正在检查更新…', self._check)

    def _check(self):
        with self.opener('latest.json') as response:
            raw = response.read(16385)
        if len(raw) > 16384:
            raise ValueError('更新清单过大，请稍后重试')
        try:
            release = validate_manifest(json.loads(raw))
        except (ValueError, UnicodeError, RecursionError):
            raise ValueError('更新信息暂时不可用，请稍后重试') from None
        if self.stop.is_set():
            return
        newer = version_tuple(release['version']) > version_tuple(self.current)
        ready = newer and self._verified(self.directory / 'Denghuo-Setup.exe', release['installer'])
        with self.lock:
            self.release = release if newer else None
            self.state.update(state='ready' if ready else 'available' if newer else 'current', latest_version=release['version'],
                progress=100 if ready else 0, notes=release['notes'] if newer else '', message=('安装包已校验，可以安装' if ready else f"新版 {release['version']} 可用" if newer else
                    '已是最新版本' if release['version'] == self.current else '当前无需更新'))

    def _path(self, name):
        unlinked(self.directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        return unlinked(self.directory / name)

    def _verified(self, path, expected):
        try:
            path = unlinked(path)
            if not path.is_file() or path.stat().st_size != expected['size']:
                return False
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                if stream.read(2) != b'MZ':
                    return False
                stream.seek(0)
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
            return digest.hexdigest() == expected['sha256']
        except OSError:
            return False

    def download(self):
        with self.lock:
            if not self.release:
                raise ValueError('请先检查是否有新版')
            release = self.release
        return self._start('downloading', '正在下载安装包…', lambda: self._download(release))

    def _download(self, release):
        expected = release['installer']
        target = self._path('Denghuo-Setup.exe')
        if self._verified(target, expected):
            self._set(state='ready', progress=100, message='安装包已校验，可以安装')
            return
        if shutil.disk_usage(self.directory).free < expected['size'] + 16 * 1024 * 1024:
            raise ValueError('磁盘空间不足，请腾出空间后重试')
        pending = self._path('Denghuo-Setup.part')
        size, digest, deadline = 0, hashlib.sha256(), time.monotonic() + 300
        try:
            with self.opener('Denghuo-Setup.exe') as response, pending.open('wb') as output:
                while True:
                    if self.stop.is_set():
                        return
                    if self._download_cancelled():
                        return
                    if time.monotonic() > deadline:
                        raise ValueError('下载超时，请稍后重试')
                    chunk = response.read1(65536)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > expected['size']:
                        raise ValueError('安装包已更新或大小不符，请重新检查更新')
                    output.write(chunk)
                    digest.update(chunk)
                    self._set(progress=min(99, size * 100 // expected['size']))
                output.flush()
                os.fsync(output.fileno())
            if size != expected['size'] or digest.hexdigest() != expected['sha256'] or not self._verified(pending, expected):
                raise ValueError('安装包校验未通过，请重新检查更新')
            if self._download_cancelled():
                return
            unlinked(target)
            pending.replace(target)
            self._set(state='ready', progress=100, message='安装包已校验，可以安装')
        finally:
            # These two fixed cache names belong exclusively to this updater.
            if pending.exists() and not pending.is_symlink():
                pending.unlink()

    def cancel_download(self):
        with self.lock:
            if self.state['state'] == 'downloading':
                self.download_cancel.set()
                self.state['message'] = '正在取消下载…'
            return dict(self.state)

    def _download_cancelled(self):
        if self.download_cancel.is_set():
            self._set(state='available', message='已取消下载', progress=0)
            return True
        return False

    def install(self, request_exit):
        with self.lock:
            if not self.can_install:
                raise ValueError('源码运行时请使用正式安装版更新')
            if self.state['state'] != 'ready' or not self.release:
                raise ValueError('请先下载并校验安装包')
            release = self.release
        def prepare():
            if not self._verified(self._path('Denghuo-Setup.exe'), release['installer']):
                raise ValueError('安装包已变化，请重新下载')
            state = request_exit()
            with self.lock:
                self.pending_exit = state['id']
                self.state.update(state='installing', message='处理未完成工作后安装')
        return self._start('verifying', '正在核对安装包…', prepare)

    def launch_after_exit(self, exit_state):
        # A later ordinary exit must never install an update whose confirmation was cancelled.
        if self.worker is not None and self.state['state'] in ('verifying', 'installing'):
            self.worker.join(timeout=1)
        with self.lock:
            if (not self.can_install or not self.pending_exit or exit_state.get('id') != self.pending_exit
                    or exit_state.get('phase') != 'finished'):
                return False
            expected = self.release['installer']
            self.pending_exit = None
        path = self._path('Denghuo-Setup.exe')
        if not self._verified(path, expected):
            raise ValueError('安装包已变化，尚未运行；请重新启动灯火检查更新')
        # Interactive Inno Setup: never force-close applications or silently replace data.
        subprocess.Popen([str(path), '/DIR=' + str(Path(sys.executable).parent), '/NORESTART'],
                         close_fds=True)
        return True
