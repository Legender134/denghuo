"""Delayed native events retain their rendered target and captured provenance."""
import copy
from types import SimpleNamespace
from unittest.mock import Mock, patch

from companion.decisions import context_actions
from companion.native_host import binding_token
from companion.native_manager import NativeManager
from test_native_controllers import ControllerFixture


class ReferenceHandoffTests(ControllerFixture):
    def search(self, text):
        self.lookup.query.set(text)
        self.lookup.search(preserve_detail=True)
        return copy.deepcopy(self.lookup.rows[0])

    def test_old_search_click_cannot_open_new_row_or_discard_draft(self):
        self.open('items.potions.potionofhealing')
        self.lookup.variables['hp'].set('  7 ')
        old = self.search('items.potions.potionofhealing')
        new = self.search('actors.buffs.burning')
        self.assertNotEqual(old['id'], new['id'])
        self.lookup.handle({'action': 'select', 'index': 0, 'token': binding_token(old)})
        self.assertEqual(self.lookup.identity, 'items.potions.potionofhealing')
        self.assertEqual(self.lookup.raw_params()['hp'], '  7 ')
        self.assertIsNone(self.lookup.confirmation)
        self.assertIn('搜索结果已更新', self.lookup.workspace_error)
        self.lookup.handle({'action': 'select', 'index': 0, 'token': binding_token(new)})
        self.assertIsNotNone(self.lookup.confirmation)
        self.lookup.handle({'action': 'replace_decision', 'decision': 'discard'})
        self.assertEqual(self.lookup.identity, new['id'])

    def test_unchanged_search_rows_keep_valid_token_across_emit(self):
        row = self.search('actors.buffs.burning')
        self.lookup.emit()
        self.search('actors.buffs.burning')
        self.lookup.handle({'action': 'select', 'index': 0, 'token': binding_token(row)})
        self.assertEqual(self.lookup.identity, row['id'])

    def test_source_menu_cannot_retarget_link_after_detail_changes(self):
        self.open('items.potions.potionofhealing')
        old_token = self.lookup.source_token()
        self.open('actors.buffs.burning')
        self.lookup.note.set('尚未保存')
        with patch('companion.native_workspace.webbrowser.open') as opened:
            self.lookup.handle({'action': 'source_link', 'index': 0, 'token': old_token})
            opened.assert_not_called()
            self.assertEqual(self.lookup.note.get(), '尚未保存')
            self.lookup.handle({'action': 'source_link', 'index': 0, 'token': self.lookup.source_token()})
            opened.assert_called_once_with(self.lookup.rendered['provenance']['links'][0]['url'])

    def reference(self):
        actions = context_actions(self.session, self.session.snapshot())
        return next(ref for risk in actions['risks'] for ref in risk['references']
                    if ref['entry'] == 'items.potions.potionofhealing')

    def test_confirmation_handoff_preserves_old_snapshot_and_copies_caller(self):
        ref = self.reference()
        captured = copy.deepcopy(ref)
        self.open('actors.buffs.burning')
        self.lookup.note.set('旧草稿')
        self.lookup.open_reference(ref)
        self.assertIsNotNone(self.lookup.confirmation)
        self.session.update_manual({'hp': 20})
        ref['params']['hp'] = 29
        ref['stamp'][-1] = -1
        self.lookup.handle({'action': 'replace_decision', 'decision': 'discard'})
        self.finish()
        self.assertEqual(self.lookup.calculated['hp'], 4)
        self.assertEqual(self.lookup.context['stamp'], tuple(captured['stamp']))
        self.assertIn('旧参考', self.lookup.origin.text)
        self.assertTrue(self.lookup.save_plan('保留原始来源'))
        self.assertEqual(set(self.lookup.saved_plan['origin']), {'kind', 'mode', 'snapshot_at', 'slot', 'fields'})
        self.assertNotIn(str(self.directory), str(self.lookup.saved_plan['origin']))

    def test_missing_stamp_is_unconfirmed_and_can_save_without_path(self):
        ref = self.reference()
        ref.pop('stamp')
        self.lookup.open_reference(ref)
        self.finish()
        self.assertIsNone(self.lookup.context['stamp'])
        self.assertIn('来源未确认', self.lookup.origin.text)
        self.assertTrue(self.lookup.save_plan('旧来源未确认'))
        self.assertNotIn('stamp', self.lookup.saved_plan['origin'])

    def test_manager_references_bind_payload_even_if_same_index(self):
        native = NativeManager.__new__(NativeManager)
        native.frozen = False
        native.manager = SimpleNamespace(open_reference=Mock())
        native.error = Mock()
        native.report_drafts = Mock()
        native.session = self.session
        native.update = Mock()
        native.host = self.host
        old = ({'entry': 'actors.buffs.burning', 'params': {}}, {}, '')
        new = ({'entry': 'actors.buffs.corrosion', 'params': {}}, {}, '')
        native.references = [new]
        native.dispatch({'action': 'reference', 'index': 0, 'token': binding_token(old)})
        native.manager.open_reference.assert_not_called()
        native.error.assert_called_once()
        native.dispatch({'action': 'reference', 'index': 0, 'token': binding_token(new)})
        native.manager.open_reference.assert_called_once_with(*new)
