"""Persistence-level conflict acceptance for separate windows and records."""
from pathlib import Path
import tempfile
import unittest

from companion.engine import Catalog
from companion.native_workspace import NumericLookup
from companion.service import Session


class WorkspaceConcurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='lamp-plan-cas-')
        self.addCleanup(temporary.cleanup)
        self.config = Path(temporary.name) / 'settings.json'
        self.a = Session(self.config, self.catalog)
        self.b = Session(self.config, self.catalog)

    def plan(self, name='窗口一', note='初始条件'):
        return self.a.knowledge.save(name, 'numeric', 'items.potions.potionofhealing',
                                     {'hp': 10, 'max_hp': 40}, note=note)

    def test_stale_delete_cannot_remove_a_new_revision_or_change_its_bytes(self):
        prior = self.plan()
        updated = self.a.knowledge.save('另一窗口的新条件', prior['kind'], prior['entry'], {'hp': 20, 'max_hp': 40},
            record_id=prior['id'], expected_record_revision=prior['record_revision'], note='新备注不能被旧确认删除')
        original = self.a.knowledge.path.read_bytes()
        for revision in (None, '', prior['record_revision']):
            with self.assertRaisesRegex(ValueError, '旧删除确认已失效'):
                self.b.workspace_action({'action': 'remove', 'id': prior['id'], 'confirmed': True,
                                         'expected_record_revision': revision})
            self.assertEqual(self.a.knowledge.path.read_bytes(), original)
        self.assertEqual(self.b.knowledge.reopen(prior['id'])['plan'], updated)

    def test_current_delete_ignores_other_record_and_favorite_updates(self):
        selected = self.plan()
        other = self.plan('保留的另一方案', '蛇层备选\nTARGET Beta')
        self.a.knowledge.favorite('items.waterskin', True)
        self.b.workspace_action({'action': 'remove', 'id': selected['id'], 'confirmed': True,
                                 'expected_record_revision': selected['record_revision']})
        status = self.a.knowledge.status()
        self.assertEqual([row['id'] for row in status['plans']], [other['id']])
        self.assertEqual(status['favorites'], ['items.waterskin'])
        with self.assertRaisesRegex(ValueError, '已不存在'):
            self.b.workspace_action({'action': 'remove', 'id': selected['id'], 'confirmed': True,
                                     'expected_record_revision': selected['record_revision']})

    def test_original_naming_revision_rejects_old_payload_and_allows_an_independent_copy(self):
        prior = self.plan()
        self.a.knowledge.save('最新条件', prior['kind'], prior['entry'], {'hp': 20, 'max_hp': 40},
            record_id=prior['id'], expected_record_revision=prior['record_revision'], note='最新备注')
        with self.assertRaisesRegex(ValueError, '另一窗口'):
            self.b.workspace_action({'action': 'save', 'name': '找回的命名草稿', 'kind': prior['kind'],
                'entry': prior['entry'], 'params': prior['params'], 'note': '找回的原始备注',
                'record_id': prior['id'], 'expected_record_revision': prior['record_revision']})
        copy = self.b.knowledge.save('找回副本', prior['kind'], prior['entry'], prior['params'], note='找回的原始备注')
        self.assertNotEqual(copy['id'], prior['id'])
        self.assertEqual(copy['params']['hp'], 10)
        self.assertEqual(self.a.knowledge.reopen(prior['id'])['plan']['params']['hp'], 20)

    def test_native_name_note_search_preserves_filter_order_and_notes(self):
        rows = [
            {'id': 'a'*32, 'name': 'Alpha', 'kind': 'numeric', 'updated': 20, 'note': '蛇层备选\nTARGET Beta'},
            {'id': 'b'*32, 'name': 'Beta', 'kind': 'alchemy', 'updated': 30, 'note': '蛇层备选'},
            {'id': 'c'*32, 'name': 'Gamma', 'kind': 'numeric', 'updated': 10},
        ]
        self.assertEqual([row['id'] for row in NumericLookup.filtered_plans(rows, ' 蛇层备选 ')], ['b'*32, 'a'*32])
        self.assertEqual([row['id'] for row in NumericLookup.filtered_plans(rows, 'target beta', '数值方案')], ['a'*32])
        self.assertEqual([row['id'] for row in NumericLookup.filtered_plans(rows, '蛇层备选', order='名称')], ['a'*32, 'b'*32])
        self.assertEqual(rows[0]['note'], '蛇层备选\nTARGET Beta')


if __name__ == '__main__':
    unittest.main()
