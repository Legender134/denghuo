"""Public floor encounter rules; never reads or reveals saved enemy instances.

Derived from SPD 4.0.2 spawn, room and boss challenge rules (GPL-3.0+,
Oleg Dolya and Evan Debenham). Rotation slots are not per-floor guarantees.
"""
from collections import Counter

from .monster_reference import monster_record, normal_stats, reference


# Additional trap pools verified at the same pinned 4.0.2 revision as reference().
TRAP_POOL_SOURCES = {
    'core/src/main/java/com/shatteredpixel/shatteredpixeldungeon/levels/CavesLevel.java':'65bf20aa7927d7ca511f18e77b2c547092fa69d550d366791c8e08e0567a0333',
    'core/src/main/java/com/shatteredpixel/shatteredpixeldungeon/levels/CityLevel.java':'3d4ef24c26984390bfd9f12fe03485b61322b90fa4abf99d4f2b8d7277a69142',
}


def floor_encounters(game, catalog):
    depth, branch, version = game.get('depth'), game.get('branch', 0), game.get('version')
    mask = game.get('challenges')
    known = type(mask) is int and 0 <= mask <= 511
    stronger = known and bool(mask & 256)
    result = {'depth':depth,'branch':branch,'version':'4.0.2','rows':[],
              'challenges_mask':mask if known else None,'challenges_known':known,
              'note':'普通轮换、房间、任务与饰品生成条件参考；不是本局已出现的怪物清单。携带物品主动召唤与临时变化另查对应资料。'}
    if version!=922 or type(depth) is not int or not 1<=depth<=26 or type(branch) is not int:
        result['note']='当前保存版本或楼层尚未核对常规生成规则；可在手册查询4.0.2独立参考。'
        return result
    data = reference()
    result['sources']=[{'path':path,'sha256':digest,'url':f'https://github.com/00-Evan/shattered-pixel-dungeon/blob/{data["commit"]}/{path}'}
        for path,digest in data['verified_source_files'].items() if path in data['encounters'].get('condition_sources',()) or path.endswith(('/MobSpawner.java','/Shaman.java','/Elemental.java','/Dungeon.java','/MiningLevel.java','/VaultLevel.java','/GuardianTrap.java'))]
    def add(identity, condition, group, *, reference_depth=None, profile=None):
        existing=next((r for r in result['rows'] if r['id']==identity and r.get('reference_depth')==reference_depth),None)
        if existing:
            existing['condition']+='；另可出现：'+condition
            return
        row = monster_record(catalog, identity)
        if not row: raise ValueError('楼层怪物参考不完整，请核对资料版本。')
        stats = normal_stats(row,identity,depth if reference_depth is None else reference_depth,stronger_bosses=stronger)
        health=str(stats['HP'])+('/'+str(stats['HT']) if stats['HP']!=stats['HT'] else '')
        item={'id':identity,'name':row['name'],'condition':condition,'group':group,
            'hp':health,'damage':str(stats['damageRoll']),'dr':str(stats['drRoll'])}
        if identity in ('actors.mobs.goo','actors.mobs.tengu','actors.mobs.dm300','actors.mobs.dwarfking','actors.mobs.yogdzewa','actors.mobs.pylon'):
            item['reference_params']={'stronger_bosses':int(stronger)}
        if identity=='actors.mobs.eye':
            item['reference_params']={'no_herbalism':int(known and bool(mask & 8))}
        if reference_depth is not None:item['reference_depth']=reference_depth
        if profile:
            item['reference_key']=identity+'@'+profile
            item['name']+='（招魂法师召唤）'
        result['rows'].append(item)
    def finish():
        for row in result['rows']:
            group=row['group']
            if group in ('稀有替换','罕见跨区','罕见跨区变种'): row['fold_group']='稀有与罕见变种'
            elif group in ('特殊房间','任务房间'): row['fold_group']='房间与任务条件'
            elif group=='首领支援': row['fold_group']='首领支援与召唤'
            elif group=='挑战支援': row['fold_group']='绝命头目挑战支援'
            elif group=='宝库机关': row['fold_group']='宝库机关/房间条件'
            elif group=='饰品条件': row['fold_group']='饰品生成条件'
            elif group=='机关/陷阱条件': row['fold_group']='机关/陷阱条件'
        result['note']+=(' 已确认开启绝命头目：应用已核对的首领初始生命、支援名单与拳头选择规则；其他挑战机制及临时状态另查资料。' if stronger else
                         ' 已确认未开启绝命头目，采用普通首领参考；其他挑战及临时状态另查资料。' if known else
                         ' 挑战信息未确认，暂按未开启绝命头目的普通参考；不能据此确认本局难度。')
        return result
    if branch:
        if branch==1 and 11<=depth<=14:
            # The active blacksmith quest type is not inferred from depth.
            for identity,condition in (('crystalwisp','水晶矿洞任务'),('gnollguard','豺狼矿洞任务')):
                add('actors.mobs.'+identity,'矿洞刷新：'+condition,'任务条件')
            for identity,condition in (('crystalguardian','水晶任务的大型矿洞房间'),('crystalspire','水晶任务的巨大矿洞房间'),
                ('gnollsapper','豺狼任务的大型矿洞房间'),('gnollgeomancer','豺狼任务的巨大矿洞房间')):
                add('actors.mobs.'+identity,condition+'；须匹配本局铁匠任务类型','任务房间')
            add('actors.mobs.bat','仅旧版或非当前两种任务的兼容回退分支；4.0.2正常新局任务不会选择此分支','任务房间')
            result['note']='4.0.2正常新局只选择水晶或豺狼任务，两者互斥；任务入口在第12–14层。菌类任务尚未实装，不列入正常名单。'
            if depth==11: result['note']+=' 当前第11层支线为兼容位置，不是此版新局任务入口。'
        elif branch==1 and 16<=depth<=19:
            for identity in ('vaultskeleton','vaultdm100','vaultshaman','vaultdm200','vaultghoul','vaultelemental$fire','vaultelemental$frost','vaultelemental$shock','vaultgolem','vaultbosselemental'):
                add('actors.mobs.quest.vault.'+identity,'宝库房间按自身布置生成；不是普通主地牢刷新','宝库房间')
            add('actors.mobs.npcs.vaultsentry','扫描宝藏房间生成的固定机关，不可破坏；扫描方向、宽度及间隔由房间配置，不是普通攻击或普通随机掉落','宝库机关')
            add('actors.mobs.npcs.vaultlaser','激光房间按可用墙面布置的固定机关，不可破坏；方向、轮次间隔及射击次数由房间配置，不是普通攻击或普通随机掉落','宝库机关')
            result['note']='宝库房间与首领参考；不使用主地牢轮换或稀有替换概率。房间的实际生物须主动揭示本层保存内容。'
        else: result['note']='此支线位置没有已核对的常规生成规则。'
        return finish()
    bosses = {5:'goo',10:'tengu',15:'dm300',20:'dwarfking',25:'yogdzewa'}
    if depth in bosses:
        add('actors.mobs.'+bosses[depth],('绝命头目挑战初始生命参考' if stronger else '普通难度初始生命参考')+'；支援、召唤与战斗阶段另查展开资料','首领')
        if depth==15:
            add('actors.mobs.pylon',f'DM-300战斗共激活{3 if stronger else 2}座能量塔；超载阶段须破坏当前供能塔，未激活的塔无敌','首领支援')
        elif depth==20:
            for identity in ('dkghoul','dkmonk','dkwarlock'):
                add('actors.mobs.dwarfking$'+identity,'矮人国王分阶段召唤；未必同时在场'+('；绝命头目使用强化召唤分支' if stronger else '；国王魔像仅属绝命头目挑战，未列入普通难度'),'首领支援')
            if stronger:
                add('actors.mobs.dwarfking$dkgolem','绝命头目第二阶段后段成对召唤；其他召唤分支每第9次也选择国王魔像，须有可用召唤位置；未必同时在场','挑战支援')
        elif depth==25:
            for first,second in (('burningfist','soiledfist'),('rottingfist','rustedfist'),('brightfist','darkfist')):
                for identity in (first,second):
                    add('actors.mobs.yogfist$'+identity,'绝命头目三轮召拳每轮同时召唤2拳，共6拳；同一配对不会同轮出现，顺序由生成规则决定，未预测本局顺序' if stronger else '普通难度此配对只随机选1种，再与其他配对打乱出现顺序；不是6拳都会出现','首领支援')
            add('actors.mobs.yogdzewa$larva',('绝命头目召唤池有6个名额，其中前4个名额按血巢状态分配；' if stronger else '普通召唤池有4个名额；')+'已摧毁恶魔血巢对应名额使用幼虫；未读取本局血巢计数','首领支援')
            add('actors.mobs.yogdzewa$yogripper','绝命头目召唤池最后2个名额固定使用跳跃恶魔；另4个按血巢状态分配，未读取本局血巢计数' if stronger else '普通召唤池中仍存活的恶魔血巢对应名额使用跳跃恶魔；未读取本局血巢计数','首领支援')
            if stronger:
                add('actors.mobs.yogdzewa$yogeye','绝命头目召唤池前4个名额中，仍存活血巢对应的偶数索引名额（第1、3名额）使用古神邪眼；未读取本局血巢计数，不保证出现','挑战支援')
                add('actors.mobs.yogdzewa$yogscorpio','绝命头目召唤池前4个名额中，仍存活血巢对应的奇数索引名额（第2、4名额）使用古神蝎子；未读取本局血巢计数，不保证出现','挑战支援')
        result['note']='首领层不套用普通楼层刷怪轮换；召唤与场景生物由首领战机制决定。'
        return finish()
    if depth==26:
        result['note']='最终楼层不生成普通刷新怪物；不将第24层轮换套用到这里。'
        return result
    rules = data['encounters']
    slots = Counter(rules['rotations'][str(depth)])
    total = sum(slots.values())
    for identity,count in slots.items():
        label = f'普通轮换每轮 {total} 个名额中占 {count} 个；轮换打乱后逐个取用'
        if identity in rules['selectors']:
            for choice in rules['selectors'][identity]:
                if choice.get('alternative'):
                    condition=label+'；元素名额默认2%先替换成混沌元素，鼠头骨可改变概率'
                    group='稀有替换'
                else:
                    condition=label+f'；此类型按 {choice["chance"]*100:g}% 选择'
                    if identity=='Elemental.random()': condition+='（仅在未先替换成混沌元素时）'
                    group='普通轮换'
                add(choice['id'],condition,group)
        else:
            add(identity,label+'；若有稀有变种则默认2%替换，鼠头骨可改变概率' if identity in rules['alternatives'] else label,'普通轮换')
            if identity in rules['alternatives']:
                add(rules['alternatives'][identity],'每个对应普通怪物名额默认2%替换；鼠头骨可改变概率','稀有替换')
    rare = rules['rare_additions'].get(str(depth))
    if rare:
        add(rare['class'],'每次建立整轮时有2.5%额外加入1个名额；不是每次刷新2.5%','罕见跨区')
        if rare['class'] in rules['alternatives']:
            add(rules['alternatives'][rare['class']],'先满足2.5%整轮额外加入，再按默认2%替换；鼠头骨可改变替换概率','罕见跨区变种')
    priority={'普通轮换':0,'稀有替换':1,'罕见跨区':2,'罕见跨区变种':3}
    result['rows'].sort(key=lambda row:priority.get(row['group'],4))
    if 11<=depth<=24:
        add('levels.traps.guardiantrap$guardian',f'仅本层存在且激活守卫陷阱时，每次激活最多召唤 {(depth-5)//5} 个守卫（当前等效第{depth}层）；每个守卫须有可用生成格，不保证本层存在该陷阱或生成满额；不属于普通刷新轮换','机关/陷阱条件')
        for path,digest in TRAP_POOL_SOURCES.items():
            result['sources'].append({'path':path,'sha256':digest,'url':f'https://github.com/00-Evan/shattered-pixel-dungeon/blob/{data["commit"]}/{path}'})
    add('actors.mobs.ebonymimic','仅普通主地牢非首领层生成物品时，宝箱怪之牙生效且分支命中才可能出现；生效等级0／1／2／3对应分支概率12.5%／25%／37.5%／50%，无效果为0。伪装为普通地面物品、出口或门；不是每个宝箱的概率，未读取本局饰品或实际生成结果','饰品条件')
    for identity,condition in (('piranha','水池宝藏房间生成3只食人鱼，每个名额默认2%替换为幻影食人鱼；鼠头骨可改变替换概率'),
        ('phantompiranha','水池房间的食人鱼名额默认2%替换；这不是房间生成概率'),
        ('statue','石像房间生成1座石像，默认10%改为装甲石像；鼠头骨可改变替换概率'),
        ('armoredstatue','石像房间的石像名额默认10%替换；这不是房间生成概率'),
        ('wraith','开启坟墓或有怨灵的容器时生成；未指定种类的怨灵名额默认1%替换为被折磨的灵魂，鼠头骨可改变概率'),
        ('tormentedspirit','未指定种类的怨灵生成名额默认1%替换；净化奖励与普通击杀掉落不同'),
        ('crystalmimic','水晶宝库房间的宝箱分支默认10%替换1个水晶宝箱；鼠头骨与宝箱怪之牙可改变概率')):
        add('actors.mobs.'+identity,condition,'特殊房间')
    add('levels.rooms.special.sentryroom$sentry','哨卫房间内的固定机关；不能作为可击杀的普通怪物','特殊房间')
    if depth>1:
        for identity,condition in (('mimic','普通物品生成的宝箱分支可产生；不是每层固定出现'),
            ('goldenmimic','升级装备或神器的上锁宝箱分支可替换；不是普通刷新名额'),
            ('bee','隐藏蜂蜜房间生成；第1层不会生成该秘密房间')):
            add('actors.mobs.'+identity,condition,'特殊房间')
    if depth in (2,3,4):
        identity={2:'fetidrat',3:'gnolltrickster',4:'greatcrab'}[depth]
        add('actors.mobs.'+identity,'本层生成悲伤幽灵，且玩家接受它的任务并有可用生成位置时','任务房间')
    if 7<=depth<=9:
        for identity,condition in (('skeleton','制杖师的尸尘任务乱葬房间'),('elemental$newbornfireelemental','制杖师余烬任务，完成蜡烛仪式后'),
            ('rotheart','制杖师的腐莓任务花园'),('rotlasher','制杖师的腐莓任务花园')):
            add('actors.mobs.'+identity,condition+'；制杖师任务类型互斥，未读取本局选择','任务房间')
        add('items.quest.corpsedust$dustwraith','尸尘任务拾起并继续携带尸尘时召唤；携带离层后仍可能在其他楼层产生','任务房间')
    if 21<=depth<=24:
        add('actors.mobs.demonspawner','恶魔大厅每层的血巢房间；不会作为普通刷新怪物','任务房间')
        add('actors.mobs.ripperdemon','恶魔血巢存活且有可用邻格时召唤','任务房间')
    if any(r['id']=='actors.mobs.necromancer' for r in result['rows']):
        add('actors.mobs.necromancer$necroskeleton','死灵法师发动召唤且有可用位置时；不能套用普通骷髅的经验或掉落','任务房间')
    if any(r['id']=='actors.mobs.spectralnecromancer' for r in result['rows']):
        add('actors.mobs.wraith','招魂法师发动召唤且有可用位置时；直接生成普通怨灵，固定按等效第4层调整数值，不使用当前层数或稀有替换',
            '任务房间',reference_depth=4,profile='spectral-summon')
    return finish()
