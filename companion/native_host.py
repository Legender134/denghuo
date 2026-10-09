"""Bounded local JSON-lines bridge to the standard Windows controls helper."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from queue import Queue, Empty, Full
import subprocess
import threading
import uuid

from .paths import ROOT

VERSION, MAX_LINE = 1, 512 * 1024


class Value:
    def __init__(self, value='', changed=None):
        self.value, self.changed = value, changed

    def get(self):
        return self.value

    def set(self, value):
        if value != self.value:
            self.value = value
            if self.changed:
                self.changed()


class TextState:
    def __init__(self, text=''):
        self.text = text

    def configure(self, **values):
        if 'text' in values:
            self.text = values['text']

    def cget(self, key):
        return self.text if key == 'text' else None

    def get(self, *_):
        return self.text


class NativeWindow:
    def __init__(self, host, surface):
        self.host, self.surface = host, surface

    def withdraw(self):
        self.host.command('hide', surface=self.surface)

    def deiconify(self):
        self.host.command('show', surface=self.surface)

    def winfo_exists(self):
        return not self.host.closed

    def state(self):
        return 'normal' if self.host.visibility.get(self.surface) else 'withdrawn'


class NativeHost:
    """Only its own child is accepted; no external window styles are changed."""
    def __init__(self, root, dispatch, error):
        self.root, self.dispatch, self.error = root, dispatch, error
        self.session = uuid.uuid4().hex
        self.outgoing, self.incoming = Queue(maxsize=128), Queue(maxsize=128)
        self.process, self.closed, self.ready, self.failed = None, False, False, False
        self.visibility, self.handles = {}, {}
        self.serial, self.revision = 0, 0
        self.timer = root.after(40, self.poll)
        threading.Thread(target=self.start, daemon=True, name='native-helper-start').start()

    def start(self):
        try:
            helper = Path(os.environ.get('LAMP_NATIVE_HELPER', str(ROOT / 'native' / 'NativeCompanion.exe')))
            if not helper.is_file():
                raise OSError('原生控件程序缺失；请完整解压含 NativeCompanion.exe 的程序。源码开发请先运行 tools/build_native_helper.py。')
            self.process = subprocess.Popen([str(helper), self.session], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=False,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            for name, target in (('read', self.read), ('write', self.write), ('stderr', self.read_error)):
                threading.Thread(target=target, daemon=True, name='native-helper-'+name).start()
        except (OSError, ValueError) as exc:
            self.receive({'action': 'bridge_error', 'message': str(exc)})

    def receive(self, item):
        try:
            self.incoming.put(item, timeout=.5)
        except Full:
            logging.error('Native helper input queue full; retaining Python draft')

    def read(self):
        try:
            while not self.closed:
                line = self.process.stdout.readline(MAX_LINE+1)
                if not line:
                    break
                if len(line) > MAX_LINE or not line.endswith(b'\n'):
                    raise ValueError('原生窗口传输超出限制；草稿保留在本次会话')
                item = json.loads(line.decode('utf-8'))
                if not isinstance(item, dict) or item.get('version') != VERSION or item.get('session') != self.session:
                    raise ValueError('原生窗口协议不匹配')
                if item.get('action') == 'ready':
                    if item.get('pid') != self.process.pid:
                        raise ValueError('原生窗口进程身份不匹配')
                self.receive(item)
        except (OSError, ValueError, UnicodeError) as exc:
            self.receive({'action': 'bridge_error', 'message': str(exc)})
        finally:
            if not self.closed:
                self.receive({'action': 'bridge_error', 'message': '原生窗口已断开；本次草稿仍保留。请通过完整面板结束本次辅助后重新启动。'})

    def write(self):
        try:
            while not self.closed:
                try:
                    raw = self.outgoing.get(timeout=.2)
                except Empty:
                    continue
                self.process.stdin.write(raw)
                self.process.stdin.flush()
        except (OSError, ValueError) as exc:
            if not self.closed:
                self.receive({'action': 'bridge_error', 'message': str(exc)})

    def read_error(self):
        for line in iter(self.process.stderr.readline, b''):
            logging.warning('Native helper: %s', line[:2048].decode('utf-8', errors='replace').strip())

    def command(self, action, **payload):
        if self.closed or getattr(self, 'failed', False):
            return False
        self.serial += 1
        item = {'version': VERSION, 'session': self.session, 'request': self.serial,
                'revision': self.revision, 'action': action, **payload}
        raw = (json.dumps(item, ensure_ascii=False, allow_nan=False)+'\n').encode('utf-8')
        if len(raw) > MAX_LINE:
            self.error('原生窗口内容过大；请缩小结果范围，草稿仍保留。')
            return False
        try:
            self.outgoing.put_nowait(raw)
            return True
        except Full:
            self.error('原生窗口暂时繁忙；草稿仍保留，请稍后重试。')
            return False

    def poll(self):
        self.timer = None
        if self.closed:
            return
        for _ in range(48):
            try:
                item = self.incoming.get_nowait()
            except Empty:
                break
            if item.get('action') == 'bridge_error':
                if getattr(self, 'failed', False):
                    continue
                self.failed = True
                self.ready = False
                self.error(item['message'])
            elif getattr(self, 'failed', False):
                continue
            elif item.get('action') == 'ready':
                self.ready = True
                self.environment = {key: item.get(key) for key in ('pid', 'system_dpi', 'framework')}
                logging.info('Native helper ready: %s', self.environment)
                self.dispatch(item)
            else:
                self.dispatch(item)
        self.timer = self.root.after(40, self.poll)

    def is_foreground(self, surface, native):
        hwnd = self.handles.get(surface)
        return bool(self.process and hwnd and native.process(hwnd) == self.process.pid and native.foreground() == hwnd)

    def close(self):
        if self.closed:
            return
        self.command('shutdown')
        # Allow the writer to deliver normal shutdown without blocking the GUI.
        def finish():
            if self.process:
                try:
                    self.process.wait(timeout=1.5)
                except subprocess.TimeoutExpired:
                    self.process.terminate()  # Our child only, after orderly EOF request.
                for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                    try:
                        stream.close()
                    except (OSError, ValueError):
                        pass
            self.closed = True
        threading.Thread(target=finish, daemon=True, name='native-helper-close').start()
        if self.timer:
            self.root.after_cancel(self.timer)
            self.timer = None
