"""Reuse a fixed public character scene without counting a replaced ring twice."""
import copy
import json

from .character_scene import calculate_scene, validate_scene


SCENE_KEYS = {'character_scene', 'scene_ring_slot'}


def canonical_scene(raw, result, kind):
    if 'character_scene' not in raw:
        if 'scene_ring_slot' in raw:
            raise ValueError('替换戒指槽位需要共享角色条件')
        return
    scene = raw['character_scene']
    if isinstance(scene, str):
        if len(scene) > 6000:
            raise ValueError('角色条件过大')
        try:
            scene = json.loads(scene)
        except (ValueError, RecursionError) as exc:
            raise ValueError('角色条件格式不正确') from exc
    result['character_scene'] = validate_scene(scene)
    if kind == 'ring':
        from .values_decisions import bounded_integer
        slot = bounded_integer(raw.get('scene_ring_slot', 0), '替换戒指条件', 0, 1)
        if slot > len(scene['rings']):
            raise ValueError('请先填写该戒指槽位之前的角色条件')
        result['scene_ring_slot'] = slot
        for side in ('a', 'b'):
            other = next((ring for index, ring in enumerate(scene['rings']) if index != slot), None)
            pair = other is not None and other['identity'] == result['id_' + side]
            if pair and (other['level'] is None or other['cursed'] is None):
                raise ValueError('共享条件中另一枚同类型戒指的等级或诅咒未确认')
            result['ring_pair_' + side] = '1' if pair else '0'
            result['ring_pair_level_' + side] = other['level'] if pair else 0
            result['ring_pair_curse_' + side] = '1' if pair and other['cursed'] else '0'
    elif 'scene_ring_slot' in raw:
        raise ValueError('只有戒指比较使用替换槽位')
    for side in ('a', 'b'):
        for increment in (0, 1):
            comparison_scene(result, side, result['level_' + side] + increment,
                             result.get('strength_budget', 0))


def comparison_scene(raw, side, level, strength_budget=0, clear_curse=False):
    if 'character_scene' not in raw:
        return None
    scene = copy.deepcopy(raw['character_scene'])
    if scene['base_strength'] is not None:
        scene['base_strength'] += strength_budget
    if raw['id_' + side].startswith('items.rings.'):
        curse = '0' if clear_curse else raw['curse_' + side]
        ring = {'identity': raw['id_' + side], 'level': level,
                'cursed': None if curse == 'unknown' else curse == '1'}
        slot = raw['scene_ring_slot']
        if slot == len(scene['rings']):
            scene['rings'].append(ring)
        else:
            scene['rings'][slot] = ring
    result = calculate_scene(scene)
    if not result['strength']['usable']:
        missing = '、'.join(result['strength']['missing']) or '力量超出可用范围'
        raise ValueError(side.upper() + '侧共享角色条件尚不能确定总力量：' + missing)
    result['replacement'] = ('替换角色条件中的戒指' + str(raw['scene_ring_slot'] + 1)
                             if 'scene_ring_slot' in raw else '共同角色条件')
    result['assumption'] = ('备选戒指等级按明确手填假设' if raw.get('level_known_' + side) == '0'
                            else '所列条件固定参考；升级不保证解咒')
    return result


def comparison_strength(raw, side, level, strength_budget=0, clear_curse=False):
    scene = comparison_scene(raw, side, level, strength_budget, clear_curse)
    return scene['strength']['effective'] if scene else raw['strength'] + strength_budget


def attach_scenes(result, raw):
    if 'character_scene' not in raw:
        return result
    for side, choice in zip(('a', 'b'), result['choices']):
        choice['character_scene'] = comparison_scene(raw, side, choice['level'])
        choice['upgraded_character_scene'] = comparison_scene(raw, side, choice['level'] + 1)
        if choice.get('after_curse_removed'):
            choice['uncursed_character_scene'] = comparison_scene(raw, side, choice['level'] + 1, clear_curse=True)
    result['notice'] = result['notice'].replace('未合并戒指、天赋、诅咒、偷袭伤害和临时状态', '未合并除力量来源外的戒指、天赋、诅咒、偷袭伤害和临时战斗效果').replace('未计其他戒指、天赋、魔法免疫或临时等级', '未计未填写的其他戒指、天赋或临时等级')
    result['notice'] += ' 共享角色条件已计入基础力量、根骨之戒、力大无穷天赋及所列临时力量；未计其他战斗效果。戒指比较按明确槽位替换，A、B各自计算，不重复佩戴原戒指。'
    if result.get('explanation'):
        result['explanation']['boundary'] = result['notice']
    return result
