"""Finite, explicit 4.0.2 recipes and fixed-reference alchemy budgets.

Rules are derived from Shattered Pixel Dungeon, GPL-3.0-or-later, pinned below.
This planner never guesses unidentified item identities or applies game actions.
"""
from collections import Counter
import copy
import re

VERSION = '4.0.2'
VERSION_CODE = 922
COMMIT = '57a4e06a4caf162446d1c28caa7983f0493fecf0'
SOURCE = 'https://github.com/00-Evan/shattered-pixel-dungeon'
JAVA_ROOT = 'core/src/main/java/com/shatteredpixel/shatteredpixeldungeon/'
MAX_INT = 2147483647  # Item.quantity and Dungeon.energy are Java signed int fields.

POTIONS = (
    ('Strength', 'Mastery'), ('Healing', 'Shielding'), ('MindVision', 'MagicalSight'),
    ('Frost', 'SnapFreeze'), ('LiquidFlame', 'DragonsBreath'), ('ToxicGas', 'CorrosiveGas'),
    ('Haste', 'Stamina'), ('Invisibility', 'ShroudingFog'), ('Levitation', 'StormClouds'),
    ('ParalyticGas', 'EarthenArmor'), ('Purity', 'Cleansing'), ('Experience', 'DivineInspiration'))
SCROLLS = (
    ('Upgrade', 'Enchantment', 'Enchantment'), ('Identify', 'Divination', 'Intuition'),
    ('RemoveCurse', 'AntiMagic', 'DetectMagic'), ('MirrorImage', 'PrismaticImage', 'Flock'),
    ('Recharging', 'MysticalEnergy', 'Shock'), ('Teleportation', 'Passage', 'Blink'),
    ('Lullaby', 'SirensSong', 'DeepSleep'), ('MagicMapping', 'Foresight', 'Clairvoyance'),
    ('Rage', 'Challenge', 'Aggression'), ('Retribution', 'PsionicBlast', 'Blast'),
    ('Terror', 'Dread', 'Fear'), ('Transmutation', 'Metamorphosis', 'Augmentation'))
# Only named SimpleRecipe classes whose complete arrays/cost/output have been checked.
SIMPLE = (
    ('potions/brews/BlizzardBrew', ('potions/PotionOfFrost',), (1,), 8, 1),
    ('potions/brews/InfernalBrew', ('potions/PotionOfLiquidFlame',), (1,), 12, 1),
    ('potions/brews/ShockingBrew', ('potions/PotionOfParalyticGas',), (1,), 10, 1),
    ('potions/brews/AquaBrew', ('potions/exotic/PotionOfStormClouds',), (1,), 8, 8),
    ('potions/brews/CausticBrew', ('potions/PotionOfToxicGas', 'quest/GooBlob'), (1, 1), 1, 1),
    ('potions/elixirs/ElixirOfDragonsBlood', ('potions/exotic/PotionOfDragonsBreath',), (1,), 10, 1),
    ('potions/elixirs/ElixirOfIcyTouch', ('potions/exotic/PotionOfSnapFreeze',), (1,), 6, 1),
    ('potions/elixirs/ElixirOfToxicEssence', ('potions/exotic/PotionOfCorrosiveGas',), (1,), 8, 1),
    ('potions/elixirs/ElixirOfMight', ('potions/PotionOfStrength',), (1,), 16, 1),
    ('potions/elixirs/ElixirOfFeatherFall', ('potions/PotionOfLevitation',), (1,), 10, 1),
    ('potions/elixirs/ElixirOfArcaneArmor', ('potions/exotic/PotionOfEarthenArmor', 'quest/GooBlob'), (1, 1), 8, 1),
    ('potions/elixirs/ElixirOfAquaticRejuvenation', ('potions/PotionOfHealing', 'quest/GooBlob'), (1, 1), 6, 1),
    ('spells/BeaconOfReturning', ('scrolls/exotic/ScrollOfPassage',), (1,), 12, 5))

