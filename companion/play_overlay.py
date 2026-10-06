"""Small game-bound displays and native numeric lookup. No game input or save writes."""
from __future__ import annotations

import logging
from queue import Queue, Empty
import threading
import time
import tkinter as tk
from tkinter import ttk

from .play_state import PlayPreferences, SnapshotNotices, place, source_label
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


class NumericLookup:
    def __init__(self, owner):
        self.owner = owner
        self.window = tk.Toplevel(owner.manager.root)
        self.window.withdraw()
        self.window.title('灯火 · 数值速查')
        self.window.configure(bg=BG)
        self.window.attributes('-topmost', True)
        self.return_target = None
        self.window.minsize(min(owner.pixels(340), self.window.winfo_screenwidth()-40),
                            min(owner.pixels(300), self.window.winfo_screenheight()-80))
        self.window.geometry(f'{min(owner.pixels(430), self.window.winfo_screenwidth()-40)}x'
                             f'{min(owner.pixels(570), self.window.winfo_screenheight()-80)}')
        self.window.protocol('WM_DELETE_WINDOW', self.hide)
        self.window.bind('<Escape>', lambda _: self.hide())
        self.window.bind('<MouseWheel>', self.scroll_parameters, add='+')
        self.query = tk.StringVar()
        self.entry = ttk.Entry(self.window, textvariable=self.query)
        self.entry.pack(fill='x', padx=12, pady=(12, 6))
        self.entry.bind('<KeyRelease>', self.schedule_search)
        row = tk.Frame(self.window, bg=BG)
        row.pack(fill='x', padx=12)
        self.count = tk.Label(row, text='', bg=BG, fg=FG, anchor='w')
        self.count.pack(side='left')
        tk.Button(row, text='固定到游戏速查', command=self.pin, bg=BG, fg=GOLD, relief='flat').pack(side='right')
        tk.Button(row, text='清除固定', command=self.clear_pin, bg=BG, fg=GOLD, relief='flat').pack(side='right')
        self.list = tk.Listbox(self.window, height=4, bg=BG, fg=FG, selectbackground='#435944',
                               activestyle='none', exportselection=False)
        self.list.pack(fill='x', padx=12, pady=6)
        self.list.bind('<<ListboxSelect>>', lambda _: self.select())
        self.param_holder = tk.Frame(self.window, bg=BG)
        self.param_holder.pack(fill='x', padx=12)
        self.param_canvas = tk.Canvas(self.param_holder, bg=BG, height=0, highlightthickness=0)
        self.param_scroll = ttk.Scrollbar(self.param_holder, command=self.param_canvas.yview)
        self.param_canvas.configure(yscrollcommand=self.param_scroll.set)
        self.param_scroll.pack(side='right', fill='y')
        self.param_canvas.pack(side='left', fill='x', expand=True)
        self.params = tk.Frame(self.param_canvas, bg=BG)
        self.params_window = self.param_canvas.create_window(0, 0, window=self.params, anchor='nw')
        self.params.bind('<Configure>', lambda _: self.param_canvas.configure(scrollregion=self.param_canvas.bbox('all')))
        self.param_canvas.bind('<Configure>', lambda e: self.param_canvas.itemconfigure(self.params_window, width=e.width))
        self.calculate_button = ttk.Button(self.window, text='按所填参数计算', command=self.calculate)
        self.origin = tk.Label(self.window, text='百科参数为参考示例，请按游戏核对。', bg=BG, fg=GOLD,
                               anchor='w', justify='left', wraplength=owner.pixels(395))
        self.origin.pack(fill='x', padx=12, pady=5)
        body = tk.Frame(self.window, bg=BG)
        body.pack(fill='both', expand=True, padx=12, pady=(0, 12))
        self.text = tk.Text(body, wrap='word', bg=BG, fg=FG, font=('Microsoft YaHei UI', 11),
                            relief='flat', state='disabled', padx=6, pady=6)
        scroll = ttk.Scrollbar(body, command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.text.pack(side='left', fill='both', expand=True)
        self.rows, self.inputs, self.variables = [], [], {}
        self.identity = None
        self.rendered, self.calculated = None, None
        self.dirty = False
        self.submitted = None
        self.pending = None
        self.ticket = None
        self.query.trace_add('write', lambda *_: self.schedule_search())
        self.search()

    def schedule_search(self, _=None):
        if self.pending:
            self.window.after_cancel(self.pending)
        self.pending = self.window.after(180, self.search)

    def scroll_parameters(self, event):
        widget = event.widget
        while widget is not None and widget is not self.window:
            if widget is self.param_holder:
                self.param_canvas.yview_scroll(-3 if event.delta > 0 else 3, 'units')
                return 'break'
            widget = getattr(widget, 'master', None)

    def search(self):
        self.pending = None
        result = self.owner.manager.session.catalog.search(self.query.get()[:200], limit=30)
        self.rows = result['entries']
        self.list.delete(0, 'end')
        for row in self.rows:
            self.list.insert('end', row['name'] + ' · ' + row['type_label'])
        self.count.configure(text=f"{result['total']}项 · 前{len(self.rows)}项")
        self.identity, self.rendered, self.calculated = None, None, None
        self.ticket = None
        self.clear_params()
        self.show_text('选择条目查看真实数值与适用条件。' if self.rows else '没有匹配条目，请换一个关键词。')

    def show_text(self, text):
        self.text.configure(state='normal')
        self.text.delete('1.0', 'end')
        self.text.insert('1.0', text)
        self.text.configure(state='disabled')
        self.text.yview_moveto(0)

    def clear_params(self):
        for child in self.params.winfo_children():
            child.destroy()
        self.inputs, self.variables = [], {}
        self.dirty = False
        self.param_canvas.configure(height=0)
        self.calculate_button.pack_forget()

    def select(self):
        selected = self.list.curselection()
        if not selected or selected[0] >= len(self.rows):
            return
        self.identity = self.rows[selected[0]]['id']
        self.rendered, self.calculated = None, None
        self.clear_params()
        self.origin.configure(text='百科 · 默认参数是示例；可在下方修改后计算。')
        self.ticket = self.owner.worker.request('detail', self.identity, {})
        self.submitted = None
        self.show_text('正在读取数值…')

    def render(self, detail, error=None):
        if self.submitted is not None and any(var.get().strip() != self.submitted.get(key)
                                             for key, var in self.variables.items()):
            self.changed()
            return
        if error:
            self.rendered, self.calculated = None, None
            self.show_text(error)
            return
        self.rendered = detail
        self.inputs = detail['inputs']
        if not self.variables:
            for index, field in enumerate(self.inputs):
                tk.Label(self.params, text=field['label'], bg=BG, fg=FG, anchor='w').grid(row=index, column=0, sticky='w')
                value = tk.StringVar(value=str(field['value']))
                self.variables[field['key']] = value
                ttk.Entry(self.params, textvariable=value, width=9).grid(row=index, column=1, sticky='e', padx=(8, 0), pady=2)
                value.trace_add('write', lambda *_: self.changed())
            self.params.columnconfigure(0, weight=1)
            self.params.update_idletasks()
            self.param_canvas.configure(height=min(self.owner.pixels(150), self.params.winfo_reqheight()) if self.inputs else 0)
            if self.inputs:
                self.calculate_button.pack(fill='x', padx=12, pady=4, before=self.origin)
        self.calculated = {f['key']: f['value'] for f in detail['inputs']}
        self.dirty = False
        self.origin.configure(text=f"百科 {detail['version']} · 按下方参数计算，未自动读取当前角色。")
        self.show_text(detail_text(detail))

    def changed(self):
        self.dirty = True
        self.origin.configure(text='参数已修改，旧结果不可继续参考；点击计算。')
        self.show_text('参数已修改，请重新计算。')

    def calculate(self):
        if not self.identity:
            return
        from .values import integer_parameters
        try:
            raw = {key: var.get().strip() for key, var in self.variables.items()}
            if any(not value for value in raw.values()):
                raise ValueError('请填写全部显示的参数')
            integer_parameters(raw)
        except (ValueError, OverflowError) as exc:
            self.origin.configure(text=str(exc))
            return
        self.ticket = self.owner.worker.request('detail', self.identity, raw)
        self.submitted = dict(raw)
        self.show_text('正在计算…')

    def pin(self):
        if not self.identity or self.dirty or self.rendered is None or self.calculated is None:
            self.origin.configure(text='先选择条目并计算有效参数，再固定参考。')
            return
        self.owner.pinned = (self.identity, dict(self.calculated))
        self.owner.peek_key = None
        self.origin.configure(text='已固定；返回游戏后按速查键查看。固定的是百科参考。')

    def clear_pin(self):
        self.owner.pinned = None
        self.owner.peek_key = None
        self.origin.configure(text='已清除固定；游戏速查恢复装备与局势快照。')

    def show(self):
        target = self.owner.native.game()
        if target or not self.visible():
            self.return_target = target
        self.window.deiconify()
        self.window.lift()
        self.entry.focus_force()  # Only explicit user lookup activates an input window.

    def hide(self):
        target, self.return_target = self.return_target, None
        self.owner.native.return_to_game(target)
        self.window.withdraw()

    def visible(self):
        return self.window.state() not in ('withdrawn', 'iconic')

    def destroy(self):
        if self.pending:
            self.window.after_cancel(self.pending)
        self.window.destroy()


class PlayDisplay:
    def __init__(self, manager, native=None):
        self.manager = manager
        self.native = native or WindowsDisplay()
        self.preferences = PlayPreferences(manager.session.config_path.parent)
        self.state = self.preferences.values
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
        self.current_notice = self.notices.update(snap, time.monotonic(), self.state['notice_seconds'], self.state['alerts'])

    def in_game(self):
        return self.native.game() is not None

    def save(self, patch):
        self.preferences.update(patch)
        self.state = self.preferences.values
        self.peek_key = None

    def toggle(self):
        self.save({'enabled': not self.state['enabled']})
        if not self.state['enabled']:
            self.peek_open = False
            self.hide()

    def toggle_peek(self):
        if (self.lookup and self.lookup.visible()
                and self.native.foreground() == self.native.hwnd(self.lookup.window)):
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
        except Empty:
            pass
        try:
            self.game = self.native.game()
            if self.game and self.state['enabled']:
                if self.manager.root.state() not in ('withdrawn', 'iconic'):
                    self.manager.hide_to_tray()
                self.draw()
            else:
                self.peek_open = False
                self.hide()
        except (OSError, tk.TclError):
            logging.exception('Play display unavailable; manager remains accessible')
            self.hide()
        self.timer = self.manager.root.after(200, self.poll)

    def draw(self):
        if not self.snap or not self.game:
            return
        rect = self.game['rect']
        scale = self.manager.ui_scale * self.state['font_scale']
        short_source = ('局势不可读' if self.snap.get('error') or not self.snap.get('data') else
                        '手填局势' if self.snap['settings']['mode'] == 'manual' else
                        '旧快照' if self.snap['stale'] else '存档快照')
        backup = self.snap.get('backup_health', {}).get('state')
        backup_text = {'blocked': '备份受阻', 'paused': '备份暂停', 'protected': '保存已备份'}.get(backup, '等待保存')
        heading = '拖动入口 · 双击锁定' if self.editing else f'灯火 · {short_source} · {backup_text}'
        width = min(self.pixels(290), rect[2] - rect[0])
        width, height = self.status.content(heading, '', '', scale, width, self.state['opacity'])
        if height > rect[3] - rect[1]:
            self.hide()
            return
        x, y = place(rect, width, height, self.state, self.manager.ui_scale)
        if not self.drag:
            self.status.show(x, y, width, height, self.editing)
        below = y + height + round(7 * scale)
        notice = self.current_notice
        if notice and time.monotonic() < self.notices.until and not self.editing and not self.peek_open:
            hero = (self.snap.get('data') or {}).get('hero', {})
            caption = source_label(self.snap) + (f" · HP {hero['hp']:g}/{hero['ht']:g}" if hero else '')
            w, h = self.notice.content(notice['title'], notice['body'], caption, scale,
                                       min(self.pixels(340), rect[2] - rect[0]), self.state['opacity'], notice['severity'])
            nx = min(x, max(rect[0], rect[2] - w))
            ny = below if below + h <= rect[3] else max(rect[1], y - h - round(7 * scale))
            if h <= rect[3] - rect[1]:
                self.notice.show(nx, ny, w, h)
            else:
                self.notice.hide()
        else:
            self.notice.hide()
        if self.peek_open and not self.editing:
            key = self.snap['revision'], self.snap.get('error'), self.snap['stale'], repr(self.pinned)
            if key != self.peek_key:
                self.peek_key, self.peek_data = key, None
                self.peek_ticket = self.worker.request('peek', self.snap, self.pinned)
            data = self.peek_data or {'title': '灯火速查', 'source': source_label(self.snap), 'text': '正在读取数值…', 'note': ''}
            source = data['source'] if self.pinned else source_label(self.snap)
            footer = data['note'] + '\n' + self.state['bindings']['library'] + ' 完整数值 · ' + self.state['bindings']['quick'] + ' 收起'
            w, h = self.peek.content(data['title'] + '\n' + source, data['text'], footer, scale,
                                     min(self.pixels(380), rect[2] - rect[0]), self.state['opacity'])
            if h > rect[3] - rect[1] - height - round(14 * scale):
                w, h = self.peek.content(data['title'], source + '\n该条目较长，打开手册查看完整数值与条件。',
                                         self.state['bindings']['library'] + ' 手册 · ' + self.state['bindings']['quick'] + ' 收起',
                                         scale, min(self.pixels(380), rect[2] - rect[0]), self.state['opacity'])
            nx = min(x, max(rect[0], rect[2] - w))
            ny = below if below + h <= rect[3] else max(rect[1], y - h - round(7 * scale))
            if h <= rect[3] - rect[1]:
                self.peek.show(nx, ny, w, h)
            else:
                self.peek.hide()
        else:
            self.peek.hide()

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
