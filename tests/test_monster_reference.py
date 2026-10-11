import unittest

from companion.engine import Catalog
from companion.rules import NumericRules
from companion.values import PlayerValues
from companion.monster_reference import loot_rows, monster_record, reference


class MonsterReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.values = PlayerValues(NumericRules(Catalog()))

    def detail(self, name, **params):
        return self.values.detail('actors.mobs.'+name, params)

    def stats(self, name, **params):
        return {r['label']:r['value'] for r in self.detail(name,**params)['blocks'][0]['values']}

    def loot(self, name, **params):
        key = 'actors.mobs.'+name
        row = monster_record(self.values.catalog,key)
        return loot_rows(self.values,key,row,{'depth':1,'hero_level':1,'loot_count':0,'swarm_generation':0,**params})

    def chance(self, name, item, **params):
        return sum(r['probability'] for r in self.loot(name,**params) if r.get('id') == item)

    def mechanisms(self, name, **params):
        block=next(row for row in self.detail(name,**params)['blocks'] if row['title']=='特殊攻击与机制')
        return {row['label']:row for row in block['values']}

    def test_slime_compression_has_source_thresholds_and_separate_input_stage(self):
        # Slime.java's explicit threshold examples, plus the values immediately
        # below each boundary. CausticSlime inherits the same damage method.
        cases=((0,0),(4,4),(5,5),(6,5),(7,6),(9,6),(10,7),(13,7),
               (14,8),(18,8),(19,9),(24,9),(25,10))
        for name in ('slime','causticslime'):
            for damage,expected in cases:
                detail=self.detail(name,damage=damage)
                metrics=self.mechanisms(name,damage=damage)
                self.assertEqual(metrics['所填输入经史莱姆压缩后']['value'],str(expected))
                self.assertIn('不是保证扣血',metrics['所填输入经史莱姆压缩后']['condition'])
                field=next(row for row in detail['inputs'] if row['key']=='damage')
                self.assertEqual(field['label'],'进入敌人承伤分支的整数伤害')
            self.assertTrue(any('5点起压缩' in r[1] for r in self.defenses(name)['rows']))
            self.assertFalse(any(b['title']=='其他明确数值' for b in self.detail(name)['blocks']))

    def test_spawner_compression_boundaries_and_depth_cooldown_follow_official_body(self):
        # DemonSpawner.damage's explicit input/output examples and their lower
        # neighbours, independent of the candidate's compression expression.
        for damage,expected in ((0,0),(19,19),(20,20),(21,20),(22,21),(24,21),
                                (25,22),(28,22),(29,23),(33,23),(34,24),(39,24),
                                (40,25),(46,25),(47,26),(54,26),(55,27),(63,27),
                                (64,28),(73,28),(74,29),(84,29),(85,30)):
            metrics=self.mechanisms('demonspawner',damage=damage,depth=21)
            self.assertEqual(metrics['所填输入经血巢压缩后']['value'],str(expected))
            self.assertEqual(metrics['该输入推进召唤冷却']['value'],str(expected))
        # The body uses6.67, so floor23 is46.66, not the rounded46.67 comment.
        for depth,expected in ((20,'60'),(21,'60'),(22,'53.33'),(23,'46.66'),(24,'40'),(30,'40')):
            self.assertEqual(self.mechanisms('demonspawner',depth=depth)['成功召唤后基础添加冷却']['value'],expected)
        self.assertTrue(any('20点起压缩' in row[1] for row in self.defenses('demonspawner')['rows']))
        field=next(r for r in self.detail('demonspawner')['inputs'] if r['key']=='damage')
        self.assertEqual(field['label'],'进入敌人承伤分支的整数伤害')

    def test_golem_and_guard_control_conditions_do_not_claim_fixed_player_turns(self):
        golem=self.mechanisms('golem')
        self.assertEqual(golem['拉回目标后冷却']['value'],'20')
        self.assertEqual(golem['自身成功传送后冷却']['value'],'30')
        self.assertIn('无落点时也会',golem['拉回目标行动耗时']['condition'])
        self.assertIn('只有成功传送',golem['自身成功传送后冷却']['condition'])
        guard=self.mechanisms('guard')
        self.assertEqual(guard['正常铁链最大敌人距离']['value'],'4')
        self.assertEqual(guard['每只守卫成功使用铁链次数']['value'],'1')
        self.assertEqual(guard['拉拽后残废基础持续']['value'],'4')

    def test_vault_golem_keeps_enemy_pull_without_unavailable_self_teleport(self):
        # VaultGolem retains Golem.Hunting, but Mob's stealth setup replaces
        # Golem.Wandering, the only normal entry to self-teleport preparation.
        metrics=self.mechanisms('quest.vault.vaultgolem')
        self.assertEqual(metrics['拉回目标后冷却']['value'],'20')
        self.assertEqual(metrics['拉回目标行动耗时']['value'],'1')
        self.assertEqual(metrics['能正常追近时的拉回选择']['value'],'1 / ⌊100÷距敌距离⌋')
        self.assertIn('追近失败后还有不经',metrics['能正常追近时的拉回选择']['condition'])
        self.assertIn('魔法免疫或无落点',metrics['拉回目标行动耗时']['condition'])
        self.assertEqual(metrics['自身传送']['value'],'不使用')
        self.assertIn('宝库潜行行为替换游荡状态',metrics['自身传送']['condition'])
        for label in ('自身传送准备耗时','自身传送落点处理耗时','自身成功传送后冷却'):
            self.assertNotIn(label,metrics)
            self.assertIn(label,self.mechanisms('golem'))

    def test_vault_dm200_inherits_gas_and_failed_approach_fallback(self):
        metrics=self.mechanisms('quest.vault.vaultdm200')
        self.assertEqual(metrics['排气行动耗时']['value'],'1')
        self.assertEqual(metrics['排气后冷却计数']['value'],'30')
        self.assertEqual(metrics['排气后冷却计数']['unit'],'次自身行动')
        self.assertEqual(metrics['弹道路径每格播种毒气体积']['value'],'20')
        self.assertEqual(metrics['弹道终点另播种毒气体积']['value'],'100')
        self.assertIn('追近失败后另有不经此随机检定',metrics['排气选择检定']['condition'])
        self.assertIn('路径与冷却仍需满足',metrics['排气选择检定']['condition'])
        self.assertNotIn('腐蚀气体基础强度',metrics)

    def test_vault_dm100_remote_shock_uses_vault_accuracy(self):
        # DM100.doAttack supplies the inherited3-10 bolt. Its virtual
        # attackSkill resolves to VaultDM100's25, not normal DM100's11.
        metrics=self.mechanisms('quest.vault.vaultdm100')
        self.assertEqual(metrics['远程电击基础伤害']['value'],'3–10')
        self.assertEqual(metrics['远程电击耗时']['value'],'1')
        self.assertEqual(metrics['魔法命中掷骰倍率']['value'],'2')
        self.assertIn('基础命中25',metrics['魔法命中掷骰倍率']['condition'])
        self.assertIn('非相邻',metrics['远程电击基础伤害']['condition'])
        self.assertIn('弹道被阻挡时使用普通攻击',metrics['远程电击基础伤害']['condition'])
        self.assertIn('不扣普通护甲',metrics['远程电击耗时']['condition'])
        self.assertIn('基础命中11',self.mechanisms('dm100')['魔法命中掷骰倍率']['condition'])

    def test_vault_skeleton_retains_death_explosion_and_two_independent_armor_rolls(self):
        metrics=self.mechanisms('quest.vault.vaultskeleton')
        self.assertEqual(metrics['死亡碎骨爆炸基础伤害']['value'],'6–12')
        self.assertIn('非坠落死亡',metrics['死亡碎骨爆炸基础伤害']['condition'])
        self.assertIn('周围8格',metrics['死亡碎骨爆炸基础伤害']['condition'])
        self.assertIn('不进行命中检定',metrics['死亡碎骨爆炸基础伤害']['condition'])
        self.assertEqual(metrics['碎骨爆炸护甲减伤掷骰']['value'],'2')
        self.assertIn('两次独立减伤掷骰之和',metrics['碎骨爆炸护甲减伤掷骰']['condition'])

    def test_vault_shaman_fixed_type_is_separate_from_per_hit_debuff_chance(self):
        metrics=self.mechanisms('quest.vault.vaultshaman')
        self.assertEqual(metrics['远程土弹伤害']['value'],'6–15')
        self.assertEqual(metrics['远程土弹耗时']['value'],'1')
        self.assertEqual(metrics['魔法命中掷骰倍率']['value'],'2')
        self.assertIn('基础命中25',metrics['魔法命中掷骰倍率']['condition'])
        self.assertIn('相邻或弹道受阻时使用普通攻击',metrics['远程土弹伤害']['condition'])
        self.assertEqual(metrics['命中后附加负面状态概率']['value'],'50')
        self.assertIn('仅远程魔法命中后、土弹伤害结算前',metrics['命中后附加负面状态概率']['condition'])
        for buff,chance in (('weakness','2/5'),('vulnerable','2/5'),('hex','1/5')):
            name=self.values.catalog.messages['actors.buffs.'+buff+'.name']
            metric=metrics[f'生成时选择{name}类型概率']
            self.assertEqual(metric['value'],chance)
            self.assertIn('生成时均匀抽取0–4并固定类型',metric['condition'])
            self.assertIn('每次攻击不重抽类型',metric['condition'])
            self.assertIn('未读取本局类型',metric['condition'])
        normal=self.mechanisms('shaman$redshaman')
        self.assertIn('基础命中18',normal['魔法命中掷骰倍率']['condition'])
        self.assertFalse(any('生成时选择' in label for label in normal))

    def test_vault_ability_reuse_keeps_overridden_stats_and_token_loot(self):
        # Values are independently specified by the fixed Vault subclasses;
        # they must not be replaced by the normal parent's stats or loot gate.
        expected={
            'vaultdm100':('2–8','25','18','4–8'),
            'vaultdm200':('10–25','28','15','0–8'),
            'vaultgolem':('25–30','28','15','0–12'),
            'vaultshaman':('5–25','25','18','5–11'),
            'vaultskeleton':('2–10','24','20','4–9'),
        }
        for name,vector in expected.items():
            identity='quest.vault.'+name
            with self.subTest(name=name):
                stats=self.stats(identity)
                self.assertEqual(tuple(stats[label] for label in ('基础伤害范围','基础命中','基础闪避','基础减伤范围')),vector)
                self.assertEqual(stats['基础经验'],'0')
                rows=self.loot(identity,hero_level=30,loot_count=7,wealth_bonus=-1)
                self.assertEqual(len(rows),1)
                self.assertEqual(rows[0]['id'],'items.quest.dwarftoken')
                self.assertAlmostEqual(rows[0]['probability'],5/6 if name=='vaultdm100' else 1,places=6)
                self.assertNotIn('loot_count',{row['key'] for row in self.detail(identity)['inputs']})

    def test_existing_vault_ghoul_and_elemental_abilities_keep_source_inheritance(self):
        pairs=(('ghoul','vaultghoul'),('elemental$fireelemental','vaultelemental$fire'),
               ('elemental$frostelemental','vaultelemental$frost'),('elemental$shockelemental','vaultelemental$shock'))
        for normal,vault in pairs:
            with self.subTest(vault=vault):
                self.assertEqual(self.mechanisms(normal,damage=7),self.mechanisms('quest.vault.'+vault,damage=7))

    def test_necromancer_and_spectral_summons_have_separate_profiles(self):
        normal=self.mechanisms('necromancer',depth=8)
        spectral=self.mechanisms('spectralnecromancer',depth=8)
        self.assertEqual(normal['首次召唤准备耗时']['value'],'1')
        self.assertEqual(normal['后续召唤准备耗时']['value'],'2')
        self.assertEqual(normal['普通召唤骷髅初始生命']['value'],'20')
        self.assertEqual(normal['骷髅满血时肾上腺素基础持续']['value'],'3')
        self.assertNotIn('普通召唤骷髅初始生命',spectral)
        self.assertNotIn('骷髅满血时肾上腺素基础持续',spectral)
        self.assertEqual(spectral['召唤怨灵的固定等效层数']['value'],'4')
        self.assertIn('普攻3–6',spectral['该召唤怨灵的基础数值']['value'])

    def test_bandit_requires_successful_theft_and_uses_half_source_durations(self):
        normal=self.mechanisms('thief')
        bandit=self.mechanisms('bandit')
        self.assertEqual(normal['一次成功偷窃数量']['value'],'1')
        self.assertIn('顶层',normal['偷窃尝试']['condition'])
        self.assertIn('不重抽',normal['偷窃尝试']['condition'])
        self.assertEqual(normal['丢弃被盗物品的逃脱最小距离']['value'],'6')
        self.assertNotIn('成功偷窃后失明基础持续',normal)
        self.assertEqual(bandit['成功偷窃后失明基础持续']['value'],'5')
        self.assertEqual(bandit['成功偷窃后残废基础持续']['value'],'5')
        self.assertEqual(bandit['成功偷窃后中毒剩余参数']['value'],'5–6')
        self.assertEqual(bandit['新中毒首次基础伤害']['value'],'2–3')

    def test_swarm_split_requires_remaining_two_hp_and_separates_pre_damage_parent(self):
        for hp,damage,clone in ((50,20,15),(9,2,3),(2,0,1),(21,20,0),(0,0,0),(10,20,0)):
            metrics=self.mechanisms('swarm',target_hp=hp,damage=damage,swarm_generation=2)
            self.assertEqual(metrics['若成功分裂，新个体初始生命']['value'],str(clone))
            self.assertEqual(metrics['原个体分裂后、最终承伤前生命']['value'],str(hp-clone))
            self.assertEqual(metrics['新个体分裂代数']['value'],'3')
        detail=self.detail('swarm',target_hp=50,damage=20)
        inputs={r['key']:r for r in detail['inputs']}
        self.assertIn('分裂判定前',inputs['target_hp']['label'])
        self.assertIn('防御效果处理',inputs['damage']['label'])

    def test_phantom_piranha_source_distance_and_java_half_rounding(self):
        for damage,expected in ((0,0),(1,1),(2,1),(11,6),(20,10),(25,13)):
            metrics=self.mechanisms('phantompiranha',damage=damage)
            self.assertEqual(metrics['非相邻或无法定位来源的所填伤害']['value'],str(expected))
            self.assertEqual(metrics['相邻已定位来源的所填伤害']['value'],str(damage))
            self.assertIn('法杖或牧师法术按玩家位置',metrics['非相邻或无法定位来源的所填伤害']['condition'])
        self.assertTrue(any('四舍五入' in r[1] and '八方向相邻' in r[2] for r in self.defenses('phantompiranha')['rows']))

    def test_elemental_profiles_keep_normal_vault_and_newborn_actions_separate(self):
        for name in ('elemental$fireelemental','quest.vault.vaultelemental$fire'):
            metrics=self.mechanisms(name)
            self.assertEqual(metrics['近战命中后点燃概率']['value'],'50')
            self.assertEqual(metrics['远程点燃基础持续参数']['value'],'4')
            self.assertNotIn('火球影响范围',metrics)
        newborn=self.mechanisms('elemental$newbornfireelemental')
        self.assertEqual(newborn['普通敌对形态近战点燃概率']['value'],'0')
        self.assertNotIn('近战命中后点燃概率',newborn)
        self.assertIn('保存落点',newborn['火球准备耗时范围']['condition'])
        frost=self.mechanisms('elemental$frostelemental')
        self.assertEqual(frost['一次冻结处理添加冻伤：干燥／水格']['value'],'3／5')
        self.assertIn('不是首次命中必定冻结',frost['冻伤达到上限后的冻结基础持续']['condition'])
        chaos=self.mechanisms('elemental$chaoselemental')
        self.assertEqual(chaos['混沌远程普通命中检定']['value'],'跳过')
        for name in ('elemental$shockelemental','quest.vault.vaultelemental$shock'):
            for damage,expected in ((0,'0'),(1,'0'),(2,'1'),(6,'2'),(7,'3'),(20,'8'),(25,'10')):
                metrics=self.mechanisms(name,damage=damage)
                self.assertEqual(metrics['所填近战伤害的每个电弧基础伤害']['value'],expected)
            detail=self.detail(name,damage=7)
            field=next(row for row in detail['inputs'] if row['key']=='damage')
            self.assertIn('近战命中效果处理后',field['label'])

    def test_wealth_conditions_scale_pools_and_cap_only_after_limited_drop_counts(self):
        # Mob.lootChance multiplies by 1.2 ** effective bonus; Scorpio chooses
        # uniformly from ten eligible potions after its ordinary drop succeeds.
        for bonus,chance in ((0,.5),(1,.6),(-1,5/12),(10,1)):
            rows=self.loot('scorpio',wealth_bonus=bonus)
            self.assertAlmostEqual(sum(r['probability'] for r in rows),chance,places=6)
            self.assertTrue(all(abs(r['probability']-chance/10)<1e-7 for r in rows))
        self.assertAlmostEqual(sum(r['probability'] for r in self.loot('skeleton',loot_count=1,wealth_bonus=2)),.080016,places=6)
        self.assertAlmostEqual(self.chance('swarm','items.potions.potionofhealing',swarm_generation=1,loot_count=1,wealth_bonus=1),.08,places=6)
        self.assertEqual(self.chance('crab','items.food.mysterymeat',hero_level=12,wealth_bonus=100),0)
        detail=self.detail('scorpio',wealth_bonus=1)
        field=next(r for r in detail['inputs'] if r['key']=='wealth_bonus')
        self.assertEqual((field['value'],field['min'],field['step']),(1,-100,1))
        self.assertIn('不是戒指等级',detail['blocks'][1]['note'])
        self.assertIn('不计算财富额外战利品',detail['blocks'][1]['note'])
        for invalid in (True,1.5,'NaN',101,-101):
            with self.assertRaises(ValueError):self.detail('scorpio',wealth_bonus=invalid)

    def test_wealth_does_not_scale_fixed_extras_or_vault_constant_overrides(self):
        for bonus in (-10,10):
            self.assertEqual(self.chance('causticslime','items.quest.gooblob',wealth_bonus=bonus),1)
            self.assertEqual(self.chance('dm201','items.quest.metalshard',wealth_bonus=bonus),1)
            self.assertEqual(self.chance('rotheart','plants.rotberry$seed',wealth_bonus=bonus),1)
            self.assertAlmostEqual(sum(r['probability'] for r in self.loot('gnollexile',wealth_bonus=bonus)),1)
        for name in ('vaultdm200','vaultgolem','vaultshaman','vaultskeleton'):
            identity='quest.vault.'+name
            self.assertEqual(self.chance(identity,'items.quest.dwarftoken',wealth_bonus=-1),1)
            self.assertNotIn('wealth_bonus',{r['key'] for r in self.detail(identity)['inputs']})
        for name in ('vaultdm100','vaultghoul','vaultelemental$fire'):
            self.assertAlmostEqual(self.chance('quest.vault.'+name,'items.quest.dwarftoken',wealth_bonus=-1),5/6,places=6)

    def test_acidic_keeps_scorpio_attacks_and_ooze_action_order(self):
        for depth,expected in ((5,'1'),(6,'2'),(24,'5'),(25,'6')):
            metrics=self.mechanisms('acidic',depth=depth)
            self.assertEqual(metrics['远程攻击基础伤害']['value'],'30–40')
            self.assertEqual(metrics['攻击命中后施加残废概率']['value'],'50')
            self.assertEqual(metrics['攻击命中后施加淤泥概率']['value'],'100')
            self.assertEqual(metrics['相邻攻击者触发淤泥概率']['value'],'100')
            self.assertEqual(metrics['淤泥初始持续参数']['value'],'20')
            self.assertEqual(metrics['所填等效层数的淤泥单次基础伤害']['value'],expected)
            self.assertIn('第一次仍先结算一次',metrics['水中洗掉淤泥的顺序']['condition'])
        for name in ('goo','fetidrat','causticslime'):
            metrics=self.mechanisms(name,depth=4)
            self.assertEqual(metrics['所填等效层数的淤泥单次基础伤害']['value'],'1（剩余持续参数为偶数时）')
        urls=[r['url'] for r in self.detail('acidic')['provenance']['links']]
        for filename in ('Acidic','Scorpio','Ooze','Cripple','RingOfWealth','Ring'):
            self.assertTrue(any('/'+filename+'.java' in url for url in urls),filename)

    def test_bleeding_parameters_are_distinct_from_first_tick_and_total_damage(self):
        albino=self.mechanisms('albino')
        self.assertEqual(albino['传给流血状态的强度范围']['value'],'2–3')
        self.assertEqual(albino['新流血首次强度范围']['value'],'1–3')
        self.assertIn('伤害必须大于0',albino['命中后施加流血概率']['condition'])
        for name in ('ripperdemon','yogdzewa$yogripper'):
            ripper=self.mechanisms(name)
            self.assertEqual(ripper['命中时传给流血的强度']['value'],'11.25–18.75')
            self.assertEqual(ripper['新流血首次强度范围']['value'],'5.625–18.75')
            self.assertEqual(ripper['新流血首跳基础伤害']['value'],'6–19')
            self.assertIn('不能作为固定总伤害',ripper['新流血首跳基础伤害']['condition'])
            self.assertIn('部分跳跃取消',ripper['跳跃重新设置的冷却']['condition'])

    def test_ooze_and_fetid_gas_do_not_share_probability_or_volume_units(self):
        caustic=self.mechanisms('causticslime');fetid=self.mechanisms('fetidrat')
        self.assertEqual(caustic['攻击命中后施加淤泥概率']['value'],'50')
        self.assertIn('不额外要求',caustic['攻击命中后施加淤泥概率']['condition'])
        self.assertEqual(fetid['攻击命中后施加淤泥概率']['value'],'1/3')
        self.assertEqual(fetid['受攻击时播种恶臭气体体积']['unit'],'体积')
        self.assertIn('每次进入防御',fetid['受攻击时播种恶臭气体体积']['condition'])

    def test_healing_uses_post_armor_attack_values_and_barrier_is_not_additive(self):
        bat=self.mechanisms('bat');succubus=self.mechanisms('succubus')
        self.assertIn('目标护甲已影响',bat['命中后的吸血恢复']['condition'])
        self.assertIn('生命已满则恢复0',bat['正常基础攻击可提供的恢复额度']['condition'])
        self.assertEqual(succubus['魅惑基础持续参数']['value'],'5')
        self.assertIn('任何魅惑状态',succubus['命中已魅惑目标的恢复额度']['condition'])
        self.assertIn('取较大值，不反复累加',succubus['恢复超额的屏障']['condition'])

    def test_rotberry_and_seed_drops_warn_that_burning_skips_normal_death(self):
        heart=self.loot('rotheart')
        seed=next(row for row in heart if row.get('id')=='plants.rotberry$seed')
        self.assertEqual(seed['probability'],1)
        self.assertIn('燃烧伤害',seed['condition']);self.assertIn('无法获得',seed['condition'])
        self.assertTrue(all('燃烧直接摧毁' in row['condition'] for row in self.loot('rotlasher')))
        self.assertEqual(self.mechanisms('rotlasher')['攻击命中后残废基础持续']['value'],'2')
        self.assertIn('5–29',self.mechanisms('rotheart')['受攻击时播种毒气体积']['condition'])

    def test_monk_focus_and_senior_move_reduction_keep_inheritance_and_conditions(self):
        for name,extra in (('monk','0.67'),('senior','2.33'),('dwarfking$dkmonk','0.67')):
            metrics=self.mechanisms(name)
            self.assertEqual(metrics['每次正常移动额外扣除冷却']['value'],extra)
            self.assertIn('未麻痹且未睡眠',metrics['专注时的闪避']['condition'])
            self.assertIn('不是固定6–7次角色行动',metrics['消耗专注后的冷却']['condition'])

    def test_ghoul_links_can_transfer_and_need_not_use_original_partner(self):
        for name in ('ghoul','dwarfking$dkghoul','quest.vault.vaultghoul'):
            metrics=self.mechanisms(name)
            self.assertEqual(metrics['正常复活生命']['value'],'5')
            self.assertIn('不局限原配对',metrics['可继续连接的宿主']['condition'])
            self.assertIn('宿主参与决斗时暂停',metrics['第n次倒地的复活等待']['condition'])

    def test_mining_enemy_attack_and_linked_defense_do_not_use_generic_melee_values(self):
        wisp=self.mechanisms('crystalwisp')
        self.assertEqual(wisp['远程光束基础伤害']['value'],'5–10')
        self.assertEqual(wisp['魔法命中掷骰倍率']['value'],'2')
        guard=self.mechanisms('gnollguard',damage=15)
        self.assertEqual(guard['非相邻目标的长矛基础伤害']['value'],'16–22')
        self.assertEqual(guard['相邻目标基础伤害']['value'],'6–12')
        self.assertEqual(guard['连接爆破手存活时所填伤害']['value'],'3')
        self.assertIn('连接解除后不除4',guard['连接爆破手存活时所填伤害']['condition'])

    def test_mechanism_source_links_include_underlying_state_rules(self):
        for name,sources in (('albino',('Bleeding','Char')),('ripperdemon',('Bleeding','Char')),
                             ('succubus',('Charm','Barrier','ShieldBuff')),('fetidrat',('Ooze','StenchGas')),
                             ('causticslime',('Slime','Ooze')),('senior',('Monk','Char'))):
            urls=[row['url'] for row in self.detail(name)['provenance']['links']]
            for source in sources:
                self.assertTrue(any('/'+source+'.java' in url for url in urls),(name,source))

    def test_every_enemy_has_complete_stats_and_drop_reference(self):
        roster = {identity for group in reference()['bestiary_groups'].values() for identity in group}
        self.assertEqual(len(roster),85)
        self.assertLessEqual(roster, reference()['monsters'].keys())
        self.assertLessEqual(roster, self.values.catalog.entry_index.keys())
        for identity in reference()['monsters']:
            with self.subTest(identity=identity):
                detail = self.values.detail(identity)
                self.assertEqual(detail['blocks'][0]['title'],'常规战斗数值')
                self.assertEqual(len(detail['blocks'][0]['values']),10)
                self.assertEqual(detail['blocks'][1]['title'],'掉落物、数量与概率')
                self.assertTrue(all(r['value'] not in ('None','') for r in detail['blocks'][0]['values']))
                self.assertTrue(any('/items/Generator.java' in r['url'] for r in detail['provenance']['links']))
                self.assertEqual(self.values.catalog.entry_index[identity]['type_label'],'敌人')

    def test_swarm_generation_changes_experience_and_drop_conditions_together(self):
        for generation,experience in ((0,'3'),(1,'0'),(2,'0')):
            for hero in (5,30):
                stats=self.stats('swarm',hero_level=hero,swarm_generation=generation)
                self.assertEqual(stats['基础经验'],experience)
                self.assertEqual(stats['所填等级可获经验'],experience if hero==5 else '0')

    def test_normal_attack_delay_has_inherited_overrides_and_non_attackers(self):
        for name in ('monk','ripperdemon','thief','bandit','dwarfking$dkmonk'):
            self.assertEqual(self.stats(name)['普通攻击基础耗时'],'0.5')
        self.assertEqual(self.stats('rat')['普通攻击基础耗时'],'1')
        self.assertIn('所持武器',self.stats('statue')['普通攻击基础耗时'])
        for name in ('necromancer','demonspawner','yogdzewa','pylon','rotheart'):
            self.assertEqual(self.stats(name)['普通攻击基础耗时'],'不使用普通攻击')

    def test_gas_volumes_and_trickster_combo_branch_probabilities(self):
        dm={v['label']:v['value'] for b in self.detail('dm200')['blocks'] for v in b.get('values',[])}
        self.assertEqual(dm['排气后冷却计数'],'30')
        self.assertEqual(dm['弹道路径每格播种毒气体积'],'20')
        self.assertEqual(dm['弹道终点另播种毒气体积'],'100')
        def combo(before):
            detail=self.detail('gnolltrickster',trickster_combo=before)
            self.assertIn('trickster_combo',{r['key'] for r in detail['inputs']})
            return next(b for b in detail['blocks'] if b['title']=='豺狼诡术师本次命中连击效果')['rows']
        first=combo(0);self.assertEqual(sum(r[1] for r in first),100)
        self.assertEqual([r[2] for r in first],[1]*4)
        self.assertEqual([r[3] for r in first],['不附加中毒或点燃']*2+['中毒基础持续参数 1 回合','中毒基础持续参数 2 回合'])
        fourth=combo(3)
        self.assertEqual([r[3] for r in fourth],['中毒基础持续参数 2 回合','中毒基础持续参数 3 回合','点燃','点燃'])
        self.assertEqual([r[4] for r in fourth],['中毒基础持续参数 '+str(n)+' 回合' for n in (2,3,4,5)])

    def defenses(self, name):
        return next(block for block in self.detail(name)['blocks'] if block['title']=='固有抗性、免疫与防御条件')

    def test_intrinsic_property_immunities_and_effect_specific_resistance(self):
        # Fixed Char.Property / Skeleton / DM100 / Eye / Spinner source rules.
        skeleton=self.defenses('skeleton')
        immune={r[0] for r in skeleton['rows'] if r[1]=='免疫此类效果'}
        self.assertEqual(immune,{'流血','毒气','中毒'})
        dm100={r[0]:r[1] for r in self.defenses('dm100')['rows']}
        self.assertEqual(dm100['雷霆法杖'],'效果系数 ×0.5')
        self.assertEqual(dm100['中毒'],'免疫此类效果')
        self.assertNotIn('解离法杖',dm100)
        eye={r[0]:r[1] for r in self.defenses('eye')['rows']}
        self.assertEqual(eye,{'死亡凝视':'效果系数 ×0.5','解离法杖':'效果系数 ×0.5','解离陷阱':'效果系数 ×0.5'})
        spinner={r[0]:r[1] for r in self.defenses('spinner')['rows']}
        self.assertEqual(spinner['中毒'],'效果系数 ×0.5')
        self.assertEqual(spinner['蛛网'],'免疫此类效果')
        self.assertNotIn('概率',skeleton['columns'])
        self.assertIn('不是触发概率',skeleton['note'])
        self.assertEqual(self.defenses('rat')['rows'],[])

    def test_piranha_environmental_copy_preserves_electricity_and_freezing_exceptions(self):
        for name in ('piranha','phantompiranha'):
            effects=reference()['monsters']['actors.mobs.'+name]['defenses']['immunities']
            self.assertIn('actors.blobs.blizzard',effects)
            self.assertIn('actors.blobs.corrosivegas',effects)
            self.assertIn('actors.buffs.burning',effects)
            self.assertNotIn('actors.blobs.electricity',effects)
            self.assertNotIn('actors.blobs.freezing',effects)
            self.assertTrue(any('BlobImmunity.java' in r['url'] for r in self.detail(name)['provenance']['links']))
        base=self.defenses('piranha')['rows'];phantom=self.defenses('phantompiranha')['rows']
        self.assertEqual(phantom[:len(base)],base)
        self.assertEqual(len(phantom),len(base)+1)
        self.assertIn('非相邻或无法定位',phantom[-1][0])

    def test_phase_and_source_dependent_defenses_are_not_flattened_to_always_immune(self):
        dm300=self.defenses('dm300')
        self.assertTrue(any(r[0]=='所有伤害' and '超载期间' in r[2] for r in dm300['rows']))
        king=self.defenses('dwarfking')
        doom=next(r for r in king['rows'] if r[0]=='末日伤害加成')
        self.assertIn('已有末日状态',doom[2])
        self.assertIn('不是全程免疫',doom[2])
        geomancer=self.defenses('gnollgeomancer')
        self.assertTrue(any('所连接' in r[2] for r in geomancer['rows']))
        self.assertTrue(any('镐子只绕过岩石护甲' in r[2] for r in geomancer['rows']))
        fist=self.defenses('yogfist$burningfist')
        self.assertTrue(any(r[0]=='所有伤害' and '4格以内' in r[2] for r in fist['rows']))

    def test_elemental_weakness_and_vault_lightning_exception_are_conditioned(self):
        fire=self.defenses('elemental$fireelemental')
        self.assertIn(['冻结／冻伤状态施加','转为30–36 HP基础伤害',
                       '不保留该状态；基础范围按此种普通最大生命计算，临时最大生命和其他承伤处理另计'],fire['rows'])
        newborn=self.defenses('elemental$newbornfireelemental')
        self.assertTrue(any(r[1]=='转为30–36 HP基础伤害' for r in newborn['rows']))
        boss=self.defenses('quest.vault.vaultbosselemental')
        lightning=[r for r in boss['rows'] if r[0]=='雷霆法杖']
        self.assertEqual(len(lightning),1)
        self.assertEqual(lightning[0][1],'效果系数 ×1')
        self.assertIn('仅电光形态',lightning[0][2])
        self.assertTrue(any(r[0]=='燃烧' and r[2]=='火焰形态' for r in boss['rows']))
        self.assertTrue(any(r[0]=='冻结' and r[2]=='冰霜形态' for r in boss['rows']))

    def test_every_reference_defense_effect_has_a_readable_label(self):
        for identity in reference()['monsters']:
            detail=self.values.detail(identity)
            section=next(block for block in detail['blocks'] if block['title']=='固有抗性、免疫与防御条件')
            for row in section['rows']:
                self.assertEqual(len(row),3)
                self.assertNotIn('%s',row[0])
                self.assertNotIn('.class',row[0])
                self.assertTrue(all(str(cell).strip() for cell in row))

    def test_bestiary_variants_do_not_fall_back_to_state_effects_or_parent_drops(self):
        for color in ('red','blue','purple'):
            key='actors.mobs.shaman$'+color+'shaman'
            self.assertIn(key, {row['id'] for row in self.values.catalog.search('萨满')['entries']})
            self.assertAlmostEqual(sum(row['probability'] for row in self.loot('shaman$'+color+'shaman',loot_count=1)),.01)
        self.assertEqual(self.stats('dwarfking$dkwarlock')['基础经验'],'0')
        self.assertEqual(sum(row['probability'] for row in self.loot('dwarfking$dkwarlock')),0)
        self.assertEqual(self.chance('quest.vault.vaultelemental$fire','items.quest.dwarftoken'),1)

    def test_enemy_hazards_are_not_presented_as_damageable_ordinary_mobs(self):
        self.assertEqual(self.stats('pylon')['初始最大生命'],'50')
        self.assertEqual(self.stats('pylon')['基础伤害范围'],'不使用普通攻击')
        self.assertEqual(self.stats('npcs.vaultlaser')['初始最大生命'],'不可破坏')
        sentry=self.values.detail('levels.rooms.special.sentryroom$sentry',{'depth':12})
        stats={row['label']:row['value'] for row in sentry['blocks'][0]['values']}
        self.assertEqual(stats['基础命中'],'44')
        self.assertEqual(stats['基础闪避'],'无限闪避')

    def test_gnoll_exile_exposes_concrete_per_draw_probabilities(self):
        loot=self.loot('gnollexile',depth=1)
        self.assertTrue(all(row.get('id') for row in loot))
        self.assertAlmostEqual(sum(row['probability'] for row in loot),1)
        gold=[row for row in loot if row['id']=='items.gold']
        self.assertEqual(gold[0]['quantity'],'40–80')
        self.assertAlmostEqual(gold[0]['probability'],2/7)

    def test_pylon_damage_compression_matches_source_thresholds(self):
        for damage,expected in [(14,14),(15,15),(17,16),(20,17),(24,18),(29,19),(36,20)]:
            detail=self.detail('pylon',damage=damage)
            ability={row['label']:row['value'] for row in detail['blocks'][2]['values']}
            self.assertEqual(ability['所填伤害压缩后承受'],str(expected))

    def test_version_mismatch_does_not_apply_current_enemy_rules(self):
        from types import SimpleNamespace
        self.assertIsNone(monster_record(SimpleNamespace(data={'version':'4.0.1','commit':'old'}),'actors.mobs.rat'))

    def test_inherited_bandit_stats_and_elemental_enemy_branch(self):
        bandit = self.stats('bandit')
        self.assertEqual([bandit[k] for k in ('初始最大生命','基础闪避','基础经验','基础减伤范围')],['20','12','5','0–3'])
        fire = self.stats('elemental$fireelemental')
        self.assertEqual([fire[k] for k in ('初始最大生命','基础伤害范围','基础命中','基础减伤范围')],['60','20–25','25','0–5'])
        newborn = self.stats('elemental$newbornfireelemental')
        self.assertEqual([newborn[k] for k in ('基础伤害范围','基础命中')],['10–12','15'])

    def test_barkskin_is_excluded_without_losing_ordinary_armor(self):
        self.assertEqual(self.stats('rat')['基础减伤范围'],'0–1')
        self.assertEqual(self.stats('bat')['基础减伤范围'],'0–4')
        self.assertEqual(self.stats('armoredbrute')['基础减伤范围'],'4–12')

    def test_experience_and_regular_loot_level_limits_are_distinct(self):
        # Rat maxLvl=5; crab maxLvl=9 and loot gate maxLvl+2.
        self.assertEqual(self.stats('rat',hero_level=6)['所填等级可获经验'],'0')
        self.assertEqual(self.stats('rat',hero_level=5)['所填等级可获经验'],'1')
        self.assertAlmostEqual(self.chance('crab','items.food.mysterymeat',hero_level=11),.167)
        self.assertEqual(self.chance('crab','items.food.mysterymeat',hero_level=12),0)
        self.assertEqual(self.stats('crystalguardian')['基础经验'],'0')
        self.assertEqual(sum(r['probability'] for r in self.loot('fungalspinner')),0)

    def test_normal_boss_health_is_not_lost_to_challenge_initializer(self):
        for name,health in [('goo','100'),('tengu','200'),('dm300','300'),('dwarfking','300')]:
            self.assertEqual(self.stats(name)['初始最大生命'],health)

    def test_generation_depth_changes_spawned_enemy_stats(self):
        self.assertEqual(self.stats('piranha',depth=12)['初始最大生命'],'70')
        self.assertEqual(self.stats('piranha',depth=12)['基础伤害范围'],'12–28')
        self.assertEqual(self.stats('wraith',depth=12)['基础闪避'],'110')
        self.assertEqual(self.stats('goldenmimic',depth=10)['初始最大生命'],'84')
        self.assertEqual(self.stats('armoredstatue',depth=12)['初始最大生命'],'150')

    def test_mimic_ambush_damage_and_accuracy_are_separate_from_awake_attacks(self):
        # Official Mimic.damageRoll neutral branch is exactly2+2*level;
        # Ebony doubles that branch; Golden rounds depth*1.33f first;
        # Crystal temporarily switches alignment and keeps ordinary damage.
        expected={1:('4','4','8','2–4'),10:('22','28','44','11–22'),24:('50','66','100','25–50')}
        for depth,damages in expected.items():
            for name,damage in zip(('mimic','goldenmimic','ebonymimic','crystalmimic'),damages):
                with self.subTest(depth=depth,name=name):
                    detail=self.detail(name,depth=depth)
                    special=next(row for row in detail['blocks'] if row['title']=='特殊攻击与机制')
                    metrics={row['label']:row for row in special['values']}
                    self.assertEqual(metrics['伪装首击基础伤害']['value'],damage)
                    self.assertEqual(metrics['伪装首击命中值']['value'],'无限命中')
                    self.assertIn('目标未隐形',metrics['伪装首击命中值']['condition'])
                    self.assertIn('目标护甲',metrics['伪装首击基础伤害']['condition'])
                    self.assertEqual(len(detail['blocks'][0]['values']),10)

    def test_goo_half_health_and_pumped_attack_have_separate_source_values(self):
        detail=self.detail('goo')
        stages=next(row for row in detail['blocks'] if row['title']=='粘咕生命阶段与蓄力攻击')
        self.assertEqual(stages['rows'],[['高于最大生命的50%','1–8','3–24','10','20','8'],
                                         ['不超过最大生命的50%','1–12','3–36','15','30','12']])
        special=next(row for row in detail['blocks'] if row['title']=='特殊攻击与机制')
        values={row['label']:row for row in special['values']}
        self.assertEqual([values[label]['value'] for label in ('高血量选择开始蓄力概率','半血选择开始蓄力概率','正常蓄力准备','蓄力攻击最大距离','攻击命中后施加淤泥概率','正常水中每次行动恢复')],['20','50','2','2','1/3','1'])
        self.assertIn('不是每回合',values['高血量选择开始蓄力概率']['condition'])
        self.assertIn('双方方向',values['蓄力攻击最大距离']['condition'])
        self.assertIn('未命中不会保留',special['note'])
        self.assertEqual(detail['blocks'][0]['values'][2]['value'],'1–8')

    def test_great_crab_full_block_is_conditional_and_not_zero_evasion_guidance(self):
        detail=self.detail('greatcrab')
        special=next(row for row in detail['blocks'] if row['title']=='特殊攻击与机制')
        values={row['label']:row for row in special['values']}
        self.assertEqual(values['格挡当前目标时的闪避']['value'],'无限闪避')
        for condition in ('未睡眠','未麻痹','非隐形','无限命中'):
            self.assertIn(condition,values['格挡当前目标时的闪避']['condition'])
        self.assertEqual(values['未满足格挡条件时的基础闪避']['value'],'0')
        self.assertEqual(values['格挡法杖与牧师法术的直接伤害']['value'],'0')
        self.assertIn('附加和环境效果另计',values['格挡法杖与牧师法术的直接伤害']['condition'])
        self.assertIn('第3次',values['追近尝试中的原地停顿']['value'])

    def test_eye_gaze_and_dm100_shock_include_damage_timing_and_magic_conditions(self):
        # Fixed official4.0.2 Eye.deathGaze, Eye.doAttack, DM100.doAttack
        # and Char.hit: independently specified source values, not RNG prediction.
        expected = {
            'eye': ('死亡凝视基础伤害','30–50','死亡凝视发射耗时'),
            'dm100': ('远程电击基础伤害','3–10','远程电击耗时'),
        }
        for name,(label,damage,time_label) in expected.items():
            with self.subTest(name=name):
                detail=self.detail(name)
                special=next(row for row in detail['blocks'] if row['title']=='特殊攻击与机制')
                metrics={row['label']:row for row in special['values']}
                self.assertEqual(metrics[label]['value'],damage)
                self.assertEqual(metrics[time_label]['value'],'1')
                self.assertEqual(metrics['魔法命中掷骰倍率']['value'],'2')
                self.assertIn('不是必中',metrics['魔法命中掷骰倍率']['condition'])
                self.assertNotIn('特殊技能伤害另列',detail['blocks'][0]['values'][2]['condition'])
        eye=next(row for row in self.detail('eye')['blocks'] if row['title']=='特殊攻击与机制')
        metrics={row['label']:row for row in eye['values']}
        self.assertEqual(metrics['死亡凝视蓄力耗时']['value'],'2')
        self.assertEqual(metrics['发射后冷却计数']['value'],'4–6')
        self.assertEqual(metrics['发射后冷却计数']['unit'],'次自身行动')
        self.assertIn('不是固定的角色回合数',metrics['发射后冷却计数']['condition'])
        self.assertIn('实墙',eye['note'])
        self.assertIn('重新瞄准',eye['note'])
        shock=next(row for row in self.detail('dm100')['blocks'] if row['title']=='特殊攻击与机制')
        self.assertIn('非相邻',shock['values'][0]['condition'])
        self.assertIn('弹道被阻挡',shock['values'][0]['condition'])

    def test_eye_charged_damage_division_keeps_integer_thresholds(self):
        for damage,expected in [(0,0),(3,0),(4,1),(7,1),(8,2),(19,4),(20,5),(99999,24999)]:
            with self.subTest(damage=damage):
                detail=self.detail('eye',damage=damage)
                special=next(row for row in detail['blocks'] if row['title']=='特殊攻击与机制')
                metrics={row['label']:row for row in special['values']}
                metric=metrics['蓄力时所填伤害缩减后']
                self.assertEqual(metric['value'],str(expected))
                self.assertIn('之后仍受抗性',metric['condition'])
                self.assertIn('damage',[row['key'] for row in detail['inputs']])

    def test_common_enemy_attack_branches_expose_death_rage_and_status_values(self):
        expected={
            'warlock':{'远程暗影弹基础伤害':'12–18','远程暗影弹耗时':'1','魔法命中掷骰倍率':'2','命中角色后施加降级概率':'50','降级基础持续':'30'},
            'skeleton':{'死亡碎骨爆炸基础伤害':'6–12','碎骨爆炸护甲减伤掷骰':'2'},
            'necromancer$necroskeleton':{'死亡碎骨爆炸基础伤害':'6–12','碎骨爆炸护甲减伤掷骰':'2'},
            'brute':{'濒死狂暴基础伤害':'15–40','正常濒死狂暴初始护盾':'24','狂暴护盾每次自然衰减':'4','狂暴护盾自然衰减间隔':'1'},
            'armoredbrute':{'濒死狂暴基础伤害':'15–40','正常濒死狂暴初始护盾':'21','狂暴护盾每次自然衰减':'1','狂暴护盾自然衰减间隔':'3'},
            'spinner':{'攻击命中后施加中毒概率':'50','新中毒基础持续':'7–8'},
            'scorpio':{'远程攻击基础伤害':'30–40','攻击命中后施加残废概率':'50','残废基础持续':'10'},
        }
        for name,vector in expected.items():
            with self.subTest(name=name):
                special=next(row for row in self.detail(name)['blocks'] if row['title']=='特殊攻击与机制')
                metrics={row['label']:row['value'] for row in special['values']}
                self.assertEqual(metrics,vector)
        for name,source in [('warlock','Degrade.java'),('scorpio','Cripple.java'),('spinner','Poison.java')]:
            self.assertTrue(any(source in row['url'] for row in self.detail(name)['provenance']['links']))
        self.assertIn('非坠落',self.detail('skeleton')['blocks'][2]['values'][0]['condition'])
        self.assertIn('不是7–8点总伤害',self.detail('spinner')['blocks'][2]['values'][1]['condition'])

    def test_yog_fists_separate_normal_ranged_attacks_from_melee_and_cooldown(self):
        # Pinned YogFist.doAttack/canAttack and the two no-op cooldown overrides.
        for subtype in ('burning','soiled','rotting','rusted','bright','dark'):
            with self.subTest(subtype=subtype):
                name='yogfist$'+subtype+'fist'
                detail=self.detail(name)
                metrics=self.mechanisms(name)
                self.assertEqual(metrics['初始远程冷却']['value'],'0')
                self.assertEqual(metrics['远程施放耗时']['value'],'1')
                light_dark=subtype in ('bright','dark')
                self.assertEqual(metrics['远程施放后添加冷却']['value'],'0' if light_dark else '8–12')
                self.assertEqual(self.stats(name)['基础伤害范围'],'22–44' if subtype=='rusted' else '18–36')
                self.assertIn('魔法弹道',metrics['初始远程冷却']['condition'])
                if light_dark:
                    self.assertIn('相邻时',metrics['远程施放后添加冷却']['condition'])
                else:
                    self.assertIn('未麻痹',metrics['远程施放后添加冷却']['condition'])
                    self.assertIn('浮点值',metrics['远程施放后添加冷却']['condition'])
                self.assertIn('4格以内',str(self.defenses(name)['rows']))
                self.assertIn('正常难度',detail['blocks'][2]['note'])

    def test_bright_and_dark_fists_use_magic_damage_and_separate_half_health_events(self):
        bright=self.mechanisms('yogfist$brightfist')
        dark=self.mechanisms('yogfist$darkfist')
        for metrics,label in ((bright,'远程光束基础伤害'),(dark,'远程暗影弹基础伤害')):
            self.assertEqual(metrics[label]['value'],'10–20')
            self.assertIn('倍率×2',metrics[label]['condition'])
            self.assertIn('不是必中',metrics[label]['condition'])
            self.assertEqual(metrics['半血传送触发线']['value'],'150')
            self.assertIn('仍存活',metrics['半血传送触发线']['condition'])
        self.assertEqual([bright[label]['value'] for label in ('远程命中后失明基础持续','半血传送时失明基础持续','死亡时失明基础持续')],['5','15','30'])
        self.assertEqual(dark['远程命中后削减光亮持续']['value'],'50')
        self.assertIn('仅目标已有光亮',dark['远程命中后削减光亮持续']['condition'])
        self.assertEqual(dark['半血传送或死亡时的光亮']['value'],'移除玩家光亮状态')
        self.assertIn('直接致死',str(self.defenses('yogfist$brightfist')['rows']))

    def test_burning_and_soiled_fists_expose_environment_and_status_parameters(self):
        burning=self.mechanisms('yogfist$burningfist',depth=25)
        self.assertEqual(burning['远程点燃基础持续参数']['value'],'8')
        self.assertEqual(burning['所填层数的燃烧单次基础伤害']['value'],'1–9')
        self.assertEqual(burning['周围火焰补充后的最低体积']['value'],'4')
        self.assertEqual(burning['周围火焰补充后的最低体积']['unit'],'体积')
        self.assertIn('不直接点燃',burning['远程目标格有水时']['value'])
        self.assertIn('不进行普通命中检定',burning['远程点燃基础持续参数']['condition'])
        soiled=self.mechanisms('yogfist$soiledfist')
        self.assertEqual(soiled['远程扎根基础持续参数']['value'],'3')
        self.assertIn('飞行目标不能扎根',soiled['远程扎根基础持续参数']['condition'])
        self.assertEqual(soiled['远程每个可播草格变为茂草概率']['value'],'20')
        self.assertIn('不论扎根是否命中',soiled['远程播草范围']['condition'])
        self.assertIn('超过4格',soiled['远程播草范围']['condition'])
        self.assertIn('可重复',soiled['每次自身行动培育茂草的尝试']['condition'])
        self.assertIn('仍可被点燃',str(self.defenses('yogfist$soiledfist')['rows']))

    def test_soiled_fist_grass_reduction_keeps_java_rounding_and_input_stage(self):
        # YogFist.SoiledFist.damage counts NEIGHBOURS9, including its own tile.
        # 6 grass cells yield zero; 7..9 can produce a negative, rejected input.
        cases=((20,0,20),(20,1,17),(20,3,10),(20,5,3),(20,6,0),
               (20,7,-3),(20,9,-10),(1,3,1),(1,9,0),(3,7,0),
               (99999,1,83333),(99999,9,-49999))
        for damage,grass_cells,expected in cases:
            with self.subTest(damage=damage,grass_cells=grass_cells):
                detail=self.detail('yogfist$soiledfist',damage=damage,grass_cells=grass_cells)
                metric=self.mechanisms('yogfist$soiledfist',damage=damage,grass_cells=grass_cells)['所填草丛减伤后的输入']
                self.assertEqual(metric['value'],str(expected))
                self.assertEqual(metric['unit'],'HP输入')
                self.assertIn('不是最终HP损失',metric['condition'])
                inputs={row['key']:row for row in detail['inputs']}
                self.assertEqual(inputs['grass_cells']['max'],9)
                self.assertEqual(inputs['damage']['label'],'进入草丛减伤分支的整数伤害')
        for invalid in (-1,10,True,1.5):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.detail('yogfist$soiledfist',grass_cells=invalid)

    def test_rotting_fist_bleeding_input_is_not_instant_or_total_damage(self):
        # Bleeding.set first samples [input/2,input], then act rounds and decays.
        # These independent source cases include .3/.6 and .9/1.8 boundaries.
        cases=((0,'0','0','0'),(1,'0.6','0.3–0.6','0–1'),
               (3,'1.8','0.9–1.8','1–2'),(20,'12','6–12','6–12'))
        for damage,parameter,strength,first_hit in cases:
            with self.subTest(damage=damage):
                metrics=self.mechanisms('yogfist$rottingfist',damage=damage)
                self.assertEqual(metrics['所填伤害传给流血的强度参数']['value'],parameter)
                self.assertEqual(metrics['所填伤害传给流血的强度参数']['unit'],'强度参数')
                self.assertEqual(metrics['新流血首次强度范围']['value'],strength)
                self.assertEqual(metrics['新流血首跳基础伤害']['value'],first_hit)
                self.assertIn('已有流血取更强值',metrics['新流血首次强度范围']['condition'])
                self.assertIn('后续每跳重新随机衰减',metrics['新流血首跳基础伤害']['condition'])
        detail=self.detail('yogfist$rottingfist')
        self.assertEqual(next(row for row in detail['inputs'] if row['key']=='damage')['label'],'来源抗性结算并四舍五入后的整数伤害')
        metrics=self.mechanisms('yogfist$rottingfist',depth=25)
        self.assertEqual(metrics['正常水中每次自身行动恢复']['value'],'6')
        self.assertIn('恢复不超过缺失生命',metrics['正常水中每次自身行动恢复']['condition'])
        self.assertEqual(metrics['远程播种毒气体积']['value'],'100')
        self.assertEqual(metrics['远程播种毒气体积']['unit'],'体积')
        self.assertEqual(metrics['所填层数的毒气单次基础伤害']['value'],'6')
        self.assertEqual(metrics['近战命中后施加淤泥概率']['value'],'50')
        self.assertEqual(metrics['淤泥初始持续参数']['value'],'20')
        self.assertEqual(metrics['所填等效层数的淤泥单次基础伤害']['value'],'6')
        self.assertIn('无镰刀收割标记',metrics['受伤转流血']['condition'])

    def test_rusted_fist_deferred_pool_and_remote_cripple_keep_their_stages(self):
        metrics=self.mechanisms('yogfist$rustedfist')
        self.assertEqual(metrics['远程残废基础持续参数']['value'],'4')
        self.assertIn('不进行普通命中检定',metrics['远程残废基础持续参数']['condition'])
        self.assertEqual(metrics['承伤转为延迟池的额度']['unit'],'伤害池参数')
        self.assertEqual(metrics['新延迟池首次伤害前等待']['value'],'1')
        self.assertEqual(metrics['延迟状态后续行动间隔']['value'],'1')
        self.assertEqual(metrics['延迟池每次基础伤害']['value'],'max(1, ⌊当前池×0.1⌋)')
        self.assertEqual(metrics['延迟池每次基础伤害']['unit'],'HP输入')
        self.assertIn('实际HP损失受后续承伤处理影响',metrics['延迟池每次基础伤害']['condition'])
        self.assertIn('不再次入池',str(self.defenses('yogfist$rustedfist')['rows']))
        for subtype in ('burning','soiled','rotting','rusted','bright','dark'):
            inputs={row['key'] for row in self.detail('yogfist$'+subtype+'fist')['inputs']}
            self.assertEqual('grass_cells' in inputs,subtype=='soiled')
            self.assertEqual('damage' in inputs,subtype in ('soiled','rotting'))
            self.assertEqual('depth' in inputs,subtype in ('burning','rotting'))

    def test_count_decay_and_swarm_generation_are_evaluated(self):
        healing = 'items.potions.potionofhealing'
        self.assertAlmostEqual(self.chance('bat',healing,loot_count=1),.1667*6/7)
        self.assertEqual(self.chance('bat',healing,loot_count=7),0)
        self.assertAlmostEqual(self.chance('swarm',healing,loot_count=1,swarm_generation=2),2/45)
        self.assertAlmostEqual(sum(r['probability'] for r in self.loot('skeleton',loot_count=2)),.1667/9)

    def test_warlock_strict_greater_comparison_excludes_zero_roll(self):
        # Random.Int(3)==0 AND Random.Int(8)>count, with a 50% loot roll.
        # At count=0 only 1..7 pass, not 0..7.
        item='items.potions.potionofhealing'
        self.assertAlmostEqual(self.chance('warlock',item),7/48)
        self.assertAlmostEqual(self.chance('warlock',item,loot_count=1),1/8)
        self.assertEqual(self.chance('warlock',item,loot_count=7),0)
        self.assertAlmostEqual(sum(r['probability'] for r in self.loot('warlock',loot_count=7)),.5)

    def test_scorpio_and_succubus_use_uniform_excluded_pools(self):
        scorpio=self.loot('scorpio')
        self.assertEqual(len(scorpio),10)
        self.assertTrue(all(abs(r['probability']-.05)<1e-12 for r in scorpio))
        self.assertNotIn('items.potions.potionofhealing',{r['id'] for r in scorpio})
        succubus=self.loot('succubus')
        self.assertEqual(len(succubus),10)
        self.assertTrue(all(abs(r['probability']-.033)<1e-12 for r in succubus))

    def test_boss_quantity_distribution_and_fixed_rewards_bypass_regular_gate(self):
        goo=self.loot('goo',hero_level=30)
        blobs=[r for r in goo if r.get('id')=='items.quest.gooblob']
        self.assertEqual([(r['quantity'],r['probability']) for r in blobs],[(2,.6),(3,.3),(4,.1)])
        self.assertEqual(self.chance('goo','items.keys.wornkey',hero_level=30),1)
        self.assertEqual(self.chance('spectralnecromancer','items.scrolls.scrollofremovecurse',hero_level=17),0)

    def test_invalid_condition_inputs_are_rejected(self):
        for key,value in [('loot_count',-1),('loot_count',True),('swarm_generation',1.5),('depth',0)]:
            with self.subTest(key=key,value=value), self.assertRaises(ValueError):
                self.detail('swarm',**{key:value})

    def test_exotic_crystals_splits_class_loot_without_increasing_success_chance(self):
        healing='items.potions.potionofhealing';shielding='items.potions.exotic.potionofshielding'
        for level,fraction in ((-1,0),(0,.2),(1,.4),(2,.6),(3,.8)):
            rows=self.loot('bat',exotic_crystals=level,loot_count=1,wealth_bonus=1)
            total=.1667*6/7*1.2
            self.assertAlmostEqual(sum(r['probability'] for r in rows),total,places=7)
            self.assertAlmostEqual(sum(r['probability'] for r in rows if r['id']==healing),total*(1-fraction),places=7)
            self.assertAlmostEqual(sum(r['probability'] for r in rows if r['id']==shielding),total*fraction,places=7)
        for name in ('bat','necromancer','spectralnecromancer','swarm','demonspawner',
                     'elemental$fireelemental','elemental$frostelemental','elemental$shockelemental','elemental$chaoselemental'):
            self.assertIn('exotic_crystals',{r['key'] for r in self.detail(name)['inputs']})
        self.assertEqual(self.chance('bat',shielding,exotic_crystals=3,loot_count=7),0)
        self.assertEqual(self.chance('bat',shielding,exotic_crystals=3,hero_level=30),0)
        for name in ('warlock','scorpio','succubus','dm100','acidic','quest.vault.vaultelemental$fire'):
            self.assertEqual(self.loot(name),self.loot(name,exotic_crystals=3))
            self.assertNotIn('exotic_crystals',{r['key'] for r in self.detail(name)['inputs']})
        for value in (-2,4,1.5,True):
            with self.assertRaises(ValueError):self.detail('bat',exotic_crystals=value)

    def test_newborn_embers_remains_fixed_enemy_reward_above_loot_gate(self):
        for hero in (1,30):
            for wealth,exotic in ((-10,-1),(100,3)):
                rows=self.loot('elemental$newbornfireelemental',hero_level=hero,wealth_bonus=wealth,exotic_crystals=exotic)
                embers=next(row for row in rows if row['id']=='items.quest.embers')
                self.assertEqual((embers['quantity'],embers['probability']),(1,1))
                self.assertIn('友方召唤体不提供',embers['condition'])
        self.assertNotIn('items.quest.embers',{r['id'] for r in self.loot('elemental$fireelemental')})


if __name__ == '__main__':
    unittest.main()
