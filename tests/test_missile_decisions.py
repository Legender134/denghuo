"""Ordinary missile decisions against checked SPD 4.0.2 public branches."""
import json
from pathlib import Path
import tempfile
import unittest

from companion.character_scene import empty_scene, MIGHT
from companion.engine import Catalog, PREFIX
from companion.public_source_data import MISSILE_PUBLIC_TYPES
from companion.rules import NumericRules
from companion.service import Session
from companion.values import PlayerValues
from companion.values_decisions import compare_equipment
from companion.values_investment import canonical_comparison, family


class MissileDecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()
        cls.rules = NumericRules(cls.catalog)
        cls.values = PlayerValues(cls.rules)

    def args(self, **overrides):
        return {'id_a':'items.weapon.missiles.shuriken', 'id_b':'items.weapon.missiles.trident',
                'level_a':2, 'level_b':2, 'strength':14, **overrides}

    def compare(self, **overrides):
        return compare_equipment(self.values, self.args(**overrides))

    def cells(self, detail):
        return {cell['label']:cell for block in detail['blocks'] for cell in block.get('values', [])}

    def test_all_fifteen_keep_item_specific_damage_and_strength(self):
        # Exact +2 min/max from the checked individual min(int)/max(int) overrides.
        expected = {'bolas':(4,13), 'fishingspear':(6,14), 'forcecube':(12,40),
            'heavyboomerang':(10,22), 'javelin':(10,28), 'kunai':(8,18),
            'shuriken':(6,12), 'throwingclub':(6,12), 'throwinghammer':(12,30),
            'throwingknife':(4,10), 'throwingspear':(8,21), 'throwingspike':(4,7),
            'throwingstone':(4,7), 'tomahawk':(8,22), 'trident':(12,35)}
        self.assertEqual(len(MISSILE_PUBLIC_TYPES),15)
        self.assertEqual(set(expected),{identity.rsplit('.',1)[-1] for identity in MISSILE_PUBLIC_TYPES})
        for identity,(tier,_) in MISSILE_PUBLIC_TYPES.items():
            with self.subTest(identity=identity):
                result=self.compare(id_a=identity,id_b=identity)
                current=result['choices'][0]['current']
                self.assertEqual(result['family'],'missile')
                self.assertEqual(tuple(int(current[key]) for key in ('最低基础伤害','最高基础伤害')),expected[identity.rsplit('.',1)[-1]])
                self.assertEqual(int(current['力量需求']),6+2*tier)
                self.assertEqual(int(result['choices'][0]['upgraded']['力量需求']),5+2*tier)
                self.assertFalse(set(current)&{'武器额外减伤','力量与武器允许偷袭','攻击距离','命中倍率','攻击耗时'})
                detail=self.values.detail(identity,{'level':2})
                self.assertEqual(self.cells(detail)['力量需求']['value'],str(6+2*tier))
                strength=next(block for block in detail['blocks'] if block['title']=='力量需求')
                self.assertIn('投掷',strength['note'])

    def test_known_inventory_tier_requirement_mastery_and_hidden_grade(self):
        for name,tier,need in [('Shuriken',2,10),('Trident',5,16),('ThrowingHammer',5,16)]:
            source={'__className':PREFIX+'items.weapon.missiles.'+name, 'level':2,
                    'levelKnown':True,'cursedKnown':True,'cursed':False}
            with self.subTest(name=name):
                current=self.catalog.item(source,{})
                self.assertEqual((current['tier'],current['level'],current['strength_requirement']),(tier,2,need))
                self.assertEqual(self.catalog.item({**source,'level':3},{})['strength_requirement'],need-1)
                self.assertEqual(self.catalog.item({**source,'mastery_potion_bonus':True},{})['strength_requirement'],need-2)
                hidden=self.catalog.item({**source,'level':77,'levelKnown':False},{})
                self.assertIsNone(hidden['level'])
                self.assertIsNone(hidden['strength_requirement'])
                self.assertNotIn('77',str(hidden))
                self.assertTrue(any('力量需求待核对' in text for text in hidden['details']))

    def test_mastery_augmentation_and_excess_strength_are_separate(self):
        current=self.compare(strength=10,mastery_a='1',augment_a='DAMAGE')['choices'][0]['current']
        self.assertEqual([current[key] for key in ('力量需求','力量缺口','最低基础伤害','最高基础伤害','额外力量伤害')],['8','0','9','18','0–2'])
        self.assertAlmostEqual(float(current['目标投掷耗时']),5/3,places=5)
        self.assertEqual(current['空格投掷耗时'],'1')
        self.assertEqual(current['快速投掷就绪耗时'],'0')
        speed=self.compare(id_a='items.weapon.missiles.trident',strength=14,augment_a='SPEED')['choices'][0]['current']
        self.assertEqual((speed['最低基础伤害'],speed['最高基础伤害'],speed['力量缺口']),('8','25','2'))
        self.assertAlmostEqual(float(speed['目标投掷耗时']),.96,places=5)
        self.assertAlmostEqual(float(speed['相邻投掷命中倍率']),.5/1.5**2,places=5)
        self.assertAlmostEqual(float(speed['非相邻投掷命中倍率']),1.5/1.5**2,places=5)

    def test_handbook_accuracy_time_and_range_are_conditional(self):
        cells=self.cells(self.values.detail('items.weapon.missiles.shuriken',{'level':2,'strength':10}))
        self.assertEqual((cells['相邻投掷命中倍率']['value'],cells['非相邻投掷命中倍率']['value']),('0.5','1.5'))
        self.assertIn('0点',cells['相邻投掷命中倍率']['condition'])
        self.assertIn('不是最终命中概率',cells['相邻投掷命中倍率']['condition'])
        self.assertIn('0.5+0.25',cells['贴身投掷天赋命中分支']['condition'])
        self.assertIn('标记不存在',cells['快速投掷就绪耗时']['condition'])
        self.assertIn('标记存在时',cells['目标投掷耗时']['condition'])
        self.assertNotIn('移动',cells['快速投掷就绪耗时']['condition'])
        self.assertNotIn('攻击距离',cells)
        inputs={row['key']:row for row in self.values.detail('items.weapon.missiles.shuriken')['inputs']}
        self.assertIn('strength',inputs)
        self.assertEqual(inputs['level']['min'],-100)
        cube=self.compare(id_a='items.weapon.missiles.forcecube',strength=14,augment_a='DAMAGE')['choices'][0]['current_metrics']
        cube={row['label']:row for row in cube}
        self.assertAlmostEqual(float(cube['非坑空格投掷耗时']['value']),2.4,places=5)
        self.assertEqual(cube['坑空格投掷耗时']['value'],'1')
        self.assertIn('英雄',cube['特殊效果边界']['condition'])
        boomerang=self.compare(id_a='items.weapon.missiles.heavyboomerang',strength=20)['choices'][0]['current_metrics']
        returning=next(row for row in boomerang if row['label']=='回旋命中倍率')
        self.assertEqual(returning['value'],'1.5')
        self.assertIn('不保证再次命中',returning['condition'])

    def test_negative_level_clamps_damage_but_retains_grade_and_base_requirement(self):
        current=self.compare(level_a=-100)['choices'][0]['current']
        self.assertEqual((current['最低基础伤害'],current['最高基础伤害'],current['力量需求']),('0','0','11'))
        handbook=self.cells(self.values.detail('items.weapon.missiles.shuriken',{'level':-100}))
        self.assertEqual((handbook['最低基础伤害']['value'],handbook['最高基础伤害']['value']),('0','0'))
        result=self.compare(level_a=-1,planning='1',upgrade_budget=2,strength_budget=0)
        self.assertEqual(result['params']['level_a'],-1)

    def test_minimum_strength_and_full_budget_keep_thresholds_and_rows(self):
        plan=self.compare(strength=14,planning='1',upgrade_budget=8,strength_budget=0)['planning']
        trident=plan['choices'][1]
        self.assertEqual((trident['needed_upgrades'],trident['spent_upgrades'],trident['planned_level'],trident['remaining_upgrades']),(4,4,6,4))
        short=self.compare(strength=14,planning='1',upgrade_budget=1,strength_budget=0)['planning']['choices'][1]
        self.assertEqual((short['planned_level'],short['remaining_strength_deficit'],short['within_budget']),(3,1,False))
        potion=self.compare(strength=14,planning='1',upgrade_budget=8,strength_budget=1)['planning']['choices'][1]
        self.assertEqual((potion['needed_upgrades'],potion['spent_upgrades'],potion['planned_level']),(1,1,3))
        full=self.compare(strength=14,planning='1',upgrade_budget=8,strength_budget=1,investment_mode='all')['planning']['choices'][1]
        self.assertEqual((full['planned_level'],full['remaining_upgrades']),(10,0))
        self.assertEqual([row['level'] for row in full['alternatives']],list(range(2,11)))
        for option in full['alternatives']:
            rows={row['label']:row for row in option['metric_rows']}
            self.assertEqual(rows['目标投掷耗时']['unit'],'回合')
            self.assertIn('不是最终命中概率',rows['相邻投掷命中倍率']['condition'])
        cap=self.compare(level_a=99,planning='1',upgrade_budget=8,investment_mode='all')['planning']['choices'][0]
        self.assertEqual((cap['planned_level'],cap['remaining_upgrades']),(100,7))

    def test_fixed_plan_keeps_signed_grade_scene_budgets_and_field_origins(self):
        scene=empty_scene(11)
        scene['rings']=[{'identity':MIGHT,'level':2,'cursed':False}]
        params=self.args(level_a=-1,level_b=2,mastery_a='1',augment_a='SPEED',level_known_a='1',level_known_b='0',
            character_scene=json.dumps(scene),planning='1',upgrade_budget=4,strength_budget=1,investment_mode='all')
        fixed=canonical_comparison(self.values,params)
        self.assertEqual(canonical_comparison(self.values,fixed),fixed)
        with tempfile.TemporaryDirectory(prefix='lamp-missile-plan-') as directory:
            session=Session(Path(directory)/'settings.json',self.catalog)
            source={'fields':{'id_a':'已知背包身份','level_a':'已知背包等级','level_b':'手填假设','character_scene':'固定角色条件','upgrade_budget':'手填预算'}}
            saved=session.knowledge.save('投掷固定条件','equipment',None,fixed,source)
            opened=session.knowledge.reopen(saved['id'])
            self.assertEqual(opened['plan']['params'],fixed)
            self.assertEqual(opened['plan']['origin']['fields'],source['fields'])
            self.assertEqual(opened['result']['params'],fixed)
            self.assertEqual(opened['result']['planning']['effective_strength'],15)
            self.assertEqual(opened['result']['choices'][0]['character_scene']['strength']['effective'],14)
            self.assertIn('当前等级已在游戏中确认',opened['result']['choices'][0]['current_metrics'][0]['condition'])
            self.assertIn('升级试算，未实际升级',opened['result']['choices'][0]['upgraded_metrics'][0]['condition'])
            planned=opened['result']['planning']['choices'][0]['metric_rows'][0]
            self.assertIn('升级试算，未实际升级',planned['condition'])
            self.assertIn('手填等级假设',opened['result']['choices'][1]['current_metrics'][0]['condition'])
            other=Session(Path(directory)/'imported'/'settings.json',self.catalog)
            other.knowledge.import_records(session.knowledge.export())
            self.assertEqual(other.knowledge.reopen(saved['id'])['plan']['params'],fixed)

    def test_rejects_darts_spiritbow_obsolete_nested_and_cross_family(self):
        for identity in ('items.weapon.missiles.darts.dart','items.weapon.missiles.boomerang',
                         'items.weapon.spiritbow','items.weapon.missiles.shuriken$shurikeninstanttracker',
                         'items.weapon.missiles.missileweapon','items.weapon.missiles.unverified'):
            with self.subTest(identity=identity),self.assertRaises(ValueError):
                self.compare(id_a=identity,id_b=identity)
            self.assertIsNone(family(identity))
        for identity in ('items.weapon.melee.sword','items.armor.platearmor','items.wands.wandofmagicmissile','items.rings.ringofmight'):
            with self.subTest(identity=identity),self.assertRaisesRegex(ValueError,'同一类别'):
                self.compare(id_b=identity)
        for args in ({'level_a':True},{'level_a':-101},{'level_known_a':'maybe'},
                     {'mastery_a':'2'},{'augment_a':'DEFENSE'},{'planning':'1','upgrade_budget':101},
                     {'id_a':[]},{'id_a':{}}):
            with self.subTest(args=args),self.assertRaises(ValueError):self.compare(**args)

    def test_special_damage_branches_are_not_guaranteed_totals(self):
        for tail,condition in [('kunai','60%'),('throwingknife','75%'),('tomahawk','流血'),
                               ('fishingspear','食人鱼'),('bolas','残废'),('throwinghammer','拾取耗时0')]:
            current=self.compare(id_a='items.weapon.missiles.'+tail)['choices'][0]['current_metrics']
            self.assertIn(condition,next(row['condition'] for row in current if row['label']=='特殊效果边界'))
        boundary=next(row['condition'] for row in self.compare()['choices'][0]['current_metrics'] if row['label']=='升级与耐久边界')
        self.assertIn('未读取精确耐久',boundary)
        self.assertIn('诅咒',boundary)

    def test_upgrade_curse_conditions_and_provenance_match_each_override(self):
        detail=self.values.detail('items.scrolls.scrollofupgrade',{'level':6})
        cells=self.cells(detail)
        self.assertEqual(cells['装备绑定诅咒解除']['value'],'100')
        self.assertIn('仅普通近战武器与护甲',cells['装备绑定诅咒解除']['condition'])
        self.assertIn('不适用于法杖、戒指或投掷',cells['装备绑定诅咒解除']['condition'])
        self.assertEqual(cells['法杖 / 戒指诅咒解除']['value'],'33.3333')
        self.assertIn('原本被诅咒',cells['法杖 / 戒指诅咒解除']['condition'])
        self.assertEqual(cells['投掷武器绑定诅咒解除']['value'],'33.3333')
        self.assertIn('未硬化',cells['投掷武器绑定诅咒解除']['condition'])
        self.assertIn('附魔保留',cells['投掷武器绑定诅咒解除']['condition'])
        self.assertEqual(cells['硬化诅咒投掷武器解咒']['value'],'0')
        self.assertIn('即使硬化消失',cells['硬化诅咒投掷武器解咒']['condition'])
        self.assertEqual(cells['无诅咒附魔投掷武器解咒']['value'],'100')
        self.assertIn('没有诅咒附魔',cells['无诅咒附魔投掷武器解咒']['condition'])
        self.assertTrue(any('注魔菱晶' in block.get('note','') and '保留' in block['note'] for block in detail['blocks']))
        urls=[link['url'] for link in detail['provenance']['links']]
        for name in ('ScrollOfUpgrade','Weapon','MissileWeapon','Armor','Wand','Ring'):
            self.assertTrue(any('/'+name+'.java' in url for url in urls),name)
        shuriken=self.values.detail('items.weapon.missiles.shuriken')['provenance']['links']
        for name in ('Shuriken','MissileWeapon','Weapon','Item'):
            self.assertTrue(any('/'+name+'.java' in link['url'] for link in shuriken),name)


if __name__=='__main__':unittest.main()
