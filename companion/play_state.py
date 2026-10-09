"""Play display preferences and snapshot notices; never invent live game state."""
from __future__ import annotations

import json
import math
import hashlib
import threading
import uuid
from pathlib import Path
import time

from .hotkeys import DEFAULT_BINDINGS, normalize_chord

PLAY_DEFAULTS = {'enabled': True, 'alerts': True, 'anchor': 'top_left', 'offset_x': 16,
                 'offset_y': 100, 'font_scale': 1.0, 'opacity': .9,
                 'notice_seconds': 5, 'bindings': DEFAULT_BINDINGS}


def validate_preferences(row):
    if not isinstance(row, dict) or set(row) - set(PLAY_DEFAULTS):
        raise ValueError('游玩设置格式不正确')
    result = {**PLAY_DEFAULTS, 'bindings': dict(DEFAULT_BINDINGS)}
    for key, value in row.items():
        if key in ('enabled', 'alerts'):
            if type(value) is not bool:
                raise ValueError('游玩开关格式不正确')
        elif key == 'anchor':
            if value not in ('top_left', 'top_right', 'bottom_left', 'bottom_right'):
                raise ValueError('请选择显示位置')
        elif key in ('offset_x', 'offset_y'):
            if type(value) is not int or not 0 <= value <= 16384:
                raise ValueError('位置偏移需要是0–16384的整数')
        elif key in ('font_scale', 'opacity', 'notice_seconds'):
            low, high = {'font_scale': (1, 2), 'opacity': (.5, 1), 'notice_seconds': (3, 30)}[key]
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError('字号、背景或提示时间超出范围')
        elif key == 'bindings':
            if not isinstance(value, dict) or set(value) - set(DEFAULT_BINDINGS):
                raise ValueError('快捷键设置不正确')
            value = {**DEFAULT_BINDINGS, **{k: normalize_chord(v) for k, v in value.items()}}
            enabled = [v for v in value.values() if v]
            if len(enabled) != len(set(enabled)):
                raise ValueError('不同功能不能使用相同的快捷键')
        result[key] = value
    return result


class PlayPreferences:
    def __init__(self, directory):
        self.path = Path(directory) / 'play-mode.json'
        self.error = ''
        self.lock = threading.RLock()
        self.generation = 0
        self._disk_stamp = None
        self.values = validate_preferences({})
        try:
            with self.path.open('rb') as stream:
                raw = stream.read(16385)
            self._disk_stamp = hashlib.sha256(raw).hexdigest()
            if len(raw) > 16384:
                raise ValueError('游玩设置过大')
            self.values = validate_preferences(json.loads(raw.decode('utf-8-sig')))
        except FileNotFoundError:
            pass
        except (ValueError, OSError, RecursionError):
            self.error = '游玩设置无法读取，游玩显示已暂停；保存设置时会保留原文件。'
            self.values['enabled'] = False

    def update(self, patch, expected_generation=None):
        with self.lock:
            if expected_generation is not None and (type(expected_generation) is not int or expected_generation != self.generation):
                raise ValueError('游玩设置刚在另一窗口修改，请重新读取已保存设置；当前草稿仍保留')
            if not isinstance(patch, dict) or set(patch) - set(PLAY_DEFAULTS):
                raise ValueError('游玩设置格式不正确')
            clean = validate_preferences({**self.values, **patch})
            try:
                with self.path.open('rb') as stream:
                    original = stream.read(16385)
                current_stamp = hashlib.sha256(original).hexdigest()
            except FileNotFoundError:
                current_stamp = None
            if current_stamp != self._disk_stamp:
                raise ValueError('游玩设置文件刚被修改，请重新读取已保存设置；原文件与当前草稿仍保留')
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.error and self.path.exists():
                preserved = self.path.with_name(f'play-mode.recovery-{time.time_ns()}.json')
                with self.path.open('rb') as source, preserved.open('xb') as target:
                    while chunk := source.read(65536):
                        target.write(chunk)
            pending = self.path.with_name(self.path.name + '.' + uuid.uuid4().hex + '.pending')
            raw = json.dumps(clean, ensure_ascii=False, indent=2).encode('utf-8')
            try:
                with pending.open('xb') as stream:
                    stream.write(raw)
                pending.replace(self.path)
            finally:
                if pending.exists():
                    pending.unlink()
            self.values, self.error = clean, ''
            self._disk_stamp = hashlib.sha256(raw).hexdigest()
            self.generation += 1

    def reload(self):
        with self.lock:
            saved = type(self)(self.path.parent)
            self.values, self.error, self._disk_stamp = saved.values, saved.error, saved._disk_stamp
            self.generation += 1

