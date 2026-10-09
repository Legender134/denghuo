"""Conditional wand/ring investment metrics, using the reviewed numeric backend."""
from __future__ import annotations

CONTEXT_KEYS = ('hp','max_hp','hero_level','depth','target_hp','target_max_hp','enemy_exp','minor','major','charges')
EXTRA_KEYS = {'investment_mode', 'character_scene', 'scene_ring_slot', *(f'{key}_{side}' for side in ('a','b')
    for key in ('level_known','curse','ring_pair','ring_pair_level','ring_pair_curse', *CONTEXT_KEYS))}
FAMILIES = {'weapon':'items.weapon.melee.', 'armor':'items.armor.', 'wand':'items.wands.', 'ring':'items.rings.'}


def family(identity):
    return next((kind for kind,prefix in FAMILIES.items() if isinstance(identity,str) and identity.startswith(prefix)),None)


def canonical_comparison(values, raw):
    from .values_decisions import bounded_integer
    from .values import INPUTS
    base = {'strength', *(f'{field}_{side}' for side in ('a','b') for field in ('id','level','tier','mastery','augment'))}
    budget = {'planning','upgrade_budget','strength_budget'}
    if not isinstance(raw,dict) or set(raw)-base-budget-EXTRA_KEYS:
        raise ValueError('装备方案包含不支持的参数')
    result = {'strength':bounded_integer(raw.get('strength',10),'有效力量',1,1000)}
    kinds=[]
    for side in ('a','b'):
        identity=raw.get('id_'+side)
        kind=family(identity)
        if not kind or '$' in identity or identity.endswith('.ability') or not any(e['id']==identity for e in values.catalog.entries):
            raise ValueError('请选择普通近战武器、护甲、法杖或戒指')
        kinds.append(kind)
        result['id_'+side]=identity
        result['level_'+side]=bounded_integer(raw.get('level_'+side,0),'A等级' if side=='a' else 'B等级',-100 if kind in ('weapon','armor') else 0,99)
        result['tier_'+side]=bounded_integer(raw.get('tier_'+side,3),'原护甲阶数',1,5)
        for key,default,allowed in [('mastery','0',('0','1')),('augment','NONE',('NONE','EVASION','DEFENSE') if kind=='armor' else ('NONE','SPEED','DAMAGE') if kind=='weapon' else ('NONE',))]:
            item=raw.get(key+'_'+side,default)
            if item not in allowed:raise ValueError('请核对'+('精通' if key=='mastery' else '强化')+'选项')
            if kind in ('wand','ring') and key=='mastery' and item!='0':raise ValueError('法杖和戒指不使用装备精通条件')
            result[key+'_'+side]=item
        if kind in ('wand','ring'):
            for key,default,allowed in [('level_known','0',('0','1')),('curse','0',('0','1','unknown'))]:
                item=raw.get(key+'_'+side,default)
                if item not in allowed:raise ValueError('请核对已知等级和诅咒状态')
                result[key+'_'+side]=item
            if kind=='ring':
                result['ring_pair_'+side]=raw.get('ring_pair_'+side,'0')
                if result['ring_pair_'+side] not in ('0','1'):raise ValueError('请明确是否组合另一枚同类型戒指')
                result['ring_pair_level_'+side]=bounded_integer(raw.get('ring_pair_level_'+side,0),'另一枚同类型戒指等级',-100,100)
                result['ring_pair_curse_'+side]=raw.get('ring_pair_curse_'+side,'0')
                if result['ring_pair_curse_'+side] not in ('0','1','unknown'):raise ValueError('请核对另一枚同类型戒指诅咒状态')
            for key in CONTEXT_KEYS:
                name=key+'_'+side
                if name in raw:
                    spec=INPUTS[key]
                    result[name]=bounded_integer(raw[name],spec[0]+'（'+side.upper()+'）',spec[2],spec[3])
            # Shared strength is explicit; return actual requested context and defaults so save/reopen is stable.
            supplied={key:result[key+'_'+side] for key in CONTEXT_KEYS if key+'_'+side in result}
            detail=values.detail(identity,{'level':result['level_'+side],'strength':result['strength'],**supplied})
            requested={item['key'] for item in detail['inputs']}
            if identity.endswith('wandoffireblast'):
                requested.add('charges');result['charges_'+side]=bounded_integer(raw.get('charges_'+side,1),'本次消耗充能',1,3)
            if set(supplied)-requested:raise ValueError('方案包含此条目不使用的上下文参数')
            for item in detail['inputs']:
                if item['key'] in CONTEXT_KEYS:result[item['key']+'_'+side]=item['value']
    if kinds[0]!=kinds[1]:raise ValueError('请分别在近战武器、护甲、法杖或戒指的同一类别内比较')
    planning=raw.get('planning','0')
    if planning not in ('0','1'):raise ValueError('请明确选择是否启用预算规划')
    if planning=='1':
        result['planning']='1'
        for key,label,high in [('upgrade_budget','升级卷轴预算',100),('strength_budget','拟投入力量药剂',99)]:
            result[key]=bounded_integer(raw.get(key,0),label,0,high)
        if 'character_scene' not in raw and result['strength']+result['strength_budget']>1000:raise ValueError('规划有效力量（所填力量加拟投入药剂）需要是 1–1000 的整数')
        mode=raw.get('investment_mode','min_strength' if kinds[0] in ('weapon','armor') else 'all')
        if mode not in ('all','min_strength') or kinds[0] in ('wand','ring') and mode!='all':
            raise ValueError('最小力量门槛规划仅用于普通近战武器与护甲；法杖和戒指请选择完整投入')
        if 'investment_mode' in raw or kinds[0] in ('wand','ring'):result['investment_mode']=mode
    elif set(raw)&(budget-{'planning'}|{'investment_mode'}):raise ValueError('预算参数需要明确启用升级规划')
    from .character_comparison import canonical_scene
    canonical_scene(raw, result, kinds[0])
    return result


