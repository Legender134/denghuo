"""Bounded ordinary melee conditions from SPD 4.0.2, GPL-3.0-or-later.

Hero.attackSkill/damageRoll, Weapon.delayFactor and Ring.getBuffedBonus,
commit 57a4e06a4caf162446d1c28caa7983f0493fecf0.
Oleg Dolya 2012-2015; Evan Debenham 2014-2026.
No random distribution, proc, mean DPS or time-to-kill is inferred.
"""
import copy
import json
import math

from .game_math import float32 as f, augmented_damage
from .character_scene import solo_bonus

MODEL = 'ordinary-v1'
TARGET_KEYS = {'format', 'name', 'base_accuracy', 'evasion', 'dr_min', 'dr_max'}


def validate_target(raw):
    if isinstance(raw, str):
        if len(raw) > 1500:
            raise ValueError('目标条件过大')
        try:
            raw = json.loads(raw)
        except (ValueError, RecursionError) as exc:
            raise ValueError('目标条件格式不正确') from exc
    if not isinstance(raw, dict) or set(raw) != TARGET_KEYS or type(raw['format']) is not int or raw['format'] != 1:
        raise ValueError('目标条件格式不正确')
    if not isinstance(raw['name'], str) or not 1 <= len(raw['name'].strip()) <= 80 or any(ord(c) < 32 for c in raw['name']):
        raise ValueError('请填写1–80字的目标场景名称')
    for key in ('base_accuracy', 'evasion', 'dr_min', 'dr_max'):
        if raw[key] is not None and (type(raw[key]) is not int or not 0 <= raw[key] <= 1000000):
            raise ValueError('目标命中、闪避和减伤需要0–1000000整数，未确认请留空')
    if raw['dr_min'] is not None and raw['dr_max'] is not None and raw['dr_min'] > raw['dr_max']:
        raise ValueError('目标减伤下限不能高于上限')
    return copy.deepcopy(raw)


def canonical_combat(raw, result, kind):
    if 'combat_model' in raw:
        if raw['combat_model'] != MODEL or kind != 'weapon':
            raise ValueError('普通持械近战模型仅用于普通近战武器')
        result['combat_model'] = MODEL
    if 'target_context' in raw:
        if result.get('combat_model') != MODEL:
            raise ValueError('目标条件需要明确启用普通持械近战模型')
        result['target_context'] = validate_target(raw['target_context'])


def ring_effect(scene, identity):
    """Resolve one buffed ring type; unrelated unknown grades do not block it."""
    if scene is None:
        return {'value': 0, 'missing': [], 'source': '未附共享角色，明确按无戒指假设'}
    missing, total = [], 0
    if scene['magic_immune'] is True:
        return {'value': 0, 'missing': [], 'source': '魔法免疫抑制戒指'}
    if scene['magic_immune'] is None:
        missing.append('魔法免疫状态')
    enhanced = scene.get('enhanced_rings', False)
    for index, ring in enumerate(scene['rings']):
        if ring['identity'] is None:
            missing.append('戒指' + str(index + 1) + '身份')
        elif ring['identity'] == identity:
            if ring['level'] is None or ring['cursed'] is None:
                missing.append('同类型戒指' + str(index + 1) + '等级或诅咒')
            elif enhanced is None:
                missing.append('戒指增强状态')
            else:
                total += solo_bonus(ring['level'] + int(enhanced), ring['cursed'])
    if not missing and total == 0:
        if scene['spirit_form'] is None:
            missing.append('精神形态状态')
        elif scene['spirit_form']:
            if scene['spirit_ring'] is None:
                missing.append('精神形态戒指身份')
            elif scene['spirit_ring'] == identity:
                if scene['spirit_level'] is None or scene['spirit_cursed'] is None or enhanced is None:
                    missing.append('精神形态等级、诅咒或戒指增强状态')
                else:
                    total += solo_bonus(scene['spirit_level'] + int(enhanced), scene['spirit_cursed'])
    return {'value': None if missing else total, 'missing': missing,
            'source': '同类型普通戒指合计；为0时使用精神形态后备；增强仅加buffed等级'}


def hit_probability(accuracy, evasion):
    # Char.hit: infinite evasion wins even over infinite accuracy.
    if evasion >= 1000000:
        return 0
    if accuracy >= 1000000 or evasion == 0:
        return 1
    return 1 - evasion / (2 * accuracy) if accuracy >= evasion else accuracy / (2 * evasion)


