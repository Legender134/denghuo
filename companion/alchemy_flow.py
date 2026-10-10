"""Target alchemy and one shared, simulated ledger for SPD 4.0.2.

Recipe semantics are ported from the pinned Shattered Pixel Dungeon sources,
GPL-3.0-or-later (Oleg Dolya 2012-2015; Evan Debenham 2014-2026).
No save data is read here and no game action is performed.
"""
from collections import Counter
import copy
import math
import re

from .alchemy import COMMIT, JAVA_ROOT, MAX_INT, POTIONS, SCROLLS, VERSION, VERSION_CODE, integer, item_id, recipe_list
from .game_math import float32 as f
from .public_source_data import MISSILE_PUBLIC_TYPES
from .public_talents import MAXIMUM as TALENT_MAXIMUM

SEEDS = dict(zip(
    ('blindweed', 'mageroyal', 'earthroot', 'fadeleaf', 'firebloom', 'icecap',
     'rotberry', 'sorrowmoss', 'starflower', 'stormvine', 'sungrass', 'swiftthistle'),
    ('Invisibility', 'Purity', 'ParalyticGas', 'MindVision', 'LiquidFlame', 'Frost',
     'Strength', 'ToxicGas', 'Experience', 'Levitation', 'Healing', 'Haste')))
SEED_POTIONS = {'plants.' + plant + '$seed': item_id('potions/PotionOf' + potion) for plant, potion in SEEDS.items()}
DEFAULT_POTION_WEIGHTS = (0, 6, 4, 3, 3, 3, 2, 2, 2, 2, 2, 1)
# Concrete inventory classes, not all translated entries below these namespaces.
# WAND.classes in Generator.java; Dart plus TippedDart.types at the pinned commit.
WAND_TYPES = ('WandOfMagicMissile', 'WandOfLightning', 'WandOfDisintegration', 'WandOfFireblast',
              'WandOfCorrosion', 'WandOfBlastWave', 'WandOfLivingEarth', 'WandOfFrost',
              'WandOfPrismaticLight', 'WandOfWarding', 'WandOfTransfusion', 'WandOfCorruption', 'WandOfRegrowth')
DART_TYPES = ('Dart', 'RotDart', 'HealingDart', 'DisplacingDart', 'ChillingDart', 'IncendiaryDart',
              'PoisonDart', 'AdrenalineDart', 'BlindingDart', 'ShockingDart', 'ParalyticDart', 'CleansingDart', 'HolyDart')
NON_INVENTORY_IDS = {item_id('wands/' + name) for name in (
    'Wand', 'DamageWand', 'CursedWand', 'WandOfLightning$LightningCharge', 'WandOfLivingEarth$EarthGuardian',
    'WandOfLivingEarth$RockArmor', 'WandOfMagicMissile$MagicCharge', 'WandOfRegrowth$Dewcatcher',
    'WandOfRegrowth$Lotus', 'WandOfRegrowth$Seedpod')}
NON_INVENTORY_IDS |= {item_id(path) for path in ('weapon/missiles/MissileWeapon', 'weapon/missiles/Boomerang',
    'weapon/missiles/Shuriken$ShurikenInstantTracker', 'weapon/missiles/darts/TippedDart',
    'stones/Runestone', 'stones/InventoryStone', 'trinkets/Trinket', 'potions/Potion')}
BOMBS = (
    ('potions/PotionOfFrost', 'FrostBomb', 0), ('scrolls/ScrollOfMirrorImage', 'WoollyBomb', 0),
    ('potions/PotionOfLiquidFlame', 'Firebomb', 1), ('scrolls/ScrollOfRage', 'Noisemaker', 1),
    ('potions/PotionOfInvisibility', 'SmokeBomb', 2), ('scrolls/ScrollOfRecharging', 'FlashBangBomb', 2),
    ('potions/PotionOfHealing', 'RegrowthBomb', 3), ('scrolls/ScrollOfRemoveCurse', 'HolyBomb', 3),
    ('quest/GooBlob', 'ArcaneBomb', 6), ('quest/MetalShard', 'ShrapnelBomb', 6))
TRINKETS = ('RatSkull', 'ParchmentScrap', 'PetrifiedSeed', 'ExoticCrystals', 'MossyClump',
            'DimensionalSundial', 'ThirteenLeafClover', 'TrapMechanism', 'MimicTooth',
            'WondrousResin', 'EyeOfNewt', 'SaltCube', 'VialOfBlood', 'ShardOfOblivion',
            'ChaoticCenser', 'FerretTuft', 'CrackedSpyglass')
DYNAMIC = (
    ('resin', '法杖提炼奥术树脂', 'ArcaneResin.Recipe', 'ArcaneResin', 'whole'),
    ('liquid-metal', '整堆投掷武器熔炼', 'LiquidMetal.Recipe', 'LiquidMetal', 'whole'),
    ('trinket-catalyst', '魔能触媒四选', 'TrinketCatalyst.Recipe', 'trinkets/TrinketCatalyst', 'choice'),
    ('trinket-upgrade', '饰物逐级升级', 'Trinket.UpgradeTrinket', 'trinkets/Trinket', 'upgrade'),
    ('cook-fruit', '烹煮无味果', 'Blandfruit.CookFruit', 'food/Blandfruit', 'stack'),
    ('enhance-bomb', '强化炸弹', 'Bomb.EnhanceBomb', 'bombs/Bomb', 'stack'),
    ('unstable-brew', '不稳定酿剂', 'UnstableBrew.Recipe', 'potions/brews/UnstableBrew', 'stack'),
    ('unstable-spell', '不稳定晶核', 'UnstableSpell.Recipe', 'spells/UnstableSpell', 'stack'),
    ('alchemize', '炼金菱晶', 'Alchemize.Recipe', 'spells/Alchemize', 'stack'),
    ('seed-potion', '三种子酿药', 'Potion.SeedToPotion', 'potions/Potion', 'random'),
    ('meat-pie', '肉馅饼', 'MeatPie.Recipe', 'food/MeatPie', 'stack'),
    ('cook-meat', '炖肉（自动组合批次）', 'StewedMeat.oneMeat', 'food/StewedMeat', 'cooking'))
IDENTITY = re.compile(r'(?:items|plants)\.[a-z0-9_.$-]{1,290}\Z')
KEY = re.compile(r'[a-zA-Z0-9_.:-]{1,100}\Z')
STATE_KEYS = {'cooked', 'potion_id', 'cursed', 'is_upgradable', 'base_level', 'public_level',
              'resin_bonus', 'hero_class', 'wand_preservation', 'level', 'tier',
              'default_quantity', 'durability', 'catalyst_stage', 'rolled_choices'}
CHOICE_KEYS = {'source_key', 'source_keys', 'selection', 'target_level', 'seed_id', 'seed_ids',
               'ingredient_id', 'potion_id', 'scroll_id', 'stone_id', 'pasty_id', 'meat_id'}


