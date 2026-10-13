"""Workspace transport and filtering; GUI acceptance uses the isolated live helper."""
import json
import copy
from queue import Queue
import unittest
from unittest.mock import Mock
from companion.native_host import NativeHost, MAX_LINE
from companion.native_workspace import NumericLookup
from companion.character_scene import calculate_scene, empty_scene
from tests.test_native_controllers import ControllerFixture

class NativeWorkspaceTests(unittest.TestCase):
    def test_plan_timestamp_bounds_keep_valid_rows_and_identities(self):
        from datetime import datetime, timezone
        from companion.native_workspace import plan_updated_text
        expected = datetime.fromtimestamp(10, timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
        self.assertEqual(plan_updated_text(10), expected)
        self.assertEqual(plan_updated_text(1700000000), datetime.fromtimestamp(1700000000, timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M"))
        lookup = NumericLookup.__new__(NumericLookup)
        lookup.owner, lookup.host = Mock(), Mock()
        rows = [{'id': 'a'*32, 'name': '早期', 'kind': 'numeric', 'updated': 10},
                {'id': 'b'*32, 'name': '超出范围', 'kind': 'numeric', 'updated': 999999999999}]
        lookup.owner.manager.session.workspace_status.return_value = {'available': True, 'plans': rows}
        lookup.choose_plan()
        emitted = lookup.host.command.call_args.kwargs['rows']
        self.assertEqual([row['id'] for row in emitted], ['b'*32, 'a'*32])
        self.assertIn('时间超出本机显示范围', emitted[0]['text'])
        self.assertIn(expected, emitted[1]["text"])

    def test_character_filter_label_and_exact_identity_handoff(self):
        rows = [{'id': 'a'*32, 'name': '同名条件', 'note': '根骨之戒需要核对', 'kind': 'character', 'updated': 30},
                {'id': 'b'*32, 'name': '同名条件', 'note': '', 'kind': 'character', 'updated': 20},
                {'id': 'c'*32, 'name': '数值', 'note': '根骨之戒', 'kind': 'numeric', 'updated': 40}]
        lookup = NumericLookup.__new__(NumericLookup); lookup.owner, lookup.host = Mock(), Mock()
        lookup.owner.manager.session.workspace_status.return_value = {'available': True, 'plans': rows}
        lookup.choose_plan(query='根骨之戒', kind='角色条件')
        emitted = lookup.host.command.call_args.kwargs['rows']
        self.assertEqual([row['id'] for row in emitted], ['a'*32])
        self.assertIn('角色条件', emitted[0]['text'])
        self.assertEqual(NumericLookup.filtered_plans(rows, kind='角色条件', order='名称'), rows[:2])
        lookup.owner.manager.session.knowledge.reopen.return_value = {'plan': rows[1]}
        lookup.emit = Mock()
        lookup.origin = Mock()
        self.assertTrue(lookup.open_plan('b'*32, False))
        lookup.owner.manager.native_ui.workspace.open_plan.assert_called_once_with({'plan': rows[1]})
        lookup.owner.manager.session.panel.request.assert_not_called()

    def test_plan_filter_keeps_opaque_identity_and_stable_name_order(self):
        rows=[{'id':'a'*32,'name':'Beta','kind':'numeric','updated':10}, {'id':'b'*32,'name':'Alpha','kind':'numeric','updated':5}, {'id':'c'*32,'name':'Manual','kind':'manual','updated':11}]
        found=NumericLookup.filtered_plans(rows,kind='数值方案',order='名称')
        self.assertEqual([row['name'] for row in found],['Alpha','Beta'])
        self.assertEqual(NumericLookup.filtered_plans(rows,'bEtA')[0]['id'],'a'*32)
        self.assertEqual(NumericLookup.filtered_plans(rows,'missing'),[])

    def test_reopening_plan_picker_keeps_filters_and_refreshes_matching_records(self):
        rows = [
            {'id': 'a'*32, 'name': 'Beta', 'note': 'NeedLE', 'kind': 'character', 'updated': 30},
            {'id': 'b'*32, 'name': 'Alpha', 'note': 'needle', 'kind': 'character', 'updated': 20},
            {'id': 'c'*32, 'name': 'Other', 'kind': 'character', 'updated': 40},
            {'id': 'd'*32, 'name': 'Alpha', 'note': 'needle', 'kind': 'alchemy', 'updated': 50},
        ]
        lookup = NumericLookup.__new__(NumericLookup)
        lookup.owner, lookup.host, lookup.emit = Mock(), Mock(), Mock()
        lookup.owner.manager.session.workspace_status.return_value = {'available': True, 'plans': rows}
        lookup.handle({'action': 'filter_plans', 'query': ' nEeDlE ', 'kind': '角色条件', 'order': '名称'})
        self.assertEqual([row['id'] for row in lookup.host.command.call_args.kwargs['rows']], ['b'*32, 'a'*32])
        rows.append({'id': 'e'*32, 'name': 'Able', 'note': 'needle', 'kind': 'character', 'updated': 10})
        lookup.handle({'action': 'choose_plan'})
        self.assertEqual([row['id'] for row in lookup.host.command.call_args.kwargs['rows']],
                         ['e'*32, 'b'*32, 'a'*32])
        lookup.handle({'action': 'filter_plans', 'query': '', 'kind': '全部类型', 'order': '最近更新'})
        self.assertEqual([row['id'] for row in lookup.host.command.call_args.kwargs['rows']],
                         ['d'*32, 'c'*32, 'a'*32, 'b'*32, 'e'*32])
        lookup.handle({'action': 'choose_plan'})
        self.assertEqual([row['id'] for row in lookup.host.command.call_args.kwargs['rows']],
                         ['d'*32, 'c'*32, 'a'*32, 'b'*32, 'e'*32])

    def test_alchemy_filter_preserves_identity_labels_and_both_orders(self):
        rows = [
            {'id': 'd'*32, 'name': 'Beta', 'kind': 'alchemy', 'updated': 20},
            {'id': 'c'*32, 'name': 'Alpha', 'kind': 'alchemy', 'updated': 10},
            {'id': 'b'*32, 'name': 'Alpha', 'kind': 'alchemy', 'updated': 10},
            {'id': 'a'*32, 'name': 'Alpha', 'kind': 'numeric', 'updated': 30},
            {'id': 'e'*32, 'name': 'Alpha', 'kind': 'equipment', 'updated': 40},
            {'id': 'f'*32, 'name': 'Alpha', 'kind': 'manual', 'updated': 50},
        ]
        self.assertEqual([row['id'] for row in NumericLookup.filtered_plans(rows, kind='炼金方案')],
                         ['d'*32, 'b'*32, 'c'*32])
        self.assertEqual([row['id'] for row in NumericLookup.filtered_plans(rows, ' ALPHA ', '炼金方案', '名称')],
                         ['b'*32, 'c'*32])
        lookup = NumericLookup.__new__(NumericLookup)
        lookup.owner, lookup.host = Mock(), Mock()
        lookup.owner.manager.session.workspace_status.return_value = {'available': True, 'plans': rows}
        lookup.choose_plan(kind='炼金方案', order='名称')
        action, = lookup.host.command.call_args.args
        emitted = lookup.host.command.call_args.kwargs['rows']
        self.assertEqual(action, 'plans')
        self.assertEqual([row['id'] for row in emitted], ['b'*32, 'c'*32, 'd'*32])
        self.assertEqual([row['text'].split(' · ')[:2] for row in emitted],
                         [['Alpha', '炼金方案'], ['Alpha', '炼金方案'], ['Beta', '炼金方案']])

    def host(self):
        host=NativeHost.__new__(NativeHost);host.closed=False;host.serial=host.revision=0
        host.session='a'*32;host.outgoing=Queue(maxsize=1);host.error=Mock()
        return host

    def test_utf8_protocol_carries_version_request_and_revision(self):
        host=self.host();host.revision=42
        self.assertTrue(host.command('lookup_state',note='中文用途'))
        value=json.loads(host.outgoing.get().decode('utf-8'))
        self.assertEqual((value['version'],value['request'],value['revision']),(1,1,42))
        self.assertEqual(value['note'],'中文用途')

    def test_full_output_queue_returns_visible_error_without_blocking(self):
        host=self.host();host.command('first')
        self.assertFalse(host.command('second'))
        host.error.assert_called_once()
        self.assertFalse(host.command('lookup_state',result='x'*(MAX_LINE+1)))

    def test_disconnected_bridge_stops_new_commands_and_duplicate_errors(self):
        host=self.host();host.ready=True;host.root=Mock();host.dispatch=Mock();host.incoming=Queue(maxsize=4)
        host.incoming.put({'action':'bridge_error','message':'EOF fixture'})
        host.incoming.put({'action':'bridge_error','message':'pipe fixture'})
        host.incoming.put({'action':'edit','values':{'hp':'new inaccessible input'}})
        host.poll()
        self.assertFalse(host.ready)
        self.assertTrue(host.failed)
        host.error.assert_called_once_with('EOF fixture')
        host.dispatch.assert_not_called()
        self.assertFalse(host.command('manager_state'))
        self.assertTrue(host.outgoing.empty())


class NativeStrengthWorkflowTests(ControllerFixture):
    def test_ring_primary_answer_uses_selected_effect_and_both_curse_states(self):
        self.open('items.rings.ringofaccuracy')
        payload=self.host.commands[-1][1]
        self.assertEqual([row['value'] for row in payload['primary_values']], ['1.3', '0.591716'])
        self.assertTrue(all('命中倍率' in row['label'] for row in payload['primary_values']))
        self.assertIn('正常', payload['primary_values'][0]['label'])
        self.assertIn('诅咒', payload['primary_values'][1]['label'])
        self.lookup.variables['level'].set('12'); self.lookup.calculate(); self.finish()
        payload=self.host.commands[-1][1]
        self.assertIn('+12', payload['primary_note'])
        self.assertEqual(payload['primary_values'][0]['value'], '30.2875')
        self.lookup.variables['level'].set('-'); self.lookup.changed('level')
        self.assertEqual(self.host.commands[-1][1]['primary_values'], [])

    def test_failed_then_pending_calculation_reports_state_preserves_raw_and_blocks_repeat(self):
        self.open('items.potions.potionofhealing')
        self.lookup.variables['hp'].set('  '); self.lookup.calculate()
        payload=self.host.commands[-1][1]
        self.assertIn('填写',payload['parameter_error'])
        self.assertFalse(payload['calculating']); self.assertFalse(payload['can_save'])
        self.assertEqual(self.lookup.raw_params()['hp'],'  ')
        self.lookup.variables['hp'].set('3'); self.lookup.calculate()
        ticket=self.worker.ticket; payload=self.host.commands[-1][1]
        self.assertTrue(payload['calculating']); self.assertFalse(payload['can_save'])
        self.assertEqual(payload['primary_values'],[])
        self.lookup.calculate(); self.assertEqual(self.worker.ticket,ticket)
        self.finish(); payload=self.host.commands[-1][1]
        self.assertFalse(payload['calculating']); self.assertEqual(payload['parameter_error'],'')
        self.assertTrue(payload['can_save']); self.assertTrue(payload['focus_result'])

    def test_edit_during_pending_calculation_cancels_busy_without_accepting_old_answer(self):
        self.open('items.potions.potionofhealing')
        self.lookup.variables['hp'].set('3'); self.lookup.calculate()
        self.lookup.variables['hp'].set('  1e  ')
        self.assertFalse(self.host.commands[-1][1]['calculating'])
        self.finish()
        self.assertEqual(self.lookup.raw_params()['hp'],'  1e  ')
        self.assertFalse(self.host.commands[-1][1]['can_save'])
        self.assertEqual(self.host.commands[-1][1]['primary_values'],[])

    def test_primary_healing_answer_is_structured_and_revoked_by_half_input(self):
        self.session.update_manual({'hp': 36, 'ht': 60, 'level': 8})
        self.open('items.potions.potionofhealing')
        payload = self.host.commands[-1][1]
        self.assertEqual([(row['label'], row['value']) for row in payload['primary_values']],
                         [('最终实际恢复', '24'), ('首次恢复', '16')])
        self.assertIn('药水恐惧', payload['primary_note'])
        self.assertIn('手填局势', payload['origin_brief'])
        self.assertTrue(payload['can_save'])
        self.lookup.variables['hp'].set('  1e  ')
        payload = self.host.commands[-1][1]
        self.assertEqual(payload['primary_values'], [])
        self.assertFalse(payload['can_save'])
        self.assertTrue(payload['needs_calculation'])
        self.assertEqual(next(row['raw'] for row in payload['fields'] if row['key']=='hp'), '  1e  ')
        self.lookup.variables['hp'].set('30')
        self.lookup.calculate(); self.finish()
        self.assertTrue(self.host.commands[-1][1]['focus_result'])
        self.assertTrue(self.host.commands[-1][1]['can_save'])

    def test_provenance_and_missing_conditions_never_publish_old_primary_answer(self):
        self.open('items.potions.potionofhealing')
        self.assertTrue(self.host.commands[-1][1]['primary_values'])
        self.lookup.handle({'action': 'provenance'})
        self.assertEqual(self.host.commands[-1][1]['primary_values'], [])
        self.open('actors.buffs.corrosion')
        payload = self.host.commands[-1][1]
        self.assertEqual(payload['primary_values'], [])
        self.assertFalse(payload['can_save'])
        self.assertTrue(payload['needs_calculation'])

    def test_favorite_label_state_tracks_the_persisted_toggle(self):
        self.open('items.potions.potionofhealing')
        self.assertFalse(self.host.commands[-1][1]['favorite'])
        self.lookup.favorite()
        self.assertTrue(self.host.commands[-1][1]['favorite'])
        self.assertIn(self.lookup.identity, self.session.workspace_status()['favorite_ids'])
        self.lookup.favorite()
        self.assertFalse(self.host.commands[-1][1]['favorite'])
        self.assertNotIn(self.lookup.identity, self.session.workspace_status()['favorite_ids'])

    def test_numeric_sections_keep_columns_current_row_conditions_and_full_result(self):
        for identity, params in (('items.wands.wandoffireblast', {'level': 3}),
                                 ('items.weapon.melee.spear', {'level': 3}),
                                 ('items.potions.potionofhealing', {'hp': 12, 'max_hp': 35})):
            with self.subTest(identity=identity):
                self.open(identity)
                for key, value in params.items(): self.lookup.variables[key].set(str(value))
                self.lookup.calculate(); self.finish()
                payload = self.host.commands[-1][1]
                original = self.lookup.rendered['blocks']
                sections = payload['numeric_sections']
                self.assertEqual(len(sections), len(original))
                for section in sections:
                    block = original[section['index']]
                    for key, value in block.items(): self.assertEqual(section[key], value)
                    self.assertEqual(section['collapsed'], bool(block.get('columns')))
                    if 'selected_row' in block:
                        self.assertEqual(section['selected_values'], [{'label': label, 'value': value}
                            for label, value in zip(block['columns'], block['rows'][block['selected_row']])])
                self.assertEqual(payload['result'], self.lookup.text.text)
                self.assertIn(self.lookup.rendered['notice'], payload['result_prose'])
                self.assertNotIn('装备等级 /', payload['result_prose'])
                self.assertTrue('values' in sections[0] or sections[0]['selected_values'])
                before = copy.deepcopy(original)
                sections[0]['title'] = 'transport edit'
                self.assertEqual(self.lookup.rendered['blocks'], before)

    def test_numeric_sections_hide_stale_values_and_preserve_sources_or_provenance_text(self):
        self.lookup.open_reference({'entry': 'items.weapon.melee.spear', 'params': {'level': 3},
                                    'source_label': '独立存档记录'}, {'mode': 'example'}, '仅基础参考')
        self.finish(); self.lookup.note.set('玩家用途')
        payload = self.host.commands[-1][1]
        for text in ('独立存档记录', '仅基础参考', '玩家用途'):
            self.assertIn(text, payload['result_prose'])
        self.lookup.handle({'action': 'provenance'})
        payload = self.host.commands[-1][1]
        self.assertEqual(payload['numeric_sections'], [])
        self.assertEqual(payload['result_prose'], payload['result'])
        self.lookup.variables['level'].set('1e')
        payload = self.host.commands[-1][1]
        self.assertEqual(payload['numeric_sections'], [])
        self.assertIn('重新计算', payload['result'])
        for text in ('独立存档记录', '仅基础参考', '玩家用途'):
            self.assertIn(text, payload['result_prose'])
        self.assertNotIn('最低基础伤害', payload['result_prose'])

    def test_unknown_damage_family_is_not_labeled_as_healing(self):
        self.open('actors.buffs.corrosion')
        self.assertEqual(set(self.lookup.rendered['missing_inputs']), {'power', 'remaining_turns'})
        self.assertIn('当前条件未确认', self.lookup.origin.text)
        self.assertNotIn('治疗', self.lookup.origin.text)
        self.assertIsNone(self.lookup.calculated)
        self.assertTrue(all(self.lookup.raw_params()[key] == '' for key in ('power', 'remaining_turns')))
        current = next(section for section in self.host.commands[-1][1]['numeric_sections'] if section['title'] == '当前酸蚀状态')
        self.assertEqual(current['values'], [])
        self.assertEqual(current['selected_values'], [])

    def set_scene(self, params):
        self.session.update_manual({'hp': 4, 'ht': 30, 'level': 5,
                                    'strength': params['base_strength'], 'character_scene': params})

    def test_known_total_strength_default_and_dependency_change_keep_captured_values(self):
        scene = empty_scene(10); scene['rings'] = [{'identity': 'items.rings.ringofmight', 'level': 2, 'cursed': False}]
        scene['strongman'] = 2; scene['adrenaline'] = 2
        self.set_scene(scene); self.open('items.rings.ringofforce')
        expected = calculate_scene(scene)['strength']['effective']
        self.assertEqual(self.lookup.variables['strength'].get(), str(expected))
        self.assertIn('角色总力量', self.lookup.input_origins['strength'])
        self.assertIn('基础 10', self.lookup.input_origins['strength'])
        self.assertIn('根骨之戒 3', self.lookup.text.text)
        self.assertIn('力大无穷 1', self.lookup.text.text)
        snap = self.session.snapshot(); prior = self.lookup.raw_params()
        changed = dict(scene, adrenaline=5); self.set_scene(changed)
        current = self.session.snapshot(); current.update({key: snap.get(key) for key in ('revision', 'modified')})
        self.lookup.refresh_origin(current)
        self.assertIn('旧参考', self.lookup.origin.text)
        self.assertEqual(self.lookup.raw_params(), prior)

    def test_unknown_conditions_use_explicit_base_reference_and_missing_labels(self):
        scene = empty_scene(11); scene['rings'] = [{'identity': 'items.rings.ringofmight', 'level': None, 'cursed': None}]
        self.set_scene(scene); self.open('items.rings.ringofforce')
        self.assertEqual(self.lookup.variables['strength'].get(), '11')
        self.assertIn('基础力量参考 11', self.lookup.input_origins['strength'])
        self.assertIn('总力量未确认', self.lookup.input_origins['strength'])
        self.assertIn('根骨之戒1等级或诅咒', self.lookup.text.text)
        self.assertNotIn('角色总力量 11', self.lookup.input_origins['strength'])

    def test_known_total_outside_numeric_bounds_keeps_explicit_base_reference(self):
        scene = empty_scene(1000); scene['adrenaline'] = 1000
        self.set_scene(scene); self.open('items.rings.ringofforce')
        self.assertEqual(self.lookup.variables['strength'].get(), '1000')
        self.assertIn('基础力量参考 1000', self.lookup.input_origins['strength'])
        self.assertIn('总力量超出当前数值工具范围', self.lookup.text.text)

    def test_current_equipment_context_captures_its_strength_conditions(self):
        scene = empty_scene(12); scene['rings'] = [{'identity': 'items.rings.ringofmight', 'level': 1, 'cursed': False}]
        self.set_scene(scene)
        item = self.session.catalog.item({'__className': 'com.shatteredpixel.shatteredpixeldungeon.items.rings.RingOfForce',
            'levelKnown': True, 'cursedKnown': True, 'level': 0, 'quantity': 1}, {'RingOfForce_known': True})
        item['available'] = True
        self.session.data['items'] = [item]
        # Real workspace status supplies both item context and the matching scene stamp.
        self.lookup.search(); row = next(row for row in self.lookup.rows if row['id'] == 'items.rings.ringofforce')
        self.lookup.select_row(row); self.finish()
        self.assertEqual(self.lookup.variables['strength'].get(), '14')
        self.assertIn('角色总力量 14', self.lookup.input_origins['strength'])
        self.assertIn('根骨之戒 2', self.lookup.text.text)
        status = self.session.workspace_status()
        status['character_scene']['stamp'] = list(status['character_scene']['stamp'])
        status['character_scene']['stamp'][-1] -= 1
        self.session.workspace_status = Mock(return_value=status)
        self.lookup.search(); row = next(row for row in self.lookup.rows if row['id'] == 'items.rings.ringofforce')
        self.lookup.select_row(row); self.finish()
        self.assertIn('力量参考 · 角色条件来源未确认', self.lookup.input_origins['strength'])
        self.assertNotIn('角色总力量 14', self.lookup.input_origins['strength'])

    def test_manual_saved_and_pinned_reference_does_not_follow_new_scene(self):
        self.set_scene(empty_scene(12)); self.open('items.rings.ringofforce')
        self.lookup.variables['strength'].set('17'); self.lookup.calculate(); self.finish()
        self.assertEqual(self.lookup.input_origins['strength'], '手填')
        self.assertIn('明确手填参考', self.lookup.text.text)
        self.assertTrue(self.lookup.save_plan('固定力量参考'))
        plan = self.lookup.saved_plan; self.lookup.pin()
        self.set_scene(empty_scene(20)); self.lookup.search(preserve_detail=True)
        self.assertEqual(self.lookup.variables['strength'].get(), '17')
        self.assertEqual(self.owner.pinned[1]['strength'], 17)
        self.lookup.open_plan(plan['id'], False)
        self.assertEqual(self.lookup.variables['strength'].get(), '17')
        self.assertIn('固定参数', self.lookup.origin.text)
        self.assertEqual(self.lookup.saved_plan['origin']['fields']['strength'], '手填')

    def test_imported_strength_without_matching_source_is_never_called_current_total(self):
        self.set_scene(empty_scene(19))
        self.lookup.open_reference({'entry': 'items.rings.ringofforce', 'params': {'strength': 13}},
            {'mode': 'save', 'snapshot_at': 1, 'slot': 2}, '旧参考限制')
        self.finish()
        self.assertEqual(self.lookup.variables['strength'].get(), '13')
        self.assertIn('保存的力量参考', self.lookup.input_origins['strength'])
        self.assertIn('不能视为当前总力量', self.lookup.text.text)

    def test_character_and_v1_v2_alchemy_plans_keep_exact_ids_and_never_replace_numeric_draft(self):
        from companion.alchemy import VERSION
        character = self.session.knowledge.save('角色条件', 'character', None, empty_scene(13))
        legacy = self.session.knowledge.save('旧炼金', 'alchemy', None,
            {'recipe': 'potion-healing', 'recipe_version': VERSION, 'batches': 1,
             'energy': 4, 'energy_reserve': 0, 'energy_origin': 'manual',
             'resources': [{'id': 'items.potions.potionofhealing', 'quantity': 1,
                            'reserve': 0, 'origin': 'manual'}], 'reference_version': None})
        target = self.session.knowledge.save('目标炼金', 'alchemy', None,
            {'format': 2, 'recipe_version': VERSION, 'targets': [{'key': 'g1', 'recipe': 'potion-healing',
              'quantity': 1, 'choices': {}}], 'resources': [], 'energy': 4, 'energy_reserve': 0,
             'energy_origin': 'manual', 'reference_version': None, 'chains': {}})
        original = self.session.workspace_status()['plans']
        self.session.panel.request = Mock()
        for plan in (character, legacy, target):
            self.assertTrue(self.lookup.open_plan(plan['id'], False))
            self.session.panel.request.assert_called_with('workspace', plan_id=plan['id'])
        self.assertEqual(self.session.workspace_status()['plans'], original)
        self.open('items.rings.ringofforce'); self.lookup.variables['strength'].set('invalid original')
        calls = self.session.panel.request.call_count
        for plan in (character, legacy, target):
            self.assertTrue(self.lookup.open_plan(plan['id']))
            self.assertEqual(self.lookup.variables['strength'].get(), 'invalid original')
            self.assertTrue(self.lookup.dirty)
            self.assertIsNone(self.lookup.confirmation)
            calls += 1
            self.assertEqual(self.session.panel.request.call_count, calls)
            self.session.panel.request.assert_called_with('workspace', plan_id=plan['id'])


if __name__=='__main__':unittest.main()
