"""In-play task controllers using the same public data and calculators as the panel."""
from __future__ import annotations

import copy
import json
import re
from decimal import Decimal, InvalidOperation

from .native_host import binding_token
from .values_investment import family


BOOL = [('', '未确认'), ('false', '否'), ('true', '是')]
FLAGS = [('0', '否'), ('1', '是')]
CURSE = [('unknown', '未确认'), ('0', '无诅咒'), ('1', '有诅咒')]
ORIGIN_KEYS = ('kind', 'mode', 'slot', 'snapshot_at', 'fields', 'references', 'mixed_snapshots', 'context_token', 'state_revision')


def integer(value, label, optional=False):
    if optional and value == '':
        return None
    if not isinstance(value, str) or not re.fullmatch(r'[+-]?\d{1,11}', value.strip()):
        raise ValueError(label + '需要完整整数；原始输入仍保留')
    return int(value)


def row_count(raw, key):
    value = integer(raw.get(key, '0'), '工作区行数')
    if not 0 <= value <= {'targets': 64, 'resources': 256, 'paths': 64}[key]:
        raise ValueError('工作区行数超出可用范围；原始输入仍保留')
    return value


def boolean(value):
    if value not in ('', 'true', 'false'):
        raise ValueError('请选择是、否或未确认；原始输入仍保留')
    return None if not value else value == 'true'


def field(key, label, value='', choices=None, section='条件'):
    return {'key': key, 'label': label, 'raw': str(value) if value is not None else '',
            'choices': [{'id': str(k), 'text': v} for k, v in choices] if choices is not None else [], 'section': section}


def backup_version_text(summary):
    if summary.get('empty'): return ''
    version = summary.get('version')
    if type(version) is not int: return '来源版本未知，请核对游戏版本。'
    # SPD 4.0.2 GamesInProgress rejects versions before v3_1_1 (850).
    return '版本码 '+str(version)+(' · 当前参考游戏无法继续此旧档，需对应旧版游戏。' if version < 850 else '')


def comparison_summary(result, strength_origin='独立假设'):
    """Select decision metrics; reuse every calculated outcome without new arithmetic."""
    choices, params = result['choices'], result['params']
    kind = result['family']
    notes = []
    branch_labels = []
    state_names = {'infusion': {'1': '注魔保留', '0': '注魔消失'},
                   'curse': {'1': '诅咒保留', '0': '解咒', 'unknown': '诅咒未确认'},
                   'hardened': {'1': '硬化保留', '0': '无硬化', 'unknown': '硬化未确认'}}
    for side, choice in zip(('a', 'b'), choices):
        augment = {'SPEED': '速度', 'DAMAGE': '伤害', 'EVASION': '闪避', 'DEFENSE': '防御'}.get(params.get('augment_'+side))
        choice['summary_name'] = choice['name']+f" {choice['level']:+d}"+(f' · {augment}' if augment else '')
        if params.get('level_known_'+side) == '0': choice['summary_name'] += '（假设）'
        if choice.get('upgrade_pending'): notes.append(side.upper()+' 注魔未确认，升级待计算')
        branches = choice.get('upgrade_branches', [])
        if len(branches) > 1:
            # Order is shared with every metric's possible outcomes below.
            dimensions = [key for key in state_names if len({branch[key] for branch in branches}) > 1]
            if len({branch['resin'] for branch in branches}) > 1: dimensions.append('resin')
            names = [' · '.join('树脂'+str(branch[key]) if key == 'resin' else state_names[key][branch[key]]
                                for key in dimensions) or f"{branch['level']:+d}" for branch in branches]
            branch_labels.append(side.upper()+' 升级可能：'+' / '.join(names))

    def outcomes(choice, label):
        branches = choice.get('upgrade_branches', [])
        if not branches: return choice['upgraded'].get(label, '待确认')
        cells = [branch['metrics'].get(label, '—') for branch in branches]
        return cells[0] if len(set(cells)) == 1 else ' / '.join(cells)

    rows = result['rows']
    by_label = {row['label']: row for row in rows}
    selected = []
    def add(label, default=None):
        if label not in by_label: return
        values = [choice['current'].get(label, '—') for choice in choices]
        values += [branch['metrics'].get(label, '—') for choice in choices for branch in choice.get('upgrade_branches', [])]
        if default is not None and all(value == default for value in values): return
        selected.append(label)

    add('力量缺口', '0')
    if kind in ('weapon', 'missile'):
        add('最高基础伤害')
        add('攻击耗时' if kind == 'weapon' else '目标投掷耗时')
        if kind == 'weapon':
            add('命中倍率', '1'); add('攻击距离', '1'); add('力量与武器允许偷袭', '是')
        else:
            add('相邻投掷命中倍率'); add('非相邻投掷命中倍率')
            notes.append('投掷按目标位置分别判断；未确认快速投掷就绪。')
    elif kind == 'armor':
        add('常规减伤'); add('护甲闪避惩罚倍率', '1')
        add('护甲强化闪避加值', '0'); add('移动速度倍率', '1')
    else:
        selected = [row['label'] for row in rows[:2]]
    if any(len(choice.get('upgrade_branches', [])) > 1 for choice in choices):
        notes.append('升级分支为可能结果，非保证。')
    result['summary_context'] = ''
    if params.get('character_scene'):
        strengths = [str(choice['character_scene']['strength']['effective']) for choice in choices]
        strength = strengths[0] if len(set(strengths)) == 1 else 'A '+strengths[0]+' / B '+strengths[1]
        result['summary_context'] = '当前角色力量 '+strength+' · 覆盖独立力量'
    elif kind in ('weapon', 'missile', 'armor'):
        result['summary_context'] = '有效力量 '+str(params['strength'])+' · '+strength_origin
    result['summary_rows'] = [{**by_label[label], 'values': [value for choice in choices
        for value in (choice['current'].get(label, '—'), outcomes(choice, label))]} for label in selected]
    def display(value):
        if not re.fullmatch(r'[+-]?\d+\.\d+(?:[eE][+-]?\d+)?', value): return value
        try:
            short = format(float(value), '.3g')
            return ('≈' if Decimal(short) != Decimal(value) else '')+short
        except (ValueError, InvalidOperation):
            return value
    for row in result['summary_rows']:
        row['display_values'] = [' / '.join(display(part) for part in value.split(' / ')) for value in row['values']]
    if any('≈' in value for row in result['summary_rows'] for value in row['display_values']):
        notes.append('≈ 为摘要近似值，展开查看完整精度。')
    result['summary_branches'] = branch_labels
    result['summary_notes'] = notes
    return result