def identifier(value):
    if not isinstance(value, str) or not IDENTITY.fullmatch(value):
        raise ValueError('材料需要标准物品或植物种子身份，未知身份不能猜测')
    return value


def key(value):
    if not isinstance(value, str) or not KEY.fullmatch(value):
        raise ValueError('目标或库存实例标识不正确')
    return value


def choices(raw):
    if not isinstance(raw, dict) or set(raw) - CHOICE_KEYS:
        raise ValueError('配方选择格式不正确')
    for name, value in raw.items():
        if name in ('selection', 'target_level'):
            if value is not None and (type(value) is not int or not 0 <= value <= 3):
                raise ValueError('饰物选择或目标等级需要0–3的整数')
        elif name in ('source_keys', 'seed_ids'):
            if not isinstance(value, list) or not 1 <= len(value) <= 64:
                raise ValueError('材料选择列表不正确')
            for entry in value:
                (key if name == 'source_keys' else identifier)(entry)
            if name == 'source_keys' and len(set(value)) != len(value):
                raise ValueError('同一原始堆或物品不能重复选择')
        else:
            (key if name == 'source_key' else identifier)(value)
    if 'source_key' in raw and 'source_keys' in raw:
        raise ValueError('请使用单个实例或实例列表，不能重复登记')
    return copy.deepcopy(raw)


def validate_plan(raw):
    """Persistence validation deliberately does not depend on current recipes."""
    required = {'format', 'recipe_version', 'targets', 'resources', 'energy',
                'energy_reserve', 'energy_origin', 'reference_version', 'chains'}
    if not isinstance(raw, dict) or set(raw) != required or type(raw['format']) is not int or raw['format'] != 2:
        raise ValueError('目标炼金方案格式不正确')
    if not isinstance(raw['recipe_version'], str) or not re.fullmatch(r'[0-9.]{1,40}', raw['recipe_version']):
        raise ValueError('炼金规则版本不正确')
    for name in ('energy', 'energy_reserve'):
        integer(raw[name], '炼金能量')
    if raw['energy_reserve'] > raw['energy'] or raw['energy_origin'] not in ('known', 'manual'):
        raise ValueError('能量来源或最低保留量不正确')
    if raw['reference_version'] is not None:
        integer(raw['reference_version'], '参考版本')
    if not isinstance(raw['targets'], list) or not 1 <= len(raw['targets']) <= 64:
        raise ValueError('目标列表需要1–64项')
    seen = set()
    for target in raw['targets']:
        if not isinstance(target, dict) or set(target) != {'key', 'recipe', 'quantity', 'choices'}:
            raise ValueError('炼金目标格式不正确')
        key(target['key'])
        if target['key'] in seen:
            raise ValueError('目标标识重复')
        seen.add(target['key'])
        if not isinstance(target['recipe'], str) or not re.fullmatch(r'[a-z0-9-]{1,100}', target['recipe']):
            raise ValueError('炼金配方身份不正确')
        integer(target['quantity'], '目标产出数量')
        choices(target['choices'])
    if not isinstance(raw['resources'], list) or len(raw['resources']) > 256:
        raise ValueError('库存实例最多256项')
    seen = set()
    for row in raw['resources']:
        if not isinstance(row, dict) or set(row) != {'key', 'id', 'quantity', 'reserve', 'origin', 'state'}:
            raise ValueError('库存实例格式不正确')
        key(row['key']); identifier(row['id'])
        if row['key'] in seen:
            raise ValueError('同一库存实例不能重复使用')
        seen.add(row['key'])
        integer(row['quantity'], '库存数量'); integer(row['reserve'], '保留数量')
        if row['reserve'] > row['quantity'] or row['origin'] not in ('known', 'manual'):
            raise ValueError('材料来源或最低保留量不正确')
        state = row['state']
        if not isinstance(state, dict) or set(state) - STATE_KEYS:
            raise ValueError('物品状态字段不正确')
        for name, value in state.items():
            if value is None:
                continue
            if name in ('cursed', 'is_upgradable'):
                if type(value) is not bool: raise ValueError('诅咒或升级资格需要明确状态')
            elif name == 'cooked':
                if value not in ('raw', 'cooked', 'unknown'): raise ValueError('生熟状态不正确')
            elif name == 'catalyst_stage':
                if value not in ('unrolled', 'awaiting_choice'): raise ValueError('触媒选择阶段不正确')
            elif name == 'hero_class':
                if value not in ('WARRIOR', 'MAGE', 'ROGUE', 'HUNTRESS', 'DUELIST', 'CLERIC'):
                    raise ValueError('角色职业不正确')
            elif name == 'rolled_choices':
                if not isinstance(value, list) or len(value) != 4: raise ValueError('触媒需保留完整四选项')
                for item in value: identifier(item)
            elif name == 'potion_id':
                identifier(value)
            elif name == 'durability':
                if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100:
                    raise ValueError('精确耐久假设需要0–100的有限数值')
                if row['origin'] != 'manual':
                    raise ValueError('精确耐久不能从隐藏存档字段标为已知，请明确手填假设')
            elif name in ('level', 'base_level', 'public_level'):
                if type(value) is not int or not -MAX_INT - 1 <= value <= MAX_INT:
                    raise ValueError('物品等级需为Java有符号整数；未知等级请留空')
            else:
                integer(value, '物品状态数值')
    if not isinstance(raw['chains'], dict) or len(raw['chains']) > 256:
        raise ValueError('前置配方选择不正确')
    for output, selection in raw['chains'].items():
        identifier(output)
        if (not isinstance(selection, dict) or set(selection) != {'recipe', 'choices'}
                or not isinstance(selection['recipe'], str) or not re.fullmatch(r'[a-z0-9-]{1,100}', selection['recipe'])):
            raise ValueError('前置配方选择不正确')
        choices(selection['choices'])
    return copy.deepcopy(raw)


