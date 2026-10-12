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


def normal_stats(row, identity, depth, *, stronger_bosses=False):
    stats = dict(row['stats'])
    family = row['dynamic']
    name = identity.removeprefix('actors.mobs.')
    if stronger_bosses and name in ('goo','tengu','dm300','dwarfking','pylon'):
        health = {'goo':120,'tengu':250,'dm300':400,'dwarfking':450,'pylon':80}[name]
        stats.update(HP=health,HT=health)
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


def _slime_damage(damage):
    """Slime.damage at normal scaling, including Java float assignment steps."""
    value = float32(damage)
    if value >= 5:
        inside = float32(float32(8 * float32(value - 4)) + 1)
        value = float32(4 + float32(float32(math.sqrt(inside) - 1) / 2))
    return int(value)


def _soiled_fist_damage(damage, grass_cells):
    """SoiledFist.damage's integer product, float division, and Math.round."""
    if grass_cells == 0: return damage
    return math.floor(float32(float32(damage * (6-grass_cells)) / float32(6)) + .5)


def defense_block(values, identity, row, *, stronger_bosses=False):
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
    add_effects(profile,'固有属性参考；额外装备、增益及未列明的挑战变化另计' if stronger_bosses else '固有；无额外装备、增益或挑战')
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
        rows.append(['所有伤害','无敌',f'超载期间；{"绝命头目" if stronger_bosses else "普通难度"}共激活{3 if stronger_bosses else 2}座能量塔，需破坏当前供能塔解除'])
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
        if name=='yogfist$soiledfist':
            rows.extend([
                ['进入承伤分支的整数伤害','输入×（6−草丛格数）÷6，四舍五入','自身及周围8格中的高草、茂草计数0–9；0格时保留原值。6格时为0，负值被普通承伤处理拒绝；其他抗性等随后结算，不是最终扣血'],
                ['燃烧状态造成的伤害','不扣血','仍可被点燃，火焰也能烧毁周围草丛；此规则不等于免疫所有火焰相关来源'],
            ])
        elif name=='yogfist$rottingfist':
            rows.append(['非流血来源的伤害','转为流血强度参数','须不处于无敌，且此拳自身没有镰刀收割标记；先乘来源抗性并四舍五入，再把结果×0.6传给流血。原输入不立即扣血，已有流血与后续每跳分别结算'])
        elif name=='yogfist$rustedfist':
            rows.append(['非延迟伤害状态来源的伤害','加入延迟伤害池','须不处于无敌；先乘来源抗性并四舍五入，非负结果加入粘稠的延迟伤害状态。原输入不立即扣血，延迟状态自己的伤害不再次入池'])
        elif name in ('yogfist$brightfist','yogfist$darkfist'):
            rows.append(['首次跨过半血且仍存活的伤害','生命设回最大生命的一半','本次承伤前高于半血、承伤后不超过半血；正常最大生命300时设回150，随后传送。若本次直接致死则走死亡分支，不保证半血锁血'])
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
    elif name=='gnollguard':
        rows.append(['进入承伤分支的伤害','输入伤害 ÷4，整数截断','该守卫所连接的豺狼爆破手仍存活时；普通抗性等随后结算'])
    elif name=='demonspawner':
        rows.append(['进入承伤分支的整数伤害','20点起压缩，非固定上限','20／40／85点输入变为20／25／30；同时按压缩后的输入推进召唤冷却，再结算普通抗性等，不是最终扣血'])
    elif name in ('monk','senior'):
        rows.append(['需要命中检定的攻击','无限闪避','有专注状态、未麻痹且未睡眠时；无限命中仍不能绕过此分支，不表示所有伤害来源均免疫'])
    elif name in ('slime','causticslime'):
        rows.append(['进入承伤分支的整数伤害','5点起压缩，非固定上限','普通难度、无飞升；10／20／25点输入变为7／9／10，再结算普通抗性、屏障等。可在特殊机制中填写输入'])
    elif name=='phantompiranha':
        rows.append(['非相邻或无法定位的伤害来源','输入伤害 ÷2，四舍五入','生物来源使用该生物位置，法杖或牧师法术使用玩家位置；按八方向相邻判断。先减半取整再结算普通抗性等，不是最终扣血'])
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


def _wealth_applies(identity, row):
    # Mob.lootChance applies both Wealth and Shard of Oblivion. These four
    # Vault overrides return 1 without calling it; their inherited loot differs.
    return row['base_loot_chance']>0 and _family(identity) not in (
        'quest.vault.vaultdm200','quest.vault.vaultgolem','quest.vault.vaultshaman','quest.vault.vaultskeleton')


def _exotic_loot_target(identity):
    # Only these reviewed classes reach Mob.createLoot's Class<?> branch.
    # Acidic and the category-pool overrides bypass that branch entirely.
    name=_family(identity)
    if name in ('bat','necromancer','spectralnecromancer','swarm','demonspawner'):
        return 'items.potions.exotic.potionofshielding'
    return {
        'elemental$fireelemental':'items.potions.exotic.potionofdragonsbreath',
        'elemental$newbornfireelemental':'items.potions.exotic.potionofdragonsbreath',
        'elemental$frostelemental':'items.potions.exotic.potionofsnapfreeze',
        'elemental$shockelemental':'items.scrolls.exotic.scrollofmysticalenergy',
        'elemental$chaoselemental':'items.scrolls.exotic.scrollofmetamorphosis',
    }.get(name)


def loot_rows(values, identity, row, p):
    name = _family(identity)
    depth, count, hero = p['depth'], p['loot_count'], p['hero_level']
    chance = float(row['base_loot_chance'])
    if name == 'swarm': chance = 1/(6*(p['swarm_generation']+1))
    limit = row['stats']['maxLvl']+2
    gate = hero <= limit
    condition = f'角色等级不超过 {limit} 级' if limit > 0 else '此种敌人的普通掉落通道关闭'
    modifier_condition = ''
    ordinary_gate = gate and not p.get('loot_stolen',0)
    if row['base_loot_chance']>0:
        condition += ('；此目标的普通战利品已被袖章成功偷取，不再次普通掉落' if p.get('loot_stolen',0) else
                      '；此目标未被袖章成功偷取普通战利品（失败尝试不关闭此通道）')
    if _wealth_applies(identity,row):
        wealth=p.get('wealth_bonus',0)
        multiplier=float32(math.pow(1.2,wealth))
        bounty,preparation=p.get('bounty_hunter',0),p.get('preparation_level',0)
        bonus=0
        if bounty>0 and preparation>0:
            bonus=float32(float32(float32(.02)*float32(math.pow(2,preparation-1)))*bounty)
            multiplier=float32(multiplier+bonus)
        modifier_condition += f'；赏金猎人有效点数 {bounty}，准备阶段 {preparation}，额外倍率 +{display(bonus)}（须击杀时标记与准备同时生效）'
        level=p.get('oblivion_shard',-1)
        eligible=p.get('unidentified_equipment',0)
        if level >= 0:
            effective=min(eligible,level+1)
            fragment=float32(1+float32(float32(.2)*effective))
            multiplier=float32(multiplier+float32(fragment-1))
            modifier_condition += f'；遗忘碎片生效等级 {level}，合格未鉴定项 {eligible}，按等级上限计入 {effective} 项；碎片额外倍率与财富、赏金猎人相加'
        chance *= multiplier
        modifier_condition = f'；财富有效加成 {wealth}，普通掉率倍率 {display(multiplier)}，概率最高100%'+modifier_condition
    if name in ('skeleton','necromancer$necroskeleton','guard','shaman','thief','bandit','dm200','dm201','golem'):
        chance *= (1/3)**count
        condition += f'；本局同类战利品已生成 {count} 次（含袖章成功偷取），每次后概率降至原来的 1/3'
    elif name in ('slime','causticslime'):
        chance *= (1/4)**count
        condition += f'；本局史莱姆武器已生成 {count} 次（含袖章成功偷取），每次后概率降至原来的 1/4'
    elif name in ('bat','necromancer','spectralnecromancer','swarm'):
        cap = 7 if name == 'bat' else 5 if name == 'swarm' else 6
        chance *= max(0,cap-count)/cap
        condition += f'；本局此计数已生成 {count} 瓶（含袖章成功偷取），达到 {cap} 瓶后为 0%'
        if name == 'swarm': condition += f'；分裂代数 {p["swarm_generation"]}（原始蝇群为 0）'
    condition += modifier_condition
    chance = min(1,max(0,chance)) if ordinary_gate else 0
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
        condition += f'；术士治疗药剂已生成 {count} 瓶（含袖章成功偷取），达到 7 瓶后不再掉治疗药剂'
    elif name.startswith('quest.vault.') and name != 'quest.vault.vaultbosselemental':
        rows = [_item(values,'items.quest.dwarftoken',chance if _wealth_applies(identity,row) else 1 if ordinary_gate else 0)]
        if not _wealth_applies(identity,row):condition += '；此种宝库变体普通掉率固定为100%，不使用财富、赏金猎人或遗忘碎片倍率'
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
    exotic=_exotic_loot_target(identity)
    if exotic:
        level=p.get('exotic_crystals',-1)
        conversion=0 if level==-1 else float32(float32(.2)+float32(float32(.2)*level))
        original=rows[0]
        rows=[{**original,'probability':original['probability']*(1-conversion)}]
        if conversion:
            rows.append(_item(values,exotic,original['probability']*conversion,original['quantity']))
        condition+=f'；异晶生效等级 {level}（−1为无效果），普通掉落成功后按 {display(100*conversion)}% 转换为对应合剂／秘卷；两行互斥，不额外增加掉落次数'
    for item in rows:
        item['condition'] = condition + ('；'+item['condition'] if item.get('condition') else '')
    extras = {
        'causticslime':('items.quest.gooblob',1,1), 'dm201':('items.quest.metalshard',1,1),
        'spectralnecromancer':('items.scrolls.scrollofremovecurse',1,1),
        'rotheart':('plants.rotberry$seed',1,1), 'tengu':('items.tengusmask',1,1),
        'dwarfking':('items.kingscrown',1,1),
        'elemental$newbornfireelemental':('items.quest.embers',1,1),
    }
    if name in extras:
        item, probability, quantity = extras[name]
        gated = name in ('causticslime','dm201','spectralnecromancer')
        rows.append(_item(values,item,probability if gate or not gated else 0,quantity,
                          (f'角色等级不超过 {limit} 级；' if gated else '')+'固定奖励，与普通随机掉落分别结算'))
        if name == 'rotheart':
            rows[-1]['condition'] = '正常死亡时的固定奖励；燃烧伤害会直接摧毁腐莓核心，绕过死亡掉落，无法获得此种子'
        elif name == 'elemental$newbornfireelemental':
            rows[-1]['condition'] = '敌对新生火焰元素死亡时独立掉落1份余烬；不受普通掉落等级上限、财富或异晶转换影响；友方召唤体不提供此任务奖励'
    if name == 'rotlasher':
        for item in rows:
            item['condition'] += '；燃烧直接摧毁时绕过正常死亡掉落'
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
        condition = '正常击杀时掉落现有携带物；生成奖励在生成时决定，普通掉率表不能推断本局容器内容'
        if name == 'crystalmimic':
            condition += '；后来偷来的物品另计，不享受生成奖励的去诅咒规则；成功逃脱会连同携带物消失'
        rows.append({'name':'生成时装入及尚未丢失的全部战利品','quantity':'随容器内容变化','probability':1,'condition':condition})
    if name == 'tormentedspirit':
        rows += [{**r,'condition':'净化后的奖励；普通击杀不会给此奖励；装备无诅咒且有附魔／刻印'} for r in _category('WEAPON',depth,.5)+_category('ARMOR',depth,.5)]
    # Challenges.isItemBlocked only removes Dewdrop at Level.drop. It does
    # not cancel the loot draw or block seeds, stones, food, or healing items.
    for item in rows:
        if item.get('id') == 'items.dewdrop':
            generated = item['probability']
            blocked = p.get('no_herbalism',0) == 1
            item['generation_probability'] = generated
            if blocked: item['probability'] = 0
            item['condition'] += (f'；生成分支概率 {display(100*generated)}%，每次生成2份露珠；'
                                  + ('荒芜之地阻止两份露珠落地，可取得概率0%' if blocked else
                                     '未开启荒芜之地，露珠可正常落地'))
    return rows