# The actual registered inner classes are part of the fixed source contract.
EXTRA_SIMPLE = (
    ('spells/MagicalInfusion', ('scrolls/ScrollOfUpgrade',), (1,), 12, 1, 'Recipe'),
    ('spells/PhaseShift', ('scrolls/ScrollOfTeleportation',), (1,), 10, 6, 'Recipe'),
    ('spells/Recycle', ('scrolls/ScrollOfTransmutation',), (1,), 12, 12, 'Recipe'),
    ('spells/TelekineticGrab', ('LiquidMetal',), (10,), 10, 8, 'Recipe'),
    ('spells/SummonElemental', ('quest/Embers',), (1,), 10, 6, 'Recipe'),
    ('potions/elixirs/ElixirOfHoneyedHealing', ('potions/PotionOfHealing', 'Honeypot$ShatteredPot'), (1, 1), 2, 1, 'Recipe'),
    ('spells/CurseInfusion', ('scrolls/ScrollOfRemoveCurse', 'quest/MetalShard'), (1, 1), 6, 4, 'Recipe'),
    ('spells/ReclaimTrap', ('scrolls/ScrollOfMagicMapping', 'quest/MetalShard'), (1, 1), 8, 5, 'Recipe'),
    ('spells/WildEnergy', ('scrolls/ScrollOfRecharging', 'quest/MetalShard'), (1, 1), 4, 5, 'Recipe'),
    ('food/StewedMeat', ('food/MysteryMeat',), (1,), 1, 1, 'oneMeat'),
    ('food/StewedMeat', ('food/MysteryMeat',), (2,), 2, 2, 'twoMeat'),
    ('food/StewedMeat', ('food/MysteryMeat',), (3,), 2, 3, 'threeMeat'))


def item_id(relative):
    return 'items.' + relative.replace('/', '.').lower()


def definitions():
    rows = []
    for regular, exotic in POTIONS:
        rows.append({'id': 'potion-' + regular.lower(), 'group': '普通药剂 → 合剂',
                     'inputs': [{'id': item_id('potions/PotionOf' + regular), 'quantity': 1}],
                     'output': item_id('potions/exotic/PotionOf' + exotic), 'quantity': 1, 'cost': 4,
                     'path': JAVA_ROOT + 'items/potions/exotic/ExoticPotion.java', 'adapter': 'PotionToExotic'})
    for regular, exotic, stone in SCROLLS:
        ingredient = [{'id': item_id('scrolls/ScrollOf' + regular), 'quantity': 1}]
        rows.append({'id': 'scroll-' + regular.lower(), 'group': '普通卷轴 → 秘卷',
                     'inputs': copy.deepcopy(ingredient), 'output': item_id('scrolls/exotic/ScrollOf' + exotic),
                     'quantity': 1, 'cost': 6, 'path': JAVA_ROOT + 'items/scrolls/exotic/ExoticScroll.java', 'adapter': 'ScrollToExotic'})
        rows.append({'id': 'stone-' + regular.lower(), 'group': '普通卷轴 → 符石',
                     'inputs': copy.deepcopy(ingredient), 'output': item_id('stones/StoneOf' + stone),
                     'quantity': 2, 'cost': 0, 'path': JAVA_ROOT + 'items/scrolls/Scroll.java', 'adapter': 'ScrollToStone'})
    for output, ingredients, amounts, cost, quantity, inner in (*[(*row, 'Recipe') for row in SIMPLE], *EXTRA_SIMPLE):
        suffix = '-' + inner.lower() if inner != 'Recipe' else ''
        rows.append({'id': 'recipe-' + output.rsplit('/', 1)[-1].lower() + suffix, 'group': '已核对实用配方',
                     'inputs': [{'id': item_id(i), 'quantity': q} for i, q in zip(ingredients, amounts)],
                     'output': item_id(output), 'quantity': quantity, 'cost': cost,
                     'path': JAVA_ROOT + 'items/' + output + '.java', 'adapter': 'SimpleRecipe', 'recipe_class': inner})
    return rows