class GameWorkspace:
    def __init__(self, native):
        self.native, self.session, self.host = native, native.session, native.host
        self.page, self.revision = 'inventory', 0
        self.raw = {'equipment': {'strength': '10', 'planning': '1', 'upgrade_budget': '0', 'strength_budget': '0',
                    **{key + '_' + side: value for side in ('a', 'b') for key, value in
                       [('id', ''), ('level', '0'), ('tier', '3'), ('mastery', '0'), ('augment', 'NONE'),
                        ('level_known', '0'), ('curse', 'unknown'), ('infusion', '0'), ('hardened', '0'), ('resin', '0'),
                        ('ring_pair', '0'), ('ring_pair_level', '0'), ('ring_pair_curse', 'unknown')]}},
                    'alchemy': {'energy': '', 'energy_reserve': '0', 'targets': '1', 'resources': '0', 'paths': '0',
                                't0.recipe': 'potion-healing', 't0.quantity': '1'}, 'character': {}}
        self.results, self.calculated, self.saved, self.sources, self.undo = {}, {}, {}, {}, {}
        self.dirty, self.selected, self.rows, self.inventory_binding = set(), {}, {}, None
        self.revealed = {}
        self.inventory_reveal_generation = 0
        self.selected_tokens = {}
        self.client_revisions = {}
        self.focus_result = None
        self.map_catalog, self.map_result, self.backup_catalog, self.backup_preview = None, None, None, None
        self.map_binding, self.map_generation = None, 0
        self.map_items_page, self.map_items_identity = 0, None
        self.map_publication_pending = False
        self.structured_results = {}
        self.legacy_alchemy = None
        self.confirmation = None
        self.notices = {}
        self.notice_briefs = {}
        self.names = {row['id']: row['name'] for row in self.session.catalog.entries}
        from .alchemy_flow import family_list, resource_catalog
        self.recipes = family_list(self.session.catalog)
        self.resources = resource_catalog(self.session.catalog)
        from .character_scene import empty_scene
        self.load_character(empty_scene(), dirty=False)

    def drafts(self):
        return {page: {'values': copy.deepcopy(self.raw[page]), 'source': copy.deepcopy(self.sources.get(page, {}))}
                for page in self.dirty}

    def restore_draft(self, draft):
        if not isinstance(draft, dict) or set(draft) - set(self.raw):
            raise ValueError('游戏工作区草稿格式不兼容；原件保留')
        captured = {}
        for page, item in draft.items():
            if not isinstance(item, dict) or set(item) != {'values', 'source'} or not isinstance(item['source'], dict):
                raise ValueError('游戏工作区草稿不完整；原件保留')
            captured[page] = self.checked_raw(item['values'])
        for page, values in captured.items():
            self.raw[page] = values
            self.sources[page] = copy.deepcopy(draft[page]['source'])
            self.saved.pop(page, None); self.undo.pop(page, None)
            self.structured_results.pop(page, None)
            self.results.pop(page, None); self.calculated.pop(page, None); self.dirty.add(page)
        self.emit()

    @staticmethod
    def checked_raw(raw):
        if not isinstance(raw, dict) or len(raw) > 12000 or any(not isinstance(k, str) or len(k) > 120
                or not isinstance(v, str) or len(v) > {'context': 12000, 'legacy': 200000}.get(k, 1200) for k, v in raw.items()):
            raise ValueError('工作区输入过大或格式不兼容；原始输入仍保留')
        return copy.deepcopy(raw)

    def edit(self, page, values):
        if page not in self.raw:
            return
        values = self.checked_raw(values)
        if values == self.raw[page]:
            return
        old = self.raw[page]
        if values == self.display_raw(page):
            self.raw[page] = values
            return  # Displaying an existing fallback is not a manual edit.
        if page not in self.dirty:
            self.undo[page] = (copy.deepcopy(old), copy.deepcopy(self.sources.get(page, {})))
        if page == 'alchemy':
            for key in list(values):
                if values[key] != old.get(key):
                    if key.startswith('r') and '.' in key:
                        values[key.split('.')[0]+'.origin'] = 'manual'
                    if key == 'energy':
                        values['energy_origin'] = 'manual'
        self.raw[page] = values; self.dirty.add(page)
        self.notices.pop(page, None)
        if {k: v for k, v in values.items() if k not in ('name', 'note')} != {k: v for k, v in old.items() if k not in ('name', 'note')}:
            self.results.pop(page, None); self.calculated.pop(page, None)
            self.mark_manual_source(page, old, values)
        self.native.report_drafts()

    def display_raw(self, page):
        old = self.raw[page]
        visible = copy.deepcopy(old)
        try:
            specs = [] if old.get('legacy') else (self.equipment_fields() if page == 'equipment' else self.alchemy_fields() if page == 'alchemy' else self.character_fields())
            for spec in specs:
                visible.setdefault(spec['key'], spec['raw'])
            visible.setdefault('name', ''); visible.setdefault('note', '')
        except (ValueError, KeyError):
            pass  # Invalid partial structure must still remain editable as raw text.
        return visible

    def mark_manual_source(self, page, old, values):
        source = self.sources.get(page)
        if not source:
            return
        changed = {key for key in old.keys() | values.keys() if old.get(key) != values.get(key)} - {'name', 'note'}
        fields = source.get('fields', {})
        for key in changed:
            canonical_key = self.origin_key(page, key)
            if canonical_key in fields:
                fields[canonical_key] = '手填 · 固定假设'
        references = source.get('references')
        if references and page == 'equipment':
            for side in ('a', 'b'):
                if 'id_'+side in changed:
                    identity = values.get('id_'+side, '')
                    references[side] = {'id': identity, 'name': self.names.get(identity, identity), 'effect_id': None, 'user_note': None}
        if changed:
            source['label'] = source.get('label', '固定来源') + ' · 已编辑的条件为手填假设。' if '已编辑的条件为手填假设。' not in source.get('label', '') else source['label']

    @staticmethod
    def origin_key(page, key):
        return ('rings' if key.startswith('ring') else key) if page == 'character' else (
            'resources' if re.match(r'r\d+\.', key) or key == 'resources' else
            'targets' if re.match(r't\d+\.', key) or key == 'targets' else
            'chains' if re.match(r'c\d+\.', key) or key == 'paths' else key) if page == 'alchemy' else (
            'character_scene' if key == 'context.scene_enabled' else 'scene_ring_slot' if key == 'context.scene_ring_slot' else
            'target_context' if key.startswith('context.target') else key.removeprefix('context.'))

    @staticmethod
    def captured_source(snap):
        from .decisions import source
        return {**source(snap), 'context_token': binding_token([
            snap['settings'].get('save_root'), snap['settings']['mode'], snap.get('active_slot'),
            snap.get('snapshot_content') or [snap.get('started'), snap.get('revision')]]),
            'state_revision': snap.get('revision')}

    def source_status(self, page, snap=None):
        """Describe the task's fixed conditions independently of the live page header."""
        from .native_workspace import plan_updated_text
        snap = self.session.snapshot() if snap is None else snap
        origin = self.sources.get(page, {})
        if not origin:
            return {'brief': '手填条件 · 未绑定游戏', 'detail': '按明确手填假设计算，不代表当前实战状态。', 'stale': False}
        captured = self.captured_source(snap)
        unbound = origin.get('mode') in ('save', 'manual') and (not origin.get('context_token') or
            origin.get('mode') == 'manual' and 'state_revision' not in origin)
        old = bool(origin.get('mode') in ('save', 'manual') and (snap.get('error') or not snap.get('data') or
            origin['mode'] != captured['mode'] or origin.get('slot') != captured['slot'] or
            origin.get('snapshot_at') != captured['snapshot_at'] or
            origin.get('context_token') != captured['context_token'] or
            origin.get('mode') == 'save' and snap.get('stale') or
            origin.get('mode') == 'manual' and origin.get('state_revision', snap.get('revision')) != snap.get('revision')))
        old = old or bool(origin.get('mixed_snapshots')) or bool(unbound)
        prefix = '旧参考' if old else '固定方案' if page in self.saved else '固定参考'
        parts = [prefix]
        if origin.get('mode') == 'save':
            parts.append('槽位 '+str(origin.get('slot') or '?'))
            stamp = origin.get('snapshot_at')
            parts.append(plan_updated_text(stamp)+' 保存' if type(stamp) in (int, float) else '保存时间未记录')
        elif origin.get('mode') == 'manual':
            parts.append('来自手填局势')
        else:
            parts.append('独立条件')
        if any(str(value).startswith('手填') for value in origin.get('fields', {}).values()):
            parts.append('含手填假设')
        if origin.get('mixed_snapshots'):
            parts.append('含不同保存条件；逐项核对')
        if unbound:
            parts.append('来源连接未确认')
        detail = origin.get('label', '固定条件')+'\n'+('当前局势或连接已变化；原条件保留，请核对后主动重新带入。' if old else '条件固定，后续游戏变化不会覆盖输入。')
        return {'brief': ' · '.join(parts), 'detail': detail, 'stale': old}

    @staticmethod
    def captured_field_label(captured, label):
        from .native_workspace import plan_updated_text
        if captured.get('mode') == 'save':
            stamp = captured.get('snapshot_at')
            return label+' · 槽位 '+str(captured.get('slot') or '?')+' · '+(plan_updated_text(stamp)+' 保存' if type(stamp) in (int,float) else '保存时间未记录')
        return label+' · 来自手填局势'

    def equipment_source(self, captured, fields, label):
        prior = self.sources.get('equipment', {})
        retained = {key:value for key,value in prior.get('fields', {}).items() if key not in fields}
        remaining_snapshot = any(not str(value).startswith(('手填', '未确认')) for value in retained.values())
        different = any(prior.get(key) != captured.get(key) for key in ('mode','slot','snapshot_at','context_token'))
        return {**captured, **({'references': copy.deepcopy(prior['references'])} if prior.get('references') else {}),
                'label': label, 'fields': {**retained, **fields},
                'mixed_snapshots': bool(remaining_snapshot and (different or prior.get('mixed_snapshots')))}

    def equipment_choices(self):
        from .values_investment import FAMILIES
        # Prefix families also include armor glyphs and other reference pages.
        # Only actual equipment classes occur directly in these namespaces.
        return [(row['id'], row['name']) for row in self.session.catalog.entries
                if family(row['id']) and '$' not in row['id'] and not row['id'].endswith('.ability')
                and (family(row['id']) == 'missile' or '.' not in row['id'][len(FAMILIES[family(row['id'])]):])]

    def equipment_fields(self):
        raw = self.raw['equipment']; result = []
        equipment = self.equipment_choices()
        for side in ('a', 'b'):
            result.append(field('id_'+side, '装备 '+side.upper(), raw.get('id_'+side), [('', '请选择已知装备 / 明确假设'), *equipment], '选择比较对象'))
        for side in ('a', 'b'):
            group = '装备 '+side.upper(); kind = family(raw.get('id_'+side))
            result.append(field('level_'+side, '显示等级（未知时只是手填假设）', raw.get('level_'+side, ''), section=group))
            if kind in ('missile', 'wand', 'ring'):
                result.append(field('level_known_'+side, '该等级已经鉴定', raw.get('level_known_'+side, '0'), FLAGS, group))
            if kind in ('weapon', 'missile', 'armor'):
                result += [field('tier_'+side, '原护甲阶数（职业护甲）', raw.get('tier_'+side, '3'), section=group)] if kind == 'armor' else []
                result += [field('mastery_'+side, '已使用精通药剂', raw.get('mastery_'+side, '0'), [('unknown', '未确认'), *FLAGS], group),
                           field('augment_'+side, '强化', raw.get('augment_'+side, 'NONE'),
                                 [('unknown', '未确认'), ('NONE', '无强化'), ('EVASION', '闪避'), ('DEFENSE', '防御')] if kind == 'armor' else [('unknown', '未确认'), ('NONE', '无强化'), ('SPEED', '速度'), ('DAMAGE', '伤害')], group),
                           field('hardened_'+side, '已硬化', raw.get('hardened_'+side, '0'), [('unknown', '未确认'), *FLAGS], group)]
            if kind:
                result.append(field('curse_'+side, '诅咒条件', raw.get('curse_'+side, 'unknown'), CURSE, group))
            if kind in ('weapon', 'missile', 'armor', 'wand'):
                result.append(field('infusion_'+side, '注魔假设', raw.get('infusion_'+side, '0'), [('unknown', '未确认'), ('0', '无注魔'), ('1', '有注魔')], group))
            if kind == 'wand':
                result.append(field('resin_'+side, '树脂层数', raw.get('resin_'+side, '0'), section=group))
            if kind == 'ring':
                result += [field('ring_pair_'+side, '同时装备另一枚同类戒指', raw.get('ring_pair_'+side, '0'), FLAGS, group),
                           field('ring_pair_level_'+side, '另一枚同类戒指等级', raw.get('ring_pair_level_'+side, '0'), section=group),
                           field('ring_pair_curse_'+side, '另一枚同类戒指诅咒', raw.get('ring_pair_curse_'+side, 'unknown'), CURSE, group)]
            if kind in ('wand', 'ring'):
                from .values import INPUTS
                identity = raw.get('id_'+side)
                detail = self.session.values.detail(identity)
                for spec in detail['inputs']:
                    if spec['key'] in ('hp', 'max_hp', 'hero_level', 'depth', 'target_hp', 'target_max_hp', 'enemy_exp', 'minor', 'major', 'charges'):
                        key = spec['key']+'_'+side
                        result.append(field(key, INPUTS[spec['key']][0]+'（手填条件）', raw.get(key, str(spec['value'])), section=group))
        context = self.equipment_context()
        shared = bool(context.get('character_scene') and raw.get('context.scene_enabled', '1') != '0')
        result += [field('strength', '独立力量（停用角色条件后生效）' if shared else '有效力量', raw.get('strength', ''), section='共同条件'),
                   field('planning', '启用升级预算', raw.get('planning', '0'), FLAGS, '共同条件')]
        kind = family(raw.get('id_a'))
        if raw.get('planning') == '1':
            result += [field('upgrade_budget', '升级卷轴预算', raw.get('upgrade_budget', '0'), section='共同条件'),
                       field('strength_budget', '另拟投入力量药剂（不重复已计入的力量）', raw.get('strength_budget', '0'), section='共同条件'),
                       field('context.investment_mode', '预算用法', raw.get('context.investment_mode', context.get('investment_mode', 'all' if kind in ('wand', 'ring') else 'min_strength')),
                             [('all', '列出预算内每种投入')] if kind in ('wand', 'ring') else [('min_strength', '优先满足力量门槛'), ('all', '列出预算内每种投入')], '共同条件')]
        if context.get('character_scene'):
            result.append(field('context.scene_enabled', '使用已带入的固定角色条件', raw.get('context.scene_enabled', '1'), FLAGS, '共享角色条件'))
            if kind == 'ring':
                result.append(field('context.scene_ring_slot', '备选戒指替换槽位', raw.get('context.scene_ring_slot', str(context.get('scene_ring_slot', 0))), [('0', '戒指槽位 1'), ('1', '戒指槽位 2')], '共享角色条件'))
        if kind == 'weapon':
            model = raw.get('context.combat_model', context.get('combat_model', ''))
            result.append(field('context.combat_model', '启用普通持械近战模型', model, [('', '只比较装备基础指标'), ('ordinary-v1', '包含所列角色戒指与普通近战条件')], '战斗条件'))
            if model:
                target = context.get('target_context', {})
                enabled = raw.get('context.target_enabled', '1' if target else '0')
                result.append(field('context.target_enabled', '使用手填目标条件', enabled, FLAGS, '战斗条件'))
                if enabled == '1':
                    for key, label in [('name', '目标场景名称'), ('base_accuracy', '英雄基础命中（未乘武器 / 戒指）'), ('evasion', '目标闪避'), ('dr_min', '目标减伤下限'), ('dr_max', '目标减伤上限')]:
                        result.append(field('context.target.'+key, label+'（未确认请留空）', raw.get('context.target.'+key, target.get(key, '')), section='战斗条件'))
        return result

    def equipment_context(self):
        context = json.loads(self.raw['equipment']['context']) if self.raw['equipment'].get('context') else {}
        if not isinstance(context, dict) or set(context) - {'character_scene', 'scene_ring_slot', 'combat_model', 'target_context', 'investment_mode'}:
            raise ValueError('所保存装备共享条件格式不兼容；原件保留')
        return context

    def equipment_args(self):
        raw = self.raw['equipment']; args, visible = {}, {}
        for spec in self.equipment_fields():
            key = spec['key']; value = raw.get(key, spec['raw'])
            (visible if key.startswith('context.') else args)[key] = value.strip()
        context = self.equipment_context()
        if args.get('planning') != '1':
            args.pop('upgrade_budget', None); args.pop('strength_budget', None)
            context.pop('investment_mode', None)
        else: context['investment_mode'] = visible['context.investment_mode']
        if visible.get('context.scene_enabled') == '0':
            context.pop('character_scene', None); context.pop('scene_ring_slot', None)
        elif 'character_scene' in context:
            if family(args.get('id_a')) == 'ring': context['scene_ring_slot'] = integer(visible.get('context.scene_ring_slot', '0'), '替换戒指槽位')
            else: context.pop('scene_ring_slot', None)
        if family(args.get('id_a')) == 'weapon':
            if visible.get('context.combat_model'):
                context['combat_model'] = visible['context.combat_model']
                if visible.get('context.target_enabled') == '1':
                    context['target_context'] = {'format': 1, 'name': visible['context.target.name'], **{key: integer(visible['context.target.'+key], '目标条件', True) for key in ('base_accuracy', 'evasion', 'dr_min', 'dr_max')}}
                else: context.pop('target_context', None)
            else: context.pop('combat_model', None); context.pop('target_context', None)
        else: context.pop('combat_model', None); context.pop('target_context', None)
        args.update(context)
        return args

    def recipe(self, identity):
        return next((row for row in self.recipes if row['id'] == identity), None)

    def recipe_choices(self):
        return [(row['id'], row.get('name') or self.names.get(row.get('output'), row['id'])+' · '+row.get('group', '')) for row in self.recipes]

    def add_recipe_target(self, identity):
        recipe = self.recipe(identity)
        if not recipe:
            raise ValueError('配方已不可用；当前炼金草稿仍保留')
        previous = self.raw['alchemy']
        if previous.get('legacy'):
            raise ValueError('请先在炼金中转换旧方案，再加入目标；旧草稿仍保留')
        count = row_count(previous, 'targets')
        if count >= 64:
            raise ValueError('炼金目标已达到上限；当前草稿仍保留')
        self.undo['alchemy'] = (copy.deepcopy(previous), copy.deepcopy(self.sources.get('alchemy', {})))
        updated = {**previous, 'targets': str(count + 1),
                   f't{count}.recipe': identity, f't{count}.quantity': '1'}
        self.edit('alchemy', updated)
        self.structured_results.pop('alchemy', None)
        self.notice_briefs['alchemy'] = '已加入目标 ' + str(count + 1) + ' · ' + dict(self.recipe_choices())[identity]
        self.page = 'alchemy'
        self.hide_inventory_reveals()
        self.emit('alchemy')
        self.host.command('show', surface='alchemy')

    def choice_fields(self, raw, prefix, recipe, group):
        result = []
        for spec in (self.recipe(recipe) or {}).get('choices', []):
            key = spec['key']; kind = spec['type']
            options = [(identity, self.names.get(identity, identity)) for identity in spec['allowed']]
            if kind in ('instance', 'instance-list'):
                options = [(f'r{i}', self.names.get(raw.get(f'r{i}.id'), '未选身份')+f' · 库存 {i+1}')
                           for i in range(row_count(raw, 'resources'))
                           if raw.get(f'r{i}.id') in self.resources.get(spec['group'], [])]
            elif kind == 'selection':
                options = [(str(i), '已显示的第 '+str(i+1)+' 项') for i in range(4)]
            elif kind == 'level':
                options = [(str(i), '+'+str(i)) for i in range(1, 4)]
            parts = 3 if kind == 'three-items' else 1
            for i in range(parts):
                name = prefix+'.'+key+('.'+str(i) if parts == 3 else '')
                label = {'source_key': '原始实例', 'source_keys': '选择原始实例（可多选）',
                         'selection': '已显示的触媒选项', 'target_level': '目标等级'}.get(key, '配方材料选择')
                result.append({**field(name, label+(f' {i+1}' if parts == 3 else ''), raw.get(name, ''), [('', '请选择明确条件'), *options], group), 'multiple': kind == 'instance-list'})
        return result

    def alchemy_fields(self):
        raw = self.raw['alchemy']; result = []
        for i in range(row_count(raw, 'targets')):
            prefix = f't{i}'; group = '产出目标 '+str(i+1)+' · 按顺序共用库存'
            result += [field(prefix+'.recipe', '配方', raw.get(prefix+'.recipe', ''), self.recipe_choices(), group),
                       field(prefix+'.quantity', '本次制作并保留的产出件数', raw.get(prefix+'.quantity', '1'), section=group)]
            result += self.choice_fields(raw, prefix, raw.get(prefix+'.recipe'), group)
        result += [field('energy', '本次可用总能量（未知请明确填写）', raw.get('energy', ''), section='共享预算'),
                   field('energy_reserve', '最低保留能量', raw.get('energy_reserve', '0'), section='共享预算')]
        catalog = {row['id']: row for row in self.resources['items']}
        options = [('', '请选择明确物品身份'), *[(k, v['name']) for k, v in catalog.items()]]
        enums = {'cursed': BOOL, 'is_upgradable': BOOL, 'cooked': [('', '未确认'), ('raw', '未煮'), ('cooked', '已煮'), ('unknown', '生熟未确认')],
                 'hero_class': [('', '未确认'), *[(v, k) for k, v in [('战士', 'WARRIOR'), ('法师', 'MAGE'), ('盗贼', 'ROGUE'), ('女猎', 'HUNTRESS'), ('决斗家', 'DUELIST'), ('牧师', 'CLERIC')]]] ,
                 'catalyst_stage': [('', '未确认'), ('unrolled', '未生成选项'), ('awaiting_choice', '已付费待选择')]}
        labels = {'cursed': '有诅咒', 'is_upgradable': '可升级', 'base_level': '公开基础等级', 'public_level': '公开显示等级',
                  'level': '已知等级', 'resin_bonus': '树脂加成', 'hero_class': '职业', 'wand_preservation': '法杖保存天赋点数',
                  'tier': '阶数', 'default_quantity': '原始生成堆大小', 'durability': '精确耐久（只接受手填假设）',
                  'cooked': '生熟', 'potion_id': '已经烹煮的药剂身份', 'catalyst_stage': '触媒阶段'}
        for i in range(row_count(raw, 'resources')):
            prefix = f'r{i}'; group = '独立库存 '+str(i+1)+' · '+('已知快照' if raw.get(prefix+'.origin') == 'known' else '明确手填假设')
            result += [field(prefix+'.id', '物品 / 原始堆身份', raw.get(prefix+'.id', ''), options, group),
                       field(prefix+'.quantity', '现有数量', raw.get(prefix+'.quantity', ''), section=group),
                       field(prefix+'.reserve', '最低保留数量', raw.get(prefix+'.reserve', '0'), section=group)]
            for key in catalog.get(raw.get(prefix+'.id'), {}).get('state_fields', []):
                if key == 'rolled_choices':
                    for n in range(4):
                        name = prefix+'.state.rolled_choices.'+str(n)
                        result.append(field(name, '触媒已经显示的选项 '+str(n+1), raw.get(name, ''), [('', '未确认'), *[(k, self.names.get(k, k)) for k in self.resources['trinkets']], ('items.trinkets.trinketcatalyst$randomtrinket', '随机身份（未确定）')], group))
                else:
                    choices = enums.get(key)
                    if key == 'potion_id':
                        choices = [('', '未确认'), *[(k, self.names.get(k, k)) for k in self.resources['potions'] if '.exotic.' not in k]]
                    name = prefix+'.state.'+key
                    result.append(field(name, labels.get(key, key)+'（空白表示未确认）', raw.get(name, ''), choices, group))
        for i in range(row_count(raw, 'paths')):
            prefix = f'c{i}'; group = '明确指定前置生产路径 '+str(i+1)
            result += [field(prefix+'.id', '需要制作的材料', raw.get(prefix+'.id', ''), options, group),
                       field(prefix+'.recipe', '前置配方', raw.get(prefix+'.recipe', ''), self.recipe_choices(), group)]
            result += self.choice_fields(raw, prefix, raw.get(prefix+'.recipe'), group)
        return result

    def alchemy_choices(self, raw, prefix):
        result = {}
        for spec in (self.recipe(raw.get(prefix+'.recipe')) or {}).get('choices', []):
            key, kind = spec['key'], spec['type']; value = raw.get(prefix+'.'+key, '')
            if kind == 'three-items':
                values = [raw.get(prefix+'.'+key+'.'+str(n), '') for n in range(3)]
                if any(values): result[key] = values
            elif value:
                if kind in ('instance', 'instance-list'):
                    keys = value.split('|') if kind == 'instance-list' else [value]
                    keys = [raw.get(v+'.key', v) for v in keys]
                    result[key] = keys if kind == 'instance-list' else keys[0]
                else: result[key] = integer(value, '配方选择') if kind in ('selection', 'level') else value
        return result

    def alchemy_args(self):
        raw = self.raw['alchemy']; resources = []; specs = self.alchemy_fields()
        labels = {spec['key']: spec['label'] for spec in specs}
        for i in range(row_count(raw, 'resources')):
            prefix = f'r{i}'; state = {}
            for key in raw:
                if key not in labels or not key.startswith(prefix+'.state.') or not raw.get(key, ''): continue
                name = key[len(prefix+'.state.'):]; value = raw[key]
                if name.startswith('rolled_choices.'):
                    state.setdefault('rolled_choices', [None]*4)[int(name[-1])] = value
                elif name in ('cursed', 'is_upgradable'): state[name] = boolean(value)
                elif name in ('cooked', 'potion_id', 'hero_class', 'catalyst_stage'): state[name] = value
                elif name == 'durability': state[name] = float(value)
                else: state[name] = integer(value, labels.get(key, '库存状态'))
            resources.append({'key': raw.get(prefix+'.key', prefix), 'id': raw.get(prefix+'.id', ''), 'quantity': integer(raw.get(prefix+'.quantity', ''), '库存数量'),
                'reserve': integer(raw.get(prefix+'.reserve', '0'), '最低保留数量'), 'origin': raw.get(prefix+'.origin', 'manual'), 'state': state})
        targets = [{'key': raw.get(f't{i}.key', f't{i}'), 'recipe': raw.get(f't{i}.recipe', ''), 'quantity': integer(raw.get(f't{i}.quantity', ''), '目标产出'),
                    'choices': self.alchemy_choices(raw, f't{i}')} for i in range(row_count(raw, 'targets'))]
        chains = {raw.get(f'c{i}.id', ''): {'recipe': raw.get(f'c{i}.recipe', ''), 'choices': self.alchemy_choices(raw, f'c{i}')}
                  for i in range(row_count(raw, 'paths'))}
        if len(chains) != row_count(raw, 'paths'):
            raise ValueError('同一材料只能指定一条前置路径；请移除重复路径，原始输入仍保留')
        return {'format': 2, 'recipe_version': '4.0.2', 'energy': integer(raw.get('energy', ''), '可用能量'),
                'energy_reserve': integer(raw.get('energy_reserve', '0'), '最低保留能量'), 'energy_origin': raw.get('energy_origin', 'manual'),
                'reference_version': integer(raw['reference_version'], '参考版本') if raw.get('reference_version') else None,
                'targets': targets, 'resources': resources, 'chains': chains}

    def load_character(self, scene, dirty=True):
        values = {key: '' if value is None else str(value).lower() if type(value) is bool else str(value)
                  for key, value in scene.items() if key not in ('rings', 'format')}
        values['format'] = str(scene['format'])
        for i in range(2):
            ring = scene['rings'][i] if i < len(scene['rings']) else {'identity': 'none', 'level': None, 'cursed': None}
            for key, value in ring.items():
                values[f'ring{i}.{key}'] = '' if value is None else str(value).lower() if type(value) is bool else str(value)
        self.raw['character'] = values
        if dirty: self.dirty.add('character')

    def character_fields(self):
        raw = self.raw['character']; rows = []
        labels = {'base_strength': '基础力量', 'strongman': '力大无穷点数', 'adrenaline': '激素涌动力量',
                  'magic_immune': '魔法免疫', 'spirit_form': '精神形态', 'spirit_ring': '精神形态戒指',
                  'spirit_level': '精神形态戒指等级', 'spirit_cursed': '精神形态戒指有诅咒', 'enhanced_rings': '戒指强化状态'}
        rings = [('', '身份未确认'), ('none', '无戒指'), *[(k, v) for k, v in self.names.items() if family(k) == 'ring' and '$' not in k]]
        for key, label in labels.items():
            if key == 'enhanced_rings' and raw.get('format') != '2': continue
            choices = rings if key == 'spirit_ring' else BOOL if key in ('magic_immune', 'spirit_form', 'spirit_cursed', 'enhanced_rings') else None
            rows.append(field(key, label+'（空白表示未确认）', raw.get(key, ''), choices, '角色力量条件'))
        for i in range(2):
            rows += [field(f'ring{i}.identity', '戒指身份', raw.get(f'ring{i}.identity', ''), rings, '已装备戒指 '+str(i+1)),
                     field(f'ring{i}.level', '等级', raw.get(f'ring{i}.level', ''), section='已装备戒指 '+str(i+1)),
                     field(f'ring{i}.cursed', '有诅咒', raw.get(f'ring{i}.cursed', ''), BOOL, '已装备戒指 '+str(i+1))]
        return rows

    def character_args(self):
        raw = self.raw['character']; result = {'format': integer(raw.get('format', '1'), '角色条件版本'), 'rings': []}
        for spec in self.character_fields():
            key, value = spec['key'], raw.get(spec['key'], '')
            if key.startswith('ring'): continue
            result[key] = (value or None) if key == 'spirit_ring' else None if not value else boolean(value) if spec['choices'] else integer(value, spec['label'])
        for i in range(2):
            identity = raw.get(f'ring{i}.identity', '')
            if identity == 'none': continue
            curse = raw.get(f'ring{i}.cursed', '')
            result['rings'].append({'identity': identity or None, 'level': integer(raw.get(f'ring{i}.level', ''), '戒指等级', True), 'cursed': boolean(curse)})
        return result

    def calculate(self, page):
        from .knowledge import canonical_plan
        args = self.equipment_args() if page == 'equipment' else self.alchemy_args() if page == 'alchemy' else self.character_args()
        canonical, result = canonical_plan(self.session, page, None, args)
        if page == 'equipment' and self.sources.get(page, {}).get('references'):
            references = self.sources[page]['references']
            for side in ('a', 'b'):
                identity = canonical['id_'+side]
                if references.get(side, {}).get('id') != identity:
                    references[side] = {'id': identity, 'name': self.names.get(identity, identity),
                                        'effect_id': None, 'user_note': None}
        self.calculated[page] = canonical
        self.structured_results[page] = copy.deepcopy(result)
        self.results[page] = self.result_text(page, result)
        self.focus_result = page

    def result_text(self, page, result):
        if page == 'equipment':
            lines = [f"A · {result['choices'][0]['name']}    /    B · {result['choices'][1]['name']}"]
            references = self.sources.get(page, {}).get('references', {})
            if references:
                lines.append('公开装备固定参考（捕获时名称；效果身份仅用于辨认，未计额外收益；数值以所填支持条件为准）')
                for side in ('a', 'b'):
                    reference = references[side]
                    lines.append(side.upper()+' · '+reference['name']+
                        ('；公开效果：'+self.names.get(reference['effect_id'], reference['effect_id']) if reference.get('effect_id') else ''))
                    note = reference.get('user_note')
                    if note: lines.append('用户记录（非游戏事实）：'+note['title']+'\n'+note['body'])
            planning = result.get('planning')
            if planning:
                pending = ['AB'[index] for index, choice in enumerate(planning['choices']) if choice.get('upgrade_pending')]
                lines.append('预算待确认：'+ '、'.join(pending)+' 注魔假设未确认，升级预算待计算。' if pending else '预算按所列条件计算；随机升级分支需分别核对。')
                lines.append(f"预算 {planning['upgrade_budget']} 卷 / {planning['strength_budget']} 瓶力量药剂；A、B 分别使用同一预算，不能同时花费。")
                lines.append('    '.join('AB'[index]+f" 投入 {choice.get('spent_upgrades', '?')} 卷 · 余 {choice.get('remaining_upgrades', '?')} 卷"
                    for index, choice in enumerate(planning['choices'])))
            lines.append('当前 / 升级一次（A / B）')
            for row in result['rows']:
                lines.append(row['label']+'   A '+str(row['values'][0])+' → '+str(row['values'][1])+'    B '+str(row['values'][2])+' → '+str(row['values'][3])+' '+row.get('unit', ''))
            lines.append('条件与投入明细')
            for row in result['rows']:
                if row.get('condition'): lines.append(row['label']+' · '+row['condition'])
            for side, choice in zip(('A', 'B'), result['choices']):
                if len(choice.get('upgrade_branches', [])) > 1:
                    lines.append(side+' · 升级一次的可能结果')
                    for branch in choice['upgrade_branches']:
                        lines.append(f"{branch['level']:+d} · "+branch['condition'])
                        lines += [cell['label']+' '+cell['value']+' '+cell.get('unit', '') for cell in branch['metric_rows']]
            if planning:
                for index, choice in enumerate(planning['choices']):
                    lines.append('AB'[index]+' · '+choice['name']+' · '+choice.get('explanation', ''))
                    for alternative in choice.get('alternatives', []):
                        lines.append(f"投入 {alternative.get('upgrades', alternative.get('spent_upgrades', '?'))} 卷 · 余 {alternative.get('remaining_upgrades', '?')} 卷；力量药剂投入 {alternative.get('spent_strength', '?')} 瓶 · 余 {alternative.get('remaining_strength', '?')} 瓶")
                        branches = alternative.get('upgrade_branches')
                        if not branches:
                            lines += [cell['label']+' '+str(cell['value'])+' '+cell.get('unit', '')+' · '+cell.get('condition', '') for cell in alternative.get('metric_rows', [])]
                        for branch in branches or []:
                            lines.append(branch['condition'])
                            lines += [cell['label']+' '+str(cell['value'])+' '+cell.get('unit', '')+' · '+cell.get('condition', '') for cell in branch['metric_rows']]
                lines.append(planning['notice'])
            lines.append(result['notice'])
            return '\n'.join(lines)
        if page == 'character':
            strength = result['strength']
            text = ('总力量 '+str(strength['effective']) if strength.get('state') == 'known' else '总力量尚未确认：'+'；'.join(strength['missing']))
            components = strength['components']
            text += '\n\n'+' · '.join(label+' '+('未知' if components[key] is None else str(components[key])) for key, label in [('base', '基础'), ('might_rings', '戒指'), ('adrenaline', '激素涌动'), ('strongman', '力大无穷')])
            return text+'\n\n'+result['boundary']
        if result.get('format') != 2:
            return ('旧版固定配方方案 · 原记录保留\n\n'+result['recipe']['name']+f" · 计划 {result['requested_batches']} 批 / 可完成 {result['batches']} 批\n产出 {result['output']['quantity']} 件\n能量消耗 {result['energy']['spent']}，余 {result['energy']['remaining']}\n\n"+
                    '\n'.join(self.names.get(row['id'], row['id'])+f" · 消耗 {row.get('spent', row.get('consumed', '?'))}，余 {row.get('remaining', '?')}" for row in result['materials'])+'\n\n'+'\n'.join(result['warnings']))
        return self.alchemy_result_text(result)

    def alchemy_labels(self, result):
        labels = {**self.names, **{row['id']: row['name'] for row in self.recipes},
                  'energy': '能量', 'item': '库存物品', 'output': '产出', 'steps': '制作步骤',
                  'seed_id': '种子', 'seed_ids': '三个种子槽', 'stone_id': '符石',
                  'potion_id': '药剂', 'scroll_id': '卷轴', 'ingredient_id': '强化材料',
                  'pasty_id': '饼底', 'meat_id': '肉类'}
        for index, row in enumerate(result['materials'], 1):
            labels[row['key']] = f"库存{index} · "+self.names.get(row['id'], '未收录物品')
        for index, row in enumerate(result['targets'], 1):
            labels[row['key']] = f"目标{index} · "+labels.get(row['recipe'], '炼金目标')
        return labels

    @staticmethod
    def alchemy_condition_text(text, labels):
        # Conditions can refer to stock keys or catalog IDs. Translate only
        # complete tokens so e.g. item-1 cannot corrupt item-10 or an item ID.
        pattern = '|'.join(re.escape(key) for key in sorted(labels, key=len, reverse=True))
        return re.sub(r'(?<![\w.$-])(?:'+pattern+r')(?![\w.$-])',
                      lambda match: labels[match.group()], str(text))

    def alchemy_choice_text(self, choice, labels):
        fields = {'source_key': '所选库存', 'source_keys': '所选库存', 'seed_id': '种子', 'seed_ids': '种子槽',
                  'stone_id': '符石', 'potion_id': '药剂', 'scroll_id': '卷轴', 'ingredient_id': '强化材料',
                  'pasty_id': '饼底', 'meat_id': '肉类', 'selection': '四选项序号（从0计）', 'target_level': '目标等级'}
        parts = []
        for key, value in choice.items():
            values = value if isinstance(value, list) else [value]
            parts.append(fields.get(key, '配方条件')+'：'+'、'.join(labels.get(str(v), str(v)) for v in values))
        return '；'.join(parts)

    def alchemy_shortage_text(self, shortage, labels, target):
        lines = []; row = shortage
        while row:
            name = labels.get(row['id'], '所需材料')
            lines.append('缺口 · '+target+'：'+name+f" · 需用 {row['required']} / 可用 {row['available']} / 还缺 {row['missing']}\n"+
                         self.alchemy_condition_text(row['reason'], labels))
            for index, option in enumerate(row.get('options', []), 1):
                selected = self.alchemy_choice_text(option.get('choices', {}), labels)
                lines.append(f"候选{index} · "+labels.get(option['recipe'], '前置配方')+(' · '+selected if selected else ''))
            if row.get('inputs'):
                lines.append('对应材料：'+'、'.join(labels.get(item.get('key'), labels.get(item['id'], '原始物品'))+' ×'+str(item['quantity'])
                    for item in row['inputs']))
            for condition in row.get('pending', []):
                lines.append('待确认 · '+target+'：'+self.alchemy_condition_text(condition, labels))
            row = row.get('dependency')
        return '\n'.join(lines)

    def alchemy_result_summary(self, result):
        labels = self.alchemy_labels(result)
        lines = ['可以制作' if result['complete'] else '预算充足 · 产出未确定' if result['within_budget'] else '暂不能完成']
        if any(row.get('certainty') != 'known' for row in result['outputs']):
            lines.append('随机或条件产出，不能保证指定物品。')
        if result['pending_conditions']:
            lines.append(f"还有 {len(result['pending_conditions'])} 项条件待确认")
        for row in result['targets']:
            lines.append(labels[row['key']]+f" · {row['planned_quantity']} / {row['requested_quantity']} 件")
        energy = result['energy']
        lines.append(f"耗能 {energy['spent']} · 余 {energy['remaining']}"+
                     (f" · 保留 {energy['reserve']}" if energy['reserve'] else ''))
        for row in result['shortages']:
            lines.append(labels.get(row['target'], '当前目标')+'：还缺 '+labels.get(row['id'], '材料')+f" ×{row['missing']}")
        return '\n'.join(lines)

    def alchemy_result_text(self, result, *, details_only=False):
        labels = self.alchemy_labels(result)
        lines = [self.alchemy_result_summary(result)]
        for row in result['targets']:
            lines.append(labels[row['key']]+f" · 计划 {row['planned_quantity']} / 目标 {row['requested_quantity']} 件")
        energy = result['energy']
        lines.append(f"能量：{energy['quantity']} − {energy['spent']} = {energy['remaining']}；最低保留 {energy['reserve']}")
        steps = []
        for index, step in enumerate(result['steps'], 1):
            target = labels.get(step['target'], '当前目标')
            steps.append(f"{index}. "+labels.get(step['recipe'], '制作')+f" · {step.get('batches', '?')} 批 · "+target)
            steps.append('   材料：'+('、'.join(self.names.get(row['id'], '原始物品')+' ×'+str(row['quantity']) for row in step['inputs']) or '无需库存材料'))
            cost = step['energy']; steps.append(f"   能量：{cost['before']} − {cost['spent']} = {cost['after']}")
        if details_only: lines = []
        lines.append('制作顺序（按固定条件模拟）\n'+('\n'.join(steps) if steps else '没有可完成的制作步骤。'))
        for step in result.get('requested_steps', []):
            if step.get('status') != 'pending': continue
            materials = [self.names.get(row['id'], '原始物品')+' ×'+str(row['quantity']) if isinstance(row, dict) else str(row)
                         for row in step.get('requirements', [])]
            cost = step.get('energy_spent')
            lines.append('未完成 · '+labels.get(step['target'], '当前目标')+'\n配方材料：'+('、'.join(materials) or '需确认具体材料')+
                         f"\n目标数量 {step['requested_quantity']} · 所需能量 "+(str(cost) if cost is not None else '待确认'))
        for row in result['outputs']:
            lines.append('产出 · '+labels.get(row.get('target'), '当前目标')+'：'+self.names.get(row.get('id'), '随机或条件产出')+' ×'+
                         (str(row['quantity']) if row.get('quantity') is not None else '待确认')+' · '+
                         {'known': '身份与产量确定', 'random': '随机身份', 'conditional': '条件结果'}.get(row.get('certainty'), '需核对产出边界'))
        for row in result['outcome_boundaries']:
            boundary = row.get('message', row.get('text', row.get('condition', row.get('reason', '此产出有随机或条件边界，不能视为确定库存'))))
            lines.append('产出条件 · '+labels.get(row.get('target'), '当前目标')+'：'+self.alchemy_condition_text(boundary, labels))
        for row in result['shortages']:
            lines.append(self.alchemy_shortage_text(row, labels, labels.get(row['target'], '当前目标')))
        for row in result['pending_conditions']:
            lines.append('待确认 · '+labels.get(row.get('target'), labels.get(row.get('recipe'), '当前目标'))+'：'+self.alchemy_condition_text(row['condition'], labels))
        lines += result['warnings']
        consumed = [self.names.get(row['id'], '原始物品')+f" · 消耗 {row['spent']}，余 {row['remaining']}，保留 {row['reserve']}"
                    for row in result['materials'] if row['spent']]
        lines.append('实际消耗材料\n'+('\n'.join(consumed) if consumed else '未消耗库存材料。'))
        return '\n\n'.join(lines)

    def result_details(self, page):
        if page == 'backups':
            row = next((r for r in self.rows.get(page, []) if r['id'] == self.selected.get(page)), None)
            if row and self.backup_preview:
                return [{'id': 'record_details', 'title': '当前与目标详情', 'expanded': False,
                         'text': self.backup_preview['text']+'\n\n核验 ID '+str(row['entry']['id'])[:12]}]
            return [{'id': 'record_details', 'title': '记录时间与校验信息', 'text': row['text'], 'expanded': False}] if row else []
        result = self.structured_results.get(page, {})
        if page != 'alchemy' or page not in self.calculated or result.get('format') != 2:
            return []
        unused = [row for row in result['materials'] if not row['spent']]
        details = [{'id': 'crafting_steps', 'title': '制作步骤与材料', 'text': self.alchemy_result_text(result, details_only=True), 'expanded': False}]
        if not unused: return details
        labels = self.alchemy_labels(result)
        text = '\n'.join(labels[row['key']]+f" · 未消耗，余 {row['remaining']}，最低保留 {row['reserve']}" for row in unused)
        return details + [{'id': 'unused_inventory', 'title': f'未消耗库存（{len(unused)}项）', 'text': text, 'expanded': False}]

    def inventory(self):
        snap = self.session.snapshot()
        self.inventory_source = self.captured_source(snap)
        from .inventory_inspection import snapshot_token
        with self.session.lock:
            expected = snapshot_token(self.session)
        binding = binding_token([snap.get('started'), snap.get('revision'), snap.get('settings_revision'), expected])
        if binding != self.inventory_binding:
            self.revealed.clear(); self.inventory_binding = binding
        rows = []
        for item in [] if snap.get('error') else (snap.get('data') or {}).get('items', []):
            item = self.revealed.get(item['instance_key'], item)
            curse = ' · 有诅咒' if item.get('cursed') is True else ''
            rows.append({'id': item['instance_key'], 'text': item['name']+f" ×{item['quantity']}"+curse+' · '+item['location'],
                         'token': binding_token([binding, item]), 'item': copy.deepcopy(item), 'expected': expected})
        self.rows['inventory'] = rows
        current = next((r for r in rows if r['id'] == self.selected.get('inventory')), None)
        if self.selected.get('inventory') and (current is None or current['token'] != self.selected_tokens.get('inventory')):
            self.selected.pop('inventory', None); self.selected_tokens.pop('inventory', None)
        return rows

    def sync_map_source(self, snap=None):
        snap = self.session.snapshot() if snap is None else snap
        settings = snap.get('settings', {})
        binding = binding_token([snap.get(key) for key in ('started', 'revision', 'settings_revision', 'active_slot', 'run_id', 'error')]
            + [settings.get(key) for key in ('save_root', 'mode', 'slot')])
        if binding == self.map_binding:
            return self.map_publication_pending
        self.map_binding = binding; self.map_generation += 1
        self.map_publication_pending = True
        self.map_catalog = self.map_result = None
        self.rows['map'] = []
        self.selected.pop('map', None); self.selected_tokens.pop('map', None)
        return True

    def map_item_rows(self):
        """Publish a small page; every saved instance remains reachable."""
        floor = self.map_result
        if not floor:
            return [], ''
        identity = binding_token([self.map_binding, self.map_generation, floor['source']])
        if identity != self.map_items_identity:
            self.map_items_page, self.map_items_identity = 0, identity
        rows = []
        for group in ('heaps', 'mobs'):
            for container in floor[group]:
                location = container['name']+f" ({container['x']}, {container['y']})"
                if container.get('haunted'): location += ' · 闹鬼'
                for item in container.get('items', []):
                    rows.append((item, location))
        return rows, identity

    def map_items_detail(self):
        from .reference import native_item_artwork
        rows, token = self.map_item_rows()
        if not rows: return None
        self.map_items_page = min(self.map_items_page, (len(rows)-1)//20)
        start = self.map_items_page*20
        items = []
        for item, location in rows[start:start+20]:
            curse = ' · 有诅咒' if item.get('cursed') is True else ' · 诅咒未确认' if item.get('cursed') is None else ''
            items.append({'id': item['instance_key'], 'entry': item['key'], 'token': token,
                'summary': item['name']+f" ×{item['quantity']}"+curse,
                'location': location, 'artwork': native_item_artwork(item),
                'text': '\n\n'.join(part for part in (location, ' · '.join(item.get('details', [])), item.get('description', '')) if part),
                'can_reference': item['key'] in self.session.catalog.entry_index})
        return {'id': 'map_items', 'title': '楼层物品 · '+str(len(rows))+' 项', 'text': '', 'expanded': False,
            'items': items, 'token': token, 'previous': start > 0, 'next': start+20 < len(rows),
            'range': f'{start+1}–{min(start+20, len(rows))} / {len(rows)}'}

    def map_item_reference(self, item):
        self.sync_map_source()
        rows, token = self.map_item_rows()
        selected = next((row for row, _ in rows if row['instance_key'] == item.get('id')), None)
        if not selected or token != item.get('token'):
            raise ValueError('楼层已变化或隐藏内容已收起，请重新主动揭示后选择物品。')
        if selected['key'] not in self.session.catalog.entry_index:
            raise ValueError('此物品暂无数值资料；属性与说明仍可展开查看。')
        floor = copy.deepcopy(self.map_result)
        from .scouting import inspect_saved
        from .floor_reference import item_reference
        def read():
            current = inspect_saved(self.session, {'action': 'floor', 'depth': floor['depth'], 'branch': floor['branch'],
                'expected': floor['source']['expected'], 'reveal': True})
            if current['source']['floor_sha256'] != floor['source']['floor_sha256']:
                raise ValueError('该楼层保存已变化，请重新主动揭示后选择物品。')
            return item_reference(selected, floor)
        def complete(reference, error):
            self.sync_map_source()
            _, current_token = self.map_item_rows()
            if current_token != token or self.page != 'map': return
            if error: self.native.error(error)
            else: self.native.manager.open_reference(reference, None, '')
        self.native.queue_io('正在核对楼层物品', read, complete)

    def public_map(self):
        snap = self.session.snapshot()
        if snap.get('error') or snap.get('settings', {}).get('mode') != 'save':
            return None
        data = snap.get('data') or {}
        terrain = data.get('map')
        if not terrain:
            return None
        return {'depth': data.get('depth'), 'branch': data.get('branch', 0), 'map': copy.deepcopy(terrain),
                'revealed': False, 'note': terrain.get('caption', '最近保存的已探索地形；不代表当前视野')}

    def emit(self, page=None):
        from .reference import native_artwork, native_item_artwork
        # Background receipts refresh their own pane without changing navigation.
        page = self.page if page is None else page
        specs, rows, actions = [], [], []
        task_snap = self.session.snapshot()
        result_details = self.result_details(page)
        if page == 'inventory':
            rows = self.inventory()
            actions = [('reference', '查看物品数值'), ('reveal', '揭示这一件…'), ('equip_a', '加入比较 A'), ('equip_b', '加入比较 B')]
            text = '' if rows else '暂无背包物品；请连接存档并在游戏内保存。'
            selected = self.selected.get(page)
            row = next((r for r in rows if r['id'] == selected), None)
            if row:
                item = row['item']; text = item['name']+f" ×{item['quantity']}"
                if item.get('cursed') is True: text += ' · 有诅咒'
                result_details.append({'id': 'item_description', 'title': '物品说明', 'expanded': False,
                    'text': item['location']+'\n\n'+item['description']+'\n\n'+' · '.join(item.get('details', []))})
                if item.get('revealed'):
                    actions[1] = ('hide_reveal', '收起所选物品揭示')
                if item.get('revealed'): text += '\n已主动揭示；游戏鉴定状态未改变。'
                elif not item.get('known'): text += '\n身份未鉴定。'
                if item.get('available') is False: text += ' 当前不可用，仅作阅读参考。'
        elif page in self.raw:
            if page == 'alchemy': self.legacy_alchemy = json.loads(self.raw[page]['legacy']) if self.raw[page].get('legacy') else None
            specs = self.equipment_fields() if page == 'equipment' else self.alchemy_fields() if page == 'alchemy' else self.character_fields()
            actions = [('calculate', '比较装备' if page == 'equipment' else '计算炼金计划' if page == 'alchemy' else '计算总力量'),
                       ('import', '带入快照力量' if page == 'equipment' else '带入已知库存与能量' if page == 'alchemy' else '带入快照角色条件'),
                       ('undo', '撤回修改'), ('save', '保存方案…')]
            if page == 'equipment': actions.append(('use_character', '带入角色条件'))
            if self.saved.get(page): actions.append(('update', '更新原方案'))
            if page == 'alchemy': actions += [('add_target', '增加目标'), ('remove_target', '移除末项目标'), ('add_resource', '增加独立库存'), ('remove_resource', '移除末项库存'), ('add_path', '指定前置路径'), ('remove_path', '移除末项路径')]
            specs += [field('name', '方案名称', self.raw[page].get('name', ''), section='保存方案'), field('note', '用途 / 假设备注（可选）', self.raw[page].get('note', ''), section='保存方案')]
            text = self.results.get(page, '填写条件后计算。')
            if page == 'equipment' and self.equipment_context().get('character_scene') and self.raw[page].get('context.scene_enabled', '1') != '0':
                from .character_scene import calculate_scene
                captured = calculate_scene(self.equipment_context()['character_scene'])['strength']
                text += '\n\n固定角色条件 · '+('总力量 '+str(captured['effective']) if captured['state'] == 'known' else '总力量待确认：'+'；'.join(captured['missing']))+'。展开窗口底部来源，编辑「角色条件」后，再点击「带入角色条件」更新。'
            if page == 'alchemy' and page in self.calculated and self.structured_results.get(page, {}).get('format') == 2:
                text = self.alchemy_result_summary(self.structured_results[page])
            if page == 'alchemy' and self.legacy_alchemy:
                specs = []; actions = [('convert_legacy', '复制为可编辑的多目标方案')]
                text = self.results.get(page, '旧版原方案仍保留。')+'\n\n复制会保留原记录，按原配方每批产出换算目标件数。确认后再编辑并另存。'
        elif page == 'map':
            self.sync_map_source()
            rows = self.rows.get('map', [])
            actions = [('map_known', '查看当前已探索地形'), ('reload', '读取已生成楼层'), ('map_reveal', '主动揭示所选楼层'), ('map_hide', '收起隐藏内容')]
            text = '当前保存楼层默认只显示已探索地形，未知区域保持遮蔽。其他已生成楼层需选择后主动揭示；地图只读，非实时视野。'
            public = self.public_map()
            if self.map_result:
                floor = self.map_result
                text = f"第 {floor['depth']} 层 / 支线 {floor['branch']} · 已主动揭示\n\n"+floor['note']
                for label, key in [('地形', 'features'), ('陷阱', 'traps'), ('生物', 'mobs'), ('容器', 'heaps')]:
                    lines = []
                    for row in floor[key]:
                        line = row['name']+f" ({row['x']}, {row['y']})"
                        if key == 'traps': line += ' · '+('有效' if row['active'] else '已失效')+(' · 隐藏' if not row['visible'] else '')
                        if row.get('haunted'): line += ' · 闹鬼'
                        if row.get('hp') is not None: line += f" · 已保存生命 {row['hp']}"
                        if row.get('items'): line += f" · 保存物品 {len(row['items'])} 项"
                        lines.append(line)
                    text += '\n\n'+label+'\n'+'\n'.join(lines)
            elif public:
                text = f"当前第 {public['depth']} 层 / 支线 {public['branch']} · 已探索地形\n\n"+public['note']+'\n\n'+text
            else:
                text = '当前没有可显示的已探索地图；请连接有效存档并在游戏内完成保存。\n\n'+text
            if self.map_result or public:
                result_details.append({'id': 'map_discoveries', 'title': '地图说明与发现', 'text': text, 'expanded': False})
                floor = self.map_result or public
                text = f"第 {floor['depth']} 层"+(f" · 支线 {floor['branch']}" if floor['branch'] else '')
                text += ' · 已主动揭示' if self.map_result else ' · 已探索地形'
                text += '\n存档地图，非实时视野'
                item_detail = self.map_items_detail() if self.map_result else None
                if item_detail: result_details.append(item_detail)
        else:
            rows = self.rows.get('backups', [])
            actions = [('reload', '刷新历史'), ('backup_preview', '预览所选进度')]
            text = '选择备份或可撤回记录，先预览当前与目标进度。回档前必须关闭游戏；原进度会完整保留。'
            if not rows and self.backup_catalog is not None:
                if self.backup_catalog.get('records_available') is False:
                    text = '存档历史暂时无法读取。请核对下方原因后刷新。'
                elif task_snap['settings']['mode'] != 'save' or task_snap.get('error') or not task_snap.get('data'):
                    text = '暂无存档记录。请先在游戏中保存一局，再刷新历史。'
                elif self.backup_catalog.get('enabled'):
                    if self.backup_catalog.get('health') == 'blocked' or self.backup_catalog.get('error'):
                        text = '暂无存档记录，备份暂时受阻。'
                    else:
                        text = '暂无存档记录。已保存进度会自动备份，也可从窗口右上角「···」选择「立即备份已保存进度」。'
                else:
                    text = '暂无存档记录，自动备份已暂停。可从窗口右上角「···」选择「立即备份已保存进度」。'
            selected_record = next((r for r in rows if r['id'] == self.selected.get('backups')), None)
            if selected_record:
                text = self.backup_row_summary(selected_record['action'], selected_record['entry'])+'\n\n'+text
            if self.backup_catalog:
                text += '\n\n'+self.backup_catalog.get('error', '')+'\n'+self.backup_catalog.get('notice', '')
            if self.backup_preview:
                text = self.backup_preview['brief']
                actions.append(('backup_confirm', '核对并恢复此进度…' if self.backup_preview['action'] == 'restore' else '核对并撤回上次回档…'))
        self.revision += 1
        rendered_rows = [{**{k: r[k] for k in ('id', 'text', 'token')},
                          **({'summary': self.backup_row_summary(r['action'], r['entry'])} if page == 'backups' else {}),
                          'artwork': native_item_artwork(r['item']) if page == 'inventory' else {}} for r in rows]
        selected_item = next((r['item'] for r in rows if page == 'inventory' and r['id'] == self.selected.get(page)), None)
        presented_actions = []
        for command, label in actions:
            reason = ''
            if command in ('reference', 'reveal', 'hide_reveal', 'equip_a', 'equip_b') and not selected_item:
                reason = '先选择一个背包物品'
            elif command == 'reference' and selected_item and (not (selected_item.get('known') or selected_item.get('revealed')) or selected_item.get('key') not in self.session.catalog.entry_index):
                reason = '未知身份或此物品暂无数值资料'
            elif command == 'reveal' and selected_item and not selected_item.get('has_hidden_details'):
                continue
            elif command in ('equip_a', 'equip_b') and selected_item and (not (selected_item.get('known') or selected_item.get('revealed')) or selected_item.get('available') is not True or not family(selected_item.get('key'))):
                continue
            elif command in ('save', 'update') and page not in self.calculated:
                reason = '先计算有效条件，再保存方案'
            elif command == 'undo' and page not in self.undo:
                reason = '尚无可撤回的修改'
            elif command == 'backup_preview' and not self.selected.get('backups'):
                reason = '先选择一条存档记录'
            elif command == 'map_reveal' and not self.selected.get('map'):
                reason = '先读取并选择一个保存楼层'
            elif command == 'map_hide' and not self.map_result:
                reason = '尚未揭示隐藏内容'
            elif command == 'import' and (task_snap.get('error') or not task_snap.get('data')):
                reason = '当前没有可带入的有效局势；仍可手填条件'
            if command == 'import' and task_snap['settings']['mode'] == 'manual' and page in ('equipment', 'character'):
                label = '带入手填局势力量' if page == 'equipment' else '带入手填角色条件'
            presented_actions.append({'id': command, 'text': label, 'disabled': bool(reason), 'reason': reason})
        task_source = self.source_status(page, task_snap) if page in self.raw else {}
        origins = self.sources.get(page, {}).get('fields', {})
        for spec in specs:
            key = spec['key']
            spec['help'] = origins.get(self.origin_key(page, key), '明确手填假设；请按游戏核对')
            if key in ('name','note'):
                spec['help'] = '仅作为方案说明，不改变计算条件'
            if page == 'alchemy' and re.match(r'r\d+\.', key):
                spec['help'] = ('来自已知库存；各状态仍需核对' if self.raw[page].get(key.split('.')[0]+'.origin') == 'known' else '手填库存与条件假设')
            spec['help_visible'] = key not in ('name', 'note') and (spec['raw'] in ('', 'unknown') or
                task_source.get('stale', False) or self.sources.get(page, {}).get('mixed_snapshots', False))
            if key not in ('name', 'note') and spec['raw'] in ('', 'unknown'):
                spec['help'] = '条件未确认；计算前请核对。' + (' '+spec['help'] if task_source.get('stale') else '')
        comparison = copy.deepcopy(self.structured_results.get(page, {})) if page == 'equipment' and page in self.calculated else {}
        if comparison: comparison_summary(comparison, origins.get('strength', '独立假设'))
        for choice in comparison.get('choices', []):
            choice['artwork'] = native_artwork(choice.get('id'))
        self.host.command('game_state', page=page, fields=specs, rows=rendered_rows,
            artwork=native_item_artwork(selected_item) if selected_item else {},
            selected=self.selected.get(page, ''), text=text, actions=presented_actions,
            task_source=task_source,
            raw=copy.deepcopy(self.raw.get(page, {})), revision=self.revision,
            draft_revision=self.client_revisions.get(page, 0), dirty=page in self.dirty,
            calculated=page in self.calculated, focus_result=self.focus_result == page,
            notice=self.notices.get(page, '') if page not in self.dirty else '',
            notice_brief=self.notice_briefs.get(page, ''),
            result_details=result_details,
            map=(self.map_result or self.public_map() or {}).get('map', {}) if page == 'map' else {},
            map_revealed=bool(self.map_result) if page == 'map' else False,
            progress=copy.deepcopy((self.backup_preview or {}).get('progress', {})) if page == 'backups' else {},
            backup_summary=copy.deepcopy((self.backup_preview or {}).get('summary', {})) if page == 'backups' else {},
            comparison=comparison,
            planning=copy.deepcopy(self.structured_results.get(page, {}).get('planning', {})) if page == 'equipment' and page in self.calculated else {})
        if page == 'map': self.map_publication_pending = False
        self.focus_result = None
        self.native.report_drafts()

    def handle(self, item):
        page = item.get('page', self.page)
        if page not in ('inventory', *self.raw, 'map', 'backups'): raise ValueError('工作区不存在')
        self.page = page
        if item.get('action') == 'game_page' and page != 'inventory':
            self.hide_inventory_reveals()
        if 'draft_revision' in item:
            revision = item['draft_revision']
            if type(revision) is not int or revision < self.client_revisions.get(page, 0): return
            self.client_revisions[page] = revision
        if 'values' in item: self.edit(page, item['values'])
        if item.get('action') == 'game_edit':
            if item.get('structure'): self.emit(page)
            return
        if item.get('action') == 'game_page' and page in ('map', 'backups'):
            self.reload(page); self.emit(page); return
        action = item.get('command')
        if item.get('action') == 'game_select':
            if page == 'map': self.sync_map_source()
            row = next((r for r in (self.inventory() if page == 'inventory' else self.rows.get(page, [])) if r['id'] == item.get('id') and r['token'] == item.get('token')), None)
            if not row: raise ValueError('列表已变化，请重新选择')
            self.selected[page] = row['id']
            self.selected_tokens[page] = row['token']
            if page == 'backups': self.backup_preview = None
            if page == 'map': self.map_result = None; self.map_generation += 1
        elif action == 'reload': self.reload(page)
        elif action == 'map_reveal': self.reveal_map()
        elif action == 'map_item_reference': self.map_item_reference(item)
        elif action in ('map_items_previous', 'map_items_next'):
            self.sync_map_source()
            rows, token = self.map_item_rows()
            if not rows or token != item.get('token'): raise ValueError('楼层已变化，请重新主动揭示后查看物品。')
            self.map_items_page = max(0, min((len(rows)-1)//20, self.map_items_page+(-1 if action.endswith('previous') else 1)))
        elif action in ('map_hide', 'map_known'):
            self.map_result = None; self.map_generation += 1
        elif action == 'backup_preview': self.preview_backup()
        elif action == 'backup_confirm':
            preview = self.backup_preview
            if not preview: raise ValueError('请先重新预览当前与目标进度')
            self.host.command('game_confirm', page='backups', token=preview['token'], undo=preview['action']=='undo',
                slot=preview['payload']['slot'], save_root=preview['save_root'],
                text=preview['text']+'\n\n请先关闭游戏。确认后原进度会完整保留；不会消耗或删除备份。')
        elif action == 'backup_execute':
            preview = copy.deepcopy(self.backup_preview)
            if not preview or item.get('token') != preview['token']: raise ValueError('预览已变化，尚未恢复；请重新预览')
            payload = preview['payload']
            self.native.queue_io('正在恢复所预览进度', lambda: self.session.backup_action(payload),
                lambda result, error: self.backup_done(result, error, preview))
        elif action == 'calculate': self.calculate(page)
        elif action == 'use_character':
            if page != 'equipment': raise ValueError('只有装备比较使用共享角色条件')
            context = self.equipment_context(); context['character_scene'] = self.character_args()
            self.undo[page] = (copy.deepcopy(self.raw[page]), copy.deepcopy(self.sources.get(page, {})))
            self.raw[page].update(context=json.dumps(context, ensure_ascii=False), **{'context.scene_enabled': '1'})
            captured = copy.deepcopy(self.sources.get('character', {})) or {'mode': 'example'}
            captured.setdefault('mode', 'example')
            provenance = self.captured_field_label(captured, '固定角色条件') if captured['mode'] in ('save', 'manual') else '手填 · 固定角色条件'
            if any(str(value).startswith('手填') for value in captured.get('fields', {}).values()):
                provenance += ' · 含手填假设'
            self.sources[page] = self.equipment_source(captured, {'character_scene': provenance}, '固定带入角色条件；停用共享条件后才使用独立力量。')
            self.dirty.add(page); self.results.pop(page, None); self.calculated.pop(page, None)
        elif action == 'convert_legacy': self.convert_legacy()
        elif action == 'name_plan':
            if page not in self.calculated: raise ValueError('先计算有效条件，再命名保存')
            self.host.command('game_name_plan', page=page, name=self.raw[page].get('name', ''),
                note=self.raw[page].get('note', ''), existing=bool(self.saved.get(page)))
        elif action in ('save', 'update'):
            if page not in self.calculated: raise ValueError('先计算有效条件，再命名保存')
            raw = self.raw[page]; saved = self.saved.get(page); source = self.sources.get(page, {})
            if action == 'update' and not saved:
                raise ValueError('当前草稿未关联原方案，请另存新方案。')
            payload = {'action': 'save', 'kind': page, 'entry': None, 'name': raw.get('name', ''), 'note': raw.get('note', ''),
                       'params': self.calculated[page], 'source': {k: copy.deepcopy(source[k]) for k in ORIGIN_KEYS if k in source}}
            if 'fields' in payload['source']:
                payload['source']['fields'] = {key: value for key, value in payload['source']['fields'].items() if key in self.calculated[page]}
            if action == 'update':
                if not saved: raise ValueError('没有当前原方案；可另存')
                payload.update(record_id=saved['id'], expected_record_revision=saved['record_revision'])
            captured = copy.deepcopy(raw); captured_revision = self.client_revisions.get(page, 0)
            def complete(result, error):
                if error: self.native.error(error)
                else:
                    if self.raw[page] == captured and self.client_revisions.get(page, 0) == captured_revision:
                        self.saved[page] = result['plan']; self.dirty.discard(page)
                        self.undo.pop(page, None)
                        self.notices[page] = '已保存「'+result['plan']['name']+'」。'
                    else: self.native.error('先前条件已保存；等待期间的新输入仍是未保存草稿。')
                self.emit(page)
            self.native.queue_io('正在保存'+{'equipment': '装备', 'alchemy': '炼金', 'character': '角色'}[page]+'方案', lambda: self.session.workspace_action(payload), complete)
        elif action in ('add_target', 'remove_target', 'add_resource', 'remove_resource', 'add_path', 'remove_path'):
            self.undo['alchemy'] = (copy.deepcopy(self.raw['alchemy']), copy.deepcopy(self.sources.get('alchemy', {})))
            raw = self.raw['alchemy']; kind = action.split('_')[1]; count_key, prefix, maximum = {'target': ('targets', 't', 64), 'resource': ('resources', 'r', 256), 'path': ('paths', 'c', 64)}[kind]
            count = integer(raw[count_key], '行数'); adding = action.startswith('add')
            if adding and count >= maximum: raise ValueError('已达到可用行数上限')
            if not adding and count == 0: return
            if adding:
                if kind == 'target': raw.update({f't{count}.recipe': 'potion-healing', f't{count}.quantity': '1'})
                if kind == 'resource': raw.update({f'r{count}.id': '', f'r{count}.quantity': '', f'r{count}.reserve': '0', f'r{count}.origin': 'manual'})
            else:
                for key in list(raw):
                    if key.startswith(f'{prefix}{count-1}.'): del raw[key]
            raw[count_key] = str(count+(1 if adding else -1)); self.dirty.add('alchemy'); self.results.pop('alchemy', None); self.calculated.pop('alchemy', None)
        elif action == 'undo':
            if self.undo.get(page):
                self.raw[page], self.sources[page] = self.undo.pop(page); self.dirty.add(page); self.results.pop(page, None); self.calculated.pop(page, None)
        elif action == 'import': self.import_snapshot(page)
        elif action in ('reference', 'reveal', 'hide_reveal', 'equip_a', 'equip_b'): self.inventory_action(action)
        elif action == 'replace_decision': self.replace_decision(item.get('decision'))
        self.emit(page)

    def reload(self, page, *, preserve_selection=None):
        from .scouting import inspect_saved
        if page == 'map':
            self.sync_map_source(); self.map_generation += 1
            self.map_catalog = self.map_result = None; self.rows['map'] = []
            self.selected.pop('map', None); self.selected_tokens.pop('map', None)
            generation = self.map_generation
        def complete(result, error):
            if page == 'map':
                self.sync_map_source()
                if generation != self.map_generation:
                    return
            if error:
                self.rows[page] = []; self.native.error(error)
                if page == 'map': self.map_catalog = self.map_result = None
                else: self.backup_catalog = self.backup_preview = None
            elif page == 'map':
                self.map_catalog, self.map_result = result, None
                self.rows[page] = [{'id': f"{r['depth']}:{r['branch']}", 'text': f"第 {r['depth']} 层 / 支线 {r['branch']}"+(' · 当前' if r['current'] else '')+(' · 文件不可用' if not r['available'] else ''),
                    'token': binding_token([result['source'], r]), 'floor': r} for r in result['floors']]
            else:
                self.backup_catalog, self.backup_preview = result, None
                rows = []
                for action, entries in [('restore', result['history']), ('undo', result['undo'])]:
                    for row in entries:
                        rows.append({'id': action+':'+row['id'], 'text': self.backup_row_text(action, row),
                            'token': binding_token([result['context'], action, row]), 'entry': row, 'action': action, 'context': result['context']})
                self.rows[page] = rows
            self.selected.pop(page, None)
            self.selected_tokens.pop(page, None)
            if not error and page == 'backups' and preserve_selection:
                retained = next((row for row in self.rows[page] if row['id'] == preserve_selection), None)
                if retained:
                    self.selected[page], self.selected_tokens[page] = retained['id'], retained['token']
            self.emit(page)
        self.native.queue_io('正在读取楼层清单' if page == 'map' else '正在读取存档历史',
            lambda: inspect_saved(self.session, {'action': 'catalog'}) if page == 'map' else self.session.backup_status(), complete)

    def reveal_map(self):
        self.sync_map_source()
        row = next((r for r in self.rows.get('map', []) if r['id'] == self.selected.get('map')), None)
        if not row or not self.map_catalog: raise ValueError('请先读取并选择当前已生成的楼层')
        from .scouting import inspect_saved
        payload = {'action': 'floor', 'depth': row['floor']['depth'], 'branch': row['floor']['branch'], 'expected': self.map_catalog['source']['expected'], 'reveal': True}
        selected = row['token']
        self.map_generation += 1; generation = self.map_generation
        def complete(result, error):
            self.sync_map_source()
            if generation != self.map_generation:
                return
            current = next((r for r in self.rows.get('map', []) if r['id'] == self.selected.get('map')), {})
            if current.get('token') != selected:
                return
            if error: self.map_result = None; self.native.error(error)
            else: self.map_result = result
            self.emit('map')
        self.native.queue_io('正在只读揭示所选保存楼层', lambda: inspect_saved(self.session, payload), complete)

    @staticmethod
    def backup_row_summary(action, row):
        from .engine import CLASSES
        from .native_workspace import plan_updated_text
        summary = row if action == 'restore' else row.get('before') or {}
        label = row.get('label') or ('未命名备份' if action == 'restore' else '回档前进度')
        saved = summary.get('saved')
        stamp = plan_updated_text(saved)+' 保存' if type(saved) in (int, float) else '保存时间未记录'
        progress = GameWorkspace.progress_brief(summary) if summary.get('empty') else ' · '.join([
            CLASSES.get(summary.get('class'), summary.get('class') or '职业未记录'),
            '第 '+str(summary.get('depth', '?'))+' 层', '生命 '+str(summary.get('hp', '?'))+'/'+str(summary.get('ht', '?'))])
        return ('备份' if action == 'restore' else '撤回回档')+f" · 槽位 {row['slot']} · "+label+'\n'+progress+'\n'+stamp+('\n'+backup_version_text(summary) if not summary.get('empty') else '')+('\n'+summary['warning'] if summary.get('warning') else '')

    @staticmethod
    def backup_row_text(action, row):
        from datetime import datetime, timezone
        from .engine import CLASSES
        def timestamp(value):
            if type(value) not in (int, float): return '未记录'
            try: return datetime.fromtimestamp(value, timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M:%S UTC%z')
            except (ValueError, OSError, OverflowError): return '时间超出本机显示范围'
        summary = row if action == 'restore' else row.get('before') or {}
        label = row.get('label') or ('未命名备份' if action == 'restore' else '回档前进度')
        lines = [('备份' if action == 'restore' else '撤回回档')+f" · 槽位 {row['slot']} · "+label,
                 '保存时间（'+('存档文件' if action == 'restore' else '回档前存档')+'） '+timestamp(summary.get('saved'))]
        if summary.get('empty'): lines.append(GameWorkspace.progress_brief(summary))
        elif summary:
            lines.append(' · '.join([CLASSES.get(summary.get('class'), summary.get('class') or '职业未记录'),
                '第 '+str(summary.get('depth', '?'))+' 层', '生命 '+str(summary.get('hp', '?'))+'/'+str(summary.get('ht', '?'))]))
        else: lines.append('角色摘要未记录；请预览核对')
        if summary.get('warning'): lines.append(summary['warning'])
        if not summary.get('empty'): lines.append(backup_version_text(summary))
        observed = row.get('last_seen', row.get('time')) if action == 'restore' else row.get('time')
        if observed is not None: lines.append(('最近观察 ' if action == 'restore' else '回档时间 ')+timestamp(observed))
        lines.append('核验 ID '+str(row['id'])[:12])
        return '\n'.join(lines)

    @staticmethod
    def progress_brief(summary):
        if summary.get('empty'): return '进度无法读取' if summary.get('warning') else '空槽位'
        from .engine import CLASSES
        return ' · '.join([str(CLASSES.get(summary.get('class'), summary.get('class') or '职业未记录'))+
            ' Lv.'+str(summary.get('level','?')), '第 '+str(summary.get('depth','?'))+' 层',
            '生命 '+str(summary.get('hp','?'))+'/'+str(summary.get('ht','?'))])

    @staticmethod
    def progress_text(summary):
        if summary.get('empty'):
            return GameWorkspace.progress_brief(summary)+('\n'+summary['warning'] if summary.get('warning') else '')
        from datetime import datetime, timezone
        progress = GameWorkspace.progress_brief(summary)
        saved = summary.get('saved')
        try:
            stamp = datetime.fromtimestamp(saved, timezone.utc).astimezone() if type(saved) in (int, float) else None
            saved_text = stamp.strftime('%Y-%m-%d %H:%M:%S UTC%z') if stamp else '未记录'
        except (ValueError, OSError, OverflowError):
            saved_text = '时间超出本机显示范围'
        return progress+'\n'+backup_version_text(summary)+'\n保存时间 '+saved_text+('\n'+summary['warning'] if summary.get('warning') else '')

    def preview_backup(self):
        row = next((r for r in self.rows.get('backups', []) if r['id'] == self.selected.get('backups')), None)
        if not row: raise ValueError('请先选择一条备份或可撤回记录')
        entry = row['entry']; selected = row['token']; action = row['action']
        payload = {'slot': entry['slot'], 'id': entry['id'], 'context': row['context']}
        def complete(result, error):
            current = next((r for r in self.rows.get('backups', []) if r['id'] == self.selected.get('backups')), {})
            if error: self.backup_preview = None; self.native.error(error)
            elif current.get('token') == selected:
                text = f"槽位 {entry['slot']} · "+('恢复备份' if action == 'restore' else '撤回上次回档')+'\n存档目录：'+result['save_root']+'\n\n当前进度\n'+self.progress_text(result['current'])+'\n\n目标进度\n'+self.progress_text(result['target'])+'\n\n'+('种子和职业一致，请核对是否同一局冒险。' if result['same_run'] else '不同冒险或无法确认是否同一局，请核对目标。')
                label = entry.get('label') or ('未命名备份' if action == 'restore' else '回档前进度')
                brief = f"槽位 {entry['slot']} · "+('恢复备份' if action == 'restore' else '撤回回档')+' · '+label+'\n\n'
                brief += '\n\n'.join(title+(' · '+backup_version_text(result[key]) if not result[key].get('empty') else '')+
                    '\n'+self.progress_brief(result[key])+('\n'+result[key]['warning'] if result[key].get('warning') else '')
                    for key,title in [('target','目标进度'),('current','当前进度')])
                request = {**payload, 'action': action, 'expected_current': result['expected_current'],
                    'confirm': ('恢复' if action == 'restore' else '撤回')+f"槽位 {entry['slot']}"}
                self.backup_preview = {'action': action, 'text': text, 'brief': brief, 'payload': request, 'token': binding_token([request, text]),
                    'save_root': result.get('save_root', ''),
                    'summary': {'heading': f"槽位 {entry['slot']} · "+label,
                        'target': '目标 · '+self.progress_brief(result['target']),
                        'warning': '\n'.join(filter(None, [result['target'].get('warning'), result['current'].get('warning'),
                            '' if result['same_run'] else '不同冒险或无法确认，请核对目标。']))},
                    'progress': {'current': result['current'], 'target': result['target'], 'same_run': result['same_run']}}
            self.emit('backups')
        self.native.queue_io('正在核对当前与目标进度', lambda: self.session.backup_transfer('preview' if action == 'restore' else 'undo-preview', payload), complete)

    def backup_done(self, result, error, submitted):
        self.backup_preview = None
        payload = submitted['payload']
        operation = '恢复备份' if payload['action'] == 'restore' else '撤回回档'
        identity = f"槽位 {payload['slot']} · {operation} · 记录 {payload['id']}"
        target = self.progress_text(submitted.get('progress', {}).get('target', {}))
        if error:
            self.native.error(error)
            message = '未确认完成：'+error+'\n请修正原因后重新预览并确认；旧确认已失效。'
        elif isinstance(result, dict) and result.get('ok') is True:
            message = result.get('message') or '操作已完成；原进度已完整保留。可以重新进入游戏核对。'
        else:
            message = '未收到完成回执，请核对存档历史和当前进度后再操作。'
        root = submitted.get('save_root', '')
        self.notice_briefs['backups'] = f"槽位 {payload['slot']} · "+(operation+'完成 · 原进度已保留' if not error and isinstance(result, dict) and result.get('ok') is True else '未确认完成，请展开回执核对')
        self.notices['backups'] = identity+('\n存档目录：'+root if root else '')+'\n目标进度：'+target+'\n'+message
        self.emit('backups')
        self.reload('backups', preserve_selection=payload['action']+':'+payload['id'] if error else None)

    def open_plan(self, opened, confirmed=False):
        plan = opened['plan']; page = plan['kind']
        if page in self.dirty and not confirmed:
            self.confirmation = (page, copy.deepcopy(opened), self.display_raw(page), copy.deepcopy(self.sources.get(page, {})))
            self.host.command('confirm', surface='game', page=page, title='打开方案',
                text='当前'+{'equipment': '装备', 'alchemy': '炼金', 'character': '角色'}[page]+'有未保存草稿。可保存全部原始输入副本后继续、返回编辑，或明确放弃；半输入也能保留。', purpose='game_replace')
            return False
        self.dirty.discard(page); self.undo.pop(page, None); self.notices.pop(page, None)
        params = copy.deepcopy(plan['params'])
        if page == 'character': self.load_character(params, dirty=False)
        elif page == 'equipment':
            self.raw[page] = {k: str(v) for k, v in params.items() if not isinstance(v, (dict, list))}
            self.raw[page].setdefault('planning', '0')
            context = {k: params[k] for k in ('character_scene', 'scene_ring_slot', 'combat_model', 'target_context', 'investment_mode') if k in params}
            if context: self.raw[page]['context'] = json.dumps(context, ensure_ascii=False)
        else:
            self.legacy_alchemy = params if params.get('format') != 2 else None
            if not self.legacy_alchemy: self.load_alchemy(params)
            else: self.raw[page] = {'legacy': json.dumps(params, ensure_ascii=False)}
        self.raw[page].update(name=plan['name'], note=plan.get('note', ''))
        self.sources[page] = {**copy.deepcopy(plan.get('origin', {})), 'label': '固定方案「'+plan['name']+'」 · 打开不会更新原记录或带入当前游戏状态。'}
        self.saved[page] = copy.deepcopy(plan)
        if opened.get('result') is not None:
            self.structured_results[page] = copy.deepcopy(opened['result'])
            self.calculated[page] = params; self.results[page] = self.result_text(page, opened['result'])
            self.focus_result = page
        else:
            self.calculated.pop(page, None); self.results[page] = '当前规则无法计算原记录：'+opened.get('calculation_error', '')+'；原参数和备注仍保留。'
        self.page = page
        self.emit(page); self.host.command('game_show', page=page)
        return True

    def replace_decision(self, decision):
        captured, self.confirmation = self.confirmation, None
        if not captured or decision not in ('saved', 'discard'):
            return
        page, opened, raw, source = captured
        if self.display_raw(page) != raw or self.sources.get(page, {}) != source:
            raise ValueError('确认期间草稿已变化；原输入仍保留，请重新打开方案')
        if decision == 'saved':
            self.session.save_exit_draft('native', 'game-workspace', '切换方案前的原始草稿',
                {page: {'values': raw, 'source': source}})
        self.open_plan(opened, confirmed=True)

    def hide_inventory_reveals(self):
        self.inventory_reveal_generation += 1
        if not self.revealed:
            return
        selected = self.selected.get('inventory')
        self.revealed.clear()
        current = next((r for r in self.inventory() if r['id'] == selected), None)
        if current:
            self.selected['inventory'] = selected
            self.selected_tokens['inventory'] = current['token']

    def load_alchemy(self, params):
        raw = {k: str(params[k]) if params[k] is not None else '' for k in ('energy', 'energy_reserve', 'energy_origin', 'reference_version')}
        raw.update(targets=str(len(params['targets'])), resources=str(len(params['resources'])), paths=str(len(params['chains'])))
        instances = {row['key']: f'r{i}' for i, row in enumerate(params['resources'])}
        def choices(prefix, selected):
            for key, value in selected.items():
                if key == 'source_keys': raw[prefix+'.'+key] = '|'.join(instances.get(v, v) for v in value)
                elif isinstance(value, list):
                    for i, item in enumerate(value): raw[f'{prefix}.{key}.{i}'] = str(item)
                else: raw[prefix+'.'+key] = str(instances.get(value, value))
        for i, target in enumerate(params['targets']):
            raw[f't{i}.key'] = target.get('key', 't'+str(i))
            raw[f't{i}.recipe'] = target['recipe']; raw[f't{i}.quantity'] = str(target['quantity']); choices(f't{i}', target['choices'])
        for i, row in enumerate(params['resources']):
            raw[f'r{i}.key'] = row['key']
            for key in ('id', 'quantity', 'reserve', 'origin'): raw[f'r{i}.{key}'] = str(row[key])
            for key, value in row['state'].items():
                if key == 'rolled_choices':
                    for n, identity in enumerate(value): raw[f'r{i}.state.{key}.{n}'] = identity or ''
                else: raw[f'r{i}.state.{key}'] = '' if value is None else str(value).lower() if type(value) is bool else str(value)
        for i, (identity, chain) in enumerate(params['chains'].items()):
            raw[f'c{i}.id'] = identity; raw[f'c{i}.recipe'] = chain['recipe']; choices(f'c{i}', chain['choices'])
        self.raw['alchemy'] = raw

    def convert_legacy(self):
        params = self.legacy_alchemy
        if not params: raise ValueError('没有待复制的旧版炼金方案')
        recipe = self.recipe(params['recipe'])
        if not recipe: raise ValueError('原配方当前不支持复制；原记录保留')
        self.undo['alchemy'] = (copy.deepcopy(self.raw['alchemy']), copy.deepcopy(self.sources.get('alchemy', {})))
        metadata = {k: self.raw['alchemy'].get(k, '') for k in ('name', 'note')}
        self.load_alchemy({**params, 'format': 2, 'targets': [{'recipe': params['recipe'], 'quantity': params['batches']*recipe['quantity'], 'choices': {}}],
            'resources': [{**row, 'key': 'r'+str(i), 'state': {}} for i, row in enumerate(params['resources'])], 'chains': {}})
        self.raw['alchemy'].update(metadata)
        self.legacy_alchemy = None; self.saved.pop('alchemy', None); self.dirty.add('alchemy'); self.calculated.pop('alchemy', None); self.results.pop('alchemy', None)

    def inventory_action(self, action):
        row = next((r for r in self.inventory() if r['id'] == self.selected.get('inventory')), None)
        if not row or row['token'] != self.selected_tokens.get('inventory'): raise ValueError('请先选择当前背包实例；保存变化后需要重新选择')
        item = row['item']
        if action == 'hide_reveal':
            self.revealed.pop(item['instance_key'], None)
            current = next((r for r in self.inventory() if r['id'] == item['instance_key']), None)
            if current:
                self.selected['inventory'] = item['instance_key']
                self.selected_tokens['inventory'] = current['token']
        elif action == 'reveal':
            from .inventory_inspection import inspect_item
            binding = self.inventory_binding
            generation = self.inventory_reveal_generation
            def complete(result, error):
                self.inventory()
                if error: self.native.error(error)
                elif self.inventory_binding == binding and self.inventory_reveal_generation == generation:
                    self.revealed[item['instance_key']] = result['item']
                    if self.selected.get('inventory') == item['instance_key']:
                        self.selected_tokens['inventory'] = binding_token([binding, result['item']])
                self.emit('inventory')
            self.native.queue_io('正在只读揭示所选物品', lambda: inspect_item(self.session, {'expected': row['expected'], 'instance_key': item['instance_key'], 'reveal': True}), complete)
        elif action.startswith('equip_'):
            if not (item.get('known') or item.get('revealed')) or item.get('available') is not True or not family(item.get('key')): raise ValueError('请选择身份已知或已主动揭示、当前可用的受支持装备；未知身份不能自动带入')
            self.import_equipment(item, action[-1]); self.page = 'equipment'
            self.emit('equipment'); self.host.command('game_show', page='equipment')
        else:
            if not (item.get('known') or item.get('revealed')): raise ValueError('未知身份只提供说明；需要时可先主动揭示所选物品')
            from .native_workspace import NumericLookup
            snap = self.session.snapshot(); reference = NumericLookup.entry_context(snap, item['key'])
            reference.update(entry=item['key'], source_label=item['name']+' · '+reference['source_label'],
                             level_origin='not_applicable' if item.get('level_applicable') is False else 'unknown' if item.get('level') is None else 'revealed' if item.get('revealed') and not item.get('game_level_known') else 'known')
            reference['params'].update({k: item[k] for k in ('level', 'tier') if item.get(k) is not None})
            origins = reference.setdefault('field_origins', {})
            if item.get('level') is not None:
                origins['level'] = '已主动揭示的存档等级' if reference['level_origin'] == 'revealed' else '物品已知等级'
            if item.get('tier') is not None:
                origins['tier'] = '存档物品阶数'+(' · 主动揭示模式' if item.get('revealed') else '')
            if item.get('revealed'):
                reference['conditions'] = reference.get('conditions', '')+'；已主动揭示存档中的物品资料，未改变游戏鉴定状态'
            self.native.manager.open_reference(reference, None, '')

    def import_equipment(self, item, side):
        raw = self.raw['equipment']; self.undo['equipment'] = (copy.deepcopy(raw), copy.deepcopy(self.sources.get('equipment', {})))
        raw['id_'+side] = item['key']; raw['level_'+side] = '' if item.get('level') is None else str(item['level'])
        raw['level_known_'+side] = '1' if item.get('level') is not None else '0'
        raw['curse_'+side] = 'unknown' if item.get('cursed') is None else '1' if item['cursed'] else '0'
        raw['infusion_'+side] = 'unknown'
        kind = family(item['key'])
        public = {'id': item['key'], 'level': item.get('level'), 'curse': item.get('cursed')}
        if kind in ('weapon', 'missile', 'armor'):
            public.update(mastery=item.get('mastery'), augment=item.get('augmentation'),
                          hardened=(item.get('equipment_state') or {}).get('hardened'))
        if kind == 'armor': public['tier'] = item.get('tier')
        if kind == 'wand': public['resin'] = (item.get('alchemy_state') or {}).get('resin_bonus')
        for key, value in public.items():
            if key in ('id', 'level', 'curse'): continue
            raw[key+'_'+side] = ('' if key in ('tier', 'resin') else 'unknown') if value is None else str(int(value)) if type(value) is bool else str(value)
        origin = '主动揭示' if item.get('revealed') else '已知公开'
        captured = getattr(self, 'inventory_source', None) or self.captured_source(self.session.snapshot())
        provenance = self.captured_field_label(captured, origin)
        self.sources['equipment'] = self.equipment_source(captured,
            {**{key+'_'+side: provenance if value is not None else '未确认' for key, value in public.items()},
             'infusion_'+side: '未确认'},
            '装备 '+side.upper()+' · '+item['name']+' · '+item['location']+'，固定带入该背包实例的'+origin+'装备条件；游戏鉴定状态未改变，未确认的条件仍需明确核对。')
        self.sources['equipment'].setdefault('references', {})[side] = {'id': item['key'], 'name': item['name'],
            'effect_id': (item.get('equipment_state') or {}).get('effect_id'),
            'user_note': copy.deepcopy(item.get('user_note'))}
        self.dirty.add('equipment'); self.results.pop('equipment', None); self.calculated.pop('equipment', None)

    def import_snapshot(self, page):
        from .decisions import source, public_context
        snap = self.session.snapshot()
        if snap.get('error') or not snap.get('data'): raise ValueError('当前没有可带入的有效快照；原始输入保留')
        if page == 'equipment':
            total = snap['data'].get('character_scene', {}).get('strength', {})
            if total.get('usable') is not True:
                missing = '、'.join(total.get('missing') or ['戒指、天赋与临时状态'])
                raise ValueError('总力量未确认：'+missing+'。原输入保留；请补全角色条件，或明确手填游戏面板总力量。')
        self.undo[page] = (copy.deepcopy(self.raw[page]), copy.deepcopy(self.sources.get(page, {})))
        if page == 'alchemy':
            from .alchemy import resources_from_snapshot
            stock = resources_from_snapshot(self.session)
            if not stock['compatible']: raise ValueError(stock['message'])
            raw = self.raw[page]; count = len(stock['instances'])
            old = {raw.get(f'r{i}.snapshot_key'): (raw.get(f'r{i}.id'), raw.get(f'r{i}.reserve', '0')) for i in range(row_count(raw, 'resources'))}
            had_reserve = any(v[1] not in ('', '0') for v in old.values())
            for key in list(raw):
                if re.match(r'r\d+\.', key): del raw[key]
            raw.update(resources=str(count), energy='' if stock['energy'] is None else str(stock['energy']), energy_origin='known', reference_version=str(stock['reference_version']))
            for i, row in enumerate(stock['instances']):
                for key in ('id', 'quantity', 'reserve', 'origin'): raw[f'r{i}.'+key] = str(row[key])
                raw[f'r{i}.snapshot_key'] = row['key']
                raw[f'r{i}.key'] = row['key']
                previous = old.get(row['key'])
                raw[f'r{i}.reserve'] = previous[1] if previous and previous[0] == row['id'] else '' if had_reserve else '0'
                for key, value in row['state'].items():
                    if key == 'rolled_choices':
                        for n, identity in enumerate(value): raw[f'r{i}.state.rolled_choices.{n}'] = identity
                    else: raw[f'r{i}.state.'+key] = '' if value is None else str(value).lower() if type(value) is bool else str(value)
            # Old selected instance references cannot silently point to a newly replaced stack.
            for key in list(raw):
                if '.source_key' in key: raw[key] = ''
        elif page == 'character': self.load_character(snap['data']['character_scene']['params'])
        else:
            strength = public_context(snap).get('strength')
            if strength is None: raise ValueError('当前力量未确认；请明确手填条件')
            self.raw[page]['strength'] = str(strength)
        imported_fields = ('strength',) if page == 'equipment' else ('resources', 'energy') if page == 'alchemy' else tuple(self.character_args())
        captured = self.captured_source(snap)
        fields = {key: self.captured_field_label(captured, '快照' if snap['settings']['mode'] == 'save' else '手填局势') for key in imported_fields}
        label = source(snap)['label']+' · 固定带入，后续快照变化不会自动覆盖。'+('仅带入力量；装备其他条件仍需逐项核对。' if page == 'equipment' else '未知身份与未确认状态未猜测。')
        self.sources[page] = (self.equipment_source(captured, fields, label) if page == 'equipment' else
                              {**captured, 'fields': fields, 'label': label})
        self.dirty.add(page); self.results.pop(page, None); self.calculated.pop(page, None)
