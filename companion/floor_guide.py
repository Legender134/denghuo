"""Public floor encounter rules; never reads or reveals saved enemy instances.

Derived from SPD 4.0.2 MobSpawner/Shaman/Elemental and Dungeon (GPL-3.0+,
Oleg Dolya and Evan Debenham). Rotation slots are not per-floor guarantees.
"""
from collections import Counter

from .monster_reference import monster_record, normal_stats, reference


def floor_encounters(game, catalog):
    depth, branch, version = game.get('depth'), game.get('branch', 0), game.get('version')
    result = {'depth':depth,'branch':branch,'version':'4.0.2','rows':[],
              'note':'常规生成规则参考；不是本局已出现的怪物清单。特殊房间、任务、陷阱与召唤可额外产生生物。'}
    if version!=922 or type(depth) is not int or not 1<=depth<=26 or type(branch) is not int:
        result['note']='当前保存版本或楼层尚未核对常规生成规则；可在手册查询4.0.2独立参考。'
        return result
    data = reference()
    result['sources']=[{'path':path,'sha256':digest,'url':f'https://github.com/00-Evan/shattered-pixel-dungeon/blob/{data["commit"]}/{path}'}
        for path,digest in data['verified_source_files'].items() if path.endswith(('/MobSpawner.java','/Shaman.java','/Elemental.java','/Dungeon.java','/MiningLevel.java','/VaultLevel.java'))]
    def add(identity, condition, group):
        row = monster_record(catalog, identity)
        if not row: raise ValueError('楼层怪物参考不完整，请核对资料版本。')
        stats = normal_stats(row,identity,depth)
        result['rows'].append({'id':identity,'name':row['name'],'condition':condition,'group':group,
            'hp':str(stats['HT']),'damage':str(stats['damageRoll']),'dr':str(stats['drRoll'])})
    if branch:
        if branch==1 and 11<=depth<=14:
            # The active blacksmith quest type is not inferred from depth.
            for identity,condition in (('bat','其他矿洞任务'),('crystalwisp','水晶矿洞任务'),
                                       ('gnollguard','豺狼矿洞任务'),('fungalspinner','菌类矿洞任务')):
                add('actors.mobs.'+identity,'矿洞刷新：'+condition,'任务条件')
            result['note']='矿洞按铁匠任务类型刷新；下面分支互斥。特殊房间与任务首领另计，不表示本局四类都会出现。'
        elif branch==1 and 16<=depth<=19:
            for identity in ('vaultskeleton','vaultdm100','vaultshaman','vaultdm200','vaultghoul','vaultelemental$fire','vaultelemental$frost','vaultelemental$shock','vaultgolem','vaultbosselemental'):
                add('actors.mobs.quest.vault.'+identity,'宝库房间按自身布置生成；不是普通主地牢刷新','宝库房间')
            result['note']='宝库房间与首领参考；不使用主地牢轮换或稀有替换概率。房间的实际生物须主动揭示本层保存内容。'
        else: result['note']='此支线位置没有已核对的常规生成规则。'
        return result
    bosses = {5:'goo',10:'tengu',15:'dm300',20:'dwarfking',25:'yogdzewa'}
    if depth in bosses:
        add('actors.mobs.'+bosses[depth],'首领层主敌人；支援、召唤与战斗阶段另查展开资料','首领')
        result['note']='首领层不套用普通楼层刷怪轮换；召唤与场景生物由首领战机制决定。'
        return result
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
    return result