def integer(value, label):
    if type(value) is not int or not 0 <= value <= MAX_INT:
        raise ValueError(f'{label}必须是 0–{MAX_INT} 的整数')
    return value


def validate_plan(raw):
    """Validate stored types without requiring that an old recipe still exists."""
    if isinstance(raw, dict) and 'format' in raw:
        from .alchemy_flow import validate_plan as validate_flow
        return validate_flow(raw)
    keys = {'recipe', 'recipe_version', 'batches', 'energy', 'energy_reserve',
            'energy_origin', 'resources', 'reference_version'}
    if not isinstance(raw, dict) or set(raw) != keys:
        raise ValueError('炼金方案参数不正确')
    if not isinstance(raw['recipe'], str) or not re.fullmatch(r'[a-z0-9-]{1,100}', raw['recipe']):
        raise ValueError('炼金配方身份不正确')
    if not isinstance(raw['recipe_version'], str) or not re.fullmatch(r'[0-9.]{1,40}', raw['recipe_version']):
        raise ValueError('炼金规则版本不正确')
    for key in ('batches', 'energy', 'energy_reserve'):
        integer(raw[key], {'batches': '规划次数', 'energy': '炼金能量', 'energy_reserve': '保留能量'}[key])
    if raw['energy_reserve'] > raw['energy']:
        raise ValueError('保留能量不能超过现有能量')
    if raw['energy_origin'] not in ('manual', 'known'):
        raise ValueError('能量来源必须是明确手填或已知快照')
    if raw['reference_version'] is not None:
        integer(raw['reference_version'], '参考存档版本')
    if not isinstance(raw['resources'], list) or not 1 <= len(raw['resources']) <= 64:
        raise ValueError('材料列表不正确')
    identities = set()
    for row in raw['resources']:
        if not isinstance(row, dict) or set(row) != {'id', 'quantity', 'reserve', 'origin'}:
            raise ValueError('材料条件不正确')
        if not isinstance(row['id'], str) or not re.fullmatch(r'items\.[a-z0-9_.$-]{1,290}', row['id']):
            raise ValueError('材料身份不正确；未知身份不能参与规划')
        if row['id'] in identities:
            raise ValueError('同一材料只能登记一份总库存，不能重复使用同一库存')
        identities.add(row['id'])
        integer(row['quantity'], '材料数量')
        integer(row['reserve'], '保留材料')
        if row['reserve'] > row['quantity']:
            raise ValueError('保留材料不能超过现有数量')
        if row['origin'] not in ('manual', 'known'):
            raise ValueError('材料来源必须是明确手填或已知快照；未知身份不能参与规划')
    return copy.deepcopy(raw)


def recipe_list(catalog):
    if catalog.data.get('version') != VERSION or catalog.data.get('commit') != COMMIT:
        raise ValueError('炼金规则仅核对官方 4.0.2；当前资料版本不同，请保留方案并核对版本')
    entries = {row['id']: row for row in catalog.entries}
    metadata = {row['id']: row for row in catalog.data.get('alchemy_recipes', [])}
    result = []
    for definition in definitions():
        row = copy.deepcopy(definition)
        if row['output'] not in entries or any(i['id'] not in entries for i in row['inputs']):
            raise ValueError('已核对配方的材料或产出资料缺失')
        row['name'] = entries[row['output']]['name']
        if row['output'] == item_id('food/StewedMeat'):
            row['name'] += f"（{row['inputs'][0]['quantity']}份原肉 → {row['quantity']}份；{row['cost']}能量）"
        row['unit'] = '件'
        for ingredient in row['inputs']:
            ingredient['name'] = entries[ingredient['id']]['name']
            ingredient['unit'] = '件'
        row['source'] = copy.deepcopy(metadata.get(row['id'], {}).get('source', {}))
        row['family'] = metadata.get(row['id'], {}).get('family')
        if not row['source']:
            raise ValueError('炼金来源证据缺失，请重新生成官方固定版本资料')
        result.append(row)
    return result


