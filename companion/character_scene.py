"""Reusable public character strength conditions for SPD 4.0.2.

The source is Hero.STR, Ring.getBonus/soloBonus, AdrenalineSurge.boost and
SpiritForm.ringLevel, pinned at 57a4e06a4caf162446d1c28caa7983f0493fecf0,
GPL-3.0-or-later. This is a condition calculation, never a game action.
"""
import copy
import math
import re

from .game_math import float32 as f
from .public_talents import talent_points

PREFIX = 'com.shatteredpixel.shatteredpixeldungeon.'
MIGHT = 'items.rings.ringofmight'
KEYS = {'format', 'base_strength', 'rings', 'strongman', 'adrenaline', 'magic_immune',
        'spirit_form', 'spirit_ring', 'spirit_level', 'spirit_cursed'}


def optional_int(value, label, lower, upper):
    if value is not None and (type(value) is not int or not lower <= value <= upper):
        raise ValueError(label + '需要范围内的整数，未确认请留空')
    return value


def ring_identity(value):
    if value is not None and (not isinstance(value, str) or not re.fullmatch(r'items\.rings\.ringof[a-z]+', value)):
        raise ValueError('戒指身份需要已知的标准条目，未鉴定请选未确认')
    return value


def validate_scene(raw):
    if not isinstance(raw, dict) or set(raw) != KEYS or type(raw['format']) is not int or raw['format'] != 1:
        raise ValueError('角色条件格式不正确')
    optional_int(raw['base_strength'], '基础力量', 1, 1000)
    optional_int(raw['strongman'], '力大无穷天赋点数', 0, 3)
    optional_int(raw['adrenaline'], '激素涌动力量', 0, 1000)
    optional_int(raw['spirit_level'], '精神形态戒指等级', 0, 4)
    for key in ('magic_immune', 'spirit_form', 'spirit_cursed'):
        if raw[key] is not None and type(raw[key]) is not bool:
            raise ValueError('临时状态需要明确选择，未确认不能当作没有')
    if raw['spirit_ring'] != 'none':
        ring_identity(raw['spirit_ring'])
    if not isinstance(raw['rings'], list) or len(raw['rings']) > 2:
        raise ValueError('普通角色条件最多包含两个实际装备的戒指')
    for ring in raw['rings']:
        if not isinstance(ring, dict) or set(ring) != {'identity', 'level', 'cursed'}:
            raise ValueError('戒指条件格式不正确')
        ring_identity(ring['identity'])
        optional_int(ring['level'], '戒指等级', -100, 100)
        if ring['cursed'] is not None and type(ring['cursed']) is not bool:
            raise ValueError('戒指诅咒需要明确选择')
    return copy.deepcopy(raw)


def empty_scene(base=10):
    return {'format': 1, 'base_strength': base, 'rings': [], 'strongman': 0,
            'adrenaline': 0, 'magic_immune': False, 'spirit_form': False,
            'spirit_ring': None, 'spirit_level': None, 'spirit_cursed': None}


def solo_bonus(level, cursed):
    return min(0, level - 2) if cursed else level + 1