def context_for(raw, side, level, strength=None):
    from .character_comparison import comparison_strength
    return {'level':level,'strength':comparison_strength(raw, side, level) if strength is None else strength,
            **{key:raw[key+'_'+side] for key in CONTEXT_KEYS if key+'_'+side in raw}}


def conditional_metrics(values, raw, side, level, *, strength=None, clear_curse=False):
    from .values import integer_parameters
    identity=raw['id_'+side];kind=family(identity)
    params=context_for(raw,side,level,strength)
    if 'character_scene' in raw and clear_curse and strength is None:
        from .character_comparison import comparison_strength
        params['strength'] = comparison_strength(raw, side, level, clear_curse=True)
    detail=values.detail(identity,params)
    curse='0' if clear_curse else raw['curse_'+side]
    assumptions=('已知等级' if raw['level_known_'+side]=='1' else '手填等级假设，未确认游戏鉴定')
    suffix='；'+assumptions+'；未计未填写的天赋、临时等级和目标特殊状态'
    rows=[]
    if kind=='ring':
        pair=raw['ring_pair_'+side]=='1'
        other_curse=raw['ring_pair_curse_'+side]
        if curse=='unknown' or pair and other_curse=='unknown':
            return [{'label':'戒指效果','value':'诅咒状态未确认','unit':'','condition':'请明确填写单戒或两戒的诅咒分支后比较'+suffix}]
        solo=min(0,level-2) if curse=='1' else level+1
        other=(min(0,raw['ring_pair_level_'+side]-2) if other_curse=='1' else raw['ring_pair_level_'+side]+1) if pair else 0
        bonus=solo+other
        scene=raw.get('character_scene')
        if scene:
            if scene['magic_immune']:
                bonus=0
                suffix+='；魔法免疫抑制戒指效果'
            elif bonus==0:
                if scene['spirit_form'] is None or scene['spirit_form'] and scene['spirit_ring'] is None:
                    return [{'label':'戒指效果','value':'精神形态条件未确认','unit':'','condition':suffix}]
                if scene['spirit_form'] and scene['spirit_ring']==identity:
                    if scene['spirit_level'] is None or scene['spirit_cursed'] is None:
                        return [{'label':'戒指效果','value':'精神形态等级或诅咒未确认','unit':'','condition':suffix}]
                    bonus=min(0,scene['spirit_level']-2) if scene['spirit_cursed'] else scene['spirit_level']+1
                    suffix+='；普通戒指合计为0，计入所列精神形态后备效果'
        blocks=[]
        values.rings(identity,integer_parameters(params),blocks,set(),effective_bonus=bonus)
        condition=('同类型两枚相加，另一枚等级与诅咒按所填条件固定' if pair else '单枚戒指')+'；本枚'+('保持诅咒分支；升级随机解咒未假定成功' if curse=='1' else '无诅咒分支')+suffix
        rows=[{'label':'合计戒指效果等级','value':str(bonus),'unit':'点','condition':condition}]
        for block in blocks:
            for cell in block.get('values',[]):rows.append({**cell,'condition':'；'.join(filter(None,[cell.get('condition'),block.get('note'),condition]))})
    else:
        for block in detail['blocks']:
            if block['title'] in ('出售与回收','其他明确数值'):continue
            if curse!='0' and block['title']!='法杖充能':continue
            for cell in block.get('values',[]):
                rows.append({**cell,'condition':'；'.join(filter(None,[cell.get('condition'),block.get('note'),suffix.lstrip('；')]))})
            columns=block.get('columns',[])
            if columns and columns[0] in ('装备等级','法杖等级'):
                selected=next((row for row in block.get('rows',[]) if str(row[0]).lstrip('+')==str(level)),None)
                if not selected:continue
                if identity.endswith('wandoffireblast'):
                    charge=raw.get('charges_'+side,1)
                    rows.append({'label':'本次焰浪基础伤害','value':str(selected[charge]),'unit':'HP','condition':f'消耗{charge}次充能；'+block.get('note','')+suffix})
                elif identity.endswith('wandofcorrosion'):
                    for label,value,unit in zip(columns[1:],selected[1:],('量','点')):
                        rows.append({'label':label,'value':str(value),'unit':unit,'condition':'持续气体接触与目标抗性需核对'+suffix})
        if curse!='0':rows.append({'label':'法杖效果','value':'诅咒随机效果' if curse=='1' else '诅咒状态未确认','unit':'','condition':'此分支不能使用正常法杖伤害；升级解咒有随机性，未假定成功'+suffix})
    return list({row['label']:row for row in rows}.values())


