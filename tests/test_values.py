import json
import unittest

from companion.engine import Catalog
from companion.rules import NumericRules
from companion.values import PlayerValues, integer_parameters


class PlayerValuesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog=Catalog()
        cls.values=PlayerValues(NumericRules(cls.catalog))

    def detail(self, identity, **parameters):
        return self.values.detail(identity, parameters)

    def metrics(self, identity, **parameters):
        return {v['label']:v['value'] for b in self.detail(identity,**parameters)['blocks'] for v in b.get('values',[])}

    def test_every_entry_opens_without_implementation_text(self):
        for entry in self.catalog.entries:
            with self.subTest(entry=entry['id']):
                result=self.detail(entry['id'])
                visible=json.dumps(result['blocks'],ensure_ascii=False)
                for forbidden in ('源码','Random.','Math.','return ','buffedLvl','getBuffedBonus','Java','代码','完整规则','floor('):
                    self.assertNotIn(forbidden,visible)
                self.assertNotIn('sections',result)
                self.assertNotIn('source',result)

    def test_healing_pool_and_actual_health_are_separate(self):
        metrics=self.metrics('items.potions.potionofhealing',max_hp=100,hp=10,hero_level=12)
        self.assertEqual(metrics['治疗池总量'],'94')
        self.assertEqual(metrics['最终实际恢复'],'90')
        self.assertEqual(metrics['首次恢复'],'24')
        self.assertEqual(metrics['治疗池耗尽'],'15')
        self.assertEqual(metrics['药水恐惧挑战毒强度'],'10')
        schedule=next(b['rows'] for b in self.detail('items.potions.potionofhealing',max_hp=100,hp=10)['blocks'] if b['title']=='每回合恢复明细')
        self.assertEqual(schedule[0],['1','24','24','34','70'])
        self.assertEqual(schedule[-1][3:],['100','0'])
        self.assertEqual(sum(int(r[2]) for r in schedule),90)
        full=self.metrics('items.potions.potionofhealing',max_hp=100,hp=100)
        self.assertEqual(full['最终实际恢复'],'0')

    def test_upgrade_risks_are_before_upgrade_with_separate_branches(self):
        for level,chance in ((3,'0'),(4,'10'),(5,'20'),(6,'40'),(7,'80'),(8,'100'),(100,'100')):
            with self.subTest(level=level):
                metrics=self.metrics('items.scrolls.scrollofupgrade',level=level)
                self.assertEqual(metrics['普通附魔 / 刻印消失'],chance)
                self.assertEqual(metrics['诅咒附魔 / 刻印移除'],'33.3333')
        self.assertEqual(self.metrics('items.scrolls.scrollofupgrade',level=6)['硬化保护消失'],'10')
        self.assertEqual(self.metrics('items.scrolls.scrollofupgrade',level=6)['无附魔 / 刻印时硬化保护消失'],'0')
        hardening=next(v for b in self.detail('items.scrolls.scrollofupgrade',level=6)['blocks'] for v in b.get('values',[]) if v['label']=='硬化保护消失')
        self.assertIn('有附魔或刻印',hardening['condition'])
        blocks=self.detail('items.scrolls.scrollofupgrade')['blocks']
        metamorphed=next(b for b in blocks if b['title'].startswith('非战士蜕变'))
        self.assertEqual(metamorphed['rows'][2],['+6','40','40','0'])

    def test_combo_shows_reset_and_pause_conditions(self):
        metrics=self.metrics('actors.buffs.combo')
        self.assertEqual(metrics['每次命中后的最低保持时间'],'5')
        self.assertEqual(metrics['击杀后基础保持时间'],'15')
        blocks=self.detail('actors.buffs.combo')['blocks']
        self.assertEqual(next(b for b in blocks if b['title'].startswith('连斩'))['rows'][-1],['3','60'])

    def test_equipment_comparison_counts_strength_mastery_and_speed(self):
        from companion.values_decisions import compare_equipment
        result=compare_equipment(self.values,{'id_a':'items.weapon.melee.wornshortsword',
            'id_b':'items.weapon.melee.shortsword','strength':'10','level_a':'0','level_b':'0',
            'augment_a':'SPEED','mastery_b':'1'})
        rows={r['label']:r for r in result['rows']}
        self.assertEqual(rows['最高基础伤害']['values'],['7','8','15','18'])
        self.assertEqual(rows['力量需求']['values'],['10','9','10','9'])
        self.assertEqual(rows['力量缺口']['values'],['0','0','0','0'])
        self.assertEqual(rows['攻击耗时']['values'][0],'0.666667')
        result=compare_equipment(self.values,{'id_a':'items.weapon.melee.wornshortsword',
            'id_b':'items.weapon.melee.shortsword','strength':'10'})
        self.assertEqual(result['choices'][1]['current']['攻击耗时'],'1.44')

    def test_comparison_refuses_unrelated_types_and_special_missing_values(self):
        from companion.values_decisions import compare_equipment
        for identity in ('items.potions.potionofhealing','items.armor.clotharmor','items.weapon.melee.shortsword.ability'):
            with self.subTest(identity=identity),self.assertRaises(ValueError):
                compare_equipment(self.values,{'id_a':'items.weapon.melee.wornshortsword','id_b':identity})

    def test_speed_augmentation_uses_game_rounding_at_half_boundaries(self):
        from companion.game_math import augmented_damage
        from companion.values_decisions import compare_equipment
        for damage, expected in ((45,32),(85,60),(165,116),(15,11),(12,8)):
            self.assertEqual(augmented_damage(damage,.7),expected)
        result=compare_equipment(self.values,{'id_a':'items.weapon.melee.longsword','id_b':'items.weapon.melee.shortsword',
            'level_a':'4','level_b':'10','strength':'20','augment_a':'SPEED','augment_b':'SPEED'})
        for choice in result['choices']:
            self.assertEqual(choice['current']['最高基础伤害'],'32')
        block=next(b for b in self.detail('items.quest.pickaxe.ability',level=10)['blocks'] if b['title'].startswith('穿刺伤害'))
        self.assertEqual(block['rows'][1],['速度强化','8–32','28–52','20'])

    def test_weapon_passive_defense_and_strength_penalty_are_separate_from_damage(self):
        from companion.values_decisions import compare_equipment
        metrics=self.metrics('items.weapon.melee.roundshield',level=4,strength=11)
        self.assertEqual(metrics['额外减伤基础范围'],'0–8')
        self.assertEqual(metrics['按所填力量的额外减伤'],'0–6')
        result=compare_equipment(self.values,{'id_a':'items.weapon.melee.roundshield','id_b':'items.weapon.melee.greatshield',
            'level_a':'4','level_b':'4','strength':'11'})
        self.assertEqual(result['choices'][0]['current']['武器额外减伤'],'0–6')
        self.assertEqual(result['choices'][1]['current']['武器额外减伤'],'0–4')
        self.assertEqual(result['choices'][0]['current']['力量与武器允许偷袭'],'否')

    def test_armor_comparison_includes_augmentation_and_encumbrance(self):
        from companion.values_decisions import compare_equipment
        result=compare_equipment(self.values,{'id_a':'items.armor.platearmor','id_b':'items.armor.clotharmor',
            'level_a':'0','level_b':'4','strength':'16','augment_b':'EVASION'})
        current=result['choices'][0]['current']
        self.assertEqual(current['常规减伤'],'0–6')
        self.assertEqual(current['信念护体'],'0–2')
        self.assertEqual(current['移动速度倍率'],'0.694444')
        self.assertEqual(current['护甲闪避惩罚倍率'],'0.444444')
        cloth=result['choices'][1]['current']
        self.assertEqual(cloth['常规减伤'],'2–2')
        self.assertEqual(cloth['护甲强化闪避加值'],'12')

    def test_class_armor_uses_original_tier_in_reference_and_comparison(self):
        from companion.values_decisions import compare_equipment
        for kind in ('warriorarmor','magearmor','roguearmor','huntressarmor','duelistarmor','clericarmor'):
            with self.subTest(kind=kind):
                detail=self.metrics('items.armor.'+kind,level=4,tier=1)
                self.assertEqual(detail['常规减伤'],'4–6')
                self.assertEqual(detail['力量需求'],'8')
        compared=compare_equipment(self.values,{'id_a':'items.armor.warriorarmor','tier_a':'1','level_a':'4',
            'augment_a':'EVASION','id_b':'items.armor.platearmor','level_b':'4','strength':'12'})
        self.assertEqual(compared['choices'][0]['current']['常规减伤'],'2–2')
        self.assertEqual(compared['choices'][0]['current']['力量需求'],'8')
        self.assertEqual(compared['choices'][1]['current']['常规减伤'],'0–22')

    def test_stone_inputs_match_attacker_defender_and_game_float_rounding(self):
        detail=self.detail('items.armor.glyphs.stone',accuracy=10,evasion=20,damage=40)
        labels={i['key']:i['label'] for i in detail['inputs']}
        self.assertIn('攻击者',labels['accuracy']);self.assertIn('穿戴者',labels['evasion'])
        metrics=self.metrics('items.armor.glyphs.stone',accuracy=10,evasion=20,damage=40)
        self.assertEqual(metrics['闪避转换的减伤'],'56.25');self.assertEqual(metrics['转换后本次伤害'],'18')
        self.assertEqual(self.metrics('items.armor.glyphs.stone',accuracy=25,evasion=20,damage=10)['转换后本次伤害'],'8')
        self.assertEqual(self.metrics('items.armor.glyphs.stone',accuracy=10,evasion=10,damage=40,glyph_multiplier=2)['转换后本次伤害'],'18')
        self.assertEqual(self.metrics('items.armor.glyphs.stone',accuracy=0,evasion=0,damage=40)['转换后本次伤害'],'0')
        normal={i['key']:i['label'] for i in self.detail('mechanics.accuracy')['inputs']}
        self.assertEqual(normal['accuracy'],'你的命中值');self.assertEqual(normal['evasion'],'目标闪避值')

    def test_slam_crush_and_pickaxe_have_evaluated_conditional_numbers(self):
        slam=self.metrics('actors.buffs.combo$combomove.slam', combo=7, armor_roll=9, damage=20)
        self.assertEqual(slam['按此次护甲减伤追加伤害'],'13')
        self.assertEqual(slam['未计目标减伤的攻击伤害'],'33')
        crush=self.metrics('actors.buffs.combo$combomove.crush',combo=9,damage=21,enemy_armor=4)
        self.assertEqual(crush['主目标减伤前伤害'],'47')
        self.assertEqual(crush['周围单个目标伤害'],'19')
        self.assertEqual(crush['周围易伤目标伤害'],'25')
        pickaxe=self.detail('items.quest.pickaxe.ability',level=0)
        values=next(b for b in pickaxe['blocks'] if b['title'].startswith('穿刺伤害'))
        self.assertEqual(values['rows'][0],['无强化','2–15','10–23','8'])
        self.assertEqual(values['rows'][1],['速度强化','1–11','7–17','6'])
        self.assertEqual(self.metrics('items.quest.pickaxe.ability')['对存活目标施加易伤'],'3')

    def test_vial_total_increase_with_slow_healing(self):
        metrics=self.metrics('items.potions.potionofhealing',max_hp=100,hp=10,vial=3)
        self.assertEqual(metrics['治疗池总量'],'141')
        self.assertEqual(metrics['首次恢复'],'6')
        self.assertEqual(metrics['最终实际恢复'],'90')

    def test_active_healing_does_not_reapply_pool_multiplier(self):
        metrics=self.metrics('actors.buffs.healing',max_hp=100,hp=10,power=141,vial=3)
        self.assertEqual(metrics['剩余治疗池'],'141')
        self.assertEqual(metrics['首次恢复'],'6')
        metrics=self.metrics('actors.buffs.healing',max_hp=100,hp=10,power=100,healing_percent=0,healing_flat=20)
        self.assertEqual(metrics['首次恢复'],'20')
        self.assertEqual(metrics['治疗池耗尽'],'5')
        self.assertEqual(self.metrics('actors.buffs.healing',power=0)['首次恢复'],'0')
        with self.assertRaises(ValueError):self.detail('actors.buffs.healing',power='1.5')

    def test_fractional_dot_values_and_expired_poison(self):
        poison=self.metrics('actors.buffs.poison',power='3.5')
        self.assertEqual(poison['首次毒伤'],'2')
        self.assertEqual(poison['完整毒伤总量'],'5')
        self.assertEqual(self.metrics('actors.buffs.poison',power=0)['首次毒伤'],'0')
        self.assertEqual(self.metrics('actors.buffs.corrosion',power='7.5',depth=10)['下一次酸蚀伤害'],'7')
        self.assertEqual(self.metrics('actors.buffs.bleeding',power='7.5')['下一次流血'],'8')

    def test_traps_and_holy_bomb_have_current_version_values(self):
        self.assertEqual(self.metrics('levels.traps.flashingtrap',depth=10)['未计护甲的流血强度'],'9')
        self.assertEqual(self.metrics('levels.traps.corrosiontrap',depth=10)['起始酸蚀强度'],'3')
        bomb=self.metrics('items.bombs.holybomb',depth=10)
        self.assertEqual(bomb['基础爆炸伤害'],'14–42')
        self.assertEqual(bomb['对亡灵/恶魔追加伤害'],'7–21')
        self.assertEqual(self.metrics('actors.buffs.corrosion',depth=10,power=6)['下次后强度增加'],'1')
        self.assertEqual(self.metrics('actors.buffs.corrosion',depth=10,power=7)['下次后强度增加'],'0.5')
        flash=self.metrics('items.bombs.flashbangbomb',depth=10)
        self.assertEqual(flash['基础爆炸伤害'],'14–42')
        self.assertEqual(flash['额外电击伤害'],'4–11')
        self.assertEqual(self.metrics('items.bombs.firebomb',depth=10)['基础爆炸伤害'],'14–42')
        regrowth=self.metrics('items.bombs.regrowthbomb',max_hp=100,hp=10)
        self.assertEqual(regrowth['直接爆炸伤害'],'0')
        self.assertEqual(regrowth['最终实际恢复'],'90')

    def test_grim_probability_uses_post_hit_health_squared(self):
        values=self.metrics('items.weapon.enchantments.grim',level=0,target_hp=20,target_max_hp=40)
        self.assertEqual(values['斩杀触发概率'],'12.5')
        self.assertEqual(self.metrics('items.weapon.enchantments.grim',level=0,target_hp=40,target_max_hp=40)['斩杀触发概率'],'0')

    def test_transfusion_splits_healing_and_overflow(self):
        values=self.metrics('items.wands.wandoftransfusion',level=3,max_hp=100,target_hp=38,target_max_hp=40)
        self.assertEqual(values['治疗友军时自身损血'],'5')
        self.assertEqual(values['目标实际治疗'],'2')
        self.assertEqual(values['目标溢出护盾'],'12')
        self.assertEqual(values['对敌施法自身护盾'],'8')

    def test_accuracy_boundaries(self):
        for a,e,probability in [(20,10,'75'),(10,20,'25'),(10,10,'50'),(0,10,'0'),(10,0,'100'),(0,0,'100')]:
            self.assertEqual(self.metrics('mechanics.accuracy',accuracy=a,evasion=e)['本次攻击命中'],probability)
        self.assertEqual(self.metrics('mechanics.accuracy',accuracy='20.5',evasion='10.25')['本次攻击命中'],'75')

    def test_weapon_ability_and_spell_outputs_are_numbers(self):
        spear=self.detail('items.weapon.melee.spear.ability',level=3)
        table=next(b for b in spear['blocks'] if b['title']=='决斗家技能伤害')
        self.assertEqual(table['rows'][3],['+3','20–47','15'])
        blessing=self.metrics('actors.hero.spells.blessspell',talent=2)
        self.assertEqual(blessing['自身赐福'],'10')
        self.assertEqual(blessing['自身护盾'],'15')
        self.assertEqual(blessing['友军赐福'],'15')
        link=self.metrics('actors.hero.spells.lifelinkspell',talent=3)
        self.assertEqual(link['实际链接持续'],'17')
        with self.assertRaises(ValueError):self.detail('actors.hero.spells.sunray',talent=3)

    def test_negative_weapon_ability_labels_keep_the_signed_level(self):
        for identity in ('items.weapon.melee.sword', 'items.weapon.melee.spear'):
            for level in (-1, 0, 3):
                with self.subTest(identity=identity, level=level):
                    result = self.detail(identity, level=level)
                    ability = next(b for b in result['blocks'] if b['title']=='决斗家技能伤害')
                    labels = [row[0] for row in ability['rows']]
                    self.assertIn(format(level, '+d'), labels)
                    self.assertTrue(all(not label.startswith('+-') for label in labels))

    def test_regrowth_limit_and_lotus_values(self):
        values=self.metrics('items.wands.wandofregrowth',level=0,hero_level=10,charges=3)
        self.assertEqual(values['正常产草的累计充能额度'],'40')
        self.assertEqual(values['缠绕时长'],'12')
        self.assertEqual(values['随机植物概率'],'100')
        self.assertEqual(self.metrics('items.wands.wandofregrowth',level=10)['正常产草的累计充能额度'],'无限')

    def test_ring_curse_and_real_artifact_display_levels(self):
        haste=self.detail('items.rings.ringofhaste')
        self.assertEqual(next(b['rows'][0] for b in haste['blocks'] if b['title']=='移动速度倍率'),['+0','1.15','0.756144'])
        sand=self.detail('items.artifacts.timekeepershourglass')
        rows=next(b['rows'] for b in sand['blocks'] if b['title']=='沙漏容量与时间静止')
        self.assertEqual(rows[0],['+0','5','10'])
        self.assertEqual(rows[-1],['+10','10','20'])
        might=self.catalog.entries
        recipe=next(e for e in might if e['id']=='items.potions.elixirs.elixirofmight')['recipes'][0]
        self.assertEqual((recipe['cost'],recipe['quantity']),(16,1))

    def test_random_selection_tables_normalize(self):
        for identity in ('items.spells.unstablespell','items.potions.brews.unstablebrew'):
            for b in self.detail(identity)['blocks']:
                if not b.get('columns'):continue
                for column in range(1,len(b['columns'])):
                    self.assertAlmostEqual(sum(float(row[column]) for row in b['rows']),100,places=3)

    def test_class_ability_numbers_include_real_conditions(self):
        shock=self.detail('actors.hero.abilities.warrior.shockwave',strength=14)
        force=next(b for b in shock['blocks'] if b['title']=='震波威力')
        self.assertEqual(force['rows'][0],['0','9–18','0','5'])
        self.assertEqual(force['rows'][4],['4','16–32','100','5'])
        shadow=self.detail('actors.hero.abilities.rogue.shadowclone',hero_level=10)
        self.assertEqual(next(b for b in shadow['blocks'] if b['title']=='完美复制')['rows'][-1],['4','106'])
        self.assertEqual(self.metrics('actors.hero.abilities.cleric.ascendedform')['初始护盾'],'30')
        trinity=self.detail('actors.hero.abilities.cleric.trinity')
        costs=next(b for b in trinity['blocks'] if b['title']=='三位一体充能')['rows']
        self.assertIn(['意之位格：焰浪/再生','50'],costs)
        self.assertIn(['魂之位格：虚空锁链/预知护符/沙漏','35'],costs)

    def test_assassin_monk_and_related_state_details(self):
        prep=self.detail('actors.buffs.preparation')
        self.assertEqual(next(b for b in prep['blocks'] if b['title']=='斩杀所需生命低于')['rows'][-1],['9','50','67','83','100'])
        monk=self.detail('actors.buffs.monkenergy$monkability$dragonkick',strength=14,hero_level=30,max_hp=100,hp=10)
        moves=next(b for b in monk['blocks'] if b['title']=='武僧五门武功')['rows']
        self.assertEqual(moves[3],['盘龙','4','6–36HP','9–54HP'])
        self.assertEqual(moves[4][-1],'5回合 / 治疗18HP / 承伤减免80%')
        state=self.metrics('actors.hero.spells.lifelinkspell$lifelinkspellbuff',talent=3)
        self.assertEqual(state['实际链接持续'],'17')
        self.assertEqual(self.metrics('actors.hero.spells.holylance$lancecooldown')['再次使用等待'],'30')

    def test_environment_healing_and_cooldowns_are_evaluated(self):
        rat=self.detail('actors.mobs.rat')
        rat_values={v['label']:v for b in rat['blocks'] for v in b.get('values',[])}
        self.assertEqual(rat_values['基础伤害范围']['unit'],'HP')
        self.assertEqual((rat_values['通用随机掉落率']['value'],rat_values['通用随机掉落率']['unit']),('0','%'))
        aquatic=self.metrics('items.potions.elixirs.elixirofaquaticrejuvenation$aquahealing',max_hp=65,hp=60)
        self.assertEqual(aquatic['水中每回合实际恢复'],'1–2')
        self.assertEqual(aquatic['向上取整概率'],'30')
        self.assertEqual(self.metrics('actors.buffs.wellfed')['饥饿游戏治疗额度'],'9')
        self.assertEqual(self.metrics('actors.hero.talent$improvisedprojectilecooldown')['状态基础时限'],'50')
        self.assertTrue(self.detail('items.journal.guidebook')['non_numeric'])
        self.assertFalse(self.detail('items.potions.potionofhealing')['non_numeric'])
        self.assertEqual(self.metrics('items.quest.gooblob')['单件炼金回收'],'3')
        self.assertEqual(self.metrics('levels.traps.guardiantrap$guardian',depth=10)['最大生命'],'65')

    def test_monk_vigor_uses_fractional_energy_and_actual_boundary(self):
        identity='actors.buffs.monkenergy$monkability$dragonkick'
        for level,energy,points,expected in ((14,7,3,'否'),(14,7.5,3,'是'),
                                            (20,12,2,'否'),(20,12.5,2,'是')):
            with self.subTest(level=level,energy=energy,points=points):
                result=self.detail(identity,hero_level=level,power=energy)
                rows=next(b for b in result['blocks'] if b['title']=='武道振兴强化门槛')['rows']
                self.assertEqual(rows[points-1][-1],expected)
                value=next(i for i in result['inputs'] if i['key']=='power')
                self.assertEqual(value['step'],'any');self.assertIn('内力',value['label'])
                if level==20:self.assertEqual(rows[1][1:3],['13','12.5'])
        sword=self.detail('items.weapon.melee.sword',level=3)
        self.assertEqual(next(b for b in sword['blocks'] if b['title']=='当前 +3 装备数值')['values'][1]['value'],'32')
        self.assertEqual(next(v['value'] for b in sword['blocks'] if b['title']=='当前 +3 装备数值' for v in b['values'] if v['label']=='力量需求'),'12')
        armor=self.detail('items.armor.mailarmor',level=3)
        self.assertTrue(all(v['unit']=='点' for b in armor['blocks'] if b['title']=='当前 +3 装备数值' for v in b['values'] if '力量' in v['label']))

    def test_boss_phase_tables_do_not_hide_challenge_health(self):
        goo=self.detail('actors.mobs.goo')
        health=next(b for b in goo['blocks'] if b['title']=='粘咕血量与挑战')['rows']
        self.assertEqual(health[0],['普通','100','50','1'])
        self.assertEqual(health[1][1:3],['120','60'])
        damage=next(b for b in goo['blocks'] if b['title']=='粘咕攻击阶段')['rows']
        self.assertEqual(damage[-1][1:3],['1–12','3–36'])
        dm=self.detail('actors.mobs.dm300')
        self.assertEqual(next(b for b in dm['blocks'] if b['title']=='DM-300血量与超充')['rows'][1][1:4],['400','300 / 200 / 100','3'])
        king=self.detail('actors.mobs.dwarfking')
        self.assertEqual(next(b for b in king['blocks'] if b['title']=='矮人国王阶段')['rows'][0][1:5],['300','50','300','12'])

    def test_artifact_capacities_costs_and_random_effects(self):
        tome=self.detail('items.artifacts.holytome',hero_level=1)
        rows=next(b for b in tome['blocks'] if b['title']=='法典容量、充能与升级')['rows']
        self.assertEqual(rows[0],['+0','3','42','44','10','50'])
        self.assertEqual(rows[-1][1:4],['10','30','39'])
        beacon=self.detail('items.artifacts.lloydsbeacon')
        rows=next(b for b in beacon['blocks'] if b['title']=='道标使用成本')['rows']
        self.assertEqual(rows[1],['返回已设位置','0','0'])
        key=self.detail('items.artifacts.skeletonkey')
        rows=next(b for b in key['blocks'] if b['title']=='骷髅钥匙容量与恢复')['rows']
        self.assertEqual(rows[0],['+0','3','97.5','112.5','5'])
        sleeve=self.detail('items.artifacts.masterthievesarmband',stored_charges=3,shop_value=50)
        rows=next(b for b in sleeve['blocks'] if b['title']=='商店偷窃实际概率')['rows']
        self.assertEqual(rows[0],['+0','3','60','12'])
        book=self.detail('items.artifacts.unstablespellbook')
        probabilities=next(b for b in book['blocks'] if b['title']=='随机卷轴效果概率')['rows']
        self.assertAlmostEqual(sum(float(r[1]) for r in probabilities),100,places=3)
        capacities=next(b for b in book['blocks'] if b['title']=='魔典容量与充能')['rows']
        self.assertEqual(capacities[-1],['+10','8','80','115'])

    def test_numeric_talents_use_calculated_damage_and_real_counts(self):
        slam=self.detail('actors.hero.talent.body_slam',power=20)
        self.assertEqual(next(b for b in slam['blocks'] if b['title']=='各级天赋实际数值')['rows'][-1],['4','24–36'])
        directed=self.detail('actors.hero.talent.directed_power',targets=3)
        self.assertEqual(next(b for b in directed['blocks'] if b['title']=='各级天赋实际数值')['rows'][-1],['4','360'])
        cached=self.detail('actors.hero.talent.cached_rations')
        self.assertEqual(next(b for b in cached['blocks'] if b['title']=='各级天赋实际数值')['rows'][-1],['2','3','2 / 4 / 6','200','5','1'])
        intuition=self.detail('actors.hero.talent.unencumbered_spirit')
        self.assertEqual(next(b for b in intuition['blocks'] if b['title']=='各级天赋实际数值')['rows'][-1],['3','100','75','50','0'])

    def test_invalid_values_are_rejected_and_defaults_fit_health(self):
        self.assertEqual(integer_parameters({'max_hp':20})['hp'],20)
        for raw in ({'hp':True},{'level':'1.5'},{'level':-1},{'hp':40,'max_hp':20},{'target_hp':41},{'level':'__import__("os")'},{'vial':4}):
            with self.subTest(raw=raw),self.assertRaises((ValueError,TypeError)):integer_parameters(raw)

    def test_decimal_inputs_and_field_specific_feedback(self):
        for key in ('accuracy','evasion','glyph_multiplier','power','healing_percent','loot_chance'):
            with self.subTest(key=key):
                self.assertEqual(integer_parameters({key:'.5'})[key],.5)
                with self.assertRaisesRegex(ValueError,'可使用小数'):
                    integer_parameters({key:'wrong'})
        self.assertEqual(integer_parameters({'level':'+3.0'})['level'],3)
        with self.assertRaisesRegex(ValueError,'装备等级.*整数'):
            integer_parameters({'level':'.5'})
        with self.assertRaisesRegex(ValueError,'你的命中值.*之间'):
            integer_parameters({'accuracy':-1})
        for invalid in (None, float('inf'), '1e999', '__import__("os")'):
            with self.subTest(value=invalid),self.assertRaises(ValueError):
                integer_parameters({'accuracy':invalid})


if __name__=='__main__':unittest.main()
