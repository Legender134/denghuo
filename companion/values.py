"""Player-facing, evaluated gameplay values. No implementation text in responses."""
from __future__ import annotations

import math
import re

from .rules import Formula, NumericRules, PREFIX, Range, UnknownFormula, display, key_for
from .values_data import FIXED, DURATION_EFFECTS, TRINKETS
from .values_abilities import add_advanced_values
from .values_decisions import add_operation_values
from .values_resources import add_resource_values
from .reference_sources import provenance
from .game_math import augmented_damage

INPUTS = {
    'level': ('装备等级', 0, 0, 100),
    'hero_level': ('角色等级', 10, 1, 30),
    'max_hp': ('你的最大生命', 65, 1, 10000),
    'hp': ('你的当前生命', 32, 0, 10000),
    'depth': ('主地牢等效层数', 10, 1, 30),
    'strength': ('有效力量（按游戏面板核对）', 14, 1, 1000),
    'target_hp': ('目标当前生命', 40, 0, 10000),
    'target_max_hp': ('目标最大生命', 40, 1, 10000),
    'targets': ('视野内目标数量', 3, 0, 100),
    'accuracy': ('你的命中值', 20, 0, 1000000),
    'evasion': ('目标闪避值', 10, 0, 1000000),
    'glyph_multiplier': ('刻印强度倍率（无增益填1）', 1, 0, 1000),
    'damage': ('此次基础伤害', 20, 0, 100000),
    'power': ('状态强度/剩余量', 10, 0, 10000),
    'healing_percent': ('每次恢复占剩余额度的百分比', 25, 0, 100),
    'healing_flat': ('每次额外固定恢复', 0, 0, 10000),
    'stored_charges': ('神器当前整数充能', 3, 0, 100),
    'shop_value': ('目标物品基础售价（不是商店标价）', 50, 1, 100000),
    'loot_chance': ('目标普通掉落概率', 20, 0, 100),
    'tier': ('原护甲阶数', 3, 1, 5),
    'vial': ('凝血试管等级（−1为无）', -1, -1, 3),
    'dew_volume': ('水袋中的露珠', 20, 0, 20),
    'shielding_dew': ('护盾露珠天赋点数（无则填0）', 0, 0, 3),
    'current_shield': ('当前屏障护盾', 0, 0, 10000),
    'charges': ('本次消耗充能', 1, 1, 3),
    'talent': ('相关天赋投入点数', 1, 1, 4),
    'enemy_exp': ('目标基础经验', 5, 0, 100),
    'minor': ('目标轻度负面状态数量', 0, 0, 20),
    'major': ('目标重度负面状态数量', 0, 0, 20),
    'casts': ('此前施法次数', 0, 0, 100),
    'combo': ('当前连击数', 8, 0, 1000),
    'armor_roll': ('此次自身随机护甲减伤', 10, 0, 100000),
    'enemy_armor': ('此次目标随机护甲减伤', 0, 0, 100000),
}


def integer_parameters(raw, *, signed_equipment=False, health_fields=None):
    result = {}
    for key, (label, default, low, high) in INPUTS.items():
        if key == 'level' and signed_equipment:
            low = -100
        value = raw.get(key, default)
        fractional=key in ('accuracy','evasion','glyph_multiplier','power','healing_percent','loot_chance')
        expected = '数值，可使用小数' if fractional else '整数'
        invalid = f'{label}需要填写{expected}（{low}–{high}）'
        if isinstance(value, bool):
            raise ValueError(invalid)
        if isinstance(value, str) and not re.fullmatch(r'[+-]?(?:\d{1,7}(?:\.\d{0,6})?|\.\d{1,6})', value):
            raise ValueError(invalid)
        try:
            numeric = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(invalid) from exc
        if not math.isfinite(numeric):
            raise ValueError(invalid)
        if not fractional and not numeric.is_integer():
            raise ValueError(invalid)
        number = numeric if fractional else int(numeric)
        if not low <= number <= high:
            raise ValueError(f'{label}须在 {low}–{high} 之间')
        result[key] = number
    if 'hp' not in raw:
        result['hp'] = min(result['hp'], result['max_hp'])
    if 'target_hp' not in raw:
        result['target_hp'] = min(result['target_hp'], result['target_max_hp'])
    validate_health_parameters(result, INPUTS if health_fields is None else health_fields)
    return result


def validate_health_parameters(parameters, fields):
    # A relation is meaningful only when this formula exposes both inputs.
    for current, maximum in (('hp', 'max_hp'), ('target_hp', 'target_max_hp')):
        if current in fields and maximum in fields and parameters[current] > parameters[maximum]:
            raise ValueError('当前生命不能超过最大生命')


def rounded(value):
    return math.floor(value + .5)


def metric(label, value, unit='', condition=''):
    text = display(value) if isinstance(value, (int, float, Range)) else str(value)
    return {'label': label, 'value': text, 'unit': unit, 'condition': condition}


def block(title, rows, note=''):
    return {'title': title, 'values': rows, 'note': note}


def table(title, columns, rows, note=''):
    return {'title': title, 'columns': columns, 'rows': [[str(v) for v in row] for row in rows], 'note': note}


def heal_schedule(amount, current, maximum, vial=-1, percent=.25, flat=0, apply_vial=True):
    """Match Healing.healingThisTick, including full-health wasted ticks and vial cap."""
    if vial >= 0 and apply_vial:
        amount = rounded(amount * (1 + .125 * (vial+1)))
    left, hp, rows = amount, current, []
    cap = [4+rounded(.15*maximum), 3+rounded(.1*maximum), 2+rounded(.07*maximum), 1+rounded(.05*maximum)]
    while left > 0 and len(rows) < 10000:
        tick = min(left, max(1, augmented_damage(left, percent)+flat))
        if vial >= 0:
            tick = min(tick, cap[vial])
        actual = min(maximum-hp, tick)
        hp += actual; left -= tick
        rows.append([len(rows)+1, tick, actual, hp, left])
    return amount, rows


TOKEN = re.compile(r'(?<![\d.])(?P<value>\d+(?:\.\d+)?(?:\s*[~～–—/]\s*\d+(?:\.\d+)?)*)\s*(?P<unit>%|倍|回合|点|格|层|级|次|个|瓶|张|件|包|颗|只|阶)')
NAMED_NUMBERS = [
    ('恢复生命', r'(?:恢复|治疗)([\d.~～–/]+)点生命'),
    ('额外伤害', r'([\d.~～–/]+)点额外伤害'),
    ('额外护盾', r'(?:护盾增加|增加)([\d.~～–/]+)点护盾'),
]


def description_numbers(text):
    """Turn official Chinese stat clauses into labelled numeric cells, not prose rows."""
    result = []
    for found in TOKEN.finditer(text):
        before = text[max(0, found.start()-40):found.start()]
        after = text[found.end():found.end()+18]
        unit = found['unit']; value = found['value'].replace(' ', '').replace('~', '–').replace('～', '–')
        sentence_before = re.split(r'[。；，\n：:]', before)[-1]
        if re.search(r'(?:生命值|血量|生命)(?:不高于|低于|至少|高于|达到)?$', before): label = '生命条件'
        elif '冷却' in before[-12:] or '冷却' in after[:12]: label = '冷却时间'
        elif '恢复' in before[-12:] and '生命' in after[:8]: label = '恢复生命'; unit = 'HP'
        elif '额外伤害' in after[:10] or ('伤害' in before[-12:] and unit=='点'): label = '额外伤害'; unit = 'HP'
        elif '护盾' in after[:8] or '护盾' in before[-10:]: label = '护盾'
        elif '力量' in before[-12:] or '力量' in after[:8]: label = '力量增益'
        elif '鉴定武器' in before: label = '武器鉴定速度'
        elif '鉴定护甲' in before: label = '护甲鉴定速度'
        elif unit == '%' and '概率' in after[:10]: label = '触发概率'
        elif unit == '%' and '伤害抗性' in after[:10]: label = '伤害减免'
        elif unit == '回合' and '进食' in before[-12:]: label = '进食耗时'
        elif unit == '回合':
            status = next((word for word in ('失明','致盲','残废','隐形','充能','赐福','浮空','冻结','狂乱','魅惑') if word in after[:14] or word in before[-10:]), '')
            label = status+'时长' if status else '持续时间'
        elif unit == '格': label = '距离'
        elif unit == '倍': label = '效果倍率'
        elif unit == '层': label = '层数'
        elif unit == '级': label = '等级'
        elif unit == '次': label = '次数'
        elif unit == '点':
            noun = re.match(r'(?:的)?([\u4e00-\u9fff]{1,8})', after)
            label = noun[1] if noun else '增益量'
        else: label = sentence_before[-14:].strip(' _') or '数量'
        # Retain the actual trigger as a condition; never pretend all branches apply together.
        sentence = re.split(r'[。\n]', text[max(0,text.rfind('。',0,found.start())+1):])[0].strip()
        if '随局势变化' in sentence:continue
        result.append(metric(label, value, unit, sentence))
    # Duplicate same-value clauses do not make a second numerical stat.
    return list({(r['label'],r['value'],r['unit'],r['condition']):r for r in result}.values())


