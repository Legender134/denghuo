"""Dew recovery ported from Shattered Pixel Dungeon 4.0.2 (GPL-3.0-or-later).

Sources: Waterskin.execute, Dewdrop.consumeDew, VialOfBlood and Healing.setHeal.
Use the game's single precision arithmetic before Java's Math.round operations.
"""
import math
from .game_math import float32 as f


def rounded(value):
    return math.floor(value+.5)


def dew_effect(hp,maximum,drops,shielding=0,current_shield=0,vial=-1):
    effect=rounded(f(f(maximum*f(.05))*drops))
    heal=min(maximum-hp,effect)
    shield=0
    multiplier=1+.125*(vial+1) if vial>=0 else 1
    if shielding:
        if drops>1 and heal<effect and vial>=0:
            heal=rounded(f(heal/multiplier))
        cap=rounded(f(f(maximum*f(.2))*shielding))
        shield=max(0,min(effect-heal,cap-current_shield))
    gradual=heal>0 and drops>1 and vial>=0
    amount=rounded(f(heal*multiplier)) if gradual else heal
    caps=(4+rounded(f(f(.15)*maximum)),3+rounded(f(f(.1)*maximum)),
          2+rounded(f(f(.07)*maximum)),1+rounded(f(f(.05)*maximum)))
    left,current,schedule=amount,hp,[]
    while gradual and left:
        tick=min(left,caps[vial])
        actual=min(maximum-current,tick)
        current+=actual
        left-=tick
        schedule.append([len(schedule)+1,tick,actual,current,left])
    return {'effect':effect,'pool':amount,'actual_heal':min(maximum-hp,amount),
            'shield':shield,'gradual':gradual,'schedule':schedule,
            'first_heal':schedule[0][2] if schedule else amount}


def water_drink(hp,maximum,volume,shielding=0,current_shield=0,vial=-1):
    if not volume:
        return {'consumed':0,'remaining':0,'actual_heal':0,'shield':0,'pool':0,'effect':0,
                'gradual':False,'schedule':[],'first_heal':0}
    missing=f(1-f(hp/maximum))
    needed=f(missing/f(.05))
    if needed>f(1.01) and vial>=0:
        needed=f(needed/(1+.125*(vial+1)))
    cap=rounded(f(f(maximum*f(.2))*shielding))
    # Java's zero-cap branch is NaN or negative Infinity, so adds no drops.
    if shielding and cap:
        missing_shield=f(1-f(current_shield/cap))
        missing_shield=f(missing_shield*f(f(.2)*shielding))
        if missing_shield>0:needed=f(needed+f(missing_shield/f(.05)))
    consumed=min(volume,max(1,math.ceil(f(needed-f(.01)))))
    return {'consumed':consumed,'remaining':volume-consumed,
            **dew_effect(hp,maximum,consumed,shielding,current_shield,vial)}


def add_resource_values(identity,p,result,requested):
    if identity!='items.waterskin':return
    from .values import block,metric,table
    requested.update(('hp','max_hp','dew_volume','shielding_dew','current_shield','vial'))
    outcome=water_drink(p['hp'],p['max_hp'],p['dew_volume'],p['shielding_dew'],p['current_shield'],p['vial'])
    result.insert(0,block('按所填露珠条件计算',[
        metric('本次消耗露珠',outcome['consumed'],'滴'),
        metric('饮用后剩余露珠',outcome['remaining'],'滴'),
        metric('首次恢复',outcome['first_heal'],'HP','逐次恢复' if outcome['gradual'] else '即时恢复'),
        metric('最终实际恢复',outcome['actual_heal'],'HP','不含正在生效的其他治疗'),
        metric('实际新增屏障',outcome['shield'],'点','按所填护盾露珠天赋与现有屏障'),
        metric('治疗池总量',outcome['pool'],'HP','满血后的剩余额度会继续消耗' if outcome['gradual'] else '即时恢复，无新增治疗池'),
        metric('饮用耗时',1 if p['dew_volume'] else 0,'回合','按所填水量饮用' if p['dew_volume'] else '空水袋未执行饮用'),
    ],'按所填生命、露珠、天赋、现有屏障和凝血试管计算；这些条件不是已确认的实时游戏状态。'))
    result.append(block('露珠生效条件',[
        metric('每滴基础恢复量',rounded(f(p['max_hp']*f(.05))),'HP','单滴，按最大生命的5%取整'),
        metric('露珠容量',20,'滴'),
        metric('所填天赋的屏障上限',rounded(f(f(p['max_hp']*f(.2))*p['shielding_dew'])),'点'),
    ],'多滴露珠合并后取整，不等于把单滴取整结果相加。多滴且凝血试管生效时逐次治疗，单滴不受试管倍率加成。满血且没有可增加屏障时，强制饮用仍会消耗至少1滴。已有治疗池/速度按游戏取较大值，不能直接把两次总量相加。'))
    if outcome['schedule']:
        result.append(table('本次新增治疗池逐次恢复',['更新次序','本次额度','实际恢复HP','恢复后生命','剩余额度'],
                            outcome['schedule'],'只按本次新增的独立治疗计算，不含已存在的治疗池、持续伤害、状态阻碍和其他生命变化。'))
    if p['dew_volume']==0:
        result.append(block('空水袋',[metric('可恢复生命',0,'HP')],'没有露珠，本次无法饮用露珠恢复生命。'))