def structured_physical(metrics):
    units={'最低基础伤害':'HP','最高基础伤害':'HP','额外力量伤害':'HP','武器额外减伤':'HP','常规减伤':'HP','信念护体':'HP',
        '力量需求':'点','力量缺口':'点','护甲强化闪避加值':'点','命中倍率':'倍','移动速度倍率':'倍','护甲闪避惩罚倍率':'倍','攻击耗时':'回合','攻击距离':'格'}
    return [{'label':key,'value':value,'unit':units.get(key,''),'condition':'只在信念护体挑战生效' if key=='信念护体' else
        '力量与装备限制；除力量来源外，未合并其他戒指、天赋与临时战斗效果' if key in ('攻击耗时','命中倍率','移动速度倍率','护甲闪避惩罚倍率','护甲强化闪避加值') else
        '按所填有效力量；伤害与随机减伤范围未计目标防御或抗性'} for key,value in metrics.items()]


def metric_difference(before, after):
    try:return f'{float(after)-float(before):+g}'
    except (TypeError,ValueError):return '见范围 / 条件'


def comparison_rows(choices):
    maps=[{cell['label']:cell for cell in choice[phase+'_metrics']} for choice in choices for phase in ('current','upgraded')]
    rows=[]
    for label in dict.fromkeys(key for cells in maps for key in cells):
        cells=[items.get(label) for items in maps];present=[cell for cell in cells if cell]
        unit=present[0]['unit']
        comparable=cells[0] and cells[2] and cells[0]['unit']==cells[2]['unit']
        conditions=list(dict.fromkeys(c['condition'] for c in present if c.get('condition')))
        rows.append({'label':label,'values':[c['value'] if c else '不适用 / 未核对' for c in cells],
                     'difference':metric_difference(cells[0]['value'],cells[2]['value']) if comparable else '不适用',
                     'unit':unit,'condition':'；'.join(conditions),
                     'conditions':[c.get('condition','') if c else '此装备没有已核对的同名效果' for c in cells]})
    return rows


def phase_changes(current, planned):
    before={cell['label']:cell for cell in current}
    return [{'label':cell['label'],'before':before.get(cell['label'],{}).get('value','未核对'),'after':cell['value'],
             'difference':metric_difference(before.get(cell['label'],{}).get('value'),cell['value']),
             'unit':cell['unit'],'condition':cell.get('condition','')} for cell in planned]


