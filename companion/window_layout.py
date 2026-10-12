"""Visible companion geometry, separate from game and personal preferences."""
from __future__ import annotations

import copy
import json
import logging
import hashlib
import time
from pathlib import Path
import threading

from .backups import atomic_json


DEFAULT = {'width': 480, 'height': 600, 'x': None, 'y': None,
           'game_x': 16, 'game_y': 16, 'collapsed': False, 'page': 'overview'}
PAGES = {'overview', 'inventory', 'lookup', 'equipment', 'alchemy', 'character',
         'floor', 'map', 'backups', 'plans', 'settings'}


def validate(raw):
    if not isinstance(raw, dict) or set(raw) != set(DEFAULT):
        raise ValueError('窗口布局格式不兼容；原件保留')
    for key in ('width', 'height', 'x', 'y', 'game_x', 'game_y'):
        value = raw[key]
        if key in ('x', 'y') and value is None:
            continue
        low, high = (320, 2400) if key in ('width', 'height') else (-32768, 32768)
        if type(value) is not int or not low <= value <= high:
            raise ValueError('窗口布局超出可用范围；原件保留')
    if type(raw['collapsed']) is not bool or raw['page'] not in PAGES:
        raise ValueError('窗口布局状态不兼容；原件保留')
    if (raw['x'] is None) != (raw['y'] is None):
        raise ValueError('窗口位置不完整；原件保留')
    return copy.deepcopy(raw)


class WindowLayout:
    def __init__(self, config):
        self.path = Path(config).with_name('companion-window.json')
        self.values, self.error = copy.deepcopy(DEFAULT), ''
        self.lock, self.pending, self.stop = threading.Lock(), threading.Event(), threading.Event()
        self.original = None
        self.reset_requested = False
        try:
            if self.path.exists():
                raw = self.path.read_bytes()
                if len(raw) > 8192:
                    raise ValueError('窗口布局文件过大；原件保留')
                self.values = validate(json.loads(raw))
                self.original = raw
        except (ValueError, OSError) as exc:
            self.error = str(exc)
        self.worker = threading.Thread(target=self.persist, daemon=True, name='companion-layout')
        self.worker.start()

    def update(self, raw, reset=False):
        value = validate(raw)
        with self.lock:
            self.values = value
            self.reset_requested = self.reset_requested or reset
        self.pending.set()

    def persist(self):
        while True:
            self.pending.wait(.2)
            if self.pending.is_set():
                self.pending.clear()
                with self.lock:
                    value = copy.deepcopy(self.values)
                    reset, self.reset_requested = self.reset_requested, False
                try:
                    # An unreadable/external layout is preserved; reset/move never deletes it.
                    current = self.path.read_bytes() if self.path.exists() else None
                    if reset and current != self.original and current is not None:
                        preserved = self.path.with_name('companion-window.before-reset-'+str(time.time_ns())+'-'+hashlib.sha256(current).hexdigest()[:12]+'.json')
                        with preserved.open('xb') as stream: stream.write(current)
                        if self.path.read_bytes() != current: raise ValueError('布局在恢复默认期间变化；原件与副本均保留，请重试')
                        self.original = current
                    if current != self.original:
                        self.error = '布局文件已被外部修改；本次位置仍保留，原文件未覆盖。'
                    else:
                        atomic_json(self.path, value)
                        self.original = self.path.read_bytes()
                        self.error = ''
                except (ValueError, OSError) as exc:
                    self.error = '布局尚未保存：' + str(exc)
                    logging.warning(self.error)
            if self.stop.is_set() and not self.pending.is_set():
                return

    def close(self):
        self.stop.set()
        self.worker.join(1)
