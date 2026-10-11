"""Version-bound enemy values and conditioned normal loot, independent of RNG draws."""
from __future__ import annotations

from functools import lru_cache
import json
import math
from pathlib import Path

from .game_math import float32
from .rules import display

ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def reference():
    return json.loads((ROOT / 'data/monster_reference.json').read_text(encoding='utf-8'))


def monster_record(catalog, identity):
    data = reference()
    if (data['version'], data['commit']) != (catalog.data.get('version'), catalog.data.get('commit')):
        return None
    return data['monsters'].get(identity)


def span(low, high):
    return display(low) if low == high else display(low) + '–' + display(high)


def _family(identity):
    if identity == 'levels.traps.guardiantrap$guardian': return 'statue'
    if identity == 'items.quest.corpsedust$dustwraith': return 'wraith'
    name = identity.removeprefix('actors.mobs.')
    if name.startswith('shaman$'): return 'shaman'
    aliases = reference()['bestiary_conversions']
    if name.startswith(('dwarfking$dk', 'yogdzewa$yog')):
        return aliases[identity].removeprefix('actors.mobs.')
    return name


def _mimic_level(name, depth):
    return math.floor(float32(float32(depth) * float32(1.33)) + .5) if name == 'goldenmimic' else depth


def normal_stats(row, identity, depth):
    stats = dict(row['stats'])
    family = row['dynamic']
    name = identity.removeprefix('actors.mobs.')
    if family == 'mimic':
        level = _mimic_level(name,depth)
        stats.update(HP=6*(1+level), HT=6*(1+level), defenseSkill=2+level//2,
                     damageRoll=span(1+level,2+2*level), attackSkill=6+level, drRoll=span(0,1+level//2))
    elif family == 'piranha':
        stats.update(HP=10+5*depth, HT=10+5*depth, defenseSkill=10+2*depth,
                     damageRoll=span(depth,4+2*depth), attackSkill=20+2*depth, drRoll=span(0,depth))
    elif family == 'bee':
        health = 4*(2+depth)
        stats.update(HP=health, HT=health, defenseSkill=9+depth,
                     damageRoll=span(health//10,health//4), attackSkill=9+depth, drRoll=0)
    elif family == 'wraith':
        scaled = math.floor(float32(float32(1.5)*float32(depth))+.5) if name == 'tormentedspirit' else depth
        stats.update(HP=1, HT=1, defenseSkill=5*(10+scaled),
                     damageRoll=span(1+scaled//2,2+scaled), attackSkill=10+scaled, drRoll=0)
    elif family == 'statue':
        health = (30+10*depth) if name == 'armoredstatue' else (15+5*depth)
        stats.update(HP=health, HT=health, defenseSkill=4+depth,
                     damageRoll='所持武器的伤害范围', attackSkill=f'{9+depth} × 所持武器的命中倍率（取整）',
                     drRoll=f'0–（{depth}＋所持武器的格挡值）'+('，再加所穿护甲的减伤' if name == 'armoredstatue' else ''))
    elif family == 'sentry':
        stats.update(HP='不可破坏', HT='不可破坏', defenseSkill='无限闪避', damageRoll='不使用普通攻击',
                     attackSkill=20+depth*2, drRoll='免疫伤害')
    return stats


def _metric(label, value, unit='', condition=''):
    if value in ('不可破坏', '不使用普通攻击', '免疫伤害', '无限闪避', '无敌'):
        unit = ''
    return {'label':label,'value':display(value) if isinstance(value,(int,float)) else str(value),'unit':unit,'condition':condition}


def defense_block(values, identity, row):
    """Intrinsic class/property rules; conditional defenses stay conditional."""
    profile = row['defenses']
    aliases = {
        'actors.buffs.allybuff':'转化为盟友的状态', 'actors.buffs.sleep':'睡眠类状态',
        'actors.buffs.speed':'速度改变状态', 'actors.mobs.eye$deathgaze':'死亡凝视',
        'actors.blobs.vaultflametraps':'宝库火焰机关',
        'actors.mobs.tengu$fireability$fireblob':'天狗的火焰能力',
        'levels.rooms.special.magicalfireroom$eternalfire':'永恒之火',
    }
    def title(effect):
        if effect in aliases: return aliases[effect]
        name = values.catalog.entry_index.get(effect,{}).get('name') or values.catalog.messages[effect+'.name']
        if effect.startswith('items.weapon.enchantments.'): name += '附魔'
        elif effect.startswith('items.armor.glyphs.'): name += '刻印'
        elif effect.startswith('actors.mobs.elemental$'): name += '造成的伤害'
        return name
    rows = []
    def add_effects(effects,condition):
        for kind in ('resistances','immunities'):
            for effect in effects[kind]:
                if identity.endswith('.vaultbosselemental') and condition=='电光形态' and effect=='items.wands.wandoflightning':
                    rows.append([title(effect),'效果系数 ×1','仅电光形态，直接雷霆法杖伤害的抗性例外；形态承伤分支仍先加10点'])
                else:
                    rows.append([title(effect),'效果系数 ×0.5' if kind=='resistances' else '免疫此类效果',condition])
    add_effects(profile,'固有；无额外装备、增益或挑战')
    name = _family(identity)
    if name=='quest.vault.vaultbosselemental':
        for prop,form in [('FIERY','火焰形态'),('ICY','冰霜形态'),('ELECTRIC','电光形态')]:
            add_effects(reference()['property_defenses'][prop],form)
        rows.extend([
            ['抗魔刻印所列魔法来源','输入伤害 ÷4，整数截断','火焰形态；直接法杖／牧师法术命中另减少特殊攻击冷却3、环境攻击冷却5'],
            ['角色的投掷武器攻击','输入伤害 +10 HP','火焰形态；在普通承伤处理前增加'],
            ['角色的投掷武器攻击','输入伤害 ÷4，整数截断','冰霜形态；投掷武器还会嵌在目标上'],
            ['角色的非投掷普通攻击','输入伤害 +10 HP','冰霜形态；包括角色的徒手攻击'],
            ['抗魔刻印所列魔法来源','输入伤害 +10 HP','电光形态；直接法杖／牧师法术另为所持法杖充能0.2'],
            ['角色／其他生物的普通攻击','输入伤害 ÷4，整数截断','电光形态；角色使用投掷武器时不走此分支'],
            ['冻结／冻伤状态施加','转为5–10 HP基础伤害','火焰形态；不保留该状态，抗性及其他承伤处理另计'],
            ['燃烧状态施加','转为5–10 HP基础伤害','冰霜形态；不保留该状态，抗性及其他承伤处理另计'],
        ])
    if name in ('npcs.vaultsentry','npcs.vaultlaser'):
        rows.append(['所有效果及伤害','免疫效果，且无敌','固定机关，不能作为可击杀的普通怪物'])
    elif name=='dm300':
        rows.append(['所有伤害','无敌','超载期间；普通难度共激活2座能量塔，需破坏当前供能塔解除'])
    elif name=='dwarfking':
        rows.extend([
            ['所有伤害','无敌','第二阶段；其召唤物死亡触发的国王伤害类例外'],
            ['末日伤害加成','免疫再次加成','第二／三阶段且已有末日状态时；不是全程免疫末日状态'],
            ['伤害结算','转为延迟伤害','第三阶段；已延迟的伤害除外，不应把本次输入直接视为即时扣血'],
        ])
    elif name=='yogdzewa':
        rows.append(['所有伤害','无敌','战斗尚未开始，或任意古神之拳仍存活时'])
    elif name.startswith('yogfist$'):
        rows.append(['所有伤害','无敌','距古神基座4格以内；按游戏八方向距离判断'])
    elif name=='gnollgeomancer':
        rows.extend([
            ['所有伤害','无敌','该地卜师所连接的豺狼人爆破手仍存活时'],
            ['非镐子来源的伤害','无敌','有岩石护甲时；镐子只绕过岩石护甲这一条件'],
            ['外来状态施加','拒绝施加','仍睡眠时；自身岩石护甲和延迟落石除外'],
        ])
    elif name=='crystalspire':
        rows.append(['非镐子来源的伤害','无敌','必须使用镐子破坏；固定免疫列表仍另行适用'])
    elif name=='crystalguardian':
        rows.append(['来自生物的伤害','有条件无敌','倒地恢复期间；角色和水晶尖塔来源例外，不能推定所有来源均无效'])
    if name.startswith('elemental$') or name.startswith('quest.vault.vaultelemental$'):
        fire = name.endswith(('$fireelemental','$newbornfireelemental','$fire'))
        frost = name.endswith(('$frostelemental','$frost'))
        if fire or frost:
            health = row['stats']['HT']
            rows.append(['冻结／冻伤状态施加' if fire else '燃烧状态施加',
                         f'转为{health//2}–{health*3//5} HP基础伤害',
                         '不保留该状态；基础范围按此种普通最大生命计算，临时最大生命和其他承伤处理另计'])
    return {'title':'固有抗性、免疫与防御条件','columns':['效果或伤害来源','规则','条件'],
            'rows':rows,'note':
            ('表内 ×0.5 是抗性系数，不是触发概率。实际伤害按效果自己的结算顺序取整；状态的持续或强度如何使用抗性由该效果决定。'
             '同一抗性类去重，不同父类同时匹配时系数相乘。免疫按效果来源类及其子类判断；附带效果分别结算。'
             '临时增益、精英、装备刻印和其他未列分支另计。' if rows else
             '此种敌人没有列出的固有抗性或免疫。普通护甲、闪避、临时状态与其他防御分支仍分别生效。')}


def _category(name, depth, probability=1, *, floor_set=None):
    data = reference()
    if name == 'ALL':
        weights = data['category_weights']
        total = sum(weights.values())
        return [item for category, weight in weights.items() if weight > 0
                for item in _category(category, depth, probability*weight/total)]
    if name in ('WEAPON','ARMOR','MISSILE'):
        floor_set = min(4,max(0,depth//5 if floor_set is None else floor_set))
        weights = data['tier_weights'][floor_set]
        total = sum(weights)
        result = []
        for i, weight in enumerate(weights):
            if not weight: continue
            chance = probability*weight/total
            if name == 'ARMOR':
                item = data['categories']['ARMOR'][i]
                result.append({**item,'probability':chance})
            else:
                result.extend(_category(('WEP_T' if name == 'WEAPON' else 'MIS_T')+str(i+1),depth,chance))
        return result
    entries = data['categories'][name]
    total = sum(row['weight'] for row in entries)
    result = [{**row,'probability':probability*row['weight']/total} for row in entries if row['weight']]
    if name == 'GOLD':
        for row in result:
            row.update(quantity=span(30+10*depth, 60+20*depth), condition='金币数量在范围内按整数等概率生成')
    if name == 'ARTIFACT':
        for row in result:
            row['condition'] = '神器池仍为初始状态时；已生成过的神器会被移除，池空后改为戒指'
    return result


def _item(values, identity, probability=1, quantity=1, condition=''):
    row = values.rules.entries.get(identity)
    name = row['name'] if row else values.catalog.messages.get(identity+'.name',identity)
    return {'id':identity,'name':name,'quantity':quantity,'probability':probability,'condition':condition}


def loot_rows(values, identity, row, p):
    name = _family(identity)
    depth, count, hero = p['depth'], p['loot_count'], p['hero_level']
    chance = float(row['base_loot_chance'])
    limit = row['stats']['maxLvl']+2
    gate = hero <= limit
    condition = f'角色等级不超过 {limit} 级' if limit > 0 else '此种敌人的普通掉落通道关闭'
    if name in ('skeleton','necromancer$necroskeleton','guard','shaman','thief','bandit','dm200','dm201','golem'):
        chance *= (1/3)**count
        condition += f'；本局同一掉落计数已成功掉落 {count} 次，每次后概率降至原来的 1/3'
    elif name in ('slime','causticslime'):
        chance *= (1/4)**count
        condition += f'；本局史莱姆武器已掉落 {count} 次，每次后概率降至原来的 1/4'
    elif name in ('bat','necromancer','spectralnecromancer','swarm'):
        cap = 7 if name == 'bat' else 5 if name == 'swarm' else 6
        if name == 'swarm': chance = 1/(6*(p['swarm_generation']+1))
        chance *= max(0,cap-count)/cap
        condition += f'；本局此计数已掉落 {count} 瓶，达到 {cap} 瓶后为 0%'
        if name == 'swarm': condition += f'；分裂代数 {p["swarm_generation"]}（原始蝇群为 0）'
    chance = min(1,max(0,chance)) if gate else 0
    rows = []
    expr = row['loot_expression'] or 'null'
    if name in ('slime','causticslime'):
        rows = _category('WEP_T2',depth,chance)
        condition += '；武器固定为 +0，仍可能有附魔或诅咒'
    elif name == 'armoredbrute':
        rows = [_item(values,'items.armor.scalearmor',chance*.75),_item(values,'items.armor.platearmor',chance*.25)]
    elif name in ('dm200','dm201','golem'):
        floor_set = 5 if name == 'golem' else 4
        rows = _category('WEAPON',depth,chance/2,floor_set=floor_set)+_category('ARMOR',depth,chance/2,floor_set=floor_set)
    elif name in ('thief','bandit'):
        rows = _category('RING',depth,chance/2)+_category('ARTIFACT',depth,chance/2)
    elif name == 'eye':
        rows = [_item(values,'items.dewdrop',chance*.5,2)] + _category('SEED',depth,chance*.25)+_category('STONE',depth,chance*.25)
    elif name in ('scorpio','succubus'):
        category = 'POTION' if name == 'scorpio' else 'SCROLL'
        excluded = ('items.potions.potionofhealing','items.potions.potionofstrength') if name == 'scorpio' else ('items.scrolls.scrollofidentify','items.scrolls.scrollofupgrade')
        pool = [item for item in reference()['categories'][category] if item['id'] not in excluded]
        rows = [{**item,'probability':chance/len(pool)} for item in pool]
        condition += '；从可选种类等概率选取，不使用普通生成权重'
    elif name == 'warlock':
        healing = max(0,7-count)/24
        rows = [_item(values,'items.potions.potionofhealing',chance*healing)]
        pool = [r for r in _category('POTION',depth) if r['id'] != 'items.potions.potionofhealing']
        total = sum(r['probability'] for r in pool)
        rows += [{**r,'probability':chance*(1-healing)*r['probability']/total} for r in pool]
        condition += f'；术士治疗药剂已掉落 {count} 瓶，达到 7 瓶后不再掉治疗药剂'
    elif name.startswith('quest.vault.') and name != 'quest.vault.vaultbosselemental':
        rows = [_item(values,'items.quest.dwarftoken',1 if gate else 0)]
    elif name == 'gnollexile':
        rows = _category('ALL',depth,1 if gate else 0)
        condition += '；先抽取2件（50%）或3件（50%）；此列是每次抽取的概率；神器仍受唯一池限制'
    elif expr.startswith('Generator.Category.'):
        rows = _category(expr.rsplit('.',1)[-1],depth,chance)
        if name == 'gnolltrickster':
            rows = [{**r,'quantity':(r['quantity']+1)//2} for r in rows]
            condition += '；+0、无诅咒；投掷武器数量减半并向上取整'
    elif expr not in ('null','None'):
        targets = {
            'PotionOfExperience.class':'items.potions.potionofexperience','MysteryMeat.class':'items.food.mysterymeat',
            'PotionOfHealing.class':'items.potions.potionofhealing','Gold.class':'items.gold',
            'ScrollOfTransmutation.class':'items.scrolls.scrolloftransmutation','PotionOfLiquidFlame.class':'items.potions.potionofliquidflame',
            'PotionOfFrost.class':'items.potions.potionoffrost','ScrollOfRecharging.class':'items.scrolls.scrollofrecharging',
            'Spear.class':'items.weapon.melee.spear','Food.class':'items.food.food','PhantomMeat.class':'items.food.phantommeat',
            'Pasty.class':'items.food.pasty','new MysteryMeat().quantity(2)':'items.food.mysterymeat',
        }
        quantity = 2 if name == 'greatcrab' else span(30+10*depth,60+20*depth) if expr == 'Gold.class' else 1
        rows = [_item(values,targets[expr],chance,quantity)]
        if expr == 'Gold.class': condition += '；金币数量在范围内按整数等概率生成'
    for item in rows:
        item['condition'] = condition + ('；'+item['condition'] if item.get('condition') else '')
    extras = {
        'causticslime':('items.quest.gooblob',1,1), 'dm201':('items.quest.metalshard',1,1),
        'spectralnecromancer':('items.scrolls.scrollofremovecurse',1,1),
        'rotheart':('plants.rotberry$seed',1,1), 'tengu':('items.tengusmask',1,1),
        'dwarfking':('items.kingscrown',1,1),
    }
    if name in extras:
        item, probability, quantity = extras[name]
        gated = name in ('causticslime','dm201','spectralnecromancer')
        rows.append(_item(values,item,probability if gate or not gated else 0,quantity,
                          (f'角色等级不超过 {limit} 级；' if gated else '')+'固定奖励，与普通随机掉落分别结算'))
    if name in ('goo','dm300'):
        item = 'items.quest.gooblob' if name == 'goo' else 'items.quest.metalshard'
        rows += [_item(values,item,probability,quantity,'首领奖励；不受普通随机掉落概率影响') for quantity,probability in ((2,.6),(3,.3),(4,.1))]
        if name == 'goo': rows.append(_item(values,'items.keys.wornkey',1,1,'击败本层粘咕后的固定钥匙奖励'))
    if name == 'hermitcrab':
        rows += [{**r,'condition':f'角色等级不超过 {limit} 级；额外固定获得一件护甲'} for r in _category('ARMOR',depth,1 if gate else 0)]
    if name in ('thief','bandit'):
        rows.append({'name':'尚未丢失的被盗物品','quantity':'被盗数量','probability':1,'condition':'仅在敌人仍携带该物品时；返还不受普通掉落等级上限影响'})
    if name in ('statue','armoredstatue'):
        rows.append({'name':'该石像所持武器','quantity':1,'probability':1,'condition':'非腐化复制体；具体装备在生成时决定，普通掉率表不能推断本局所持装备'})
        if name == 'armoredstatue': rows.append({'name':'该石像所穿护甲','quantity':1,'probability':1,'condition':'非腐化复制体；具体装备在生成时决定'})
    if name in ('mimic','goldenmimic','crystalmimic','ebonymimic'):
        rows.append({'name':'生成时装入及尚未丢失的全部战利品','quantity':'随容器内容变化','probability':1,'condition':'物品在生成时决定；击杀时返还，普通掉率表不能推断本局容器内容'})
    if name == 'tormentedspirit':
        rows += [{**r,'condition':'净化后的奖励；普通击杀不会给此奖励；装备无诅咒且有附魔／刻印'} for r in _category('WEAPON',depth,.5)+_category('ARMOR',depth,.5)]
    return rows


def add_monster_values(values, identity, p, result, requested):
    row = monster_record(values.catalog,identity)
    if row is None: return False
    depth, hero = p['depth'],p['hero_level']
    requested.add('hero_level')
    name = _family(identity)
    uses_depth = bool(row['dynamic']) or row['loot_expression'] in ('Gold.class','Generator.Category.ARMOR','Generator.Category.WEAPON','Generator.Category.MISSILE') or name in ('dm200','dm201','golem','hermitcrab','thief','bandit','tormentedspirit','gnollexile')
    if uses_depth: requested.add('depth')
    counts = ('skeleton','necromancer$necroskeleton','guard','shaman','thief','bandit','dm200','dm201','golem','slime','causticslime','bat','necromancer','spectralnecromancer','swarm','warlock')
    if name in counts: requested.add('loot_count')
    if name == 'swarm': requested.add('swarm_generation')
    stats = normal_stats(row,identity,depth)
    max_level = stats['maxLvl']
    exp = stats['EXP'] if max_level >= 1 else 0
    exp_condition=f'角色等级不超过 {max_level} 级时' if max_level>=1 else '此种敌人通常不提供升级经验'
    if name=='swarm':
        if p['swarm_generation']>0: exp=0
        exp_condition+=f'；所填分裂代数 {p["swarm_generation"]}；正代数分裂体不提供经验'
    stat_rows = [
        _metric('初始生命',stats['HP'],'HP'), _metric('初始最大生命',stats['HT'],'HP'),
        _metric('基础伤害范围',stats['damageRoll'],'HP','普通攻击；特殊攻击和状态效果不能按此范围估算'),
        _metric('基础命中',stats['attackSkill'],'点','这是命中值，不是最终命中概率'),
        _metric('基础闪避',stats['defenseSkill'],'点','伏击、麻痹等会改变实际闪避'),
        _metric('基础减伤范围',stats['drRoll'],'HP','无树肤等额外状态'),
        _metric('基础经验',exp,'经验',exp_condition),
        _metric('所填等级可获经验',exp if hero<=max_level else 0,'经验',f'所填角色等级 {hero}；普通击杀，无飞升及坠落等特殊处理'),
        _metric('基础速度倍率',stats['baseSpeed'],'倍','攻击耗时和特殊状态另计'),
        _metric('普通攻击基础耗时',stats['attackDelay'],'回合','无肾上腺素等修正；与移动速度分别计算，不保证固定攻击次数'),
    ]
    note = '普通敌人、正常状态，无挑战、精英、飞升、召唤盟友或其他状态修正。随机范围端点不表示等概率。'
    if row['dynamic']: note += f' 此表按生成时层数 {depth} 计算；已生成敌人的层数不会随玩家移动而改变。'
    if row['dynamic'] == 'statue': note += ' 装甲石像的实际闪避还会受所穿护甲影响；具体武器、护甲决定的数值需结合本局装备。'
    if name in ('crystalspire','fungalcore','demonspawner','necromancer','spectralnecromancer','yogdzewa'): note += ' 此类敌人的主要伤害来自特殊能力或召唤，普通攻击值不表示它会使用普通攻击。'
    result.insert(0,{'title':'常规战斗数值','values':stat_rows,'note':note})
    loot = loot_rows(values,identity,row,p)
    result.insert(1,{'title':'掉落物、数量与概率','columns':['掉落物','每次抽取数量' if name=='gnollexile' else '数量','每次抽取概率' if name=='gnollexile' else '每次满足条件的概率','条件'],
                    'rows':[[r['name'],str(r['quantity']),display(100*r['probability'])+'%',r.get('condition','')] for r in loot],
                    'note':'按所填角色等级和本局累计掉落次数计算，默认无财富戒指、赏金猎人、遗忘碎片、幸运附魔或异晶饰品。物品池表已乘上该敌人的普通掉率；不代表本次一定掉落。神器池使用初始可用池参考，实际已生成神器会改变分布。' if loot else '此敌人没有常规自身物品掉落。任务奖励、已存容器、财富戒指和幸运附魔等额外机制按各自条件结算。'})
    abilities = []
    if name == 'goo':
        result.insert(2,{'title':'粘咕生命阶段与蓄力攻击','columns':['生命阶段','普通基础伤害HP','蓄力基础伤害HP','普通命中值','蓄力命中值','基础闪避值'],
            'rows':[['高于最大生命的50%','1–8','3–24','10','20','8'],
                    ['不超过最大生命的50%','1–12','3–36','15','30','12']],
            'note':'正常难度；蓄力只是基础伤害乘3、命中值乘2，目标护甲和最终命中检定仍生效。半血判定包括恰好50%；水中恢复可能重新跨回高血量阶段。'})
        abilities = [_metric('高血量选择开始蓄力概率',20,'%','可发动攻击且尚未蓄力时的选择概率；不是每回合固定概率'),
                     _metric('半血选择开始蓄力概率',50,'%','生命不超过最大生命的50%，可发动攻击且尚未蓄力时'),
                     _metric('正常蓄力准备',2,'次自身攻击行动','开始和继续准备各耗默认1回合，之后发射攻击再耗默认1回合；其他状态修正另计'),
                     _metric('蓄力攻击最大距离',2,'格','需双方方向的攻击弹道都可达；实际墙角与光路以游戏为准'),
                     _metric('攻击命中后施加淤泥概率','1/3','','目标抗性及免疫另计'),
                     _metric('正常水中每次行动恢复',1,'HP','没有飞行、当前格是水且生命未满时；不是每个玩家行动必定恢复')]
    elif name == 'greatcrab':
        abilities = [_metric('格挡当前目标时的闪避','无限闪避','','已注意目标、未睡眠、未麻痹且攻击者为当前非隐形目标；无限命中也不能绕过无限闪避分支'),
                     _metric('未满足格挡条件时的基础闪避',0,'点','随后仍有普通伏击和其他状态处理'),
                     _metric('格挡法杖与牧师法术的直接伤害',0,'HP','已注意、未睡眠、未麻痹，且当前目标为非隐形玩家；附加和环境效果另计'),
                     _metric('追近尝试中的原地停顿','每3次中的第3次','','前2次调用普通追近，第3次不移动；寻路、其他行动和状态仍会影响实际移动')]
    elif name in ('mimic','goldenmimic','ebonymimic','crystalmimic'):
        level=_mimic_level(name,depth)
        damage=span(1+level,2+2*level) if name=='crystalmimic' else (2+2*level)*(2 if name=='ebonymimic' else 1)
        abilities=[_metric('伪装首击基础伤害',damage,'HP','尚在伪装状态时发动攻击；目标护甲等仍可减伤'),
                   _metric('伪装首击命中值','无限命中','','目标未隐形时；无限闪避及其他命中规则另计')]
        if name=='crystalmimic':
            abilities.append(_metric('伪装首击额外伤害倍率',1,'倍','水晶宝箱怪没有普通宝箱怪的首击伤害加成；攻击角色时另尝试偷走符合条件的未装备物品'))
    elif name == 'eye':
        requested.add('damage')
        abilities = [_metric('死亡凝视基础伤害','30–50','HP','光路上的每个目标分别进行魔法命中检定；不扣普通护甲，抗性等另计'),
                     _metric('死亡凝视蓄力耗时',2,'回合','默认攻击耗时1回合的两倍；肾上腺素等状态另计'),
                     _metric('死亡凝视发射耗时',1,'回合','默认攻击耗时；蓄力后目标离开视野仍可能向先前位置发射'),
                     _metric('发射后冷却计数','4–6','次自身行动','每次自身行动开始减1；不是固定的角色回合数'),
                     _metric('魔法命中掷骰倍率',2,'倍','基础命中30的随机掷骰乘2，再与目标闪避掷骰比较；不是必中或最终命中概率'),
                     _metric('蓄力时所填伤害缩减后',p['damage']//4,'HP','进入邪眼承伤分支的伤害先除4并向下取整，之后仍受抗性等处理影响')]
    elif name == 'dm100':
        abilities = [_metric('远程电击基础伤害','3–10','HP','目标非相邻，且魔法弹道可达目标时；相邻或弹道被阻挡时使用普通攻击'),
                     _metric('远程电击耗时',1,'回合','不扣普通护甲，抗性等另计'),
                     _metric('魔法命中掷骰倍率',2,'倍','基础命中11的随机掷骰乘2，再与目标闪避掷骰比较；不是必中或最终命中概率')]
    elif name == 'dm200':
        abilities=[_metric('排气行动耗时',1,'回合','敌人可见、不能普通攻击，且通过距离随机检定与可排气路径检查时'),
                   _metric('排气后冷却计数',30,'次自身行动','每次自身行动开始减1；初始0，不是固定角色回合数'),
                   _metric('排气选择检定','1 / ⌊100÷距敌距离⌋','','仅距离至少1且仍不能普通攻击时；通过检定不保证能排气，路径与冷却仍需满足'),
                   _metric('弹道路径每格播种毒气体积',20,'体积','Ballistica.subPath(0,dist) 所列格；体积不是伤害或固定持续时间'),
                   _metric('弹道终点另播种毒气体积',100,'体积','在路径播种之后添加；扩散、叠加、抗性与中毒伤害分别结算')]
    elif name == 'dm201':
        abilities=[_metric('腐蚀气体喷射耗时',1,'回合','受到符合条件的非腐化伤害后记为受威胁；目标在视野内才喷射，随后清除此标记'),
                   _metric('目标格腐蚀气体体积',15,'体积','体积不是伤害或固定持续时间'),
                   _metric('目标周围非实心格各播种体积',5,'体积','周围8格，实心格跳过'),
                   _metric('腐蚀气体基础强度',8,'强度参数','环境气体与腐蚀状态分别更新；不按每次攻击8点伤害理解'),
                   _metric('DM-200普通毒气排气','不使用','','此变体禁止普通排气及追近／逃离，不能套用DM-200的30次计数分支')]
    elif name == 'gnolltrickster':
        requested.add('trickster_combo')
        combo=p['trickster_combo']+1
        rows=[]
        for roll in range(4):
            effect=combo+roll
            poison=f'中毒基础持续参数 {effect-2} 回合' if effect>2 else '不附加中毒或点燃'
            rows.append([roll,25,combo,'点燃' if effect>=6 else poison,poison])
        result.append({'title':'豺狼诡术师本次命中连击效果','columns':['随机整数','概率%','递增后连击数','目标尚未燃烧','目标已燃烧'],
            'rows':rows,'note':'仅普通攻击成功进入命中效果处理后；连击先加1，再均匀抽取0–3并相加。调用追近／拉开路径时把连击重置为0；不把手填连击当当前存档状态。已有中毒、燃烧、抗性及免疫按效果自身规则结算。'})
        abilities=[_metric('可燃目标格点燃时播种火焰体积',4,'体积','仅效果值至少6、目标尚未燃烧且当前格可燃时；角色仍尝试获得燃烧状态'),
                   _metric('连击重置',0,'次','调用getCloser路径时，不要求最终实际移动成功')]
    elif name == 'warlock':
        abilities = [_metric('远程暗影弹基础伤害','12–18','HP','目标非相邻且魔法弹道可达时；不扣普通护甲，抗性等另计'),
                     _metric('远程暗影弹耗时',1,'回合'),
                     _metric('魔法命中掷骰倍率',2,'倍','命中随机掷骰乘2；不是最终命中概率'),
                     _metric('命中角色后施加降级概率',50,'%','只对角色；目标抗性和免疫另计'),
                     _metric('降级基础持续',30,'回合','已有更长状态不缩短；抗性及其他状态修正另计')]
    elif name in ('skeleton','necromancer$necroskeleton'):
        abilities = [_metric('死亡碎骨爆炸基础伤害','6–12','HP','非坠落死亡时，对周围8格的存活角色分别结算；不进行命中检定'),
                     _metric('碎骨爆炸护甲减伤掷骰',2,'次','将目标两次独立减伤掷骰之和扣除，最低伤害0；不是同一次掷骰简单翻倍，其他防护另计')]
    elif name in ('brute','armoredbrute'):
        armored=name=='armoredbrute'
        abilities = [_metric('濒死狂暴基础伤害','15–40','HP','首次生命降至0后进入狂暴，非坠落；目标护甲仍可减伤'),
                     _metric('正常濒死狂暴初始护盾',21 if armored else 24,'HP','基础最大生命40；最大生命改变时，护盾按最大生命÷2取整后加1或4计算'),
                     _metric('狂暴护盾每次自然衰减',1 if armored else 4,'HP','护盾也会被受到的伤害消耗，耗尽后死亡'),
                     _metric('狂暴护盾自然衰减间隔',3 if armored else 1,'回合','狂暴状态自己的行动间隔；不能据此保证还能攻击固定次数')]
    elif name == 'spinner':
        abilities = [_metric('攻击命中后施加中毒概率',50,'%','目标抗性和免疫另计；触发后清除吐网冷却并尝试逃离'),
                     _metric('新中毒基础持续','7–8','回合','已有中毒取更长持续时间；不是7–8点总伤害，解毒及抗性另计')]
    elif name == 'scorpio':
        abilities = [_metric('远程攻击基础伤害','30–40','HP','仅攻击非相邻、投射弹道可达的目标；不是魔法命中，目标护甲仍生效'),
                     _metric('攻击命中后施加残废概率',50,'%','目标抗性和免疫另计'),
                     _metric('残废基础持续',10,'回合','已有更长状态不缩短；目标抗性和其他状态修正另计')]
    elif name == 'shaman':
        names=[values.catalog.messages['actors.buffs.'+buff+'.name'] for buff in ('weakness','vulnerable','hex')]
        abilities = [_metric('远程土弹伤害','6–15','HP','魔法命中检定；每次攻击耗时1回合'),
                     _metric('命中后附加负面状态概率',50,'%',f'红色{names[0]}、蓝色{names[1]}、紫色{names[2]}')]
    elif name == 'pylon':
        requested.add('damage')
        damage=p['damage']
        reduced=damage if damage<15 else 14+math.floor(math.sqrt(8*(damage-14)+1)-1)//2
        abilities = [_metric('激活后邻格电击伤害','10–20','HP','每回合攻击两个相对的相邻格，方向逐回合旋转；未激活时不攻击且无敌'),
                     _metric('所填伤害压缩后承受',reduced,'HP','激活且伤害类型可生效时；15点及以上输入触发压缩')]
    elif name == 'npcs.vaultsentry':
        abilities = [_metric('扫描首次电击','6–12','HP','可见扫描区域中的非隐形友方目标'),
                     _metric('连续扫描电击','3–6','HP','同一目标在上一次扫描更新中已被电击'),
                     _metric('默认扫描间隔',1,'回合','具体扫描方向、宽度及间隔由宝库房间配置，已生成机关以本局为准')]
    elif name == 'npcs.vaultlaser':
        abilities = [_metric('激光伤害','10–20','HP','路径上的友方目标；不进行命中检定，实墙阻挡光束'),
                     _metric('连续射击间隔',1,'回合','同一轮尚未发射完时；轮次间隔、方向及射击次数由房间配置')]
    if abilities:
        note = '正常难度，无飞升及额外状态修正。'
        if name == 'eye':
            note += ' 冷却结束、目标可见且光路可达时开始蓄力；光路遇实墙阻挡。可见目标可能重新瞄准，不能假定横移一格必定避开；以游戏实际瞄准和警告为准。'
        elif name == 'goo':
            note += ' 追近、后退或离开追击状态会取消蓄力；蓄力攻击尝试结束后也清除蓄力，未命中不会保留。'
        result.insert(2,{'title':'特殊攻击与机制','values':abilities,'note':note})
    result.insert(3 if abilities else 2,defense_block(values,identity,row))
    return True
