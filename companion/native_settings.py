"""Preferences drafts and CAS remain in Python; controls are standard WinForms."""
from __future__ import annotations

import copy
from .native_host import Value, TextState, NativeWindow
from .play_state import PLAY_DEFAULTS, validate_preferences

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
        self.recovery_pending = None
        self.read_values()

    def read_values(self):
        preferences = self.manager.play.preferences
        with preferences.lock:
            self.revision, state = preferences.generation, copy.deepcopy(preferences.values)
        self.saved_baseline = copy.deepcopy(state)
        self.vars = {key: Value(next(label for label, anchor in ANCHORS.items() if anchor == value) if key == 'anchor' else value if type(value) is bool else str(value), self.changed)
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
        self.edit_notice()
        self.emit()

    def edit_notice(self):
        self.status.text = ('设置有未保存草稿；保存后才生效。' if self.has_draft()
                            else '本窗口的修改已撤回，没有未保存草稿；需要时可重新读取最新保存值。')

    def save(self):
        try:
            submitted_values, submitted_bindings = copy.deepcopy(self.draft_values())
            patch = dict(submitted_values)
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
            patch['bindings'] = submitted_bindings
            receipt = self.manager.play.save(patch, expected_generation=self.revision)
            self.revision = receipt['revision']
            self.saved_baseline = copy.deepcopy(receipt['settings'])
            self.draft_baseline = (submitted_values, submitted_bindings)
            self.status.text = self.manager.play_apply_error or ('本次提交已保存；之后的新编辑仍未保存。'
                if self.has_draft() else '已保存；注册状态见下方。透明度只作用于背景。')
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
        baseline_values, baseline_bindings = self.draft_baseline
        changed = [key for key, value in values.items() if value != baseline_values[key]]
        changed += ['binding.'+key for key, value in bindings.items() if value != baseline_bindings[key]]
        return {'format': 2, 'values': values, 'bindings': bindings,
                'baseline': copy.deepcopy(self.saved_baseline), 'changed': changed,
                'preferences_revision': self.revision}

    @staticmethod
    def wire_values(state):
        values = {key: next(label for label, anchor in ANCHORS.items() if anchor == value)
                  if key == 'anchor' else value if type(value) is bool else str(value)
                  for key, value in state.items() if key != 'bindings'}
        return {**values, **{'binding.'+key: value for key, value in state['bindings'].items()}}

    def restore_draft(self, draft):
        if self.has_draft():
            raise ValueError('当前游玩设置已有草稿；请先保存或重新读取，原副本仍保留。')
        if (not isinstance(draft, dict) or not isinstance(draft.get('values'), dict)
                or not isinstance(draft.get('bindings'), dict)
                or set(draft['values']) != set(self.vars) or set(draft['bindings']) != set(self.bindings)):
            raise ValueError('游玩设置草稿字段不完整；原文件仍保留')
        legacy = 'format' not in draft
        if not legacy and (type(draft['format']) is not int or draft['format'] != 2):
            raise ValueError('游玩设置草稿版本不兼容；原文件仍保留')
        raw = {}
        for key, value in {**draft['values'], **{'binding.'+k: v for k, v in draft['bindings'].items()}}.items():
            if key in ('enabled', 'alerts'):
                if type(value) is not bool:
                    raise ValueError('游玩设置开关草稿格式不正确；原文件仍保留')
            else:
                if legacy and type(value) in (int, float):
                    value = str(value)
                if not isinstance(value, str) or len(value) > 80 or any(ord(c) < 32 for c in value):
                    raise ValueError('游玩设置原始输入格式不正确；原文件仍保留')
            raw[key] = value
        if raw['anchor'] not in ANCHORS:
            raise ValueError('游玩设置草稿位置不受支持；原文件仍保留')
        baseline = None
        if not legacy:
            baseline = draft.get('baseline')
            if (not isinstance(baseline, dict) or set(baseline) != set(PLAY_DEFAULTS)
                    or not isinstance(baseline.get('bindings'), dict)
                    or set(baseline['bindings']) != set(self.bindings)):
                raise ValueError('草稿缺少原保存值；原文件仍保留')
            baseline = validate_preferences(baseline)
        changed = list(raw) if legacy else draft.get('changed')
        if (not isinstance(changed, list) or any(not isinstance(key, str) or key not in raw for key in changed)
                or len(set(changed)) != len(changed)):
            raise ValueError('草稿修改字段范围不正确；原文件仍保留')
        preferences = self.manager.play.preferences
        with preferences.lock:
            current, generation = copy.deepcopy(preferences.values), preferences.generation
        current_raw = self.wire_values(current)
        baseline_raw = self.wire_values(baseline) if baseline else None
        flat = lambda state: {**{k: v for k, v in state.items() if k != 'bindings'},
                               **{'binding.'+k: v for k, v in state['bindings'].items()}}
        old_values, current_values = (flat(baseline) if baseline else {}), flat(current)
        labels = {'enabled': '启用游玩显示', 'alerts': '新风险提醒', 'anchor': '显示角落', **dict(FIELDS),
                  **{'binding.'+key: label+'快捷键' for key, label in LABELS.items()}}
        rows = [{'key': key, 'label': labels[key], 'original': baseline_raw[key] if baseline_raw else '旧版未记录',
                 'current': current_raw[key], 'draft': raw[key], 'original_available': baseline is not None,
                 'conflict': legacy or current_values[key] != old_values[key] and raw[key] != current_raw[key]}
                for key in changed]
        self.recovery_pending = {'raw': raw, 'baseline_raw': baseline_raw, 'current': current,
            'generation': generation, 'edit_revision': self.edit_revision, 'rows': rows}
        if any(row['conflict'] for row in rows):
            self.host.command('recover_settings', rows=rows,
                text='只载入原来修改的字段。请选择保留当前值或找回草稿；载入后仍需另行保存。'
                if not legacy else '旧版副本未记录修改范围，请逐项选择。默认保留当前值，原副本不会改动。')
            return
        self.finish_recovery({row['key']: 'draft' for row in rows})

    def finish_recovery(self, choices):
        pending = self.recovery_pending
        if pending is None:
            raise ValueError('草稿载入确认已失效，请重新选择副本。')
        keys = {row['key'] for row in pending['rows']}
        if (not isinstance(choices, dict) or set(choices) != keys
                or any(value not in ('current', 'draft', 'original') for value in choices.values())
                or not pending['baseline_raw'] and 'original' in choices.values()):
            raise ValueError('请逐项选择要载入的值；原副本仍保留。')
        preferences = self.manager.play.preferences
        with preferences.lock:
            if (self.edit_revision != pending['edit_revision'] or self.has_draft()
                    or preferences.generation != pending['generation']):
                raise ValueError('确认期间设置又有变化；当前编辑和原副本仍保留，请重新载入核对。')
            current_raw = self.wire_values(pending['current'])
            merged = dict(current_raw)
            for key, choice in choices.items():
                if choice == 'draft':
                    merged[key] = pending['raw'][key]
                elif choice == 'original':
                    merged[key] = pending['baseline_raw'][key]
            self.revision = pending['generation']
            self.saved_baseline = copy.deepcopy(pending['current'])
            self.draft_baseline = ({key: current_raw[key] for key in self.vars},
                                   {key: current_raw['binding.'+key] for key in self.bindings})
            for key in self.vars:
                self.vars[key].value = merged[key]
            for key in self.bindings:
                self.bindings[key].value = merged['binding.'+key]
        self.recovery_pending = None
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
            self.edit_notice()
        elif action == 'settings_save':
            self.save()
        elif action == 'settings_recovery_decision':
            if item.get('decision') == 'restore':
                self.finish_recovery(item.get('choices'))
            else:
                self.recovery_pending = None
                self.status.text = '已取消载入；当前设置和原草稿副本保持不变。'
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