def _mimic_prize_block(name):
    if name not in ('goldenmimic','ebonymimic','crystalmimic'): return None
    if name == 'crystalmimic':
        rules = [_metric('生成奖励数量','保留预先装入的奖励','','水晶宝库房间自然生成时预装1件法杖、戒指或神器，神器池耗尽时改为戒指；其他来源以预装内容为准。不额外生成基类的五类随机奖励，也不另抽宝箱怪之牙奖励'),
                 _metric('生成时奖励的诅咒标记','清除并标为已知','','对当时已装入的全部物品处理；此分支不额外升级，也没有黄金／黑檀变体的诅咒附魔、刻印清除步骤')]
    else:
        rules = [_metric('生成时新增基础奖励',1,'条','在预先装入物品之外，从金币、投掷武器、护甲、近战武器、戒指五类均等抽候选；空结果或挑战禁物重抽，不能把最终类别比例一律当成20%。金币数量和投掷堆叠数量按各自生成规则'),
                 _metric('宝箱怪之牙额外抽取',1,'条','仅宝箱怪之牙的隐蔽宝箱怪效果生效时，从默认物品池另抽一次；与基础奖励及黑檀额外抽取分别计算'),
                 _metric('生成奖励质量','装备／法杖去诅咒','','处理当时已装入的装备类物品与法杖：清除诅咒并标为已知；武器的诅咒附魔、护甲的诅咒刻印也移除，正常附魔／刻印不因此移除'),
                 _metric('生成奖励中 +0 非神器升级',50 if name == 'goldenmimic' else 100,'%','仅上述装备类物品与法杖，且处理时等级恰为+0、不是神器；升级1次。神器、负等级和已有正等级物品不走此升级分支')]
        if name == 'ebonymimic':
            rules.insert(2,_metric('黑檀独立额外抽取',1,'条','再从默认物品池抽一次，然后统一处理奖励质量；因此生成时新增奖励共2条，宝箱怪之牙隐蔽效果生效时共3条，均不含预先装入内容'))
    return {'title':'生成奖励与质量','values':rules,
            'note':'在宝箱怪生成时处理奖励；只将诅咒状态标为已知，不因此鉴定等级或全部属性。击杀只是掉落仍携带的内容，不会重新抽取或升级。后来偷来的物品不套用这些生成规则；此资料不读取或鉴定本局容器内容。'}


