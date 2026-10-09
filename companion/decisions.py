"""Public-context decision paths; no hidden identities or game actions."""
from __future__ import annotations

FOODS = {kind: 'items.food.'+kind.lower() for kind in (
    'Food', 'SmallRation', 'SupplyRation', 'Pasty', 'Berry', 'ChargrilledMeat',
    'StewedMeat', 'FrozenCarpaccio', 'MysteryMeat', 'MeatPie', 'PhantomMeat', 'Blandfruit')}

RESOURCES = {
    'PotionOfHealing':('核对治疗','items.potions.potionofhealing'),
    'Waterskin':('核对露珠恢复','items.waterskin'),
    'PotionOfShielding':('核对护盾','items.potions.exotic.potionofshielding'),
    'PotionOfInvisibility':('核对脱离接触','items.potions.potionofinvisibility'),
    'ScrollOfTeleportation':('核对转移','items.scrolls.scrollofteleportation'),
    'StoneOfBlink':('核对定向转移','items.stones.stoneofblink'),
    'ScrollOfRemoveCurse':('核对解咒','items.scrolls.scrollofremovecurse'),
    'ScrollOfIdentify':('核对鉴定','items.scrolls.scrollofidentify'),
    'PotionOfStrength':('核对力量成长','items.potions.potionofstrength'),
    'ScrollOfUpgrade':('核对升级风险','items.scrolls.scrollofupgrade'),
    **{kind:('核对进食',entry) for kind,entry in FOODS.items()},
}
RISK_REFERENCES = {
    'critical_hp':('items.potions.potionofhealing','actors.buffs.healing'),
    'low_hp':('actors.buffs.healing',),
    'burning':('actors.buffs.burning','actors.buffs.levitation'),
    'ooze':('actors.buffs.ooze',),
    'corrosion':('actors.buffs.corrosion',),
    'dot':('actors.buffs.poison','actors.buffs.bleeding'),
    'roots':('actors.buffs.roots','items.stones.stoneofblink'),
    'cripple':('actors.buffs.cripple',),
    'lost_inventory':('actors.buffs.lostinventory',),
    'strength_potion':('items.potions.potionofstrength',),
    'upgrade_scroll':('items.scrolls.scrollofupgrade',),
    'unknown':('items.scrolls.scrollofidentify',),
    'pharmacophobia':('items.potions.potionofhealing',),
    'hungry':('actors.buffs.hunger','items.food.food'),
    'starving':('actors.buffs.hunger','items.food.food'),
}


def public_context(snapshot):
    data = {} if snapshot.get('error') else snapshot.get('data') or {}
    hero = data.get('hero',{})
    context = {key:value for key,value in {'hp':hero.get('hp'),'max_hp':hero.get('ht'),
            'hero_level':hero.get('level'),'strength':hero.get('strength'),'depth':data.get('depth')}.items()
            if value is not None}
    strength = data.get('character_scene', {}).get('strength', {})
    if strength.get('usable') is True:
        context['strength'] = strength['effective']
    barriers = [buff for buff in data.get('buffs',[]) if buff.get('kind') == 'Barrier']
    if len(barriers) == 1 and type(barriers[0].get('current_shield')) is int:
        context['current_shield'] = barriers[0]['current_shield']
    return context


def source(snapshot):
    return {'mode':snapshot['settings']['mode'],'snapshot_at':snapshot.get('modified') or None,
            'slot':snapshot.get('active_slot'), 'stale':bool(snapshot.get('stale')),
            'label':'手动填写' if snapshot['settings']['mode']=='manual' else '旧快照记录' if snapshot.get('stale') else '最近保存的记录'}


