"""Reviewed operation risks and equipment comparisons for players."""
import math
from .game_math import augmented_damage

DEFENSIVE_WEAPONS={'roundshield':(3,4,1),'greatshield':(5,6,2),
                   'quarterstaff':(2,2,0),'katana':(4,3,0),'rapier':(1,1,0)}
CLASS_ARMORS={'warriorarmor','magearmor','roguearmor','huntressarmor','duelistarmor','clericarmor'}


def armor_ranges(tier, level, augment='NONE'):
    defense={'NONE':0,'EVASION':-1,'DEFENSE':1}[augment]*(2+level)
    maximum=tier*(2+level)+defense
    if level>maximum: maximum=(level-maximum+1)//2
    minimum=level-maximum if level>=maximum else level
    return minimum,maximum,1+tier+level+defense

def passive_defense(identity, level):
    _,base,scaling=DEFENSIVE_WEAPONS.get(identity.rsplit('.',1)[-1],(0,0,0))
    return base+level*scaling
def upgrade_risk(level, hardened=False):
    threshold = 6 if hardened else 4
    return 0 if level < threshold else min(100, 10 * 2 ** (level - threshold))


def add_operation_values(identity, p, result, requested):
    from .values import block, metric, table
    if identity == 'items.scrolls.scrollofupgrade':
        requested.add('level')
        level = p['level']
        result.append(block(f'从 +{level} 升到 +{level+1} 的风险', [
            metric('普通附魔 / 刻印消失', upgrade_risk(level), '%', '有正常附魔或刻印，且未硬化'),
            metric('硬化保护消失', upgrade_risk(level, True), '%', '装备已硬化且有附魔或刻印；本次保留附魔或刻印'),
            metric('无附魔 / 刻印时硬化保护消失', 0, '%', '无附魔或刻印的硬化装备，升级不会触发损失判定'),
            metric('诅咒附魔 / 刻印移除', 100/3, '%', '有诅咒附魔或刻印且未硬化；不是普通附魔消失概率'),
            metric('装备绑定诅咒解除', 100, '%', '不等于保证移除诅咒附魔或刻印'),
        ], '等级填写升级前的装备等级。普通、硬化、诅咒三种分支分别判断，不把概率相加。护甲刻印的普通概率按无蜕变刻印转移天赋计算。'))
        result.append(table('普通附魔与硬化风险对照', ['升级前等级', '普通附魔 / 刻印消失%', '硬化保护消失%'],
                            [[f'+{n}', upgrade_risk(n), upgrade_risk(n, True)] for n in range(11)],
                            '损失概率仅用于已有附魔或刻印的装备；无附魔/刻印的硬化装备为0%。使用注魔菱晶升级时保留附魔、刻印与诅咒，和升级卷轴不同。'))
        result.append(table('非战士蜕变获得刻印转移：普通护甲刻印消失概率',
                            ['升级前等级', '天赋0点%', '天赋1点%', '天赋2点%'],
                            [[f'+{n}', upgrade_risk(n), upgrade_risk(n) if n >= 6 else 0,
                              upgrade_risk(n) if n >= 7 else 0] for n in range(4, 9)],
                            '只影响普通护甲刻印分支；战士本职天赋、硬化和诅咒分支不套用此表。'))
    elif identity == 'actors.buffs.combo':
        result.append(block('连击保持时间', [metric('每次命中后的最低保持时间', 5, '回合'),
            metric('击杀后基础保持时间', 15, '回合')],
            '倒计时归零时断连；命中不会缩短已有的更长计时。腐化后满血的目标也触发击杀分支。'))
        result.append(table('连斩天赋：击杀后的保持时间', ['天赋点数', '保持回合'], [[n, 15+15*n] for n in range(4)]))
        result.append(table('不动如山生效期间的倒计时', ['天赋点数', '每过1回合减少', '5回合计时可保持'],
                            [[0, 1, 5], [1, .5, 10], [2, .25, 20], [3, 0, '原地生效期间暂停']],
                            '需已触发不动如山并留在原地；移动后恢复正常倒计时。'))
    elif identity == 'items.stones.stoneofaugmentation':
        result.append(table('武器强化对照', ['强化', '基础伤害倍率', '攻击耗时倍率'],
                            [['无', 1, 1], ['速度', .7, 2/3], ['伤害', 1.5, 5/3]],
                            '伤害按游戏取整；额外力量伤害与其他效果需单独计算。护甲强化的效果受阶数与等级影响。'))
        requested.add('level')
        level=p['level']
        result.append(table(f'护甲 +{level} 强化的数值变化', ['强化','闪避值加减','减伤上限加减'],
            [['无',0,0],['闪避',2*(2+level),-(2+level)],['防御',-2*(2+level),2+level]],
            '闪避加减在力量不足的惩罚后计入；减伤范围重新按护甲阶数计算，不能只把该数字加到范围两端。'))
    if identity.startswith('items.weapon.melee.') and passive_defense(identity, p['level']):
        requested.update(('level','strength'))
        tier=DEFENSIVE_WEAPONS[identity.rsplit('.',1)[-1]][0]
        from .engine import strength_requirement
        need=strength_requirement(tier,p['level'])
        result.append(block('武器自身的防御',[
            metric('额外减伤基础范围',f'0–{passive_defense(identity,p["level"])}','HP'),
            metric('按所填力量的额外减伤',f'0–{max(0,passive_defense(identity,p["level"])-2*max(0,need-p["strength"]))}','HP')],
            '普通持武器状态；不含精通药剂、拳击架势、天赋与其他修正。力量不足会降低防御。'))


