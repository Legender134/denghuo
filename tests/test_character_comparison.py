import copy
import json
from pathlib import Path
import tempfile
import unittest

from companion.character_scene import empty_scene, MIGHT
from companion.engine import Catalog
from companion.service import Session
from companion.values_decisions import compare_equipment
from companion.rules import NumericRules
from companion.values import PlayerValues


class CharacterComparisonTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(prefix='lamp-shared-compare-')
        self.addCleanup(self.directory.cleanup)
        config=Path(self.directory.name)/'settings.json'
        config.write_text(json.dumps({'save_root':str(Path(self.directory.name)/'synthetic-saves')}),encoding='utf-8')
        self.session=Session(config,Catalog())
        self.scene=empty_scene(11)
        self.scene['rings']=[{'identity':MIGHT,'level':2,'cursed':False}]

    def args(self,kind='ring'):
        return {'strength':14,'id_a':MIGHT if kind=='ring' else 'items.weapon.melee.shortsword',
                'id_b':'items.rings.ringofhaste' if kind=='ring' else 'items.weapon.melee.dagger',
                'level_a':2,'level_b':0,'level_known_a':'1','level_known_b':'1',
                'curse_a':'0','curse_b':'0','character_scene':copy.deepcopy(self.scene),
                **({'scene_ring_slot':0} if kind=='ring' else {})}

    def calculate(self,args):return compare_equipment(self.session.values,args)

    def test_ring_replacement_separates_a_b_and_upgrade_without_double_counting(self):
        result=self.calculate(self.args())
        a,b=result['choices']
        self.assertEqual(a['character_scene']['strength']['effective'],14)
        self.assertEqual(a['upgraded_character_scene']['strength']['effective'],15)
        self.assertEqual(b['character_scene']['strength']['effective'],11)
        self.assertEqual(b['upgraded_character_scene']['strength']['effective'],11)
        self.assertEqual(result['params']['character_scene'],self.scene)

    def test_other_ring_is_retained_and_same_type_pair_is_derived(self):
        self.scene['rings'].append({'identity':MIGHT,'level':1,'cursed':False})
        args=self.args();args['ring_pair_a']='0'
        result=self.calculate(args)
        self.assertEqual(result['params']['ring_pair_a'],'1')
        self.assertEqual(result['params']['ring_pair_level_a'],1)
        self.assertEqual(result['choices'][0]['character_scene']['strength']['effective'],16)
        self.assertEqual(result['choices'][1]['character_scene']['strength']['effective'],13)

    def test_magic_immunity_suppresses_strength_and_ring_metrics(self):
        self.scene['magic_immune']=True
        result=self.calculate(self.args())
        self.assertTrue(all(choice['character_scene']['strength']['effective']==11 for choice in result['choices']))
        self.assertEqual(result['choices'][0]['current']['合计戒指效果等级'],'0')

    def test_signed_other_ring_level_survives_plan_reopen(self):
        self.scene['rings'].append({'identity':MIGHT,'level':-2,'cursed':False})
        result=self.calculate(self.args())
        saved=self.session.knowledge.save('负等级另一枚戒指','equipment',None,result['params'])
        reopened=self.session.knowledge.reopen(saved['id'])
        self.assertEqual(reopened['result']['params']['ring_pair_level_a'],-2)
        self.assertEqual(reopened['result']['choices'][0]['character_scene']['strength']['effective'],13)

    def test_strength_potion_budget_changes_base_and_recalculates_talent_rounding(self):
        self.scene=empty_scene(27);self.scene['strongman']=3
        args=self.args('weapon');args.pop('level_known_a');args.pop('level_known_b');args.pop('curse_a');args.pop('curse_b')
        args.update(strength=31,planning='1',upgrade_budget=1,strength_budget=1,investment_mode='all')
        result=self.calculate(args)
        self.assertEqual(result['choices'][0]['character_scene']['strength']['effective'],31)
        self.assertEqual(result['planning']['effective_strength'],33)
        self.assertEqual(self.scene['base_strength'],27)

    def test_pending_scene_cannot_be_misrepresented_as_definite_comparison(self):
        self.scene['strongman']=None
        with self.assertRaisesRegex(ValueError,'尚不能确定总力量'):
            self.calculate(self.args())
        args=self.args();args.pop('character_scene')
        with self.assertRaisesRegex(ValueError,'替换戒指槽位需要'):
            self.calculate(args)

    def test_query_string_and_plan_roundtrip_retain_nested_scene_and_fixed_revision(self):
        args=self.args();args['character_scene']=json.dumps(args['character_scene']);args['scene_ring_slot']='0'
        result=self.calculate(args)
        saved=self.session.knowledge.save('双戒替换参考','equipment',None,result['params'])
        opened=self.session.knowledge.reopen(saved['id'])
        self.assertEqual(opened['result']['choices'][1]['character_scene']['strength']['effective'],11)
        exported=self.session.knowledge.export()
        config=Path(self.directory.name)/'other'/'settings.json'
        config.parent.mkdir()
        config.write_text(json.dumps({'save_root':str(Path(self.directory.name)/'other-synthetic-saves')}),encoding='utf-8')
        other=Session(config,Catalog())
        other.knowledge.import_records(exported)
        self.assertEqual(other.knowledge.reopen(saved['id'])['plan']['params']['character_scene'],self.scene)


class EnhancedRingComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.values=PlayerValues(NumericRules(Catalog()))

    def compare(self, identity='items.rings.ringoffuror', **scene_changes):
        scene={**empty_scene(14),'format':2,'enhanced_rings':True,
               'rings':[{'identity':identity,'level':2,'cursed':False}],**scene_changes}
        return compare_equipment(self.values,{
            'id_a':identity,'id_b':identity,'level_a':2,'level_b':2,'strength':14,
            'character_scene':scene,'scene_ring_slot':0,'planning':'1',
            'upgrade_budget':2,'strength_budget':0,'investment_mode':'all'})

    def test_enhancement_reaches_current_upgrade_and_budget(self):
        result=self.compare()
        a=result['choices'][0]
        self.assertEqual(a['current']['合计戒指效果等级'],'4')
        self.assertAlmostEqual(float(a['current']['攻击速度倍率']),1.09051**4,places=5)
        self.assertEqual(a['upgraded']['合计戒指效果等级'],'5')
        for option in result['planning']['choices'][0]['alternatives']:
            self.assertEqual(option['metrics']['合计戒指效果等级'],str(option['level']+2))
        self.assertEqual(self.compare(enhanced_rings=False)['choices'][0]['current']['合计戒指效果等级'],'3')
        legacy=self.compare(enhanced_rings=False)['params']
        legacy['character_scene'].pop('enhanced_rings')
        legacy['character_scene']['format']=1
        self.assertEqual(compare_equipment(self.values,legacy)['choices'][0]['current']['合计戒指效果等级'],'3')

    def test_might_and_sharpshooting_keep_their_unbuffed_exceptions(self):
        might=self.compare(MIGHT)['choices'][0]
        self.assertEqual(might['current']['力量增益'],'3')
        self.assertEqual(might['character_scene']['strength']['effective'],17)
        self.assertAlmostEqual(float(might['current']['最大生命倍率']),1.035**4,places=5)
        sharp=self.compare('items.rings.ringofsharpshooting')['choices'][0]['current']
        self.assertEqual(sharp['投掷有效等级增益'],'4')
        self.assertAlmostEqual(float(sharp['投掷耐久倍率']),1.2**3,places=5)

    def test_unknown_enhancement_preserves_only_independent_outputs(self):
        might=self.compare(MIGHT,enhanced_rings=None)['choices'][0]['current']
        self.assertEqual(might['最大生命倍率'],'待确认')
        self.assertEqual(might['力量增益'],'3')
        sharp=self.compare('items.rings.ringofsharpshooting',enhanced_rings=None)['choices'][0]['current']
        self.assertEqual(sharp['投掷有效等级增益'],'待确认')
        self.assertAlmostEqual(float(sharp['投掷耐久倍率']),1.2**3,places=5)

    def test_each_channel_has_its_own_zero_sum_spirit_fallback(self):
        identity='items.rings.ringofsharpshooting'
        result=self.compare(identity,rings=[{'identity':identity,'level':2,'cursed':False},
                                            {'identity':identity,'level':-1,'cursed':True}],
                            spirit_form=True,spirit_ring=identity,spirit_level=4,spirit_cursed=False)
        current=result['choices'][0]['current']
        self.assertEqual(current['合计戒指效果等级'],'2')
        self.assertEqual(current['未增强戒指效果等级'],'5')
        self.assertEqual(current['投掷有效等级增益'],'2')
        self.assertAlmostEqual(float(current['投掷耐久倍率']),1.2**5,places=5)

    def test_magic_immunity_overrides_unknown_enhancement(self):
        current=self.compare(MIGHT,enhanced_rings=None,magic_immune=True)['choices'][0]['current']
        self.assertEqual(current['力量增益'],'0')
        self.assertEqual(current['最大生命倍率'],'1')


if __name__=='__main__':unittest.main()