def resource_catalog(catalog):
    ids = {row['id']: row for row in catalog.entries}
    fixed = recipe_list(catalog)
    relevant = {row['output'] for row in fixed} | {i['id'] for row in fixed for i in row['inputs']} | set(SEED_POTIONS)
    relevant |= {item_id('bombs/' + out) for _, out, _ in BOMBS} | {item_id(i) for i, _, _ in BOMBS}
    relevant |= {item_id('food/' + name) for name in ('Blandfruit', 'Food', 'Pasty', 'PhantomMeat', 'MysteryMeat', 'StewedMeat', 'ChargrilledMeat', 'FrozenCarpaccio', 'MeatPie')}
    relevant |= {item_id('trinkets/' + name) for name in TRINKETS}
    relevant |= {item_id(path) for recipe, _, _, path, _ in DYNAMIC if recipe not in ('seed-potion', 'trinket-upgrade')}
    wands = [item_id('wands/' + name) for name in WAND_TYPES]
    missiles = sorted(MISSILE_PUBLIC_TYPES)
    darts = [item_id('weapon/missiles/darts/' + name) for name in DART_TYPES]
    stones = [item_id('stones/StoneOf' + c) for _, _, c in SCROLLS]
    relevant |= set(wands) | set(missiles) | set(darts) | set(stones)
    groups = {
        'seeds': list(SEED_POTIONS),
        'potions': [item_id('potions/PotionOf' + a) for a, _ in POTIONS] + [item_id('potions/exotic/PotionOf' + b) for _, b in POTIONS],
        'scrolls': [item_id('scrolls/ScrollOf' + a) for a, _, _ in SCROLLS] + [item_id('scrolls/exotic/ScrollOf' + b) for _, b, _ in SCROLLS],
        'stones': [item_id('stones/StoneOf' + c) for _, _, c in SCROLLS],
        'trinkets': [item_id('trinkets/' + name) for name in TRINKETS],
        'catalyst': [item_id('trinkets/TrinketCatalyst')],
        'missiles': missiles, 'darts': darts, 'wands': wands,
        'bomb_ingredients': [item_id(i) for i, _, _ in BOMBS],
        'pie_pasty': [item_id('food/' + i) for i in ('Pasty', 'PhantomMeat')],
        'pie_meat': [item_id('food/' + i) for i in ('MysteryMeat', 'StewedMeat', 'ChargrilledMeat', 'FrozenCarpaccio')]}
    def kind(identity):
        for name in ('seeds', 'trinkets', 'catalyst', 'missiles', 'darts', 'wands'):
            if identity in groups[name]: return name
        return 'stack'
    state_fields = {'seeds': [], 'trinkets': ['level'], 'catalyst': ['catalyst_stage', 'rolled_choices'],
                    'wands': ['cursed', 'base_level', 'public_level', 'resin_bonus', 'hero_class', 'wand_preservation'],
                    'missiles': ['cursed', 'is_upgradable', 'level', 'tier', 'default_quantity', 'durability']}
    state_fields['darts'] = state_fields['missiles']
    return {**groups, 'known_names': {i: row['name'] for i, row in ids.items()
                                     if i.startswith(('items.', 'plants.')) and isinstance(row.get('name'), str) and row['name']},
            'items': [{'id': i, 'name': ids[i]['name'], 'kind': kind(i),
                                'state_fields': state_fields.get(kind(i), ['cooked', 'potion_id'] if i == item_id('food/Blandfruit') else [])}
                               for i in sorted(relevant) if i in ids]}


def family_list(catalog):
    fixed = recipe_list(catalog)
    resources = resource_catalog(catalog)
    fields = {
        'resin': [('source_keys', 'instance-list', 'wands')], 'liquid-metal': [('source_keys', 'instance-list', 'missiles')],
        'trinket-catalyst': [('source_key', 'instance', 'catalyst'), ('selection', 'selection', None)],
        'trinket-upgrade': [('source_key', 'instance', 'trinkets'), ('target_level', 'level', None)],
        'cook-fruit': [('seed_id', 'item', 'seeds')], 'enhance-bomb': [('ingredient_id', 'item', 'bomb_ingredients')],
        'unstable-brew': [('potion_id', 'item', 'potions'), ('seed_id', 'item', 'seeds')],
        'unstable-spell': [('scroll_id', 'item', 'scrolls'), ('stone_id', 'item', 'stones')],
        'alchemize': [('seed_id', 'item', 'seeds'), ('stone_id', 'item', 'stones')],
        'seed-potion': [('seed_ids', 'three-items', 'seeds')],
        'meat-pie': [('pasty_id', 'item', 'pie_pasty'), ('meat_id', 'item', 'pie_meat')], 'cook-meat': []}
    sources = {r['family']: r['source'] for r in catalog.data.get('alchemy_families', [])}
    rows = [{**copy.deepcopy(row), 'mode': 'stack', 'choices': [], 'possible_outputs': [row['output']]} for row in fixed]
    for identity, name, family, path, mode in DYNAMIC:
        energy_cost = {'resin': 5, 'liquid-metal': 3, 'trinket-catalyst': 6, 'cook-fruit': 2,
                       'unstable-brew': 1, 'unstable-spell': 1, 'alchemize': 2, 'seed-potion': 0,
                       'meat-pie': 6}.get(identity)
        requirements = {
            'resin': ['一根已知无诅咒法杖；产量还需公开基础等级和职业/天赋'],
            'liquid-metal': ['一原始可升级且已知无诅咒投掷武器整堆；精确耐久需明确手填'],
            'trinket-catalyst': ['一魔能触媒；首次6能量，已付费待四选不再付费'],
            'trinket-upgrade': ['一件明确饰物；初始与目标等级；逐级独立成本'],
            'cook-fruit': ['一个未熟无味果', '一粒明确种子'],
            'enhance-bomb': ['一个普通炸弹', '一个明确增强材料'],
            'unstable-brew': ['一瓶普通或合剂药剂', '一粒明确种子'],
            'unstable-spell': ['一张普通或秘卷卷轴', '一颗明确符石'],
            'alchemize': ['一粒明确种子', '一颗明确符石'],
            'seed-potion': ['三个种子槽各消耗一粒，可选同种；产出身份可能随机'],
            'meat-pie': ['一个肉馅饼或幻影鱼肉', '一个口粮', '一份明确肉类'],
            'cook-meat': ['生肉按目标件数消耗；一/二/三肉批次自动组合']}[identity]
        rows.append({'id': identity, 'name': name, 'family': family, 'mode': mode,
                     'choices': [{'key': k, 'type': t, 'group': group, 'allowed': resources.get(group, [])} for k, t, group in fields[identity]],
                     'energy_cost': energy_cost, 'requirements': requirements,
                     'output_quantity': 8 if identity == 'alchemize' else (None if mode in ('whole', 'upgrade', 'cooking') else 1),
                     'possible_outputs': (resources['trinkets'] if identity in ('trinket-catalyst', 'trinket-upgrade') else
                                          [item_id('bombs/' + out) for _, out, _ in BOMBS] if identity == 'enhance-bomb' else
                                          list(SEED_POTIONS.values()) if identity == 'seed-potion' else
                                          [item_id(path)]),
                     'source': copy.deepcopy(sources.get(family, {})), 'path': JAVA_ROOT + 'items/' + path + '.java'})
    return rows


class Need(Exception):
    def __init__(self, identity, required, available, reason, condition=False, **extra):
        self.detail = {'id': identity, 'required': required, 'available': available,
                       'missing': max(0, required - available), 'reason': reason, 'condition': condition, **extra}