def ordinary_metrics(values, raw, side, level, strength):
    if raw.get('combat_model') != MODEL:
        return []
    from .engine import strength_requirement
    from .values import metric
    identity = raw['id_' + side]
    entry = next(e for e in values.catalog.entries if e['id'] == identity)
    owner = values.identity(entry)
    constants = values.rules.constants(owner)
    tier = constants['tier'] + (1 if identity.endswith('.greataxe') else 0)
    need = strength_requirement(tier, level, raw['mastery_' + side] == '1')
    deficit = max(0, need - strength)
    damage_factor, delay_factor = {'NONE': (1, 1), 'SPEED': (.7, f(f(2) / 3)), 'DAMAGE': (1.5, f(f(5) / 3))}[raw['augment_' + side]]
    low, high = [augmented_damage(max(0, values.rules.calculate(owner, method, [level], level)), damage_factor) for method in ('min', 'max')]
    extra = max(0, strength - need)
    scene = raw.get('character_scene')
    force, furor, accuracy = [ring_effect(scene, 'items.rings.ringof' + name) for name in ('force', 'furor', 'accuracy')]
    boundary = '普通持械近战；含力量不足、强化及所列武力/狂怒/精准戒指；不含附魔、诅咒效果、剑舞、拳击架势、偷袭、其他天赋状态或目标特殊结算'
    rows = []
    def resolved(label, effect, unit, transform=lambda value: value):
        rows.append(metric(label, transform(effect['value']) if effect['value'] is not None else '待确认', unit,
                           boundary + '；' + ('待确认：' + '、'.join(effect['missing']) if effect['missing'] else effect['source'])))
    resolved('普通近战武力加值', force, 'HP')
    resolved('普通近战精准戒指倍率', accuracy, '倍', lambda value: f(math.pow(f(1.3), value)))
    speed = None if furor['value'] is None else f(math.pow(1.09051, furor['value']))
    base_delay = f(f(constants.get('DLY', 1)) * f(delay_factor))
    if deficit:
        base_delay = f(base_delay * math.pow(1.2, deficit))
    delay = None if speed is None else f(base_delay * f(f(1) / speed))
    resolved('普通近战攻击耗时', furor, '回合', lambda _: delay)
    damage = None if force['value'] is None else (max(0, low + force['value']), max(0, high + extra + force['value']))
    rows.append(metric('普通近战命中前伤害范围', '待确认' if damage is None else f'{damage[0]}–{damage[1]}', 'HP',
                       boundary + '；包括0到额外力量上限；范围端点不表示等概率或平均伤害'))
    target = raw.get('target_context')
    if target:
        condition = '手填目标「' + target['name'] + '」；' + boundary
        attack = None
        if target['base_accuracy'] is not None and accuracy['value'] is not None:
            multiplier = f(math.pow(f(1.3), accuracy['value']))
            weapon_factor = f(f(constants.get('ACC', 1)) / math.pow(1.5, deficit))
            # Hero multiplies and rounds floats, then clamps to at least 1.
            attack = max(1, min(2147483647, math.floor(f(f(target['base_accuracy'] * multiplier) * weapon_factor) + .5)))
        rows.append(metric('目标模型有效命中', attack if attack is not None else '待确认', '点', condition + '；基础命中为未乘武器/戒指的手填attackSkill，不由英雄等级推断'))
        chance = None if attack is None or target['evasion'] is None else 100 * hit_probability(attack, target['evasion'])
        rows.append(metric('目标模型命中率参考', chance if chance is not None else '待确认', '%', condition + '；普通独立均匀抽样的连续解析参考；百万闪避优先视为必闪，百万命中视为必中；不预测具体下一击'))
        after = None if damage is None or target['dr_min'] is None or target['dr_max'] is None else (max(0, damage[0] - target['dr_max']), max(0, damage[1] - target['dr_min']))
        rows.append(metric('目标模型命中后扣血范围', '待确认' if after is None else f'{after[0]}–{after[1]}', 'HP', condition + '；仅以手填DR上下限相减并归零，不含防御触发、抗性或易伤；不推算平均DPS或击杀回合'))
    return rows