def context_actions(session,snapshot):
    provenance = source(snapshot)
    data = snapshot.get('data')
    if not data or snapshot.get('error'):
        return {'state':'no-current-state','source':provenance,'risks':[],'options':[],
                'message':'可先查资料和试算；当前角色与资源尚未确认'}
    hero = data['hero']
    buffs = {buff['kind'] for buff in data.get('buffs',[])}
    blocked = bool(buffs & {'Paralysis','TimeStasis','Frost','MagicalSleep'})
    entries = {entry['id']:entry for entry in session.catalog.entries}
    common_params = public_context(snapshot)
    risks = []
    known_available = [item for item in data.get('items',[]) if item.get('known') and item.get('available') is True]
    for tip in data.get('tips',[]):
        identities = RISK_REFERENCES.get(tip['id'],())
        if tip['id'].startswith('curse_'):
            identities = ('items.scrolls.scrollofremovecurse',)
        elif tip['id'] in ('strength_主武器', 'strength_副武器', 'strength_护甲'):
            place = tip['id'].split('_',1)[1]
            identities = tuple(item['key'] for item in known_available if item['location']==place)
        elif tip['id']=='paralysis':
            identities = tuple('actors.buffs.'+kind.lower() for kind in sorted(buffs & {'Paralysis','TimeStasis','Frost','MagicalSleep'}))
        elif tip['id']=='boss_next':
            boss = {4:'goo',9:'tengu',14:'dm300',19:'dwarfking',24:'yogdzewa'}.get(data['depth'])
            identities = ('actors.mobs.'+boss,) if boss else ()
        if tip['id']=='dot':
            identities = tuple(entry for entry in identities if entry.rsplit('.',1)[-1] in {kind.lower() for kind in buffs})
        references = [{'entry':entry,'name':entries[entry]['name'],'params':dict(common_params),
                       'level_origin':'example',
                       'source_label':'资料参考 · 实际资源与行动条件请另行核对'} for entry in identities if entry in entries]
        if tip['id'] in ('strength_主武器', 'strength_副武器', 'strength_护甲'):
            for reference in references:
                item=next(item for item in known_available if item['key']==reference['entry'] and item['location']==tip['id'].split('_',1)[1])
                if item.get('level') is not None:reference['params']['level']=item['level']
                if item.get('tier') is not None:reference['params']['tier']=item['tier']
                reference['level_origin']='known' if item.get('level') is not None else 'unknown'
                reference['source_label']='已知装备记录；总力量与实际生效条件仍需按游戏核对'
        risks.append({'id':tip['id'],'title':tip['title'],'references':references})
    grouped = {}
    for item in known_available:
        if item['kind'] not in RESOURCES:
            continue
        kind = item['kind']
        if kind in grouped:
            grouped[kind]['quantity'] += item['quantity']
            if kind=='Waterskin':
                grouped[kind]['params'].pop('dew_volume',None)
                grouped[kind]['calculation_missing']='记录中有多个水袋，请核对要使用的水袋露珠量、天赋与屏障后计算'
            continue
        purpose,entry = RESOURCES[kind]
        if entry not in entries:
            continue
        option = {'entry':entry,'name':item['name'],'quantity':item['quantity'], 'purpose':purpose,
                  'source':provenance,'params':dict(common_params),'values':[],
                  'restriction':'生命值为0；普通行动建议暂停，先核对复活或狂暴状态' if hero['hp']<=0 else
                                '当前状态限制主动行动；解除后再核对是否能使用' if blocked else '',
                  'calculation_missing':'', 'note':'所记资源需按当前游戏画面核对；资料入口不会替你操作游戏'}
        if kind in ('PotionOfHealing','Waterskin'):
            vials = [item for item in data.get('items',[]) if item.get('kind')=='VialOfBlood']
            if not vials:
                option['params']['vial'] = -1
            elif len(vials)==1 and vials[0].get('known') and vials[0].get('available') and vials[0].get('level_known') and type(vials[0].get('level')) is int and -1<=vials[0]['level']<=3:
                option['params']['vial'] = vials[0]['level']
            else:
                option['calculation_missing'] = '凝血试管等级或可用性未确认，请核对后计算'
            if kind=='PotionOfHealing':
                if '药水恐惧' in data.get('challenges',[]):
                    option['restriction']+=('；' if option['restriction'] else '')+'药水恐惧挑战：此药剂不恢复生命，改为中毒'
                if not 1<=hero['level']<=30 or not 0<=hero['hp']<=hero['ht']<=10000:
                    option['calculation_missing']='当前角色数值超出已核对的计算范围，请在游戏中核对'
                if data.get('compatibility_warning'):
                    option['calculation_missing']='存档与资料版本不同，先核对版本；不把参考治疗量当作此局确认结果'
                if 'Healing' in buffs:
                    option['calculation_missing']='已有治疗状态；治疗池和恢复速度不直接相加，请先核对当前治疗状态再试算'
                if not option['restriction'] and not option['calculation_missing']:
                    result=session.values.detail(entry,option['params'])
                    option['values']=[row for block in result['blocks'] for row in block.get('values',[])
                                      if row['label'] in ('首次恢复','最终实际恢复','治疗池耗尽')]
                    option['note']='逐次恢复，首次恢复与最终总量不同；治疗池不保证和正在生效的治疗叠加'
            else:
                option['params']={key:value for key,value in option['params'].items() if key in ('hp','max_hp','vial','current_shield')}
                if type(item.get('volume')) is int:option['params']['dew_volume']=item['volume']
                option['calculation_missing']=('护盾露珠天赋仍需核对；屏障与生命使用该保存记录，未确认参数仍是示例'
                    if 'current_shield' in option['params'] else '露珠量、护盾天赋与现有屏障需核对后计算；未确认的参数仍是示例')
                option['note']='凝血试管可能让多滴露珠逐次恢复；回血与护盾按实际分支分配'
        if kind in FOODS:
            add_food_context(session, data, kind, entry, option, known_available)
        grouped[kind]=option
    order = list(RESOURCES)
    options = sorted(grouped.values(),key=lambda row:order.index(next(kind for kind,value in RESOURCES.items() if value[1]==row['entry'])))
    return {'state':'manual' if provenance['mode']=='manual' else 'saved-stale' if provenance['stale'] else 'saved',
            'source':provenance, 'risks':risks,'options':options,
            'message':'核对当前可用资源，再查看条件与具体数值。旧快照和手动填写不会自动成为此刻确认信息。'}


