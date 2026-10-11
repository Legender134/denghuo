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

    def test_every_enemy_has_complete_stats_and_drop_reference(self):
        roster = {identity for group in reference()['bestiary_groups'].values() for identity in group}
        self.assertEqual(len(roster),85)
        self.assertLessEqual(roster, reference()['monsters'].keys())
        self.assertLessEqual(roster, self.values.catalog.entry_index.keys())
        for identity in reference()['monsters']:
            with self.subTest(identity=identity):
                detail = self.values.detail(identity)
                self.assertEqual(detail['blocks'][0]['title'],'常规战斗数值')
                self.assertEqual(len(detail['blocks'][0]['values']),9)
                self.assertEqual(detail['blocks'][1]['title'],'掉落物、数量与概率')
                self.assertTrue(all(r['value'] not in ('None','') for r in detail['blocks'][0]['values']))
                self.assertTrue(any('/items/Generator.java' in r['url'] for r in detail['provenance']['links']))
                self.assertEqual(self.values.catalog.entry_index[identity]['type_label'],'敌人')

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
                    self.assertEqual(len(detail['blocks'][0]['values']),9)

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
