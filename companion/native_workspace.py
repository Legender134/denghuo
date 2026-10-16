"""Python-owned numeric workspace; the helper owns controls, never game rules."""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timezone
import webbrowser

from .native_host import Value, TextState, NativeWindow, binding_token
from .quick_reference import detail_text

ITEM_CATEGORIES = {'药剂': 'items.potions.', '卷轴': 'items.scrolls.',
                   '武器': 'items.weapon.', '护甲': 'items.armor.',
                   '戒指': 'items.rings.', '法杖': 'items.wands.', '食物': 'items.food.'}
PAGE_SIZE = 30


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
        self.category = '常用'
        self.browse_all = False
        self.browse_offset = 0
        self.query = Value('', self.schedule_search)
        self.note = Value('', self.note_changed)
        self.list, self.origin, self.text = Rows(), TextState(), TextState()
        self.rows, self.inputs, self.variables, self.input_origins = [], [], {}, {}
        self.search_suggestions, self.search_error = [], ''
        self.identity = self.context = self.saved_plan = self.rendered = self.calculated = None
        self.selected_row = {}
        self.workspace_error = self.plan_error = self.parameter_error = ''
        self.workspace_revision, self.favorite_ids = None, set()
        self.dirty = self.draft_modified = False
        self.submitted = self.ticket = self.pending = self.return_target = None
        self.suggested, self.total = False, 0
        self.edit_revision, self.undo_state, self.confirmation = 0, None, None
        self.pending_save = None
        self.focus_result = False
        self.focus_suggestions = False
        self.focus_listing = False
        self.calculating = False
        self.operation_receipt = ''
        self.origin_brief = '参考示例 / 手填条件'
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
                if key in ('hero_level', 'max_hp', 'hp', 'strength', 'depth', 'current_shield')}

    @staticmethod
    def scoped_origin(label, context):
        """Keep each captured field identifiable after importing another character."""
        if label.startswith(('手填', '示例', '未确认')) or ' · 槽位 ' in label:
            return label
        source = (context or {}).get('source') or {}
        if source.get('mode') != 'save':
            return label
        stamp = source.get('snapshot_at')
        suffix = ' · 槽位 '+str(source.get('slot') or '?')+' · '+(
            plan_updated_text(stamp)+' 保存' if type(stamp) in (int, float) else '保存时间未记录')
        return label[:120-len(suffix)]+suffix

    @classmethod
    def entry_context(cls, snap, identity, *, include_boss=False):
        from .decisions import source, healing_context, dot_context, dot_origins, boss_context
        from .public_skills import skill_context
        specific = skill_context(snap, identity)
        params = cls.hero_context(snap)
        params.update(specific.get('params', {}))
        if identity in ('items.potions.potionofhealing', 'items.potions.elixirs.elixirofhoneyedhealing'):
            water = skill_context(snap, 'items.dewdrop')
            if 'vial' in water.get('params', {}) and (snap['settings']['mode'] == 'save'
                    or any(row.get('kind') == 'VialOfBlood' for row in (snap.get('data') or {}).get('items', []))):
                params['vial'] = water['params']['vial']
                specific['field_origins'] = {'vial': water['field_origins']['vial']}
        if include_boss:
            params.update(boss_context(snap, identity))
        if identity == 'actors.buffs.healing' and not snap.get('error'):
            buffs = [row for row in (snap.get('data') or {}).get('buffs', []) if row.get('kind') == 'Healing']
            if len(buffs) == 1:
                params.update(healing_context(buffs[0]))
        if not snap.get('error'):
            buffs = [row for row in (snap.get('data') or {}).get('buffs', []) if row.get('reference_id') == identity]
            if len(buffs) == 1:
                fields = dot_context(buffs[0])
                params.update(fields)
                specific['field_origins'] = {**specific.get('field_origins', {}), **dot_origins(fields)}
        provenance = source(snap)
        context = {**specific, 'params': params, 'stamp': cls.source_stamp(snap),
                   'source': provenance, 'source_label': provenance['label'], 'mode': provenance['mode']}
        cls.bind_strength_context(context, (snap.get('data') or {}).get('character_scene'))
        return context

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
        retained = (self.rendered or {}).get('retained_legacy_params', [])
        saved_params = {key: value for key, value in (self.saved_plan or {}).get('params', {}).items() if key not in retained}
        return bool(self.pending_save) or self.draft_modified or self.dirty or bool(self.saved_plan and (
            (self.calculated is not None and self.calculated != saved_params) or self.note.get() != self.saved_plan.get('note', '')))

    def schedule_search(self):
        self.browse_all = False
        root = self.owner.manager.root
        if self.pending:
            root.after_cancel(self.pending)
        self.pending = root.after(180, self.search)

    def categories(self):
        return ['常用', '全部', '收藏', '最近', '随身', *ITEM_CATEGORIES] + list(dict.fromkeys(
            row['category'] for row in self.owner.manager.session.catalog.entries))

    def search(self, preserve_detail=False):
        if self.pending:
            self.owner.manager.root.after_cancel(self.pending)
        self.pending = None
        self.browse_offset = 0
        session = self.owner.manager.session
        query = self.query.get().strip()[:200]
        self.search_suggestions, self.search_error = [], ''
        status = session.workspace_status()
        self.workspace_revision, self.favorite_ids = status['revision'], set(status['favorite_ids'])
        self.workspace_error = status.get('error', '')
        self.suggested = not query and self.category == '常用' and not self.browse_all
        if self.suggested:
            self.rows = []
            seen = set()
            for group, label in (('common', '常用'), ('favorites', '收藏'), ('recent', '最近')):
                for row in status[group]:
                    if row['id'] not in seen:
                        self.rows.append({**row, 'lookup_group': label,
                                          'lookup_example': group in ('favorites', 'recent')})
                        seen.add(row['id'])
            self.total = len(session.catalog.entries)
        else:
            result = self.browse_results(status=status)
            self.rows, self.total = result['entries'], result['total']
            self.search_suggestions = result['suggestions']
        self.list.delete()
        for row in self.rows:
            self.list.insert('end', row.get('lookup_label', row['name']))
        if (preserve_detail or self.has_draft()) and self.identity:
            self.refresh_origin(session.snapshot())
        else:
            self.clear_params()
            self.identity = self.context = self.saved_plan = self.rendered = self.calculated = None
            self.ticket = self.submitted = None
            self.plan_error = ''
            self.origin.text = '百科参数为参考示例，请按游戏核对。'
            self.show_text('选择条目查看。' if self.rows else '没有匹配条目。')
        self.emit()

    def browse_results(self, *, offset=0, status=None):
        session = self.owner.manager.session
        query = self.query.get().strip()[:200]
        if self.category in ITEM_CATEGORIES:
            found = session.catalog.search(query, limit=len(session.catalog.entries))
            prefix = ITEM_CATEGORIES[self.category]
            rows = [row for row in found['entries'] if row['id'].startswith(prefix)]
            return {'entries': rows[offset:offset+PAGE_SIZE], 'total': len(rows),
                    'suggestions': [row for row in found['suggestions'] if row['id'].startswith(prefix)] if not rows else []}
        if self.category not in ('收藏', '最近', '随身'):
            return session.catalog.search(query, category='全部' if self.category == '常用' else self.category, limit=PAGE_SIZE, offset=offset)
        status = status or session.workspace_status()
        rows = copy.deepcopy(status[{'收藏':'favorites', '最近':'recent', '随身':'current'}[self.category]])
        if self.category == '随身':
            # Keep each captured object; its upgrade/effect calculations live in its detail.
            derived = [related for row in rows for related in row.get('related', [])]
            rows = [row for row in rows if row not in derived]
        if query:
            matches = {row['id'] for row in session.catalog.search(query, limit=len(session.catalog.entries))['entries']}
            rows = [row for row in rows if row['id'] in matches]
        for row in rows:
            if self.category == '随身':
                captured = status.get('character_scene', {})
                if row['lookup_context'].get('stamp') == captured.get('stamp'):
                    self.bind_strength_context(row['lookup_context'], captured.get('current'))
                if row['lookup_context'].get('level_unknown'):
                    row['lookup_label'] += '（等级未知）'
            else:
                row['lookup_example'] = True
        return {'entries': rows[offset:offset+PAGE_SIZE], 'total':len(rows), 'suggestions':[]}

    def more_results(self):
        if self.pending:
            self.search(preserve_detail=True)
            return
        if self.suggested:
            self.suggested = False
            self.browse_all = True
            self.category = '全部'
            offset = 0
        else:
            if self.browse_offset+len(self.rows) >= self.total: return
            offset = self.browse_offset+len(self.rows)
        self.browse_page(offset)

    def previous_results(self):
        if self.pending:
            self.search(preserve_detail=True)
            return
        if self.browse_offset:
            self.browse_page(max(0, self.browse_offset-PAGE_SIZE))

    def browse_page(self, offset):
        result = self.browse_results(offset=offset)
        if offset and not result['entries']:
            offset = max(0, (result['total']-1)//PAGE_SIZE*PAGE_SIZE)
            result = self.browse_results(offset=offset)
        self.browse_offset, self.rows = offset, result['entries']
        self.total = result['total']
        self.search_suggestions = result.get('suggestions', [])
        self.list.delete()
        for row in self.rows:
            self.list.insert('end', row.get('lookup_label', row['name']))
        self.focus_listing = True
        self.emit()

    def show_text(self, text):
        self.text.text = text

    def clear_params(self):
        self.inputs, self.variables, self.input_origins = [], {}, {}
        self.operation_receipt = ''
        self.parameter_error = ''
        self.dirty = self.draft_modified = False
        self.note.value = ''
        self.pending_save = None
        self.calculating = False

    def guard(self, label, action):
        if not self.has_draft():
            action()
            return True
        self.confirmation = (self.edit_revision, action)
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
        if self.pending:
            self.search(preserve_detail=True)
        self.focus_result = True
        self.operation_receipt = ''
        self.saved_plan, self.plan_error = None, ''
        self.identity = row['id']
        self.selected_row = copy.deepcopy(row)
        self.rendered = self.calculated = None
        self.clear_params()
        self.context = copy.deepcopy(row.get('lookup_context'))
        if (self.context and self.identity in ('items.potions.potionofhealing', 'items.potions.elixirs.elixirofhoneyedhealing')
                and 'vial' not in self.context['params'] and not self.context.get('fixed_origins')):
            snap = self.owner.manager.session.snapshot()
            if tuple(self.context.get('stamp') or ()) == self.source_stamp(snap):
                current = self.entry_context(snap, self.identity)
                if 'vial' in current['params']:
                    self.context['params']['vial'] = current['params']['vial']
                    self.context.setdefault('field_origins', {})['vial'] = current['field_origins']['vial']
        if self.context is None and not row.get('lookup_example'):
            snap = self.owner.manager.session.snapshot()
            context = self.entry_context(snap, self.identity)
            if context['params'] or context.get('skill_state'):
                self.context = context
        self.ticket = self.owner.worker.request('detail', self.identity, self.context['params'] if self.context else {})
        self.submitted = None
        self.show_text('正在读取数值…')
        try:
            receipt = self.owner.manager.session.workspace_action({'action': 'remember', 'entry': self.identity})
            self.workspace_error = receipt.get('recovery_warning', '')
        except (ValueError, OSError) as exc:
            self.workspace_error = str(exc)
        self.emit()

    def render(self, detail, error=None, *, show_result=False):
        if detail and detail.get('id') != self.identity:
            return  # A late result belongs to the previous selected entry.
        if self.submitted is not None and {key: value.strip() for key, value in self.raw_params().items()} != self.submitted:
            self.changed()
            return
        self.calculating = False
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
                prefix = ('独立参考' if self.context and not self.context.get('stamp') and self.context.get('mode')=='example' and self.context.get('source_label') else
                          '参考来源未确认' if self.context and not self.context.get('stamp') else
                          '手动局势' if self.context and self.context.get('mode') == 'manual' else '快照')
                self.input_origins[key] = (self.saved_plan['origin'].get('fields', {}).get(key, '保存的参考参数') if self.saved_plan else
                    (prefix+'已知等级' if key == 'level' else prefix+'已知阶数' if key == 'tier' else
                     (self.context.get('strength_origin') if self.context.get('strength_origin', '').startswith('保存的') else
                      prefix+(self.context.get('strength_origin') or '力量参考 · 角色条件来源未确认')) if key == 'strength' else prefix)
                    if self.context and key in self.context['params'] else
                    '等级未知 · +0示例' if key == 'level' and self.context and self.context.get('level_unknown') else '示例 · 请核对')
                if key in detail.get('missing_inputs', []):
                    self.input_origins[key] = '未确认 · 请填写'
                elif not self.saved_plan and key in (self.context or {}).get('fixed_origins', {}):
                    self.input_origins[key] = self.context['fixed_origins'][key]
                elif not self.saved_plan and key in (self.context or {}).get('field_origins', {}):
                    self.input_origins[key] = ('' if key == 'talent' else prefix+' · ')+self.context['field_origins'][key]
                if not self.saved_plan and key in (self.context or {}).get('params', {}):
                    self.input_origins[key] = self.scoped_origin(self.input_origins[key], self.context)
                self.variables[key] = Value(str(field['value']), lambda key=key: self.changed(key))
        self.calculated = None if detail.get('missing_inputs') else {field['key']: field['value'] for field in self.inputs}
        self.dirty, self.parameter_error = False, ''
        self.refresh_origin(self.owner.manager.session.snapshot())
        self.refresh_text()
        if self.submitted is not None and self.calculated is not None:
            self.focus_result = True
        if show_result:
            self.host.command('show', surface='lookup')
            self.focus_result = True
        self.emit()

    def result_text_parts(self):
        source = (self.context or {}).get('source_label', '')
        bounds = (self.context or {}).get('conditions', '')
        strength_bounds = ((self.context or {}).get('strength_conditions', '') if self.input_origins.get('strength') != '手填' else
                           '力量参数为明确手填参考；尚未据此重算戒指、天赋与临时状态。') if 'strength' in self.variables else ''
        if self.input_origins.get('strength') == '手填' and '力量' in bounds:
            bounds = '原记录条件（当前力量已改为手填）：' + bounds
        note = '用户用途/假设备注（未验证）：\n'+self.note.get() if self.note.get() else ''
        item_note = (self.context or {}).get('user_note')
        saved_note = ('游戏中的用户记录（非游戏规则）：\n' + item_note['title'] + '\n' + item_note['body']) if item_note else ''
        return (source, bounds, strength_bounds, saved_note), (note, self.workspace_error)

    def refresh_text(self):
        if self.rendered is None or self.dirty:
            return
        before, after = self.result_text_parts()
        self.show_text('\n\n'.join(text for text in (*before, detail_text(self.rendered), *after) if text))

    def numeric_presentation(self):
        """Keep tables structured without publishing stale or alternate article content."""
        before, after = self.result_text_parts()
        prose = '\n\n'.join(text for text in (*before, (self.rendered or {}).get('notice', ''), *after) if text)
        if self.dirty or self.parameter_error:
            return [], '\n\n'.join(text for text in (self.text.text, prose) if text)
        if not self.rendered:
            return [], self.text.text
        full = '\n\n'.join(text for text in (*before, detail_text(self.rendered), *after) if text)
        if full != self.text.text:
            return [], self.text.text
        sections = []
        for index, block in enumerate(self.rendered.get('blocks', [])):
            section = copy.deepcopy(block)
            section.update(index=index, collapsed=bool(block.get('columns')), selected_values=[])
            selected = block.get('selected_row')
            rows = block.get('rows', [])
            if type(selected) is int and 0 <= selected < len(rows):
                section['selected_values'] = [{'label': label, 'value': value}
                    for label, value in zip(block.get('columns', []), rows[selected])]
            sections.append(section)
        # Values for the selected conditions precede complete reference tables.
        sections.sort(key=lambda section: (not bool(section.get('values') or section['selected_values']), section['index']))
        food = (self.context or {}).get('food_reference') if self.identity.startswith('items.food.') else None
        if food:
            sections.insert(0, {**copy.deepcopy(food), 'index': -1, 'collapsed': False, 'selected_values': []})
        return sections, prose

    def primary_presentation(self, sections):
        """Use explicit result metadata; never infer the answer by parsing Chinese prose."""
        if self.dirty or self.calculated is None or self.calculating or self.parameter_error:
            return [], ''
        food = (self.context or {}).get('food_reference') if self.identity.startswith('items.food.') else None
        if food:
            return copy.deepcopy(food['primary_values']), food['summary_note']
        mechanism = next((section for section in sections if section.get('reading_notes')), None)
        if mechanism:
            return [], mechanism.get('summary_note', '')
        if self.identity.startswith('actors.mobs.npcs.') and not any(section.get('title') == '常规战斗数值' for section in sections):
            return [], ''  # Task characters lead with their description, not inherited 1 HP.
        explicit = next((section for section in sections if section.get('primary_values')), None)
        section = explicit or next((section for section in sections if section.get('values') or section.get('selected_values')), {})
        values = section.get('primary_values') or section.get('selected_values') or section.get('values') or []
        # Ordinary monsters lead with the combat rules the game does not expose.
        # Special enemy mechanisms keep their explicit primary presentation.
        if ({value.get('label') for value in values} == {'初始生命／上限', '基础伤害范围'}
                and self.identity in ('actors.mobs.rat', 'actors.mobs.gnoll', 'actors.mobs.crab')
                and not any(part.get('title') == '特殊攻击与机制' for part in sections)):
            available = {value['label']: value for value in section.get('values', [])}
            labels = [('基础伤害范围', '普攻'), ('基础减伤范围', '减伤'), ('基础速度倍率', '移速')]
            if all(key in available for key, _ in labels):
                compact = [{**copy.deepcopy(available[key]), 'label': label, 'condition': ''}
                           for key, label in labels]
                return compact, ((section.get('summary_note') or '') + '特殊攻击另计；移速不代表攻击频率。')
        note = section.get('summary_note', section.get('note_summary', section.get('note', '')))
        if self.identity in ('items.potions.potionofhealing', 'items.potions.elixirs.elixirofhoneyedhealing'):
            value = self.calculated.get('vial', -1)
            basis = '凝血试管 ' + ('无效果（−1）' if value < 0 else f'+{value:g}')
            origin = self.input_origins.get('vial', '示例 · 请核对')
            if origin.startswith('快照 · 最近保存的记录 · 槽位 '):
                origin = '快照 · 槽位 '+origin.split(' · 槽位 ', 1)[1].split(' · ', 1)[0]+(
                    ' · 最新记录未确认' if '最新记录未确认' in origin else '')
            note = basis + '（' + origin + '）。' + note
        elif self.identity in ('actors.buffs.poison', 'actors.buffs.bleeding'):
            value = self.calculated['power']
            basis = f'剩余中毒 {value:g} 回合' if self.identity == 'actors.buffs.poison' else f'当前流血强度 {value:g}'
            note = basis + '（' + self.input_origins.get('power', '示例 · 请核对') + '）。' + note
        return copy.deepcopy(values[:2]), note

    def refresh_origin(self, snap):
        self.origin_brief = '参考示例 / 手填条件'
        if self.parameter_error or self.plan_error or self.workspace_error:
            self.origin.text = self.parameter_error or self.plan_error or self.workspace_error
            self.origin_brief = '需要核对 · '+self.origin.text
        elif self.dirty:
            self.origin.text = '参数已修改，旧结果不可继续参考；点击计算。'
            self.origin_brief = '条件已修改 · 待重新计算'
        elif self.rendered and self.rendered.get('missing_inputs'):
            self.origin.text = '当前条件未确认，请补全空白参数后计算。'
            self.origin_brief = '条件未确认 · 需补全参数'
        elif self.saved_plan and not (self.context or {}).get('imported_latest'):
            self.origin.text = '保存的参考方案 · '+self.saved_plan['name']+' · 固定参数，未跟随当前角色'
            self.origin_brief = '保存方案 · 固定条件，未跟随角色'
        elif self.rendered:
            uses = bool((self.context or {}).get('food_reference')) or any(value.startswith(('快照', '手动局势', '参考来源未确认')) for value in self.input_origins.values())
            stamp = (self.context or {}).get('stamp')
            old = uses and (not stamp or snap.get('error') or not snap.get('data') or snap.get('stale') or tuple(stamp) != self.source_stamp(snap))
            if uses and self.input_origins.get('strength', '').startswith(('快照', '手动局势')) and 'character_scene' in self.context:
                old = old or self.context['character_scene'] != (snap.get('data') or {}).get('character_scene')
            independent=any(value.startswith('独立参考') for value in self.input_origins.values())
            source = ('固定参考；未绑定当前角色，条件以所给来源为准。' if independent and not uses else
                      '参考来源未确认；请核对原参数。' if uses and not stamp else
                      '旧参考：快照已变/过期，请核对。' if old else
                      ('手动局势' if snap['settings']['mode'] == 'manual' else f"槽位 {snap['active_slot']} 快照")+'；其余示例/手填。' if uses else
                      '示例/手填；未自动读取当前角色。')
            mixed = bool(((self.context or {}).get('source') or {}).get('mixed_snapshots'))
            if mixed:
                source = '混合来源；保留的条目条件与带入的角色条件请逐项核对。'
            self.origin.text = '百科 '+self.rendered['version']+' · '+source
            self.origin_brief = ('旧参考 · 请核对条件' if old else '独立参考 · 未绑定当前角色' if independent and not uses else
                                 '参考来源未确认' if uses and not stamp else '手填局势与参考条件' if uses and snap['settings']['mode']=='manual' else '快照条件与手填假设' if uses else '示例 / 手填条件')
            if mixed:
                self.origin_brief = '混合来源 · 请逐项核对'+(' · 当前记录已变化' if old else '')
        if (self.rendered and not self.dirty and not self.parameter_error and
                self.identity.startswith('plants.') and self.identity.endswith('$seed')):
            self.origin_brief = '种植触发后 · ' + self.origin_brief
        if not self.dirty and (self.draft_modified or self.pending_save):
            self.origin.text += ' · 当前参数、备注或命名有未保存修改；请核对后保存。'

    def changed(self, key=None):
        self.operation_receipt = ''
        self.edit_revision += 1
        self.ticket = None  # An older worker cannot clear a new draft.
        self.calculating = False
        self.dirty = self.draft_modified = True
        self.parameter_error = ''
        if key:
            self.input_origins[key] = '手填'
        self.origin.text = '参数已修改，旧结果不可继续参考；点击计算。'
        self.origin_brief = '条件已修改 · 待重新计算'
        self.show_text('参数已修改，请重新计算。')
        self.emit()

    def note_changed(self):
        self.operation_receipt = ''
        self.edit_revision += 1
        self.draft_modified = True
        self.refresh_text()
        self.refresh_origin(self.owner.manager.session.snapshot())
        self.emit()

    def raw_params(self):
        return {key: str(value.get()) for key, value in self.variables.items()}

    def calculate(self, _=None):
        if not self.identity or self.calculating:
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
            self.refresh_origin(self.owner.manager.session.snapshot())
            self.emit()
            return 'break'
        self.ticket = self.owner.worker.request('detail', self.identity, raw)
        self.calculating = True
        self.submitted, self.parameter_error = dict(raw), ''
        self.show_text('正在计算…')
        self.emit()
        return 'break'

    def use_latest(self):
        """Explicit, undoable import; unknown fields preserve the actual raw input."""
        if not self.identity or not self.inputs:
            return
        snap = self.owner.manager.session.snapshot()
        if snap.get('error') or not snap.get('data'):
            self.operation_receipt = self.origin.text = '当前角色状态未确认；原参数仍保留。'
            self.emit()
            return
        context = self.entry_context(snap, self.identity, include_boss=True)
        context['imported_latest'] = True
        current_keys = {'hero_level', 'max_hp', 'hp', 'strength', 'depth', 'current_shield'}
        from .decisions import BOSS_REFERENCE_IDS
        if self.identity in BOSS_REFERENCE_IDS:
            current_keys.add('stronger_bosses')
        if self.identity.startswith('actors.hero.talent.') or self.identity.startswith('actors.hero.spells.') and '$' not in self.identity:
            current_keys.add('talent')
        if self.identity in ('items.waterskin', 'items.dewdrop'):
            current_keys.update(('shielding_dew', 'vial', 'dew_volume'))
        if self.identity in ('items.potions.potionofhealing', 'items.potions.elixirs.elixirofhoneyedhealing'):
            current_keys.add('vial')
        if self.identity == 'actors.buffs.healing':
            current_keys.update(('power', 'healing_percent', 'healing_flat', 'vial'))
        if self.identity == 'actors.buffs.corrosion':
            current_keys.update(('power', 'remaining_turns', 'corrosion_public'))
        if self.identity == 'items.armor.glyphs.viscosity$defereddamage':
            current_keys.add('damage')
        eligible = set(self.variables) & current_keys
        if not eligible:
            self.operation_receipt = '此条目没有可带入的角色条件；原物品参数与来源保留。'
            self.emit()
            return
        self.undo_state = self.draft(include_result=True)
        self.operation_receipt = ''
        prior = copy.deepcopy(self.context or {})
        prior_source = prior.get('source') or (self.saved_plan or {}).get('origin') or {}
        imported = eligible & set(context['params'])
        retained = {key for key, label in self.input_origins.items() if key not in imported
                    and not label.startswith(('手填', '示例', '未确认'))}
        different = (tuple(prior.get('stamp') or ()) != tuple(context['stamp']) or
                     any(prior_source.get(key) != context['source'].get(key) for key in ('mode', 'slot', 'snapshot_at')))
        if imported and retained:
            for key in retained:
                self.input_origins[key] = self.scoped_origin(self.input_origins[key], {'source': prior_source})
            if different or prior_source.get('mixed_snapshots'):
                context['source']['mixed_snapshots'] = True
            context['retained_source_label'] = prior.get('retained_source_label', prior.get('source_label', '保存的条目条件'))
            context['retained_conditions'] = prior.get('retained_conditions', prior.get('conditions', ''))
            context['source_label'] = context['retained_source_label']+' · 角色条件：'+context['source_label']
            context['conditions'] = '\n'.join(part for part in (context.get('conditions', ''), context['retained_conditions']) if part)
        prefix = '手动局势' if context['mode'] == 'manual' else '快照'
        for key, variable in self.variables.items():
            if key in current_keys and key in context['params']:
                variable.value = str(context['params'][key])
                self.input_origins[key] = self.scoped_origin(context.get('field_origins', {}).get(key, prefix), context)
            elif key in current_keys:
                if key == 'vial' and self.identity in ('items.potions.potionofhealing', 'items.potions.elixirs.elixirofhoneyedhealing'):
                    self.input_origins[key] = self.input_origins.get(key, '示例 · 请核对').replace(' · 最新记录未确认', '') + ' · 最新记录未确认'
                else:
                    self.input_origins[key] = self.input_origins.get(key, '示例 · 请核对').split(' · 最新记录未确认')[0]+' · 最新记录未确认' + (
                        ' · ' + context['conditions'].split('；')[0] if key in ('talent', 'shielding_dew') and context.get('conditions') else '')
        self.context = context if imported else prior or context
        self.edit_revision += 1
        self.ticket = self.submitted = None
        self.calculating = False
        self.dirty = self.draft_modified = True
        self.calculate()
        self.emit()

    def pin(self):
        if not self.identity or self.dirty or self.rendered is None or self.calculated is None:
            self.origin.text = '先选择条目并计算有效参数，再固定参考。'
        else:
            self.owner.pinned = (self.identity, dict(self.calculated))
            self.owner.pinned_note = self.note.get()
            self.owner.pinned_context = copy.deepcopy(self.context) or {'mode': 'example', 'source_label': '固定参考'}
            self.owner.pinned_context['fixed_origins'] = dict(self.input_origins)
            self.owner.peek_key = None
            self.origin.text = '已固定到随行；本次运行内保留，条件不自动更新。'
        self.operation_receipt = self.origin.text
        self.emit()

    def view_pin(self):
        pinned = copy.deepcopy(self.owner.pinned)
        if not pinned:
            self.operation_receipt = '尚未固定参考。'
            self.emit()
            return
        identity, params = pinned
        context = copy.deepcopy(getattr(self.owner, 'pinned_context', None)) or {
            'mode': 'example', 'source_label': '固定参考', 'params': {}}
        context['params'] = params
        note = getattr(self.owner, 'pinned_note', '')
        def opened():
            self.select_row({'id': identity, 'lookup_context': context})
            self.note.value = note
            self.operation_receipt = '固定参考 · 原参数，未跟随当前角色。'
            self.emit()
        self.guard('查看固定参考', opened)

    def clear_pin(self):
        self.owner.pinned, self.owner.peek_key = None, None
        self.owner.pinned_note = ''
        self.owner.pinned_context = None
        self.origin.text = '已清除固定参考。'
        self.operation_receipt = self.origin.text
        self.emit()

    def favorite(self):
        try:
            if not self.identity:
                raise ValueError('先选择资料，再收藏。')
            session = self.owner.manager.session
            enabled = self.identity not in session.workspace_status()['favorite_ids']
            receipt = session.workspace_action({'action': 'favorite', 'entry': self.identity, 'enabled': enabled})
            if enabled:
                self.favorite_ids.add(self.identity)
            else:
                self.favorite_ids.discard(self.identity)
            self.origin.text = ('已收藏；重启后保留。' if enabled else '已取消收藏。') + receipt.get('recovery_warning', '')
        except (ValueError, OSError) as exc:
            self.origin.text = str(exc)
        self.operation_receipt = self.origin.text
        self.emit()

    def save_plan(self, name=None, update=False):
        if (self.context or {}).get('food_reference'):
            self.operation_receipt = self.origin.text = '此项是捕获的进食参考，没有可保存的计算参数；可以收藏资料。'
            self.emit()
            return False
        if not self.identity or self.dirty or self.rendered is None or self.calculated is None:
            self.operation_receipt = self.origin.text = '先计算有效参数，再命名保存。'
            self.emit()
            return False
        if name is None:
            self.host.command('name_plan', name=self.saved_plan['name'] if self.saved_plan else self.rendered['name'],
                              note=self.note.get(), existing=bool(self.saved_plan), pending_save=self.pending_save)
            return False
        source = dict(self.saved_plan['origin'] if self.saved_plan and not (self.context or {}).get('imported_latest') else (self.context or {}).get('source') or {'mode': 'example', 'snapshot_at': None, 'slot': None})
        if self.context and self.context.get('stamp') and not self.saved_plan and source.get('mode') == 'example':
            source = {'mode': self.context['mode'], 'snapshot_at': self.context['stamp'][-1], 'slot': self.context['stamp'][3]}
        source = {key: copy.deepcopy(source[key]) for key in ('mode', 'snapshot_at', 'slot', 'references', 'mixed_snapshots') if key in source}
        source['fields'] = {key: self.input_origins[key] for key in self.calculated}
        payload = {'action': 'save', 'kind': 'numeric', 'name': name, 'entry': self.identity,
                   'params': dict(self.calculated), 'source': source, 'note': self.note.get()}
        if update and self.saved_plan:
            payload.update(record_id=self.saved_plan['id'], expected_record_revision=self.saved_plan['record_revision'])
        try:
            receipt = self.owner.manager.session.workspace_action(payload)
            self.saved_plan = receipt['plan']
            if self.context:
                self.context.pop('imported_latest', None)
            self.note.value = self.saved_plan.get('note', '')
            self.pending_save = None
            self.plan_error, self.draft_modified = '', False
            self.refresh_text()
            self.operation_receipt = self.origin.text = ('已更新原方案「' if update else '已保存「')+name+'」；重启后保留。'+receipt.get('recovery_warning', '')
            self.emit()
            return True
        except (ValueError, OSError) as exc:
            self.operation_receipt = self.plan_error = self.origin.text = str(exc)
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
        try:
            opened = self.owner.manager.session.knowledge.reopen(record_id)
            if opened['plan']['kind'] != 'numeric':
                workspace = getattr(self.owner.manager.native_ui, 'workspace', None)
                if workspace and opened['plan']['kind'] in ('equipment', 'alchemy', 'character'):
                    workspace.open_plan(opened)
                    return True
                self.owner.manager.session.panel.request('workspace', plan_id=record_id)
                self.origin.text = '已将所选方案交给完整面板；请核对固定条件。'
                self.emit()
                return True
            if confirm_draft:
                return self.guard('打开方案', lambda: self.open_plan(record_id, False))
            if self.pending:
                self.search(preserve_detail=True)
            self.ticket = self.submitted = None
            self.clear_params()
            self.saved_plan, self.identity = opened['plan'], opened['plan']['entry']
            self.selected_row = {}
            self.note.value = self.saved_plan.get('note', '')
            self.context, self.plan_error = None, ''
            if opened['result'] is None:
                self.rendered = self.calculated = None
                self.dirty = self.draft_modified = False
                self.origin.text = '当前版本无法计算；原方案参数、来源、规则版本和备注仍保留。'
                self.show_text(self.origin.text+'\n'+opened.get('calculation_error', '')+
                    '\n可复制下列原记录；在完整面板打开此方案可编辑参数另存或导出资料库。\n\n'+
                    json.dumps(self.saved_plan, ensure_ascii=False, indent=2))
                self.host.command('show', surface='lookup')
                self.focus_result = True
                self.emit()
                try:
                    self.owner.manager.session.panel.request('workspace', plan_id=record_id)
                    self.origin.text += ' 已在完整面板打开此原方案，可核对后编辑另存。'
                except (ValueError, OSError) as exc:
                    self.origin.text += ' 完整面板暂时无法打开：'+str(exc)+'；当前原记录仍可复制。'
                self.emit()
                return True
            self.render(opened['result'], show_result=True)
            return True
        except (ValueError, OSError) as exc:
            self.origin.text = str(exc)
            self.emit()
            return False

    def reload_plan(self):
        if self.saved_plan:
            self.guard('重新读取最新方案', lambda: self.open_plan(self.saved_plan['id'], False))

    def open_reference(self, reference, source=None, note=''):
        reference = copy.deepcopy(reference)
        source = copy.deepcopy(source if source is not None else reference.get('source') or {})
        captured = reference.get('stamp')
        stamp = tuple(captured) if isinstance(captured, (list, tuple)) and len(captured) == 6 else None
        def apply():
            if self.pending:
                self.search(preserve_detail=True)
            self.focus_result = True
            self.undo_state = self.draft(include_result=True)
            snap = self.owner.manager.session.snapshot()
            self.clear_params()
            self.saved_plan, self.plan_error = None, ''
            self.identity = reference['entry']
            self.selected_row = {}
            self.context = {'params': dict(reference.get('params', {})), 'stamp': stamp,
                'mode': source.get('mode') or (stamp[2] if stamp else 'example'), 'level_unknown': reference.get('level_origin') == 'unknown',
                'source': source or {}, 'conditions': note or reference.get('conditions', ''), 'source_label': reference.get('source_label', '')}
            self.context['field_origins'] = dict(reference.get('field_origins', {}))
            if self.identity.startswith('items.food.') and reference.get('food_reference'):
                self.context['food_reference'] = copy.deepcopy(reference['food_reference'])
            if 'strength' in self.context['params']:
                exact_source = (stamp == self.source_stamp(snap) and source and source.get('mode') == snap['settings']['mode']
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
        self.operation_receipt = ''
        self.selected_row = {}
        self.context, self.saved_plan = copy.deepcopy(draft.get('context')), copy.deepcopy(draft.get('saved_plan'))
        self.input_origins = dict(draft.get('origins', {}))
        self.variables = {key: Value(str(value), lambda key=key: self.changed(key)) for key, value in draft.get('raw_params', {}).items()}
        self.note.value, self.query.value = draft.get('note', ''), draft.get('query', '')
        self.set_pending_save(draft.get('pending_save'))
        self.calculated = copy.deepcopy(draft.get('calculated')) if _runtime else None
        self.rendered = copy.deepcopy(draft.get('rendered')) if _runtime else None
        self.dirty, self.draft_modified = True, True
        self.edit_revision += 1
        self.search(preserve_detail=True)
        self.show()
        selected = next((index for index, row in enumerate(self.rows) if row['id'] == self.identity), None)
        if selected is not None:
            self.list.selection_set(selected)
        self.origin.text = '已载入未完成草稿；尚未重新计算或保存，不会应用到游戏。'
        self.show_text('原始草稿已恢复，请核对后重新计算。')
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

    def exit_copy_payload(self):
        """Capture an independent exit copy on the UI thread, without IO or edits."""
        pending = self.pending_save
        if self.identity and not self.dirty and self.rendered is not None and self.calculated:
            name = pending['name'] if pending else self.saved_plan['name'] if self.saved_plan else self.rendered['name']
            note = pending['note'] if pending else self.note.get()
            try:
                from .knowledge import text, user_note
                name = text(name[:75]+' 草稿副本', '方案名称') if name.strip() else ''
                user_note(note)
            except ValueError:
                name = ''
            if name:
                source = copy.deepcopy(self.saved_plan['origin'] if self.saved_plan and not (self.context or {}).get('imported_latest') else
                    (self.context or {}).get('source') or {'mode': 'example', 'snapshot_at': None, 'slot': None})
                if self.context and self.context.get('stamp') and not self.saved_plan and source.get('mode') == 'example':
                    source = {'mode': self.context['mode'], 'snapshot_at': self.context['stamp'][-1], 'slot': self.context['stamp'][3]}
                source = {key: source[key] for key in ('mode', 'snapshot_at', 'slot', 'references', 'mixed_snapshots') if key in source}
                source['fields'] = {key: self.input_origins[key] for key in self.calculated}
                return {'kind': 'plan', 'payload': {'kind': 'numeric', 'entry': self.identity,
                    'name': name, 'params': copy.deepcopy(self.calculated),
                    'source': source, 'note': note}}
        return {'kind': 'raw', 'draft': copy.deepcopy(self.draft())}

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
        elif action == 'browse':
            category = item.get('category')
            if category in self.categories():
                self.category = category
                self.browse_all = False
                self.search(preserve_detail=True)
        elif action == 'select':
            index = item.get('index', -1)
            if (type(index) is not int or not 0 <= index < len(self.rows)
                    or item.get('token') != binding_token(self.rows[index])):
                self.workspace_error = self.origin.text = '搜索结果已更新，请核对后重新选择；当前草稿仍保留。'
                self.emit()
                return
            self.workspace_error = ''
            self.list.selection_set(index)
            self.select()
        elif action == 'first':
            self.open_first_result()
            return
        elif action == 'related':
            rows = self.related_rows()
            index = item.get('index', -1)
            if type(index) is not int or not 0 <= index < len(rows) or item.get('token') != binding_token(rows[index]):
                self.operation_receipt = '关联资料已变化，请重新打开；当前草稿仍保留。'
            else:
                row = copy.deepcopy(rows[index])
                self.guard('打开关联资料', lambda: self.select_row(row))
        elif action == 'alchemy_recipe':
            row = next((row for row in self.recipe_rows()
                        if row['id'] == item.get('recipe') and row['token'] == item.get('token')), None)
            if row is None:
                self.operation_receipt = '配方资料已变化，请重新打开；当前草稿仍保留。'
            else:
                try:
                    self.owner.manager.native_ui.workspace.add_recipe_target(row['id'])
                except ValueError as error:
                    self.operation_receipt = str(error)
                else:
                    self.operation_receipt = '已加入炼金目标；已有目标与库存仍保留。'
        elif action == 'suggestion':
            if self.pending:
                self.search()
            index = item.get('index', -1)
            if (type(index) is not int or not 0 <= index < len(self.search_suggestions)
                    or item.get('token') != binding_token(self.search_suggestions[index])):
                self.search_error = '搜索建议已更新，请重新选择；当前草稿仍保留。'
                self.emit()
                return
            self.search_error = ''
            row = copy.deepcopy(self.search_suggestions[index])
            self.guard('切换资料', lambda: self.select_row(row))
        elif action == 'more':
            self.more_results()
        elif action == 'previous_results':
            self.previous_results()
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
            self.refresh_origin(self.owner.manager.session.snapshot())
        elif action == 'save_dialog_closed':
            if item.get('cancelled', True):
                self.pending_save = None
                self.refresh_origin(self.owner.manager.session.snapshot())
            self.edit_revision += 1
        elif action == 'filter_plans':
            self.choose_plan(item.get('query', ''), item.get('kind', '全部类型'), item.get('order', '最近更新'))
        elif action == 'open_plan':
            self.open_plan(item['id'])
        elif action == 'replace_decision':
            confirmation, self.confirmation = self.confirmation, None
            if confirmation and item.get('decision') in ('saved', 'discard'):
                revision, callback = confirmation
                if self.edit_revision != revision:
                    raise ValueError('确认期间草稿已变化；原输入仍保留，请重新选择操作。')
                if item.get('decision') == 'saved':
                    self.save_draft_copy()
                callback()
        elif action in ('favorite', 'pin', 'view_pin', 'clear_pin', 'choose_plan', 'save_plan', 'reload_plan', 'undo_import', 'use_latest'):
            getattr(self, action)()
        elif action == 'provenance' and self.rendered:
            provenance = self.rendered.get('provenance', {})
            self.show_text('\n\n'.join([provenance.get('summary', ''), *provenance.get('limits', []), *[row['label']+'\n'+row['url'] for row in provenance.get('links', [])]]))
        elif action == 'source_link' and self.rendered:
            links = self.rendered.get('provenance', {}).get('links', [])
            index = item.get('index', -1)
            if (type(index) is not int or not 0 <= index < len(links)
                    or item.get('token') != self.source_token()):
                self.workspace_error = self.origin.text = '资料来源已更新，请重新打开官方依据菜单；当前草稿仍保留。'
                self.emit()
                return
            self.workspace_error = ''
            webbrowser.open(links[index]['url'])
        elif action == 'hide':
            self.hide()
        self.emit()

    def source_token(self):
        return binding_token({'entry': self.identity, 'provenance': (self.rendered or {}).get('provenance', {})})

    def related_rows(self):
        return self.selected_row.get('related', []) if self.selected_row.get('id') == self.identity else []

    def recipe_rows(self):
        if not self.rendered or self.rendered.get('id') != self.identity:
            return []
        return [{'id': row['id'], 'name': row['name'], 'token': binding_token([self.identity, row])}
                for row in self.rendered.get('alchemy_recipes', [])]

    def emit(self):
        from .reference import native_artwork
        self.host.revision += 1
        entry = self.owner.manager.session.catalog.entry_index.get(self.identity, {})
        if self.selected_row.get('id') == self.identity:
            entry = {**entry, **self.selected_row}
        description = entry.get('description', '')
        paragraph = description.strip().split('\n\n')[0]
        lead = re.match(r'^[\s\S]*?[。！？](?:[”」』"])?', paragraph)
        introduction = lead.group(0) if lead else paragraph
        sections, prose = self.numeric_presentation()
        primary_values, primary_note = self.primary_presentation(sections)
        if self.calculated is not None and not self.dirty and not self.calculating and not self.parameter_error:
            basis = ''
            if self.identity == 'items.waterskin':
                basis = '露珠 ' + str(self.calculated['dew_volume']) + ' 滴（' + self.input_origins.get('dew_volume', '示例 · 请核对') + '）。'
            elif 'stronger_bosses' in self.calculated:
                basis = ('绝命头目' if self.calculated['stronger_bosses'] else '普通首领') + '（' + self.input_origins.get('stronger_bosses', '示例 · 请核对') + '）。'
            primary_note = basis + primary_note
        reading_notes = (next((section['reading_notes'] for section in sections if section.get('reading_notes')), [])
                         if not self.dirty and self.calculated is not None and not self.calculating and not self.parameter_error else [])
        fields = [{**field, 'raw': self.variables[field['key']].get(), 'origin': self.input_origins.get(field['key'], '')} for field in self.inputs if field['key'] in self.variables]
        self.host.command('lookup_state', draft_revision=self.edit_revision, query=self.query.get(),
            focus_result=self.focus_result, focus_suggestions=self.focus_suggestions,
            focus_listing=self.focus_listing,
            rows=[{'text': text, 'name': row['name'], 'kind': row.get('type_label', ''),
                   'hint': ' · '.join(filter(None, (row.get('display_hint', ''),
                       '资料不可用' if row.get('available') is False else
                       '等级未知' if row.get('lookup_context', {}).get('level_unknown') else
                       '主动揭示' if '已主动揭示' in row.get('lookup_label', '') else ''))),
                   'group': row.get('lookup_group', ''),
                   'context': row.get('lookup_label', '') if row.get('lookup_context') else '',
                   'token': binding_token(row), 'artwork': native_artwork(row.get('id'))}
                  for text, row in zip(self.list.values, self.rows)], fields=fields, note=self.note.get(),
            category=self.category, categories=self.categories(), suggested=self.suggested,
            shown_count=len(self.rows), total_count=self.total, page_offset=self.browse_offset,
            scope_source=next((row.get('lookup_context', {}).get('source_label', '') for row in self.rows), '') if self.category == '随身' else '',
            suggestions=[{'text': row['name']+' · '+row['type_label'], 'token': binding_token(row),
                          'artwork': native_artwork(row['id'])} for row in self.search_suggestions],
            search_error=self.search_error,
            artwork=native_artwork(self.identity), entry_id=self.identity or '',
            entry_name=entry.get('name') or (self.rendered or {}).get('name', ''),
            entry_hint=entry.get('display_hint', ''),
            entry_type=entry.get('type_label', ''), description=description, introduction=introduction,
            reference_version=self.owner.manager.session.catalog.data['version'],
            related=[{'text': row['name'], 'token': binding_token(row)} for row in self.related_rows()],
            numeric_sections=sections, result_prose=prose,
            primary_values=primary_values, primary_note=primary_note,
            reading_notes=reading_notes, recipes=self.recipe_rows(),
            origin_brief=getattr(self, 'origin_brief', '参考示例 / 手填条件'),
            calculating=self.calculating, parameter_error=self.parameter_error,
            operation_receipt=self.operation_receipt,
            result=self.text.text, status=self.origin.text, dirty=self.has_draft(),
            needs_calculation=self.dirty or bool((self.rendered or {}).get('missing_inputs')),
            can_save=bool(self.identity and self.calculated is not None and not self.dirty and self.rendered and not self.calculating and not self.parameter_error and not (self.context or {}).get('food_reference')),
            favorite=bool(self.identity and self.identity in self.favorite_ids),
            has_saved_plan=bool(self.saved_plan), has_pin=bool(self.owner.pinned),
            can_more=self.suggested or self.browse_offset+len(self.rows) < self.total,
            can_previous=not self.suggested and self.browse_offset > 0, undo=bool(self.undo_state),
            can_latest=bool(self.identity and self.inputs and self.owner.manager.session.snapshot().get('data')),
            sources=self.rendered.get('provenance', {}).get('links', []) if self.rendered else [],
            sources_token=self.source_token())
        self.focus_result = False
        self.focus_suggestions = False
        self.focus_listing = False
        self.owner.manager.native_ui.report_drafts()

    def open_first_result(self, _=None):
        if self.pending:
            self.search()
        if self.rows:
            self.list.selection_set(0)
            self.select()
        elif self.search_suggestions:
            self.search_error = '没有完全匹配，请选择一个近似条目。'
            self.focus_suggestions = True
            self.emit()
        else:
            self.search_error = '没有匹配条目，可清空搜索或切换分类。'
            self.emit()
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
