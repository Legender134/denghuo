"""Ordinary-scroll outcomes from the pinned SPD 4.0.2 level/upgrade rules."""
from pathlib import Path
import tempfile
import unittest

from companion.engine import Catalog
from companion.public_source_data import MISSILE_PUBLIC_TYPES
from companion.rules import NumericRules
from companion.service import Session
from companion.values import PlayerValues
from companion.values_decisions import compare_equipment
from companion.values_investment import canonical_comparison


class UpgradeContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog=Catalog()
        cls.values=PlayerValues(NumericRules(cls.catalog))

    def args(self, identity='items.weapon.melee.sword', **overrides):
        return {'id_a':identity,'id_b':identity,'level_a':6,'level_b':6,'strength':20,**overrides}

    def compare(self, identity='items.weapon.melee.sword', **overrides):
        return compare_equipment(self.values,self.args(identity,**overrides))

    def test_public_resin_consumption_preserves_grade_then_increases_it(self):
        result=self.compare('items.wands.wandofmagicmissile',level_a=3,level_b=3,
            resin_a=1,infusion_a='0',curse_a='0',planning='1',upgrade_budget=2,strength_budget=0)
        choice=result['choices'][0]
        self.assertEqual(choice['upgraded_level'],3)
        for label,value in (('最低基础伤害','5'),('最高基础伤害','14'),('最大充能','6')):
            self.assertEqual(choice['current'][label],value)
            self.assertEqual(choice['upgraded'][label],value)
        plan=result['planning']['choices'][0]
        self.assertEqual([row['level'] for row in plan['alternatives']],[3,3,4])
        self.assertEqual((plan['planned_level'],plan['spent_upgrades']),(4,2))
        self.assertEqual([row['upgrade_branches'][0]['resin'] for row in plan['alternatives'][1:]],[0,0])

    def test_hardened_infusion_jumps_six_to_eight_without_same_scroll_removal(self):
        for identity,expected in (('items.weapon.melee.sword',('11','52')),
                                  ('items.armor.platearmor',('8–50','0–14'))):
            with self.subTest(identity=identity):
                choice=self.compare(identity,infusion_a='1',hardened_a='1')['choices'][0]
                self.assertEqual(choice['upgraded_level'],8)
                labels=('常规减伤','信念护体') if '.armor.' in identity else ('最低基础伤害','最高基础伤害')
                self.assertEqual(tuple(choice['upgraded'][label] for label in labels),expected)
                self.assertEqual({branch['hardened'] for branch in choice['upgrade_branches']},{'0','1'})
                self.assertTrue(all(branch['infusion']=='1' and branch['level']==8 for branch in choice['upgrade_branches']))
                self.assertNotIn('after_infusion_removed',choice)

    def test_unhardened_effect_removal_has_its_own_grade_and_metrics(self):
        choice=self.compare(infusion_a='1',hardened_a='0')['choices'][0]
        self.assertEqual(choice['upgraded_level'],8)
        self.assertEqual(choice['after_infusion_removed_level'],6)
        removed={cell['label']:cell for cell in choice['after_infusion_removed']}
        self.assertEqual((removed['最低基础伤害']['value'],removed['最高基础伤害']['value']),('9','44'))
        self.assertEqual(removed['最低基础伤害']['unit'],'HP')
        self.assertNotIn('after_curse_removed',choice)

    def test_no_infusion_does_not_claim_unmodeled_hardening_survives(self):
        choice=self.compare(level_a=10,infusion_a='0',hardened_a='1')['choices'][0]
        self.assertEqual(choice['upgraded_level'],11)
        self.assertEqual(choice['upgrade_branches'][0]['hardened'],'unknown')
        self.assertIn('不保证硬化仍在',choice['upgrade_branches'][0]['condition'])
        self.assertEqual(choice['upgrade_risk'],100)  # Legacy ordinary-unhardened reference.
        with self.assertRaisesRegex(ValueError,'A侧硬化状态未确认，请明确选择'):
            self.compare(hardened_a='unknown')

    def test_budget_tracks_hardening_loss_before_later_effect_removal(self):
        plan=self.compare(infusion_a='1',hardened_a='1',planning='1',upgrade_budget=2,
            strength_budget=0,investment_mode='all')['planning']['choices'][0]
        first,second=plan['alternatives'][1:]
        self.assertEqual({(b['level'],b['infusion']) for b in first['upgrade_branches']},{(8,'1')})
        self.assertEqual({(b['level'],b['infusion']) for b in second['upgrade_branches']},{(9,'1'),(7,'0')})
        self.assertEqual(second['after_infusion_removed_level'],7)
        forced=self.compare(level_a=10,infusion_a='1',hardened_a='1',planning='1',upgrade_budget=2,
            investment_mode='all')['planning']['choices'][0]['alternatives']
        self.assertEqual({(b['level'],b['hardened'],b['infusion']) for b in forced[1]['upgrade_branches']},{(11,'0','1')})
        self.assertNotIn('after_infusion_removed',forced[1])
        self.assertEqual({(b['level'],b['infusion']) for b in forced[2]['upgrade_branches']},{(12,'1'),(10,'0')})
        below=self.compare(level_a=5,infusion_a='1',hardened_a='1')['choices'][0]
        self.assertEqual({branch['hardened'] for branch in below['upgrade_branches']},{'1'})

    def test_minimum_strength_uses_worst_reachable_grade(self):
        short=self.compare(level_a=9,infusion_a='1',hardened_a='0',strength=10,
            planning='1',upgrade_budget=1,strength_budget=0)['planning']['choices'][0]
        self.assertEqual((short['needed_upgrades'],short['planned_level'],short['remaining_strength_deficit'],short['within_budget']),
                         (3,10,1,False))
        # Retaining infusion reaches the threshold after one scroll; removing it does not.
        self.assertEqual(short['metrics']['力量缺口'],'0')
        self.assertEqual({b['metrics']['力量需求'] for b in short['alternatives'][1]['upgrade_branches']},{'10','11'})
        enough=self.compare(level_a=9,infusion_a='1',hardened_a='0',strength=10,
            planning='1',upgrade_budget=3,strength_budget=0)['planning']['choices'][0]
        self.assertEqual((enough['spent_upgrades'],enough['planned_level'],enough['remaining_strength_deficit']),(3,12,0))

    def test_summary_does_not_promote_one_infusion_branch_to_a_guarantee(self):
        result=self.compare(level_a=5,strength=11,infusion_a='1',hardened_a='0')
        choice=result['choices'][0];explanation=result['explanation']['choices'][0]
        self.assertEqual({b['metrics']['力量缺口'] for b in choice['upgrade_branches']},{'0','1'})
        self.assertIn('部分结果可跨过力量门槛',explanation['summary'])
        self.assertIn('其他结果仍差 1 点',explanation['summary'])
        self.assertIn('不能保证',explanation['summary'])
        self.assertIn(choice['upgrade_branches'][0]['condition'],explanation['timing_and_accuracy'])
        self.assertTrue(all(choice['upgrade_branches'][0]['condition'] in row['condition']
                            for row in explanation['upgrade_changes']))

    def test_summary_warns_when_effect_removal_makes_sufficient_strength_insufficient(self):
        result=self.compare(level_a=10,strength=10,infusion_a='1',hardened_a='0')
        choice=result['choices'][0];summary=result['explanation']['choices'][0]['summary']
        self.assertEqual(choice['current']['力量缺口'],'0')
        self.assertEqual({b['metrics']['力量缺口'] for b in choice['upgrade_branches']},{'0','1'})
        self.assertIn('部分结果会出现 1 点力量缺口',summary)

    def test_summary_preserves_guaranteed_and_equal_strength_outcomes(self):
        ordinary=self.compare(level_a=5,strength=11,infusion_a='0')['explanation']['choices'][0]
        self.assertIn('所有可达结果均可跨过力量门槛',ordinary['summary'])
        equal=self.compare(level_a=6,strength=11,infusion_a='1',hardened_a='0')
        self.assertEqual({b['metrics']['力量需求'] for b in equal['choices'][0]['upgrade_branches']},{'11'})
        self.assertIn('当前达到力量需求',equal['explanation']['choices'][0]['summary'])
        self.assertNotIn('会出现',equal['explanation']['choices'][0]['summary'])

    def test_wand_uncursing_clears_infusion_and_uses_uncursed_grade(self):
        result=self.compare('items.wands.wandofmagicmissile',infusion_a='1',curse_a='1',
            planning='1',upgrade_budget=2,strength_budget=0)
        choice=result['choices'][0]
        self.assertEqual((choice['upgraded_level'],choice['after_curse_removed_level'],choice['after_infusion_removed_level']),(8,6,6))
        self.assertNotIn('最低基础伤害',choice['upgraded'])
        cleared={cell['label']:cell['value'] for cell in choice['after_curse_removed']}
        self.assertEqual((cleared['最低基础伤害'],cleared['最高基础伤害'],cleared['最大充能']),('8','20','9'))
        second=result['planning']['choices'][0]['alternatives'][2]
        self.assertEqual({(branch['level'],branch['infusion'],branch['curse']) for branch in second['upgrade_branches']},
                         {(9,'1','1'),(7,'0','0')})

    def test_all_fifteen_missiles_share_grade_branches_without_promising_unbind(self):
        self.assertEqual(len(MISSILE_PUBLIC_TYPES),15)
        for identity in MISSILE_PUBLIC_TYPES:
            with self.subTest(identity=identity):
                result=self.compare(identity,infusion_a='1',hardened_a='0',level_known_a='1')
                choice=result['choices'][0]
                self.assertEqual({(b['level'],b['infusion']) for b in choice['upgrade_branches']},{(8,'1'),(6,'0')})
                retained=choice['upgrade_branches'][0]
                self.assertIn('原绑定诅咒保留',retained['condition'])
                self.assertNotEqual(retained['curse'],'0')
                ordinary=self.compare(identity,level_a=8)['choices'][0]['current']
                self.assertEqual(choice['upgraded']['最低基础伤害'],ordinary['最低基础伤害'])
                self.assertEqual(choice['upgraded']['最高基础伤害'],ordinary['最高基础伤害'])
                self.assertIn('未读取精确耐久',str(choice['upgraded_metrics']))

    def test_unknown_infusion_keeps_current_grade_and_blocks_upgrade_projection(self):
        for identity in ('items.weapon.melee.sword','items.armor.platearmor','items.wands.wandofmagicmissile'):
            with self.subTest(identity=identity):
                result=self.compare(identity,infusion_a='unknown',planning='1',upgrade_budget=2)
                choice=result['choices'][0];plan=result['planning']['choices'][0]
                self.assertEqual(choice['level'],6)
                self.assertIsNone(choice['upgraded_level'])
                self.assertEqual(choice['upgraded']['升级条件'],'注魔假设未确认')
                self.assertEqual(choice['upgrade_branches'],[])
                self.assertIsNone(plan['planned_level'])
                self.assertEqual([row['upgrades'] for row in plan['alternatives']],[0])
                self.assertTrue(plan['upgrade_pending'])
                self.assertFalse(any('base_level' in key or 'curse_infusion_bonus' in key for key in result['params']))

    def test_invalid_context_is_rejected_instead_of_guessing_a_base(self):
        invalid=({'infusion_a':'yes'},{'infusion_a':True},{'hardened_a':1},{'resin_a':0},
                 {'infusion_a':'1','level_a':7},{'infusion_a':'1','level_a':-5},
                 {'base_level_a':5},{'curse_infusion_bonus_a':True})
        for overrides in invalid:
            with self.subTest(overrides=overrides),self.assertRaises(ValueError):self.compare(**overrides)
        for overrides in ({'resin_a':True},{'resin_a':4},{'resin_a':'1.5'},
                          {'level_a':0,'resin_a':1},{'infusion_a':'1','curse_a':'0'},
                          {'infusion_a':'1','curse_a':'unknown'},{'hardened_a':'0'}):
            with self.subTest(overrides=overrides),self.assertRaises(ValueError):self.compare('items.wands.wandofmagicmissile',**overrides)
        with self.assertRaises(ValueError):self.compare('items.rings.ringofhaste',infusion_a='0')

    def test_java_negative_division_and_ordinary_defaults_remain_intact(self):
        infused=self.compare(level_a=-6,infusion_a='1',hardened_a='1')['choices'][0]
        self.assertEqual(infused['upgraded_level'],-4)  # base -6 -> -5; Java -5/6 == 0.
        ordinary=self.compare(level_a=-100)
        self.assertEqual(ordinary['choices'][0]['upgraded_level'],-99)
        self.assertNotIn('infusion_a',ordinary['params'])
        self.assertEqual(canonical_comparison(self.values,ordinary['params']),ordinary['params'])
        capped=self.compare('items.wands.wandofmagicmissile',level_a=99,resin_a=1,
            planning='1',upgrade_budget=4)['planning']['choices'][0]
        self.assertEqual([row['level'] for row in capped['alternatives']],[99,99,100])
        self.assertEqual((capped['planned_level'],capped['spent_upgrades'],capped['remaining_upgrades']),(100,2,2))

    def test_fixed_plan_export_import_reopen_keeps_assumptions_and_actual_budget(self):
        cases=(self.args('items.wands.wandofmagicmissile',level_a=3,resin_a=1,infusion_a='0',
                        planning='1',upgrade_budget=2,strength_budget=0),
               self.args(infusion_a='1',hardened_a='1',planning='1',upgrade_budget=2,investment_mode='all'),
               self.args(infusion_a='unknown',planning='1',upgrade_budget=2))
        with tempfile.TemporaryDirectory(prefix='lamp-upgrade-plan-') as directory:
            session=Session(Path(directory)/'settings.json',self.catalog)
            other=Session(Path(directory)/'other'/'settings.json',self.catalog)
            for index,args in enumerate(cases):
                with self.subTest(index=index):
                    expected=compare_equipment(self.values,args)
                    saved=session.knowledge.save('升级条件'+str(index),'equipment',None,expected['params'],
                        {'fields':{'infusion_a':'明确手填假设'}})
                    reopened=session.knowledge.reopen(saved['id'])
                    self.assertEqual(reopened['result'],expected)
            other.knowledge.import_records(session.knowledge.export())
            for saved in session.knowledge.status()['plans']:
                self.assertEqual(other.knowledge.reopen(saved['id'])['result'],session.knowledge.reopen(saved['id'])['result'])
            # The new plan parameters contain only entered assumptions, never hidden saved flags/base grades.
            exported=session.knowledge.export().decode('utf-8')
            self.assertNotIn('curse_infusion_bonus',exported)
            self.assertNotIn('base_level',exported)


if __name__=='__main__':unittest.main()
