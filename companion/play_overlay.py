"""Small game-bound displays and native numeric lookup. No game input or save writes."""
from __future__ import annotations

import logging
from datetime import datetime
from queue import Queue, Empty
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import ttk, simpledialog, messagebox

from .play_state import SnapshotNotices, place, source_label
from .quick_reference import detail_text, peek_reference
from .windows import WindowsDisplay

BG, FG, GOLD, KEY = '#202a21', '#e7edde', '#dec38c', '#010203'


class FloatingCard:
    """Separate background and opaque text layers; both are passive while playing."""
    def __init__(self, root, native, title):
        self.native = native
        self.background = tk.Toplevel(root)
        self.window = tk.Toplevel(root)
        self.visible = False
        self.geometry = None
        self.signature = None
        for window in (self.background, self.window):
            window.withdraw()
            window.title(title)
            window.overrideredirect(True)
        self.background.configure(bg=BG)
        self.window.configure(bg=KEY)
        self.window.attributes('-transparentcolor', KEY)
        self.labels = []
        for _ in range(3):
            label = tk.Label(self.window, bg=KEY, fg=FG, justify='left', anchor='w', borderwidth=0)
            self.labels.append(label)
        self.window.update_idletasks()
        self.background.update_idletasks()
        try:
            self.native.passive(self.background)
            self.native.passive(self.window)
        except (OSError, tk.TclError):
            self.window.destroy()
            self.background.destroy()
            raise

    def content(self, heading, body, footer, scale, width=300, opacity=.9, severity='info'):
        signature = heading, body, footer, scale, width, opacity, severity
        if signature != self.signature:
            self.signature = signature
            padding = round(8 * scale)
            for index, (label, text) in enumerate(zip(self.labels, (heading, body, footer))):
                label.pack_forget()
                if not text:
                    continue
                color = '#ffd6c5' if index == 0 and severity == 'critical' else GOLD if index == 0 else FG
                label.configure(text=text, fg=color, wraplength=max(100, width - 2 * padding),
                                font=('Microsoft YaHei UI', -round((19 if index != 2 else 17) * scale),
                                      'bold' if index == 0 else 'normal'))
                label.pack(fill='x', padx=padding, pady=(padding if index == 0 else 3, padding if index == 2 else 3))
            self.background.attributes('-alpha', opacity)
            self.window.update_idletasks()
        return width, max(round(32 * scale), self.window.winfo_reqheight())

    def show(self, x, y, width, height, editing=False):
        geometry = x, y, width, height, editing
        if not self.visible:
            for window in (self.background, self.window):
                self.native.passive(window)
                window.deiconify()
            self.visible = True
        if geometry != self.geometry:
            self.native.passive(self.background)
            self.native.passive(self.window, click_through=not editing)
            self.native.show(self.background, x, y, width, height)
            self.native.show(self.window, x, y, width, height)
            self.geometry = geometry

    def hide(self):
        if self.visible:
            self.window.withdraw()
            self.background.withdraw()
            self.visible, self.geometry = False, None

    def destroy(self):
        self.hide()
        self.window.destroy()
        self.background.destroy()


class ReferenceWorker:
    def __init__(self, session):
        self.session = session
        self.tasks, self.results = Queue(maxsize=1), Queue()
        self.stop = threading.Event()
        self.ticket = 0
        self.thread = threading.Thread(target=self.run, daemon=True, name='numeric-reference')
        self.thread.start()

    def request(self, kind, *args):
        self.ticket += 1
        try:
            self.tasks.get_nowait()
        except Empty:
            pass
        self.tasks.put_nowait((self.ticket, kind, args))
        return self.ticket

    def run(self):
        while not self.stop.is_set():
            try:
                ticket, kind, args = self.tasks.get(timeout=.2)
            except Empty:
                continue
            try:
                result = (peek_reference(self.session, *args) if kind == 'peek'
                          else self.session.values.detail(*args))
                self.results.put((ticket, kind, result, None))
            except Exception:
                logging.exception('Numeric reference unavailable')
                self.results.put((ticket, kind, None, '数值暂不可用，请核对参数；完整解压程序后重试。'))


