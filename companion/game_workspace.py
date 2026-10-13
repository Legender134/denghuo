"""In-play task controllers using the same public data and calculators as the panel."""
from __future__ import annotations

import copy
import json
import re

from .native_host import binding_token
from .values_investment import family


BOOL = [('', '未确认'), ('false', '否'), ('true', '是')]
FLAGS = [('0', '否'), ('1', '是')]
CURSE = [('unknown', '未确认'), ('0', '无诅咒'), ('1', '有诅咒')]
ORIGIN_KEYS = ('kind', 'mode', 'slot', 'snapshot_at', 'fields', 'references')


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
        self.map_publication_pending = False
        self.structured_results = {}
        self.legacy_alchemy = None
        self.confirmation = None
        self.notices = {}
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
            canonical_key = ('rings' if key.startswith('ring') else key) if page == 'character' else (
                'resources' if re.match(r'r\d+\.', key) or key == 'resources' else
                'targets' if re.match(r't\d+\.', key) or key == 'targets' else
                'chains' if re.match(r'c\d+\.', key) or key == 'paths' else key) if page == 'alchemy' else (
                'character_scene' if key == 'context.scene_enabled' else 'scene_ring_slot' if key == 'context.scene_ring_slot' else
                'target_context' if key.startswith('context.target') else key.removeprefix('context.'))
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
                result += [field('mastery_'+side, '已使用精通药剂', raw.get('mastery_'+side, '0'), FLAGS, group),
                           field('augment_'+side, '强化', raw.get('augment_'+side, 'NONE'),
                                 [('NONE', '无强化'), ('EVASION', '闪避'), ('DEFENSE', '防御')] if kind == 'armor' else [('NONE', '无强化'), ('SPEED', '速度'), ('DAMAGE', '伤害')], group),
                           field('hardened_'+side, '已硬化', raw.get('hardened_'+side, '0'), FLAGS, group)]
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
        result += [field('strength', '有效力量（明确手填假设）', raw.get('strength', ''), section='共同条件'),
                   field('planning', '启用升级预算', raw.get('planning', '1'), FLAGS, '共同条件')]
        context = self.equipment_context()
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
        raw = self.raw['alchemy']; result = [field('energy', '本次可用总能量（未知请明确填写）', raw.get('energy', ''), section='共享预算'),
            field('energy_reserve', '最低保留能量', raw.get('energy_reserve', '0'), section='共享预算')]
        for i in range(row_count(raw, 'targets')):
            prefix = f't{i}'; group = '产出目标 '+str(i+1)+' · 按顺序共用库存'
            result += [field(prefix+'.recipe', '配方', raw.get(prefix+'.recipe', ''), self.recipe_choices(), group),
                       field(prefix+'.quantity', '本次制作并保留的产出件数', raw.get(prefix+'.quantity', '1'), section=group)]
            result += self.choice_fields(raw, prefix, raw.get(prefix+'.recipe'), group)
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
        self.calculated[page] = canonical
        self.structured_results[page] = copy.deepcopy(result)
        self.results[page] = self.result_text(page, result)
        self.focus_result = page

    def result_text(self, page, result):
        if page == 'equipment':
            lines = [f"A · {result['choices'][0]['name']}    /    B · {result['choices'][1]['name']}"]
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
            text += '\n\n'+' · '.join(label+' '+str(strength['components'][key]) for key, label in [('base', '基础'), ('might_rings', '戒指'), ('adrenaline', '激素涌动'), ('strongman', '力大无穷')])
            return text+'\n\n'+result['boundary']
        if result.get('format') != 2:
            return ('旧版固定配方方案 · 原记录保留\n\n'+result['recipe']['name']+f" · 计划 {result['requested_batches']} 批 / 可完成 {result['batches']} 批\n产出 {result['output']['quantity']} 件\n能量消耗 {result['energy']['spent']}，余 {result['energy']['remaining']}\n\n"+
                    '\n'.join(self.names.get(row['id'], row['id'])+f" · 消耗 {row.get('spent', row.get('consumed', '?'))}，余 {row.get('remaining', '?')}" for row in result['materials'])+'\n\n'+'\n'.join(result['warnings']))
        lines = ['预算内可完成' if result['within_budget'] else '材料、能量或条件不足']
        for row in result['targets']:
            recipe = self.recipe(row['recipe'])
            lines.append((recipe.get('name') or self.names.get(recipe.get('output'), row['recipe']))+f" · 计划 {row['planned_quantity']} / 目标 {row['requested_quantity']} 件")
        energy = result['energy']; lines.append(f"能量：{energy['quantity']} − {energy['spent']} = {energy['remaining']}；最低保留 {energy['reserve']}")
        for row in result['materials']:
            lines.append(self.names.get(row['id'], row['id'])+f" [{row['key']}] · 消耗 {row['spent']}，余 {row['remaining']}，保留 {row['reserve']}")
        for step in result['steps']:
            recipe = self.recipe(step['recipe']) or {}
            lines.append('制作 '+(recipe.get('name') or self.names.get(recipe.get('output'), step['recipe']))+f" · {step.get('batches', '?')} 批 · 能量 {step['energy']['spent']}")
            for row in step.get('inputs', []):
                lines.append('  消耗 '+self.names.get(row.get('id'), row.get('id', '原始实例'))+' ×'+str(row.get('quantity', '?'))+' · '+row.get('key', ''))
        for row in result['outputs']:
            lines.append('产出 '+self.names.get(row.get('id'), '随机或条件产出')+' ×'+str(row.get('quantity', '?'))+' · '+{'known': '身份与产量确定', 'random': '随机身份', 'conditional': '条件结果'}.get(row.get('certainty'), '需核对产出边界'))
        for row in result['shortages']: lines.append('缺口：'+row['reason'])
        for row in result['pending_conditions']: lines.append('待确认：'+row['condition'])
        for row in result['outcome_boundaries']: lines.append(row.get('message', row.get('text', row.get('condition', row.get('reason', '此产出有随机或条件边界，不能视为确定库存')))))
        lines += result['warnings']
        return '\n\n'.join(lines)

    def inventory(self):
        snap = self.session.snapshot()
        from .inventory_inspection import snapshot_token
        with self.session.lock:
            expected = snapshot_token(self.session)
        binding = binding_token([snap.get('started'), snap.get('revision'), snap.get('settings_revision'), expected])
        if binding != self.inventory_binding:
            self.revealed.clear(); self.inventory_binding = binding
        rows = []
        for item in [] if snap.get('error') else (snap.get('data') or {}).get('items', []):
            item = self.revealed.get(item['instance_key'], item)
            rows.append({'id': item['instance_key'], 'text': item['name']+f" ×{item['quantity']} · "+item['location'],
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
        if page is not None: self.page = page
        page = self.page; specs, rows, actions = [], [], []
        if page == 'inventory':
            rows = self.inventory()
            actions = [('reference', '查看所选物品数值'), ('reveal', '主动揭示所选物品'), ('equip_a', '放入装备 A'), ('equip_b', '放入装备 B')]
            text = '每项是实际背包实例；未知身份保持未知。选择物品查看说明。'
            selected = self.selected.get(page)
            row = next((r for r in rows if r['id'] == selected), None)
            if row:
                item = row['item']; text = item['name']+'\n'+item['location']+'\n\n'+item['description']+'\n\n'+' · '.join(item.get('details', []))
                if item.get('revealed'):
                    actions[1] = ('hide_reveal', '收起所选物品揭示')
                text += '\n\n'+('已主动揭示；游戏鉴定状态未改变。' if item.get('revealed') else '未鉴定身份保持未知。' if not item.get('known') else '已知公开资料。')
                if item.get('available') is False: text += ' 当前不可用，仅作阅读参考。'
        elif page in self.raw:
            if page == 'alchemy': self.legacy_alchemy = json.loads(self.raw[page]['legacy']) if self.raw[page].get('legacy') else None
            specs = self.equipment_fields() if page == 'equipment' else self.alchemy_fields() if page == 'alchemy' else self.character_fields()
            actions = [('calculate', '计算预算' if page in ('equipment', 'alchemy') else '计算总力量'), ('import', '带入存档'), ('undo', '撤回修改'), ('save', '另存方案')]
            if page == 'equipment': actions.append(('use_character', '带入角色条件'))
            if self.saved.get(page): actions.append(('update', '更新原方案'))
            if page == 'alchemy': actions += [('add_target', '增加目标'), ('remove_target', '移除末项目标'), ('add_resource', '增加独立库存'), ('remove_resource', '移除末项库存'), ('add_path', '指定前置路径'), ('remove_path', '移除末项路径')]
            specs += [field('name', '方案名称', self.raw[page].get('name', ''), section='保存方案'), field('note', '用途 / 假设备注（可选）', self.raw[page].get('note', ''), section='保存方案')]
            text = self.results.get(page, '填写条件后计算。空白和半输入会原样保留，不会当成零。')
            source = self.sources.get(page, {})
            text += '\n\n'+source.get('label', '明确手填假设；不是已经确认的当前实战状态。')
            if page == 'equipment' and self.equipment_context().get('character_scene'):
                from .character_scene import calculate_scene
                captured = calculate_scene(self.equipment_context()['character_scene'])['strength']
                text += '\n\n固定角色条件 · '+('总力量 '+str(captured['effective']) if captured['state'] == 'known' else '总力量待确认：'+'；'.join(captured['missing']))+'。在「更多 → 角色条件」编辑后，点击「带入角色条件」更新此比较；不会跟随游戏自动变动。'
            if self.dirty.__contains__(page): text += '\n当前条件尚未命名保存。'
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
                    text += '\n\n'+label+'\n'+'\n'.join(row['name']+f" ({row['x']}, {row['y']})"+(' · '+ '、'.join(item['name']+f" ×{item['quantity']}" for item in row['items']) if row.get('items') else '') for row in floor[key])
            elif public:
                text = f"当前第 {public['depth']} 层 / 支线 {public['branch']} · 已探索地形\n\n"+public['note']+'\n\n'+text
            else:
                text = '当前没有可显示的已探索地图；请连接有效存档并在游戏内完成保存。\n\n'+text
        else:
            rows = self.rows.get('backups', [])
            actions = [('reload', '刷新历史'), ('backup_preview', '预览所选进度')]
            text = '选择备份或可撤回记录，先预览当前与目标进度。回档前必须关闭游戏；原进度会完整保留。'
            if self.backup_catalog:
                text += '\n\n'+self.backup_catalog.get('error', '')+'\n'+self.backup_catalog.get('notice', '')
            if self.backup_preview:
                text = self.backup_preview['text']
                actions.append(('backup_confirm', '确认恢复所预览进度' if self.backup_preview['action'] == 'restore' else '确认撤回上次回档'))
        self.revision += 1
        self.host.command('game_state', page=page, fields=specs, rows=[{k: r[k] for k in ('id', 'text', 'token')} for r in rows],
            selected=self.selected.get(page, ''), text=text, actions=[{'id': k, 'text': v} for k, v in actions],
            raw=copy.deepcopy(self.raw.get(page, {})), revision=self.revision,
            draft_revision=self.client_revisions.get(page, 0), dirty=page in self.dirty,
            calculated=page in self.calculated, focus_result=self.focus_result == page,
            notice=self.notices.get(page, ''),
            map=(self.map_result or self.public_map() or {}).get('map', {}) if page == 'map' else {},
            map_revealed=bool(self.map_result) if page == 'map' else False,
            progress=copy.deepcopy((self.backup_preview or {}).get('progress', {})) if page == 'backups' else {},
            comparison=copy.deepcopy(self.structured_results.get(page, {})) if page == 'equipment' and page in self.calculated else {},
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
        elif action in ('map_hide', 'map_known'):
            self.map_result = None; self.map_generation += 1
        elif action == 'backup_preview': self.preview_backup()
        elif action == 'backup_confirm':
            preview = self.backup_preview
            if not preview: raise ValueError('请先重新预览当前与目标进度')
            self.host.command('game_confirm', page='backups', token=preview['token'], undo=preview['action']=='undo', text=preview['text']+'\n\n请先关闭游戏。确认后原进度会完整保留；不会消耗或删除备份。')
        elif action == 'backup_execute':
            preview = copy.deepcopy(self.backup_preview)
            if not preview or item.get('token') != preview['token']: raise ValueError('预览已变化，尚未恢复；请重新预览')
            payload = preview['payload']
            self.native.queue_io('正在恢复所预览进度', lambda: self.session.backup_action(payload), lambda result, error: self.backup_done(error))
        elif action == 'calculate': self.calculate(page)
        elif action == 'use_character':
            if page != 'equipment': raise ValueError('只有装备比较使用共享角色条件')
            context = self.equipment_context(); context['character_scene'] = self.character_args()
            self.undo[page] = (copy.deepcopy(self.raw[page]), copy.deepcopy(self.sources.get(page, {})))
            self.raw[page].update(context=json.dumps(context, ensure_ascii=False), **{'context.scene_enabled': '1'})
            self.dirty.add(page); self.results.pop(page, None); self.calculated.pop(page, None)
        elif action == 'convert_legacy': self.convert_legacy()
        elif action == 'name_plan':
            if page not in self.calculated: raise ValueError('先计算有效条件，再命名保存')
            self.host.command('game_name_plan', page=page, name=self.raw[page].get('name', ''),
                note=self.raw[page].get('note', ''), existing=bool(self.saved.get(page)))
        elif action in ('save', 'update'):
            if page not in self.calculated: raise ValueError('先计算有效条件，再命名保存')
            raw = self.raw[page]; saved = self.saved.get(page); source = self.sources.get(page, {})
            payload = {'action': 'save', 'kind': page, 'entry': None, 'name': raw.get('name', ''), 'note': raw.get('note', ''),
                       'params': self.calculated[page], 'source': {k: copy.deepcopy(source[k]) for k in ORIGIN_KEYS if k in source}}
            if 'fields' in payload['source']:
                payload['source']['fields'] = {key: value for key, value in payload['source']['fields'].items() if key in self.calculated[page]}
            if action == 'update':
                if not saved: raise ValueError('没有当前原方案；可另存')
                payload.update(record_id=saved['id'], expected_record_revision=saved['record_revision'])
            captured = copy.deepcopy(raw)
            def complete(result, error):
                if error: self.native.error(error)
                else:
                    if self.raw[page] == captured:
                        self.saved[page] = result['plan']; self.dirty.discard(page)
                        self.undo.pop(page, None)
                        self.notices[page] = '已保存「'+result['plan']['name']+'」。'
                        self.results[page] = self.results.get(page, '')+'\n\n已保存「'+result['plan']['name']+'」。'
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

    def reload(self, page):
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
                from .native_workspace import plan_updated_text
                rows = []
                for action, entries in [('restore', result['history']), ('undo', result['undo'])]:
                    for row in entries:
                        rows.append({'id': action+':'+row['id'], 'text': ('备份' if action == 'restore' else '撤回回档')+f" · 槽位 {row['slot']} · "+plan_updated_text(row.get('last_seen', row.get('time', 0)))+' · '+(row.get('name') or row['id'][:12]),
                            'token': binding_token([result['context'], action, row]), 'entry': row, 'action': action, 'context': result['context']})
                self.rows[page] = rows
            self.selected.pop(page, None); self.emit(page)
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
    def progress_text(summary):
        if summary.get('empty'): return '空槽位'
        from datetime import datetime, timezone
        from .engine import CLASSES
        progress = ' · '.join(label+' '+str(CLASSES.get(summary[key], summary[key]) if key == 'class' else summary[key])
            for key, label in [('class', '职业'), ('level', '等级'), ('depth', '层数'), ('hp', '生命'), ('ht', '最大生命')] if key in summary)
        saved = summary.get('saved')
        try:
            stamp = datetime.fromtimestamp(saved, timezone.utc).astimezone() if type(saved) in (int, float) else None
            saved_text = stamp.strftime('%Y-%m-%d %H:%M:%S UTC%z') if stamp else '未记录'
        except (ValueError, OSError, OverflowError):
            saved_text = '时间超出本机显示范围'
        identity = str(summary.get('run_id') or '')
        return progress+'\n保存时间 '+saved_text+(' · 冒险 '+identity[:12] if identity else '')+('\n'+summary['warning'] if summary.get('warning') else '')

    def preview_backup(self):
        row = next((r for r in self.rows.get('backups', []) if r['id'] == self.selected.get('backups')), None)
        if not row: raise ValueError('请先选择一条备份或可撤回记录')
        entry = row['entry']; selected = row['token']; action = row['action']
        payload = {'slot': entry['slot'], 'id': entry['id'], 'context': row['context']}
        def complete(result, error):
            current = next((r for r in self.rows.get('backups', []) if r['id'] == self.selected.get('backups')), {})
            if error: self.backup_preview = None; self.native.error(error)
            elif current.get('token') == selected:
                text = f"槽位 {entry['slot']} · "+('恢复备份' if action == 'restore' else '撤回上次回档')+'\n\n当前进度\n'+self.progress_text(result['current'])+'\n\n目标进度\n'+self.progress_text(result['target'])+'\n\n'+('同一次冒险。' if result['same_run'] else '可能属于不同冒险，请仔细核对。')
                request = {**payload, 'action': action, 'expected_current': result['expected_current'],
                    'confirm': ('恢复' if action == 'restore' else '撤回')+f"槽位 {entry['slot']}"}
                self.backup_preview = {'action': action, 'text': text, 'payload': request, 'token': binding_token([request, text]),
                    'progress': {'current': result['current'], 'target': result['target'], 'same_run': result['same_run']}}
            self.emit('backups')
        self.native.queue_io('正在核对当前与目标进度', lambda: self.session.backup_transfer('preview' if action == 'restore' else 'undo-preview', payload), complete)

    def backup_done(self, error):
        self.backup_preview = None
        if error: self.native.error(error)
        self.reload('backups')

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
            self.import_equipment(item, action[-1]); self.emit('equipment'); self.host.command('game_show', page='equipment')
        else:
            if not (item.get('known') or item.get('revealed')): raise ValueError('未知身份只提供说明；需要时可先主动揭示所选物品')
            from .native_workspace import NumericLookup
            snap = self.session.snapshot(); reference = NumericLookup.entry_context(snap, item['key'])
            reference.update(entry=item['key'], source_label=item['name']+' · '+reference['source_label'],
                             level_origin='not_applicable' if item.get('level_applicable') is False else 'unknown' if item.get('level') is None else 'revealed' if item.get('revealed') else 'known')
            reference['params'].update({k: item[k] for k in ('level', 'tier') if item.get(k) is not None})
            self.native.manager.open_reference(reference, None, '')

    def import_equipment(self, item, side):
        raw = self.raw['equipment']; self.undo['equipment'] = (copy.deepcopy(raw), copy.deepcopy(self.sources.get('equipment', {})))
        raw['id_'+side] = item['key']; raw['level_'+side] = '' if item.get('level') is None else str(item['level'])
        raw['level_known_'+side] = '1' if item.get('level') is not None else '0'
        raw['curse_'+side] = 'unknown' if item.get('cursed') is None else '1' if item['cursed'] else '0'
        raw['infusion_'+side] = 'unknown'; raw['hardened_'+side] = '0'; raw['mastery_'+side] = '0'; raw['augment_'+side] = 'NONE'
        origin = '主动揭示' if item.get('revealed') else '已知公开'
        self.sources['equipment'] = {'label': '装备 '+side.upper()+' · '+item['name']+' · '+item['location']+'，固定带入该背包实例的'+origin+'身份、等级与诅咒；游戏鉴定状态未改变，其他条件仍需明确核对。',
            'fields': {'id_'+side: origin, 'level_'+side: origin if item.get('level') is not None else '未确认',
                       'curse_'+side: origin if item.get('cursed') is not None else '未确认'}}
        self.dirty.add('equipment'); self.results.pop('equipment', None); self.calculated.pop('equipment', None)

    def import_snapshot(self, page):
        from .decisions import source, public_context
        snap = self.session.snapshot()
        if snap.get('error') or not snap.get('data'): raise ValueError('当前没有可带入的有效快照；原始输入保留')
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
        self.sources[page] = {**source(snap), 'label': source(snap)['label']+' · 固定带入，后续快照变化不会自动覆盖。'+('仅带入力量；装备其他条件仍为手填假设。' if page == 'equipment' else '未知身份与未确认状态未猜测。')}
        self.dirty.add(page); self.results.pop(page, None); self.calculated.pop(page, None)