def source_label(snap):
    if snap.get('waiting_for_save'):
        return '已就绪 · 等待游戏保存'
    if snap.get('error') or not snap.get('data'):
        return '局势不可读'
    if snap['settings']['mode'] == 'manual':
        return '手填局势已过期' if snap['stale'] else '手填局势 · 不自动跟随'
    age = max(0, int(snap.get('age_seconds') or 0))
    when = f'{age}秒前' if age < 60 else f'{age // 60}分钟前'
    return ('旧存档' if snap['stale'] else '存档快照') + ' · ' + when


def risk_summary(data, tip):
    kinds = {b.get('kind') for b in data.get('buffs', [])}
    blocked = bool(kinds & {'Paralysis', 'Frost', 'MagicalSleep', 'TimeStasis'})
    identity = tip['id']
    if blocked and identity not in ('zero_hp', 'berserk_zero'):
        return '快照中有行动限制，暂不能移动或用物品；解除后重新核对局势。'
    if identity == 'critical_hp':
        return '先停止自动探索，核对当前敌人、状态与可用的保命手段。'
    if identity in ('burning', 'ooze'):
        if 'Levitation' in kinds:
            return '快照中正在漂浮，经过水格不能灭火或清洗；先核对解除手段。'
        return ('先核对安全路线与行动状态；接触水可处理，但可能先受到一次伤害。')
    if identity == 'corrosion':
        return '核对当前酸蚀与安全路线；水不能照搬腐蚀淤泥的清洗方法。'
    if identity == 'dot':
        return '不要连续休息推进回合；先查看状态说明与剩余伤害。'
    if identity == 'roots':
        return '快照中不能靠走路脱身；核对远程、控制或已知可用传送。'
    if identity == 'zero_hp':
        return '核对游戏中的复活或结算界面，等待复活后或新一局的存档。'
    if identity == 'berserk_zero':
        return '不能仅凭零生命判断倒下；核对狂暴状态与剩余护盾。'
    return '按速查键查看完整建议；请对照当前游戏画面。'


class SnapshotNotices:
    """New save conditions only. Startup, stale and manual state do not pop alerts."""
    def __init__(self):
        self.identity = None
        self.seen = set()
        self.initialized = False
        self.notice = None
        self.until = 0
        self.last_modified = None

    def update(self, snap, now, duration=5, enabled=True):
        data = snap.get('data')
        identity = (snap['settings']['save_root'], snap.get('active_slot'), snap.get('run_id'),
                    snap['settings']['mode'])
        tips = [t for t in (data or {}).get('tips', []) if t['severity'] in ('critical', 'warning')]
        current = {(t['id'], t['severity']) for t in tips}
        eligible = bool(enabled and data and not snap.get('error') and not snap.get('stale')
                        and snap['settings']['mode'] == 'save')
        new_instance = not self.initialized or self.identity != identity
        if new_instance:
            self.notice, self.until = None, 0
        changed = self.last_modified != snap.get('modified')
        appeared = current - self.seen
        if eligible and not new_instance and changed and appeared:
            selected = next(t for t in tips if (t['id'], t['severity']) in appeared)
            self.notice = {'title': '新存档提示 · ' + selected['title'],
                           'body': risk_summary(data, selected), 'severity': selected['severity'],
                           'id': selected['id']}
            self.until = now + duration
        if not eligible or (self.notice and self.notice['id'] not in {t['id'] for t in tips}):
            self.notice, self.until = None, 0
        self.initialized, self.identity = True, identity
        self.seen, self.last_modified = current, snap.get('modified')
        return self.notice if self.notice and now < self.until else None


def place(rect, width, height, preferences, scale=1):
    left, top, right, bottom = rect
    xpad, ypad = round(preferences['offset_x'] * scale), round(preferences['offset_y'] * scale)
    x = right - width - xpad if preferences['anchor'].endswith('right') else left + xpad
    y = bottom - height - ypad if preferences['anchor'].startswith('bottom') else top + ypad
    return (max(left, min(x, max(left, right - width))),
            max(top, min(y, max(top, bottom - height))))