def explain_comparison(result):
    explanations = []
    for marker,choice in zip(('A','B'),result['choices']):
        current,upgraded = choice['current'],choice['upgraded']
        deficit = int(current.get('力量缺口','0'))
        next_deficit = int(upgraded.get('力量缺口','0'))
        strength = ('按所填有效力量，目前差 '+str(deficit)+' 点。' if deficit else '按所填有效力量，当前达到力量需求。')
        if deficit and not next_deficit:
            threshold = '升级一次可跨过力量门槛。'
        elif next_deficit<deficit:
            threshold = f'升级一次后力量缺口降到 {next_deficit} 点，仍需核对惩罚。'
        elif current.get('力量需求')==upgraded.get('力量需求'):
            threshold = '升级一次不会降低力量需求。'
        else:
            threshold = '升级一次降低力量需求；具体增益见下列变化。'
        effects = []
        for label in ('命中倍率','攻击耗时','移动速度倍率','护甲闪避惩罚倍率'):
            if label in current:
                effects.append(f'{label} {current[label]} → {upgraded[label]}')
        from .values_investment import phase_changes
        gains = [row for row in phase_changes(choice['current_metrics'],choice['upgraded_metrics']) if row['before'] != row['after']]
        explanations.append({'choice':marker,'name':choice['name'],'summary':strength+threshold,
                             'timing_and_accuracy':'；'.join(effects),'upgrade_changes':gains})
    a,b=result['choices']
    deficit_a=int(a['current'].get('力量缺口','0'));deficit_b=int(b['current'].get('力量缺口','0'))
    tradeoff='两件均达到所填力量需求；请结合伤害范围、防御、耗时和实际特殊效果取舍。'
    if deficit_a!=deficit_b:
        tradeoff=f"{'A' if deficit_a<deficit_b else 'B'} 的当前力量缺口较小；力量不足会改变命中、耗时或防御，不能只比较基础伤害。"
    elif deficit_a:
        tradeoff='两件都有力量缺口；先核对总力量，再比较命中、速度与防御的惩罚。'
    return {'choices':explanations,'tradeoff':tradeoff,
            'boundary':'这是所填基础条件的取舍说明，不是最终伤害或绝对推荐。未知等级、敌方防御、戒指、天赋和临时状态需要另行核对。'}


def add_food_context(session, data, kind, entry, option, known_available):
    """Link only known carried foods; displayed values remain conditional base references."""
    from .values import metric
    details = session.values.detail(entry)
    cells = {row['label']:row for block in details['blocks'] for row in block.get('values',[])}
    option['values'] = [dict(cells[label]) for label in ('恢复饱食','进食耗时') if label in cells]
    option['note'] = '普通进食基础耗时3回合，相关进食天赋可能缩短至1回合；进食期间敌人仍会行动。先处理眼前威胁，再核对食物。'
    if kind == 'Pasty':
        option['note'] += '馅饼节庆外观可能改变单次饱食量与附加效果，此处450点为普通馅饼参考。'
    elif kind == 'MeatPie':
        option['note'] += '肉馅饼还会赋予饱腹状态；900点为基础恢复，不表示可超出普通饱食上限。'
    elif kind == 'MysteryMeat':
        option['note'] += '生肉可能附带负面状态；可先核对烹饪方式。'
    elif kind in ('Blandfruit','FrozenCarpaccio','PhantomMeat'):
        option['note'] += '实际效果还取决于烹饪/冷冻/灵肉等特殊分支，请核对该物品说明。'
    nutrition = cells.get('恢复饱食',{}).get('value')
    if nutrition is None:
        option['calculation_missing'] = '此食物没有已核对的固定饱食量；请查独立说明。'
        return
    amount = float(nutrition)
    if '饥饿游戏' in data.get('challenges',[]):
        amount /= 3
        option['values'].append(metric('饥饿游戏基础饱食恢复',amount,'点','食物基础值除以3；仍需核对丰饶之角与节庆等修正'))
    horns = [item for item in known_available if item.get('kind') == 'HornOfPlenty' and item.get('location') in ('神器', '饰品')]
    if len(horns)==1 and horns[0].get('cursed') is True:
        amount *= .67
        option['values'].append(metric('已知诅咒丰饶之角下的参考恢复',amount,'点','按已知装备记录再乘0.67；请核对该局实际生效状态'))
    elif horns and any(item.get('cursed') is None for item in horns):
        option['calculation_missing'] = '丰饶之角诅咒状态未确认；不能把基础恢复当作此局确定结果。'
    hunger = data['hero'].get('hunger')
    if isinstance(hunger,(int,float)) and not isinstance(hunger,bool) and kind not in ('Pasty','Blandfruit'):
        option['values'].append(metric('进食后饥饿值参考',max(0,hunger-amount),'点',
            '仅扣本次基础食物恢复；未计进食期间饥饿增长、天赋、特殊状态与未确认修正，不保证即时解除危险'))
    option['note'] += '药水恐惧不把普通食物变成治疗药剂；食物饱食恢复不等于即时回血。诅咒丰饶之角会降低恢复，未确认的状态需在游戏中核对。'
