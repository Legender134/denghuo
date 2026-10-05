"""Evaluated class abilities and a few stateful effects, with explicit assumptions."""
import math


def add_advanced_values(engine, identity, p, result, requested):
    from .values import block, metric, table, rounded, display

    h, strength, hp, ht, damage = p['hero_level'], p['strength'], p['hp'], p['max_hp'], p['damage']
    base = identity.split('$')[0]
    ranks = range(5)
    rows = []

    def rank_table(title, columns, calculate, note=''):
        result.append(table(title, ['投入点数', *columns], [[n, *calculate(n)] for n in ranks], note))

    if base == 'actors.hero.abilities.warrior.heroicleap':
        requested.add('power')
        rows = [metric('跳跃耗时', 1, '回合'), metric('落点影响半径', 1, '格'), metric('连续跳跃优惠窗口', 3, '回合')]
        rank_table('英勇冲击', ['落点基础伤害HP', '按此次减伤追加伤害HP'], lambda n: [f'{n}–{4*n}', rounded(p['power']*.25*n)], f'状态强度填写本次随机护甲减伤（当前 {p["power"]}）；敌人护甲仍生效。')
        rank_table('冲击波', ['最大击退格数', '施加易伤概率%', '易伤回合'], lambda n: [1+n if n else 0, 25*n, 5 if n else 0])
        rank_table('连续跳跃', ['第二次基础充能消耗%'], lambda n: [display(35*.84**n)], '在3回合内再次跳跃；未计英勇能量。')
    elif base == 'actors.hero.abilities.warrior.shockwave':
        requested.add('strength')
        low, high = 5+strength-10, 10+2*(strength-10)
        rank_table('震波扩散', ['最远格数', '扇形角度°'], lambda n: [5+n, 60+15*n])
        rank_table('震波威力', ['伤害HP', '麻痹概率%', '麻痹/残废回合'], lambda n: [f'{rounded(low*(1+.2*n))}–{rounded(high*(1+.2*n))}', 25*n, 5], f'有效力量 {strength}；未强化、未计目标护甲；未触发麻痹时为残废。')
        rank_table('攻击波', ['触发武器/攻击效果概率%'], lambda n: [min(100,30*n)])
    elif base == 'actors.hero.abilities.warrior.endure':
        requested.add('damage')
        rows = [metric('忍耐耗时', 3, '回合'), metric('效果总时限', 12, '回合'), metric('此次承伤的基础储存', damage//2, 'HP', '输入每次减免前伤害；各次分别向下取整再累积')]
        rank_table('无视苦痛', ['伤害减免%', '此次减免后伤害HP'], lambda n: [display((1-.5*.8**n)*100), display(damage*.5*.8**n)], '最终扣血还受其他防御及游戏取整影响。')
        rank_table('持续反击', ['储存伤害增益%', '可以强化的攻击次数'], lambda n: [15*n, 1+n])
        rank_table('势均力敌', ['每名2格内敌人的储存伤害增益%'], lambda n: [5*n])
    elif base == 'actors.hero.abilities.rogue.smokebomb':
        rows = [metric('邻近敌人失明', engine.duration('Blindness')/2, '回合'), metric('通常使用耗时', 1, '回合')]
        rank_table('木桩替身', ['替身生命HP', '替身额外护甲HP'], lambda n: [20*n, f'{n}–{3*n}'])
        rank_table('仓促撤退', ['极速/隐形回合'], lambda n: [display(.67+n) if n else 0])
        rank_table('暗影步伐', ['隐形时基础充能消耗%'], lambda n: [display(50*.84**n)], '不计英勇能量；投入点数大于0时隐形施放不耗回合。')
    elif base == 'actors.hero.abilities.rogue.deathmark':
        requested.add('target_hp')
        rows = [metric('印记持续', 5, '回合'), metric('目标受到伤害倍率', 1.25, '倍'), metric('施放耗时', 0, '回合')]
        rank_table('死亡耐性', ['印记死亡后护盾HP'], lambda n: [rounded(p['target_hp']*.125*n)], f'以施加印记时生命 {p["target_hp"]} 计算；重新施加可提高记录值。')
        rank_table('双重印记', ['连续第二次基础充能消耗%'], lambda n: [display(25*.707**n)], '优惠窗口按游戏触发，未计英勇能量。')
        rank_table('恐惧死神', ['目标残废回合', '目标恐惧回合', '3格内其他敌人残废/恐惧回合'], lambda n: [5 if n else 0, 5 if n>=2 else 0, '5/5' if n==4 else '5/0' if n==3 else '0/0'])
    elif base == 'actors.hero.abilities.rogue.shadowclone':
        requested.add('hero_level')
        rows = [metric('基础生命',80,'HP'), metric('基础伤害','10–20','HP'), metric('命中',h+9,'点'), metric('闪避',h+4,'点'), metric('指挥消耗',0,'充能')]
        rank_table('完美复制', ['映像最大生命HP'], lambda n: [80+rounded(.1*n*(15+5*h))])
        rank_table('暗影之刃', ['复制英雄每回合伤害%', '触发武器效果概率%'], lambda n: [8*n,25*n], '英雄伤害先按攻击耗时折算，随后取整。')
        rank_table('克隆护甲', ['复制英雄随机减伤%', '触发护甲效果概率%'], lambda n: [12*n,25*n])
    elif base == 'actors.hero.abilities.mage.warpbeacon':
        rows = [metric('同时保留信标',1,'个'), metric('放置信标耗时',1,'回合'), metric('放置信标消耗',0,'充能'), metric('同层普通传送耗时',0,'回合')]
        rank_table('远程信标', ['最远放置距离格'], lambda n: [4*n])
        rank_table('传送碎敌', ['敌人伤害HP','自身伤害HP'], lambda n: [f'{10*n}–{15*n}',5*n], '同层目标占据信标时；自身伤害最多降到生命及护盾合计剩1。')
        rank_table('超距跃迁', ['跨层基础充能消耗%'], lambda n: [display(35*(1.833-.333*n)) if n else '未解锁'], '未计英勇能量。')
    elif base == 'actors.hero.abilities.mage.wildmagic':
        requested.add('level')
        rank_table('狂野能量', ['临时法杖等级下界','临时法杖等级上界'], lambda n: [max(p['level'],min(p['level']+(4+n)//2,3+n)),max(p['level'],min(p['level']+(5+n)//2,3+n))], '只增加本次施法有效等级；奇数点数的两种结果各50%。')
        rank_table('倾泻魔法', ['最多施法次数','同法杖第三次概率%'], lambda n: [4+n,25*n], '需要有足够充能的法杖；同一法杖最多被选三次。')
        rank_table('魔力保留', ['每次法杖充能消耗','整次技能不耗回合概率%'], lambda n: [display(.5*.67**n),25*n])
    elif base == 'actors.hero.abilities.mage.elementalblast':
        rank_table('爆炸范围', ['最大半径格'], lambda n: [4+n])
        # These ranges are the spell's own damage, not the wand's ordinary zap.
        for label, factor in [('雷霆/解离/焰浪/霜冻',1),('魔弹/大地',.5),('冲击波/棱光',.67)]:
            rank_table('元素之力 · '+label, ['基础伤害HP'], lambda n,f=factor: [f'{rounded(15*(1+.25*n)*f)}–{rounded(25*(1+.25*n)*f)}'], '未计目标抗性；与魔杖等级无关。')
        rank_table('元素之力 · 额外效果', ['雷霆麻痹回合','霜冻冻结回合','酸蚀起始强度','再生缠绕回合','输血治疗额度HP'], lambda n: [display((1+.25*n)*engine.duration('Paralysis')/2),display((1+.25*n)*engine.duration('Frost')),rounded(6*(1+.25*n)),display((1+.25*n)*engine.duration('Roots')),rounded(10*(1+.25*n))])
        requested.add('targets')
        rank_table('反应护盾', ['获得护盾HP'], lambda n: [rounded(min(4+n,p['targets'])*2.5*n)], '目标数量填写实际被技能效果命中的单位数。')
    elif base == 'actors.hero.abilities.huntress.spectralblades':
        requested.add('damage')
        rows = [metric('主目标伤害',damage,'HP'), metric('额外目标伤害',rounded(damage*.5),'HP','未计其他效果及目标护甲')]
        rank_table('穿透飞刃', ['最多穿透墙格数','命中倍率'], lambda n: [2*n,display(1+.25*n)])
        rank_table('飞刃之扇', ['最多目标数量','扇形角度°'], lambda n: [1+n,30*n])
    elif base == 'actors.hero.abilities.huntress.spirithawk':
        rows = [metric('生命',10,'HP'),metric('伤害','5–10','HP'),metric('命中/闪避',60,'点'),metric('存续',100,'回合'),metric('指挥消耗',0,'充能')]
        rank_table('迅捷飞鹰', ['移动速度倍率','保证闪避次数'],lambda n:[display(2+n/2),2*n])
        rank_table('鹰眼', ['行动后的视距格'],lambda n:[6+n], '召唤瞬间最高8格；飞鹰行动后为此表值。')
        rank_table('夺目利爪', ['失明回合','残废回合'],lambda n:[[0,2,5,5,5][n],[0,0,0,2,5][n]])
    elif base == 'actors.hero.abilities.huntress.naturespower':
        rows = [metric('基础持续',8,'回合'),metric('最多延长次数',2,'次')]
        rank_table('生长之力', ['移动速度倍率'],lambda n:[display(2+.25*n)])
    elif base == 'actors.hero.abilities.duelist.feint':
        rows = [metric('位移距离',1,'格'),metric('施放耗时',1,'回合'),metric('残影生命',1,'HP'),metric('残影闪避',0,'点'),metric('反制技能窗口',3,'回合')]
        rank_table('佯装撤退', ['极速回合'],lambda n:[2*n])
        rank_table('暴露弱点', ['敌人虚弱/易伤回合'],lambda n:[2*n])
    elif base == 'actors.hero.abilities.duelist.challenge':
        requested.update(('damage','hp','max_hp'))
        rows = [metric('决斗持续',10,'回合'),metric('与对手最大距离',5,'格'),metric('施放耗时',0,'回合'),metric('连续决斗优惠窗口',3,'回合')]
        rank_table('拉近距离', ['施放时最大瞬移格数'],lambda n:[1+n if n else 0])
        rank_table('振奋胜利', ['胜利后实际治疗HP'],lambda n:[min(ht-hp,rounded(damage*(1-.707**n))+5*n)], f'基础伤害输入决斗期间实际损失的生命（当前 {damage}）；无治疗禁用效果。')
        rank_table('淘汰赛', ['下次基础充能消耗%'],lambda n:[display(50*.84**n)], '未计英勇能量。')
    elif base == 'actors.hero.abilities.duelist.elementalstrike':
        requested.update(('targets','damage','hp','max_hp','target_hp','target_max_hp','power'))
        rank_table('元素延展', ['最远格数','扇形角度°'],lambda n:[4+n,65+10*n])
        rank_table('定向能量', ['主攻击附魔强度增益%'],lambda n:[30*p['targets']*n])
        rank_table('强力打击 · 无附魔/结晶', ['无附魔区域伤害HP','结晶区域伤害HP','结晶修复量'],lambda n:[f'{rounded(6*(1+.3*n))}–{rounded(12*(1+.3*n))}',f'{rounded(10*(1+.3*n))}–{rounded(20*(1+.3*n))}',display(4*(1+.3*n))])
        rank_table('强力打击 · 恢复/弹力', ['招架护盾HP','吸血实际治疗HP','弹力最大击退格'],lambda n:[rounded(6*p['targets']*(1+.3*n)),min(ht-hp,rounded(2.5*p['targets']*(1+.3*n))),rounded(5*(1+.3*n))])
        rank_table('强力打击 · 状态', ['剧毒强度','流血强度','恐惧回合','缠绕回合'],lambda n:[display(10*(1+.3*n)),display(10*(1+.3*n)),display(10*(1+.3*n)),rounded(6*(1+.3*n))], '剧毒首次生效延迟3回合；附魔版本不作用于已被主攻击命中的目标。')
        missing=1-p['target_hp']/p['target_max_hp']
        rank_table('强力打击 · 概率', ['幸运掉落%','腐化%','死神斩杀%'],lambda n:[display(12.5*(1+.3*n)),display(min(100,(5+20*missing)*(1+.3*n))),display(min(100,(6+24*missing)*(1+.3*n)))], '区域目标有相应附魔且满足触发条件时；只输入一个目标的当前生命计算。')
        rank_table('强力打击 · 伤害传递', ['索敌区域伤害HP','动能区域伤害HP'],lambda n:[rounded(damage*.3*(1+.3*n)),rounded(p['power']*.4*(1+.3*n))], '索敌输入本次英雄随机伤害；动能的状态强度输入储存伤害。')
    elif base == 'actors.hero.abilities.cleric.powerofmany':
        requested.add('hero_level')
        rows = [metric('强化持续',100,'回合','辐光和血色羁绊生效时暂停倒计时'),metric('获得护盾',25,'HP'),metric('圣天誓盟生命',80,'HP'),metric('圣天誓盟伤害','5–30','HP'),metric('圣天誓盟护甲','1–5','HP'),metric('圣天誓盟命中',h+9,'点'),metric('圣天誓盟闪避',h+4,'点'),metric('指挥誓盟消耗',0,'充能')]
    elif base == 'actors.hero.abilities.cleric.ascendedform':
        rows = [metric('升华持续',10,'回合'),metric('初始护盾',30,'HP'),metric('启动耗时',1,'回合')]
    elif base == 'actors.hero.abilities.cleric.trinity':
        result.append(table('三位一体充能',['使用类型','英勇能量0点消耗%'],[['体之位格：普通附魔/刻印',25],['体之位格：稀有附魔/刻印',50],['意之位格：普通法杖',25],['意之位格：焰浪/再生',50],['魂之位格：戒指及其他神器',25],['魂之位格：虚空锁链/预知护符/沙漏',35],['魂之位格：干枯玫瑰/混乱魔典/骷髅钥匙',50]],'英勇能量减耗比例与上方表相同；具体模拟效果见对应位格法术数值。'))
    elif base == 'actors.buffs.preparation':
        result.append(table('刺客蓄力',['隐形累计回合','伤害增益%','随机伤害取最高的次数'],[[1,10,1],[3,20,1],[5,35,2],[9,50,3]]))
        result.append(table('斩杀所需生命低于',['蓄力回合','天赋0点%','+1%','+2%','+3%'],[[1,3,4,5,6],[3,10,13,17,20],[5,20,27,33,40],[9,50,67,83,100]],'强化致命天赋；首领与小首领的各项门槛均除以5，必须严格低于门槛。'))
        result.append(table('刺客之距最大瞬移',['蓄力回合','天赋0点格','+1格','+2格','+3格'],[[1,1,1,2,2],[3,2,3,4,5],[5,3,4,6,7],[9,4,6,8,10]]))
    elif identity.startswith('actors.buffs.monkenergy'):
        requested.update(('strength','hero_level','hp','max_hp','power'))
        low, high=2,max(2,rounded(1.5*(strength-8)))
        result.append(table('武僧五门武功',['武功','能量消耗','普通结果','强化结果'],[
            ['空振',1,f'两击各{low}–{high}HP / 0回合',f'两击各{low}–{high}HP / 0回合'],
            ['凝神',2,'1回合 / 格挡下次物理攻击','0回合 / 格挡下次物理攻击'],
            ['冲刺',3,'4格 / 0回合','8格 / 0回合'],
            ['盘龙',4,f'6–{max(6,6*(strength-8))}HP',f'9–{max(9,9*(strength-8))}HP'],
            ['冥想',5,'5回合 / 法杖与神器充能8回合',f'5回合 / 治疗{rounded((ht-hp)/5)}HP / 承伤减免80%'],
        ],'空振与盘龙忽略普通护甲，无力量之戒及其他伤害修正；强化空振可触发武器效果。盘龙击退最多6格，麻痹与有效击退格数相等。'))
        rows=[metric('当前等级能量上限',max(10,5+h//2),'点'),metric('盘龙最大击退',6,'格'),metric('盘龙最大麻痹',6,'回合')]
        from .game_math import monk_empowered
        capacity=max(10,5+h//2)
        thresholds=[]
        for n in range(1,4):
            integer_min=next(energy for energy in range(capacity+1) if monk_empowered(energy,capacity,n))
            half_min=next(energy/2 for energy in range(2*capacity+1) if monk_empowered(energy/2,capacity,n))
            thresholds.append([n,integer_min,display(half_min),'是' if monk_empowered(p['power'],capacity,n) else '否'])
        result.append(table('武道振兴强化门槛',['天赋投入','整数内力至少','半点内力至少',f'所填内力 {display(p["power"])} 是否强化'],thresholds,
                            '内力可含小数，最后一列直接按所填内力判定；前两列分别适用于整数和半点内力。'))
    elif base == 'items.potions.elixirs.elixirofaquaticrejuvenation':
        requested.update(('hp','max_hp'))
        amt=min(max(1,ht/50),ht-hp)
        rows=[metric('水中每回合实际恢复',f'{math.floor(amt)}–{math.ceil(amt)}','HP','剩余治疗池足够；当前生命未满且不漂浮'),metric('本回合平均恢复',amt,'HP'),metric('向上取整概率',(amt%1)*100,'%')]
    elif base == 'items.remains.brokenhilt':
        requested.add('hero_level');rows=[metric('每次近战额外伤害',max(2,h//3),'HP'),metric('生效攻击次数',2,'次')]
    elif base == 'items.remains.sealshard':
        requested.add('max_hp');rows=[metric('获得护盾',rounded(ht/5),'HP')]
    elif base == 'items.remains.tornpage':
        requested.update(('hp','max_hp'));rows=[metric('治疗额度',rounded(ht/10),'HP'),metric('实际治疗',min(ht-hp,rounded(ht/10)),'HP')]
    elif base == 'items.remains.brokenstaff':rows=[metric('法杖立即充能',1,'次')]
    elif base == 'items.remains.cloakscrap':rows=[metric('神器充能强度',4,'点')]
    elif base == 'items.remains.bowfragment':rows=[metric('周围长草范围',1,'格'),metric('最多长出高草',5,'格')]

    if identity == 'items.weapon.enchantments.blocking$blockbuff':
        requested.add('level');rows=[metric('每次触发后护盾',2+p['level'],'HP','无触发强度修正'),metric('护盾时限',5,'回合','不动如山可减慢衰减')]
    elif identity == 'items.weapon.enchantments.kinetic$conserveddamage':
        requested.add('power');rows=[metric('下次命中追加伤害',p['power'],'HP'),metric('每回合储存伤害衰减',max(.1,p['power']*.025),'HP','本回合值；衰减后向上取整作为下次追加伤害')]
    elif identity == 'actors.buffs.prismaticguard':
        requested.add('hero_level');rows=[metric('虹光守卫最大生命',10+math.floor(h*2.5),'HP'),metric('未召出时生命恢复速度',.1,'HP/回合','允许自然恢复时')]
    elif identity in ('actors.blobs.freezing','actors.blobs.blizzard'):
        rows=[metric('单次寒冷累积：干地',3,'回合'),metric('单次寒冷累积：水面',5,'回合'),metric('寒冷达到此值后冻结',engine.duration('Chill'),'回合'),metric('触发冻结时长',engine.duration('Frost'),'回合'),metric('对已冻结目标延长',2,'回合')]
        if identity.endswith('blizzard'):rows.append(metric('每回合施加次数',2,'次','先后两次，期间可触发冻结'))
    elif identity == 'actors.blobs.paralyticgas':rows=[metric('持续接触时刷新麻痹',engine.duration('Paralysis'),'回合')]
    elif identity == 'actors.blobs.confusiongas':rows=[metric('持续接触时刷新眩晕',2,'回合')]
    elif identity == 'actors.blobs.web':rows=[metric('触碰后缠绕',engine.duration('Roots'),'回合')]
    elif identity == 'actors.blobs.corrosivegas':
        requested.add('power');rows=[metric('酸蚀当前强度',p['power'],'点','填写气体强度'),metric('每次接触刷新酸蚀',2,'回合')]
    elif identity == 'actors.buffs.wellfed':
        rows=[metric('通常饱腹时限',450,'回合','无盐块'),metric('通常额外治疗额度',25,'HP','生命不足时'),metric('每次额外治疗',1,'HP'),metric('治疗间隔',18,'回合','无盐块'),metric('饥饿游戏时限',150,'回合','无盐块'),metric('饥饿游戏治疗额度',9,'HP','包括末次在剩余时间0时触发的治疗；一直缺血')]
    elif identity == 'items.scrolls.exotic.scrollofsirenssong$enthralled':rows=[metric('自然到期时间','永久','', '不会自行到期；伤害等不能解除忠诚')]
    elif identity == 'actors.buffs.combo$combomove.parry':rows=[metric('招架窗口',1,'回合'),metric('招架次数',1,'次'),metric('消耗连击',0,'点','成功招架时；失败会重置')]
    elif identity == 'actors.buffs.combo$combomove.slam':
        requested.update(('combo', 'armor_roll', 'damage'))
        bonus = rounded(p['armor_roll']*p['combo']/5)
        rows = [metric('最低连击数', 4, '点'), metric('按此次护甲减伤追加伤害', bonus, 'HP'),
                metric('未计目标减伤的攻击伤害', damage+bonus, 'HP', '达到4连击；无其他攻击或防御效果'),
                metric('消耗连击', p['combo'], '点', '施放后结束连击'),
                metric('普通闪避造成的未命中概率', 0, '%', '不能绕过无敌等特殊机制')]
    elif identity == 'actors.buffs.combo$combomove.crush':
        requested.update(('combo', 'damage', 'enemy_armor'))
        hit = rounded(damage*.25*p['combo'])
        area = max(0, hit//2-p['enemy_armor'])
        rows = [metric('最低连击数', 8, '点'), metric('主目标伤害倍率', .25*p['combo'], '倍'),
                metric('主目标减伤前伤害', hit, 'HP', '无其他攻击或防御效果；达到8连击'),
                metric('周围单个目标伤害', area, 'HP', '按所填随机伤害和目标护甲；未计抗性'),
                metric('周围易伤目标伤害', int(area*1.33), 'HP', '目标已有易伤；未计其他抗性'),
                metric('周围目标最大路径距离', 3, '格', '从英雄所在格计算；墙会阻挡路径'),
                metric('消耗连击', p['combo'], '点', '施放后结束连击')]
    elif identity == 'items.quest.pickaxe.ability':
        requested.add('level')
        level = p['level']
        from .game_math import augmented_damage
        bonus = 8+2*level
        result.append(table('穿刺伤害 · 无其他装备和临时效果', ['武器强化', '普通目标减伤前HP', '特殊目标减伤前HP', '对特殊目标追加HP'],
                            [[label, f'{augmented_damage(2+level,factor)}–{augmented_damage(15+3*level,factor)}',
                              f'{augmented_damage(2+level,factor)+augmented_damage(bonus,factor)}–{augmented_damage(15+3*level,factor)+augmented_damage(bonus,factor)}', augmented_damage(bonus,factor)]
                             for label, factor in [('无强化', 1), ('速度强化', .7), ('伤害强化', 1.5)]],
                            '特殊目标：无机生物、蝇群、蜜蜂、螃蟹、蜘蛛与蝎子。各数值均未计目标护甲、力量余裕及其他增益。'))
        rows = [metric('普通闪避造成的未命中概率', 0, '%', '不能绕过无敌等特殊机制'),
                metric('对存活目标施加易伤', 3, '回合'), metric('后续易伤承伤倍率', 1.33, '倍'),
                metric('基础充能消耗', 1, '点'), metric('基础攻击耗时', 1, '回合', '无强化、力量不足或其他攻速效果')]
    elif identity == 'actors.mobs.monk$focus':rows=[metric('保证招架物理攻击',1,'次','包括通常必中的攻击')]
    elif identity == 'actors.buffs.holdfast':
        result.append(table('战士不动如山',['投入点数','额外护甲HP','连击/护盾剩余衰减速度%'],[[n,f'{n}–{2*n}',[100,50,25,0][n]] for n in range(4)],'移动离开原格后失效；表为战士效果。'))
    elif identity == 'actors.buffs.enhancedrings':
        rows=[metric('戒指有效等级提升',1,'级')]
        result.append(table('戒指强化天赋',['投入点数','使用神器后的持续回合'],[[n,3*n] for n in range(1,4)]))
    elif identity == 'actors.buffs.championenemy$growing':
        result.append(table('成长精英成长对照',['已触发成长次数','首次成长后经过回合','命中/闪避/物理伤害倍率','伤害减免%'],[[n,4*(n-1) if n else '尚未行动',display(1.19+.01*n),display((1-1/(1.19+.01*n))*100)] for n in [0,1,5,10,20,50,100]],'未包含其他精英效果；第一次成长在状态首次行动时触发。'))
    elif identity == 'items.quest.corpsedust':
        result.append(table('尸尘召唤间隔',['当前尸尘怨灵数','再召一只所需回合'],[[n,min(49,(n+1)**2)] for n in range(8)],'有可用生成格且尸尘在可用背包内时；失败不会照常生成。'))
    elif identity == 'items.wands.wandofregrowth$dewcatcher':rows=[metric('产出露珠','3–6','滴','周围可用位置足够时；每格最多一滴')]
    elif identity == 'actors.hero.spells.holylance$lancecooldown':rows=[metric('再次使用等待',30,'回合')]
    elif identity == 'actors.hero.spells.guidinglight$illuminated':
        requested.add('hero_level');rows=[metric('祭司消耗光耀追加伤害',h+5,'HP','使用法杖、辐光等指定攻击时；只应用一次')]
    elif identity == 'actors.mobs.brute$bruterage':
        requested.add('target_max_hp');rows=[metric('狂暴初始护盾',p['target_max_hp']//2+4,'HP','填写暴徒最大生命；普通未飞升'),metric('每回合护盾流失',4,'HP','未飞升'),metric('狂暴伤害','15–40','HP','普通豺狼暴徒，非装甲变种')]
    elif identity == 'levels.traps.cursingtrap':rows=[metric('诅咒身上武器/护甲数量',1,'件','存在可诅咒目标时；优先无附魔/刻印装备'),metric('地面装备受诅咒比例',100,'%','该格内可升级且非投掷武器的所有物品')]
    elif identity == 'actors.mobs.tengu$bombability$bombitem':
        requested.add('depth');d=p['depth'];rows=[metric('爆炸倒计时',3,'回合','显示3、2、1后爆炸'),metric('爆炸半径',2,'格'),metric('爆炸基础伤害',f'{5+d}–{10+2*d}','HP','目标护甲生效')]
    elif identity == 'levels.rooms.special.sentryroom$sentry':
        requested.add('depth');d=p['depth'];rows=[metric('魔法伤害',f'{2+d//2}–{4+d}','HP'),metric('魔法攻击命中',20+2*d,'点'),metric('首轮后攻击间隔',1,'回合','仍站在房间危险地板上时'),metric('可对哨卫造成伤害',0,'HP')]
    elif identity.startswith('actors.hero.talent$'):
        name=identity.split('$')[1];cooldowns={'improvisedprojectilecooldown':50,'seershotcooldown':20,'aggressivebarriercooldown':50,'lethalhastecooldown':100,'swiftequipcooldown':19,'searinglightcooldown':20}
        if name in cooldowns:rows=[metric('状态基础时限',cooldowns[name],'回合','触发时设置；迅疾配装刚装备后有效冷却约20回合')]
        elif name in ('provokedangertracker','lingeringmagictracker','followupstriketracker','deadlyfollowuptracker','liquidagilacctracker'):rows=[metric('保留时间',5,'回合','触发相应攻击后可提前消失')]
        elif name=='rejuvenatingstepscooldown':result.append(table('复春步伐冷却',['投入点数','冷却回合'],[[1,10],[2,5]]))
    if identity == 'actors.buffs.ascensionchallenge':
        requested.add('max_hp')
        rows=[metric('首次向上进入普通楼层增加',2,'层诡咒'),metric('击败强化敌人通常减少',1,'层诡咒'),metric('击败食尸鬼/撕裂魔减少',.5,'层诡咒'),metric('再次到达首领层的治疗额度',ht,'HP','首次到达，逐回合治疗，每回合20'),metric('首领层补充饱食',450,'点')]
        result.append(table('护符诡咒层数效果',['层数门槛','敌人非战斗移动倍率','英雄正常移动倍率','持续损血HP/回合'],[[0,1,1,0],[2,1,1,0],[4,2,1,0],[6,2,.5,0],[8,2,.5,1],[10,2,.5,1.5],[12,2,.5,2]],'2层起，8格外敌人不断向你靠近；6层起英雄移速减半且最高1倍；首领层不触发诡咒持续扣血。'))
    elif identity == 'actors.hero.herosubclass.warden':rows=[metric('播种时周围额外长草',8,'格','周围8格为可长草地形时'),metric('亲手播种耗时',1,'回合')]
    elif identity == 'actors.hero.herosubclass.paladin':
        result.append(table('圣骑士维持神圣附魔/刻印',['本次其他法术消耗充能','延长回合'],[[c,10*c] for c in [0,1,2,3,4,5,6,8]],'已存在的神圣武器/神圣护甲状态获得延长；重复施放同名法术不额外延长它自身。'))
    elif identity == 'items.quest.ceremonialcandle':rows=[metric('完成仪式所需蜡烛',4,'根')]
    elif identity == 'items.honeypot':rows=[metric('打碎时释放蜜蜂',1,'只')]
    elif identity == 'actors.blobs.inferno':rows=[metric('每格燃烧刷新时长',engine.duration('Burning'),'回合'),metric('额外普通火焰初始量',4,'单位','该格不存在普通火焰时')]
    elif identity == 'actors.blobs.stormcloud':rows=[metric('可转换地面变为水面概率',100,'%','每回合作用于覆盖的格子；同时熄灭该格普通火焰')]
    elif identity == 'actors.blobs.waterofawareness':rows=[metric('装备物品鉴定比例',100,'%'),metric('背包物品诅咒检测比例',100,'%'),metric('本层物品位置揭示比例',100,'%')]
    elif identity == 'actors.blobs.sacrificialfire':
        requested.add('enemy_exp');exp=p['enemy_exp']+1;rows=[metric('普通敌人献祭进度',f'{2*exp}–{3*exp}','点','非雕像/宝箱怪/蜜蜂/食人鱼/咒缚灵；按目标基础经验输入')]
    elif identity == 'levels.traps.guardiantrap$guardian':
        requested.add('depth');d=p['depth'];rows=[metric('最大生命',15+5*d,'HP'),metric('闪避',4+d,'点'),metric('未计武器命中倍率的命中',9+d,'点'),metric('未计武器防御的护甲',f'0–{d}','HP'),metric('随机武器等级',0,'级','伤害由随机武器种类决定，无附魔')]
    elif identity == 'actors.mobs.tengu$shockerability$shockeritem':
        requested.add('depth');rows=[metric('每次电击基础伤害',2+p['depth'],'HP'),metric('切换方向间隔',1,'回合'),metric('交替图案',2,'种','十字与斜对角交替')]
    elif identity == 'actors.buffs.lockedfloor':rows=[metric('封层期间饱食消耗',0,'点/回合'),metric('封层期间饿损伤害',0,'HP/回合')]
    elif identity in ('actors.blobs.smokescreen','actors.blobs.foliage'):
        rows=[metric('此环境本身直接伤害',0,'HP','烟幕阻挡视野；落叶用于旧版花园视觉')]
    elif identity == 'levels.vaultlevel$vaultflametrap':rows=[metric('陷阱图案本身伤害',0,'HP','此图案不主动触发；实际地火由房间定时机关控制')]
    elif identity == 'actors.blobs.goowarn':rows=[metric('粘咕蓄力威胁距离',2,'格','可穿过的直线路径内；显示为蓄力警告，伤害见粘咕数值')]
    elif identity == 'levels.rooms.special.toxicgasroom$toxicvent':
        requested.add('depth');rows=[metric('每次补充毒气量',12,'单位','该格毒气不高于108单位时，每回合补充'),metric('毒气每回合伤害',1+p['depth']//5,'HP')]
    elif identity == 'actors.buffs.pincushion':rows=[metric('状态解除时钉住物品返还比例',100,'%','在目标所在格掉落；这里只包括已经钉住、尚未损坏的武器')]
    elif identity == 'actors.buffs.lostinventory':rows=[metric('普通遗落物品可用数量',0,'件','明确保留的物品及矿洞镐的例外除外；找回遗物后解除')]
    elif identity in ('actors.buffs.amok','actors.buffs.revealedarea'):
        requested.add('power');rows=[metric('按你填写的剩余时间',p['power'],'回合','不同来源没有统一时限；此处填写游戏中状态图标的剩余时间')]
    elif identity == 'actors.mobs.goo':
        result.append(table('粘咕血量与挑战',['模式','最大生命HP','狂暴开始生命HP','水中每次治疗HP'],[['普通',100,50,1],['绝命头目',120,60,'依次1、2、3，之后3']], '离开水面或生命已满后，连续治疗增幅重置。'))
        result.append(table('粘咕攻击阶段',['生命阶段','普通攻击HP','蓄力攻击HP','普通命中','蓄力命中','基础闪避'],[['超过50%','1–8','3–24',10,20,8],['不高于50%','1–12','3–36',15,30,12]],'没有其他增益，目标护甲仍生效。'))
        rows=[metric('基础护甲','0–2','HP'),metric('命中时施加淤泥概率',100/3,'%'),metric('蓄力攻击最大距离',2,'格'),metric('正常开始蓄力概率',20,'%','超过半血，非已在蓄力状态'),metric('狂暴开始蓄力概率',50,'%','半血以下')]
    elif identity == 'actors.mobs.tengu':
        result.append(table('天狗血量与阶段',['模式','最大生命HP','进入第二阶段生命HP','触发跳跃的生命档宽HP'],[['普通',200,100,25],['绝命头目',250,125,31]],'一击不能穿过多个生命档，最终血量还受阶段限制。'))
        rows=[metric('伤害','6–12','HP'),metric('相邻目标命中',10,'点'),metric('非相邻目标命中',20,'点'),metric('基础闪避',15,'点'),metric('基础护甲','0–5','HP')]
    elif identity == 'actors.mobs.dm300':
        result.append(table('DM-300血量与超充',['模式','最大生命HP','超充生命节点HP','需关闭电塔数','技能基础冷却回合','落岩伤害HP'],[['普通',300,'200 / 100',2,'5–9','6–12'],['绝命头目',400,'300 / 200 / 100',3,'5–7','10–20']]))
        rows=[metric('攻击伤害','15–25','HP'),metric('基础命中',20,'点'),metric('基础闪避',15,'点'),metric('基础护甲','0–10','HP'),metric('超充移动速度倍率',2,'倍'),metric('超充期间普通承伤',0,'HP','先关闭生效的电塔')]
    elif identity == 'actors.mobs.dwarfking':
        result.append(table('矮人国王阶段',['模式','初始生命HP','第二/三阶段生命HP','第二阶段护盾HP','摧毁护盾所需侍从数','第一阶段基础召唤/技能冷却回合'],[['普通',300,50,300,12,'10–14'],['绝命头目',450,100,450,18,'8–10']], '第二阶段普通伤害无效，每个有效侍从死亡削减25护盾；第三阶段承伤转为延缓伤害。'))
        rows=[metric('物理伤害','15–25','HP'),metric('基础命中',26,'点'),metric('基础闪避',22,'点'),metric('基础护甲','0–10','HP'),metric('占据召唤格时伤害','20–40','HP')]
    elif identity == 'actors.mobs.yogdzewa':
        result.append(table('古神战斗节点',['生命HP','普通召唤拳数','绝命头目召唤拳数'],[[700,1,2],[400,1,2],[100,1,2]],'拳未被击败时古神免疫伤害，阶段不会被一次攻击跳过。'))
        rows=[metric('最大生命',1000,'HP'),metric('普通死光伤害','20–30','HP'),metric('绝命头目死光伤害','30–50','HP'),metric('基础技能/召唤冷却','10–15','回合','不同阶段和受到伤害会缩短实际等待')]

    if rows:result.append(block('具体效果',rows))
