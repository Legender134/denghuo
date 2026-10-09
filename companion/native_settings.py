"""Preferences drafts and CAS remain in Python; controls are standard WinForms."""
from __future__ import annotations

import copy
from .native_host import Value, TextState, NativeWindow

LABELS = {'capture': '立即备份已落盘进度', 'show': '显示管理窗口', 'library': '数值手册',
          'backups': '存档历史', 'play_toggle': '开关游玩显示', 'quick': '游戏内只读速查'}
ANCHORS = {'左上': 'top_left', '右上': 'top_right', '左下': 'bottom_left', '右下': 'bottom_right'}
FIELDS = [('offset_x', '横向边距'), ('offset_y', '纵向边距'), ('font_scale', '字号倍率（1–2）'),
          ('opacity', '背景不透明度（0.5–1）'), ('notice_seconds', '短提醒时长（3–30秒）')]


class PlaySettings:
    def __init__(self, manager):
        self.manager, self.host = manager, manager.native_ui.host
        self.window = NativeWindow(self.host, 'settings')
        self.vars, self.bindings, self.status = {}, {}, TextState()
        self.edit_revision, self.confirmation = 0, None
        self.read_values()

    def read_values(self):
        preferences = self.manager.play.preferences
        with preferences.lock:
            self.revision, state = preferences.generation, copy.deepcopy(preferences.values)
        self.vars = {key: Value(next(label for label, anchor in ANCHORS.items() if anchor == value) if key == 'anchor' else value, self.changed)
                     for key, value in state.items() if key != 'bindings'}
        self.bindings = {key: Value(value, self.changed) for key, value in state['bindings'].items()}
        self.draft_baseline = self.draft_values()
        self.status.text = preferences.error
        self.emit()

    def draft_values(self):
        return ({key: value.get() for key, value in self.vars.items()}, {key: value.get() for key, value in self.bindings.items()})

    def has_draft(self):
        return self.draft_values() != self.draft_baseline

    def changed(self):
        self.edit_revision += 1
        self.status.text = '设置有未保存草稿；保存后才生效。'
        self.emit()

    def save(self):
        try:
            patch = {key: value.get() for key, value in self.vars.items()}
            patch['anchor'] = ANCHORS[patch['anchor']]
            for key in ('offset_x', 'offset_y'):
                try:
                    patch[key] = int(patch[key])
                except (ValueError, TypeError):
                    label = next(label for field, label in FIELDS if field == key)
                    raise ValueError(label+'需填写整数；原始输入仍保留。') from None
            for key in ('font_scale', 'opacity', 'notice_seconds'):
                try:
                    patch[key] = float(patch[key])
                except (ValueError, TypeError):
                    label = next(label for field, label in FIELDS if field == key)
                    raise ValueError(label+'需填写数值；原始输入仍保留。') from None
            patch['bindings'] = {key: value.get() for key, value in self.bindings.items()}
            self.manager.play.save(patch, expected_generation=self.revision)
            self.revision = self.manager.play.preferences.generation
            self.draft_baseline = self.draft_values()
            self.status.text = self.manager.play_apply_error or '已保存；注册状态见下方。透明度只作用于背景。'
            self.emit()
            return True
        except (ValueError, KeyError, OSError, RuntimeError) as exc:
            self.status.text = str(exc) or '设置未保存，请核对输入'
            self.emit()
            return False

    def reload(self, confirmed=False):
        if self.has_draft() and not confirmed:
            self.host.command('confirm', surface='settings', title='重新读取游玩设置', purpose='settings_reload',
                text='重新读取会替换未保存设置草稿。保存副本、取消，或明确放弃后继续。')
            return
        self.manager.play.preferences.reload()
        self.manager.apply_play_settings()
        self.edit_revision += 1
        self.read_values()
        self.status.text = self.manager.play.preferences.error or self.manager.play_apply_error or '已重新读取保存值，当前草稿已替换。'
        self.emit()

    def key_status(self):
        caps = self.manager.session.ui_capabilities
        unavailable = caps.get('hotkeys_unavailable', [])
        lines = ['快捷键实际注册状态：'+('已完成' if caps.get('hotkeys_ready') else '尚未完成')]
        for key, label in LABELS.items():
            configured = self.manager.play.preferences.values['bindings'].get(key, '')
            applied = caps.get('bindings', {}).get(key, '')
            state = '已禁用' if not configured else '已注册' if caps.get('hotkeys_ready') and configured == applied and configured not in unavailable else '被占用/尚未生效'
            lines.append(label+'：'+(configured or '空')+' · '+state)
        return '\n'.join(lines)

    def draft(self):
        values, bindings = self.draft_values()
        return {'values': values, 'bindings': bindings, 'preferences_revision': self.revision}

    def restore_draft(self, draft):
        if not isinstance(draft, dict) or set(draft.get('values', {})) != set(self.vars) or set(draft.get('bindings', {})) != set(self.bindings):
            raise ValueError('游玩设置草稿字段不完整；原文件仍保留')
        for key, value in draft['values'].items():
            self.vars[key].value = value
        for key, value in draft['bindings'].items():
            self.bindings[key].value = str(value)
        # Keep the current saved generation, and require a separate explicit save.
        self.edit_revision += 1
        self.status.text = '已载入原始设置草稿；尚未保存或注册快捷键，请核对后点击保存。'
        self.emit()
        self.window.deiconify()

    def save_draft_copy(self):
        result = self.manager.session.save_exit_draft('native', 'play-settings', '游玩设置未完成草稿', self.draft())
        self.status.text = result['notice']+'\n'+result['path']
        self.emit()

    def handle(self, item):
        action = item['action']
        if action == 'settings_edit':
            for key, raw in item.get('values', {}).items():
                if key in self.vars:
                    self.vars[key].value = raw
            for key, raw in item.get('bindings', {}).items():
                if key in self.bindings:
                    self.bindings[key].value = str(raw)[:80]
            self.edit_revision = max(self.edit_revision+1, int(item.get('draft_revision', 0)))
            self.status.text = '设置有未保存草稿；保存后才生效。'
        elif action == 'settings_save':
            self.save()
        elif action == 'settings_reload':
            self.reload()
        elif action == 'settings_reload_decision':
            if item.get('decision') == 'saved':
                self.save_draft_copy()
            if item.get('decision') in ('saved', 'discard'):
                self.reload(True)
        elif action == 'unlock' and self.save():
            self.manager.play.unlock_layout()
            self.window.withdraw()
        self.emit()

    def emit(self):
        values, bindings = self.draft_values()
        self.host.command('settings_state', values=values, bindings=bindings, draft_revision=self.edit_revision,
            status=self.status.text, registration=self.key_status(), dirty=self.has_draft())
        self.manager.native_ui.report_drafts()