def equipment_metrics(values, identity, level, tier=3):
    """Only return supported base stats; never fabricate zero for a missing stat."""
    detail = values.detail(identity, {'level': level,'tier':tier})
    metrics = {v['label']: v['value'] for b in detail['blocks'] for v in b.get('values', [])}
    labels = ('最低基础伤害', '最高基础伤害', '力量需求', '命中倍率', '攻击耗时', '攻击距离')
    current = next((b for b in detail['blocks'] if b['title'] == f'当前 +{level} 装备数值'), None)
    if identity.startswith('items.armor.'):
        labels = ('常规减伤','信念护体','力量需求') if identity.rsplit('.',1)[-1] in CLASS_ARMORS else tuple(v['label'] for v in (current or {}).get('values', []))
    return {key: metrics[key] for key in labels if key in metrics}


def compare_equipment(values, raw):
    from .rules import display
    choices = []
    for suffix in ('a', 'b'):
        identity = raw.get('id_'+suffix, '')
        entry = next((e for e in values.catalog.entries if e['id'] == identity), None)
        if not entry or not identity.startswith(('items.weapon.melee.', 'items.armor.')) or '$' in identity or identity.endswith('.ability'):
            raise ValueError('请选择普通近战武器或护甲')
        level = int(raw.get('level_'+suffix, 0))
        if not 0 <= level <= 99:
            raise ValueError('比较等级需要是0–99；升级后最多+100')
        armor_tier=int(raw.get('tier_'+suffix,3))
        if not 1<=armor_tier<=5: raise ValueError('原护甲阶数需要是1–5')
        current = equipment_metrics(values, identity, level,armor_tier)
        upgraded = equipment_metrics(values, identity, level+1,armor_tier)
        if not current or not upgraded:
            raise ValueError('这件特殊装备尚不能比较；请查看它的独立数值页')
        mastery = raw.get('mastery_'+suffix, '0')
        augment = raw.get('augment_'+suffix, 'NONE')
        armor=identity.startswith('items.armor.')
        if mastery not in ('0', '1') or augment not in (('NONE','EVASION','DEFENSE') if armor else ('NONE','SPEED','DAMAGE')):
            raise ValueError('请核对精通和强化选项')
        strength = int(raw.get('strength', 10))
        if not 1 <= strength <= 1000:
            raise ValueError('力量需要是1–1000')
        for actual_level,stats in ((level,current),(level+1,upgraded)):
            if '力量需求' in stats:
                need = int(stats['力量需求']) - (2 if mastery == '1' else 0)
                stats['力量需求'] = str(need)
                stats['力量缺口'] = str(max(0, need-strength))
                deficit = max(0, need-strength)
                if not armor:
                    damage_factor = {'NONE': 1, 'SPEED': .7, 'DAMAGE': 1.5}[augment]
                    delay_factor = {'NONE': 1, 'SPEED': 2/3, 'DAMAGE': 5/3}[augment]
                    for label in ('最低基础伤害', '最高基础伤害'):
                        if label in stats: stats[label] = str(augmented_damage(float(stats[label]),damage_factor))
                    if '攻击耗时' in stats: stats['攻击耗时'] = display(float(stats['攻击耗时'])*delay_factor*1.2**deficit)
                    if '命中倍率' in stats: stats['命中倍率'] = display(float(stats['命中倍率'])/1.5**deficit)
                    stats['额外力量伤害'] = f'0–{max(0, strength-need)}'
                    stats['武器额外减伤'] = f'0–{max(0,passive_defense(identity,actual_level)-2*deficit)}'
                    stats['力量与武器允许偷袭'] = '否' if deficit or identity.endswith('.flail') else '是'
                else:
                    tail=identity.rsplit('.',1)[-1]
                    tier=armor_tier if tail in CLASS_ARMORS else next((v for k,v in values.catalog.data['tiers'].items() if k.lower()==tail),None)
                    if tier is None:
                        raise ValueError('特殊护甲请查看独立数值页')
                    normal_min,normal_max,challenge_max=armor_ranges(tier,actual_level,augment)
                    stats['常规减伤']=f'{max(0,normal_min-2*deficit)}–{max(0,normal_max-2*deficit)}'
                    stats['信念护体']=f'0–{max(0,challenge_max-2*deficit)}'
                    stats['护甲闪避惩罚倍率']=display(1/1.5**deficit)
                    stats['护甲强化闪避加值']=str({'NONE':0,'EVASION':2,'DEFENSE':-2}[augment]*(2+actual_level))
                    stats['移动速度倍率']=display(1/1.2**deficit)
        choices.append({'id': identity, 'name': entry['name'], 'level': level, 'current': current, 'upgraded': upgraded,
                        'upgrade_risk': upgrade_risk(level)})
    if choices[0]['id'].startswith('items.armor.') != choices[1]['id'].startswith('items.armor.'):
        raise ValueError('武器与武器、护甲与护甲分别比较')
    rows = []
    for label in dict.fromkeys(k for choice in choices for k in choice['current']):
        columns = [choice[phase].get(label, '未核对') for choice in choices for phase in ('current', 'upgraded')]
        try:
            delta = f'{float(columns[2])-float(columns[0]):+g}'
        except ValueError:
            delta = '见范围'
        rows.append({'label': label, 'values': columns, 'difference': delta})
    return {'choices': choices, 'rows': rows, 'version': values.catalog.data['version'],
            'notice': '普通攻击与持装备的基础数值，已计所填有效力量、强化和精通；伤害与力量追加分列。减伤已扣力量不足惩罚，护甲闪避加值在惩罚后计入。未合并戒指、天赋、诅咒、偷袭伤害和临时状态；信念护体一行仅在该挑战生效，不能当作最终总效果。未知等级手填试算不代表已鉴定。'}
