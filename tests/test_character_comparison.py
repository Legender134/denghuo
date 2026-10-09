import copy
import json
from pathlib import Path
import tempfile
import unittest

from companion.character_scene import empty_scene, MIGHT
from companion.engine import Catalog
from companion.service import Session
from companion.values_decisions import compare_equipment


class CharacterComparisonTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(prefix='lamp-shared-compare-')
        self.addCleanup(self.directory.cleanup)
        self.session=Session(Path(self.directory.name)/'settings.json',Catalog())
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
        other=Session(Path(self.directory.name)/'other'/'settings.json',Catalog())
        other.knowledge.import_records(exported)
        self.assertEqual(other.knowledge.reopen(saved['id'])['plan']['params']['character_scene'],self.scene)


if __name__=='__main__':unittest.main()
