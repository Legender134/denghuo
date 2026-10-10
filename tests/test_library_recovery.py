"""Bounded partial recovery preserves originals and historical plan conditions."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from companion.engine import Catalog
from companion.knowledge import KnowledgeWorkspace, MAX_BYTES, MAX_FAVORITES, MAX_PLANS, MAX_RECENT
from companion.rules import NumericRules
from companion.values import PlayerValues


class LibraryRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='denghuo-library-recovery-')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.session = SimpleNamespace(catalog=self.catalog,
            values=PlayerValues(NumericRules(self.catalog)))
        self.store = KnowledgeWorkspace(self.directory/'knowledge.json', self.session)
        self.store.save('健康治疗', 'numeric', 'items.potions.potionofhealing',
            {'hp':3,'max_hp':30,'hero_level':5}, note='独立备注\n原条件')
        self.healthy = json.loads(self.store.export())['plans'][0]

    def damaged(self, **changes):
        bad = {**copy.deepcopy(self.healthy),'id':'b'*32,'name':''}
        value = {'format':1,'favorites':['items.waterskin'],
                 'recent':[{'entry':'items.waterskin','opened':100}],
                 'plans':[copy.deepcopy(self.healthy),bad]}
        value.update(changes)
        raw = json.dumps(value,ensure_ascii=False,separators=(',',':')).encode('utf-8')
        self.store.path.write_bytes(raw)
        return raw

    def test_mixed_preview_readonly_export_and_explicit_recovery_keep_exact_original(self):
        original = self.damaged()
        generation = self.store.generation
        preview = self.store.repair_preview()
        self.assertEqual(preview['mode'],'recover')
        self.assertEqual(preview['healthy_count'],3)
        self.assertEqual(preview['categories']['plans']['invalid'],1)
        self.assertIn('方案名称',preview['issues'][0]['reason'])
        self.assertFalse(self.store.status()['available'])
        with self.assertRaises(ValueError):self.store.export()
        with self.assertRaises(ValueError):self.store.favorite('items.waterskin',False)
        recovered = json.loads(self.store.repair_export(preview['expected']))
        self.assertEqual(recovered['plans'],[self.healthy])
        self.assertEqual(self.store.path.read_bytes(),original)
        self.assertEqual(self.store.generation,generation)
        self.assertEqual(list(self.directory.glob('*.preserved-*')),[])
        with self.assertRaisesRegex(ValueError,'确认'):
            self.store.repair(preview['expected'],False)
        receipt = self.store.repair(preview['expected'],True)
        self.assertEqual(receipt['recovered_count'],3)
        self.assertEqual((self.directory/receipt['preserved_file']).read_bytes(),original)
        self.assertEqual(json.loads(self.store.export()),recovered)
        self.assertEqual(self.store.generation,generation+1)
        self.assertEqual(self.store.reopen(self.healthy['id'])['plan']['record_revision'],
            self.store.record_view(self.healthy)['record_revision'])

    def test_duplicate_id_marks_every_conflicting_row_ambiguous(self):
        conflict = {**copy.deepcopy(self.healthy),'name':'不同内容'}
        broken_conflict = {**copy.deepcopy(self.healthy),'name':''}
        distinct = {**copy.deepcopy(self.healthy),'id':'d'*32,'name':'独立健康'}
        self.damaged(plans=[self.healthy,conflict,broken_conflict,distinct],
            favorites=['items.waterskin','items.waterskin','items.scrolls.scrollofupgrade'],
            recent=[{'entry':'items.waterskin','opened':1},{'entry':'items.waterskin','opened':None}])
        preview = self.store.repair_preview()
        self.assertEqual(preview['categories']['plans']['ambiguous'],3)
        self.assertEqual(preview['categories']['favorites']['ambiguous'],2)
        self.assertEqual(preview['categories']['recent']['ambiguous'],2)
        recovered = json.loads(self.store.repair_export(preview['expected']))
        self.assertEqual(recovered['plans'],[distinct])
        self.assertEqual(recovered['favorites'],['items.scrolls.scrollofupgrade'])
        self.assertEqual(recovered['recent'],[])

    def test_invalid_category_shape_cannot_hide_other_proven_healthy_categories(self):
        self.damaged(plans={'damaged':'shape'})
        preview = self.store.repair_preview()
        self.assertTrue(preview['categories']['plans']['blocked'])
        self.assertEqual(preview['healthy_count'],2)
        recovered = json.loads(self.store.repair_export(preview['expected']))
        self.assertEqual(recovered['plans'],[])
        self.assertEqual(recovered['favorites'],['items.waterskin'])
        self.assertEqual(len(recovered['recent']),1)

    def test_over_limit_categories_are_not_silently_truncated(self):
        for category,maximum,rows in (
                ('favorites',MAX_FAVORITES,[f'items.retired{i}' for i in range(MAX_FAVORITES+1)]),
                ('recent',MAX_RECENT,[{'entry':f'items.retired{i}','opened':100} for i in range(MAX_RECENT+1)]),
                ('plans',MAX_PLANS,[{**copy.deepcopy(self.healthy),'id':f'{i:032x}'} for i in range(MAX_PLANS+1)])):
            with self.subTest(category=category):
                self.damaged(**{category:rows})
                preview = self.store.repair_preview()
                self.assertTrue(preview['categories'][category]['blocked'])
                self.assertEqual(preview['categories'][category]['total'],maximum+1)
                self.assertIn('不截断',next(row['reason'] for row in preview['issues'] if row['category']==category))
                self.assertEqual(json.loads(self.store.repair_export(preview['expected']))[category],[])

    def test_unavailable_old_numeric_and_equipment_are_healthy_structures_not_discarded(self):
        equipment = {**copy.deepcopy(self.healthy),'id':'e'*32,'name':'旧装备','kind':'equipment',
            'entry':None,'rules_version':'3.0.0','params':{'strength':14,
            'id_a':'items.weapon.melee.retiredsword','id_b':'items.weapon.melee.sword',
            'level_a':0,'level_b':0,'tier_a':3,'tier_b':3,
            'mastery_a':'0','mastery_b':'0','augment_a':'NONE','augment_b':'NONE'},
            'origin':{'kind':'saved_reference','mode':'save','snapshot_at':123,'slot':2}}
        numeric = {**copy.deepcopy(self.healthy),'id':'f'*32,'entry':'items.retired',
                   'params':{'historical_input':17},'rules_version':'3.0.0'}
        original = self.damaged(plans=[equipment,numeric,{**copy.deepcopy(self.healthy),'name':''}])
        preview = self.store.repair_preview()
        self.assertEqual(preview['categories']['plans']['healthy'],2)
        receipt = self.store.repair(preview['expected'],True)
        self.assertEqual((self.directory/receipt['preserved_file']).read_bytes(),original)
        unchanged = self.store.export()
        for row in (equipment,numeric):
            opened = self.store.reopen(row['id'])
            self.assertIsNone(opened['result'])
            self.assertTrue(opened['calculation_error'])
            self.assertEqual(opened['plan'],self.store.record_view(row))
        self.assertEqual(self.store.export(),unchanged)
        with self.assertRaises(ValueError):
            self.store.save('旧装备不可新存','equipment',None,equipment['params'])

    def test_public_import_list_and_reopen_keep_old_equipment_and_original_export(self):
        raw = self.damaged()
        valid = json.loads(raw);valid['plans']=[valid['plans'][0]]
        self.store.path.write_bytes(json.dumps(valid).encode())
        equipment = self.store.save('普通装备','equipment',None,{'strength':14,
            'id_a':'items.weapon.melee.sword','id_b':'items.weapon.melee.sword',
            'level_a':0,'level_b':0,'tier_a':3,'tier_b':3,
            'mastery_a':'0','mastery_b':'0','augment_a':'NONE','augment_b':'NONE'})
        imported = {key:copy.deepcopy(value) for key,value in equipment.items() if key!='record_revision'}
        imported['id']='e'*32;imported['params']['id_a']='items.weapon.melee.retiredsword'
        imported['rules_version']='3.0.0'
        result = self.store.import_records(json.dumps({'format':1,'favorites':[],'recent':[],'plans':[imported]}).encode())
        self.assertEqual(result['plans_added'],1)
        original = self.store.export()
        self.assertIn(imported['id'],[row['id'] for row in self.store.status()['plans']])
        reopened = self.store.reopen(imported['id'])
        self.assertEqual(reopened['plan'],self.store.record_view(imported))
        self.assertIsNone(reopened['result'])
        self.assertTrue(reopened['calculation_error'])
        self.assertEqual(self.store.export(),original)

    def test_old_manual_unsupported_conditions_remain_readable_and_strict_new_save(self):
        saved = self.store.save('旧局势','manual',None,{'hp':4,'ht':30,'level':5})
        raw = json.loads(self.store.export())
        manual = next(row for row in raw['plans'] if row['id']==saved['id'])
        manual['params']['retired_condition']=1
        self.store.path.write_bytes(json.dumps(raw,ensure_ascii=False).encode())
        original = self.store.export()
        reopened = self.store.reopen(manual['id'])
        self.assertIsNone(reopened['result'])
        self.assertIn('不支持的参数',reopened['calculation_error'])
        self.assertEqual(reopened['plan'],self.store.record_view(manual))
        self.assertEqual(self.store.export(),original)
        with self.assertRaisesRegex(ValueError,'不支持的参数'):
            self.store.save('修正前不可新存','manual',None,manual['params'])

    def test_new_equipment_target_and_scene_v2_survive_recovery_without_normalization(self):
        from companion.character_scene import empty_scene
        scene={**empty_scene(),'format':2,'enhanced_rings':None,'base_strength':14}
        params={'strength':14,'id_a':'items.weapon.melee.sword','id_b':'items.weapon.melee.sword',
            'level_a':0,'level_b':0,'tier_a':3,'tier_b':3,
            'mastery_a':'0','mastery_b':'0','augment_a':'NONE','augment_b':'NONE',
            'combat_model':'ordinary-v1','target_context':{'format':1,'name':'合成目标',
                'base_accuracy':20,'evasion':None,'dr_min':2,'dr_max':7},'character_scene':scene}
        row=self.store.save('明确目标装备','equipment',None,params)
        original=next(item for item in json.loads(self.store.export())['plans'] if item['id']==row['id'])
        self.damaged(plans=[original,{**copy.deepcopy(self.healthy),'name':''}])
        preview=self.store.repair_preview()
        recovered=json.loads(self.store.repair_export(preview['expected']))
        self.assertEqual(recovered['plans'],[original])
        self.store.repair(preview['expected'],True)
        self.assertEqual(self.store.reopen(row['id'])['plan']['params'],original['params'])

    def test_recovery_read_limit_refuses_without_truncation_or_preserved_copy(self):
        original=b' '*(16*MAX_BYTES+1)
        self.store.path.write_bytes(original)
        with self.assertRaisesRegex(ValueError,'原资料库过大'):self.store.repair_preview()
        self.assertEqual(self.store.path.stat().st_size,len(original))
        self.assertEqual(list(self.directory.glob('*.preserved-*')),[])

    def test_stale_preview_and_stale_readonly_export_do_not_mutate(self):
        self.damaged()
        preview = self.store.repair_preview()
        changed = self.damaged(favorites=['items.scrolls.scrollofupgrade'])
        for operation in (lambda:self.store.repair(preview['expected'],True),
                          lambda:self.store.repair_export(preview['expected'])):
            with self.assertRaisesRegex(ValueError,'重新预览'):operation()
        self.assertEqual(self.store.path.read_bytes(),changed)
        self.assertEqual(list(self.directory.glob('*.preserved-*')),[])

    def test_change_after_preserved_copy_keeps_both_external_change_and_exact_copy(self):
        original = self.damaged()
        preview = self.store.repair_preview()
        generation = self.store.generation
        external = original+b' '
        read_bytes = Path.read_bytes
        def read_after_copy(path):
            result = read_bytes(path)
            if '.preserved-' in path.name:
                self.store.path.write_bytes(external)
            return result
        with patch.object(Path,'read_bytes',read_after_copy):
            with self.assertRaisesRegex(ValueError,'保留副本已建立'):
                self.store.repair(preview['expected'],True)
        self.assertEqual(self.store.path.read_bytes(),external)
        preserved = list(self.directory.glob('*.preserved-*'))
        self.assertEqual(len(preserved),1)
        self.assertEqual(preserved[0].read_bytes(),original)
        self.assertEqual(self.store.generation,generation)
        self.assertEqual(list(self.directory.glob('*.pending')),[])

    def test_staging_and_replace_failures_leave_original_and_preserved_bytes(self):
        for failure in ('write','verify','replace'):
            with self.subTest(failure=failure):
                original = self.damaged()
                preview = self.store.repair_preview()
                generation = self.store.generation
                original_open,original_read,original_replace = Path.open,Path.read_bytes,Path.replace
                def open_stage(path,*args,**kwargs):
                    if path.name.endswith('.pending'):raise OSError('synthetic stage write failure')
                    return original_open(path,*args,**kwargs)
                def read_stage(path):
                    return b'{}' if path.name.endswith('.pending') else original_read(path)
                def replace_stage(path,*args,**kwargs):
                    if path.name.endswith('.pending'):raise OSError('synthetic replace failure')
                    return original_replace(path,*args,**kwargs)
                target,hook = {'write':('open',open_stage),'verify':('read_bytes',read_stage),'replace':('replace',replace_stage)}[failure]
                with patch.object(Path,target,hook):
                    with self.assertRaises((OSError,ValueError)):
                        self.store.repair(preview['expected'],True)
                self.assertEqual(self.store.path.read_bytes(),original)
                self.assertTrue(all(path.read_bytes()==original for path in self.directory.glob('*.preserved-*')))
                self.assertEqual(self.store.generation,generation)
                self.assertEqual(list(self.directory.glob('*.pending')),[])

    def test_preserved_copy_is_exclusive_and_failure_does_not_replace_original(self):
        original = self.damaged()
        preview = self.store.repair_preview()
        collision = self.directory/'knowledge.preserved-collision.json'
        collision.write_bytes(b'previous evidence')
        with patch('companion.knowledge.uuid.uuid4',return_value=SimpleNamespace(hex='collision')):
            with self.assertRaises(FileExistsError):self.store.repair(preview['expected'],True)
        self.assertEqual(collision.read_bytes(),b'previous evidence')
        self.assertEqual(self.store.path.read_bytes(),original)

    def test_unprovable_json_root_or_nonfinite_is_explicit_empty_fallback(self):
        for raw in (b'{broken',b'[]',b'{"format":2,"favorites":[],"recent":[],"plans":[]}',
                    b'{"format":1,"format":1,"favorites":[],"recent":[],"plans":[]}',
                    b'{"format":1,"favorites":[],"recent":[],"plans":[NaN]}',
                    b'{"format":1,"favorites":[],"recent":[],"plans":[1e10000]}',
                    b' '*(MAX_BYTES+1)):
            with self.subTest(raw=raw[:80]):
                self.store.path.write_bytes(raw)
                preview = self.store.repair_preview()
                self.assertEqual(preview['mode'],'empty')
                self.assertFalse(preview['can_export'])
                self.assertTrue(preview['root_error'])
                with self.assertRaisesRegex(ValueError,'没有可证明健康'):self.store.repair_export(preview['expected'])
                receipt = self.store.repair(preview['expected'],True)
                self.assertEqual((self.directory/receipt['preserved_file']).read_bytes(),raw)
                self.assertEqual(json.loads(self.store.export()),{'format':1,'favorites':[],'recent':[],'plans':[]})

    def test_valid_library_refuses_repair_and_duplicate_key_import_stays_strict(self):
        original = self.store.path.read_bytes()
        with self.assertRaisesRegex(ValueError,'无需恢复'):self.store.repair_preview()
        with self.assertRaisesRegex(ValueError,'无需恢复'):self.store.repair('anything',True)
        with self.assertRaisesRegex(ValueError,'格式不正确'):
            self.store.import_records(b'{"format":1,"favorites":[],"recent":[],"plans":[],"plans":[]}')
        self.assertEqual(self.store.path.read_bytes(),original)

    def test_unavailable_64_favorites_visible_cancel_exact_id_and_release_capacity(self):
        from companion.service import Session
        config = self.directory/'settings.json'
        config.write_text(json.dumps({'save_root':str(self.directory/'synthetic-saves'),'slot':'auto','mode':'save'}))
        session = Session(config,self.catalog)
        identities = [f'items.rings.retiredring{i}' for i in range(64)]
        session.knowledge.import_records(json.dumps({'format':1,'favorites':identities,'recent':[],'plans':[]}).encode())
        status = session.workspace_status()
        self.assertEqual(status['favorite_ids'],identities)
        self.assertEqual([row['id'] for row in status['favorites']],identities)
        self.assertTrue(all(row['available'] is False for row in status['favorites']))
        with self.assertRaisesRegex(ValueError,'64'):session.workspace_action({'action':'favorite','entry':'items.waterskin','enabled':True})
        with self.assertRaisesRegex(ValueError,'尚未收录'):session.workspace_action({'action':'favorite','entry':'items.unknown','enabled':True})
        session.workspace_action({'action':'favorite','entry':identities[17],'enabled':False})
        session.workspace_action({'action':'favorite','entry':'items.waterskin','enabled':True})
        final = session.workspace_status()
        self.assertEqual(final['favorite_ids'],identities[:17]+identities[18:]+['items.waterskin'])
        self.assertEqual(final['favorites'][-1]['available'],True)


if __name__=='__main__':
    unittest.main()