def add_monster_values(values, identity, p, result, requested):
    row = monster_record(values.catalog,identity)
    if row is None: return False
    depth, hero = p['depth'],p['hero_level']
    requested.add('hero_level')
    name = _family(identity)
    boss_condition = identity in ('actors.mobs.goo','actors.mobs.tengu','actors.mobs.dm300','actors.mobs.dwarfking','actors.mobs.yogdzewa','actors.mobs.pylon')
    stronger = boss_condition and p['stronger_bosses'] == 1
    if boss_condition: requested.add('stronger_bosses')
    if name == 'eye': requested.add('no_herbalism')
    if _exotic_loot_target(identity):requested.add('exotic_crystals')
    if row['base_loot_chance']>0: requested.add('loot_stolen')
    if _wealth_applies(identity,row): requested.update(('wealth_bonus','oblivion_shard','unidentified_equipment','bounty_hunter','preparation_level'))
    uses_depth = bool(row['dynamic']) or row['loot_expression'] in ('Gold.class','Generator.Category.ARMOR','Generator.Category.WEAPON','Generator.Category.MISSILE') or name in ('dm200','dm201','golem','hermitcrab','thief','bandit','tormentedspirit','gnollexile')
    if uses_depth: requested.add('depth')
    counts = ('skeleton','necromancer$necroskeleton','guard','shaman','thief','bandit','dm200','dm201','golem','slime','causticslime','bat','necromancer','spectralnecromancer','swarm','warlock')
    if name in counts: requested.add('loot_count')
    if name == 'swarm': requested.add('swarm_generation')
    if name in ('causticslime','fetidrat','goo','acidic','yogfist$rottingfist'): requested.add('depth')
    stats = normal_stats(row,identity,depth,stronger_bosses=stronger)
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
    if stronger:
        note = '绝命头目挑战：采用已核对的首领初始生命；其余基础战斗数值沿用普通参考。特殊机制与防御条件按各块说明，未覆盖全部挑战变化；无精英、飞升或其他状态修正。随机范围端点不表示等概率。'
    if name=='eye' and p.get('no_herbalism',0)==1:
        note = '普通基础战斗数值；掉落部分已应用荒芜之地的露珠落地过滤。其他挑战、精英、飞升、召唤盟友或临时状态修正另计。随机范围端点不表示等概率。'
    if row['dynamic']: note += f' 此表按生成时层数 {depth} 计算；已生成敌人的层数不会随玩家移动而改变。'
    if name in ('fungalcore','fungalsentry','fungalspinner'): note += ' 4.0.2的菌类矿洞任务尚未实装，正常新局不会选择它；以下仅作未实装内容的资料参考，不表示会自然生成。'
    if row['dynamic'] == 'statue': note += ' 装甲石像的实际闪避还会受所穿护甲影响；具体武器、护甲决定的数值需结合本局装备。'
    if name in ('crystalspire','gnollgeomancer','fungalcore','demonspawner','necromancer','spectralnecromancer','yogdzewa','rotheart'): note += ' 此类敌人的主要作用来自特殊能力或召唤，普通攻击值不表示它会使用普通攻击。'
    result.insert(0,{'title':'常规战斗数值','values':stat_rows,'note':note})
    loot = loot_rows(values,identity,row,p)
    loot_note=('按所填角色等级、本局战利品生成计数、财富、赏金猎人与遗忘碎片条件计算；默认未被袖章成功偷取、财富加成0、赏金猎人0（未触发）、准备阶段0（无准备）、遗忘碎片−1（无效果）、合格未鉴定项0，适用的异晶默认−1（无效果）。掉率加成仅用于普通掉落，固定额外奖励另列。'
               '财富有效加成不是戒指等级：无戒指或魔法免疫填0，单枚正常+0戒指填1，正常戒指按生效等级＋1合计；诅咒戒指按min(0, 生效等级−2)合计。'
               '额外形态和临时增益须计入生效加成后手填；未从存档推定。普通掉率按实际判定最高100%，物品池表已乘普通掉率，不代表本次一定掉落。'
               '遗忘碎片合格项由玩家确认：未鉴定的主武器、副武器、护甲、戒指、杂项槽各计1项，近期使用未鉴定法杖／投掷武器的有效标记各计1项；最多7项，实际只计入生效等级＋1项。'
               '赏金猎人需击杀结算时有效标记与刺杀准备同时存在：额外倍率＝0.02×2^(准备等级−1)×点数；未满足填0，不能仅按已投入天赋点数当作生效。准备等级1–4，最多3点。碎片倍率＝1＋0.2×计入项数；普通通道合并倍率＝财富倍率＋赏金猎人额外倍率＋碎片倍率−1，再应用生成计数、等级与成功偷取限制。袖章已成功取走此目标普通战利品时，普通掉落为0；失败尝试不关闭死亡普通掉落。成功偷取调用生成战利品，会推进相应本局计数，请填生成后的计数；不自动递增。碎片生效等级须核对当前降级等状态；不会自动鉴定装备或读取隐藏条件。'
               '本表不计算财富额外战利品或幸运附魔；神器池使用初始可用池参考，实际已生成神器会改变分布。')
    result.insert(1,{'title':'掉落物、数量与概率','columns':['掉落物','每次抽取数量' if name=='gnollexile' else '数量','每次抽取概率' if name=='gnollexile' else '每次满足条件的概率','条件'],
                    'rows':[[r['name'],str(r['quantity']),display(100*r['probability'])+'%',r.get('condition','')] for r in loot],
                     'note_summary':(('荒芜之地仅阻止露珠落地；露珠行显示可取得概率，条件列保留生成分支概率。种子和符石不受此过滤影响。' if name=='eye' else '')+'按条件列查看概率，不保证本次掉落；已计入适用的角色等级、累计次数和所填掉率条件。固定奖励另行计算；未计财富额外战利品或幸运附魔。神器池为初始参考，已生成神器会改变分布。' if loot else ''),
                     'note':loot_note if loot else '此敌人没有常规自身物品掉落。任务奖励、已存容器、财富戒指和幸运附魔等额外机制按各自条件结算。'})
    abilities = []
    if name == 'gnollexile':
        abilities = [_metric('长矛最大攻击距离',2,'格','相邻时可攻击；非相邻时须八方向距离不超过2，且两步内路径不受实墙或中间角色阻挡，自身格可通行；不能穿墙或越过挡路角色'),
                     _metric('初始行为','被动游荡','','只看见玩家不会自动追击；这是生成规则，不能断言本局这只仍处于被动'),
                     _metric('负面状态解除被动','转为普通游荡','','被动行动发现自身有负面状态时，先离开被动，再按普通察敌规则行动；不等于立即保证发动攻击'),
                     _metric('已警觉时发现敌人','进入追击','','同次被动行动中目标可见且刚被警觉时；可生效的非腐化来源承伤处理可令未追击者警觉，是否追击仍取决于目标可见等条件'),
                     _metric('被动时受到吸引','保持被动','','吸引可以改变游荡目标，单凭吸引不会解除被动')]
    elif name == 'albino':
        abilities = [_metric('命中后施加流血概率',50,'%','先完成普通攻击效果处理，处理后的伤害必须大于0；零伤害不触发'),
                     _metric('传给流血状态的强度范围','2–3','强度参数','范围内随机抽取，非等概率；不是固定持续时间或直接扣血量'),
                     _metric('新流血首次强度范围','1–3','强度','流血状态再在传入值的1/2至全值之间抽取；已有更强流血不降低'),
                     _metric('新流血首跳基础伤害','1–3','HP','首次强度四舍五入后结算，后续每跳重新衰减；抗性等另计，不是总伤害')]
    elif name in ('slime','causticslime'):
        requested.add('damage')
        abilities = [_metric('所填输入经史莱姆压缩后',_slime_damage(p['damage']),'HP','所填伤害指进入该敌人承伤分支的整数；无飞升。压缩后才进入普通抗性、屏障等处理，不是保证扣血'),
                     _metric('伤害压缩起点',5,'HP','低于5点不压缩；5／7／10／14／19／25点输入分别变为5／6／7／8／9／10点')]
        if name == 'causticslime':
            abilities += [_metric('攻击命中后施加淤泥概率',50,'%','在普通攻击效果处理前尝试施加；此分支不额外要求最终伤害大于0'),
                          _metric('淤泥初始持续参数',20,'回合','淤泥按楼层分段造成伤害；水中可洗掉，抗性等另计，不是每回合20点伤害')]
    elif name == 'fetidrat':
        abilities = [_metric('攻击命中后施加淤泥概率','1/3','','普通攻击效果处理后尝试施加；抗性及免疫另计'),
                     _metric('淤泥初始持续参数',20,'回合','水中可洗掉，伤害另按楼层和状态行动结算'),
                     _metric('受攻击时播种恶臭气体体积',20,'体积','每次进入防御效果处理时在自身格播种；不要求攻击最终扣血，不是1/3概率或20点伤害'),
                     _metric('恶臭气体效果','延长麻痹','','气体更新时作用于当前所在格的非免疫生物；气体体积不能当作麻痹持续时间')]
    elif name in ('golem','quest.vault.vaultgolem'):
        abilities = [_metric('拉回目标后冷却',20,'次自身行动','每次自身行动开始减1；目标须可见、不能普通攻击、非不可移动且绕障路径可达，不是每20次角色操作保证发动'),
                     _metric('拉回目标行动耗时',1,'回合','从自身周围8格选择可通行空位；目标魔法免疫或无落点时也会消耗此行动并设置冷却'),
                     _metric('能正常追近时的拉回选择','1 / ⌊100÷距敌距离⌋','','只在距离至少1、目标可见且不能普通攻击时；追近失败后还有不经这次随机检定的拉回尝试，其他条件仍须满足')]
        if name == 'quest.vault.vaultgolem':
            abilities.append(_metric('自身传送','不使用','','宝库潜行行为替换游荡状态，不能进入普通魔像的自身传送准备；仍保留追击中的拉回目标能力'))
        else:
            abilities += [_metric('自身传送准备耗时',2,'回合','游荡且无法追近目标、非首领层、自身传送冷却结束时；不等于追击中每2回合传送'),
                          _metric('自身传送落点处理耗时',1,'回合','下一次自身行动处理；落点须无人且有大型生物空间，否则改选目标'),
                          _metric('自身成功传送后冷却',30,'次自身行动','每次自身行动开始减1；只有成功传送才设置30，目标不可用时不设此冷却')]
    elif name == 'guard':
        abilities = [_metric('正常铁链最大敌人距离',4,'格','八方向距离小于5；目标可见、不能普通攻击、未魅惑守卫且非不可移动，投射路径和落点仍须可用'),
                     _metric('每只守卫成功使用铁链次数',1,'次','只在找到落点并实际进入拉拽分支时标记已用；失败尝试不消耗该次数'),
                     _metric('拉拽后残废基础持续',4,'回合','落点是铁链路径上最靠近守卫的可用格；不是残废状态通用的10回合，抗性等另计')]
    elif name in ('necromancer','spectralnecromancer'):
        spectral = name == 'spectralnecromancer'
        abilities = [_metric('准备召唤的最大敌人距离',4,'格','敌人可见且有视野内可通行的敌人邻格；绕障寻路可达，不能穿过实墙'),
                     _metric('首次召唤准备耗时',1,'回合','准备之后在后续自身行动尝试召唤；落点被占、无法推出占位者时会延后'),
                     _metric('后续召唤准备耗时',2,'回合','首次召唤完成后；不是两回合必定出现一个生物'),
                     _metric('占位且无法推开时的基础伤害','2–10','HP','召唤落点上的敌对阵营占位者；对同阵营占位者不造成这段伤害，每次阻塞再等待1回合')]
        if spectral:
            abilities += [_metric('召唤怨灵的固定等效层数',4,'层','直接指定普通怨灵种类；不是按当前楼层缩放，也不进行默认稀有变种替换'),
                          _metric('该召唤怨灵的基础数值','生命1 · 普攻3–6 · 命中14 · 闪避70','','与本层通用怨灵参考不同，抗性和临时状态仍另计'),
                          _metric('召唤物数量','可同时多个','','招魂法师不建立普通死灵法师的唯一骷髅连接；死亡时清除所记录且仍同阵营的怨灵')]
        else:
            abilities += [_metric('普通召唤骷髅初始生命',20,'HP','初始最大生命25；只维持自己的同阵营骷髅连接，不能套用普通骷髅经验或掉落'),
                          _metric('骷髅未满血时每次恢复','最大生命÷5向下取整','HP','正常最大生命25时恢复5，且不超过缺失生命；支援行动默认耗时1回合'),
                          _metric('骷髅满血时肾上腺素基础持续',3,'回合','只有该骷髅当前没有肾上腺素状态时施加；不是状态通用的10回合持续'),
                          _metric('骷髅回收传送条件','不在视野或绕路过长','','骷髅不能攻击目标，且无路径，或路径长度同时大于敌人距离的2倍且至少4格时，会尝试移到目标邻格；不保证有可用落点')]
    elif name in ('thief','bandit'):
        abilities = [_metric('偷窃尝试','命中角色后','','须为敌对阵营且未持有被盗物品；从背包顶层均匀抽1个条目，唯一物品或等级至少+1时失败，不重抽。嵌套袋内物品不在此随机列表'),
                     _metric('一次成功偷窃数量',1,'件','堆叠物品取1件；未堆叠物品整件取走。蜂蜜罐等物品还按自身特殊规则处理'),
                     _metric('逃跑中进入防御效果处理撒金币',1,'金币','每次在自己所在格掉落；不要求此次攻击最终造成正伤害，和击杀普通掉落分别结算'),
                     _metric('丢弃被盗物品的逃脱最小距离',6,'格','进入逃脱分支时，自身还须在玩家视野外；之后尝试转移位置并清空被盗物品，不保证一定成功转移')]
        if name == 'bandit':
            abilities += [_metric('成功偷窃后失明基础持续',5,'回合','普通失明10回合的一半；仅偷窃成功后，已有状态及抗性另计'),
                          _metric('成功偷窃后残废基础持续',5,'回合','普通残废10回合的一半；仅偷窃成功后'),
                          _metric('成功偷窃后中毒剩余参数','5–6','回合','等概率整数；已有更长中毒不缩短，不是5–6点总伤害'),
                          _metric('新中毒首次基础伤害','2–3','HP','仅新中毒，按剩余参数÷3向下取整再加1；已有状态、抗性和提前解除另计')]
    elif name == 'demonspawner':
        requested.update(('depth','damage'))
        damage=p['damage']
        reduced=damage if damage<20 else 19+math.floor(math.sqrt(8*(damage-19)+1)-1)//2
        interval=float32(60-min(20,(depth-21)*6.67)) if depth>21 else 60
        abilities = [_metric('所填输入经血巢压缩后',reduced,'HP','20点起先压缩，再进入普通抗性、屏障等处理；不是保证扣血或固定20点上限'),
                     _metric('该输入推进召唤冷却',reduced,'计数','使用压缩后、进入普通承伤处理前的数值；不以最终实际扣血倒推'),
                     _metric('成功召唤后基础添加冷却',interval,'时间计数',f'所填主地牢层数{depth}；第21／22／23／24层分别添加60／53.33／46.66／40。保留原冷却余量，每次自身行动先减1，不是固定角色操作间隔'),
                     _metric('初始召唤冷却',0,'计数','首次自身行动已有可用邻格时即可尝试召唤，不能假定要先等完整60回合'),
                     _metric('堵塞时保留的最低冷却',-20,'计数','冷却到期但周围8格没有可通行空位时不召唤；下一次到期检查把低于−20的余量截到−20，不能堆存多个同时召唤'),
                     _metric('新恶魔加入行动队列的延迟',1,'回合','每次成功在周围8格的随机可用格生成1只跳跃恶魔，进入追击状态')]
    elif name == 'swarm':
        requested.update(('target_hp','damage'))
        splits=p['target_hp']>=p['damage']+2
        clone=(p['target_hp']-p['damage'])//2 if splits else 0
        abilities = [_metric('所填条件是否允许分裂','满足生命条件' if splits else '不满足生命条件','','进入防御效果处理时当前生命至少为伤害＋2，还须有上下左右可用空位；不是斜向8格，也不保证最终发生'),
                     _metric('若成功分裂，新个体初始生命',clone,'HP','按（当前生命−所填伤害）÷2向下取整；未满足生命条件时所列0表示不生成，不是零生命生成物'),
                     _metric('原个体分裂后、最终承伤前生命',p['target_hp']-clone,'HP','仅生命条件与落点均满足时减去新个体生命，之后才继续处理本次伤害；不是保证剩余生命'),
                     _metric('新个体开始行动延迟',1,'回合'),
                     _metric('新个体分裂代数',p['swarm_generation']+1,'代','正代数分裂体不提供经验，治疗药剂概率按各自分裂代数另算'),
                     _metric('继承中毒时重新设置参数',2,'回合','原个体有中毒才给新个体设置；燃烧重新点燃，其他可随复活保留状态按各自规则复制')]
    elif name == 'bat':
        abilities = [_metric('命中后的吸血恢复','max(0, min(攻击处理后的伤害−4, 缺失生命))','HP','使用普通攻击效果处理返回的伤害；目标护甲已影响此输入，不按基础伤害范围直接回血'),
                     _metric('正常基础攻击可提供的恢复额度','1–14','HP','基础伤害5–18且无减伤或其他修正时；生命已满则恢复0，实际恢复不超过缺失生命')]
    elif name == 'succubus':
        abilities = [_metric('无魅惑目标命中后施加魅惑概率','1/3','','只在目标当前没有任何魅惑状态时进入此分支；抗性及免疫另计'),
                     _metric('魅惑基础持续参数',5,'回合','10回合基础持续的一半；忽略本次命中对魅惑的首次缩短，其他攻击和状态另计'),
                     _metric('命中已魅惑目标的恢复额度','5＋攻击处理后的伤害','HP','目标存在任何魅惑状态即进入此分支，不要求魅惑来自这只魅魔；先填满魅魔缺失生命'),
                     _metric('恢复超额的屏障','max(已有屏障, 恢复额度−缺失生命)','HP','只有恢复额度超过缺失生命时设置；与已有屏障取较大值，不反复累加，屏障仍会自然衰减'),
                     _metric('闪现后冷却计数','4–6','次普通追近分支','等概率整数；部分找不到落点的闪现尝试也会设冷却。仅普通追近分支减1，不是每个角色回合减1'),
                     _metric('闪现的目标距离条件','超过2','格','目标在视野内、未扎根且冷却结束时；落点仍受投射路径、占位和地形限制')]
    elif name in ('rotlasher','rotheart'):
        abilities = [_metric('受到燃烧状态伤害时','直接摧毁','','来源须为燃烧状态；绕过正常死亡掉落。不能把所有火焰相关来源都当作此分支')]
        if name == 'rotlasher':
            abilities += [_metric('每次自身行动最多恢复',5,'HP','生命未满，且无当前敌人或敌人不相邻时；恢复不超过缺失生命'),
                          _metric('攻击命中后残废基础持续',2,'回合','状态抗性等另计；不是残废状态通用的10回合基础持续')]
        else:
            abilities += [_metric('受攻击时播种毒气体积','5＋3×周围非实心格数','体积','防御效果处理时在自身格播种，周围8格计数0–8，因此体积5–29；不是伤害或持续回合'),
                          _metric('被摧毁时的腐莓触手','本层全部死亡','','正常死亡与燃烧直接摧毁均会触发；触手各自的正常死亡处理仍分别结算')]
    elif name in ('monk','senior'):
        senior = name == 'senior'
        abilities = [_metric('专注时的闪避','无限闪避','','须未麻痹且未睡眠；格挡需要命中检定的攻击，不免疫气体等其他伤害'),
                     _metric('消耗专注后的冷却','6–7','时间计数','范围内随机抽取，非等概率；实际消耗行动时间会扣除冷却，不是固定6–7次角色行动'),
                     _metric('每次正常移动额外扣除冷却',2.33 if senior else .67,'时间计数','额外扣除部分；再计移动本身的耗时。无其他速度状态的一步通常合计约'+('3.33' if senior else '1.67')),
                     _metric('重新获得专注的条件','追击中且冷却结束','','自身行动后检查；未获得专注前仍使用普通闪避')]
    elif name == 'ripperdemon':
        abilities = [_metric('跳跃准备的最小敌人距离',3,'格','目标可见、未扎根且跳跃冷却结束；正常攻击不可达且弹道满足条件时才准备跳跃'),
                     _metric('跳跃准备耗时','0.5–1.5','回合','正常攻击耗时0.5；把目标当前行动冷却向上取整后限制在0.5–1.5之间，不是等概率随机时间'),
                     _metric('跳跃重新设置的冷却','2–4','次自身行动','范围内随机整数，非等概率；自身行动且未麻痹时减1，部分跳跃取消也已设置冷却'),
                     _metric('命中时传给流血的强度','11.25–18.75','强度参数','普通伤害掷骰15–25再乘0.75；跳跃使用无限命中检定，目标无限闪避仍可挡下'),
                     _metric('新流血首次强度范围','5.625–18.75','强度','流血状态再抽取传入值的1/2至全值；已有更强流血不降低'),
                     _metric('新流血首跳基础伤害','6–19','HP','首次强度四舍五入后结算，不扣普通护甲；抗性等另计，后续每跳衰减，不能作为固定总伤害')]
    elif name in ('ghoul','quest.vault.vaultghoul'):
        abilities = [_metric('第n次倒地的复活等待','5×n','次生命连接状态行动','首次5、第二次10；生命连接有可用宿主时计数，宿主参与决斗时暂停，落点被占且无可用邻格会延后'),
                     _metric('正常复活生命',5,'HP','普通最大生命45，按最大生命÷10四舍五入；最大生命改变时另算'),
                     _metric('可继续连接的宿主','同阵营其他食尸鬼','','宿主能看见倒地点，或距倒地点小于4格；不局限原配对。宿主消失可转移，找不到则真正死亡'),
                     _metric('倒地不能复活的情况','坠落或坑洞等','','掉入深渊／所在格为坑洞不进入普通连接；连接期间倒地点变为坑洞也会真正死亡')]
    elif name == 'crystalwisp':
        abilities = [_metric('远程光束基础伤害','5–10','HP','目标非相邻且魔法弹道可达时；不扣普通护甲，抗性等另计，相邻或弹道受阻时使用普通攻击'),
                     _metric('远程光束耗时',1,'回合'),
                     _metric('魔法命中掷骰倍率',2,'倍','基础命中18的随机掷骰乘2；不是最终命中概率'),
                     _metric('矿洞水晶地形','可穿越','','水晶幽魂是飞行生物，并把矿洞水晶加入可通行地形')]
    elif name == 'gnollguard':
        requested.add('damage')
        abilities = [_metric('非相邻目标的长矛基础伤害','16–22','HP','攻击距离最多2格，双方方向投射弹道均须可达；普通护甲等仍生效'),
                     _metric('相邻目标基础伤害','6–12','HP','不要将近战范围用于隔格长矛攻击'),
                     _metric('连接爆破手存活时所填伤害',p['damage']//4,'HP','所填整数伤害进入守卫承伤分支后先除4向下取整，再由普通抗性等结算；连接解除后不除4')]
    elif name == 'phantompiranha':
        requested.add('damage')
        abilities = [_metric('非相邻或无法定位来源的所填伤害',math.floor(float32(p['damage']/float32(2))+.5),'HP','生物来源按其位置；法杖或牧师法术按玩家位置。先除2并四舍五入，再结算普通抗性等，不是保证扣血'),
                     _metric('相邻已定位来源的所填伤害',p['damage'],'HP','法杖或牧师法术按玩家位置判断；八方向相邻时不走减半分支，普通抗性等仍另计'),
                     _metric('受伤后的瞬移条件','存活且非腐化来源','','非相邻的已定位来源优先选其周围空水格；无落点或无法定位时尝试远离。能否成功取决于可用水格')]
    elif name == 'goo':
        result.insert(2,{'title':'粘咕生命阶段与蓄力攻击','columns':['生命阶段','普通基础伤害HP','蓄力基础伤害HP','普通命中值','蓄力命中值','基础闪避值'],
            'rows':[['高于最大生命的50%','1–8','3–24','10','20','8'],
                    ['不超过最大生命的50%','1–12','3–36','15','30','12']],
            'note':'此生命阶段的伤害、命中与闪避分支也适用于绝命头目；蓄力只是基础伤害乘3、命中值乘2，目标护甲和最终命中检定仍生效。半血判定包括恰好50%；水中恢复可能重新跨回高血量阶段。'})
        abilities = [_metric('高血量选择开始蓄力概率',20,'%','可发动攻击且尚未蓄力时的选择概率；不是每回合固定概率'),
                     _metric('半血选择开始蓄力概率',50,'%','生命不超过最大生命的50%，可发动攻击且尚未蓄力时'),
                     _metric('正常蓄力准备',2,'次自身攻击行动','开始和继续准备各耗默认1回合，之后发射攻击再耗默认1回合；其他状态修正另计'),
                     _metric('蓄力攻击最大距离',2,'格','需双方方向的攻击弹道都可达；实际墙角与光路以游戏为准'),
                     _metric('攻击命中后施加淤泥概率','1/3','','目标抗性及免疫另计'),
                     _metric('正常水中每次行动恢复',1,'HP','没有飞行、当前格是水且生命未满时；不是每个玩家行动必定恢复')]
        if stronger:
            abilities = [metric for metric in abilities if metric['label'] not in ('正常蓄力准备','正常水中每次行动恢复')]
            abilities += [_metric('绝命头目蓄力准备',1,'次自身攻击行动','直接进入完成蓄力；准备耗时为目标当前行动冷却向上取整，并限制在自身攻击耗时的1至3倍；不能固定当成1回合'),
                          _metric('绝命头目连续水中恢复','1→2→3','HP／次自身行动','非飞行、在水且生命未满的连续恢复行动逐次增加，最多3；未满足恢复条件的行动将下次恢复重置为1')]
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
            abilities += [_metric('伪装首击额外伤害倍率',1,'倍','水晶宝箱怪没有普通宝箱怪的首击伤害加成；仅尚属中立且命中玩家时尝试偷取'),
                          _metric('成功逃脱的后果','自身与携带物一同消失','','普通逃跑行为触发逃脱判断后，须自身在玩家视野外，且距玩家至少6格；未满足则转为游荡。不是每回合只要离开视野且达到距离就自动消失'),
                          _metric('停止伪装时极速基础持续','2／1','回合','停止伪装时仍属中立为2，否则为1；随后进入逃跑。受攻击而先转为敌对时走1回合分支，状态抗性及实际行动顺序另计'),
                          _metric('偷取对象','未装备、非唯一、等级小于+1','','从背包顶层条目随机抽取，嵌套袋内物品不在此列表；丢失背包状态下抽不到物品。已装备、唯一或等级至少+1的物品不能偷取'),
                          _metric('每次偷取最多随机抽取',11,'次','初抽1次，遇空结果、唯一物品或等级至少+1时最多重抽10次；抽到合格项即停止。不是保证成功，也没有固定成功率'),
                          _metric('一次成功偷取数量',1,'件','堆叠取1件，非堆叠整件取走；蜂蜜罐按自身破碎规则处理，新增携带物不重新执行生成奖励质量处理'),
                          _metric('其他命中后的目标移位','随机移到自身周围空位','','非中立状态命中玩家，或命中其他生物时，从宝箱怪周围8格的可通行且无人空位随机选落点；移动的是受击目标，无空位则不移动。敌对状态随后转为逃跑')]
    elif name == 'eye':
        requested.add('damage')
        abilities = [_metric('死亡凝视基础伤害','30–50','HP','光路上的每个目标分别进行魔法命中检定；不扣普通护甲，抗性等另计'),
                     _metric('死亡凝视蓄力耗时',2,'回合','默认攻击耗时1回合的两倍；肾上腺素等状态另计'),
                     _metric('死亡凝视发射耗时',1,'回合','默认攻击耗时；蓄力后目标离开视野仍可能向先前位置发射'),
                     _metric('发射后冷却计数','4–6','次自身行动','每次自身行动开始减1；不是固定的角色回合数'),
                     _metric('魔法命中掷骰倍率',2,'倍','基础命中30的随机掷骰乘2，再与目标闪避掷骰比较；不是必中或最终命中概率'),
                     _metric('蓄力时所填伤害缩减后',p['damage']//4,'HP','进入邪眼承伤分支的伤害先除4并向下取整，之后仍受抗性等处理影响')]
    elif name in ('dm100','quest.vault.vaultdm100'):
        abilities = [_metric('远程电击基础伤害','3–10','HP','目标非相邻，且魔法弹道可达目标时；相邻或弹道被阻挡时使用普通攻击'),
                     _metric('远程电击耗时',1,'回合','不扣普通护甲，抗性等另计'),
                     _metric('魔法命中掷骰倍率',2,'倍',f'基础命中{stats["attackSkill"]}的随机掷骰乘2，再与目标闪避掷骰比较；不是必中或最终命中概率')]
    elif name in ('dm200','quest.vault.vaultdm200'):
        abilities=[_metric('排气行动耗时',1,'回合','敌人可见、不能普通攻击，且通过距离随机检定或追近失败后尝试；冷却与绕障可排气路径检查仍须通过'),
                   _metric('排气后冷却计数',30,'次自身行动','每次自身行动开始减1；初始0，不是固定角色回合数'),
                   _metric('排气选择检定','1 / ⌊100÷距敌距离⌋','','仅距离至少1且仍不能普通攻击时；追近失败后另有不经此随机检定的尝试，路径与冷却仍需满足'),
                   _metric('弹道路径每格播种毒气体积',20,'体积','沿排气弹道计算的各格；体积不是伤害或固定持续时间'),
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
                   _metric('连击重置',0,'次','尝试追近或拉开距离时，不要求最终实际移动成功')]
    elif name == 'warlock':
        abilities = [_metric('远程暗影弹基础伤害','12–18','HP','目标非相邻且魔法弹道可达时；不扣普通护甲，抗性等另计'),
                     _metric('远程暗影弹耗时',1,'回合'),
                     _metric('魔法命中掷骰倍率',2,'倍','命中随机掷骰乘2；不是最终命中概率'),
                     _metric('命中角色后施加降级概率',50,'%','只对角色；目标抗性和免疫另计'),
                     _metric('降级基础持续',30,'回合','已有更长状态不缩短；抗性及其他状态修正另计')]
    elif name in ('skeleton','necromancer$necroskeleton','quest.vault.vaultskeleton'):
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
                     _metric('新中毒基础持续','7–8','回合','已有中毒取更长持续时间；不是7–8点总伤害，解毒及抗性另计'),
                     _metric('成功吐网后冷却',10,'次追击或逃跑行动','初始0；仅追击或逃跑状态每次自身行动开始减1。中毒触发时设为0；不是固定玩家回合数，也不保证冷却结束必定吐网'),
                     _metric('吐网预测覆盖','前进方向邻格及其两侧，共至多3格','','目标可见、已记录上次位置且冷却结束时；移动目标按前次至当前位置外推，静止目标朝蜘蛛方向。蜘蛛未处于逃跑状态且静止目标可近战时不吐网；实墙、落点可通行条件仍须满足'),
                     _metric('每格蛛网播种体积',20,'体积','只播种可通行格；蛛网自身每次更新减少1体积，体积不是扎根时长或HP伤害。没有固定直接伤害'),
                     _metric('触网扎根基础延长参数',5,'回合','踩入蛛网并触发地形处理时；飞行目标不能附着扎根，状态免疫与抗性另计，已有更长扎根不缩短'),
                     _metric('结束中毒逃跑的条件','可见目标已无中毒且无恐惧／畏惧','','此逃跑行动切回追击；不是中毒触发时立即保证移动，也不能按当前中毒时长保证固定逃跑次数')]
    elif name == 'crystalguardian':
        abilities = [_metric('正常零生命处理','生命设为1并倒地恢复','','isAlive检查发现生命不大于0时；清除除末日和残废外的状态。不能按100点初始生命推断可通过普通扣血击杀'),
                     _metric('倒地每次自身行动恢复',5,'HP','恢复不超过最大生命，普通最大生命100；该行动耗时1回合，达到满血才结束恢复。继续攻击可延缓起身，不保证固定玩家回合数'),
                     _metric('恢复期间防御效果处理','生命至少保留1','HP','进入普通攻击防御效果时先按传入伤害扣生命并设最低1，再阻止正常护甲承伤；不把该输入当作最终护甲后伤害'),
                     _metric('恢复期间基础闪避',0,'点','此时不能被伏击；部分生物来源仍被无敌规则拒绝，角色和水晶尖塔来源是例外'),
                     _metric('狭窄位置正常移动速度倍率',0.25,'倍','按当前格是否有大型生物空间判断；无其他速度修正时从基础1降到1/4，不是所有位置固定耗时4回合'),
                     _metric('踩碎矿洞水晶额外移动耗时',1,'回合','无其他速度修正；按狭窄空间减速之前的速度另算，水晶被移除。这是移动原耗时之外的附加值')]
    elif name == 'crystalspire':
        abilities = [_metric('开始主动攻击所需镐子交互',3,'次','玩家携带镐子完成交互才计数；第三次后冷却设为1，仍须玩家存活且在尖塔视野内才准备新攻击。已警告的波次先于该检查结算'),
                     _metric('尖刺单次基础伤害','6–15','HP','每次已警告波次作用于被覆盖格中的角色；水晶幽灵和尖塔自身排除，不进行普通攻击命中检定，抗性等另计'),
                     _metric('尖刺对水晶守卫的基础伤害','18–27','HP','在6–15基础上加12，并延长残废基础参数30回合；可用于延缓守卫追击，不能用玩家6–15范围代替'),
                     _metric('尖刺对守卫残废基础延长参数',30,'回合','仅水晶守卫；状态自身的抗性与已有时长另计，不是对玩家同样施加30回合'),
                     _metric('每次选择菱形／直线攻击概率','各50%','','菱形以保存的玩家格为中心按四邻扩张；直线沿瞄准线在实墙前结束，后续波次继续扩张，不跟随之后移动的玩家'),
                     _metric('波次数：生命200–300／100–199／1–99','1／2／3','波','普通最大生命300；严格低于200才增加第二波、严格低于100才增加第三波。后续波次包含先前覆盖格，不能把每波当互不重叠范围'),
                     _metric('新攻击警告准备耗时','1–3','回合','玩家剩余行动耗时向上取整并限制在1至3；之后每次尖塔行动先结算一波，未结算波次也会给出警告'),
                     _metric('准备新攻击后添加冷却',15,'浮点计数','保留原冷却余量；仅已激活且玩家在尖塔视野内、当前冷却大于0的分支每次自身行动减1，不保证每15次玩家操作攻击'),
                     _metric('镐子交互推进冷却','该次镐子伤害÷10','浮点计数','交互伤害由镐子等级与强化方向决定，不合并玩家力量、其他装备；第三次交互最后会把冷却重设为1'),
                     _metric('尖刺位移','尝试移至1个相邻格','','有非实心空位且目标仍存活时；守卫远离玩家，其他非不可移动目标远离尖塔。没有合法落点则不移动，不保证每次击退')]
    elif name in ('gnollsapper','gnollgeomancer'):
        geomancer=name=='gnollgeomancer'
        abilities = [_metric('投石／落石每次基础伤害','6–12','HP','被实际覆盖的角色分别结算；投石击中弹道首个碰撞角色，地卜师不受投石伤害。不是1–6近战，也不进行普通攻击命中检定，抗性等另计'),
                     _metric('存活目标麻痹基础延长参数','3；豺狼守卫10','回合','投石和落石伤害后目标仍存活时；不区分敌友，状态抗性与已有时长另计，不保证麻痹对应次数的玩家操作'),
                     _metric('投石击退','尝试沿弹道击退1格','','同批投石不重复击退同一角色；扎根、不可移动、占位、大型生物空间等可能阻止移动。此调用不增加碰撞伤害，不能保证击退'),
                     _metric('投石／落石准备耗时','1–3','回合','当前目标剩余行动耗时向上取整后限制在1至3；预警保存位置，投石准备后下一次自身行动结算并消耗1回合，即使石块已被移除'),
                     _metric('初始／施放后能力冷却','3–5' if geomancer else '4–6','整数计数','目标可见的追击分支以后缀递减检查旧值不大于0；范围内非等概率。不是固定玩家回合数，施放条件和可用石块仍需满足'),
                     _metric('承伤推进能力冷却','向零取整（当前冷却−输入伤害÷10）','','先普通承伤，之后使用本次传入整数伤害更新整数冷却；浮点减法后整体转整数，不是先取整商或按最终HP损失计算'),
                     _metric('投石／落石选择','可用时条件选择','','有可投石时通常各50%；上次为落石，或目标邻近木障／入口时优先投石；没有可投石仍可落石，不保证严格交替'),
                     _metric('落石覆盖格选择','距中心d格时为1／（1＋⌊d÷2⌋）','','以保存的目标格为中心，方形范围内逐格抽取；排除实心格、随机安全邻格、地卜师以及木障／入口周边，地卜师发动还排除爆破手。不是范围内所有格必落石')]
        if geomancer:
            abilities += [_metric('普通近战攻击','不使用普通攻击','','追击行为只准备能力或等待；类中的3–6基础方法不是正常实际近战伤害'),
                          _metric('生命100–150／50–99／1–49最多投石数','1／2／3','块','普通最大生命150；满血归入第一段。需要视野内未被其他施法预占、弹道可到目标的石块，实际数量可减少'),
                          _metric('生命100–150／50–99／1–49落石范围参数','2／4／6','格','以保存的目标格为中心，各方向扩展该范围的方形候选区；不是落石数量或保证覆盖整个区域'),
                          _metric('跨生命阶段时岩石护甲',25,'护盾','跨过100或50生命段后设置；仍有连接爆破手时另有无敌，不把岩石护甲当25点普通减伤'),
                          _metric('跨段伤害生命保护','最多跨入下一个生命段','','从100–150段受击后生命不超过50时设回51；从50–99段受击后生命不超过0时设回1。伤害前未进入末段不能正常死亡；无额外存活状态时，已在末段才可正常击杀'),
                          _metric('开场／阶段冲刺使用的爆破手出生位置','最多3个','位置','开场第三次镐子交互及跨段时尝试向未用位置开岩冲刺；路径先截至12步，落点被占或有陷阱可改邻格，因此不是保证恰好移动12格'),
                          _metric('成功阶段冲刺耗时／重设冷却','1／1','回合／整数计数','有未用出生位置且进入冲刺时；没有目标位置直接返回。可连接仍存活爆破手，因此击破岩石护甲不保证解除全部无敌'),
                          _metric('岩石护甲下额外推进冷却',1,'整数计数','可见目标距离大于2或有连接爆破手，且目标未麻痹时；每次该追击行动先额外减1，再执行通常的后缀递减')]
        else:
            abilities += [_metric('落石范围参数',2,'格','以保存目标格为中心的5×5候选方形，按逐格条件和概率选中；不是保证25格全部受击'),
                          _metric('可见目标追击','原地等待或相邻近战','','正常不会向可见的远处目标追近；相邻且可攻击时仍可使用1–6普通近战，不能把地卜师不普攻规则套用到爆破手')]

    elif name in ('scorpio','acidic'):
        abilities = [_metric('远程攻击基础伤害','30–40','HP','仅攻击非相邻、投射弹道可达的目标；不是魔法命中，目标护甲仍生效'),
                     _metric('攻击命中后施加残废概率',50,'%','目标抗性和免疫另计'),
                     _metric('残废基础持续',10,'回合','已有更长状态不缩短；目标抗性和其他状态修正另计')]
        if name=='acidic':
            abilities += [_metric('攻击命中后施加淤泥概率',100,'%','先尝试施加淤泥，再处理继承的普通攻击效果和50%残废；此分支不额外要求最终伤害大于0，目标免疫等另计'),
                          _metric('相邻攻击者触发淤泥概率',100,'%','进入防御效果处理且攻击者八方向相邻时，施加给攻击者；不要求酸液蝎最终扣血')]
    elif name in ('shaman','quest.vault.vaultshaman'):
        names=[values.catalog.messages['actors.buffs.'+buff+'.name'] for buff in ('weakness','vulnerable','hex')]
        abilities = [_metric('远程土弹伤害','6–15','HP','目标非相邻且魔法弹道可达时；不扣普通护甲，抗性等另计，相邻或弹道受阻时使用普通攻击'),
                     _metric('远程土弹耗时',1,'回合'),
                     _metric('魔法命中掷骰倍率',2,'倍',f'基础命中{stats["attackSkill"]}的随机掷骰乘2，再与目标闪避掷骰比较；不是必中或最终命中概率'),
                     _metric('命中后附加负面状态概率',50,'%','仅远程魔法命中后、土弹伤害结算前尝试；目标抗性和免疫另计'+
                             (f'；红色{names[0]}、蓝色{names[1]}、紫色{names[2]}' if name=='shaman' else '；按此只宝库萨满生成时固定的类型施加'))]
        if name == 'quest.vault.vaultshaman':
            abilities += [_metric(f'生成时选择{buff}类型概率',chance,'',
                                  f'生成时均匀抽取0–4并固定类型；远程命中且50%附加状态判定触发后施加{buff}，每次攻击不重抽类型；未读取本局类型')
                          for buff,chance in zip(names,('2/5','2/5','1/5'))]
    elif name == 'quest.vault.vaultbosselemental':
        abilities = [_metric('形态分段生命',120,'HP','普通最大生命600、无死亡印记等额外存活状态；当前生命向上取整分段，降到当前段下界或更低时，仍存活才换形态并耗时1回合'),
                     _metric('存活时单次跨段后的生命下限','当前段下界再减120','HP','在实际承伤之后才将生命抬至此下限；例如600降到100会抬至360。直接致死不进入此保护，不是保证防秒杀'),
                     _metric('新生成时三种初始形态概率','各1/3','','火焰／冰霜／电光；未读取本局当前形态'),
                     _metric('新生成连续战斗的各形态初始可用次数',2,'次','初始形态也扣1次；之后按剩余次数加权抽取并排除当前形态，不是每次各1/3。此上限仅适用于未读档的连续战斗；形态次数数组未保存，读档不保证沿用该上限'),
                     _metric('初始特殊／环境冷却','6–10／10–15','整数计数','新生成时抽取，初始为电光也不缩放；范围内非等概率。无待发技能分支时每次自身行动先减1，包括麻痹及非追击行动，不是固定玩家回合数'),
                     _metric('特殊施放后重设冷却：火焰／冰霜','6–10','整数计数','完成施放后重设；追击、未麻痹且有敌人时，先减1后检查不大于0才准备，特殊技能优先于环境技能'),
                     _metric('特殊施放后重设冷却：电光','4–6','整数计数','从6–10抽取后乘0.67并向零取整；不是初始冷却或4–6回合保证攻击一次'),
                     _metric('环境施放后重设冷却：火焰／冰霜','10–15','整数计数','追击、未麻痹且有敌人，并且特殊技能本次没有优先准备时检查不大于0'),
                     _metric('环境施放后重设冷却：电光','6–10','整数计数','从10–15抽取后乘0.67并向零取整，保留此整数截断结果'),
                     _metric('实际扣血推进特殊／环境冷却','向零取整（当前冷却−实际扣血÷12／24）','','实际扣血取普通承伤前后生命之差，在跨段抬生命之前计算；仅差值大于0时。浮点减法后整体转为整数，不是先取整扣血÷12／24；不是所填输入伤害'),
                     _metric('特殊技能准备耗时','1–3','回合','正常攻击耗时1：将玩家剩余行动耗时向上取整，再限制在1至3。保存瞄准位置；待发技能须未麻痹且仍有敌人才施放，不要求继续处于追击状态'),
                     _metric('特殊技能施放耗时',1,'回合','待发技能分支先处理且不再递减两类冷却；范围效果与各自状态后续行动分别结算，不进行普通攻击命中检定'),
                     _metric('环境技能发动耗时',1,'回合','随后环境状态自行行动；不能把持续环境效果与首领自身行动视为同一次攻击'),
                     _metric('换形态时环境冷却','当前整数冷却÷2，向零取整','','若有待发特殊技能则取消原瞄准，并将特殊冷却设为0；没有待发技能时保留特殊冷却'),
                     _metric('各形态普通近战伤害：冰霜／其余','15–20／20–25','HP','基础数值表的普通伤害须结合形态；不是火球、冰锥或闪电的特殊伤害'),
                     _metric('火焰火球范围','保存落点及周围8格','','排除实心格；按敌人最近移动方向预判前方一格，否则选敌人随机邻格，火墙可能再调整落点。落点不跟随敌人之后移动'),
                     _metric('火焰火球每格播种火焰体积',2,'体积','首领火球不直接调用伤害；不能套用普通／新生火元素的近战范围、火焰体积或总伤害。除宝库元素首领外的范围内角色尝试点燃'),
                     _metric('火焰火球点燃基础持续参数',8,'回合','已有更长燃烧不缩短；燃烧状态后续逐次扣血，免疫、水格等另计，不是8点直接伤害'),
                     _metric('燃烧单次基础伤害','1–（3＋⌊当前等效层数÷4⌋）','HP','火球或火墙点燃后，燃烧状态每次行动随机结算，非等概率；抗性等另计，不能乘持续参数当作保证总量'),
                     _metric('火墙每次扫描厚度／前进距离','2／1','格','每条火墙状态行动扫描当前位置及前方1格，再前进1格；墙线有单格缺口，实心格和地图外不作用'),
                     _metric('新火墙最多扫描次数',12,'次状态行动','初值11在每次扫描后才执行后缀递减并检查不大于0，因此包括0那次；行动间隔1回合，不保证命中12次或固定总伤害'),
                     _metric('火墙点燃基础持续参数',5,'回合','扫描范围内除宝库元素首领外的角色尝试点燃；已有更长燃烧不缩短，不是5点直接伤害'),
                     _metric('火墙缺口横向距离：高于半血／不高于半血','1–3／4–6','格','相对于选择墙向时玩家的横向坐标，普通半血300；不是与首领距离或安全区半径'),
                     _metric('冰霜冰锥最大射程／锥角','10／50','格／度','以保存目标格确定方向，实墙阻挡；伤害由后续冰锥状态行动推进，不是施放即覆盖所有格'),
                     _metric('冰锥初始推进半径／每次增长','2／2','格','按距离自身起点的真实距离判断；作用格在半径超过自身距离至少4格时才从集合移除，不能当作一次即逝光束'),
                     _metric('冰锥单次基础伤害','10–15','HP','范围内除宝库元素首领外、没有冰霜保护标记的角色；不进行普通命中检定，伤害来源为冻结，抗性等另计'),
                     _metric('冰锥／冰霜涡旋冻结基础持续参数',5,'回合','冰锥先造成伤害再尝试冻结；涡旋只尝试冻结，不直接扣血。状态免疫和抗性另计，不是保证5次玩家行动'),
                     _metric('涡旋方向组数：高于半血／不高于半血','2／4','组','以发动时保存的玩家位置为中心，首次状态行动按首领半血300选择相对斜向带／全部四组；逐次向中心收缩后向外推进，实墙和场地决定实际格数，不保证固定命中次数'),
                     _metric('冰霜重复命中保护','有冰霜保护标记时跳过伤害及冻结','','冰锥与涡旋共用；标记在冻结仍存在时等待，冻结结束后再移除，以给目标行动机会。不是全局冻结免疫或固定无敌回合'),
                     _metric('电光闪电束基础伤害','20–30','HP','保存目标格方向的光路及目标四个交错邻格，实墙阻挡光路；除宝库元素首领外、没有电击保护标记的角色，不进行普通命中检定，来源为电场'),
                     _metric('追踪闪电基础伤害','10–15','HP','每条环境闪电的当前／中点／终点检查有无角色，除宝库元素首领外且无电击保护标记才作用；实心地形阻断后终止，来源为电场'),
                     _metric('闪电束／追踪闪电麻痹延长基础参数',1,'回合','先造成电场伤害，再延长麻痹并加电击保护标记；已有更长麻痹不缩短，状态抗性及免疫另计'),
                     _metric('追踪闪电数量：高于半血／不高于半血','2／4','条','发动时按首领生命与半血300比较，从场地两侧或四侧生成；不是每次命中玩家的次数'),
                     _metric('追踪闪电每次前进距离',2,'地图坐标距离','每次状态行动间隔1回合；坐标随后吸附到半格并取单元格，不保证恰好跨2个格子。首次行动只准备路径，后续才检查伤害'),
                     _metric('追踪闪电转向最大幅度抽取范围','22.5–30','度','每次后续状态行动抽取转向上限，实际转角还受目标方向差限制，不保证每次转这么多'),
                     _metric('电击重复命中保护','有电击保护标记时跳过伤害及麻痹','','闪电束与追踪闪电共用；标记在麻痹仍存在时等待，麻痹结束后再移除，以给目标行动机会。不是所有电场来源免疫'),
                     _metric('电光形态非投掷武器攻击反击','5–10','HP','玩家攻击进入首领防御效果处理，且当前攻击武器不是投掷武器时；不要求首领最终扣血，也不额外检查相邻。反击来源为电击附魔，不能套用闪电束20–30')]
    elif name in ('elemental$fireelemental','elemental$frostelemental','elemental$shockelemental',
                  'elemental$chaoselemental','elemental$newbornfireelemental',
                  'quest.vault.vaultelemental$fire','quest.vault.vaultelemental$frost','quest.vault.vaultelemental$shock'):
        newborn=name=='elemental$newbornfireelemental'
        abilities=[_metric('远程攻击后重设冷却参数','3–5','自身追击行动',
                           '初始也从此范围抽取；只有追击状态每次行动先减1，普通远程可攻击判定要求小于0，不是固定玩家回合数'),
                   _metric('远程施放行动耗时',1,'回合','冷却外，普通元素还要求非相邻且魔法弹道到达目标；蓄力火球另有准备阶段')]
        if newborn:
            abilities += [_metric('普通敌对形态近战点燃概率',0,'%','不继承普通火元素的50%近战点燃；盟友召唤形态另计'),
                          _metric('火球准备耗时范围','1–3','回合','正常攻击耗时1时：将玩家剩余行动耗时向上取整后限制在1至3之间；瞄准目标邻格中可达的一格，下一次自身追击行动向保存落点施放'),
                          _metric('火球影响范围','落点及八个邻格','','实墙格排除；落点不跟随玩家后续移动，离开追击状态取消准备'),
                          _metric('火球播种火焰体积：干燥／水格','8／2','体积','不是直接扣血量或固定燃烧总伤害；范围内除自身外的角色均尝试点燃，不做普通命中检定'),
                          _metric('火球点燃基础持续参数',8,'回合','已有更长燃烧不缩短；目标免疫等另计，火焰地形也会继续变化')]
        elif name.endswith(('$fireelemental','$fire')):
            abilities += [_metric('近战命中后点燃概率',50,'%','目标所在格无水时；普通攻击已进入命中效果处理，不要求最终扣血大于0，免疫等另计'),
                          _metric('近战点燃基础持续参数',8,'回合','已有更长燃烧不缩短，不是8点伤害或保证8次伤害'),
                          _metric('远程命中后点燃概率',100,'%','先进行魔法命中检定，目标所在格无水时尝试点燃；远程分支不直接使用20–25近战伤害'),
                          _metric('远程点燃基础持续参数',4,'回合','已有更长燃烧不缩短；目标免疫等另计')]
        elif name.endswith(('$frostelemental','$frost')):
            abilities += [_metric('近战命中后冻结处理概率：干燥／水格','33.3333%／100%','','普通攻击已进入命中效果处理；水格不检查目标是否飞行，冻结免疫另计'),
                          _metric('远程命中后冻结处理概率',100,'%','先进行魔法命中检定；不直接使用20–25近战伤害'),
                          _metric('一次冻结处理添加冻伤：干燥／水格','3／5','回合','目标尚未冻结时；已存在冻伤以10回合上限限制本次添加，再计状态抗性'),
                          _metric('冻伤达到上限后的冻结基础持续',10,'回合','本次处理前已有冻伤，且添加后达到10，目标不免疫冻结时；不是首次命中必定冻结'),
                          _metric('已冻结目标再次冻结处理的参数',2,'回合','由Buff.affect处理；不是无条件额外叠加2回合')]
        elif name.endswith(('$shockelemental','$shock')):
            requested.add('damage')
            arc=math.floor(float32(float32(p['damage'])*float32(.4))+.5)
            abilities += [_metric('近战电弧基础倍率',40,'%','进入近战命中效果处理后的伤害参数乘0.4，再四舍五入；各受击者的抗性等另计'),
                          _metric('所填近战伤害的每个电弧基础伤害',arc,'HP','不是敌人普攻总伤害；目标格无水时，原近战目标从电弧受击名单移除，其他连锁角色仍可能受击'),
                          _metric('电弧首次搜索距离',2,'可通行路径格','沿非实墙路径查找角色，可递归连锁；后续角色站水中且不飞行时搜索2格，否则1格。排除施法者及已命中的角色，不区分阵营'),
                          _metric('远程命中后失明基础持续',5,'回合','先进行魔法命中检定；不直接使用20–25近战伤害，状态抗性和免疫另计')]
        else:
            abilities += [_metric('混沌远程普通命中检定','跳过','','直接触发诅咒法杖效果；不是固定伤害，也不意味着每种效果都能绕过免疫'),
                          _metric('混沌近战命中效果','随机有效诅咒法杖效果','','先完成普通近战命中效果处理，再选择效果；具体伤害和状态按被选效果分别结算')]
    elif name.startswith('yogfist$'):
        light_dark=name in ('yogfist$brightfist','yogfist$darkfist')
        abilities=[_metric('初始远程冷却',0,'计数','远程可用时须魔法弹道首先碰到目标；生物和实心地形会阻挡'),
                   _metric('远程施放耗时',1,'回合','光明／黑暗之拳仅非相邻时使用远程；其他四种可在相邻且冷却结束时使用远程'),
                   _metric('远程施放后添加冷却',0 if light_dark else '8–12','计数',
                           '此种远程没有额外冷却；相邻时改用普通近战' if light_dark else
                           '范围内抽取浮点值，非等概率；保留原冷却余量。未麻痹时每次自身行动开始减1，冷却大于0只可普通近战，不是固定玩家回合数')]
        if name=='yogfist$burningfist':
            requested.add('depth')
            abilities += [_metric('远程目标格有水时','蒸干该格，不直接点燃','','不进行普通命中检定；这次仍会在符合条件的目标邻格补充火焰'),
                          _metric('远程点燃基础持续参数',8,'回合','目标格无水时尝试点燃，不进行普通命中检定；已有更长燃烧不缩短，免疫等另计，不是8点总伤害'),
                          _metric('所填层数的燃烧单次基础伤害',span(1,3+depth//4),'HP',f'按当前主地牢等效层数{depth}，每次燃烧状态行动随机结算；不是远程施放的直接伤害或保证总量'),
                          _metric('周围火焰补充后的最低体积',4,'体积','每次自身行动对自身及周围8格、远程施放对目标及周围8格处理；仅非水、非实心且现有火焰体积小于4的格补足，不是4点伤害'),
                          _metric('每次自身行动蒸干水格的尝试','自身格＋1–2次邻格抽取','','自身站水中先蒸干；邻格抽取次数为1的概率1/3、为2的概率2/3，可重复抽到同一格，不能保证蒸干对应数量的水格')]
        elif name=='yogfist$soiledfist':
            requested.update(('damage','grass_cells'))
            abilities += [_metric('远程扎根基础持续参数',3,'回合','先进行魔法命中检定，命中掷骰倍率×2，不是必中；飞行目标不能扎根，状态抗性和免疫另计，不直接造成普通攻击伤害'),
                          _metric('远程播草范围','目标格及周围8格','','不论扎根是否命中都会播草；仅距基座超过4格、非实心且当前不是高草／茂草的格可改写'),
                          _metric('远程每个可播草格变为茂草概率',20,'%','其余80%变为普通草；不能据此保证出现固定数量的茂草'),
                          _metric('每次自身行动培育茂草的尝试','1–2次自身或邻格抽取','','次数为1的概率2/3、为2的概率1/3，可重复；只有抽到普通草才改成茂草，随后在自身及周围8格的可播草格铺普通草'),
                          _metric('所填草丛减伤后的输入',_soiled_fist_damage(p['damage'],p['grass_cells']),'HP输入',f'自身及周围8格有{p["grass_cells"]}格高草／茂草；输入先乘（6−格数）÷6并四舍五入，再结算来源抗性等。0或负结果不造成普通扣血，不是最终HP损失'),
                          _metric('燃烧状态伤害','不扣血','','仍可被点燃，火焰可烧毁草丛；不表示所有火焰来源免疫')]
        elif name=='yogfist$rottingfist':
            requested.add('damage')
            bleed=float32(float32(p['damage'])*float32(.6))
            first_low=float32(bleed/float32(2))
            abilities += [_metric('受伤转流血','原输入不立即扣血','','非无敌、来源不是流血且此拳自身无镰刀收割标记时；来源抗性结算并四舍五入后再转换，流血来源等例外走普通承伤处理'),
                          _metric('所填伤害传给流血的强度参数',bleed,'强度参数','所填值已经过来源抗性并四舍五入；再乘0.6，不是直接扣血、固定持续时间或总伤害'),
                          _metric('新流血首次强度范围',span(first_low,bleed),'强度','流血在传入强度的1/2至全值之间随机抽取，非等概率；已有流血取更强值，不相加'),
                          _metric('新流血首跳基础伤害',span(math.floor(first_low+.5),math.floor(bleed+.5)),'HP','仅新流血的首次状态行动，将首次强度四舍五入后进入普通承伤处理；后续每跳重新随机衰减，不能乘持续回合估算总量'),
                          _metric('正常水中每次自身行动恢复',6,'HP','当前生命未满且自身格有水时；按最大生命300÷50向下取整，恢复不超过缺失生命，临时最大生命改变时另算'),
                          _metric('远程播种毒气体积',100,'体积','在目标格播种，不进行普通命中检定；100不是伤害或持续回合，气体扩散与目标停留决定实际受击'),
                          _metric('所填层数的毒气单次基础伤害',1+depth//5,'HP',f'气体更新时位于有毒气格的非免疫生物；按当前主地牢等效层数{depth}计算，普通护甲不抵挡，抗性等另计'),
                          _metric('近战命中后施加淤泥概率',50,'%','普通攻击效果处理后尝试施加，不额外要求最终伤害大于0；目标免疫等另计')]
        elif name=='yogfist$rustedfist':
            abilities += [_metric('远程残废基础持续参数',4,'回合','不进行普通命中检定；状态抗性和免疫另计，不直接造成22–44近战伤害'),
                          _metric('承伤转为延迟池的额度','来源抗性取整后的伤害','伤害池参数','非无敌且来源不是延迟伤害状态时；非负结果全部加入已有池，原输入不立即扣血'),
                          _metric('新延迟池首次伤害前等待',1,'回合','池原本为0时设置；已有非零池再追加不重新等待'),
                          _metric('延迟池每次基础伤害','max(1, ⌊当前池×0.1⌋)','HP输入','每次延迟状态行动先按此量尝试伤害，再从池扣除同量；实际HP损失受后续承伤处理影响'),
                          _metric('延迟状态后续行动间隔',1,'回合','池扣至0或更低后移除；不是固定10回合结清，也不能把池值保证为最终总扣血')]
        elif light_dark:
            bright=name=='yogfist$brightfist'
            abilities += [_metric('远程光束基础伤害' if bright else '远程暗影弹基础伤害','10–20','HP','先进行魔法命中检定，命中掷骰倍率×2，不是必中；不使用18–36近战范围，来源抗性、魔法防护等另计'),
                          _metric('半血传送触发线',150,'HP','普通最大生命300；本次承伤前高于150、承伤后仍存活且不超过150才触发，生命设回150并传到玩家视野外可达空位，随后游荡'),
                          _metric('远程命中后失明基础持续' if bright else '远程命中后削减光亮持续',5 if bright else 50,'回合',
                                  '先完成光束伤害，再延长失明；已有更长失明不缩短，状态抗性和免疫另计' if bright else
                                  '先完成暗影弹伤害；仅目标已有光亮状态时缩短其剩余时间，不是50点HP伤害或直接减少50格视野')]
            if bright:
                abilities += [_metric('半血传送时失明基础持续',15,'回合','施加给玩家；已有更长失明不缩短，状态抗性和免疫另计'),
                              _metric('死亡时失明基础持续',30,'回合','施加给玩家；本次直接致死也走此分支，不触发半血传送')]
            else:
                abilities += [_metric('半血传送或死亡时的光亮','移除玩家光亮状态','','玩家有光亮才移除；不是施加失明状态，直接致死不触发半血传送')]
    elif name == 'pylon':
        requested.add('damage')
        damage=p['damage']
        reduced=damage if damage<15 else 14+math.floor(math.sqrt(8*(damage-14)+1)-1)//2
        abilities = [_metric('激活后邻格电击伤害','10–20','HP',('绝命头目每回合攻击3个相邻格：八方向环以当前方向为0，另取偏移3、5格' if stronger else '普通难度每回合攻击两个相对的相邻格：八方向环偏移0、4')+'；方向逐回合旋转；未激活时不攻击且无敌'),
                     _metric('所填伤害压缩后承受',reduced,'HP','激活且伤害类型可生效时；15点及以上输入触发压缩')]
    elif name == 'npcs.vaultsentry':
        abilities = [_metric('扫描首次电击','6–12','HP','可见扫描区域中的非隐形友方目标'),
                     _metric('连续扫描电击','3–6','HP','同一目标在上一次扫描更新中已被电击'),
                     _metric('默认扫描间隔',1,'回合','具体扫描方向、宽度及间隔由宝库房间配置，已生成机关以本局为准')]
    elif name == 'npcs.vaultlaser':
        abilities = [_metric('激光伤害','10–20','HP','路径上的友方目标；不进行命中检定，实墙阻挡光束'),
                     _metric('连续射击间隔',1,'回合','同一轮尚未发射完时；轮次间隔、方向及射击次数由房间配置')]
    if name in ('causticslime','fetidrat','goo','acidic','yogfist$rottingfist'):
        ooze_damage=1+depth//5 if depth>5 else '1（剩余持续参数为偶数时）' if depth<5 else 1
        abilities=[metric for metric in abilities if metric['label']!='淤泥初始持续参数']
        abilities += [_metric('淤泥初始持续参数',20,'回合','重新施加会重置持续参数和首次行动标记；状态行动与玩家操作不一一对应，不表示总伤害'),
                      _metric('所填等效层数的淤泥单次基础伤害',ooze_damage,'HP',f'按当前主地牢等效层数 {depth}，不是敌人生成层数；大于5时为1＋层数÷5向下取整，第5层为1，第1–4层只在整数剩余参数为偶数时造成1。普通护甲不抵挡，抗性等另计'),
                      _metric('水中洗掉淤泥的顺序','非飞行且所在格有水','','状态已行动过时先洗掉、不再造成该次伤害；新施加后第一次仍先结算一次状态行动，再在水中洗掉。不能把20回合直接乘单次伤害当总量')]
    if abilities:
        note = '正常难度，无飞升及额外状态修正。'
        if stronger:
            note = '绝命头目：仅明确标注的分支已切换；其他条目仍为普通机制参考，不能作为完整挑战机制。无飞升及额外状态修正。'
        if name == 'eye':
            note += ' 冷却结束、目标可见且光路可达时开始蓄力；光路遇实墙阻挡。可见目标可能重新瞄准，不能假定横移一格必定避开；以游戏实际瞄准和警告为准。'
        elif name == 'goo':
            note += ' 追近、后退或离开追击状态会取消蓄力；蓄力攻击尝试结束后也清除蓄力，未命中不会保留。'
        result.insert(2,{'title':'特殊攻击与机制','values':abilities,'note':note})
    result.insert(3 if abilities else 2,defense_block(values,identity,row,stronger_bosses=stronger))
    prize = _mimic_prize_block(name)
    if prize: result.insert(2,prize)
    return True
