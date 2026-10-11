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

    def test_phantom_piranha_source_distance_and_java_half_rounding(self):
        for damage,expected in ((0,0),(1,1),(2,1),(11,6),(20,10),(25,13)):
            metrics=self.mechanisms('phantompiranha',damage=damage)
            self.assertEqual(metrics['非相邻或无法定位来源的所填伤害']['value'],str(expected))
            self.assertEqual(metrics['相邻已定位来源的所填伤害']['value'],str(damage))
            self.assertIn('法杖或牧师法术按玩家位置',metrics['非相邻或无法定位来源的所填伤害']['condition'])
        self.assertTrue(any('四舍五入' in r[1] and '八方向相邻' in r[2] for r in self.defenses('phantompiranha')['rows']))

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


if __name__ == '__main__':
    unittest.main()