def metal_quantity(quantity, tier, default_quantity, level, durability):
    """Mirror float compound assignments and Java Math.round(float)."""
    per = f(5 * (tier + 1))
    if default_quantity != 3:
        per = f(f(3) / default_quantity)
    per = f(per * math.pow(f(1.35), min(5, level)))
    equivalent = f(quantity - 1)
    equivalent = f(equivalent + f(f(.25) + f(f(.0075) * f(durability))))
    product = f(equivalent * per)
    return min(MAX_INT, max(-MAX_INT - 1, math.floor(product + .5)))


class Ledger:
    def __init__(self, catalog, args, values=None):
        self.catalog, self.args, self.values = catalog, args, values
        self.rows = copy.deepcopy(args['resources'])
        self.energy = args['energy']
        self.steps, self.outputs, self.pending, self.boundaries = [], [], [], []
        self.fixed = {row['id']: row for row in recipe_list(catalog)}
        self.producers = {}
        for row in self.fixed.values():
            self.producers.setdefault(row['output'], []).append({'recipe': row['id'], 'choices': {}})
        self.producers[item_id('food/StewedMeat')] = [{'recipe': 'cook-meat', 'choices': {}}]
        for ingredient, output, _ in BOMBS:
            self.producers[item_id('bombs/' + output)] = [{'recipe': 'enhance-bomb', 'choices': {'ingredient_id': item_id(ingredient)}}]
        # Alternative materials stay explicit; never silently spend a valuable potion.
        groups = resource_catalog(catalog)
        for recipe, output, fields in (
                ('alchemize', 'spells/Alchemize', (('seed_id', 'seeds'), ('stone_id', 'stones'))),
                ('unstable-brew', 'potions/brews/UnstableBrew', (('potion_id', 'potions'), ('seed_id', 'seeds'))),
                ('unstable-spell', 'spells/UnstableSpell', (('scroll_id', 'scrolls'), ('stone_id', 'stones'))),
                ('meat-pie', 'food/MeatPie', (('pasty_id', 'pie_pasty'), ('meat_id', 'pie_meat')))):
            self.producers[item_id(output)] = [
                {'recipe': recipe, 'choices': {fields[0][0]: a, fields[1][0]: b}}
                for a in groups[fields[0][1]] for b in groups[fields[1][1]]]
        for seed, potion in SEED_POTIONS.items():
            if seed != 'plants.sungrass$seed':
                self.producers.setdefault(potion, []).append({'recipe': 'seed-potion', 'choices': {'seed_ids': [seed] * 3}})
        for recipe, output, prefix in (('resin', 'ArcaneResin', 'items.wands.'),
                                       ('liquid-metal', 'LiquidMetal', 'items.weapon.missiles.')):
            self.producers[item_id(output)] = [{'recipe': recipe, 'choices': {'source_keys': [r['key']]}}
                                              for r in self.rows if r['id'].startswith(prefix)]
        self.spent = Counter()
        self.visiting = []
        self.target = None

    def clone(self):
        result = copy.copy(self)
        for name in ('rows', 'steps', 'outputs', 'pending', 'boundaries', 'spent', 'visiting'):
            setattr(result, name, copy.deepcopy(getattr(self, name)))
        return result

    def selected(self, selection, prefix=None):
        keys = selection.get('source_keys', [selection['source_key']] if 'source_key' in selection else [])
        if not keys:
            raise Need(prefix or 'item', 1, 0, '请选择具体库存实例', True)
        rows = []
        for stock_key in keys:
            row = next((r for r in self.rows if r['key'] == stock_key and r['quantity'] > 0), None)
            if row is None:
                raise Need(stock_key, 1, 0, '所选实例不存在或已被其他目标消耗')
            if prefix and not row['id'].startswith(prefix):
                raise ValueError('所选实例不属于此配方材料')
            rows.append(row)
        return rows

    def choice(self, selection, name, allowed):
        if name not in selection:
            raise Need(name, 1, 0, '请选择具体材料：' + name, True)
        value = selection[name]
        if value not in allowed:
            raise ValueError('配方所选材料不合格：' + name)
        return value

    def spec(self, recipe, selection, quantity):
        if recipe in self.fixed:
            if selection: raise ValueError('固定配方不使用动态选择')
            row = self.fixed[recipe]
            return {'inputs': copy.deepcopy(row['inputs']), 'output': row['output'], 'yield': row['quantity'],
                    'cost': row['cost'], 'state': {}, 'source': row['source']}
        meta = next((r for r in DYNAMIC if r[0] == recipe), None)
        if meta is None: raise ValueError('此配方尚未收录；固定条件仍可保存和导出')
        expected = {field['key'] for row in family_list(self.catalog) if row['id'] == recipe for field in row['choices']}
        if set(selection) - expected - ({'source_key'} if 'source_keys' in expected else set()):
            raise ValueError('此配方不使用这些动态选择')
        spec = {'inputs': [], 'output': item_id(meta[3]), 'yield': 1, 'cost': 0, 'state': {},
                'source': next((r['source'] for r in self.catalog.data.get('alchemy_families', []) if r['family'] == meta[2]), {})}
        groups = resource_catalog(self.catalog)
        def inp(identity, amount=1, **extra):
            spec['inputs'].append({'id': identity, 'quantity': amount, **extra})
        if recipe in ('resin', 'liquid-metal'):
            rows = self.selected(selection, 'items.wands.' if recipe == 'resin' else 'items.weapon.missiles.')
            produced, unresolved, bounds = 0, [], [0, 0]
            spec.update(cost=(5 if recipe == 'resin' else 3) * len(rows), once=True)
            for row in rows:
                state = row['state']
                if state.get('cursed') is True: raise ValueError('诅咒物品不能用于此配方')
                if state.get('cursed') is not False: unresolved.append(row['key'] + ':诅咒状态')
                if recipe == 'liquid-metal':
                    if row['id'].startswith('items.weapon.missiles.darts.'):
                        raise ValueError('飞镖及涂药飞镖在固定版本不可升级，不能熔炼')
                    if row['id'] in MISSILE_PUBLIC_TYPES:
                        state = copy.deepcopy(state)
                        for name, expected in zip(('tier', 'default_quantity'), MISSILE_PUBLIC_TYPES[row['id']]):
                            if state.get(name) is not None and state[name] != expected:
                                raise ValueError('投掷武器阶数或默认堆数量与此固定种类不符')
                            state[name] = expected
                        if state.get('is_upgradable') is None: state['is_upgradable'] = True
                    if state.get('is_upgradable') is False: raise ValueError('不可升级投掷武器不能熔炼')
                    if state.get('tier') is not None and not 1 <= state['tier'] <= 5:
                        raise ValueError('投掷武器阶数不正确')
                    if state.get('default_quantity') is not None and state['default_quantity'] <= 0:
                        raise ValueError('投掷武器默认堆数量不正确')
                    names = ('level', 'tier', 'default_quantity', 'durability', 'is_upgradable')
                    if any(state.get(n) is None for n in names):
                        unresolved.extend(row['key'] + ':' + n for n in names if state.get(n) is None)
                    else:
                        produced += metal_quantity(row['quantity'], state['tier'], state['default_quantity'], state['level'], state['durability'])
                else:
                    if row['quantity'] != 1:
                        raise ValueError('每根法杖需作为独立实例登记，数量为1')
                    base, public, bonus = state.get('base_level'), state.get('public_level'), state.get('resin_bonus')
                    if base is None and public is not None and bonus is not None: base = public - bonus
                    if base is None: unresolved.append(row['key'] + ':基础等级或公开等级/树脂加成')
                    if public is not None and bonus is not None and base is not None and public != base + bonus:
                        raise ValueError('无诅咒法杖基础等级、公开等级和树脂加成不一致')
                    hero, preservation = state.get('hero_class'), state.get('wand_preservation')
                    if hero is None: unresolved.append(row['key'] + ':职业')
                    if hero != 'MAGE' and preservation is None: unresolved.append(row['key'] + ':法杖保存天赋')
                    if base is not None:
                        produced += 2 * (base + 1) + (preservation or 0 if hero != 'MAGE' else 0)
                if recipe == 'liquid-metal' and all(state.get(n) is not None for n in ('level', 'tier', 'default_quantity')):
                    for index, durability in enumerate((0, 100)):
                        bounds[index] += metal_quantity(row['quantity'], state['tier'], state['default_quantity'], state['level'], durability)
                inp(row['id'], row['quantity'], key=row['key'], whole=True)
            spec['yield'] = None if unresolved else produced
            if recipe == 'liquid-metal' and unresolved and all(r['state'].get('level') is not None and
                    (r['id'] in MISSILE_PUBLIC_TYPES or all(r['state'].get(n) is not None for n in ('tier', 'default_quantity'))) for r in rows):
                spec['yield_bounds'] = {'minimum': bounds[0], 'maximum': bounds[1], 'condition': '仅耐久0–100边界；资格仍需确认'}
            spec['pending'] = unresolved
            spec['boundary'] = '确定消耗所选原始物品与能量；未确认条件不会推测产量' if unresolved else ''
        elif recipe == 'trinket-upgrade':
            row = self.selected(selection, 'items.trinkets.')[0]
            if quantity != 1: raise ValueError('饰物升级目标是一件特定饰物，数量需为1')
            if row['id'] == item_id('trinkets/TrinketCatalyst'):
                candidates = [(identity, chain) for identity, chain in self.args['chains'].items()
                              if identity in groups['trinkets'] and chain['recipe'] == 'trinket-catalyst'
                              and chain['choices'].get('source_key') == row['key']]
                if len(candidates) != 1:
                    raise Need(row['id'], 1, 0, '触媒升级需在前置选择中指定一个已显示的饰物选项', True)
                identity, chain = candidates[0]
                output_key, _ = self.craft(chain['recipe'], chain['choices'], 1, expected=identity)
                row = next(r for r in self.rows if r['key'] == output_key)
            if row['id'] not in groups['trinkets']: raise ValueError('占位或随机饰物不能作为已确定的升级对象')
            if row['quantity'] != 1: raise ValueError('每件饰物需作为独立实例登记，数量为1')
            level, goal = row['state'].get('level'), selection.get('target_level')
            inp(row['id'], 1, key=row['key'], whole=True)
            spec.update(output=row['id'], once=True, state=copy.deepcopy(row['state']))
            if level is None or goal is None:
                spec.update({'yield': None, 'cost': None, 'pending': ['初始等级与目标等级'], 'boundary': '每次只提升一级，按具体饰物逐级收费'})
            else:
                if not 0 <= level < goal <= 3: raise ValueError('饰物目标需高于当前等级且不超过3级；已达目标无需再升级')
                if self.values is None:
                    from .rules import NumericRules
                    from .values import PlayerValues
                    self.values = PlayerValues(NumericRules(self.catalog))
                costs = [self.values.pure_value('com.shatteredpixel.shatteredpixeldungeon.' + row['id'], 'upgradeEnergyCost', level=l) for l in range(level, goal)]
                spec.update(cost=sum(costs), upgrade_costs=costs, starting_level=level)
                spec['state']['level'] = goal
        elif recipe == 'trinket-catalyst':
            row = self.selected(selection)[0]
            if row['id'] != item_id('trinkets/TrinketCatalyst'): raise ValueError('请选择魔能触媒实例')
            if row['quantity'] != 1: raise ValueError('每个触媒需作为独立实例登记，数量为1')
            state = row['state']
            stage, options = state.get('catalyst_stage'), state.get('rolled_choices')
            if options and any(o not in groups['trinkets'] + [item_id('trinkets/TrinketCatalyst$RandomTrinket')] for o in options):
                raise ValueError('触媒四选项需为合法饰物或随机占位')
            if stage == 'unrolled' and options:
                raise ValueError('未付费触媒不能附带已生成四选项')
            spec.update(once=True, output=None, cost=0 if stage == 'awaiting_choice' else 6)
            inp(row['id'], 1, key=row['key'], whole=True)
            choice = selection.get('selection')
            if stage == 'awaiting_choice' and options and choice is not None:
                selected = options[choice]
                if selected in groups['trinkets']:
                    spec.update(output=selected, state={'level': 0, 'cursed': False})
                elif selected != item_id('trinkets/TrinketCatalyst$RandomTrinket'):
                    raise ValueError('触媒选项不是固定版本的饰物或随机占位')
            if spec['output'] is None:
                spec['boundary'] = '已有四选请明确选择；未生成选项或随机选项不能保证饰物身份'
            if stage == 'awaiting_choice' and not options:
                spec['pending'] = ['已付费触媒的四选项尚未确认']
            if stage is None:
                spec['pending'] = ['触媒是否已付费并进入四选状态']
                spec['cost'] = None
        elif recipe == 'cook-fruit':
            seed = self.choice(selection, 'seed_id', groups['seeds'])
            inp(item_id('food/Blandfruit'), cooked='raw'); inp(seed)
            spec.update(cost=2, state={'cooked': 'cooked', 'potion_id': SEED_POTIONS[seed]})
        elif recipe == 'enhance-bomb':
            ingredient = self.choice(selection, 'ingredient_id', groups['bomb_ingredients'])
            _, output, cost = next(row for row in BOMBS if item_id(row[0]) == ingredient)
            inp(item_id('bombs/Bomb')); inp(ingredient)
            spec.update(output=item_id('bombs/' + output), cost=cost)
        elif recipe in ('unstable-brew', 'unstable-spell', 'alchemize'):
            pairs = {'unstable-brew': [('potion_id', 'potions'), ('seed_id', 'seeds')],
                     'unstable-spell': [('scroll_id', 'scrolls'), ('stone_id', 'stones')],
                     'alchemize': [('seed_id', 'seeds'), ('stone_id', 'stones')]}[recipe]
            for name, group in pairs: inp(self.choice(selection, name, groups[group]))
            spec.update({'cost': 2 if recipe == 'alchemize' else 1, 'yield': 8 if recipe == 'alchemize' else 1})
            if recipe != 'alchemize': spec['boundary'] = '制作产物确定；物品使用效果随机'
        elif recipe == 'seed-potion':
            seeds = selection.get('seed_ids')
            if seeds is None: raise Need('seed_ids', 3, 0, '请选择三个种子槽，可选择相同种子', True)
            if len(seeds) != 3 or any(seed not in SEED_POTIONS for seed in seeds): raise ValueError('酿药需要三个合法种子槽')
            for seed, count in Counter(seeds).items(): inp(seed, count)
            same = len(set(seeds)) == 1
            spec['output'] = SEED_POTIONS[seeds[0]] if same and not seeds[0].startswith('plants.sungrass$') else None
            if spec['output'] is None:
                spec['boundary'] = '混种含默认药池随机分支；治疗还受隐藏的酿药计数重抽，不能保证治疗或用期望药剂衔接后续步骤'
            branch = {1: 0, 2: 1, 3: 2}[len(set(seeds))]
            initial = {}
            for (potion, _), weight in zip(POTIONS, DEFAULT_POTION_WEIGHTS):
                identity = item_id('potions/PotionOf' + potion)
                slots = sum(SEED_POTIONS[seed] == identity for seed in seeds)
                numerator, denominator = branch * weight * 3 + (4 - branch) * slots * 30, 360
                divisor = math.gcd(numerator, denominator)
                initial[identity] = {'numerator': numerator // divisor, 'denominator': denominator // divisor}
            spec['probability'] = {'distinct_seeds': len(set(seeds)), 'default_pool_chance': {1: 0, 2: .25, 3: .5}[len(set(seeds))],
                                   'slot_weights': dict(Counter(seeds)), 'slot_total': 3, 'healing_counter': 'hidden',
                                   'default_pool_weights': {item_id('potions/PotionOf' + p): w for (p, _), w in zip(POTIONS, DEFAULT_POTION_WEIGHTS)},
                                   'default_pool_weight_total': 30, 'initial_probabilities_before_healing_reroll': initial,
                                   'default_healing_probability_before_reroll': .2,
                                   'healing_reroll': '每次治疗按隐藏计数（至多10）/10拒绝并重抽默认药池；最终概率未确认，连续酿药也不能视为独立试验。'}
        elif recipe == 'meat-pie':
            inp(self.choice(selection, 'pasty_id', groups['pie_pasty']))
            inp(item_id('food/Food')); inp(self.choice(selection, 'meat_id', groups['pie_meat']))
            spec['cost'] = 6
        elif recipe == 'cook-meat':
            three, rest = divmod(quantity, 3)
            inp(item_id('food/MysteryMeat'), quantity)
            spec.update({'yield': quantity, 'cost': 2 * three + rest, 'once': True,
                        'cooking_counts': {'recipe-stewedmeat-threemeat': three,
                                        'recipe-stewedmeat-onemeat': int(rest == 1),
                                        'recipe-stewedmeat-twomeat': int(rest == 2)}})
        return spec

    def take(self, requirement, amount):
        matches = [r for r in self.rows if r['id'] == requirement['id']
                   and ('key' not in requirement or r['key'] == requirement['key'])
                   and ('cooked' not in requirement or r['state'].get('cooked') == requirement['cooked'])]
        available = sum(r['quantity'] - r['reserve'] for r in matches)
        if requirement.get('whole'):
            if len(matches) != 1 or matches[0]['reserve'] or matches[0]['quantity'] != amount:
                raise Need(requirement['id'], amount, 0, '整堆或原物品必须完整可用，不能拆堆虚构保留量')
        if available < amount:
            shortage = amount - available
            identity = requirement['id']
            if 'key' in requirement or 'cooked' in requirement:
                raise Need(identity, amount, available, '指定物品、状态或保留量限制')
            if identity in self.visiting or len(self.visiting) >= 64:
                raise Need(identity, amount, available, '前置配方循环或链深度超过限制', True)
            selection = self.args['chains'].get(identity)
            producers = self.producers.get(identity, [])
            if selection is None and len(producers) == 1: selection = producers[0]
            if selection is None:
                raise Need(identity, amount, available, '缺少材料' if not producers else '多个前置配方，请明确选择', bool(producers),
                           options=copy.deepcopy(producers))
            self.visiting.append(identity)
            try:
                self.craft(selection['recipe'], selection['choices'], shortage, expected=identity)
            except Need as exc:
                raise Need(identity, amount, available, '前置无法完成：' + exc.detail['reason'],
                           exc.detail['condition'], dependency=exc.detail) from exc
            finally:
                self.visiting.pop()
            matches = [r for r in self.rows if r['id'] == identity]
            available = sum(r['quantity'] - r['reserve'] for r in matches)
            if available < amount: raise Need(identity, amount, available, '前置产出未确定或不足')
        consumed, left = [], amount
        for row in matches:
            spend = min(left, row['quantity'] - row['reserve'])
            if spend:
                row['quantity'] -= spend
                self.spent[row['key']] += spend
                consumed.append({'key': row['key'], 'id': row['id'], 'quantity': spend, 'origin': row['origin'], 'state': copy.deepcopy(row['state'])})
                left -= spend
            if not left: break
        return consumed

    def craft(self, recipe, selection, quantity, expected=None, prepared=None):
        if not quantity: return [], 0
        spec = prepared if prepared is not None else self.spec(recipe, selection, quantity)
        if expected is not None and (spec['output'] != expected or spec['yield'] is None):
            raise Need(expected, quantity, 0, '所选前置配方不能保证所需材料身份或产量', True)
        produced = spec['yield']
        batches = 1 if spec.get('once') or produced is None else (quantity + produced - 1) // produced
        total = None if produced is None else produced * batches
        if total is not None and (total <= 0 or total > MAX_INT):
            raise Need('output', quantity, 0, '无法生成所需正数产物，或产出超过游戏整数上限')
        if spec.get('once') and total is not None and quantity > total:
            raise Need(spec['output'], quantity, total, '所选完整实例的产量不足')
        cost = None if spec['cost'] is None else spec['cost'] * batches
        if cost is None:
            raise Need('energy', 1, 0, '费用所需状态未确认，不能猜测消耗', True,
                       pending=copy.deepcopy(spec.get('pending', [])), inputs=copy.deepcopy(spec['inputs']))
        inputs = []
        for requirement in spec['inputs']:
            inputs.extend(self.take(requirement, requirement['quantity'] * batches))
        if cost > self.energy - self.args['energy_reserve']:
            raise Need('energy', cost, self.energy - self.args['energy_reserve'], '共享能量扣除最低保留后不足')
        before = self.energy
        self.energy -= cost
        if len(self.steps) >= 512: raise Need('steps', 1, 0, '规划步骤超过512项', True)
        step = {'key': 'step-' + str(len(self.steps) + 1), 'target': self.target, 'recipe': recipe,
                'batches': batches, 'inputs': inputs, 'output': {'id': spec['output'], 'quantity': total, 'state': spec['state'],
                                                               'certainty': 'known' if spec['output'] is not None and total is not None else 'unknown'},
                'energy': {'before': before, 'spent': cost, 'after': self.energy}, 'source': spec['source']}
        for name in ('upgrade_costs', 'starting_level', 'cooking_counts', 'probability', 'yield_bounds'):
            if name in spec: step[name] = spec[name]
        self.steps.append(step)
        if spec.get('upgrade_costs'):
            self.steps.pop()
            previous = before
            for offset, step_cost in enumerate(spec['upgrade_costs']):
                level_before = spec['starting_level'] + offset
                graded = copy.deepcopy(step)
                graded['key'] = 'step-' + str(len(self.steps) + 1)
                graded['energy'] = {'before': previous, 'spent': step_cost, 'after': previous - step_cost}
                graded['level_before'], graded['level_after'] = level_before, level_before + 1
                graded['output']['state']['level'] = level_before + 1
                if offset:
                    graded['inputs'] = [{'key': self.steps[-1]['key'], 'id': spec['output'], 'quantity': 1,
                                         'origin': 'planned', 'state': {**copy.deepcopy(spec['state']), 'level': level_before}}]
                self.steps.append(graded)
                previous -= step_cost
        if spec.get('pending'):
            self.pending.extend({'target': self.target, 'condition': condition, 'recipe': recipe} for condition in spec['pending'])
        if spec.get('boundary'):
            self.boundaries.append({'target': self.target, 'recipe': recipe, 'message': spec['boundary']})
        output_key = None
        if spec['output'] is not None and total is not None:
            output_key = 'produced-' + str(len(self.steps))
            self.rows.append({'key': output_key, 'id': spec['output'], 'quantity': total, 'reserve': 0,
                              'origin': 'planned', 'state': copy.deepcopy(spec['state'])})
        return output_key, total

    def goal(self, target, quantity):
        self.target = target['key']
        if not quantity: return
        reused, reused_output = 0, None
        preview = self.spec(target['recipe'], target['choices'], quantity)
        if not preview.get('once') and preview['output'] is not None and preview['yield'] is not None:
            identity = preview['output']
            for row in self.rows:
                if row['origin'] == 'planned' and row['id'] == identity and row['state'] == preview['state'] and row['quantity']:
                    count = min(quantity - reused, row['quantity'])
                    row['quantity'] -= count
                    reused += count
                    reused_output = {'id': identity, 'quantity': quantity, 'state': copy.deepcopy(row['state']), 'certainty': 'known'}
                    if reused == quantity: break
        output_key, total = self.craft(target['recipe'], target['choices'], quantity - reused, prepared=preview)
        output = self.steps[-1]['output'] if quantity > reused else reused_output
        allocated = quantity if total is not None else None
        if output_key:
            row = next(r for r in self.rows if r['key'] == output_key)
            row['quantity'] -= quantity - reused
        self.outputs.append({'target': target['key'], **copy.deepcopy(output),
                             'quantity': allocated, 'produced_quantity': total, 'from_surplus': reused,
                             'surplus': None if total is None else total - (quantity - reused),
                             **({'yield_bounds': copy.deepcopy(preview['yield_bounds'])} if 'yield_bounds' in preview else {})})


def calculate(catalog, raw, values=None):
    args = validate_plan(raw)
    # Current rule limits belong to calculation, not the structural reader:
    # older fixed plans must remain readable and editable without being clamped.
    for row in args['resources']:
        preservation = row['state'].get('wand_preservation')
        if preservation is not None and not 0 <= preservation <= TALENT_MAXIMUM['WAND_PRESERVATION']:
            raise ValueError('法杖保存天赋点数必须为0–2的整数；未确认请留空')
    if args['recipe_version'] != VERSION:
        raise ValueError('此方案的炼金规则版本尚未核对，固定参数仍保留')
    recipe_list(catalog)  # Enforce pinned catalog and source evidence.
    if (args['energy_origin'] == 'known' or any(r['origin'] == 'known' for r in args['resources'])) and args['reference_version'] != VERSION_CODE:
        raise ValueError('已知资源的参考版本不是官方4.0.2，请核对后明确手填')
    entries = {row['id'] for row in catalog.entries}
    if any(row['id'] not in entries for row in args['resources']):
        raise ValueError('库存包含未收录身份，不能推测隐藏资源')
    if any(row['id'] in NON_INVENTORY_IDS for row in args['resources']):
        raise ValueError('资料子条目、旧版残留或抽象类型不能登记为官方4.0.2库存物品；原条件保留')
    ledger = Ledger(catalog, args, values)
    targets, shortages, pending, requested_steps = [], [], [], []
    for target in args['targets']:
        requested = target['quantity']
        trial = ledger.clone()
        failure = None
        try:
            trial.goal(target, requested)
            requested_steps.extend(copy.deepcopy(trial.steps[len(ledger.steps):]))
            ledger, affordable = trial, requested
        except Need as exc:
            failure = exc.detail
            requested_steps.extend(copy.deepcopy(trial.steps[len(ledger.steps):]))
            family = next(row for row in family_list(catalog) if row['id'] == target['recipe'])
            yield_count = family.get('output_quantity', family.get('quantity'))
            estimated_batches = (requested + yield_count - 1) // yield_count if yield_count else None
            energy_cost = family.get('energy_cost', family.get('cost'))
            requested_steps.append({'target': target['key'], 'recipe': target['recipe'], 'status': 'pending',
                                    'requested_quantity': requested, 'batches': estimated_batches,
                                    'requirements': family.get('requirements', family.get('inputs', [])),
                                    'energy_spent': energy_cost * estimated_batches if energy_cost is not None and estimated_batches is not None else None,
                                    'reason': failure['reason']})
            low, high = 0, requested
            # Monotone feasibility with fixed choices, at most 31 probes.
            while low < high:
                mid = (low + high + 1) // 2
                probe = ledger.clone()
                try:
                    probe.goal(target, mid)
                    low = mid
                except Need:
                    high = mid - 1
            affordable = low
            if affordable:
                ledger.goal(target, affordable)
            shortages.append({'target': target['key'], **failure})
            if failure.get('condition'):
                pending.append({'target': target['key'], 'condition': failure['reason'], 'recipe': target['recipe']})
        targets.append({**copy.deepcopy(target), 'requested_quantity': requested, 'planned_quantity': affordable,
                        'within_budget': affordable == requested, 'shortfall': requested - affordable})
    materials = [{**copy.deepcopy(row), 'spent': ledger.spent[row['key']],
                  'remaining': next(r['quantity'] for r in ledger.rows if r['key'] == row['key']),
                  'spendable_remaining': next(r['quantity'] - r['reserve'] for r in ledger.rows if r['key'] == row['key'])}
                 for row in args['resources']]
    result = {'kind': 'alchemy', 'format': 2, 'version': VERSION, 'commit': COMMIT, 'params': args,
              'targets': targets, 'requested_steps': requested_steps, 'steps': ledger.steps, 'materials': materials, 'outputs': ledger.outputs,
              'surplus': [copy.deepcopy(r) for r in ledger.rows if r['origin'] == 'planned' and r['quantity']],
              'energy': {'quantity': args['energy'], 'reserve': args['energy_reserve'], 'origin': args['energy_origin'],
                         'spent': args['energy'] - ledger.energy, 'remaining': ledger.energy,
                         'spendable_remaining': ledger.energy - args['energy_reserve']},
              'shortages': shortages, 'pending_conditions': pending + ledger.pending,
              'outcome_boundaries': ledger.boundaries,
              'within_budget': all(t['within_budget'] for t in targets),
              'warnings': ['按固定条件模拟制作；目标按列表顺序共享库存与能量，结果不会执行游戏操作。',
                           '未知产量或随机身份不会成为后续步骤的确定材料；手填条件是明确假设。',
                           '能量输入为本次明确可用总量；存档带入的Dungeon能量不自动计入未确认可用的炼金工具包。']}
    result['complete'] = result['within_budget'] and not result['pending_conditions'] and all(o['certainty'] == 'known' for o in ledger.outputs)
    return args, result


def discover(catalog, raw, values=None):
    """Independent previews; adding targets recalculates their shared ledger."""
    base = copy.deepcopy(raw)
    base.pop('targets', None)
    base.setdefault('format', 2); base.setdefault('recipe_version', VERSION); base.setdefault('chains', {})
    # Reject bad shared input once; an ineligible first item must not abort all families.
    calculate(catalog, {**base, 'targets': [{'key': 'check', 'recipe': 'potion-healing', 'quantity': 0, 'choices': {}}]}, values)
    rows = []
    groups = resource_catalog(catalog)
    for family in family_list(catalog):
        target = {'key': 'discovery', 'recipe': family['id'], 'quantity': 1, 'choices': {}}
        stock = [r for r in base.get('resources', []) if r['quantity'] > r['reserve']]
        for field in family['choices']:
            name, group = field['key'], field['group']
            if field['type'] in ('instance', 'instance-list'):
                allowed = groups.get(group, [item_id('trinkets/TrinketCatalyst')] if group == 'catalyst' else [])
                candidates = [r for r in stock if r['id'] in allowed]
                if family['id'] in ('resin', 'liquid-metal'):
                    candidates = [r for r in candidates if not r['reserve'] and r['state'].get('cursed') is not True
                                  and (family['id'] != 'liquid-metal' or (r['state'].get('is_upgradable') is not False
                                       and not r['id'].startswith('items.weapon.missiles.darts.')))
                                  and (family['id'] != 'resin' or r['quantity'] == 1)]
                    def missing_conditions(row):
                        state = row['state']
                        missing = int(state.get('cursed') is not False)
                        if family['id'] == 'resin':
                            missing += int(state.get('base_level') is None and
                                           (state.get('public_level') is None or state.get('resin_bonus') is None))
                            missing += int(state.get('hero_class') is None)
                            missing += int(state.get('hero_class') != 'MAGE' and state.get('wand_preservation') is None)
                        else:
                            missing += sum(state.get(n) is None for n in ('level', 'durability'))
                            if row['id'] not in MISSILE_PUBLIC_TYPES:
                                missing += sum(state.get(n) is None for n in ('tier', 'default_quantity', 'is_upgradable'))
                        return missing
                    candidates.sort(key=missing_conditions)
                elif family['id'] in ('trinket-catalyst', 'trinket-upgrade'):
                    candidates = [r for r in candidates if r['quantity'] == 1 and not r['reserve']]
                if family['id'] == 'trinket-upgrade':
                    candidates = [r for r in candidates if r['state'].get('level') is None or 0 <= r['state']['level'] < 3]
                    candidates.sort(key=lambda r: r['state'].get('level') is None)
                if candidates:
                    target['choices'][name] = [candidates[0]['key']] if field['type'] == 'instance-list' else candidates[0]['key']
            elif field['type'] == 'item':
                available = [r['id'] for r in stock if r['id'] in field['allowed']]
                if available: target['choices'][name] = available[0]
            elif field['type'] == 'three-items':
                slots = []
                quantities = Counter()
                for row in stock:
                    if row['id'] in field['allowed']: quantities[row['id']] += row['quantity'] - row['reserve']
                same = next((i for i, count in quantities.items() if count >= 3 and i != 'plants.sungrass$seed'), None)
                if same:
                    slots = [same] * 3
                for row in stock:
                    if len(slots) == 3: break
                    if row['id'] in field['allowed']:
                        slots.extend([row['id']] * min(3 - len(slots), row['quantity'] - row['reserve']))
                    if len(slots) == 3: break
                if len(slots) == 3: target['choices'][name] = slots
            elif field['type'] == 'level' and 'source_key' in target['choices']:
                state = next(r['state'] for r in stock if r['key'] == target['choices']['source_key'])
                if state.get('level') is not None: target['choices'][name] = state['level'] + 1
        params = {**base, 'targets': [target]}
        try:
            _, result = calculate(catalog, params, values)
        except ValueError as exc:
            rows.append({'id': family['id'], 'name': family['name'], 'choices': family['choices'], 'target': target,
                         'craftable': False, 'complete': False, 'steps': [], 'shortages': [],
                         'pending_conditions': [{'condition': str(exc), 'recipe': family['id']}],
                         'outcome_boundaries': [], 'availability': 'needs-condition'})
            continue
        availability = ('needs-condition' if result['pending_conditions'] else
                        'needs-energy' if any(s['id'] == 'energy' for s in result['shortages']) else
                        'needs-material' if result['shortages'] else
                        'random-outcome' if not result['complete'] else
                        'with-prerequisites' if len(result['steps']) > 1 else 'immediate')
        rows.append({'id': family['id'], 'name': family['name'], 'choices': family['choices'], 'target': target,
                     'craftable': result['within_budget'], 'complete': result['complete'],
                     'steps': result['steps'], 'shortages': result['shortages'],
                     'pending_conditions': result['pending_conditions'], 'outcome_boundaries': result['outcome_boundaries'],
                     'availability': availability})
    return {'recipes': rows, 'message': '每项独立预览；加入多个目标后必须重新计算共享库存和能量。'}