def compare_conditional(values, raw):
    choices=[]
    for side in ('a','b'):
        identity=raw['id_'+side];level=raw['level_'+side]
        current=conditional_metrics(values,raw,side,level);upgraded=conditional_metrics(values,raw,side,level+1)
        choice={'id':identity,'name':next(e['name'] for e in values.catalog.entries if e['id']==identity),'level':level,
                'current':{cell['label']:cell['value'] for cell in current},'upgraded':{cell['label']:cell['value'] for cell in upgraded},
                'current_metrics':current,'upgraded_metrics':upgraded,'conditions':context_for(raw,side,level)}
        if raw['curse_'+side]=='1':choice['after_curse_removed']=conditional_metrics(values,raw,side,level+1,clear_curse=True)
        choices.append(choice)
    result={'family':family(raw['id_a']),'choices':choices,'rows':comparison_rows(choices),'version':values.catalog.data['version'],'params':raw,
            'notice':'法杖与戒指按所填等级、诅咒和上下文独立比较。升级一次不保证解咒；有诅咒时保留分支并列解咒后的条件参考。两枚组合只限同类型戒指；未计其他戒指、天赋、魔法免疫或临时等级。法杖连锁、水地、目标防御/抗性和未填状态不会据此确认；没有全局最强结论。'}
    result['explanation']={'tradeoff':'先核对每列的生效条件；不同法杖、不同类型戒指的用途不可用单一数值排序。',
        'boundary':result['notice'],'choices':[{'choice':side.upper(),'name':choice['name'],'summary':'按已知条件或明确手填假设比较；未确认的诅咒不会冒充正常效果。',
         'timing_and_accuracy':'','upgrade_changes':phase_changes(choice['current_metrics'],choice['upgraded_metrics'])} for side,choice in zip(('a','b'),choices)]}
    if raw.get('planning')=='1':result['planning']=plan_conditional(values,raw,choices)
    from .character_comparison import attach_scenes
    return attach_scenes(result, raw)


def plan_conditional(values, raw, choices):
    budget=raw['upgrade_budget'];strength=raw['strength']+raw['strength_budget'];planned=[]
    for side,choice in zip(('a','b'),choices):
        alternatives=[]
        for spent in range(min(budget,100-choice['level'])+1):
            from .character_comparison import comparison_strength, comparison_scene
            level=choice['level']+spent
            side_strength=comparison_strength(raw,side,level,raw['strength_budget'])
            cells=conditional_metrics(values,raw,side,level,strength=side_strength)
            row={'upgrades':spent,'spent_upgrades':spent,'level':level,'remaining_upgrades':budget-spent,
                 'spent_strength':raw['strength_budget'],'remaining_strength':0,'metrics':{c['label']:c['value'] for c in cells},
                 'metric_rows':cells,'changes':phase_changes(choice['current_metrics'],cells)}
            if 'character_scene' in raw:row['character_scene']=comparison_scene(raw,side,level,raw['strength_budget'])
            if spent and raw['curse_'+side]=='1':row['after_curse_removed']=conditional_metrics(values,raw,side,level,strength=comparison_strength(raw,side,level,raw['strength_budget'],True),clear_curse=True)
            alternatives.append(row)
        final=alternatives[-1]
        planned.append({'id':choice['id'],'name':choice['name'],'planned_level':final['level'],'spent_upgrades':final['upgrades'],
            'remaining_upgrades':final['remaining_upgrades'],'metrics':final['metrics'],'metric_rows':final['metric_rows'],'alternatives':alternatives,
            'explanation':'逐一列出0至预算内每个投入，等级最高100。诅咒仍存/已解咒是条件分支，不把随机解咒当作保证；另一枚戒指不升级。力量药剂每瓶按基础力量+1，未实际消耗。'})
    if 'character_scene' in raw:strength='见A/B各投入的角色条件'
    return {'mode':'all','upgrade_budget':budget,'strength_budget':raw['strength_budget'],'effective_strength':strength,'choices':planned,
        'notice':'A、B是各自独立使用同一预算的备选，不能同时花费。列出的另一枚同类型戒指固定不变；其天赋、临时状态和等级来源需核对。'}
