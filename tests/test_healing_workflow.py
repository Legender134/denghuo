"""Saved public Healing conditions and conditional resource comparison, without GUI."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from companion.decisions import context_actions
from companion.engine import Catalog, PREFIX, analyze
from companion.game_math import potion_healing_pool
from companion.rules import NumericRules
from companion.service import Session
from companion.values import PlayerValues


class HealingWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()
        cls.values = PlayerValues(NumericRules(cls.catalog))

    def game(self, **fields):
        healing = {'__className':PREFIX+'actors.buffs.Healing', 'left':80, 'percent':.1,
                   'flat':2, 'vial_level':-1, 'private_unrelated':{'secret':123}}
        healing.update(fields)
        return {'version':self.catalog.data['version_code'], 'challenges':0, 'depth':2,
                'PotionOfHealing_known':True,
                'hero':{'class':'WARRIOR', 'lvl':5, 'HP':20, 'HT':100, 'STR':10,
                        'buffs':[healing], 'inventory':[{'__className':PREFIX+'items.potions.PotionOfHealing', 'quantity':2}]}}

    def snapshot(self, game=None, *, mode='save', stale=False):
        return {'settings':{'mode':mode, 'save_root':'synthetic-root'}, 'data':analyze(game or self.game(), self.catalog),
                'modified':123, 'stale':stale, 'started':100, 'active_slot':1, 'revision':7, 'error':''}

    def option(self, snapshot):
        session = SimpleNamespace(catalog=self.catalog, values=self.values)
        return context_actions(session, snapshot)['options'][0]

    def test_public_fields_and_real_saved_schedule(self):
        buff = self.snapshot()['data']['buffs'][0]
        self.assertEqual({key:buff[key] for key in ('left','percent','flat','vial_level','next_heal')},
                         {'left':80, 'percent':.1, 'flat':2, 'vial_level':-1, 'next_heal':10})
        self.assertNotIn('private_unrelated', buff)
        option = self.option(self.snapshot())
        wait, drink = option['comparison']['scenarios']
        self.assertEqual((wait['pool'], wait['first_actual'], wait['actual_heal'], wait['final_hp'], wait['ticks']), (80,10,80,100,15))
        self.assertEqual((drink['pool'], drink['first_actual'], drink['actual_heal'], drink['ticks']), (94,26,80,9))
        self.assertEqual(option['comparison']['marginal_heal'], 0)
        self.assertIn('额外恢复 0 HP', option['note'])
        self.assertIn('不预测敌方伤害', option['note'])

    def test_merge_each_field_and_new_source_resets_vial_cap(self):
        snap = self.snapshot(self.game(left=110, percent=.5, flat=8, vial_level=3))
        wait, drink = self.option(snap)['comparison']['scenarios']
        self.assertEqual(wait['next_heal'], 6)
        self.assertEqual(drink['params'], {'power':110,'healing_percent':50,'healing_flat':8,'vial':-1})
        self.assertEqual(drink['next_heal'], 63)
        self.assertEqual(drink['pool'], 110)  # Existing pool is neither added nor multiplied again.

    def test_zero_remaining_pool_has_no_invented_healing(self):
        wait, drink = self.option(self.snapshot(self.game(left=0)))['comparison']['scenarios']
        self.assertEqual((wait['next_heal'],wait['first_actual'],wait['actual_heal'],wait['ticks'],wait['schedule']), (0,0,0,0,[]))
        self.assertEqual(drink['actual_heal'], 80)

    def test_invalid_or_missing_buff_conditions_remain_unknown(self):
        for key, values in {'left':[None,-1,True,'80',1.5,10001],
                            'percent':[None,-.1,True,'0.1',float('nan'),float('inf'),1.1],
                            'flat':[None,-1,True,'2',2.5], 'vial_level':[None,-2,4,True,'-1']}.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    snap = self.snapshot(self.game(**{key:value}))
                    self.assertNotIn(key, snap['data']['buffs'][0])
                    self.assertNotIn('next_heal', snap['data']['buffs'][0])
                    option = self.option(snap)
                    self.assertEqual(option['values'], [])
                    self.assertIn('未确认', option['calculation_missing'])
        game = self.game()
        del game['hero']['buffs'][0]['percent']
        self.assertEqual(self.option(self.snapshot(game))['values'], [])
        game = self.game()
        game['hero']['buffs'].append(dict(game['hero']['buffs'][0]))
        self.assertEqual(self.option(self.snapshot(game))['values'], [])

    def test_version_challenge_locks_vial_and_known_resource_gates(self):
        for value in (None, 0, True, self.catalog.data['version_code']+1):
            game = self.game(); game['version'] = value
            self.assertEqual(self.option(self.snapshot(game))['values'], [])
        for value in (None, True, '0', -1, 512):
            game = self.game(); game['challenges'] = value
            self.assertEqual(self.option(self.snapshot(game))['values'], [])
        game = self.game(); game['challenges'] = 4
        option = self.option(self.snapshot(game))
        self.assertEqual(option['values'], [])
        self.assertIn('改为中毒', option['restriction'])
        for kind in ('Paralysis','TimeStasis','Frost','MagicalSleep'):
            game = self.game(); game['hero']['buffs'].append({'__className':PREFIX+'actors.buffs.'+kind})
            self.assertEqual(self.option(self.snapshot(game))['values'], [])
        game = self.game(); game['hero']['inventory'].append({'__className':PREFIX+'items.trinkets.VialOfBlood', 'level':2, 'levelKnown':False})
        option = self.option(self.snapshot(game))
        self.assertEqual(option['values'], [])
        self.assertIn('试管', option['calculation_missing'])
        game = self.game(); game['PotionOfHealing_known'] = False
        self.assertEqual(context_actions(SimpleNamespace(catalog=self.catalog), self.snapshot(game))['options'], [])

    def test_known_vial_multiplies_only_new_pool_and_sets_cap(self):
        game = self.game()
        game['hero']['inventory'].append({'__className':PREFIX+'items.trinkets.VialOfBlood', 'level':3, 'levelKnown':True})
        wait, drink = self.option(self.snapshot(game))['comparison']['scenarios']
        self.assertEqual((wait['pool'],wait['next_heal']), (80,10))
        self.assertEqual((drink['pool'],drink['next_heal'],drink['params']['vial']), (141,6,3))

    def test_missing_handbook_parameters_are_blank_and_not_calculated(self):
        detail = self.values.detail('actors.buffs.healing', {'hp':20,'max_hp':100,'power':80})
        self.assertEqual(set(detail['missing_inputs']), {'healing_percent','healing_flat','vial'})
        self.assertEqual({row['key']:row['value'] for row in detail['inputs'] if row['key'] in detail['missing_inputs']},
                         {'healing_percent':'','healing_flat':'','vial':''})
        self.assertFalse(any(row.get('values') for row in detail['blocks']))
        for raw in ({'power':1.5}, {'healing_percent':True}, {'healing_flat':-1}, {'vial':4}):
            with self.assertRaises(ValueError):self.values.detail('actors.buffs.healing', raw)

    def test_workspace_uses_exact_params_and_stamp_and_manual_presence_is_unknown(self):
        with tempfile.TemporaryDirectory(prefix='lamp-healing-synthetic-') as directory:
            path = Path(directory)
            config = path/'settings.json'
            config.write_text(json.dumps({'save_root':str(path/'synthetic-saves'), 'mode':'manual'}), encoding='utf-8')
            session = Session(config, self.catalog)
            snap = self.snapshot(stale=True)
            session.snapshot = lambda:snap
            row = next(row for row in session.workspace_status()['current'] if row['id']=='actors.buffs.healing')
            context = row['lookup_context']
            self.assertEqual({key:context['params'][key] for key in ('power','healing_percent','healing_flat','vial')},
                             {'power':80,'healing_percent':10,'healing_flat':2,'vial':-1})
            self.assertEqual(context['stamp'], [100,'synthetic-root','save',1,7,123])
            self.assertTrue(context['source']['stale'])
            self.assertEqual(set(context['field_origins']), {'power','healing_percent','healing_flat','vial'})
            session.snapshot = lambda:self.snapshot({'hero':{'HP':20,'HT':100,'lvl':5,'STR':10,
                                      'buffs':[{'__className':PREFIX+'actors.buffs.Healing'}]}, 'challenges':0}, mode='manual')
            row = next(row for row in session.workspace_status()['current'] if row['id']=='actors.buffs.healing')
            self.assertFalse(any(key in row['lookup_context']['params'] for key in ('power','healing_percent','healing_flat','vial')))
            self.assertIn('不套用', row['lookup_context']['conditions'])

    def test_potion_pool_uses_java_float_cast_edge(self):
        # 0.8f * 9995 rounds to 7996f, then +14 is cast to 8010.
        self.assertEqual(potion_healing_pool(9995), 8010)

    def test_float_saved_percent_keeps_precision_through_text_input(self):
        from companion.decisions import healing_context
        context = healing_context({'left':80,'percent':.10000000149011612,'flat':2,'vial_level':-1})
        detail = self.values.detail('actors.buffs.healing', {key:str(value) for key,value in context.items()})
        self.assertEqual(next(row['value'] for row in detail['inputs'] if row['key']=='healing_percent'), context['healing_percent'])


class NativeHealingWorkflowTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import Mock
        from companion.native_workspace import NumericLookup
        from tests.test_native_controllers import Host, Root, Worker
        temporary = tempfile.TemporaryDirectory(prefix='lamp-native-healing-synthetic-')
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name)
        config = path/'settings.json'
        config.write_text(json.dumps({'save_root':str(path/'synthetic-saves'),'mode':'manual'}), encoding='utf-8')
        self.session = Session(config)
        self.session.update_manual({'hp':20,'ht':100,'level':5})
        self.session.data['buffs'] = [{'kind':'Healing','name':'治疗','reference_id':'actors.buffs.healing',
                                      'left':80,'percent':.1,'flat':2,'vial_level':-1,'next_heal':10}]
        self.worker, self.host = Worker(), Host()
        manager = SimpleNamespace(session=self.session, root=Root(), native_ui=SimpleNamespace(host=self.host,report_drafts=Mock()))
        self.owner = SimpleNamespace(manager=manager,worker=self.worker,native=Mock(),pinned=None,peek_key=None)
        self.lookup = NumericLookup(self.owner)

    def finish(self):
        self.lookup.render(self.session.values.detail(*self.worker.args[1]))

    def open_current(self):
        row = next(row for row in self.session.workspace_status()['current'] if row['id']=='actors.buffs.healing')
        self.lookup.select_row(row)
        self.finish()
        return row

    def test_exact_context_manual_override_source_change_and_import_undo(self):
        row = self.open_current()
        self.assertEqual(self.lookup.raw_params()['power'], '80.0')
        self.assertEqual(self.lookup.raw_params()['healing_percent'], '10.0')
        self.assertIn('手动局势', self.lookup.input_origins['power'])
        self.lookup.variables['healing_percent'].set('40')
        self.lookup.calculate(); self.finish()
        self.assertEqual(self.lookup.input_origins['healing_percent'], '手填')
        prior = self.lookup.draft(include_result=True)
        self.session.revision += 1
        self.lookup.refresh_origin(self.session.snapshot())
        self.assertIn('旧参考', self.lookup.origin.text)
        self.lookup.open_reference({'entry':row['id'], **row['lookup_context']})
        self.lookup.handle({'action':'replace_decision','decision':'discard'})
        self.finish()
        self.assertEqual(self.lookup.raw_params()['healing_percent'], '10.0')
        self.lookup.undo_import()
        self.assertEqual(self.lookup.raw_params(), prior['raw_params'])
        self.assertEqual(self.lookup.input_origins, prior['origins'])
        self.assertEqual(self.lookup.calculated, prior['calculated'])

    def test_presence_only_is_blank_and_cannot_pin_or_save(self):
        self.session.data['buffs'] = [{'kind':'Healing','name':'治疗','reference_id':'actors.buffs.healing'}]
        self.open_current()
        self.assertEqual(self.lookup.raw_params()['power'], '')
        self.assertEqual(self.lookup.raw_params()['healing_percent'], '')
        self.assertEqual(self.lookup.input_origins['power'], '未确认 · 请填写')
        self.assertIsNone(self.lookup.calculated)
        self.lookup.pin()
        self.assertIsNone(self.owner.pinned)
        self.assertFalse(self.lookup.save_plan('不能保存虚构治疗状态'))


if __name__ == '__main__':
    unittest.main()