def calculate_scene(raw):
    params = validate_scene(raw)
    missing = []
    for key, label in (('base_strength', '基础力量'), ('strongman', '力大无穷天赋点数'), ('adrenaline', '激素涌动力量')):
        if params[key] is None:
            missing.append(label)
    bonus = 0
    if params['magic_immune'] is True:
        pass
    elif params['magic_immune'] is None:
        missing.append('魔法免疫状态')
    else:
        for index, ring in enumerate(params['rings']):
            if ring['identity'] is None:
                missing.append('戒指' + str(index + 1) + '身份')
            elif ring['identity'] == MIGHT:
                if ring['level'] is None or ring['cursed'] is None:
                    missing.append('根骨之戒' + str(index + 1) + '等级或诅咒')
                else:
                    bonus += solo_bonus(ring['level'], ring['cursed'])
        # The virtual ring is a fallback only when ordinary ring bonuses sum to zero.
        if bonus == 0:
            if params['spirit_form'] is None:
                missing.append('精神形态状态')
            elif params['spirit_form']:
                if params['spirit_ring'] is None:
                    missing.append('精神形态戒指身份（非戒指效果请选择无戒指）')
                elif params['spirit_ring'] == MIGHT:
                    if params['spirit_level'] is None or params['spirit_cursed'] is None:
                        missing.append('精神形态根骨之戒等级或诅咒')
                    else:
                        bonus += solo_bonus(params['spirit_level'], params['spirit_cursed'])
    base, points, surge = (params[key] for key in ('base_strength', 'strongman', 'adrenaline'))
    talent = None
    if base is not None and points is not None:
        coefficient = f(f(.03) + f(f(.05) * points))
        talent = math.floor(f(base * coefficient)) if points else 0
    total = None if missing else base + bonus + surge + talent
    return {'kind': 'character', 'version': '4.0.2', 'params': params,
            'strength': {'state': 'pending' if missing else 'known', 'effective': total,
                         'base': base, 'usable': total is not None and 1 <= total <= 1000,
                         'components': {'base': base, 'might_rings': None if missing else bonus,
                                        'adrenaline': surge, 'strongman': talent}, 'missing': missing},
            'boundary': '按所列角色条件计算总力量；其他战斗加成和装备本身效果仍需单独核对。'}


def scene_from_game(game, catalog, items):
    hero = game.get('hero') if isinstance(game.get('hero'), dict) else {}
    if isinstance(hero.get('character_scene'), dict):
        # A manual draft explicitly carries its conditions; base must agree with the form.
        raw = validate_scene(hero['character_scene'])
        if raw['base_strength'] != hero.get('STR'):
            raise ValueError('局势基础力量与共享角色条件不一致，请重新核对')
        return calculate_scene(raw)
    base = hero.get('STR')
    raw = empty_scene(base if type(base) is int and 1 <= base <= 1000 else None)
    raw['strongman'] = talent_points(hero, 'STRONGMAN')
    buffs = hero.get('buffs', [])
    if not isinstance(buffs, list) or any(not isinstance(buff, dict) for buff in buffs):
        raw.update(adrenaline=None, magic_immune=None, spirit_form=None)
        return calculate_scene(raw)
    kinds = {buff.get('__className'): buff for buff in buffs}
    raw['magic_immune'] = PREFIX + 'actors.buffs.MagicImmune' in kinds
    surges = [buff for buff in buffs if buff.get('__className') == PREFIX + 'actors.buffs.AdrenalineSurge']
    if surges:
        boost = surges[0].get('boost')
        raw['adrenaline'] = boost if len(surges) == 1 and type(boost) is int and 0 <= boost <= 1000 else None
    for item in items:
        if item.get('location') in ('戒指', '饰品') and item.get('available') is True and item['key'].startswith('items.rings.'):
            raw['rings'].append({'identity': item['key'] if item['known'] else None,
                                 'level': item['level'] if type(item['level']) is int and -100 <= item['level'] <= 100 else None,
                                 'cursed': item['cursed']})
    spirit = kinds.get(PREFIX + 'actors.hero.spells.SpiritForm$SpiritFormBuff')
    raw['spirit_form'] = spirit is not None
    if spirit is not None:
        effect = spirit.get('effect')
        if isinstance(effect, dict):
            if catalog.key(effect).startswith('items.rings.'):
                public = catalog.item(effect, game)
                raw['spirit_ring'] = public['key'] if public['known'] else None
                raw['spirit_level'] = talent_points(hero, 'SPIRIT_FORM')
                # The spell creates a fresh uncursed effect; it is not a random loot roll.
                raw['spirit_cursed'] = False if effect.get('cursed', False) is False else public['cursed']
            elif catalog.key(effect).startswith('items.artifacts.'):
                raw['spirit_ring'] = 'none'
    return calculate_scene(raw)