def aggregate_ingredients(inputs):
    """Each identity has one actual required count, even for repeated specifications."""
    required = Counter()
    for ingredient in inputs:
        quantity = integer(ingredient['quantity'], '每次所需材料')
        if not quantity:
            raise ValueError('配方材料数量必须大于 0')
        required[ingredient['id']] += quantity
        integer(required[ingredient['id']], '合并后所需材料')
    return dict(required)


def calculate(catalog, raw, values=None):
    if isinstance(raw, dict) and 'format' in raw:
        from .alchemy_flow import calculate as calculate_flow
        return calculate_flow(catalog, raw, values=values)
    args = validate_plan(raw)
    if args['recipe_version'] != VERSION:
        raise ValueError('此方案的炼金规则版本尚未核对；固定条件已保留，请使用对应版本资料')
    recipe = next((row for row in recipe_list(catalog) if row['id'] == args['recipe']), None)
    if recipe is None:
        raise ValueError('此配方尚未收录，不能推测材料或输出')
    required = aggregate_ingredients(recipe['inputs'])
    inventory = {row['id']: row for row in args['resources']}
    if set(inventory) != set(required):
        raise ValueError('材料列表必须对应所选配方；不能把未知身份或额外库存映射为所需材料')
    if (args['energy_origin'] == 'known' or any(r['origin'] == 'known' for r in inventory.values())) and args['reference_version'] != VERSION_CODE:
        raise ValueError('参考存档版本不是已核对的 4.0.2，不能当作已知可用资源；请核对后明确手填')
    limits = [{'label': next(i['name'] for i in recipe['inputs'] if i['id'] == identity),
               'id': identity, 'max_batches': (inventory[identity]['quantity'] - inventory[identity]['reserve']) // amount,
               'formula': f'⌊({inventory[identity]["quantity"]} − {inventory[identity]["reserve"]}) / {amount}⌋',
               'reason': '材料扣除最低保留量后'} for identity, amount in required.items()]
    if recipe['cost']:
        limits.append({'label': '炼金能量', 'id': 'energy',
                       'max_batches': (args['energy'] - args['energy_reserve']) // recipe['cost'], 'reason': '能量扣除最低保留量后'})
        limits[-1]['formula'] = f'⌊({args["energy"]} − {args["energy_reserve"]}) / {recipe["cost"]}⌋'
    limits.append({'label': '游戏单份数量上限', 'id': 'output', 'max_batches': MAX_INT // recipe['quantity'],
                   'formula': f'⌊{MAX_INT} / {recipe["quantity"]}⌋', 'reason': '产出数量不能超过游戏整数范围'})
    maximum = min(row['max_batches'] for row in limits)
    batches = min(args['batches'], maximum)
    consumed = []
    for identity, amount in required.items():
        row = inventory[identity]
        consumed.append({'id': identity, 'name': next(i['name'] for i in recipe['inputs'] if i['id'] == identity),
                         'quantity': row['quantity'], 'reserve': row['reserve'], 'per_batch': amount,
                         'spent': amount * batches, 'remaining': row['quantity'] - amount * batches,
                         'spendable_remaining': row['quantity'] - amount * batches - row['reserve'],
                         'unit': '件', 'origin': row['origin']})
    energy_spent = batches * recipe['cost']
    warnings = ['按固定条件规划；局中数据只是最近存档参考，结果不会自动执行或控制游戏。']
    if any(row['origin'] == 'manual' for row in args['resources']) or args['energy_origin'] == 'manual':
        warnings.append('手填数量与身份是你的明确假设，尚未由当前游戏确认。')
    if args['reference_version'] not in (None, VERSION_CODE):
        warnings.append('参考存档版本不同；此结果只按官方 4.0.2 手填条件计算。')
    result = {'kind': 'alchemy', 'version': VERSION, 'commit': COMMIT, 'recipe': recipe,
              'params': args, 'requested_batches': args['batches'], 'batches': batches,
              'max_batches': maximum, 'within_budget': args['batches'] <= maximum,
              'limits': limits, 'limiting': [row for row in limits if row['max_batches'] == maximum],
              'materials': consumed,
              'output': {'id': recipe['output'], 'name': recipe['name'], 'quantity': batches * recipe['quantity'], 'unit': '件'},
              'energy': {'quantity': args['energy'], 'reserve': args['energy_reserve'], 'per_batch': recipe['cost'],
                         'spent': energy_spent, 'remaining': args['energy'] - energy_spent,
                         'spendable_remaining': args['energy'] - energy_spent - args['energy_reserve'],
                         'unit': '点', 'origin': args['energy_origin']}, 'warnings': warnings}
    return args, result


def resources_from_snapshot(session):
    from .decisions import source
    snapshot = session.snapshot()
    data = {} if snapshot.get('error') else snapshot.get('data') or {}
    provenance = source(snapshot)
    allowed = {i['id'] for row in recipe_list(session.catalog) for i in row['inputs']}
    counts = Counter()
    unknown = 0
    compatible = data.get('version') == VERSION_CODE and provenance['mode'] == 'save'
    for row in data.get('items', []):
        if row.get('available') is not True:
            continue
        if row.get('known') is not True:
            unknown += 1
            continue
        if compatible and row.get('key') in allowed and type(row.get('quantity')) is int and 0 < row['quantity'] <= MAX_INT:
            counts[row['key']] += row['quantity']
    counts = {key: value for key, value in counts.items() if value <= MAX_INT}
    energy = data.get('energy')
    valid_energy = compatible and type(energy) in (int, float) and 0 <= energy <= MAX_INT and int(energy) == energy
    entries = {row['id'] for row in session.catalog.entries}
    instances = []
    for index, row in enumerate(data.get('items', [])):
        quantity = row.get('quantity')
        if (compatible and row.get('known') is True and row.get('available') is True
                and row.get('key') in entries and type(quantity) is int and 0 < quantity <= MAX_INT):
            state = copy.deepcopy(row.get('alchemy_state') or {})
            if row.get('cursed') is not None:
                state['cursed'] = row['cursed']
            if 'is_upgradable' in row:
                state['is_upgradable'] = row['is_upgradable']
            instances.append({'key': row.get('instance_key') or 'snapshot-' + str(index), 'id': row['key'],
                              'quantity': quantity, 'reserve': 0, 'origin': 'known', 'state': state})
    return {'resources': [{'id': key, 'quantity': count, 'origin': 'known'} for key, count in counts.items()],
            'instances': instances,
            'energy': int(energy) if valid_energy else None, 'reference_version': data.get('version'),
            'compatible': compatible, 'unknown_excluded': unknown, 'source': provenance,
            'message': '最近存档的已知可用材料；未知身份已排除，带入会替换材料总量，不叠加库存。' if compatible else '没有可带入的官方 4.0.2 存档参考；可明确手填假设。'}


def status(session):
    try:
        from .alchemy_flow import family_list, resource_catalog
        return {'available': True, 'recipes': recipe_list(session.catalog), 'version': VERSION, 'commit': COMMIT,
                'families': family_list(session.catalog), 'format_versions': [1, 2],
                'registered_families': copy.deepcopy(session.catalog.data.get('alchemy_families', [])),
                'resource_catalog': resource_catalog(session.catalog),
                'max_integer': MAX_INT, 'resources': resources_from_snapshot(session)}
    except ValueError as exc:
        return {'available': False, 'recipes': [], 'version': VERSION, 'commit': COMMIT,
                'max_integer': MAX_INT, 'error': str(exc)}
