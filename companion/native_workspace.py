"""Python-owned numeric workspace; the helper owns controls, never game rules."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import webbrowser

from .native_host import Value, TextState, NativeWindow
from .quick_reference import detail_text


def plan_updated_text(stamp):
    """Workspace timestamps may predate Windows local-time support."""
    try:
        return datetime.fromtimestamp(stamp, timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M')
    except (ValueError, OSError, OverflowError):
        return '时间超出本机显示范围'


class Rows:
    def __init__(self):
        self.values, self.selected = [], ()

    def delete(self, *_):
        self.values, self.selected = [], ()

    def insert(self, _, text):
        self.values.append(text)

    def curselection(self):
        return self.selected

    def selection_clear(self, *_):
        self.selected = ()

    def selection_set(self, index):
        self.selected = (int(index),)

    def get(self, index):
        return self.values[index]

    def size(self):
        return len(self.values)


class NumericLookup:
    def __init__(self, owner):
        self.owner, self.host = owner, owner.manager.native_ui.host
        self.window = NativeWindow(self.host, 'lookup')
        self.query = Value('', self.schedule_search)
        self.note = Value('', self.note_changed)
        self.list, self.origin, self.text = Rows(), TextState(), TextState()
        self.rows, self.inputs, self.variables, self.input_origins = [], [], {}, {}
        self.identity = self.context = self.saved_plan = self.rendered = self.calculated = None
        self.workspace_error = self.plan_error = self.parameter_error = ''
        self.workspace_revision, self.favorite_ids = None, set()
        self.dirty = self.draft_modified = False
        self.submitted = self.ticket = self.pending = self.return_target = None
        self.suggested, self.total = False, 0
        self.edit_revision, self.undo_state, self.confirmation = 0, None, None
        self.pending_save = None
        self.plan_filters = ('', '全部类型', '最近更新')
        self.search()

    @staticmethod
    def source_stamp(snap):
        return (snap.get('started'), snap['settings'].get('save_root'), snap['settings']['mode'],
                snap.get('active_slot'), snap.get('revision'), snap.get('modified'))

    @staticmethod
    def hero_context(snap):
        from .decisions import public_context
        return {key: value for key, value in public_context(snap).items()
                if key in ('hero_level', 'max_hp', 'hp', 'strength', 'depth')}

    @staticmethod
    def bind_strength_context(context, scene):
        """Describe only the conditions captured with these exact input values."""
        if 'strength' not in context['params']:
            return
        context['character_scene'] = copy.deepcopy(scene)
        strength = (scene or {}).get('strength', {})
        value, base = context['params']['strength'], strength.get('base')
        if (strength.get('state') == 'known' and strength.get('usable') is True
                and strength.get('effective') == value):
            context['strength_origin'] = f'角色总力量 {value:g}' + (f'（基础 {base:g}）' if base is not None else '')
            parts = strength.get('components', {})
            labels = {'base': '基础', 'might_rings': '根骨之戒', 'adrenaline': '激素涌动', 'strongman': '力大无穷'}
            context['strength_conditions'] = '此记录的总力量组成：' + '；'.join(
                labels[key] + f' {parts[key]:g}' for key in labels if parts.get(key) is not None)
        else:
            context['strength_origin'] = f'基础力量参考 {value:g} · 总力量未确认'
            missing = strength.get('missing') or ['戒指、天赋与临时状态来源未确认']
            context['strength_conditions'] = ('总力量超出当前数值工具范围，暂按基础值参考。' if strength.get('state') == 'known' and not strength.get('usable') else
                '总力量条件待确认：' + '；'.join(missing) + '。基础值不代表实际总力量。')

    def has_draft(self):
        return bool(self.pending_save) or self.draft_modified or self.dirty or bool(self.saved_plan and (
            self.calculated != self.saved_plan['params'] or self.note.get() != self.saved_plan.get('note', '')))

    def schedule_search(self):
        root = self.owner.manager.root
        if self.pending:
            root.after_cancel(self.pending)
        self.pending = root.after(180, self.search)

    def search(self, preserve_detail=False):
        if self.pending:
            self.owner.manager.root.after_cancel(self.pending)
        self.pending = None
        session = self.owner.manager.session
        query = self.query.get().strip()[:200]
        self.suggested = not query
        if self.suggested:
            status = session.workspace_status()
            self.workspace_revision, self.favorite_ids = status['revision'], set(status['favorite_ids'])
            self.workspace_error = status.get('error', '')
            self.rows = copy.deepcopy(status['current'])
            for row in self.rows:
                captured = status.get('character_scene', {})
                if row['lookup_context'].get('stamp') == captured.get('stamp'):
                    self.bind_strength_context(row['lookup_context'], captured.get('current'))
                level = row['lookup_context']['params'].get('level')
                if level is None and row['lookup_context'].get('level_unknown'):
                    row['lookup_label'] += '（等级未知）'
            for group, label in (('favorites', '收藏'), ('recent', '最近打开'), ('common', '常用')):
                for row in status[group]:
                    if not any(item['id'] == row['id'] for item in self.rows):
                        self.rows.append({**row, 'lookup_label': row['name']+' · '+label,
                                          'lookup_example': group in ('favorites', 'recent')})
            self.total = len(session.catalog.entries)
        else:
            result = session.catalog.search(query, limit=30)
            self.rows, self.total = result['entries'], result['total']
        self.list.delete()
        for row in self.rows:
            self.list.insert('end', row.get('lookup_label', row['name']+' · '+row['type_label']))
        if (preserve_detail or self.has_draft()) and self.identity:
            self.refresh_origin(session.snapshot())
        else:
            self.clear_params()
            self.identity = self.context = self.saved_plan = self.rendered = self.calculated = None
            self.ticket = self.submitted = None
            self.plan_error = ''
            self.origin.text = '百科参数为参考示例，请按游戏核对。'
            self.show_text('选择资料，或搜索名称/别名/用途。Enter 打开首项，Ctrl+F 搜索。' if self.rows else '没有匹配条目。试试别名或用途，或清空搜索查看常用资料。')
        self.emit()

    def more_results(self):
        if self.pending:
            self.search()
        if self.suggested:
            self.suggested = False
            self.rows = []
            self.list.delete()
        result = self.owner.manager.session.catalog.search(self.query.get().strip()[:200], limit=30, offset=len(self.rows))
        self.rows.extend(result['entries'])
        self.total = result['total']
        for row in result['entries']:
            self.list.insert('end', row['name']+' · '+row['type_label'])
        self.emit()

    def show_text(self, text):
        self.text.text = text

    def clear_params(self):
        self.inputs, self.variables, self.input_origins = [], {}, {}
        self.parameter_error = ''
        self.dirty = self.draft_modified = False
        self.note.value = ''
        self.pending_save = None

    def guard(self, label, action):
        if not self.has_draft():
            action()
            return True
        self.confirmation = action
        self.host.command('confirm', surface='lookup', title=label,
            text='当前速查有未保存草稿。保存草稿副本、取消，或明确放弃后继续。', purpose='replace')
        return False

    def select(self):
        selected = self.list.curselection()
        if not selected or selected[0] >= len(self.rows):
            return
        row = copy.deepcopy(self.rows[selected[0]])
        self.guard('切换资料', lambda: self.select_row(row))

    def select_row(self, row):
        self.saved_plan, self.plan_error = None, ''
        self.identity = row['id']
        self.rendered = self.calculated = None
        self.clear_params()
        self.context = copy.deepcopy(row.get('lookup_context'))
        if self.context is None and not row.get('lookup_example'):
            snap = self.owner.manager.session.snapshot()
            params = self.hero_context(snap)
            if params:
                self.context = {'stamp': self.source_stamp(snap), 'params': params,
                                'level_unknown': False, 'mode': snap['settings']['mode']}
                self.bind_strength_context(self.context, (snap.get('data') or {}).get('character_scene'))
        self.ticket = self.owner.worker.request('detail', self.identity, self.context['params'] if self.context else {})
        self.submitted = None
        self.show_text('正在读取数值…')
        try:
            self.owner.manager.session.workspace_action({'action': 'remember', 'entry': self.identity})
        except (ValueError, OSError) as exc:
            self.workspace_error = str(exc)
        self.emit()

    def render(self, detail, error=None):
        if self.submitted is not None and {key: value.strip() for key, value in self.raw_params().items()} != self.submitted:
            self.changed()
            return
        if error:
            self.rendered = self.calculated = None
            self.parameter_error = error
            self.show_text(error)
            self.emit()
            return
        self.rendered, self.inputs = detail, detail['inputs']
        if not self.variables:
            for field in self.inputs:
                key = field['key']
                prefix = '手动局势' if self.context and self.context.get('mode') == 'manual' else '快照'
                self.input_origins[key] = (self.saved_plan['origin'].get('fields', {}).get(key, '保存的参考参数') if self.saved_plan else
                    (prefix+'已知等级' if key == 'level' else prefix+'已知阶数' if key == 'tier' else
                     (self.context.get('strength_origin') if self.context.get('strength_origin', '').startswith('保存的') else
                      prefix+(self.context.get('strength_origin') or '力量参考 · 角色条件来源未确认')) if key == 'strength' else prefix)
                    if self.context and key in self.context['params'] else
                    '等级未知 · +0示例' if key == 'level' and self.context and self.context.get('level_unknown') else '示例 · 请核对')
                self.variables[key] = Value(str(field['value']), lambda key=key: self.changed(key))
        self.calculated = {field['key']: field['value'] for field in self.inputs}
        self.dirty, self.parameter_error = False, ''
        self.refresh_origin(self.owner.manager.session.snapshot())
        self.refresh_text()
        self.emit()

    def refresh_text(self):
        if self.rendered is None or self.dirty:
            return
        source = (self.context or {}).get('source_label', '')
        bounds = (self.context or {}).get('conditions', '')
        strength_bounds = ((self.context or {}).get('strength_conditions', '') if self.input_origins.get('strength') != '手填' else
                           '力量参数为明确手填参考；尚未据此重算戒指、天赋与临时状态。') if 'strength' in self.variables else ''
        if self.input_origins.get('strength') == '手填' and '力量' in bounds:
            bounds = '原记录条件（当前力量已改为手填）：' + bounds
        note = '用户用途/假设备注（未验证）：\n'+self.note.get() if self.note.get() else ''
        self.show_text('\n\n'.join(text for text in (source, bounds, strength_bounds, detail_text(self.rendered), note, self.workspace_error) if text))

    def refresh_origin(self, snap):
        if self.parameter_error or self.plan_error or self.workspace_error:
            self.origin.text = self.parameter_error or self.plan_error or self.workspace_error
        elif self.dirty:
            self.origin.text = '参数已修改，旧结果不可继续参考；点击计算。'
        elif self.saved_plan:
            self.origin.text = '保存的参考方案 · '+self.saved_plan['name']+' · 固定参数，未跟随当前角色'
        elif self.rendered:
            uses = any(value.startswith(('快照', '手动局势')) for value in self.input_origins.values())
            old = uses and (snap.get('error') or not snap.get('data') or snap.get('stale') or tuple(self.context['stamp']) != self.source_stamp(snap))
            if uses and self.input_origins.get('strength', '').startswith(('快照', '手动局势')) and 'character_scene' in self.context:
                old = old or self.context['character_scene'] != (snap.get('data') or {}).get('character_scene')
            source = '旧参考：快照已变/过期，请核对。' if old else ('手动局势' if snap['settings']['mode'] == 'manual' else f"槽位 {snap['active_slot']} 快照")+'；其余示例/手填。' if uses else '示例/手填；未自动读取当前角色。'
            self.origin.text = '百科 '+self.rendered['version']+' · '+source

    def changed(self, key=None):
        self.edit_revision += 1
        self.ticket = None  # An older worker cannot clear a new draft.
        self.dirty = self.draft_modified = True
        self.parameter_error = ''
        if key:
            self.input_origins[key] = '手填'
        self.origin.text = '参数已修改，旧结果不可继续参考；点击计算。'
        self.show_text('参数已修改，请重新计算。')
        self.emit()

    def note_changed(self):
        self.edit_revision += 1
        self.draft_modified = True
        self.refresh_text()
        self.emit()

    def raw_params(self):
        return {key: str(value.get()) for key, value in self.variables.items()}

    def calculate(self, _=None):
        if not self.identity:
            return 'break'
        from .values import integer_parameters
        try:
            raw = {key: value.strip() for key, value in self.raw_params().items()}
            if any(not value for value in raw.values()):
                raise ValueError('请填写全部显示的参数')
            # The actual detail bounds determine whether this entry supports signed equipment levels.
            signed = any(field['key'] == 'level' and field.get('min', 0) < 0 for field in self.inputs)
            integer_parameters(raw, signed_equipment=signed, health_fields=raw)
            for field in self.inputs:
                number = float(raw[field['key']])
                if not field.get('min', number) <= number <= field.get('max', number):
                    raise ValueError(f"{field['label']}须在 {field['min']}–{field['max']} 之间")
        except (ValueError, OverflowError) as exc:
            self.parameter_error = self.origin.text = str(exc)
            self.emit()
            return 'break'
        self.ticket = self.owner.worker.request('detail', self.identity, raw)
        self.submitted, self.parameter_error = dict(raw), ''
        self.show_text('正在计算…')
        self.emit()
        return 'break'

    def pin(self):
        if not self.identity or self.dirty or self.rendered is None or self.calculated is None:
            self.origin.text = '先选择条目并计算有效参数，再固定参考。'
        else:
            self.owner.pinned = (self.identity, dict(self.calculated))
            self.owner.pinned_note = self.note.get()
            self.owner.peek_key = None
            self.origin.text = '已固定；返回游戏后按速查键查看。固定的是百科参考。'
        self.emit()

    def clear_pin(self):
        self.owner.pinned, self.owner.peek_key = None, None
        self.owner.pinned_note = ''
        self.origin.text = '已清除固定；游戏速查恢复装备与局势快照。'
        self.emit()

    def favorite(self):
        try:
            if not self.identity:
                raise ValueError('先选择资料，再收藏。')
            session = self.owner.manager.session
            enabled = self.identity not in session.workspace_status()['favorite_ids']
            session.workspace_action({'action': 'favorite', 'entry': self.identity, 'enabled': enabled})
            self.origin.text = '已收藏；重启后保留。' if enabled else '已取消收藏。'
        except (ValueError, OSError) as exc:
            self.origin.text = str(exc)
        self.emit()

    def save_plan(self, name=None, update=False):
        if not self.identity or self.dirty or self.rendered is None or self.calculated is None:
            self.origin.text = '先计算有效参数，再命名保存。'
            self.emit()
            return False
        if name is None:
            self.host.command('name_plan', name=self.saved_plan['name'] if self.saved_plan else self.rendered['name'],
                              note=self.note.get(), existing=bool(self.saved_plan), pending_save=self.pending_save)
            return False
        source = dict(self.saved_plan['origin'] if self.saved_plan else (self.context or {}).get('source') or {'mode': 'example', 'snapshot_at': None, 'slot': None})
        if self.context and not self.saved_plan and source.get('mode') == 'example':
            source = {'mode': self.context['mode'], 'snapshot_at': self.context['stamp'][-1], 'slot': self.context['stamp'][3]}
        source = {key: source.get(key) for key in ('mode', 'snapshot_at', 'slot')}
        source['fields'] = {key: self.input_origins[key] for key in self.calculated}
        payload = {'action': 'save', 'kind': 'numeric', 'name': name, 'entry': self.identity,
                   'params': dict(self.calculated), 'source': source, 'note': self.note.get()}
        if update and self.saved_plan:
            payload.update(record_id=self.saved_plan['id'], expected_record_revision=self.saved_plan['record_revision'])
        try:
            self.saved_plan = self.owner.manager.session.workspace_action(payload)['plan']
            self.note.value = self.saved_plan.get('note', '')
            self.pending_save = None
            self.plan_error, self.draft_modified = '', False
            self.refresh_text()
            self.origin.text = ('已更新原方案「' if update else '已保存「')+name+'」；重启后保留。'
            self.emit()
            return True
        except (ValueError, OSError) as exc:
            self.plan_error = self.origin.text = str(exc)
            self.emit()
            return False

    @staticmethod
    def filtered_plans(plans, query='', kind='全部类型', order='最近更新'):
        kinds = {'数值方案': 'numeric', '装备方案': 'equipment', '炼金方案': 'alchemy', '手动草稿': 'manual', '角色条件': 'character'}
        rows = [row for row in plans if query.casefold().strip() in (row['name']+'\n'+row.get('note','')).casefold() and (kind == '全部类型' or row['kind'] == kinds.get(kind))]
        return sorted(rows, key=(lambda row: (row['name'].casefold(), row['id'])) if order == '名称' else
                      lambda row: (-row['updated'], row['name'].casefold(), row['id']))

    def choose_plan(self, query=None, kind=None, order=None):
        previous = getattr(self, 'plan_filters', ('', '全部类型', '最近更新'))
        self.plan_filters = tuple(old if new is None else new
                                  for new, old in zip((query, kind, order), previous))
        query, kind, order = self.plan_filters
        status = self.owner.manager.session.workspace_status()
        if not status['available']:
            self.origin.text = status['error']
            self.emit()
            return
        labels = {'numeric': '数值方案', 'equipment': '装备方案', 'alchemy': '炼金方案', 'manual': '手动草稿', 'character': '角色条件'}
        rows = self.filtered_plans(status['plans'], query, kind, order)
        self.host.command('plans', rows=[{'id': row['id'], 'text': row['name']+' · '+labels.get(row['kind'], row['kind'])+' · '+plan_updated_text(row['updated'])} for row in rows])

    def open_plan(self, record_id, confirm_draft=True):
        if confirm_draft:
            return self.guard('打开方案', lambda: self.open_plan(record_id, False))
        try:
            opened = self.owner.manager.session.knowledge.reopen(record_id)
            if opened['plan']['kind'] != 'numeric':
                self.owner.manager.session.panel.request('workspace', plan_id=record_id)
                self.origin.text = '已将所选方案交给完整面板；请核对固定条件。'
                self.emit()
                return True
            self.ticket = self.submitted = None
            self.clear_params()
            self.saved_plan, self.identity = opened['plan'], opened['plan']['entry']
            self.note.value = self.saved_plan.get('note', '')
            self.context, self.plan_error = None, ''
            self.render(opened['result'])
            return True
        except (ValueError, OSError) as exc:
            self.origin.text = str(exc)
            self.emit()
            return False

    def reload_plan(self):
        if self.saved_plan:
            self.guard('重新读取最新方案', lambda: self.open_plan(self.saved_plan['id'], False))

    def open_reference(self, reference, source=None, note=''):
        def apply():
            self.undo_state = self.draft(include_result=True)
            snap = self.owner.manager.session.snapshot()
            self.clear_params()
            self.saved_plan, self.plan_error = None, ''
            self.identity = reference['entry']
            self.context = {'params': dict(reference.get('params', {})), 'stamp': self.source_stamp(snap),
                'mode': snap['settings']['mode'], 'level_unknown': reference.get('level_origin') == 'unknown',
                'source': source or {}, 'conditions': note, 'source_label': reference.get('source_label', '')}
            if 'strength' in self.context['params']:
                exact_source = (source and source.get('mode') == snap['settings']['mode']
                    and source.get('snapshot_at') == snap.get('modified') and source.get('slot') == snap.get('active_slot')
                    and self.context['params']['strength'] == self.hero_context(snap).get('strength'))
                if exact_source:
                    self.bind_strength_context(self.context, (snap.get('data') or {}).get('character_scene'))
                else:
                    self.context.update(strength_origin='保存的力量参考 · 角色条件来源未确认',
                        strength_conditions='按所给力量参数试算；此参考未携带可核对的当前角色条件，不能视为当前总力量。')
            self.ticket = self.owner.worker.request('detail', self.identity, self.context['params'])
            self.submitted = None
            self.show_text('正在读取数值…；可撤回本次参数导入。')
            self.emit()
        self.guard('打开参考参数', apply)

    def draft(self, include_result=False):
        value = {'entry': self.identity, 'raw_params': self.raw_params(),
            'origins': dict(self.input_origins), 'context': copy.deepcopy(self.context),
            'saved_plan': copy.deepcopy(self.saved_plan), 'note': self.pending_save['note'] if self.pending_save else self.note.get(),
            'pending_save': copy.deepcopy(self.pending_save),
            'dirty': self.dirty, 'draft_modified': self.draft_modified, 'query': self.query.get()}
        if include_result:
            value.update(inputs=copy.deepcopy(self.inputs), calculated=copy.deepcopy(self.calculated),
                         rendered=copy.deepcopy(self.rendered), result_text=self.text.text)
        return value

    def restore_draft(self, draft, _runtime=False):
        if not isinstance(draft, dict) or draft.get('entry') not in {row['id'] for row in self.owner.manager.session.catalog.entries}:
            raise ValueError('草稿资料身份无效，原文件仍保留')
        self.ticket = self.submitted = None
        detail = self.owner.manager.session.values.detail(draft['entry'])
        fields = detail['inputs']
        if set(draft.get('raw_params', {})) != {field['key'] for field in fields}:
            raise ValueError('草稿参数与此资料不匹配；原文件仍保留')
        self.identity, self.inputs = draft['entry'], copy.deepcopy(fields)
        self.context, self.saved_plan = copy.deepcopy(draft.get('context')), copy.deepcopy(draft.get('saved_plan'))
        self.input_origins = dict(draft.get('origins', {}))
        self.variables = {key: Value(str(value), lambda key=key: self.changed(key)) for key, value in draft.get('raw_params', {}).items()}
        self.note.value, self.query.value = draft.get('note', ''), draft.get('query', '')
        self.set_pending_save(draft.get('pending_save'))
        self.calculated = copy.deepcopy(draft.get('calculated')) if _runtime else None
        self.rendered = copy.deepcopy(draft.get('rendered')) if _runtime else None
        self.dirty, self.draft_modified = True, True
        self.edit_revision += 1
        self.origin.text = '已载入未完成草稿；尚未重新计算或保存，不会应用到游戏。'
        self.show_text('原始草稿已恢复，请核对后重新计算。')
        self.show()
        self.emit()

    def undo_import(self):
        if self.undo_state is None:
            return
        prior, self.undo_state = self.undo_state, None
        if prior.get('entry'):
            self.restore_draft(prior, _runtime=True)
            self.dirty, self.draft_modified = prior['dirty'], prior['draft_modified']
            self.show_text(prior['result_text'])
            self.refresh_origin(self.owner.manager.session.snapshot())
        else:
            self.clear_params()
            self.identity = self.context = self.saved_plan = self.calculated = self.rendered = None
            self.show_text(prior.get('result_text', '选择资料查看数值。'))
        self.origin.text += ' · 已撤回本次参数导入'
        self.emit()

    def save_draft_copy(self):
        session = self.owner.manager.session
        pending = self.pending_save
        if pending:
            self.note.value = pending['note']
        if self.identity and not self.dirty and self.calculated is not None:
            name = (pending['name'] if pending else self.saved_plan['name'] if self.saved_plan else self.rendered['name'])+' 草稿副本'
            if pending and not pending['name'].strip():
                name = ''  # Preserve an unfinished name as a raw draft, not a false valid plan.
            if self.save_plan(name[:80], False):
                return
        session.save_exit_draft('native', 'numeric', '数值速查未完成草稿', self.draft())
        self.draft_modified = False

    def set_pending_save(self, value):
        if value is not None:
            if (not isinstance(value, dict) or set(value) != {'name', 'note', 'update'}
                    or not isinstance(value['name'], str) or len(value['name']) > 80
                    or not isinstance(value['note'], str) or len(value['note']) > 1200
                    or type(value['update']) is not bool):
                raise ValueError('未完成的方案命名草稿不完整；原始记录仍保留')
        self.pending_save = copy.deepcopy(value)

    def handle(self, item):
        action = item['action']
        if action == 'query':
            self.query.set(item.get('text', '')[:200])
        elif action == 'edit':
            # Closed naming dialogs omit this field; cancellation and success clear it explicitly.
            if 'pending_save' in item:
                self.set_pending_save(item['pending_save'])
            for key, raw in item.get('values', {}).items():
                if key in self.variables:
                    self.variables[key].set(str(raw)[:80])
            self.note.set(item.get('note', '')[:1200])
            self.edit_revision = max(self.edit_revision, int(item.get('draft_revision', 0)))
        elif action == 'select':
            self.list.selection_set(item['index'])
            self.select()
        elif action == 'first':
            self.open_first_result()
        elif action == 'more':
            self.more_results()
        elif action == 'calculate':
            self.calculate()
        elif action == 'save_named':
            self.set_pending_save({'name': item.get('name', ''), 'note': item.get('note', ''),
                                   'update': bool(item.get('update'))})
            self.note.set(item.get('note', ''))
            self.save_plan(item.get('name', ''), bool(item.get('update')))
        elif action == 'save_dialog_edit':
            self.set_pending_save(item.get('pending_save'))
            self.edit_revision += 1
        elif action == 'save_dialog_closed':
            if item.get('cancelled', True):
                self.pending_save = None
            self.edit_revision += 1
        elif action == 'filter_plans':
            self.choose_plan(item.get('query', ''), item.get('kind', '全部类型'), item.get('order', '最近更新'))
        elif action == 'open_plan':
            self.open_plan(item['id'])
        elif action == 'replace_decision':
            callback, self.confirmation = self.confirmation, None
            if item.get('decision') == 'saved':
                self.save_draft_copy()
            if callback and item.get('decision') in ('saved', 'discard'):
                callback()
        elif action in ('favorite', 'pin', 'clear_pin', 'choose_plan', 'save_plan', 'reload_plan', 'undo_import'):
            getattr(self, action)()
        elif action == 'provenance' and self.rendered:
            provenance = self.rendered.get('provenance', {})
            self.show_text('\n\n'.join([provenance.get('summary', ''), *provenance.get('limits', []), *[row['label']+'\n'+row['url'] for row in provenance.get('links', [])]]))
        elif action == 'source_link' and self.rendered:
            links = self.rendered.get('provenance', {}).get('links', [])
            index = item.get('index', -1)
            if type(index) is int and 0 <= index < len(links):
                webbrowser.open(links[index]['url'])
        elif action == 'hide':
            self.hide()
        self.emit()

    def emit(self):
        self.host.revision += 1
        fields = [{**field, 'raw': self.variables[field['key']].get(), 'origin': self.input_origins.get(field['key'], '')} for field in self.inputs if field['key'] in self.variables]
        self.host.command('lookup_state', draft_revision=self.edit_revision, query=self.query.get(),
            rows=[{'text': text} for text in self.list.values], fields=fields, note=self.note.get(),
            result=self.text.text, status=self.origin.text, dirty=self.has_draft(),
            can_more=self.suggested or len(self.rows) < self.total, undo=bool(self.undo_state),
            sources=self.rendered.get('provenance', {}).get('links', []) if self.rendered else [])
        self.owner.manager.native_ui.report_drafts()

    def open_first_result(self, _=None):
        if self.pending:
            self.search()
        if self.rows:
            self.list.selection_set(0)
            self.select()
        return 'break'

    def focus_search(self, _=None):
        self.host.command('focus_search')
        return 'break'

    def show(self):
        target = self.owner.native.game()
        if target or not self.visible():
            self.return_target = target
        if not self.query.get().strip():
            self.search(preserve_detail=True)
        self.host.command('show', surface='lookup')

    def hide(self):
        # Only an explicit helper close may return to a previously verified game.
        target, self.return_target = self.return_target, None
        native = self.owner.native
        if target and self.host.is_foreground('lookup', native):
            from .native_focus import return_to_game
            return_to_game(native, target, self.host.process.pid)
        self.host.command('hide', surface='lookup')

    def visible(self):
        return bool(self.host.visibility.get('lookup'))

    def foreground(self):
        return self.host.is_foreground('lookup', self.owner.native)

    def destroy(self):
        if self.pending:
            self.owner.manager.root.after_cancel(self.pending)
            self.pending = None
        self.window.withdraw()
