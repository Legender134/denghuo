"""Small native, always-on-top companion for windowed play."""

from datetime import datetime
import tkinter as tk
import time
import logging
import json
from queue import Empty
import threading
from tkinter import filedialog, ttk
import webbrowser

from .service import CST
from .paths import ROOT

BG, PANEL, FG, MUTED, GOLD = "#131b16", "#202a21", "#e7edde", "#9eb19d", "#dec38c"


def brief_error(message):
    text = ' '.join(message.split())
    return text if len(text) <= 120 else text[:120]+'…「完整面板」可查看完整原因'


class Overlay:
    def __init__(self, session, url, visible=True, start_hidden=False):
        self.session, self.url = session, url
        session.panel.bind(url)
        self.root = tk.Tk()
        self.root.withdraw()  # Event loop only; visible interaction uses standard native controls.
        self.root.title("灯火 · 地牢助手")
        try:
            self.root.iconbitmap(str(ROOT/'data/lamp.ico'))
        except tk.TclError:
            pass
        self.commands = session.manager_commands
        session.manager_available = True
        self.tray = None
        self.hotkeys = None
        self.play = None
        self.play_settings = None
        self.play_apply_error = ''
        self.applied_play_revision = None
        self.capture_pending = False
        # Tk point fonts already follow system DPI; geometry and wrap lengths are pixels.
        self.ui_scale = max(1.0, self.root.winfo_fpixels('1i') / 96.0)
        self.pixels = lambda value: round(value*self.ui_scale)
        self.root.configure(bg=BG)
        width = min(self.pixels(390), max(325, self.root.winfo_screenwidth()-40))
        height = min(self.pixels(400), max(360, self.root.winfo_screenheight()-self.pixels(140)))
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
        style.map('TCombobox', fieldbackground=[('readonly', PANEL)], foreground=[('readonly', FG)],
                  selectbackground=[('readonly', PANEL)], selectforeground=[('readonly', FG)])
        self.compact = False
        self.last_key = None
        self.last_top = None
        self.action_error = ""
        self.action_error_until = 0
        self.tick_id = None
        self.titlebar = tk.Frame(self.root, bg=BG)
        self.titlebar.pack(fill="x", padx=17, pady=(14, 6))
        self.title_label = tk.Label(self.titlebar, text="◈  灯火", fg=GOLD, bg=BG, font=("Microsoft YaHei UI", 17, "bold"))
        self.title_label.grid(row=0, column=0, sticky='w')
        self.titlebar.columnconfigure(0, weight=1)
        self.compact_button = self.button(self.titlebar, "收起", self.toggle_compact)
        self.button(self.titlebar, '退出', lambda: self.close(confirm_drafts=True)).grid(row=0, column=1, padx=3)
        self.compact_button.grid(row=0, column=2)
        self.body = tk.Frame(self.root, bg=BG)
        self.body.pack(fill="both", expand=True, padx=14)
        self.canvas = tk.Canvas(self.body, bg=BG, highlightthickness=0, takefocus=True)
        self.scroll = ttk.Scrollbar(self.body, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.content = tk.Frame(self.canvas, bg=BG)
        self.cards_window = self.canvas.create_window(0, 0, window=self.content, anchor="nw")
        self.content.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self.resize_cards)
        self.root.bind("<MouseWheel>", self.scroll_wheel)
        self.root.bind('<FocusIn>', lambda event: self.root.after_idle(self.reveal_widget, event.widget))
        self.canvas.bind('<Prior>', lambda _: self.scroll_page(-1))
        self.canvas.bind('<Next>', lambda _: self.scroll_page(1))
        self.status = tk.Label(self.content, text="正在读取存档…", justify="left", anchor="w", wraplength=350, bg=BG, fg=GOLD, font=("Microsoft YaHei UI", 9))
        self.status.pack(fill="x", padx=4, pady=(3, 9))
        self.backup_status = tk.Label(self.content, text='正在检查自动备份…', bg=BG, fg=MUTED,
                                      justify='left', anchor='w', wraplength=350, font=('Microsoft YaHei UI', 9))
        self.backup_status.pack(fill='x', padx=4, pady=(0, 8))
        self.hero = tk.Label(self.content, text="等待冒险", justify="left", anchor="w", wraplength=350, bg=BG, fg=FG, font=("Microsoft YaHei UI", 12, "bold"))
        self.hero.pack(fill="x", padx=4)
        self.health = tk.Canvas(self.content, height=5, bg="#354133", highlightthickness=0)
        self.health.pack(fill="x", padx=4, pady=(9, 8))
        self.compact_tip = tk.Label(self.content, text='', bg=BG, fg=GOLD, anchor='w', justify='left',
                                    wraplength=350, font=('Microsoft YaHei UI', 9))
        self.metrics = tk.Label(self.content, text="", bg=BG, fg=MUTED, anchor="w", justify="left", wraplength=350, font=("Microsoft YaHei UI", 9))
        self.metrics.pack(fill="x", padx=4, pady=(0, 10))
        self.controls = tk.Frame(self.content, bg=BG)
        self.options_visible = False
        self.connection_controls = tk.Frame(self.controls, bg=BG)
        self.connection_controls.pack(fill='x')
        self.slot = ttk.Combobox(self.connection_controls, state="readonly", values=["自动跟随"]+[f"槽位 {i}" for i in range(1, 7)], width=12)
        self.slot.current(0)
        self.slot.bind("<<ComboboxSelected>>", self.change_slot)
        self.refresh_button = self.button(self.connection_controls, "刷新", self.refresh)
        self.directory_button = self.button(self.connection_controls, "目录…", self.choose_root)
        self.cards = tk.Frame(self.content, bg=BG)
        self.cards.pack(fill='x')
        self.footer = tk.Frame(self.root, bg=BG)
        self.footer.pack(side="bottom", fill="x", padx=18, pady=12, before=self.titlebar)
        self.pin_var = tk.BooleanVar(value=session.settings["always_on_top"])
        self.display_controls = tk.Frame(self.controls, bg=BG)
        self.display_controls.pack(fill='x', pady=(6, 0))
        self.pin = tk.Checkbutton(self.display_controls, text="管理窗口置顶", variable=self.pin_var, command=self.set_pin, bg=BG, fg=MUTED, selectcolor=BG, activebackground=BG, activeforeground=FG, font=("Microsoft YaHei UI", 9))
        self.play_settings_button = self.button(self.display_controls, '游玩显示与快捷键', self.open_play_settings)
        self.controls_stacked = None
        self.controls.bind('<Configure>', lambda event: self.arrange_controls(event.width))
        self.button(self.footer, "查数值", self.open_lookup).grid(row=0, column=0, sticky='ew', padx=(0, 4), pady=(0, 6))
        self.button(self.footer, "存档历史", lambda: self.open_panel('backups')).grid(row=0, column=1, sticky='ew', padx=(4, 0), pady=(0, 6))
        self.button(self.footer, "完整面板 ↗", self.open_panel).grid(row=1, column=0, sticky='ew', padx=(0, 4))
        self.settings_button = self.button(self.footer, '设置', self.toggle_options)
        self.settings_button.grid(row=1, column=1, sticky='ew', padx=(4, 0))
        self.footer.columnconfigure((0, 1), weight=1)
        self.footer.bind('<Configure>', self.resize_footer)
        self.arrange_controls(width-40)
        self.root.bind("<Escape>", lambda _: self.root.iconify())
        self.root.bind('<F1>', lambda _: self.open_panel('help'))
        self.root.bind('<Control-b>', lambda _: self.commands.put(('capture', None)))
        self.root.bind('<Configure>', self.layout_changed)
        if visible:
            try:
                from .play_overlay import PlayDisplay
                self.play = PlayDisplay(self)
            except (OSError, tk.TclError):
                logging.exception('Play mode unavailable')
            try:
                from .hotkeys import Hotkeys
                self.hotkeys = Hotkeys(self.commands, self.play.state['bindings'] if self.play else None)
            except (OSError, RuntimeError):
                logging.exception('Global hotkeys unavailable')
            try:
                from .tray import Tray
                self.tray = Tray(self.commands)
            except (ImportError, OSError, RuntimeError):
                logging.exception('Tray unavailable; closing the overlay will minimize to the taskbar')
        if layout and layout.get('compact'):
            self.toggle_compact(preserve_expanded_size=True)
        if self.play:
            self.applied_play_revision = self.play.applied_revision
        from .native_manager import NativeManager
        self.native_ui = NativeManager(self)
        self.update_capabilities()
        self.tick()
        if visible and not start_hidden:
            self.native_ui.show()

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
        try:
            self.session.panel.request(page)
        except (ValueError, OSError) as exc:
            from tkinter import messagebox
            self.native_ui.error(str(exc)+'\n完整面板地址：'+self.url)

    def open_lookup(self):
        if self.play is not None:
            self.safely(self.play.open_lookup)
        else:
            self.open_panel('library')

    def open_reference(self, reference, source=None, note=''):
        if self.play is None:
            self.open_panel('library')
            return
        self.play.open_lookup()
        self.play.lookup.open_reference(reference, source, note)

    def toggle_options(self):
        self.options_visible = not self.options_visible
        if self.options_visible:
            if self.compact:
                self.toggle_compact()
            self.controls.pack(fill='x', padx=4, pady=(0, 12), before=self.cards)
            self.root.after_idle(self.reveal_widget, self.controls)
        else:
            self.controls.pack_forget()
        self.settings_button.configure(text='收起设置' if self.options_visible else '设置')

    def open_play_settings(self, show=True):
        if self.play is None:
            self.open_panel('play-settings')
            return
        from .play_settings import PlaySettings
        if self.play_settings is None:
            self.play_settings = PlaySettings(self)
        if show:
            self.play_settings.emit()
            self.native_ui.host.command('show', surface='settings')

    def rebind_hotkeys(self):
        if self.hotkeys is not None:
            self.hotkeys.stop()
            if self.hotkeys.thread.is_alive():
                raise RuntimeError('快捷键正在释放，请稍后重试')
        from .hotkeys import Hotkeys
        self.hotkeys = Hotkeys(self.commands, self.play.state['bindings'])

    def update_capabilities(self):
        keys = self.hotkeys
        ready = bool(keys and keys.ready.is_set() and keys.thread.is_alive() and not keys.stopped.is_set())
        bindings = dict(keys.bindings) if keys else {}
        unavailable = list(keys.unavailable) if keys else []
        with self.session.lock:
            self.session.ui_capabilities = {'play_available': self.play is not None,
                'tray_available': bool(self.tray and self.tray.icon.visible), 'hotkeys_ready': ready,
                'hotkeys_unavailable': unavailable, 'bindings': bindings,
                'applied_revision': self.applied_play_revision,
                'error': self.play_apply_error or (self.play.preferences.error if self.play else '游玩显示不可用'),
                'keyboard_panel': True, 'native_accessibility': '标准Windows控件；当前环境AX与键盘验证，旧Windows及Narrator完整任务尚待验证', 'native_helper_ready': bool(getattr(self, 'native_ui', None) and self.native_ui.host.ready)}

    def apply_play_settings(self):
        if self.play is None:
            self.play_apply_error = '游玩显示不可用；设置已保存，可通过完整面板查看。'
            self.update_capabilities()
            return
        self.play.apply_preferences()
        try:
            if self.hotkeys is None or self.hotkeys.bindings != self.play.state['bindings']:
                self.rebind_hotkeys()
            self.applied_play_revision = self.play.applied_revision
            self.play_apply_error = ''
        except (OSError, RuntimeError) as exc:
            self.play_apply_error = '显示设置已保存；快捷键尚未完成应用：'+str(exc)
            self.action_error = self.play_apply_error
            self.action_error_until = time.monotonic()+10
        self.update_capabilities()

    def hide_to_tray(self):
        self.root.withdraw()
        self.native_ui.hide()

    def process_commands(self):
        while True:
            try:
                command, value = self.commands.get_nowait()
            except Empty:
                return True
            if command == 'exit':
                if self.close(confirm_drafts=True):
                    return False
            if command == 'show':
                self.native_ui.show()
            elif command == 'quick' and self.play:
                self.safely(self.play.toggle_peek)
            elif command == 'play_toggle' and self.play:
                self.safely(self.play.toggle)
            elif command == 'play_settings':
                self.open_play_settings()
            elif command == 'play_settings_changed':
                self.apply_play_settings()
            elif command == 'library' and self.play:
                self.safely(self.play.open_lookup)
            elif command in ('panel', 'backups', 'library', 'workspace', 'help'):
                self.open_panel(command if command != 'panel' else 'overview')
            elif command == 'hotkeys':
                if value:self.root.title('灯火 · 地牢助手 · 可用快捷键 '+value)
                self.update_capabilities()
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
        wrap = max(1, event.width-8)
        self.status.configure(wraplength=wrap)
        self.hero.configure(wraplength=wrap)
        self.metrics.configure(wraplength=wrap)
        self.backup_status.configure(wraplength=wrap)
        self.compact_tip.configure(wraplength=wrap)
        for card in self.cards.winfo_children():
            for child in card.winfo_children():
                if isinstance(child, tk.Label):
                    child.configure(wraplength=max(1, event.width-24))

    def resize_footer(self, event):
        wrap = max(1, (event.width-8)//2-18)
        for child in self.footer.winfo_children():
            child.configure(wraplength=wrap)

    def arrange_controls(self, width):
        connection = (self.slot, self.refresh_button, self.directory_button)
        display = (self.pin, self.play_settings_button)
        stacked = max(sum(widget.winfo_reqwidth() for widget in connection)+16,
                      sum(widget.winfo_reqwidth() for widget in display)+8) > width
        if stacked == self.controls_stacked:
            return
        self.controls_stacked = stacked
        for frame, widgets in ((self.connection_controls, connection), (self.display_controls, display)):
            for column in range(3):
                frame.columnconfigure(column, weight=0)
            for index, widget in enumerate(widgets):
                widget.grid(row=index if stacked else 0, column=0 if stacked else index,
                            sticky='ew' if stacked else 'w',
                            padx=(0, 8) if not stacked and index < len(widgets)-1 else 0,
                            pady=(0, 6) if stacked and index < len(widgets)-1 else 0)
            frame.columnconfigure(0, weight=1)

    def reveal_widget(self, widget):
        if not widget.winfo_exists() or not widget.winfo_ismapped():
            return
        parent = widget
        while parent is not self.content:
            if parent is self.root or parent.master is None:
                return
            parent = parent.master
        top = widget.winfo_rooty()-self.content.winfo_rooty()
        height = widget.winfo_height()
        visible_top = self.canvas.canvasy(0)
        viewport = self.canvas.winfo_height()
        if top < visible_top or height > viewport:
            target = top
        elif top+height > visible_top+viewport:
            target = top+height-viewport
        else:
            return
        self.canvas.yview_moveto(target/max(1, self.content.winfo_height()))

    def restore_scroll(self, top):
        self.canvas.yview_moveto(top/max(1, self.content.winfo_height()))
        focused = self.root.focus_get()
        if focused is not None:
            self.reveal_widget(focused)

    def scroll_wheel(self, event):
        self.canvas.yview_scroll(-int(event.delta/120), 'units')
        return 'break'

    def scroll_page(self, direction):
        self.canvas.yview_scroll(direction, 'pages')
        return 'break'

    def resize_compact(self):
        self.root.update_idletasks()
        desired = self.titlebar.winfo_reqheight()+self.footer.winfo_reqheight()+self.content.winfo_reqheight()+44
        height = max(self.pixels(180), min(desired, self.expanded_size[1], self.root.winfo_screenheight()-40))
        self.root.geometry(f'{self.expanded_size[0]}x{height}')

    def safely(self, action):
        try:
            action()
            self.action_error = ""
        except (ValueError, OSError, tk.TclError) as exc:
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
            self.cards.pack_forget()
            self.compact_tip.pack(fill='x',padx=4,pady=(0,8),after=self.health)
            self.resize_compact()
        else:
            self.root.minsize(*self.minimum_size)
            self.compact_tip.pack_forget()
            self.cards.pack(fill='x')
            self.metrics.pack(fill="x", padx=4, pady=(0, 10), before=self.cards)
            if self.options_visible:
                self.controls.pack(fill="x", padx=4, pady=(0, 12), before=self.cards)
            self.root.geometry(f'{width}x{height}')
        self.last_key = None

    def tick(self):
        if self.tick_id is not None:
            self.root.after_cancel(self.tick_id)
            self.tick_id = None
        if not self.process_commands():
            return
        self.update_capabilities()
        if self.session.stop.is_set():
            self.destroy_window()
            return
        snap = self.session.snapshot()
        if self.play is not None:
            self.play.update(snap)
        backup = snap.get('backup_health', {})
        if self.tray is not None:
            try:
                self.tray.update(backup)
            except (OSError, RuntimeError):
                logging.exception('Tray status update failed')
        label = {'paused': '自动备份已暂停', 'blocked': '自动备份受阻',
                 'waiting': '备份监控中 · 等待游戏保存', 'protected': '最近保存已备份'}.get(backup.get('state'), '正在检查自动备份…')
        if backup.get('state') == 'waiting' and backup.get('last_save_protected'):
            label = '上次保存已备份 · 等待新保存'
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
        self.backup_status.configure(text=label+('\n'+brief_error(backup['error']) if backup.get('error') else ''),
                                     fg='#edafa0' if backup.get('state') == 'blocked' else MUTED)
        if snap.get('waiting_for_save'):
            status = '已准备好 · 等待游戏保存后自动连接'
        elif snap["error"]:
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
        display_status = brief_error(self.action_error if action_error else status) if action_error or snap['error'] else status
        self.status.configure(text=display_status,
                              fg="#edafa0" if action_error or snap["error"] else GOLD if snap["stale"] else MUTED)
        key = (snap["revision"], snap["error"], snap['stale'], self.compact)
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
            self.hero.configure(text="直接开始游戏即可" if snap.get('waiting_for_save') else "等待可读的冒险状态")
            self.metrics.configure(text="自动跟随最新存档，无需先配置" if snap.get('waiting_for_save') else "可先查数值，或在「完整面板」中处理连接问题")
            self.health.delete("all")
        selected = snap["settings"]["slot"]
        self.slot.current(0 if selected == "auto" else selected)
        if key != self.last_key:
            self.last_key = key
            scroll_top = self.canvas.canvasy(0)
            for child in self.cards.winfo_children():
                child.destroy()
            tips = (data or {}).get("tips", [])[:1 if self.compact else 5]
            if not tips:
                if self.session.config_error:
                    title, body = '先恢复存档连接', '助手设置无法读取。点击「设置」确认目录与槽位，或在「完整面板 → 连接设置」中保存；原配置会先保留。'
                elif snap['error']:
                    title, body = '正在等待可读的存档', '新的有效保存到达后会自动重试。可在「设置」核对目录与槽位，「完整面板」中查看完整原因。'
                elif data:
                    title, body = '继续你的冒险', '当前没有需要优先处理的特殊风险。背包、地图和详细分析在「完整面板」。'
                else:
                    title, body = '存档保存后，灯火会自动跟上', '开始或继续一局，游戏保存后会自动显示建议。现在就能查数值；其他功能可以之后慢慢探索。'
                tips = [{'severity': 'warning' if snap['error'] else 'info', 'title': title, 'body': body}]
            for tip in tips:
                card = tk.Frame(self.cards, bg=PANEL, padx=12, pady=12)
                card.pack(fill="x", pady=(0, 9))
                color = {"critical": "#e3a18a", "warning": GOLD, "info": "#b4c9a5"}[tip["severity"]]
                if snap['stale']:
                    color = MUTED
                wrap = max(1, self.canvas.winfo_width()-24)
                tk.Label(card, text=tip["title"], bg=PANEL, fg=color, wraplength=wrap, justify="left", anchor="w", font=("Microsoft YaHei UI", 10, "bold")).pack(fill="x")
                tk.Label(card, text=tip["body"], bg=PANEL, fg="#a5b79e", wraplength=wrap, justify="left", anchor="w", font=("Microsoft YaHei UI", 9)).pack(fill="x", pady=(6, 0))
            try:
                decisions = self.session.decisions(snap)
                for risk in decisions['risks']:
                    for reference in risk['references']:
                        self.button(self.cards, risk['title']+' · '+reference['name']+'资料',
                                    lambda row=reference: self.open_reference(row)).pack(fill='x', pady=(0, 4))
                for option in decisions['options']:
                    card = tk.Frame(self.cards, bg=PANEL, padx=12, pady=8)
                    card.pack(fill='x', pady=(0, 8))
                    bounds = '\n'.join(text for text in (option['restriction'], option['calculation_missing'], option['note']) if text)
                    tk.Label(card, text=option['name']+f" ×{option['quantity']} · "+decisions['source']['label']+'\n'+bounds,
                             bg=PANEL, fg=FG, justify='left', anchor='w', wraplength=wrap).pack(fill='x')
                    self.button(card, option['purpose']+'（参考参数）',
                                lambda row=option, note=bounds: self.open_reference(row, row['source'], note)).pack(fill='x', pady=(4, 0))
            except (ValueError, KeyError, OSError):
                logging.exception('Context reference unavailable')
            self.root.after_idle(self.restore_scroll, scroll_top)
            prefix = '旧信息记录 · ' if data and snap['stale'] else ''
            risk = next((tip for tip in (data or {}).get('tips', []) if tip['severity'] in ('critical', 'warning')), None)
            summary = (risk['title'] if risk else '暂无特殊风险') if data else tips[0]['title']
            self.compact_tip.configure(text=prefix+summary, wraplength=max(1,self.canvas.winfo_width()-8))
            if self.compact:
                self.resize_compact()
        self.native_ui.update(snap)
        self.tick_id = self.root.after(1000, self.tick)

    def destroy_window(self):
        with self.session.lock:
            self.session.manager_available = False
            self.session.ui_capabilities = {'play_available': False, 'tray_available': False,
                                            'hotkeys_ready': False, 'bindings': {}, 'hotkeys_unavailable': [],
                                            'applied_revision': None, 'error': '原生窗口已关闭'}
        if self.play is not None:
            self.play.close()
            self.play = None
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
        if getattr(self, 'native_ui', None):
            self.native_ui.close()
        self.root.destroy()

    def close(self, confirm_drafts=False):
        if not self.session.stop.is_set():
            self.native_ui.request_exit()
            return False
        self.destroy_window()
        return True

    def run(self):
        self.root.mainloop()