class PlayerValues:
    def __init__(self, rules: NumericRules):
        self.rules, self.catalog = rules, rules.catalog

    def identity(self, entry):
        refs = entry.get('numeric_refs', [])
        return refs[0]['class'] if refs else None

    def duration(self, name):
        identity = (PREFIX+'actors.buffs.'+name).lower()
        return self.rules.constants(identity)['DURATION']

    def pure_value(self, identity, method, args=(), level=0, context=None):
        """Evaluate direct arithmetic, or a completely pure if/else returning arithmetic."""
        try:
            return self.rules.calculate(identity, method, list(args), level, context)
        except UnknownFormula:
            owner, rule = self.rules._method(identity, method, len(args))
        body = rule['body'].strip()
        # Only a sole exhaustive if/else is accepted here, not an early return in a stateful method.
        match = re.fullmatch(r'if\s*\(([^()]+)\)\s*\{\s*return\s+([^;]+);\s*\}\s*else\s*\{\s*return\s+([^;]+);\s*\}', body, re.S)
        if not match:
            raise UnknownFormula()
        variables = {**self.rules.constants(identity), **dict(zip((p['name'] for p in rule['params']), args)), **(context or {})}
        # Conditions are parsed by the same bounded arithmetic interpreter.
        return Formula(variables).evaluate(f'{match[1]} ? ({match[2]}) : ({match[3]})')

    def detail(self, identity, raw=None):
        identity = identity.removeprefix(PREFIX)
        entry = self.rules.entries.get(identity)
        if entry is None:
            # Nested known inventory items keep their existing player-facing Chinese name.
            normalized = (PREFIX+identity).lower()
            if normalized not in self.rules.classes:
                raise KeyError(identity)
            owner = self.rules.classes[normalized]
            entry = {'id':identity, 'name':self.rules.title(owner).split(' · ')[0], 'category':'物品', 'description':'', 'numeric_refs':[{'class':normalized}]}
        signed_equipment = identity.startswith(('items.weapon.melee.', 'items.armor.')) and '$' not in identity and not identity.endswith('.ability') and not any(part in identity for part in ('.glyphs.', '.curses.'))
        signed_equipment = signed_equipment or identity == 'items.scrolls.scrollofupgrade' or identity.startswith(('items.weapon.enchantments.', 'items.weapon.curses.', 'items.armor.glyphs.', 'items.armor.curses.')) and '$' not in identity
        p = integer_parameters(raw or {}, signed_equipment=signed_equipment, health_fields=())
        talent_cap=4
        if identity.startswith('actors.hero.spells.'):
            name=identity.rsplit('.',1)[-1].split('$')[0].removesuffix('spell')
            talent_entry=next((e for e in self.catalog.entries if e['id'].startswith('actors.hero.talent.') and e['id'].rsplit('.',1)[-1].replace('_','')==name),None)
            if talent_entry:
                talent_cap=next((int(v['value']) for v in talent_entry.get('numbers',[]) if v['label']=='最大天赋点数'),4)
            if p['talent']>talent_cap:raise ValueError(f'此技能相关天赋最多投入{talent_cap}点')
        if entry.get('numeric_status') == 'legacy':
            return {'id':identity, 'name':entry['name'], 'version':self.catalog.data['version'], 'blocks':[], 'inputs':[], 'notice':'此物品只存在于旧版本，当前游戏已经移除。', 'status':'legacy'}
        owner = self.identity(entry)
        if identity.startswith('plants.') and identity.endswith('$seed') and identity[:-5] in self.rules.entries:
            effect = self.detail(identity[:-5], raw)
            effect.update(id=identity, name=entry['name'])
            effect['blocks'] = [block('播种与触发前提', [],
                '以下复用对应植物种植并触发后的效果；携带种子本身不会立即获得这些数值。'
                '需在游戏中确认可种植地形、触发对象、职业和挑战；普通职业与守望者条件分别按下表核对。'),
                *[{**row, 'title': '种植后 · ' + row['title']} for row in effect['blocks']]]
            effect['provenance']['limits'].append('植物效果需要实际播种并触发；种子不是即时治疗或增益。')
            return effect
        result, requested = [], set()
        rows = [metric(*row) for row in FIXED.get(identity, [])]
        for label, name, scale, condition in DURATION_EFFECTS.get(identity, []):
            rows.append(metric(label+'时长', self.duration(name)*scale, '回合', condition))
        if rows:
            result.append(block('效果数值', rows))

        # Keep only evaluated values from the old engine. Never return summary formulas or members.
        if owner and not entry.get('ability_owner') and not identity.startswith(('actors.hero.talent.', 'actors.hero.heroclass.', 'actors.hero.herosubclass.', 'mechanics.')):
            for example in self.rules.examples(owner, p['level']):
                if example['title']=='戒指效果表':
                    continue
                copied = dict(example)
                copied['note'] = '基础数值；未加其他装备、天赋、精英和临时效果。'
                if copied.get('columns'):
                    copied['columns'] = [x.replace('L','装备等级').replace('C=','消耗').replace('伤害','充能 · 伤害') if x.startswith('C=') else x.replace('L','装备等级') for x in copied['columns']]
                    requested.add('level')
                    if copied['title']=='戒指效果表':
                        copied['note']='只佩戴一枚戒指，分别列出正常与诅咒状态。'
                    elif copied['title']=='护甲基础减伤':
                        copied['note']='无刻印、强化和精通药剂；信念护体挑战单列。'
                    selected=next((n for n,row in enumerate(copied.get('rows',[])) if str(row[0]).lstrip('+')==str(p['level'])),None)
                    if selected is not None:
                        copied['selected_row']=selected
                        if copied['title'] in ('装备等级数值表','护甲基础减伤'):
                            selected_values=copied['rows'][selected]
                            result.insert(0,block(f'当前 {p["level"]:+d} 装备数值',[metric(label,selected_values[n],'点' if '力量' in label else 'HP') for n,label in enumerate(copied['columns'][1:],1)],copied['note']))
                        elif copied['title']=='力量需求':
                            current=next((b for b in result if b['title']==f'当前 {p["level"]:+d} 装备数值'),None)
                            if current:current['values'].append(metric('力量需求',copied['rows'][selected][1],'点','无精通药剂、诅咒及其他特殊修正'))
                units={'初始生命':'HP','初始最大生命':'HP','基础伤害范围':'HP','基础减伤范围':'HP','基础命中':'点','基础闪避':'点','闪避':'点','力量需求':'点','基础经验':'经验','经验等级上限':'级','装备阶数':'阶','基础速度倍率':'倍','持续时间':'回合','基础持续时间':'回合','基础进食时间':'回合','饮用时间':'回合','阅读时间':'回合','基础更新间隔':'回合','基础饱食恢复量':'点','进入饥饿的饱食值':'点','饥饿掉血的饱食值':'点'}
                copied['values'] = [{**v,'unit':units.get(v['label'],''),'condition':''} for v in copied.get('values', []) if v['label']!='内部等级上限']
                for value in copied['values']:
                    if value['label']=='基础掉落概率':
                        value.update(label='通用随机掉落率',value=display(float(value['value'])*100),unit='%',condition='不含固定奖励、首领奖励或特殊掉落；实际掉落还受其他效果影响')
                if any(re.search(r'[A-Za-z_]{3,}',v['label']) for v in copied['values']):
                    copied['values']=[v for v in copied['values'] if not re.search(r'[A-Za-z_]{3,}',v['label'])]
                if copied.get('rows') or copied.get('values'):
                    result.append(copied)
        if owner:
            constants = self.rules.constants(owner)
            if identity.startswith('actors.buffs.'):
                rows=[]
                for name,label,unit in [('DURATION','默认持续','回合'),('DISTANCE','作用距离','格')]:
                    if name in constants:
                        rows.append(metric(label,constants[name],unit,'不同来源可以改变时长'))
                if rows: result.append(block('状态基础数值',rows))
            if identity.startswith('items.food.'):
                rows=[]
                for name,label,unit in [('energy','恢复饱食','点'),('TIME_TO_EAT','进食耗时','回合')]:
                    if name in constants: rows.append(metric(label,constants[name],unit,'无进食天赋与挑战'))
                if rows: result.append(block('进食数值',rows))
            if identity.startswith('items.artifacts.') and '$' not in identity:
                result.append(block('神器等级',[metric('最高显示等级',10,'级')]))
            if identity.startswith('items.weapon.') and '.ability' not in identity:
                rows=[]
                for name,label,unit in [('ACC','命中倍率','倍'),('DLY','攻击耗时','回合'),('RCH','攻击距离','格')]:
                    if name in constants: rows.append(metric(label,constants[name],unit,'力量达标、无强化与其他修正'))
                if rows:result.append(block('攻击属性',rows))
            if identity.startswith('items.') and not entry.get('ability_owner'):
                rows=[]
                for method,label,unit in [('value','单件基础售价','金币'),('energyVal','单件炼金回收','能量')]:
                    try:
                        value=self.pure_value(owner,method,level=p['level'],context={'quantity':1,'levelKnown':True,'cursedKnown':True,'cursed':False})
                        rows.append(metric(label,value,unit,'已鉴定、无诅咒；0表示不能获得此收益，商店买价另计'))
                    except (UnknownFormula,KeyError):pass
                if rows:result.append(block('出售与回收',rows))

        self.dynamic(identity, entry, owner, p, result, requested)
        self.rings(identity, p, result, requested)
        self.combat_effects(identity, owner, p, result, requested)
        self.world_effects(identity, owner, p, result, requested)
        self.abilities(identity, entry, owner, p, result, requested)
        self.extra_effects(identity, entry, owner, p, result, requested)
        self.artifacts(identity, p, result, requested)
        add_advanced_values(self, identity, p, result, requested)
        add_operation_values(identity, p, result, requested)
        add_resource_values(identity, p, result, requested)
        # State entries show the reviewed numeric effects of the associated skill.
        # This is a reference calculation, never a guess at an unseen active state.
        spell_states = {
            'actors.hero.spells.bodyform$bodyformbuff': 'actors.hero.spells.bodyform',
            'actors.hero.spells.lifelinkspell$lifelinkspellbuff': 'actors.hero.spells.lifelinkspell',
            'actors.hero.spells.recallinscription$useditemtracker': 'actors.hero.spells.recallinscription',
            'actors.hero.spells.stasis$stasisbuff': 'actors.hero.spells.stasis',
        }
        if identity in spell_states:
            related=self.detail(spell_states[identity],p)
            result.extend(related['blocks'])
            requested.update(v['key'] for v in related['inputs'])
        if identity.startswith('actors.hero.talent$'):
            tail=identity.split('$',1)[1].removesuffix('tracker').removesuffix('cooldown')
            tail={'liquidagilacc':'liquidagility'}.get(tail,tail)
            related=next((e for e in self.catalog.entries if e['id'].startswith('actors.hero.talent.') and e['id'].rsplit('.',1)[-1].replace('_','')==tail),None)
            if related:self.talent(related,result,p,requested)
        if identity.startswith('actors.hero.talent.'):
            self.talent(entry,result,p,requested)
        else:
            # These are already numeric facts in the official descriptions. Surface them as cells.
            facts=[] if identity.startswith('actors.hero.spells.lifelinkspell') else description_numbers(entry.get('description',''))
            if facts: result.append(block('其他明确数值',facts))
        requested.update(self.special_inputs(identity))
        validate_health_parameters(p, requested)
        alchemy_recipes = [row for row in self.catalog.data.get('alchemy_recipes', [])
                           if row['id'] in entry.get('alchemy_recipe_ids', [])]
        for recipe in alchemy_recipes:
            if recipe['output'] == identity:
                continue  # The exact output recipe is already shown by dynamic().
            result.append(block('炼金转换 → ' + recipe['name'],
                                [metric('能量消耗', recipe['cost'], '点/次'),
                                 metric('产出数量', recipe['quantity'], '件/次')],
                                '材料：' + '、'.join(f'{row["name"]} ×{row["quantity"]}' for row in recipe['inputs']) +
                                '；官方 4.0.2，已知身份或明确手填假设；可在炼金规划中填写库存和保留预算。'))
        result=[b for b in result if b['title']!='出售与回收']+[b for b in result if b['title']=='出售与回收']
        inputs=[{'key':k,'label':INPUTS[k][0],'value':p[k],'min':-100 if k=='level' and signed_equipment else INPUTS[k][2],'max':talent_cap if k=='talent' else INPUTS[k][3],'step':'any' if k in ('accuracy','evasion','glyph_multiplier','power','healing_percent','loot_chance') else 1} for k in INPUTS if k in requested]
        if identity=='items.armor.glyphs.stone':
            labels={'accuracy':'攻击者有效命中值（通常是敌人）','evasion':'穿戴者转换前的有效闪避值（通常是你）','damage':'刻印处理前的本次伤害'}
            for value in inputs:
                if value['key'] in labels:value['label']=labels[value['key']]
        if identity=='actors.buffs.healing':
            for input_value in inputs:
                if input_value['key']=='power':input_value.update(label='剩余治疗池（已经包含饰物加成）',step=1)
        if identity.split('$')[0]=='actors.buffs.monkenergy':
            for input_value in inputs:
                if input_value['key']=='power':input_value['label']='当前内力（可填小数）'
        power_labels={'actors.buffs.poison':'剩余中毒回合','actors.buffs.bleeding':'当前流血强度','actors.buffs.corrosion':'当前酸蚀强度（未取整）','actors.buffs.barrier':'当前屏障护盾','actors.hero.abilities.warrior.heroicleap':'此次护甲随机减伤','actors.hero.talent.body_slam':'此次护甲随机减伤','actors.buffs.amok':'当前狂乱剩余回合','actors.buffs.revealedarea':'当前感知剩余回合'}
        if identity in power_labels:
            for input_value in inputs:
                if input_value['key']=='power':input_value['label']=power_labels[identity]
        return {'id':identity,'name':entry['name'],'version':self.catalog.data['version'], 'status':'values',
                'blocks':result, 'inputs':inputs, 'alchemy_recipes': alchemy_recipes,
                'notice': '回合指游戏时间，不是现实秒数。小数最多显示六位有效数字。',
                'no_fixed_values':not result, 'non_numeric':self.non_numeric(identity),
                'provenance':provenance(self, identity, owner)}

    @staticmethod
    def non_numeric(identity):
        # Reviewed reading pages and scenery have no combat stat of their own.
        return identity.startswith(('items.journal.', 'tiles.custom.')) or identity in {
            'levels.rooms.special.weakfloorroom$hiddenwell',
            'levels.rooms.quest.ambitiousimproom$questentrance',
            'levels.rooms.quest.blacksmithroom$questentrance',
            'levels.rooms.quest.blacksmithroom$smithyvisuals',
            'levels.rooms.quest.ritualsiteroom$ritualmarker',
            'levels.rooms.quest.ritualsiteroom$table',
            'levels.rooms.quest.massgraveroom$massgravedeco',
            'levels.rooms.quest.mineentrance$questexit',
            'levels.rooms.quest.vault.vaultentranceroom$questentranceinternal',
            'levels.rooms.quest.vault.vaultfinalroom$markertiles',
        }

    def special_inputs(self, identity):
        return set()

    def extra_effects(self, identity, entry, owner, p, result, requested):
        l,h,d=p['level'],p['hero_level'],p['depth'];rows=[]
        if identity in ('items.potions.elixirs.elixirofmight','items.potions.elixirs.elixirofmight$htboost'):
            requested.add('hero_level');rows.append(metric('永久力量提升',1,'点'))
            result.append(table('升级后的临时生命加成',['饮用后升了几级','当前生命上限加成HP'],[[n,rounded((5-n)*rounded(4+(15+5*(h+n))/20)/5)] for n in range(6) if h+n<=30],'按普通角色基础生命计算；升级5次后失效，不能叠加。'))
        if identity=='items.dewdrop':
            requested.update(('hp','max_hp'));amount=rounded(.05*p['max_hp']);rows=[metric('每滴露珠治疗额度',amount,'HP','不带凝血试管，不含天赋'),metric('当前实际恢复',min(amount,p['max_hp']-p['hp']),'HP')]
        if identity=='items.ankh':
            requested.add('max_hp');rows=[metric('祝福十字架复活生命',p['max_hp']//4,'HP'),metric('祝福复活无敌',self.duration('Invulnerability'),'回合'),metric('普通十字架复活生命',p['max_hp'],'HP','需要取回遗落行囊')]
        if identity=='items.brokenseal':
            requested.add('tier');result.append(table('纹章护盾',['钢铁意志天赋','护盾HP'],[[n,3+2*p['tier']+n] for n in range(3)],f'护甲阶数 {p["tier"]}；护甲等级不增加此护盾。'));rows=[metric('基础冷却',150,'回合'),metric('离开战斗后护盾收回',5,'回合'),metric('收回时最大冷却返还',75,'回合')]
        if identity=='items.armor.glyphs.camouflage':requested.add('level');rows=[metric('踏草获得隐形',rounded(3+l/2),'回合','无奥术之戒等修正')]
        if identity=='items.armor.glyphs.obfuscation':requested.add('level');rows=[metric('潜行值增益',1+l/3,'点','无奥术之戒等修正')]
        if identity in ('items.artifacts.driedrose','items.artifacts.driedrose$ghosthero'):
            requested.add('hero_level');result.append(table('幽灵属性',['玫瑰等级','最大生命HP','力量','无武器伤害HP'],[[f'+{n}',40+10*n,13+n//2,f'1–{5+n//2}'] for n in range(11)]));rows=[metric('幽灵基础命中',h+9,'点'),metric('幽灵基础闪避',h+4,'点'),metric('无敌人在场时回复到满血',500,'回合','近似平均时间；无能量戒指'),metric('从空到满的召唤充能',500,'回合','近似时间；允许自然恢复且无能量戒指')]
        if identity in ('items.artifacts.capeofthorns','items.artifacts.capeofthorns$thorns'):
            requested.add('damage');result.append(table('荆棘披风等级效果',['神器等级','承伤转充能%','激活持续回合'],[[f'+{n}',50+5*n,10+n] for n in range(11)]));rows=[metric('激活期间本次随机反弹',f'0–{p["damage"]}','HP','只反弹相邻攻击者；同量伤害减免')]
        if identity in ('items.artifacts.timekeepershourglass','items.artifacts.timekeepershourglass$timefreeze'):
            result.append(table('沙漏容量与时间静止',['显示等级','最大充能','满充能最多静止回合'],[[f'+{2*n}',5+n,2*(5+n)] for n in range(6)],'攻击、施法等可提前结束。每消耗1充能抵消2回合。'));rows=[metric('诅咒时每回合额外耗时概率',10,'%'),metric('一次额外耗时',1,'回合')]
        if identity=='items.artifacts.alchemiststoolkit':result.append(table('炼金工具箱',['等级','重新准备所需回合','再升一级能量成本'],[[f'+{n}',(10-n)**2,6 if n<10 else '已满级'] for n in range(11)]))
        if identity in ('items.artifacts.talismanofforesight','items.artifacts.talismanofforesight$foresight'):
            result.append(table('预知护符',['等级','每回合充能%','发现单位显示回合','升级所需探索经验'],[[f'+{n}',display(.05+.005*n),5+2*n,100+50*n if n<10 else '已满级'] for n in range(11)],'无能量戒指；1个未探索格获得1经验，发现陷阱10、暗门100。'))
        if identity=='items.artifacts.hornofplenty':rows=[metric('每充能通常恢复饱食',90,'点'),metric('饥饿游戏每充能恢复',30,'点')]
        if identity=='items.artifacts.etherealchains':result.append(table('虚空锁链储能目标',['等级','自然恢复充能目标'],[[f'+{n}',5+2*n] for n in range(11)],'这个目标不是硬性上限，可通过升级和其他效果超过。每拉动1格消耗1充能。'))
        if identity in ('items.wands.wandoflivingearth','items.wands.wandoflivingearth$earthguardian'):
            requested.update(('level','hero_level','depth'));ev=(h+4)//2;rows=[metric('守卫最大生命',16+8*l,'HP'),metric('守卫命中',2*ev+5,'点'),metric('守卫闪避',ev,'点'),metric('守卫攻击伤害',f'2–{4+d//2}','HP'),metric('守卫普通减伤',f'{l}–{3+3*l}','HP'),metric('守卫信念护体减伤',f'{l}–{2+l}','HP')]
        if identity in ('items.potions.potionoftoxicgas','actors.blobs.toxicgas','actors.blobs.stenchgas'):
            requested.add('depth');rows.append(metric('毒气每回合伤害',1+d//5,'HP','直接伤害，区别于中毒状态'))
        if identity=='actors.blobs.electricity':
            requested.add('depth');rows=[metric('每次电击伤害',f'0–{rounded(2+d/5)}','HP'),metric('电击间隔',2,'回合','地面电场量为奇数时伤害'),metric('地上法杖每回合充能',.333,'次')]
        if identity in ('actors.buffs.barkskin','actors.buffs.arcanearmor','actors.buffs.physicalempower','actors.buffs.wandempower','actors.buffs.scrollempower'):
            requested.add('power');rows=[metric('当前随机减伤范围' if identity.endswith(('barkskin','arcanearmor')) else '当前伤害/等级增益',f'0–{p["power"]}' if identity.endswith(('barkskin','arcanearmor')) else p['power'],'HP' if not identity.endswith('scrollempower') else '级','强度由来源决定，在这里填写当前已获得的强度')]
        if identity=='items.stones.stoneofshock':requested.add('targets');rows=[metric('每根法杖立即充能',1+p['targets'],'次','命中至少一个目标时')]
        if identity=='items.stones.stoneofclairvoyance':rows=[metric('地图揭示半径',self.rules.constants(owner).get('DIST',12),'格')]
        if identity in ('items.stones.stoneofblast','levels.traps.explosivetrap'):
            requested.add('depth');rows=[metric('爆炸伤害',f'{4+d}–{12+3*d}','HP','减去护甲减伤'),metric('爆炸半径',1,'格')]
        if identity=='items.potions.brews.aquabrew':
            requested.add('depth');rows=[metric('范围半径',2,'格'),metric('对火属性目标伤害',f'{5+d}–{10+2*d}','HP')]
        if identity=='items.potions.brews.unstablebrew':
            drink=[('治疗',3),('灵视',2),('极速',2),('隐形',2),('浮空',2),('净化',2),('经验',1)]
            result.append(table('直接饮用时的效果概率',['药剂效果','普通游戏%','药水恐惧%'],[[name,display(100*weight/14),'0' if name=='治疗' else display(100*weight/11)] for name,weight in drink]))
            result.append(table('投掷时的效果概率',['药剂效果','概率%'],[[name,display(100/6)] for name in ('毒气','液火','麻痹气体','冰霜','净化','浮空')]))
            rows=[metric('炼制能量消耗',1,'点'),metric('药剂材料',1,'瓶'),metric('种子材料',1,'颗')]
        if identity=='items.spells.unstablespell':
            result.append(table('视野里没有敌人',['卷轴效果','概率%'],[[name,display(100*w/14)] for name,w in [('鉴定',3),('祛邪',2),('魔法地图',2),('充能',2),('催眠',2),('传送',2),('嬗变',1)]]))
            result.append(table('视野里有敌人',['卷轴效果','概率%'],[[name,display(100/7)] for name in ('镜像','充能','催眠','复仇','盛怒','传送','恐惧')]))
        if rows:result.append(block('补充数值',rows))
        for recipe in entry.get('recipes',[]):
            result.append(block('炼金配方',[metric('能量消耗',recipe['cost'],'点'),metric('产出数量',recipe['quantity'],'件/次')], '材料：'+ '、'.join(f'{x["name"]} ×{x["quantity"]}' for x in recipe['inputs'])))

    def rings(self, identity, p, result, requested, *, effective_bonus=None):
        if not identity.startswith('items.rings.ringof') or '$' in identity or identity.endswith('.ability'):
            return
        kind=identity.rsplit('.',1)[-1][6:]
        formulas={
            'accuracy': [('命中倍率',1.3,'倍')], 'arcana': [('附魔/刻印强度倍率',1.175,'倍')],
            'elements': [('所受元素伤害倍率',.825,'倍')],
            'energy': [('法杖充能速度',1.175,'倍'),('神器充能速度',1.175,'倍'),('英雄护甲充能速度',1.175,'倍')],
            'evasion': [('闪避倍率',1.125,'倍')], 'furor': [('攻击速度倍率',1.09051,'倍')],
            'haste': [('移动速度倍率',1.15,'倍')], 'wealth': [('普通掉落概率倍率',1.2,'倍')],
            'might': [('最大生命倍率',1.035,'倍')], 'sharpshooting': [('投掷耐久倍率',1.2,'倍')],
        }
        requested.add('level')
        force_tier=max(1,(p['strength']-8)/2)
        if force_tier>5:force_tier=5+(force_tier-5)/2

        def force_range(bonus):
            # Official min/max force tier1 for a nonpositive effective bonus.
            # BrawlersStance extra uses the original strength tier, not the forced tier.
            base_tier=1 if bonus<=0 else force_tier
            low=max(0,rounded(base_tier+bonus))
            high=max(0,rounded(5*(base_tier+1)+bonus*(base_tier+1)))
            extra=rounded(3+force_tier+bonus*(4+2*force_tier)/8)
            return f'{low}–{high}',f'{low+extra}–{high+extra}'

        if effective_bonus is not None:
            if type(effective_bonus) is not int or not -1000<=effective_bonus<=1000:
                raise ValueError('合计戒指效果等级需要是−1000–1000的整数')
            rows=[metric(label,base**effective_bonus,unit) for label,base,unit in formulas.get(kind,[])]
            if kind in ('might','sharpshooting','force'):
                label='力量增益' if kind=='might' else '投掷有效等级增益' if kind=='sharpshooting' else '持武器额外伤害'
                rows.append(metric(label,effective_bonus,'HP' if kind=='force' else '点'))
            if kind=='tenacity':
                requested.update(('max_hp','hp'))
                missing=(p['max_hp']-p['hp'])/p['max_hp']
                rows.append(metric('当前血量下的减伤',100*(1-.85**(effective_bonus*missing)),'%',
                                   f'当前生命 {p["hp"]}/{p["max_hp"]}；负数表示增伤'))
            if kind=='force':
                requested.add('strength')
                unarmed,brawler=force_range(effective_bonus)
                rows.extend([metric('普通徒手伤害',unarmed,'HP','装备武力之戒且未使用武僧徒手能力；未计目标防御'),
                             metric('拳击架势伤害',brawler,'HP','决斗家拳击架势已开启；额外伤害按所填力量')])
            if rows:
                result.append(block('给定条件下的戒指效果',rows,
                    f'合计戒指效果等级 {effective_bonus:+d}；有效力量 {p["strength"]}。组合、诅咒和临时等级由调用方明确核对。'))
            return

        levels=sorted(set([*range(11),p['level']]))
        for label,base,unit in formulas.get(kind,[]):
            result.append(table(label,['戒指等级','正常（'+unit+'）','诅咒（'+unit+'）'],[[f'{l:+d}',display(base**(l+1)),display(base**min(0,l-2))] for l in levels], '只佩戴一枚，无其他天赋或临时等级修正。'))
        if kind in ('might','sharpshooting','force'):
            label='力量增益' if kind=='might' else '投掷有效等级增益' if kind=='sharpshooting' else '持武器额外伤害'
            result.append(table(label,['戒指等级','正常','诅咒'],[[f'{l:+d}',l+1,min(0,l-2)] for l in levels]))
        if kind=='tenacity':
            requested.update(('max_hp','hp'));missing=(p['max_hp']-p['hp'])/p['max_hp']
            result.append(table('当前血量下的减伤',['戒指等级','正常减伤%','诅咒减伤%'],[[f'{l:+d}',display(100*(1-.85**((l+1)*missing))),display(100*(1-.85**(min(0,l-2)*missing)))] for l in levels], f'当前生命 {p["hp"]}/{p["max_hp"]}；负数表示增伤。'))
        if kind=='force':
            requested.add('strength')
            rows=[]
            for level in levels:
                normal,brawler=force_range(level+1)
                cursed,cursed_brawler=force_range(min(0,level-2))
                rows.append([f'{level:+d}',normal,brawler,cursed,cursed_brawler])
            result.append(table('徒手与拳击架势',['戒指等级','普通徒手伤害','拳击架势伤害','诅咒徒手伤害','诅咒拳击架势伤害'],rows,
                f'有效力量 {p["strength"]}；只佩戴一枚，未加其他修正。诅咒不保证随升级解除；拳击架势需要决斗家主动开启。'))

    def combat_effects(self, identity, owner, p, result, requested):
        if not owner:return
        level=p['level'];depth=p['depth'];hero=p['hero_level']
        if identity.startswith(('items.weapon.enchantments.','items.armor.glyphs.','items.weapon.curses.','items.armor.curses.')):
            effect_level = max(0, level)
            requested.add('level')
            row=self.rules.classes[owner];proc=next((r for r in row['rules'] if r['name']=='proc'),None)
            if proc:
                match=re.search(r'float\s+procChance\s*=\s*([^;]+);',proc['body'])
                if match:
                    expression=re.sub(r'procChanceMultiplier\([^)]*\)','1.0',match[1])
                    try:
                        values=[[f'{l:+d}',display(min(1,Formula({'level':max(0,l)}).evaluate(expression))*100)] for l in sorted(set([*range(11),level]))]
                        if len({v[1] for v in values})==1:
                            result.append(block('触发概率',[metric('每次符合条件的触发概率',values[0][1],'%','无额外触发强度修正')]))
                        else:result.append(table('触发概率',['装备等级','每次满足条件时触发%'],values,'没有奥术之戒、天赋或强化等额外修正。'))
                    except UnknownFormula:pass
            name=identity.rsplit('.',1)[-1];rows=[]
            if name=='blazing':rows=[metric('未燃烧目标燃烧时长',8,'回合')]
            elif name=='blooming':rows=[metric('触发后平均高草数量',1.5+.1*effect_level,'格','需要可生长地形'),metric('最少/最多高草',f'{math.floor(1.5+.1*effect_level)}–{math.ceil(1.5+.1*effect_level)}','格')]
            elif name=='blocking':rows=[metric('触发时获得护盾',max(0,2+level),'HP','无已有更高护盾；负等级不降低已有护盾')]
            elif name=='chilling':rows=[metric('每次冻伤延长',3,'回合'),metric('冻伤上限',6,'回合')]
            elif name in ('elastic','repulsion'):rows=[metric('基础击退力',2,'格','障碍、碰撞和体型会影响最终距离')]
            elif name=='shocking':requested.add('damage');rows=[metric('连锁伤害',rounded(p['damage']*.5),'HP','对邻近目标，不额外伤害首个目标')]
            elif name=='venomous':rows=[metric('增加毒强度',effect_level/2+3,'点'),metric('首次毒伤延迟',3,'回合')]
            elif name=='vorpal':requested.add('damage');rows=[metric('流血起始强度',2+p['damage']/2,'点')]
            elif name=='eldritch':rows=[metric('恐惧/眩晕基础时长',5,'回合')]
            elif name=='affection':rows=[metric('魅惑基础时长',self.duration('Charm'),'回合')]
            elif name=='entanglement':rows=[metric('植被护甲总量',5+2*effect_level,'HP','移动会失效')]
            elif name=='potential':rows=[metric('每根法杖充能',1,'次','未满的法杖')]
            elif name=='vampiric':
                requested.update(('max_hp','hp','damage'));chance=.05+.25*(p['max_hp']-p['hp'])/p['max_hp']
                rows=[metric('触发概率',100*chance,'%'),metric('触发时实际治疗',min(p['max_hp']-p['hp'],rounded(.5*p['damage'])),'HP')]
            elif identity.endswith('.antientropy'):rows=[metric('周围覆盖',8,'格'),metric('自身燃烧',4,'回合','不在水中')]
            elif identity=='items.armor.curses.corrosion':rows=[metric('周围淤泥覆盖',9,'格'),metric('淤泥时长',10,'回合')]
            elif identity.endswith('.metabolism'):
                requested.update(('hp','max_hp'));amount=min(4,p['max_hp']-p['hp']);rows=[metric('单次治疗',amount,'HP','尚未饿损时'),metric('饱食消耗',10*amount,'点')]
            elif identity.endswith('.multiplicity'):rows=[metric('触发后召唤数量',1,'个'),metric('英雄召唤镜像概率',50,'%','否则复制敌人或生成敌人')]
            elif identity.endswith('.overgrowth'):rows=[metric('触发植物',1,'株','守望者也承受普通植物效果')]
            elif identity.endswith('.stench'):rows=[metric('触发后毒气量',250,'单位')]
            elif identity.endswith('.dazzling'):rows=[metric('自身失明',self.duration('Blindness'),'回合'),metric('其他目击者失明',self.duration('Blindness')/2,'回合')]
            elif identity.endswith('.friendly'):rows=[metric('自身魅惑',self.duration('Charm'),'回合'),metric('目标魅惑',self.duration('Charm')/2,'回合')]
            elif identity.endswith('.sacrificial'):
                requested.update(('hp','max_hp'));amount=(p['hp']/p['max_hp'])**2*p['max_hp']/8;rows=[metric('流血强度',max(1,amount),'点'),metric('最终施加概率',10*min(1,amount),'%','包含两次概率检查，无触发强度修正')]
            elif identity.endswith('.explosive'):rows=[metric('初始爆炸耐久',100,'点'),metric('每次攻击消耗','0–10','点'),metric('平均爆炸间隔',20,'次攻击','估计值；独立随机消耗')]
            elif identity=='items.weapon.enchantments.crystal':
                requested.add('damage');rows=[metric('追加魔法伤害',math.ceil(p['damage']*.33),'HP','无触发强度修正')]
            elif identity=='items.weapon.enchantments.kinetic':
                requested.add('damage');rows=[metric('超额击杀伤害保留',p['damage'],'HP','这里输入的是击杀的超额伤害，下次命中追加')]
            elif identity=='items.weapon.enchantments.grim':
                requested.update(('target_hp','target_max_hp'));missing=(p['target_max_hp']-p['target_hp'])/p['target_max_hp'];rows=[metric('斩杀触发概率',min(1,(.5+.05*effect_level)*missing**2)*100,'%','目标生命填写本次普通伤害结算后的值；首领等可免疫')]
            elif identity=='items.weapon.enchantments.projecting':rows=[metric('近战额外攻击距离',1,'格','穿墙能力取决于攻击种类')]
            if rows:result.append(block('当前等级效果',rows,'无其他触发强度修正。'))
        if identity=='items.wands.wandofcorrosion':
            requested.add('level');result.append(table('酸蚀法杖数值',['法杖等级','气体量','起始酸蚀强度'],[[f'{l:+d}',50+10*l,2+l] for l in sorted(set([*range(11),level]))]))
        if identity=='items.wands.wandofblastwave':
            requested.add('level');result.append(block('击退',[metric('中心击退力',level+3,'格'),metric('邻格击退力',rounded(1.5+level/2),'格')],'障碍、碰撞和体型会影响最终距离。'))
        if identity=='items.wands.wandoftransfusion':
            requested.update(('level','max_hp','target_hp','target_max_hp'));cost=rounded(p['max_hp']*.05);amount=cost+3*level;healed=min(p['target_max_hp']-p['target_hp'],amount)
            result.append(block('移血的不同目标',[metric('治疗友军时自身损血',cost,'HP','未获得战斗法师免费施法'),metric('目标实际治疗',healed,'HP'),metric('目标溢出护盾',max(0,amount-healed),'HP'),metric('对敌施法自身护盾',5+level,'HP'),metric('活体敌人魅惑',self.duration('Charm')/2,'回合')]))
        if identity in ('items.wands.wandofregrowth','items.wands.wandofregrowth$lotus'):
            requested.update(('level','hero_level','charges'));c=p['charges'];limit='无限' if level>=10 else rounded(20+hero*(2+level)*(1+level/(50-5*level)))
            result.append(block('再生与金莲',[metric('本次高草数量上限',rounded((3.67+level/3)*c),'格','仅可生长地形；超量使用后可能变为枯草'),metric('缠绕时长',4*c,'回合'),metric('生露草/种子荚总概率',100*c/6,'%','未过量使用，有剩余生长位置；两种各占一半'),metric('随机植物概率',100*c/3,'%','同上'),metric('正常产草的累计充能额度',limit,'次充能'),metric('金莲生成所需充能',3,'次'),metric('金莲寿命',25+3*level,'回合'),metric('金莲作用半径',level,'格'),metric('金莲种子保留概率',min(1,.4+.04*level)*100,'%')]))
        if identity=='items.wands.wandofcorruption':
            requested.update(('level','enemy_exp','target_hp','target_max_hp','minor','major'));power=3+level/3;resist=(1+p['enemy_exp'])*(1+4*(p['target_hp']/p['target_max_hp'])**2)*.75**p['minor']*.5**p['major'];sure=power>resist
            result.append(block('普通敌人的腐化结果',[metric('直接腐化概率',100 if sure else 0,'%','目标可被腐化、仍有可施加的负面状态；无飞升加成'),metric('改为施加重度负面概率',0 if sure else min(1,power/resist)*100,'%'),metric('改为施加轻度负面概率',0 if sure else (1-min(1,power/resist))*100,'%')], '已无可施加的负面状态时也可直接腐化；该情况不在此概率内。重度包括狂乱、迟缓、虚弱诅咒、麻痹等；其他负面按轻度计。宝箱怪、雕像、蜜蜂、食人鱼、咒缚灵须不适用本表。'))
        if identity.startswith('items.wands.') and '$' not in identity:
            requested.add('level')
            try:
                initial=self.pure_value(owner,'initialCharges')
                result.append(block('法杖充能',[metric('最大充能',min(initial+level,10),'次','未嵌入法师魔杖'),metric('普通施法耗时',1,'回合')]))
            except UnknownFormula:pass

    def world_effects(self, identity, owner, p, result, requested):
        d,l,h,maximum=p['depth'],p['level'],p['hero_level'],p['max_hp']
        rows=[]
        if identity.startswith('levels.traps.'):
            name=identity.rsplit('.',1)[-1]
            requested.add('depth')
            fixed={
                'alarmtrap':[('直接伤害',0,'HP','吸引整层敌人')],
                'burningtrap':[('初始覆盖',9,'格','中心及相邻8格'),('每格火焰量',2,'单位','')],
                'blazingtrap':[('火焰距离',2,'格','沿可通行地形'),('普通地面火焰量',5,'单位/格',''),('水面/深渊火焰量',1,'单位/格','')],
                'chillingtrap':[('初始覆盖',9,'格',''),('每格冰雾量',10,'单位','')],
                'frosttrap':[('冰雾距离',2,'格','沿可通行地形'),('每格冰雾量',20,'单位','')],
                'shockingtrap':[('初始覆盖',9,'格',''),('每格电场量',10,'单位','')],
                'stormtrap':[('电场距离',2,'格','沿可通行地形'),('每格电场量',20,'单位','')],
                'oozetrap':[('初始覆盖',9,'格','非浮空目标'),('淤泥持续',20,'回合','入水洗去')],
                'disarmingtrap':[('丢失武器',1,'件','非诅咒主武器'),('目标距离','10–20','格','沿可通行地形；寻找不到合适位置会失败')],
                'distortiontrap':[('召唤数量','3–5','个','有足够空格'),('召唤3个概率',50,'%',''),('召唤4个概率',25,'%',''),('召唤5个概率',25,'%',''),('召唤延迟',2,'回合','')],
                'summoningtrap':[('召唤数量','1–3','个','有足够空格'),('召唤1个概率',50,'%',''),('召唤2个概率',25,'%',''),('召唤3个概率',25,'%',''),('召唤延迟',2,'回合','')],
                'pitfalltrap':[('坍塌延迟',1,'回合','首领层、支线及26层无效'),('初始覆盖',9,'格','')],
                'teleportationtrap':[('传送目标',1,'个','角色或地上物品堆')],
                'gatewaytrap':[('同时连接出口',1,'个','反复通过传送到同一出口')],
                'warpingtrap':[('传送目标',1,'个','英雄同时遗忘本层地图')],
            }
            rows.extend(metric(*x) for x in fixed.get(name,[]))
            if name in ('confusiontrap','toxictrap'):rows.append(metric('气体总量',300+20*d,'单位'))
            if name=='corrosiontrap':rows.extend([metric('酸雾总量',80+5*d,'单位'),metric('起始酸蚀强度',1+d//4,'点')])
            if name=='disintegrationtrap':rows.append(metric('魔法伤害',f'{30+d}–{50+d}','HP','未计抗性'))
            if name in ('rockfalltrap','geysertrap'):
                rows.extend([metric('伤害范围',f'{5+d}–{10+2*d}','HP','落石可由护甲减伤；激流仅伤害火属性目标'),metric('作用距离',2,'格')])
                if name=='rockfalltrap':rows.append(metric('麻痹',self.duration('Paralysis'),'回合','未被落石杀死时'))
            if name=='gnollrockfalltrap':rows.extend([metric('伤害范围','6–12','HP','可由护甲减伤'),metric('普通目标麻痹',3,'回合'),metric('豺狼守卫麻痹',10,'回合')])
            if name=='guardiantrap':rows.append(metric('最多召唤守卫',max(0,(d-5)//5),'个'))
            if name in ('worndarttrap','poisondarttrap'):
                rows.append(metric('飞镖伤害','4–8','HP','减去目标护甲减伤'))
                if name=='poisondarttrap':rows.append(metric('起始毒强度',8+rounded(2*d/3),'点'))
            if name=='grippingtrap':rows.extend([metric('未计护甲的流血强度',2+d//2,'点','再减去目标本次护甲减伤的一半'),metric('残废',self.duration('Cripple'),'回合')])
            if name=='flashingtrap':rows.extend([metric('未计护甲的流血强度',4+d//2,'点','再减去目标本次护甲减伤的一半'),metric('失明',self.duration('Blindness'),'回合'),metric('残废',2*self.duration('Cripple'),'回合')])
            if name=='weakeningtrap':rows.extend([metric('通常虚弱',3*self.duration('Weakness'),'回合'),metric('已虚弱时追加',.5*self.duration('Weakness'),'回合')])
            if name=='grimtrap':
                requested.update(('hp','max_hp','target_hp','target_max_hp'))
                rows.extend([metric('对英雄伤害',min(rounded((maximum+p['hp'])/2),math.floor(.9*maximum)),'HP','未计抗性；可能致死'),metric('对所填目标伤害',rounded((p['target_max_hp']+p['target_hp'])/2),'HP','未计抗性')])
        if identity.startswith('items.bombs.'):
            name=identity.rsplit('.',1)[-1];requested.add('depth')
            try: radius=self.pure_value(owner,'explosionRange')
            except UnknownFormula:radius=None
            if radius is not None:rows.append(metric('爆炸距离',radius,'格','沿可爆破地形'))
            if name in ('bomb','bomb$doublebomb','arcanebomb','shrapnelbomb','holybomb','flashbangbomb','firebomb','frostbomb','woollybomb','smokebomb','noisemaker'):
                low,high=4+d,12+3*d
                rows.append(metric('基础爆炸伤害',f'{low}–{high}','HP','普通爆炸减去目标护甲；奥术炸弹无视护甲'))
                if name=='holybomb':rows.append(metric('对亡灵/恶魔追加伤害',f'{rounded(low*.5)}–{rounded(high*.5)}','HP','追加伤害无视护甲，作用距离2格'))
                if name=='flashbangbomb':rows.extend([metric('额外电击伤害',f'{rounded(low/4)}–{rounded(high/4)}','HP','额外独立判定；普通爆炸伤害仍然生效'),metric('麻痹',self.duration('Paralysis'),'回合','电击后仍存活的目标')])
            if name=='firebomb':rows.extend([metric('普通地面火焰量',10,'单位/格'),metric('水面/深渊火焰量',2,'单位/格')])
            if name=='frostbomb':rows.append(metric('每格冰雾量',10,'单位'))
            if name=='smokebomb':rows.append(metric('烟雾总量',1000,'单位','每格先分配40，障碍导致剩余烟雾集中于中心'))
            if name=='woollybomb':rows.extend([metric('羊群生成半径',4,'格'),metric('普通楼层羊群初始寿命',200,'回合'),metric('首领层羊群初始寿命',20,'回合','可交互提前移除')])
            if name=='regrowthbomb':
                rows.extend([metric('直接爆炸伤害',0,'HP'),metric('每格再生气体量',10,'单位'),metric('产生2株普通植物概率',200/3,'%'),metric('产生3株普通植物概率',100/3,'%'),metric('额外露珠草概率',60,'%'),metric('额外种子荚概率',30,'%'),metric('额外星花概率',10,'%','每次额外选1株，有合适地格时')])
                healing=self.detail('items.potions.potionofhealing',p)
                result.extend(b for b in healing['blocks'] if b['title'] in ('按你的生命计算','每回合恢复明细'))
                requested.update(v['key'] for v in healing['inputs'])
            recipes={'frostbomb':('冰霜药剂',0),'woollybomb':('镜像卷轴',0),'firebomb':('液火药剂',1),'noisemaker':('盛怒卷轴',1),'smokebomb':('隐形药剂',2),'flashbangbomb':('充能卷轴',2),'regrowthbomb':('治疗药剂',3),'holybomb':('祛邪卷轴',3),'arcanebomb':('粘咕球',6),'shrapnelbomb':('邪能碎片',6)}
            if name in recipes:
                material,cost=recipes[name]
                result.append(table('炸弹炼金配方',['材料','数量'],[['炸弹',1],[material,1]],f'额外炼金能量 {cost}；产出1枚。'))
        if identity in ('actors.buffs.poison','plants.sorrowmoss','items.potions.potionoftoxicgas'):
            if identity=='actors.buffs.poison':
                requested.add('power');n=p['power'];ticks=math.ceil(n);rows=[metric('首次毒伤',math.floor(n/3)+1 if n>0 else 0,'HP'),metric('完整毒伤总量',sum(math.floor(max(0,n-i)/3)+1 for i in range(ticks)),'HP','不计免疫、减伤和后续续毒'),metric('剩余时间',n,'回合')]
        if identity=='actors.buffs.bleeding':
            requested.add('power');n=p['power'];rows=[metric('下一次流血',rounded(n),'HP'),metric('预计总流血伤害',rounded(n*4),'HP','随机衰减，平均估计值')]
        if identity in ('actors.buffs.ooze','items.potions.brews.causticbrew'):
            requested.add('depth');rows.extend([metric('淤泥伤害',1+d//5 if d>=5 else .5,'HP/回合','入水洗去；对粘咕为1HP/回合')])
        if identity in ('actors.buffs.burning','actors.blobs.fire','items.potions.potionofliquidflame'):
            requested.add('depth');rows.extend([metric('每次燃烧伤害',f'1–{3+d//4}','HP','无抗性；持续接触火焰会续燃')])
        if identity=='actors.buffs.corrosion':
            requested.update(('power','depth'));n=p['power'];rows=[metric('下一次酸蚀伤害',math.floor(n),'HP'),metric('下次后强度增加',1 if n<d//2+2 else .5,'点','伤害向下取整；持续时间由施加来源决定')]
        if identity=='actors.buffs.barrier':
            requested.add('power');n=p['power'];rows=[metric('每回合平均护盾衰减',min(1,n/20),'点','无不动如山等修正')]
        if identity.startswith('items.armor.') and identity.endswith(('warriorarmor','magearmor','roguearmor','huntressarmor','duelistarmor','clericarmor')):
            from .values_decisions import armor_ranges
            requested.update(('tier','level'));t=p['tier'];low,high,challenge=armor_ranges(t,l)
            rows=[metric('常规减伤',f'{low}–{high}','HP','使用转换前护甲的阶数；无强化、刻印与力量不足惩罚'),
                  metric('信念护体',f'0–{challenge}','HP','只在此挑战生效；无其他修正'),
                  metric('力量需求',8+2*t-math.floor((math.sqrt(8*max(0,l)+1)-1)/2),'点','无精通药剂')]
        if identity=='items.armor.glyphs.antimagic':rows=[metric('额外魔法减伤','0–0' if l<0 else f'{l}–{rounded(3+1.5*l)}','HP','仅对受此刻印影响的魔法；负等级在英雄刻印查询中按未生效处理')];requested.add('level')
        if identity=='items.armor.glyphs.flow':rows=[metric('水中移动速度倍率',1 if l<0 else 2+.5*l,'倍','英雄负等级护甲不触发此移动增益')];requested.add('level')
        if identity=='items.armor.glyphs.swiftness':rows=[metric('无近敌时移动速度倍率',1 if l<0 else 1.2+.04*l,'倍','英雄负等级护甲不触发此移动增益'),metric('近敌检查距离',3,'格','沿可通行路径')];requested.add('level')
        if identity in ('items.armor.glyphs.viscosity','items.armor.glyphs.viscosity$defereddamage'):
            requested.update(('level','damage'));n=p['damage'];effective=max(0,l);deferred=math.ceil(n*(effective+1)/(effective+6));rows=[metric('转为延缓伤害',deferred,'HP'),metric('立即承受',n-deferred,'HP')]
        if identity=='items.armor.glyphs.stone':
            from .game_math import stone_factor,float32
            requested.update(('accuracy','evasion','damage','glyph_multiplier'))
            factor=stone_factor(p['accuracy'],p['evasion'],p['glyph_multiplier'])
            rows=([metric('闪避转换的减伤',100*(1-factor),'%','刻印强度倍率已单独计入；命中和闪避需已包含其他生效增益')] if factor is not None else [])
            rows.append(metric('转换后本次伤害',math.ceil(float32(p['damage']*factor)) if factor is not None else 0,'HP',
                '随后仍可进行护甲等减伤；双方有效值同时为0时实际传递0伤害，不套常规减伤百分比'))
        if identity=='items.artifacts.chaliceofblood':
            result.append(table('圣杯升级风险与恢复',['当前等级','下一次刺伤范围HP','平均恢复1HP所需回合'],[[f'+{n}',f'{math.ceil(3+2.5*n*n)}–{math.floor(7+3.5*n*n)}' if n<10 else '已满级',display(10-1.33-.667*n)] for n in range(11)],'刺伤可由护甲/护盾减伤；没有能量戒指和盐晶等恢复修正。诅咒时每15回合恢复1HP。'))
        if identity in ('items.artifacts.cloakofshadows','items.artifacts.cloakofshadows$cloakstealth'):
            result.append(table('暗影斗篷',['斗篷等级','最大充能','每次充能维持隐形'],[[f'+{n}',min(3+n,10),'4回合'] for n in range(11)]))
        if identity=='items.artifacts.hornofplenty':result.append(table('丰饶之角容量',['神器等级','最大充能'],[[f'+{n}',5+n//2] for n in range(11)]))
        if rows:result.append(block('当前条件下的数值',rows,f'等效层数 {d}' if 'depth' in requested else ''))

    def artifacts(self, identity, p, result, requested):
        """Evaluated capacity, recovery and active costs of the remaining artifacts."""
        if identity=='items.artifacts.holytome':
            requested.add('hero_level');h=p['hero_level'];rows=[]
            for n in range(11):
                cap=min(n+3,10);extra=5*(n-7)/3 if n>7 else 0
                diff=h-(1+2*n)-(n-6 if n>=7 else 0)
                xp=rounded(10*(1.1**diff if diff>=0 else .75**(-diff)))
                rows.append([f'+{n}',cap,display(45-cap-extra),display(44-extra),xp,(n+1)*50 if n<10 else '已满级'])
            result.append(table('法典容量、充能与升级',['法典等级','最大充能','空池恢复首个充能的平均回合','仅缺1充能时平均回合','消耗1充能获得经验','下一等级所需经验'],rows,f'角色等级 {h}；已装备、可正常恢复、无能量戒指。充能速度随当前缺口变化；经验按一次消耗1充能计算。'))
            result.append(table('背包中的轻装阅读',['天赋点数','相对已装备充能速度%'],[[0,0],[1,25],[2,50],[3,75]]))
        elif identity=='items.artifacts.lloydsbeacon':
            result.append(table('道标容量与自然充能',['显示等级','最大充能','空池恢复首个充能的平均回合','仅缺1充能时平均回合'],[[label,3+n,70-10*n,90] for n,label in enumerate(['+0','+3','+7','+10'])],'等级只在这些显示节点变化；已装备、无诅咒、可正常恢复。'))
            result.append(table('道标使用成本',['用途','消耗充能','耗时回合'],[['设置返回点',0,1],['返回已设位置',0,0],['随机传送：等效1–20层',1,1],['随机传送：等效21层起',2,1]],'设置/返回点要求相邻8格无敌人，封层、首领层或禁止跨层传送的区域会阻止返回。当前版本不能用普通升级卷轴升级此神器。'))
            result.append(block('额外充能',[metric('每单位神器充能效果恢复',.25,'充能')]))
        elif identity=='items.artifacts.skeletonkey':
            result.append(table('骷髅钥匙容量与恢复',['神器等级','最大充能','空池恢复首个充能的平均回合','仅缺1充能时平均回合','零经验时升到下一级至少需要经验'],[[f'+{n}',3+n//2,display(120-(3+n//2)*7.5),112.5,5+n if n<10 else '已满级'] for n in range(11)],'已装备、无能量戒指且可正常恢复；升级要求经验超过门槛，已有经验会保留。'))
            result.append(table('钥匙使用成本',['用途','充能','神器经验','耗时回合'],[['开铁锁门',1,3,1],['开金锁箱',2,4,1],['开水晶门/箱',5,7,1],['锁普通门',2,2,1],['制造钥匙墙',2,2,1],['开自己锁住的门',0,0,1]]))
            result.append(block('钥匙墙与充能',[metric('钥匙墙最多持续',10,'回合'),metric('制造墙时击退',1,'格','需要可移动且可落脚的目标'),metric('每单位神器充能效果恢复',.133,'充能')]))
        elif identity=='items.artifacts.masterthievesarmband':
            requested.update(('stored_charges','shop_value','loot_chance'));rows=[];price=p['shop_value'];chance=p['loot_chance']
            for n in range(11):
                capacity=5+n//2;available=min(capacity,p['stored_charges']);per_charge=10+n/2;used=min(available,math.ceil(price/per_charge))
                rows.append([f'+{n}',capacity,display(3+.15*n),3+n//2,5+n//2,display(min(100,chance*(1+.1*n))),display(min(100,chance*(1.5+.1*n))),10+rounded(3.33*n) if n<10 else '已满级'])
            result.append(table('袖章容量、敌人偷窃与升级',['神器等级','最大充能','获得完整1级角色经验时充能','通常失明/残废回合','伏击时失明/残废回合','通常掉落偷取概率%','伏击掉落偷取概率%','升级经验门槛'],rows,f'输入的普通掉落概率 {display(chance)}%；不含财富戒指。超出敌人经验等级上限2级或已被偷过时，掉落偷取概率为0。'))
            rows=[]
            for n in range(11):
                available=min(5+n//2,p['stored_charges']);used=min(available,math.ceil(price/(10+n/2)))
                rows.append([f'+{n}',used,display(min(100,100*used*(10+n/2)/price)),4*used])
            result.append(table('商店偷窃实际概率',['神器等级','成功时消耗充能','成功概率%','成功时神器经验'],rows,f'物品基础售价 {price}，当前整数充能 {p["stored_charges"]}；每行按该等级容量截断。失败不消耗充能，也不增加经验。'))
            result.append(block('敌人偷窃成本与诅咒',[metric('偷敌人消耗',1,'充能'),metric('一般敌人偷窃经验',3,'点'),metric('伏击敌人偷窃经验',5,'点'),metric('诅咒每回合偷走1金币概率',20,'%','当前金币大于0')]))
        elif identity=='items.artifacts.unstablespellbook':
            result.append(table('魔典容量与充能',['神器等级','最大充能','空池恢复首个充能的平均回合','仅缺1充能时平均回合'],[[f'+{n}',2+math.floor(.6*n),120-5*(2+math.floor(.6*n)),115] for n in range(11)],'已装备、可正常恢复、无诅咒、无魔法免疫、无能量戒指。'))
            names=['鉴定','祛邪','镜像','充能','传送','催眠','魔法地图','盛怒','复仇','恐惧'];weights=[3,2,3,3,3,2,1,2,2,2]
            result.append(table('随机卷轴效果概率',['效果','概率%'],[[name,display(100*w/23)] for name,w in zip(names,weights)],'不产生升级或嬗变；鉴定、祛邪和地图效果已经计入重新抽取概率。'))
            result.append(table('魔典使用成本',['效果','充能'],[['普通卷轴效果',1],['已喂入卷轴的对应秘卷效果',2]],'秘卷选项还要求第一次扣费后至少剩1充能；不会触发使用卷轴的天赋。'))
            result.append(block('魔典升级',[metric('每次喂入指定卷轴升级',1,'级'),metric('每单位神器充能效果恢复',.1,'充能')]))

    def talent(self, entry, result, p, requested):
        name=entry['id'].rsplit('.',1)[-1]
        rows=None;columns=None;note=''
        if name=='body_slam':
            requested.add('power');columns=['投入点数','此次落地伤害HP']
            rows=[[n,f'{n+rounded(p["power"]*.25*n)}–{4*n+rounded(p["power"]*.25*n)}'] for n in range(1,5)]
            note=f'状态强度填写此次护甲随机减伤，当前 {display(p["power"])}；目标护甲仍可减伤。'
        elif name=='invigorating_victory':
            requested.update(('damage','max_hp','hp'));columns=['投入点数','治疗额度HP','当前最多实际恢复HP']
            rows=[[n,rounded(p['damage']*(1-.707**n))+5*n,min(p['max_hp']-p['hp'],rounded(p['damage']*(1-.707**n))+5*n)] for n in range(1,5)]
            note=f'基础伤害填写决斗累计承伤，当前 {p["damage"]}；仅击败决斗目标时生效。'
        elif name=='directed_power':
            requested.add('targets');columns=['投入点数','附魔强度增益%'];rows=[[n,30*n*p['targets']] for n in range(1,5)];note=f'当前范围内 {p["targets"]} 个敌人，作用于主要目标直接攻击。'
        elif name=='runic_transference':
            columns=['投入点数','可携带升级层数','常见刻印转移概率%','强力/诅咒刻印转移概率%'];rows=[[1,1,100,0],[2,1,100,100]];note='刻印必须在纹章已贴附时刻上。'
        elif name=='cached_rations':
            columns=['投入点数','最多口粮包数','最早尝试出现层数','每包饱食','每包治疗HP','每包斗篷充能'];rows=[[1,2,'2 / 4',200,5,1],[2,3,'2 / 4 / 6',200,5,1]];note='需在主地牢继续生成楼层且有合适房间；首次可出现层数不是保证掉落时间。'
        elif name=='wide_search':
            columns=['投入点数','搜索外框','无遮挡且远离边界时最多检查格数'];rows=[[0,'5×5方形',24],[1,'7×7圆角',44],[2,'7×7方形',48]];note='盗贼，不含自身格；只检查当前视野内格子。'
        elif name=='natures_bounty':
            columns=['投入点数','最多浆果颗数','掉落加速层数','此前踩草概率%','该层踩草概率%','之后踩草概率%'];rows=[[n,2+2*n,2+2*n,display(100/90),display(100/30),10] for n in [1,2]];note='每踩一格符合条件的高草分别判定；库存未耗尽时。每颗100饱食，每吃2颗得到1粒种子。'
        elif name=='twin_upgrades':
            columns=['投入点数','低等级武器最少落后阶数'];rows=[[1,2],[2,1],[3,0]];note='符合阶数要求时，将低等级武器的有效等级提高到另一把武器的等级。'
        elif name=='unencumbered_spirit':
            columns=['投入点数','1阶每件内力增益%','2阶每件内力增益%','3阶每件内力增益%','4–5阶增益%'];rows=[[1,50,50,50,0],[2,75,75,50,0],[3,100,75,50,0]];note='护甲、普通近战武器分别相加；赤手空拳、武力戒指拳击架势不计武器部分。3点时获布甲1件与镶钉手套1副。'
        elif name=='ratforcements':columns=['投入点数','召唤友军小鼠只数'];rows=[[n,n] for n in range(1,5)];note='鼠化术以自身为目标，周围有足够可落脚空格。'
        if rows is not None:
            result.append(table('各级天赋实际数值',columns,rows,note))
            result.append(block('加点上限',[metric('最多投入',max(int(r[0]) for r in rows),'点')]))
            return
        parts=list(re.finditer(r'\+(\d)\s*[：:]',entry['description']))
        if not parts:return
        rows=[];notes=[]
        for i, part in enumerate(parts):
            text=entry['description'][part.end():parts[i+1].start() if i+1<len(parts) else len(entry['description'])].strip()
            # Shared paragraphs after the rank clauses are additional conditions, not rank-specific rows.
            rank_text=text.split('\n\n')[0]
            facts=description_numbers(rank_text)
            for v in facts: rows.append(['+'+part[1],v['label'],v['value']+v['unit'],v['condition']])
            if '\n\n' in text:notes.append(text.split('\n\n',1)[1])
        if rows: result.append(table('各级天赋数值',['投入点数','效果','数值','生效条件'],rows,'\n'.join(notes)))
        cap=next((int(v['value']) for v in entry.get('numbers',[]) if v['label']=='最大天赋点数'),len(parts))
        result.append(block('加点上限',[metric('最多投入',cap,'点')]))

    def abilities(self, identity, entry, owner, p, result, requested):
        l,t,h=p['level'],p['talent'],p['hero_level'];rows=[]
        if identity.startswith('items.weapon.melee.'):
            name=identity.split('.')[3].split('$')[0]
            boosts={'wornshortsword':(3,1),'shortsword':(4,1),'sword':(5,1),'longsword':(6,1),'greatsword':(7,1),'cudgel':(3,1.5),'handaxe':(4,1.5),'mace':(5,1.5),'battleaxe':(5,1.5),'warhammer':(6,1.5),'rapier':(5,1.5),'katana':(8,2),'spear':(9,2),'glaive':(12,2.5),'greataxe':(15,2)}
            base_owner=self.identity(self.rules.entries.get('items.weapon.melee.'+name,entry))
            requested.add('level')
            if name in boosts and base_owner:
                a,b=boosts[name];values=[]
                for n in sorted(set([*range(11),l])):
                    boost=a+rounded(b*n)
                    try:low=self.pure_value(base_owner,'min',[n],n)+boost;high=self.pure_value(base_owner,'max',[n],n)+boost
                    except UnknownFormula:continue
                    values.append([f'{n:+d}',f'{low}–{high}',boost])
                if values:result.append(table('决斗家技能伤害',['装备等级','技能基础伤害HP','其中额外伤害HP'],values,'力量达标、未强化、没有戒指或其他伤害加成；护甲仍可减伤。巨斧需要生命低于50%。'))
            if name in ('dagger','dirk','assassinsblade'):rows=[metric('隐身',2+l,'回合'),metric('瞬移最大距离',{'dagger':5,'dirk':4,'assassinsblade':3}[name],'格')]
            elif name in ('roundshield','greatshield'):rows=[metric('格挡持续',({'roundshield':5,'greatshield':3}[name])+l,'回合'),metric('可格挡攻击',1,'次','格挡后提前结束；部分攻击可穿透')]
            elif name in ('gloves','sai','gauntlet'):rows=[metric('每次已积累连击追加伤害',{'gloves':3,'sai':4,'gauntlet':5}[name]+l,'HP'),metric('新连击记录时间',5,'回合'),metric('已延长的连击记录时间',15,'回合')]
            elif name in ('sickle','warscythe'):rows=[metric('流血起始强度',rounded((15+2.5*l) if name=='sickle' else (30+4.5*l)),'点'),metric('直接伤害',0,'HP','伤害由流血逐步造成')]
            elif name=='flail':rows=[metric('每层旋转追加伤害',8+2*l,'HP'),metric('最多旋转次数',3,'次'),metric('旋转保留',3,'回合')]
            elif name=='runicblade':rows=[metric('技能附魔强度倍率',3+.5*l,'倍')]
            elif name=='crossbow':rows=[metric('下一发弩箭追加伤害',3+l,'HP'),metric('下一发弩箭追加负面效果时长',3+l,'回合','仅有相应效果的弩箭')]
            elif name in ('scimitar','quarterstaff'):rows=[metric('有效持续时间',4+l,'回合','含刚释放后的一回合'),metric('额外攻击速度' if name=='scimitar' else '闪避倍率',60 if name=='scimitar' else 3,'%' if name=='scimitar' else '倍')]
            if rows and '$' not in identity:
                rows.append(metric('普通技能充能消耗',1,'次','连斩杀敌后的再次使用、持续旋转等可免费；天赋可改变消耗'))
        if identity.startswith('actors.hero.abilities.') and owner and '$' not in identity:
            cap=self.rules.constants(owner).get('baseChargeUse',35)
            result.append(table('英雄护甲技能充能消耗',['英勇能量天赋','消耗充能%'],[[0,display(cap)],*[['+'+str(n),display(cap*factor)] for n,factor in enumerate((.88,.77,.68,.6),1)]],'首次普通使用；连续跳跃、双重标记等天赋另有优惠。'))
        if identity.startswith('actors.hero.spells.') and owner and '$' not in identity:
            name=identity.rsplit('.',1)[-1];requested.add('talent')
            try:cost=self.pure_value(owner,'chargeUse',[None],context={'hero':None})
            except UnknownFormula:cost={'guidinglight':1,'holyintuition':max(0,4-t),'flash':2,'recallinscription':None,'stasis':2,'walloflight':3}.get(name)
            if cost is not None:rows.append(metric('普通施法消耗',cost,'次圣典充能','祭司的神导之光每50回合可免费一次；提前放出保存的友军或撤去光墙免费'))
            if name=='blessspell':rows.extend([metric('自身护盾',5+5*t,'HP'),metric('自身赐福',2+4*t,'回合'),metric('友军治疗额度',5+5*t,'HP','溢出转为护盾'),metric('友军赐福',5+5*t,'回合'),metric('命中/闪避倍率',1.25,'倍')])
            elif name=='layonhands':rows.extend([metric('对友军治疗额度',10+5*t,'HP','溢出转为护盾'),metric('对自己护盾额度',10+5*t,'HP'),metric('此法术累积护盾上限',3*(10+5*t),'HP'),metric('施法距离',1,'格'),metric('施法耗时',0,'回合')])
            elif name=='shieldoflight':rows.extend([metric('额外物理减伤',f'{1+t}–{2*(1+t)}','HP')])
            elif name=='sunray':rows.extend([metric('基础伤害','6–12' if t>=2 else '4–8','HP'),metric('失明',6 if t>=2 else 4,'回合')])
            elif name=='guidinglight':rows.extend([metric('基础伤害','2–8','HP'),metric('消耗光耀追加伤害',h+5,'HP','祭司以法杖、盟友攻击、辐光或指定神器消耗光耀'),metric('祭司免费施法间隔',50,'回合')]);requested.add('hero_level')
            elif name=='divinesense':rows.extend([metric('灵视半径',4+4*t,'格')])
            elif name=='cleanse':rows.extend([metric('护盾',10*t,'HP'),metric('持续净化',2*(t-1),'回合','不计施法时刻的立即净化')])
            elif name=='holylance':rows.extend([metric('基础伤害',f'{15+15*t}–{rounded(27.5+27.5*t)}','HP')])
            elif name=='holyweapon':rows.extend([metric('附魔持续',50,'回合')])
            elif name=='holyward':rows.extend([metric('刻印持续',50,'回合')])
            elif name=='mnemonicprayer':rows.extend([metric('正面状态延长/负面缩短',2+t,'回合')])
            elif name=='bodyform':rows.extend([metric('持续',rounded(13.33+6.67*t),'回合')])
            elif name=='mindform':rows.extend([metric('模拟法杖等级',2+t,'级')])
            elif name=='spiritform':rows.extend([metric('模拟戒指等级',t,'级'),metric('模拟神器等级',2+2*t,'级'),metric('持续',20,'回合')])
            elif name=='lifelinkspell':rows.extend([metric('实际链接持续',rounded(6.67+3.33*t),'回合','该版本游戏文字说明的时长与实际效果不一致'),metric('双方平分伤害比例',50,'%','各自向上取整')])
            elif name=='stasis':rows.extend([metric('最大保存时间',30+30*t,'回合'),metric('提前放出消耗',0,'次充能')])
            elif name=='beamingray':rows.extend([metric('友军传送最大距离',4*t,'格','不可移动友军减半'),metric('对最近敌人伤害增益',30+5*t,'%'),metric('增益持续',10,'回合')])
            elif name=='auraofprotection':rows.extend([metric('伤害减免',10+10*t,'%'),metric('刻印强度增益',25+25*t,'%')])
            elif name=='smite':requested.add('hero_level');rows.extend([metric('追加魔法伤害',f'{5+h//2}–{10+h}','HP')])
            elif name=='hallowedground':rows.extend([metric('地面宽度',1+2*t,'格'),metric('单格每回合高草生成概率',100/(10+10*t),'%')])
            elif name=='walloflight':rows.extend([metric('光墙长度',1+2*t,'格'),metric('主动移除消耗',0,'次充能')])
            elif name=='divineintervention':rows.extend([metric('英雄/友军护盾',100+50*t,'HP'),metric('升华延长',2+t,'回合')])
            elif name=='judgement':requested.add('casts');base=5+5*t;damage=base+rounded(base*p['casts']/3);rows.extend([metric('当前审判伤害',f'{damage}–{2*damage}','HP')])
            elif name=='flash':requested.add('casts');rows.extend([metric('升华中当前消耗',2+p['casts'],'次充能','次数指升华中此前使用闪现的次数')])
            elif name=='recallinscription':result.append(table('铭文复诵消耗',['物品种类','圣典充能'],[['普通符石',2],['强化/附魔符石',4],['普通卷轴',3],['嬗变卷轴',6],['一般秘卷',4],['蜕变/附魔秘卷',8]]));rows.append(metric('可复诵时间',300 if t>=2 else 10,'回合'))
        if rows:result.append(block('技能具体效果',rows,'未计额外天赋、强化、抗性；当前所填等级生效。'))

    def dynamic(self, identity, entry, owner, p, result, requested):
        level,hero,maximum,current,depth=p['level'],p['hero_level'],p['max_hp'],p['hp'],p['depth']
        heal_ids={'items.potions.potionofhealing','items.potions.elixirs.elixirofhoneyedhealing'}
        if identity in heal_ids:
            requested.update(('max_hp','hp','hero_level','vial'))
            base=math.floor(.8*maximum+14)
            total,schedule=heal_schedule(base,current,maximum,p['vial'])
            rows=[metric('治疗池总量',total,'HP'),metric('最终实际恢复',min(maximum-current,total),'HP'),metric('首次恢复',schedule[0][2],'HP'),metric('治疗池耗尽',len(schedule),'回合'),metric('药水恐惧挑战毒强度',4+hero//2,'点','药水恐惧时不治疗，改为中毒')]
            result.append(block('按你的生命计算',rows,f'当前生命 {current}/{maximum}；凝血试管 '+('未佩戴' if p['vial']<0 else f'+{p["vial"]}')))
            result.append(table('每回合恢复明细',['恢复次数','本次治疗池消耗','实际恢复HP','治疗后生命','剩余治疗池'],schedule))
        if identity=='actors.buffs.healing':
            requested.update(('max_hp','hp','power','healing_percent','healing_flat','vial'))
            if p['power']!=int(p['power']):raise ValueError('剩余治疗池必须是整数')
            total,schedule=heal_schedule(int(p['power']),current,maximum,p['vial'],p['healing_percent']/100,p['healing_flat'],apply_vial=False)
            rows=[metric('剩余治疗池',total,'HP'),metric('最终实际恢复',min(maximum-current,total),'HP'),metric('首次恢复',schedule[0][2] if schedule else 0,'HP'),metric('治疗池耗尽',len(schedule),'回合')]
            result.append(block('当前治疗状态',rows,'按手填来源参数计算，不再次放大剩余额度；默认速度仅是治疗药剂示例。治疗过程中再次受伤会改变实际恢复。'))
            result.append(table('常见治疗速度',['来源','占剩余额度%','额外固定HP/次'],[['治疗药剂/蜂蜜治疗合剂',25,0],['护符返回首领层',0,20]],'已有治疗状态相遇时，分别保留较大的治疗池、百分比和固定治疗值；试管限速按当前来源核对。'))
            result.append(table('每回合恢复明细',['恢复次数','本次治疗池消耗','实际恢复HP','治疗后生命','剩余治疗池'],schedule))
        if identity=='items.potions.exotic.potionofshielding':
            requested.update(('max_hp','hero_level'))
            result.append(block('按你的最大生命计算',[metric('获得护盾',math.floor(.6*maximum+10),'HP'),metric('药水恐惧挑战毒强度',4+hero//2,'点','挑战开启时替代护盾')]))
        if identity=='items.potions.elixirs.elixirofaquaticrejuvenation':
            requested.add('max_hp');result.append(block('水灵治疗',[metric('治疗池',rounded(maximum*1.5),'HP','只在水中生效')]))
        if identity=='items.potions.elixirs.elixirofarcanearmor':
            requested.add('hero_level');result.append(block('魔法减伤',[metric('随机魔法减伤',f'0–{5+hero//2}','HP'),metric('持续',80,'回合')]))
        if identity=='items.potions.exotic.potionofearthenarmor':
            requested.add('hero_level');result.append(block('树肤减伤',[metric('初始物理减伤',f'0–{2+hero//3}','HP'),metric('衰减间隔',50,'回合','每次减1点')]))
        if identity=='items.potions.exotic.potionofcorrosivegas':
            requested.add('depth');result.append(block('本层酸雾强度',[metric('起始酸蚀强度',2+depth//5,'点','持续接触会递增')]))
        if identity in ('plants.sungrass','plants.sungrass$health'):
            requested.add('max_hp');result.append(block('草药疗养',[metric('总治疗额度',maximum,'HP','普通职业离开原地会中断；守望者可带走')]))
        if identity in ('plants.earthroot','plants.earthroot$armor'):
            requested.update(('max_hp','hero_level'));result.append(block('植被护甲',[metric('普通目标总护甲额度',maximum,'HP','离开原地失效'),metric('守望者树肤减伤',f'0–{hero+5}','HP'),metric('守望者树肤衰减间隔',5,'回合')]))
        if identity=='plants.sorrowmoss':
            requested.add('depth');result.append(block('中毒',[metric('起始毒强度',5+rounded(2*depth/3),'点')]))
        if identity=='items.scrolls.scrollofretribution':
            requested.update(('max_hp','hp','target_hp','target_max_hp'))
            power=min(4,4.45*(maximum-current)/maximum)
            amount=rounded(p['target_max_hp']/10+p['target_hp']*power*.225)
            result.append(block('当前伤势下的效果',[metric('单个目标伤害',amount,'HP','未计目标抗性'),metric('自身失明',self.duration('Blindness'),'回合'),metric('自身虚弱',self.duration('Weakness'),'回合')]))
        if identity=='items.scrolls.exotic.scrollofpsionicblast':
            requested.update(('max_hp','target_hp','target_max_hp','targets'))
            result.append(block('灵爆伤害',[metric('单个目标伤害',rounded((p['target_max_hp']+p['target_hp'])/2),'HP'),metric('自身伤害',rounded(maximum*.5*.9**p['targets']),'HP',f'{p["targets"]}个目标；未计抗性'),metric('自身失明',self.duration('Blindness'),'回合'),metric('自身虚弱',5*self.duration('Weakness'),'回合')]))
        if identity.startswith('items.trinkets.') and identity.rsplit('.',1)[-1] in TRINKETS:
            name=identity.rsplit('.',1)[-1];effects=TRINKETS[name];columns=['饰物等级']+[label+'（'+unit+'）' for label,_,unit in effects];rows=[]
            for l in range(4):
                row=[f'{l:+d}']
                for _,formula,_ in effects:
                    value=formula[l] if isinstance(formula,list) else Formula({'L':l}).evaluate(formula)
                    row.append(display(value))
                rows.append(row)
            result.append(table('饰物升级对照',columns,rows,'概率超过100%时，100%部分保证一次，剩余部分用于额外次数。'))
            if name=='vialofblood':
                requested.add('max_hp');result.append(table('治疗速度上限',['饰物等级','每回合最多恢复HP'],[[f'{l:+d}',[4+rounded(.15*maximum),3+rounded(.1*maximum),2+rounded(.07*maximum),1+rounded(.05*maximum)][l]] for l in range(4)],f'最大生命 {maximum}'))
        if identity.startswith('actors.hero.heroclass.'):
            requested.add('hero_level');result.append(block('角色基础数值',[metric('初始生命',20,'HP'),metric('初始力量',10,'点'),metric('当前等级基础最大生命',20+5*(hero-1),'HP'),metric('升到下一等级所需经验',5+5*hero,'经验','30级后不再升级'),metric('最高角色等级',30,'级')]))
        if identity=='mechanics.accuracy':
            requested.update(('accuracy','evasion'));a,d=p['accuracy'],p['evasion']
            probability=1 if d==0 else (0 if a==0 else 1-d/(2*a) if a>=d else a/(2*d))
            result.append(block('命中概率',[metric('本次攻击命中',probability*100,'%','普通物理攻击；不含伏击、祝福、无限命中/闪避')]))
        if identity in ('mechanics.strength','mechanics.armor'):
            requested.update(('tier','level'));t=p['tier'];l=level;strength=8+2*t-math.floor((math.sqrt(8*l+1)-1)/2)
            result.append(block('当前装备结果',[metric('普通力量需求',strength,'点'),metric('精通后需求',strength-2,'点'),metric('普通护甲减伤',f'{l}–{t*(2+l)}','HP'),metric('信念护体减伤',f'0–{1+t+l}','HP')]))
            result.append(table('降低力量需求的升级节点',['装备等级','需求降低'],[[0,0],[1,1],[3,2],[6,3],[10,4],[15,5],[21,6]]))
