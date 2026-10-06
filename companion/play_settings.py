"""User-controlled play layout, readability and global shortcuts."""
import tkinter as tk
from tkinter import ttk

BG, FG = '#202a21', '#e7edde'
LABELS = {'capture': '立即备份已落盘进度', 'show': '显示管理窗口', 'library': '数值手册',
          'backups': '存档历史', 'play_toggle': '开关游玩显示', 'quick': '游戏内只读速查'}
ANCHORS = {'左上': 'top_left', '右上': 'top_right', '左下': 'bottom_left', '右下': 'bottom_right'}


class PlaySettings:
    def __init__(self, manager):
        self.manager = manager
        self.window = tk.Toplevel(manager.root)
        self.window.title('灯火 · 游玩设置')
        self.window.configure(bg=BG)
        self.window.attributes('-topmost', True)
        width = min(manager.pixels(440), self.window.winfo_screenwidth()-40)
        height = min(manager.pixels(570), self.window.winfo_screenheight()-80)
        self.window.geometry(f'{width}x{height}')
        self.window.minsize(min(width, manager.pixels(390)), min(height, manager.pixels(400)))
        self.window.protocol('WM_DELETE_WINDOW', self.window.withdraw)
        self.window.bind('<Escape>', lambda _: self.window.withdraw())
        self.vars = {}
        state = manager.play.state
        outer = tk.Frame(self.window, bg=BG)
        outer.pack(fill='both', expand=True)
        canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        scroll = ttk.Scrollbar(outer, command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        self.window.bind('<MouseWheel>', lambda event: canvas.yview_scroll(-3 if event.delta > 0 else 3, 'units'))
        body = tk.Frame(canvas, bg=BG, padx=16, pady=12)
        child = canvas.create_window(0, 0, window=body, anchor='nw')
        body.bind('<Configure>', lambda _: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(child, width=event.width))
        for key, text in (('enabled', '启用游玩显示（只跟随游戏前台）'), ('alerts', '新存档出现新风险时短暂提示')):
            value = tk.BooleanVar(value=state[key])
            self.vars[key] = value
            tk.Checkbutton(body, text=text, variable=value, bg=BG, fg=FG, selectcolor=BG,
                           activebackground=BG, activeforeground=FG).pack(anchor='w', pady=3)
        tk.Label(body, text='显示是存档参考，尚未读取游戏实时画面。\n正常备份不弹提示；地图点击穿过游玩显示。',
                 bg=BG, fg=FG, justify='left', anchor='w').pack(fill='x', pady=8)
        form = tk.Frame(body, bg=BG)
        form.pack(fill='x')
        anchor = tk.StringVar(value=next(k for k, v in ANCHORS.items() if v == state['anchor']))
        self.vars['anchor'] = anchor
        tk.Label(form, text='显示角落', bg=BG, fg=FG).grid(row=0, column=0, sticky='w')
        ttk.Combobox(form, textvariable=anchor, values=list(ANCHORS), state='readonly', width=12).grid(row=0, column=1, sticky='e')
        fields = [('offset_x', '横向边距'), ('offset_y', '纵向边距'), ('font_scale', '字号倍率（1–2）'),
                  ('opacity', '背景不透明度（0.5–1）'), ('notice_seconds', '短提醒时长（3–30秒）')]
        for row, (key, text) in enumerate(fields, 1):
            value = tk.StringVar(value=str(state[key]))
            self.vars[key] = value
            tk.Label(form, text=text, bg=BG, fg=FG).grid(row=row, column=0, sticky='w', pady=3)
            ttk.Entry(form, textvariable=value, width=12).grid(row=row, column=1, sticky='e', pady=3)
        form.columnconfigure(0, weight=1)
        tk.Label(body, text='全局快捷键：可修改或清空禁用；需含Ctrl或Alt。', bg=BG, fg=FG, anchor='w').pack(fill='x', pady=(12, 5))
        keys = tk.Frame(body, bg=BG)
        keys.pack(fill='x')
        self.bindings = {}
        for row, (command, label) in enumerate(LABELS.items()):
            value = tk.StringVar(value=state['bindings'][command])
            self.bindings[command] = value
            tk.Label(keys, text=label, bg=BG, fg=FG).grid(row=row, column=0, sticky='w', pady=2)
            ttk.Entry(keys, textvariable=value, width=18).grid(row=row, column=1, sticky='e', pady=2)
        keys.columnconfigure(0, weight=1)
        self.status = tk.Label(body, text=manager.play.preferences.error, bg=BG, fg='#ffd6c5',
                               anchor='w', justify='left', wraplength=manager.pixels(400))
        self.status.pack(fill='x', pady=8)
        buttons = tk.Frame(body, bg=BG)
        buttons.pack(fill='x', side='bottom')
        ttk.Button(buttons, text='保存', command=self.save).pack(side='right')
        ttk.Button(buttons, text='拖动位置', command=self.unlock).pack(side='left')
        ttk.Button(buttons, text='数值速查', command=manager.play.open_lookup).pack(side='left', padx=6)
        self.window.after(500, self.key_status)

    def key_status(self):
        if not self.window.winfo_exists():
            return
        keys = self.manager.hotkeys
        if keys and keys.ready.is_set() and keys.unavailable:
            self.status.configure(text='以下快捷键被占用，尚未生效：'+', '.join(keys.unavailable)+'。可修改后保存。')

    def save(self):
        try:
            patch = {k: v.get() for k, v in self.vars.items()}
            patch['anchor'] = ANCHORS[patch['anchor']]
            for key in ('offset_x', 'offset_y'):
                patch[key] = int(patch[key])
            for key in ('font_scale', 'opacity', 'notice_seconds'):
                patch[key] = float(patch[key])
            patch['bindings'] = {k: v.get() for k, v in self.bindings.items()}
            old = self.manager.play.state['bindings']
            self.manager.play.save(patch)
            if old != self.manager.play.state['bindings']:
                self.manager.rebind_hotkeys()
            self.status.configure(text='已保存；返回游戏后生效。文字保持清晰，透明度只作用于背景。')
            self.window.after(500, self.key_status)
            return True
        except (ValueError, KeyError, OSError, RuntimeError) as exc:
            self.status.configure(text=str(exc) or '设置未保存，请核对输入')
            return False

    def unlock(self):
        if not self.save():
            return
        self.manager.play.unlock_layout()
        self.window.withdraw()
