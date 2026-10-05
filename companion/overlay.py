"""Small native, always-on-top companion for windowed play."""

from datetime import datetime
import tkinter as tk
import time
import logging
import json
from queue import Queue, Empty
import threading
from tkinter import filedialog, ttk
import webbrowser

from .service import CST
from .paths import ROOT

BG, PANEL, FG, MUTED, GOLD = "#131b16", "#202a21", "#e7edde", "#9eb19d", "#dec38c"


class Overlay:
    def __init__(self, session, url, visible=True):
        self.session, self.url = session, url
        session.panel.bind(url)
        self.root = tk.Tk()
        if not visible:
            self.root.withdraw()
        self.root.title("灯火 · 地牢助手")
        try:
            self.root.iconbitmap(str(ROOT/'data/lamp.ico'))
        except tk.TclError:
            pass
        self.commands = Queue()
        self.tray = None
        self.hotkeys = None
        self.capture_pending = False
        # Tk point fonts already follow system DPI; geometry and wrap lengths are pixels.
        self.ui_scale = max(1.0, self.root.winfo_fpixels('1i') / 96.0)
        self.pixels = lambda value: round(value*self.ui_scale)
        self.root.configure(bg=BG)
        width = min(self.pixels(390), max(325, self.root.winfo_screenwidth()-40))
        height = min(self.pixels(650), max(360, self.root.winfo_screenheight()-self.pixels(140)))
        self.minimum_size = (min(width,self.pixels(325)), min(height,self.pixels(360)))
        self.expanded_size = (width, height)
        self.layout_path = session.config_path.parent/'overlay-layout.json'
        self.layout_timer = None
        layout = self.read_layout()
        if layout:
            factor = self.ui_scale/layout['scale']
            width = min(self.root.winfo_screenwidth(), max(self.minimum_size[0], round(layout['width']*factor)))
            height = min(self.root.winfo_screenheight()-self.pixels(40), max(self.minimum_size[1], round(layout['height']*factor)))
            self.expanded_size = (width, height)
        self.root.geometry(f"{width}x{height}+{max(0, self.root.winfo_screenwidth()-width-self.pixels(25))}+{self.pixels(60)}")
        self.root.minsize(*self.minimum_size)
        if layout:
            x = min(max(0, layout['x']), max(0, self.root.winfo_screenwidth()-width))
            y = min(max(0, layout['y']), max(0, self.root.winfo_screenheight()-height-self.pixels(35)))
            self.root.geometry(f'{width}x{height}+{x}+{y}')
        self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
        self.root.option_add("*Font", ("Microsoft YaHei UI", 10))
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=PANEL, background=PANEL, foreground=FG, arrowcolor=GOLD)
        self.compact = False
        self.last_key = None
        self.last_top = None
        self.action_error = ""
        self.action_error_until = 0
        self.tick_id = None
        self.titlebar = tk.Frame(self.root, bg=BG)
        self.titlebar.pack(fill="x", padx=17, pady=(14, 6))
        tk.Label(self.titlebar, text="◈  灯火", fg=GOLD, bg=BG, font=("Microsoft YaHei UI", 17, "bold")).pack(side="left")
        self.compact_button = self.button(self.titlebar, "收起", self.toggle_compact)
        self.compact_button.pack(side="right")
        self.button(self.titlebar, "面板 ↗", self.open_panel).pack(side="right", padx=6)
        self.button(self.titlebar, '退出', self.close).pack(side='right', padx=3)
        self.status = tk.Label(self.root, text="正在读取存档…", justify="left", anchor="w", wraplength=350, bg=BG, fg=GOLD, font=("Microsoft YaHei UI", 9))
        self.status.pack(fill="x", padx=18, pady=(3, 9))
        self.backup_status = tk.Label(self.root, text='正在检查自动备份…', bg=BG, fg=MUTED,
                                      justify='left', anchor='w', wraplength=350, font=('Microsoft YaHei UI', 9))
        self.backup_status.pack(fill='x', padx=18, pady=(0, 8))
        self.hero = tk.Label(self.root, text="等待冒险", justify="left", anchor="w", wraplength=350, bg=BG, fg=FG, font=("Microsoft YaHei UI", 12, "bold"))
        self.hero.pack(fill="x", padx=18)
        self.health = tk.Canvas(self.root, height=5, bg="#354133", highlightthickness=0)
        self.health.pack(fill="x", padx=18, pady=(9, 8))
        self.compact_tip = tk.Label(self.root, text='', bg=BG, fg=GOLD, anchor='w', justify='left',
                                    wraplength=350, font=('Microsoft YaHei UI', 9))
        self.metrics = tk.Label(self.root, text="", bg=BG, fg=MUTED, anchor="w", justify="left", wraplength=350, font=("Microsoft YaHei UI", 9))
        self.metrics.pack(fill="x", padx=18, pady=(0, 10))
        self.controls = tk.Frame(self.root, bg=BG)
        self.controls.pack(fill="x", padx=18, pady=(0, 12))
        self.slot = ttk.Combobox(self.controls, state="readonly", values=["自动跟随"]+[f"槽位 {i}" for i in range(1, 7)], width=12)
        self.slot.pack(side="left")
        self.slot.current(0)
        self.slot.bind("<<ComboboxSelected>>", self.change_slot)
        self.button(self.controls, "刷新", self.refresh).pack(side="left", padx=8)
        self.button(self.controls, "目录…", self.choose_root).pack(side="right")
        self.body = tk.Frame(self.root, bg=BG)
        self.body.pack(fill="both", expand=True, padx=14)
        self.canvas = tk.Canvas(self.body, bg=BG, highlightthickness=0)
        self.scroll = ttk.Scrollbar(self.body, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.cards = tk.Frame(self.canvas, bg=BG)
        self.cards_window = self.canvas.create_window(0, 0, window=self.cards, anchor="nw")
        self.cards.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self.resize_cards)
        self.root.bind("<MouseWheel>", lambda event: self.canvas.yview_scroll(-int(event.delta/120), "units"))
        self.footer = tk.Frame(self.root, bg=BG)
        self.footer.pack(side="bottom", fill="x", padx=18, pady=12, before=self.body)
        self.pin_var = tk.BooleanVar(value=session.settings["always_on_top"])
        self.pin = tk.Checkbutton(self.footer, text="保持置顶", variable=self.pin_var, command=self.set_pin, bg=BG, fg=MUTED, selectcolor=BG, activebackground=BG, activeforeground=FG, font=("Microsoft YaHei UI", 9))
        self.pin.pack(side="left")
        self.button(self.footer, "推演", lambda: self.open_panel('manual')).pack(side="right")
        self.button(self.footer, "存档", lambda: self.open_panel('backups')).pack(side="right", padx=3)
        self.button(self.footer, "手册", lambda: self.open_panel('library')).pack(side="right", padx=6)
        self.root.bind("<Escape>", lambda _: self.root.iconify())
        self.root.bind('<Control-b>', lambda _: self.commands.put(('capture', None)))
        self.root.bind('<Configure>', self.layout_changed)
        if visible:
            try:
                from .hotkeys import Hotkeys
                self.hotkeys = Hotkeys(self.commands)
            except (OSError, RuntimeError):
                logging.exception('Global hotkeys unavailable')
            try:
                from .tray import Tray
                self.tray = Tray(self.commands)
            except (ImportError, OSError, RuntimeError):
                logging.exception('Tray unavailable; closing the overlay will minimize to the taskbar')
        if layout and layout.get('compact'):
            self.toggle_compact(preserve_expanded_size=True)
        self.tick()

    def read_layout(self):
        try:
            if self.layout_path.stat().st_size > 8192:
                return None
            row = json.loads(self.layout_path.read_text(encoding='utf-8'))
            if (all(type(row.get(k)) is int and -16384 <= row[k] <= 16384 for k in ('x','y','width','height'))
                    and row['width'] >= 250 and row['height'] >= 180
                    and type(row.get('compact')) is bool and type(row.get('scale')) in (int,float)
                    and .5 <= row['scale'] <= 5):
                return row
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        return None

    def layout_changed(self, event):
        if event.widget is not self.root:
            return
        if self.layout_timer is not None:
            self.root.after_cancel(self.layout_timer)
        self.layout_timer = self.root.after(750, self.remember_layout)

    def remember_layout(self):
        if self.layout_timer is not None:
            self.root.after_cancel(self.layout_timer)
        self.layout_timer = None
        if self.root.state() not in ('normal','zoomed'):
            return
        width, height = self.expanded_size if self.compact else (self.root.winfo_width(),self.root.winfo_height())
        if width < 250 or height < 180:
            return
        row = {'x':self.root.winfo_x(),'y':self.root.winfo_y(),'width':width,'height':height,
               'scale':self.ui_scale,'compact':self.compact}
        try:
            self.layout_path.parent.mkdir(parents=True,exist_ok=True)
            pending=self.layout_path.with_suffix('.pending')
            pending.write_text(json.dumps(row),encoding='utf-8');pending.replace(self.layout_path)
        except OSError:
            logging.exception('Unable to remember overlay layout')

    def open_panel(self, page='overview'):
        self.session.panel.request(page)

    def hide_to_tray(self):
        if self.tray is not None:
            self.root.withdraw()
        else:
            self.root.iconify()  # Keep monitoring, and keep an accessible taskbar entry.

    def process_commands(self):
        while True:
            try:
                command, value = self.commands.get_nowait()
            except Empty:
                return True
            if command == 'exit':
                self.close()
                return False
            if command == 'show':
                self.root.deiconify();self.root.lift()
            elif command in ('panel', 'backups', 'library'):
                self.open_panel(command if command != 'panel' else 'overview')
            elif command == 'hotkeys':
                if value:self.root.title('灯火 · 地牢助手 · 可用快捷键 '+value)
            elif command == 'capture' and not self.capture_pending:
                self.capture_pending = True
                def capture():
                    try:
                        self.session.backup_action({'action':'capture'})
                        self.commands.put(('captured', None))
                    except (ValueError, OSError) as exc:
                        self.commands.put(('captured', str(exc)))
                threading.Thread(target=capture, daemon=True, name='tray-backup').start()
            elif command == 'captured':
                self.capture_pending = False
                self.action_error = value or ''
                self.action_error_until = time.monotonic()+10

    def button(self, parent, title, command):
        return tk.Button(parent, text=title, command=command, bg=PANEL, fg=GOLD, activebackground="#394335", activeforeground=FG,
                         relief="flat", borderwidth=0, padx=9, pady=5, cursor="hand2", font=("Microsoft YaHei UI", 9))

    def resize_cards(self, event):
        self.canvas.itemconfigure(self.cards_window, width=event.width)
        wrap = max(self.pixels(250), self.root.winfo_width()-40)
        self.status.configure(wraplength=wrap)
        self.hero.configure(wraplength=wrap)
        self.metrics.configure(wraplength=wrap)
        self.backup_status.configure(wraplength=wrap)
        for card in self.cards.winfo_children():
            for child in card.winfo_children():
                if isinstance(child, tk.Label):
                    child.configure(wraplength=max(self.pixels(220), event.width-24))

    def safely(self, action):
        try:
            action()
            self.action_error = ""
        except (ValueError, OSError) as exc:
            self.action_error = str(exc)
            self.action_error_until = time.monotonic() + 8
            self.status.configure(text=self.action_error, fg="#edafa0")

    def set_pin(self):
        self.safely(lambda: self.session.update_settings({"always_on_top": self.pin_var.get()}))
        self.pin_var.set(self.session.settings["always_on_top"])

    def change_slot(self, _=None):
        slot = self.slot.current()
        self.safely(lambda: self.session.update_settings({"slot": slot if slot else "auto", "mode": "save"}))

    def refresh(self):
        self.safely(self.session.refresh)

    def choose_root(self):
        path = filedialog.askdirectory(parent=self.root, title="选择包含 game1、game2 等文件夹的存档目录")
        if path:
            self.safely(lambda: self.session.update_settings({"save_root": path, "mode": "save", "slot": "auto"}))

    def toggle_compact(self, preserve_expanded_size=False):
        if not self.compact and not preserve_expanded_size:
            self.expanded_size = (max(self.minimum_size[0], self.root.winfo_width()), max(self.minimum_size[1], self.root.winfo_height()))
        self.compact = not self.compact
        self.compact_button.configure(text="展开" if self.compact else "收起")
        width, height = self.expanded_size
        if self.compact:
            self.root.minsize(self.minimum_size[0], self.pixels(180))
            self.controls.pack_forget()
            self.metrics.pack_forget()
            self.body.pack_forget()
            self.compact_tip.pack(fill='x',padx=18,pady=(0,8),before=self.footer)
            self.root.update_idletasks()
            self.root.geometry(f'{width}x{max(self.pixels(180),self.root.winfo_reqheight())}')
        else:
            self.root.minsize(*self.minimum_size)
            self.compact_tip.pack_forget()
            self.body.pack(fill='both',expand=True,padx=14)
            self.metrics.pack(fill="x", padx=18, pady=(0, 10), before=self.body)
            self.controls.pack(fill="x", padx=18, pady=(0, 12), before=self.body)
            self.root.geometry(f'{width}x{height}')
        self.last_key = None

    def tick(self):
        if self.tick_id is not None:
            self.root.after_cancel(self.tick_id)
            self.tick_id = None
        if not self.process_commands():
            return
        if self.session.stop.is_set():
            self.destroy_window()
            return
        snap = self.session.snapshot()
        backup = snap.get('backup_health', {})
        if self.tray is not None:
            try:
                self.tray.update(backup)
            except (OSError, RuntimeError):
                logging.exception('Tray status update failed')
        label = {'paused': '自动备份已暂停', 'blocked': '自动备份受阻',
                 'waiting': '备份监控中 · 等待游戏保存', 'protected': '最近保存已备份'}.get(backup.get('state'), '正在检查自动备份…')
        self.backup_status.configure(text=label + ('\n'+backup['error'] if backup.get('error') else ''),
                                     fg='#edafa0' if backup.get('state') == 'blocked' else MUTED)
        top = snap["settings"]["always_on_top"]
        if self.last_top != top:
            self.root.attributes("-topmost", top)
            self.pin_var.set(top)
            self.last_top = top
        data = snap["data"]
        if backup.get('slot'):
            label = f"槽位 {backup['slot']}："+label
        if backup.get('saved'):
            label += f" · 保存{int(max(0,time.time()-backup['saved'])/60)}分钟前"
        self.backup_status.configure(text=label+('\n'+backup['error'] if backup.get('error') else ''))
        if snap["error"]:
            status = snap["error"]
        else:
            stamp = datetime.fromtimestamp(snap["modified"], CST).strftime("%m/%d %H:%M:%S")
            manual = snap["settings"]["mode"] == "manual"
            status = ("手动局势" if manual else f"槽位 {snap['active_slot']} · 存档快照") + " · " + stamp
            if manual:
                status += "\n手动信息已过期：请重新填写当前局势" if snap["stale"] else "\n不会自动跟随游戏，请随局势重新填写"
            else:
                status += "\n旧快照：请保存游戏后再参考" if snap["stale"] else "\n请对照游戏画面，非逐回合实时数据"
            if data and data.get("compatibility_warning"):
                status += "\n版本不同：规则与手册按 " + snap["catalog_version"]
        if snap.get("configuration_notice"):
            status += "\n" + snap["configuration_notice"]
        action_error = self.action_error and time.monotonic() < self.action_error_until
        self.status.configure(text=self.action_error if action_error else status,
                              fg="#edafa0" if action_error or snap["error"] else GOLD if snap["stale"] else MUTED)
        key = (snap["revision"], snap["error"], self.compact)
        if data:
            hero = data["hero"]
            branch = "（支线）" if data.get("branch") else ""
            self.hero.configure(text=f"{hero['class']} Lv.{hero['level']}  ·  第 {data['depth']} 层{branch}  ·  HP {hero['hp']:g}/{hero['ht']:g}")
            resources = "金币未填写" if snap["settings"]["mode"] == "manual" else f"金币 {data['gold']:g}"
            self.metrics.configure(text=f"基础力量 {hero['strength']:g}  ·  {hero['hunger_label']}  ·  {resources}")
            self.health.delete("all")
            ratio = max(0, min(1, hero["hp"]/hero["ht"]))
            self.health.create_rectangle(0, 0, self.health.winfo_width()*ratio, 5, fill="#e2a18d" if ratio<.5 else "#90b998", outline="")
        else:
            self.hero.configure(text="等待可读的冒险状态")
            self.metrics.configure(text="可在主面板输入局势，或查看离线手册")
            self.health.delete("all")
        selected = snap["settings"]["slot"]
        self.slot.current(0 if selected == "auto" else selected)
        if key != self.last_key:
            self.last_key = key
            for child in self.cards.winfo_children():
                child.destroy()
            tips = (data or {}).get("tips", [])[:1 if self.compact else 5]
            if not tips:
                tips = [{"severity": "info", "title": "让灯火跟上你的脚步", "body": "在游戏中保存后，这里会显示针对当前快照的建议。完整手册和手动分析在主面板。"}]
            for tip in tips:
                card = tk.Frame(self.cards, bg=PANEL, padx=12, pady=12)
                card.pack(fill="x", pady=(0, 9))
                color = {"critical": "#e3a18a", "warning": GOLD, "info": "#b4c9a5"}[tip["severity"]]
                wrap = max(self.pixels(220), self.canvas.winfo_width()-24)
                tk.Label(card, text=tip["title"], bg=PANEL, fg=color, wraplength=wrap, justify="left", anchor="w", font=("Microsoft YaHei UI", 10, "bold")).pack(fill="x")
                tk.Label(card, text=tip["body"], bg=PANEL, fg="#a5b79e", wraplength=wrap, justify="left", anchor="w", font=("Microsoft YaHei UI", 9)).pack(fill="x", pady=(6, 0))
            self.canvas.yview_moveto(0)
            self.compact_tip.configure(text=tips[0]['title'] if tips else '', wraplength=max(self.pixels(250),self.root.winfo_width()-40))
            if self.compact:
                self.root.update_idletasks()
                self.root.geometry(f'{self.expanded_size[0]}x{max(self.pixels(180),self.root.winfo_reqheight())}')
        self.tick_id = self.root.after(1000, self.tick)

    def destroy_window(self):
        if self.hotkeys is not None:
            self.hotkeys.stop()
            self.hotkeys = None
        self.remember_layout()
        if self.layout_timer is not None:
            self.root.after_cancel(self.layout_timer)
            self.layout_timer = None
        if self.tick_id is not None:
            self.root.after_cancel(self.tick_id)
            self.tick_id = None
        if self.tray is not None:
            try:
                self.tray.stop()
            except (OSError, RuntimeError):
                logging.exception('Tray shutdown failed')
            finally:
                self.tray = None
        self.root.destroy()

    def close(self):
        self.session.stop.set()
        self.destroy_window()

    def run(self):
        self.root.mainloop()
