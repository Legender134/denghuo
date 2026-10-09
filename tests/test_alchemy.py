"""Budget, identity and persistence acceptance for finite official alchemy adapters."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from companion.alchemy import MAX_INT, VERSION, VERSION_CODE, aggregate_ingredients, calculate, recipe_list, resources_from_snapshot
from companion.engine import Catalog
from companion.service import Session
from companion.session_exit import ExitDraftStore

HEALING = 'items.potions.potionofhealing'
IDENTIFY = 'items.scrolls.scrollofidentify'


def params(recipe='potion-healing', identity=HEALING, quantity=5, reserve=1, energy=18, energy_reserve=2, batches=3):
    return {'recipe': recipe, 'recipe_version': VERSION, 'batches': batches,
            'energy': energy, 'energy_reserve': energy_reserve, 'energy_origin': 'manual',
            'resources': [{'id': identity, 'quantity': quantity, 'reserve': reserve, 'origin': 'manual'}],
            'reference_version': None}


class AlchemyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='denghuo-alchemy-')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.session = Session(self.directory / 'settings.json', self.catalog)
        self.session.settings['save_root'] = str(self.directory / 'synthetic-saves')

    def test_ordinary_potion_and_scroll_exact_conversion_costs_and_outputs(self):
        potion = calculate(self.catalog, params())[1]
        self.assertEqual((potion['batches'], potion['max_batches'], potion['energy']['spent'], potion['energy']['remaining']), (3, 4, 12, 6))
        self.assertEqual(potion['output']['id'], 'items.potions.exotic.potionofshielding')
        self.assertEqual((potion['materials'][0]['spent'], potion['materials'][0]['remaining']), (3, 2))
        scroll = calculate(self.catalog, params('scroll-identify', IDENTIFY))[1]
        self.assertEqual((scroll['batches'], scroll['max_batches'], scroll['energy']['spent']), (2, 2, 12))
        self.assertFalse(scroll['within_budget'])
        self.assertEqual(scroll['output']['id'], 'items.scrolls.exotic.scrollofdivination')

    def test_zero_cost_runestones_use_one_scroll_and_output_two(self):
        result = calculate(self.catalog, params('stone-identify', IDENTIFY, energy=0, energy_reserve=0, batches=4))[1]
        self.assertEqual((result['max_batches'], result['batches'], result['output']['quantity']), (4, 4, 8))
        self.assertEqual(result['energy']['spent'], 0)

    def test_material_and_energy_reserves_are_never_spent(self):
        for q, keep, energy, energy_keep, expected in [(9, 7, 100, 0, 2), (9, 1, 15, 8, 1), (9, 9, 20, 0, 0), (9, 0, 20, 20, 0)]:
            result = calculate(self.catalog, params(quantity=q, reserve=keep, energy=energy, energy_reserve=energy_keep, batches=100))[1]
            self.assertEqual(result['batches'], expected)
            self.assertGreaterEqual(result['materials'][0]['remaining'], keep)
            self.assertGreaterEqual(result['energy']['remaining'], energy_keep)
            self.assertEqual(result['output']['quantity'], expected)
        zero = calculate(self.catalog, params(batches=0))[1]
        self.assertEqual((zero['output']['quantity'], zero['materials'][0]['spent'], zero['energy']['spent']), (0, 0, 0))

    def test_duplicate_ingredient_specifications_are_merged_once(self):
        recipe = copy.deepcopy(next(r for r in recipe_list(self.catalog) if r['id'] == 'potion-healing'))
        recipe['inputs'] *= 2
        self.assertEqual(aggregate_ingredients(recipe['inputs']), {HEALING: 2})
        with patch('companion.alchemy.recipe_list', return_value=[recipe]):
            result = calculate(self.catalog, params(quantity=5, reserve=1, energy=100, energy_reserve=0))[1]
        self.assertEqual((result['max_batches'], result['batches'], result['materials'][0]['spent'], result['materials'][0]['remaining']), (2, 2, 4, 1))
        args = params(); args['resources'] *= 2
        with self.assertRaisesRegex(ValueError, '同一材料'):
            calculate(self.catalog, args)

    def test_multi_material_recipe_and_real_output_quantity(self):
        args = params('recipe-elixirofaquaticrejuvenation', quantity=4, reserve=1, energy=100, energy_reserve=0)
        args['resources'].append({'id': 'items.quest.gooblob', 'quantity': 2, 'reserve': 1, 'origin': 'manual'})
        result = calculate(self.catalog, args)[1]
        self.assertEqual((result['max_batches'], result['batches'], result['energy']['spent']), (1, 1, 6))
        self.assertEqual([(r['spent'], r['remaining']) for r in result['materials']], [(1, 3), (1, 1)])
        aqua = calculate(self.catalog, params('recipe-aquabrew', 'items.potions.exotic.potionofstormclouds', energy=100, energy_reserve=0))[1]
        self.assertEqual(aqua['output']['quantity'], 24)

    def test_inputs_are_finite_bounded_integers_not_boolean_or_coerced(self):
        for key in ('batches', 'energy', 'energy_reserve'):
            for value in (True, -1, 1.5, '2', float('nan'), float('inf'), MAX_INT + 1):
                args = params(); args[key] = value
                with self.assertRaises(ValueError): calculate(self.catalog, args)
        for key in ('quantity', 'reserve'):
            for value in (False, -1, 1.5, '2', MAX_INT + 1):
                args = params(); args['resources'][0][key] = value
                with self.assertRaises(ValueError): calculate(self.catalog, args)
        for args in (params(reserve=6), params(energy_reserve=19)):
            with self.assertRaises(ValueError): calculate(self.catalog, args)

    def test_unknown_identity_extra_material_and_unknown_origin_are_rejected(self):
        for identity in ('items.potions.crimson', 'items.potions.potionoffrost', 'unknown'):
            with self.assertRaises(ValueError): calculate(self.catalog, params(identity=identity))
        args = params(); args['resources'][0]['origin'] = 'unknown'
        with self.assertRaisesRegex(ValueError, '未知身份'): calculate(self.catalog, args)

    def test_game_integer_output_limit_and_material_energy_limits(self):
        args = params('recipe-aquabrew', 'items.potions.exotic.potionofstormclouds', quantity=MAX_INT, reserve=0, energy=MAX_INT, energy_reserve=0, batches=MAX_INT)
        result = calculate(self.catalog, args)[1]
        self.assertLessEqual(result['output']['quantity'], MAX_INT)
        self.assertLessEqual(result['energy']['spent'], MAX_INT)

    def test_snapshot_import_excludes_unknown_unavailable_and_other_versions(self):
        snap = {'settings': {'mode': 'save'}, 'modified': 1700000000, 'active_slot': 2,
                'data': {'version': VERSION_CODE, 'energy': 17.0, 'items': [
                    {'key': HEALING, 'quantity': 2, 'known': True, 'available': True},
                    {'key': HEALING, 'quantity': 3, 'known': True, 'available': True},
                    {'key': HEALING, 'quantity': 40, 'known': False, 'available': True},
                    {'key': IDENTIFY, 'quantity': 10, 'known': True, 'available': False}]}}
        with patch.object(self.session, 'snapshot', return_value=snap):
            imported = resources_from_snapshot(self.session)
        self.assertEqual(imported['resources'], [{'id': HEALING, 'quantity': 5, 'origin': 'known'}])
        self.assertEqual((imported['energy'], imported['unknown_excluded']), (17, 1))
        snap['data']['version'] = 1000
        with patch.object(self.session, 'snapshot', return_value=snap):
            self.assertEqual(resources_from_snapshot(self.session)['resources'], [])
            self.assertIsNone(resources_from_snapshot(self.session)['energy'])

    def test_version_difference_known_reference_and_old_recipes_are_not_guessed(self):
        args = params(); args['reference_version'] = 1000
        self.assertIn('版本不同', ' '.join(calculate(self.catalog, args)[1]['warnings']))
        args['resources'][0]['origin'] = 'known'
        with self.assertRaisesRegex(ValueError, '版本'): calculate(self.catalog, args)
        args = params(); args['recipe_version'] = '3.0'
        with self.assertRaisesRegex(ValueError, '版本'): calculate(self.catalog, args)
        changed = copy.copy(self.catalog); changed.data = {**self.catalog.data, 'version': '5.0'}
        with self.assertRaisesRegex(ValueError, '版本'): calculate(changed, params())
        args = params(); args['recipe'] = 'recipe-not-yet-supported'
        with self.assertRaisesRegex(ValueError, '尚未收录'): calculate(self.catalog, args)

    def test_save_reopen_note_copy_cas_and_import_export_keep_fixed_conditions(self):
        store = self.session.knowledge
        first = self.session.workspace_action({'action': 'save', 'kind': 'alchemy', 'entry': None,
                                               'name': '首领前保留治疗', 'params': params(), 'note': '只做两瓶，先留一瓶'})['plan']
        self.session.update_manual({'hp': 1, 'ht': 40, 'healing': 40})
        opened = store.reopen(first['id'])
        self.assertEqual(opened['plan']['params'], params())
        self.assertEqual(opened['result']['energy']['quantity'], 18)
        self.assertEqual(opened['plan']['note'], '只做两瓶，先留一瓶')
        other = Session(self.session.config_path, self.catalog).knowledge
        updated = store.save('一号窗口更新', 'alchemy', None, params(batches=1), record_id=first['id'], expected_record_revision=first['record_revision'], note='变更保留用途')
        before = store.path.read_bytes()
        with self.assertRaisesRegex(ValueError, '另一窗口'):
            other.save('二号窗口', 'alchemy', None, params(batches=2), record_id=first['id'], expected_record_revision=first['record_revision'])
        self.assertEqual(before, store.path.read_bytes())
        copied = other.save('二号窗口副本', 'alchemy', None, params(batches=2), note=updated['note'])
        self.assertNotEqual(copied['id'], first['id'])
        destination = Session(self.directory / 'import' / 'settings.json', self.catalog).knowledge
        self.assertEqual(destination.import_records(store.export())['plans_added'], 2)
        self.assertEqual(destination.reopen(copied['id'])['plan']['params'], copied['params'])
        self.assertEqual(store.import_records(store.export())['plans_added'], 0)

    def test_legacy_format1_notes_and_unknown_recipe_retention(self):
        store = self.session.knowledge
        store.save('旧手动方案', 'manual', None, {'hp': 1, 'ht': 30})
        store.save('旧炼金参考', 'alchemy', None, params())
        raw = json.loads(store.export())
        for row in raw['plans']: row.pop('note')
        raw['plans'][0]['params']['recipe'] = 'removed-in-future'
        target = Session(self.directory / 'legacy' / 'settings.json', self.catalog).knowledge
        target.import_records(json.dumps(raw).encode())
        self.assertTrue(target.status()['available'])
        self.assertTrue(all(row['note'] == '' for row in target.status()['plans']))
        with self.assertRaisesRegex(ValueError, '尚未收录'): target.reopen(raw['plans'][0]['id'])

    def test_workspace_actions_and_handbook_basic_conversion_discoverability(self):
        response = self.session.workspace_action({'action': 'alchemy-calculate', 'params': params()})
        self.assertEqual(response['result']['kind'], 'alchemy')
        self.assertEqual(len(self.session.workspace_status()['alchemy']['recipes']), 61)
        for identity, recipe, cost in [(HEALING, 'potion-healing', 4), (IDENTIFY, 'scroll-identify', 6)]:
            detail = self.session.values.detail(identity)
            self.assertIn(recipe, [r['id'] for r in detail['alchemy_recipes']])
            self.assertTrue(any(b['title'].startswith('炼金转换') and any(v['label'] == '能量消耗' and str(v['value']) == str(cost) for v in b['values']) for b in detail['blocks']))

    def test_two_window_invalid_raw_exit_drafts_remain_uncomputed(self):
        drafts = ExitDraftStore(self.directory / 'unfinished')
        records = []
        for surface, bad in [('web-11111111', '-'), ('web-22222222', '无效数量')]:
            draft = {'format': 1, 'schema': 'denghuo-web-session', 'alchemy': {'raw': {'recipe': 'potion-healing', 'batches': bad, 'energy': '', 'energy_reserve': '0', 'resources': [{'id': HEALING, 'quantity': 'NaN', 'reserve': '0', 'origin': 'manual'}]}, 'saved_id': None, 'note': '保留原始假设'}}
            records.append(drafts.save(surface, 'web-session', '炼金原始草稿', draft))
        resumed = ExitDraftStore(self.directory / 'unfinished')
        self.assertEqual(len(resumed.list()), 2)
        for record, bad in zip(records, ['-', '无效数量']):
            restored = resumed.load(record['id'])['draft']['alchemy']
            self.assertEqual(restored['raw']['batches'], bad)
            self.assertEqual(restored['raw']['resources'][0]['quantity'], 'NaN')
            self.assertNotIn('result', restored)
        self.assertFalse(self.session.knowledge.path.exists())


if __name__ == '__main__':
    unittest.main()