from .native_workspace import NumericLookup


class PlayDisplay:
    def __init__(self, manager, native=None):
        self.manager = manager
        self.native = native or WindowsDisplay()
        self.preferences = manager.session.play_preferences
        self.state = self.preferences.values
        self.applied_revision = self.preferences.generation
        self.worker = ReferenceWorker(manager.session)
        created = []
        try:
            for attr, title in (('status', '游玩状态'), ('notice', '存档提示'), ('peek', '游戏速查')):
                card = FloatingCard(manager.root, self.native, '灯火 · ' + title)
                setattr(self, attr, card)
                created.append(card)
        except (OSError, tk.TclError):
            self.worker.stop.set()
            for card in created:
                card.destroy()
            raise
        self.notices = SnapshotNotices()
        self.lookup = None
        self.snap = None
        self.current_notice = None
        self.game = None
        self.peek_open, self.peek_key, self.peek_data, self.peek_ticket = False, None, None, None
        self.pinned = None
        self.pinned_note = ''
        self.editing, self.drag = False, None
        self.timer = None
        self.closed = False
        for widget in (self.status.window, *self.status.labels):
            widget.bind('<ButtonPress-1>', self.drag_start)
            widget.bind('<B1-Motion>', self.drag_move)
            widget.bind('<ButtonRelease-1>', self.drag_end)
            widget.bind('<Double-Button-1>', lambda _: self.lock_layout())
        self.timer = self.manager.root.after(200, self.poll)

    def pixels(self, value):
        return round(value * self.manager.ui_scale * self.state['font_scale'])

    def update(self, snap):
        self.snap = snap
        if self.lookup is not None:
            if not self.lookup.query.get().strip() and self.lookup.workspace_revision != snap.get('workspace_revision'):
                self.lookup.search(preserve_detail=True)
            self.lookup.refresh_origin(snap)
        self.current_notice = self.notices.update(snap, time.monotonic(), self.state['notice_seconds'], self.state['alerts'])

    def in_game(self):
        return self.native.game() is not None

    def apply_preferences(self):
        self.state = self.preferences.values
        self.applied_revision = self.preferences.generation
        self.peek_key = None
        if not self.state['enabled']:
            self.peek_open = False
            self.hide()

    def save(self, patch, expected_generation=None):
        receipt = self.preferences.update(patch, expected_generation=expected_generation)
        self.manager.apply_play_settings()
        return receipt

    def toggle(self):
        self.save({'enabled': not self.state['enabled']})
        if not self.state['enabled']:
            self.peek_open = False
            self.hide()

    def toggle_peek(self):
        if (self.lookup and self.lookup.visible()
                and self.lookup.foreground()):
            self.lookup.hide()
            return
        if not self.in_game():
            self.open_lookup()
            return
        if not self.state['enabled']:
            self.save({'enabled': True})
        self.peek_open = not self.peek_open
        self.peek_key = None

    def open_lookup(self):
        self.peek_open = False
        self.peek.hide()
        if self.lookup is None:
            self.lookup = NumericLookup(self)
        self.lookup.show()

    def lock_layout(self):
        self.editing, self.drag = False, None

    def unlock_layout(self):
        self.save({'enabled': True})
        self.editing = True
        self.manager.hide_to_tray()

    def drag_start(self, event):
        if self.editing and self.status.geometry:
            x, y = self.status.geometry[:2]
            self.drag = event.x_root - x, event.y_root - y

    def drag_move(self, event):
        if self.drag and self.game:
            x, y = event.x_root - self.drag[0], event.y_root - self.drag[1]
            width, height = self.status.geometry[2:4]
            rect = self.game['rect']
            x = max(rect[0], min(x, rect[2] - width))
            y = max(rect[1], min(y, rect[3] - height))
            self.status.show(x, y, width, height, editing=True)

    def drag_end(self, _=None):
        if self.drag and self.game:
            x, y = self.status.geometry[:2]
            scale = self.manager.ui_scale
            try:
                self.save({'anchor': 'top_left', 'offset_x': max(0, round((x - self.game['rect'][0]) / scale)),
                           'offset_y': max(0, round((y - self.game['rect'][1]) / scale))})
            except (ValueError, OSError):
                logging.exception('Unable to save play position')
        self.drag = None

    def hide(self):
        for card in (self.status, self.notice, self.peek):
            card.hide()

    def poll(self):
        self.timer = None
        if self.closed:
            return
        try:
            while True:
                ticket, kind, result, error = self.worker.results.get_nowait()
                if kind == 'detail' and self.lookup and ticket == self.lookup.ticket:
                    self.lookup.render(result, error)
                elif kind == 'peek' and ticket == self.peek_ticket:
                    self.peek_data = result or {'title': '速查暂不可用', 'source': '', 'text': error, 'note': ''}
                    if self.pinned and self.pinned_note:
                        self.peek_data['note'] = '\n'.join(filter(None, (self.peek_data.get('note'), '用户用途/假设备注（未验证）：'+self.pinned_note)))
        except Empty:
            pass
        try:
            self.game = self.native.game()
            if self.game and self.state['enabled']:
                native_ui = getattr(self.manager, 'native_ui', None)
                if native_ui and native_ui.host.visibility.get('manager'):
                    self.manager.hide_to_tray()
                self.draw()
            else:
                self.peek_open = False
                self.hide()
        except (OSError, tk.TclError):
            logging.exception('Play display unavailable; manager remains accessible')
            self.hide()
        self.timer = self.manager.root.after(200, self.poll)

    def show_pair(self, card, x, y, width, height, other_width, other_height, gap):
        left, top, right, bottom = self.game['rect']
        if height + gap + other_height > bottom - top:
            return False
        if self.state['anchor'].startswith('bottom'):
            y = max(y, top + other_height + gap)
            other_y = y - gap - other_height
        else:
            y = min(y, bottom - height - gap - other_height)
            other_y = y + height + gap
        other_x = x + width - other_width if self.state['anchor'].endswith('right') else x
        other_x = max(left, min(other_x, right - other_width))
        self.status.show(x, y, width, height)
        card.show(other_x, other_y, other_width, other_height)
        return True

    def show_combined(self, card, width, height):
        rect = self.game['rect']
        if height > rect[3] - rect[1]:
            card.hide()
            return False
        x, y = place(rect, width, height, self.state, self.manager.ui_scale)
        self.status.hide()
        card.show(x, y, width, height)
        return True

    def draw(self):
        if not self.snap or not self.game:
            return
        rect = self.game['rect']
        scale = self.manager.ui_scale * self.state['font_scale']
        gap = round(7 * scale)
        short_source = ('等待保存' if self.snap.get('waiting_for_save') else
                        '局势不可读' if self.snap.get('error') or not self.snap.get('data') else
                        '手填局势' if self.snap['settings']['mode'] == 'manual' else
                        '旧快照' if self.snap['stale'] else '存档快照')
        health = self.snap.get('backup_health', {})
        backup = health.get('state')
        backup_text = {'blocked': '备份受阻', 'paused': '备份暂停', 'protected': '保存已备份'}.get(backup, '等待保存')
        if backup == 'waiting' and health.get('last_save_protected'):
            backup_text = '上次保存已备份'
        heading = '拖动入口 · 双击锁定' if self.editing else f'灯火 · {short_source} · {backup_text}'
        data = self.snap.get('data') or {}
        hero = data.get('hero')
        tip = next((tip for tip in data.get('tips', []) if tip['severity'] in ('critical', 'warning')), None)
        summary = (f"HP {hero['hp']:g}/{hero['ht']:g} · " + (tip['title'] if tip else '暂无特殊风险')) if hero else ''
        severity = tip['severity'] if tip and not self.snap['stale'] else 'info'
        width = min(self.pixels(290), rect[2] - rect[0])
        width, height = self.status.content(heading, summary, '', scale, width, self.state['opacity'], severity)
        if height > rect[3] - rect[1]:
            self.hide()
            return
        x, y = place(rect, width, height, self.state, self.manager.ui_scale)
        if not self.drag:
            self.status.show(x, y, width, height, self.editing)
        notice = self.current_notice
        if notice and time.monotonic() < self.notices.until and not self.editing and not self.peek_open:
            caption = source_label(self.snap) + (f" · HP {hero['hp']:g}/{hero['ht']:g}" if hero else '')
            w, h = self.notice.content(notice['title'], notice['body'], caption, scale,
                                       min(self.pixels(340), rect[2] - rect[0]), self.state['opacity'], notice['severity'])
            if not self.show_pair(self.notice, x, y, width, height, w, h, gap):
                w, h = self.notice.content(heading+'\n'+notice['title'], notice['body'], caption, scale,
                                           min(self.pixels(340), rect[2] - rect[0]), self.state['opacity'], notice['severity'])
                self.show_combined(self.notice, w, h)
        else:
            self.notice.hide()
        if self.peek_open and not self.editing:
            key = self.snap['revision'], self.snap.get('error'), self.snap['stale'], repr(self.pinned)
            if key != self.peek_key:
                self.peek_key, self.peek_data = key, None
                self.peek_ticket = self.worker.request('peek', self.snap, self.pinned)
            data = self.peek_data or {'title': '灯火速查', 'source': source_label(self.snap), 'text': '正在读取数值…', 'note': ''}
            source = data['source'] if self.pinned else source_label(self.snap)
            controls = self.shortcut_label('library', '手册')+' · '+self.shortcut_label('quick', '收起')
            footer = data['note']+'\n'+controls
            w, h = self.peek.content(data['title'] + '\n' + source, data['text'], footer, scale,
                                     min(self.pixels(380), rect[2] - rect[0]), self.state['opacity'])
            if h + gap + height > rect[3] - rect[1]:
                w, h = self.peek.content(data['title'], source + '\n该条目较长，打开手册查看完整数值与条件。',
                                         controls, scale, min(self.pixels(380), rect[2] - rect[0]), self.state['opacity'])
            if not self.show_pair(self.peek, x, y, width, height, w, h, gap):
                body = '\n'.join(part for part in (data['title'], source, summary, '打开手册查看完整数值与条件。') if part)
                w, h = self.peek.content(heading, body,
                                         controls, scale, min(self.pixels(380), rect[2] - rect[0]), self.state['opacity'])
                if h > rect[3] - rect[1]:
                    w, h = self.peek.content(heading, data['title']+'\n'+source+'\n打开手册查看完整数值与条件。',
                                             controls, scale, min(self.pixels(380), rect[2] - rect[0]), self.state['opacity'])
                if not self.show_combined(self.peek, w, h):
                    for body in (summary, ''):
                        sw, sh = self.status.content(heading, body, controls, scale, width, self.state['opacity'], severity)
                        if sh <= rect[3] - rect[1]:
                            sx, sy = place(rect, sw, sh, self.state, self.manager.ui_scale)
                            self.status.show(sx, sy, sw, sh)
                            break
                    else:
                        self.status.content(heading, summary, '', scale, width, self.state['opacity'], severity)
        else:
            self.peek.hide()

    def shortcut_label(self, command, label):
        caps = self.manager.session.ui_capabilities
        chord = self.state['bindings'][command]
        if (chord and caps.get('hotkeys_ready') and caps.get('bindings', {}).get(command) == chord
                and chord not in caps.get('hotkeys_unavailable', [])):
            return chord+' '+label
        return label+'键未生效（管理窗口可打开）'

    def close(self):
        self.closed = True
        if self.timer:
            self.manager.root.after_cancel(self.timer)
            self.timer = None
        self.worker.stop.set()
        if self.lookup:
            self.lookup.destroy()
        for card in (self.status, self.notice, self.peek):
            card.destroy()
