"""Actual JavaScript payloads into persistence; synthetic public equipment only."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from companion.engine import Catalog
from companion.knowledge import KnowledgeWorkspace
from companion.rules import NumericRules
from companion.values import PlayerValues
from tests.test_native_controllers import ControllerFixture

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')


class SavedPlanContracts(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.catalog = Catalog(ROOT / 'data/catalog.json')
        self.session = SimpleNamespace(catalog=self.catalog, values=PlayerValues(NumericRules(self.catalog)))
        self.store = KnowledgeWorkspace(Path(self.directory.name) / 'knowledge.json', self.session)

    def wire(self, kind, identity, items=None, ack=None, **options):
        result = subprocess.run([NODE, str(ROOT / 'tools/verify_saved_plan_contracts.js'), '--wire'],
            input=json.dumps({'kind': kind, 'id': identity, 'items': items, 'ack': ack, **options}),
            text=True, encoding='utf-8', capture_output=True, check=True)
        return json.loads(result.stdout)

    def save_payload(self, payload):
        return self.store.save(**{key: value for key, value in payload.items() if key != 'action'})

    @unittest.skipUnless(NODE, 'Node.js is required for the frontend persistence contract')
    def test_five_families_actual_frontend_new_reopen_update_and_strict_fields(self):
        for kind, identity in [('weapon', 'items.weapon.melee.sword'), ('armor', 'items.armor.mailarmor'),
                ('missile', 'items.weapon.missiles.throwingknife'), ('wand', 'items.wands.wandofmagicmissile'),
                ('ring', 'items.rings.ringofmight')]:
            with self.subTest(kind=kind):
                wire = self.wire(kind, identity)
                saved = self.save_payload(wire['payloads'][0])
                opened = self.store.reopen(saved['id'])
                self.assertEqual(opened['plan']['note'], '固定备注')
                self.assertEqual(set(saved['origin']['fields']) - set(saved['params']), set())
                self.assertIsNotNone(opened['result'])
                update = self.wire(kind, identity, ack=saved)['payloads'][1]
                self.assertEqual(update['expected_record_revision'], saved['record_revision'])
                changed = self.save_payload(update)
                self.assertEqual(changed['id'], saved['id'])
                self.assertEqual(changed['note'], '更新备注')
                self.assertEqual(self.store.reopen(saved['id'])['plan']['origin'], changed['origin'])
                extra = copy.deepcopy(wire['payloads'][0]);extra['source']['fields']['irrelevant'] = '不使用的条件'
                with self.assertRaisesRegex(ValueError, '不使用'):
                    self.save_payload(extra)
                from companion.character_scene import empty_scene
                scene = empty_scene();scene['base_strength'] = 14
                planned = self.wire(kind, identity, planning=True, character=scene)['payloads'][0]
                budget_saved = self.save_payload(planned)
                self.assertEqual(budget_saved['params']['upgrade_budget'], 2)
                self.assertEqual(budget_saved['params']['character_scene']['base_strength'], 14)
                self.assertIsNotNone(self.store.reopen(budget_saved['id'])['result'])

    @unittest.skipUnless(NODE, 'Node.js is required for the frontend persistence contract')
    def test_public_same_base_identity_independent_copy_import_and_bad_metadata(self):
        identity = 'items.weapon.melee.sword'
        items = [dict(key=identity, name=name, owned=True, level=2,
            equipment_state={'effect_id': 'items.weapon.enchantments.'+effect},
            user_note={'title': label, 'body': '独立玩家正文', 'scope': 'specific_item'})
            for name, effect, label in [('烈焰单手剑 +2', 'blazing', '主手火剑'), ('寒霜单手剑 +2', 'chilling', '备用冰剑')]]
        payload = self.wire('weapon', identity, items)['payloads'][0]
        saved = self.save_payload(payload)
        reopened = self.store.reopen(saved['id'])
        rendered = subprocess.run([NODE, str(ROOT / 'tools/verify_saved_plan_contracts.js'), '--reopen'],
            input=json.dumps(reopened), text=True, encoding='utf-8', capture_output=True)
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        self.assertEqual(json.loads(rendered.stdout)['references'], saved['origin']['references'])
        self.assertNotIn('references', saved['params'])
        self.assertEqual(saved['origin']['references']['b']['user_note']['title'], '备用冰剑')
        duplicate = self.save_payload({**payload, 'name': '独立副本'})
        self.assertNotEqual(saved['id'], duplicate['id'])
        self.assertEqual(saved['origin'], duplicate['origin'])
        other = KnowledgeWorkspace(Path(self.directory.name) / 'imported.json', self.session)
        other.import_records(self.store.export())
        self.assertEqual(other.reopen(saved['id'])['plan']['origin'], saved['origin'])
        for mutate in (lambda r: r['a'].update(id='items.weapon.melee.axe'),
                lambda r: r['a'].update(hidden='secret'), lambda r: r['a']['user_note'].update(body='x'*501)):
            bad = copy.deepcopy(payload);mutate(bad['source']['references'])
            with self.assertRaises(ValueError):self.save_payload(bad)
        legacy = copy.deepcopy(payload);del legacy['source']['references']
        self.assertIsNotNone(self.store.reopen(self.save_payload(legacy)['id'])['result'])

    def test_supported_old_shape_unavailable_calculation_preserves_original_record_and_bytes(self):
        row = {'id': '1'*32, 'name': '旧版回旋镖', 'kind': 'numeric', 'entry': 'items.weapon.missiles.boomerang',
            'params': {'level': 3}, 'rules_version': '2.0.0', 'created': 10, 'updated': 10,
            'origin': {'kind': 'saved_reference', 'mode': 'save', 'snapshot_at': 100, 'slot': 2, 'fields': {'level': '原公开等级'}},
            'note': '保留的用途备注'}
        self.store.import_records(json.dumps({'format': 1, 'favorites': [], 'recent': [], 'plans': [row]}).encode())
        before = self.store.path.read_bytes()
        opened = self.store.reopen(row['id'])
        self.assertIsNone(opened['result']);self.assertTrue(opened['calculation_error'])
        self.assertEqual({key: opened['plan'][key] for key in row}, row)
        self.assertEqual(self.store.export(), before)
        self.assertEqual(self.store.path.read_bytes(), before)
        with self.assertRaises(ValueError):self.store.save('禁止新算', 'numeric', row['entry'], row['params'], row['origin'])


class NativeSavedPlanContracts(ControllerFixture):
    def test_unavailable_original_record_opens_without_result_dictionary(self):
        row = {'id': '9'*32, 'name': '原记录', 'kind': 'numeric', 'entry': 'items.weapon.missiles.boomerang',
            'params': {'level': 3}, 'rules_version': '2.0.0', 'created': 10, 'updated': 10,
            'origin': {'kind': 'saved_reference', 'mode': 'example', 'snapshot_at': None, 'slot': None}, 'note': '原备注'}
        self.session.knowledge.import_records(json.dumps({'format': 1, 'favorites': [], 'recent': [], 'plans': [row]}).encode())
        before = self.session.knowledge.path.read_bytes()
        self.session.panel.request = Mock()
        self.assertTrue(self.lookup.open_plan(row['id'], False))
        self.session.panel.request.assert_called_once_with('workspace', plan_id=row['id'])
        self.assertIn('当前版本无法计算', self.lookup.text.text)
        self.assertIn('"level": 3', self.lookup.text.text)
        self.assertIn('原备注', self.lookup.text.text)
        self.assertFalse(self.lookup.has_draft())
        self.assertEqual(self.session.knowledge.path.read_bytes(), before)
        self.session.panel.request = Mock(side_effect=ValueError('synthetic unavailable browser'))
        self.assertTrue(self.lookup.open_plan(row['id'], False))
        self.assertIn('synthetic unavailable browser', self.lookup.origin.text)
        self.assertIn('"level": 3', self.lookup.text.text)
        self.assertEqual(self.session.knowledge.path.read_bytes(), before)

    def test_exit_copy_snapshot_has_pending_name_note_and_no_controller_mutation(self):
        self.open('items.weapon.melee.sword')
        self.lookup.set_pending_save({'name': '待保存名称', 'note': '待保存备注', 'update': True})
        prior = copy.deepcopy(self.lookup.draft(include_result=True))
        captured = self.lookup.exit_copy_payload()
        self.assertEqual(captured['kind'], 'plan')
        self.assertEqual(captured['payload']['name'], '待保存名称 草稿副本')
        self.assertEqual(captured['payload']['note'], '待保存备注')
        self.assertEqual(set(captured['payload']['source']['fields']), set(captured['payload']['params']))
        self.assertEqual(self.lookup.draft(include_result=True), prior)
        self.lookup.set_pending_save({'name': '', 'note': '未完成', 'update': False})
        self.assertEqual(self.lookup.exit_copy_payload()['kind'], 'raw')
        self.lookup.set_pending_save({'name': '名称', 'note': '非法\t备注', 'update': False})
        self.assertEqual(self.lookup.exit_copy_payload()['kind'], 'raw')
        self.lookup.set_pending_save({'name': '待保存名称', 'note': '待保存备注', 'update': True})
        self.lookup.variables['level'].set('unfinished')
        raw = self.lookup.exit_copy_payload()
        self.assertEqual(raw['kind'], 'raw')
        self.assertEqual(raw['draft']['pending_save']['name'], '待保存名称')
        self.lookup.set_pending_save({'name': '', 'note': '未完成', 'update': False})
        self.assertEqual(raw['draft']['pending_save']['name'], '待保存名称')


if __name__ == '__main__':
    unittest.main()
