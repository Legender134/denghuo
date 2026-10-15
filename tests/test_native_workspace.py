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


class NativeCatalogBrowseTests(ControllerFixture):
    def test_categories_favorites_and_browse_all_keep_unsaved_input(self):
        self.open('items.potions.potionofhealing')
        self.lookup.favorite()
        self.lookup.variables['max_hp'].set('1e')
        for category in ('药剂', '敌人与角色', '收藏', '最近'):
            self.assertIn(category, self.lookup.categories())
            self.lookup.handle({'action': 'browse', 'category': category})
            self.assertTrue(self.lookup.rows)
            self.assertEqual(self.lookup.raw_params()['max_hp'], '1e')
            self.assertTrue(self.lookup.has_draft())
            if category == '药剂':
                self.assertTrue(all(row['id'].startswith('items.potions.') for row in self.lookup.rows))
            elif category not in ('收藏', '最近'):
                self.assertTrue(all(row['category'] == category for row in self.lookup.rows))
        self.lookup.handle({'action': 'browse', 'category': '全部'})
        first = [row['id'] for row in self.lookup.rows]
        self.assertEqual(len(first), 30)
        self.assertFalse(self.lookup.suggested)
        self.assertEqual(len(first), len(set(first)))
        self.lookup.more_results()
        self.assertFalse(self.lookup.suggested)
        self.assertEqual(len(self.lookup.rows), 60)
        self.lookup.handle({'action': 'browse', 'category': '常用'})
        self.assertTrue(self.lookup.suggested)
        self.lookup.more_results()
        self.assertEqual(self.lookup.category, '全部')
        self.assertEqual(len(self.lookup.rows), 30)
        self.assertEqual(self.lookup.raw_params()['max_hp'], '1e')

    def test_current_object_has_one_row_and_related_calculation_preserves_capture(self):
        from companion.native_host import binding_token
        item = self.session.catalog.item({'__className': 'com.shatteredpixel.shatteredpixeldungeon.items.weapon.melee.Longsword',
            'levelKnown': True, 'cursedKnown': True, 'level': 2, 'quantity': 1}, {})
        item['available'] = True
        self.session.data['items'] = [item]
        self.lookup.handle({'action': 'browse', 'category': '随身'})
        self.assertEqual(len(self.lookup.rows), 1)
        row = self.lookup.rows[0]
        self.assertTrue(row['related'])
        self.lookup.select_row(row); self.finish()
        related = self.lookup.related_rows()[0]
        self.lookup.handle({'action': 'related', 'index': 0, 'token': binding_token(related)})
        self.finish()
        self.assertEqual(self.lookup.identity, related['id'])
        self.assertEqual(self.lookup.context, related['lookup_context'])
        self.assertEqual(self.lookup.variables['level'].get(), '2')
        self.assertIn('升级前等级', self.lookup.text.text)
        self.assertEqual(self.lookup.related_rows(), [])

    def test_npc_description_and_dangerous_npc_are_distinguished(self):
        self.open('actors.mobs.npcs.imp')
        payload = self.host.commands[-1][1]
        self.assertTrue(payload['introduction'])
        self.assertIn(payload['introduction'], payload['description'])
        self.assertEqual(payload['primary_values'], [])
        self.open('actors.mobs.npcs.vaultsentry')
        payload = self.host.commands[-1][1]
        self.assertFalse(payload['primary_values'])
        self.assertIn('扫描', ' '.join(payload['reading_notes']))


class NativeStrengthWorkflowTests(ControllerFixture):
    def test_water_primary_distinguishes_timing_shield_and_unavailable_water(self):
        self.open('items.waterskin')
        for params, expected, note in (
            ({'vial': -1}, [('即时恢复', '80')], '不含已有治疗'),
            ({'vial': 0}, [('首次恢复', '19'), ('逐回合合计', '80')], '不再受伤'),
            ({'vial': 3}, [('首次恢复', '6'), ('逐回合合计', '80')], '不能直接相加'),
            ({'vial': 0, 'shielding_dew': 1}, [('首次恢复', '19'), ('逐回合合计', '80')], '另增屏障 20 点'),
            ({'vial': -1, 'shielding_dew': 1}, [('即时恢复', '80'), ('新增屏障', '20')], '不含已有治疗'),
            ({'dew_volume': 0}, [('可用露珠', '0')], '无法饮用'),
            ({'hp': 100}, [('即时恢复', '0')], '消耗 1 滴，剩 19 滴'),
        ):
            with self.subTest(params=params):
                result = self.session.values.detail('items.waterskin',
                    {'hp': 20, 'max_hp': 100, 'dew_volume': 20, 'vial': -1, **params})
                primary, summary = self.lookup.primary_presentation(result['blocks'])
                self.assertEqual([(row['label'], row['value']) for row in primary], expected)
                self.assertIn(note, summary)
                self.assertTrue(any(row['label'] == '实际新增屏障' for row in result['blocks'][0]['values']))

    def test_invisibility_answer_keeps_break_condition_and_one_base_duration(self):
        self.open('actors.buffs.invisibility')
        payload = self.host.commands[-1][1]
        answer = payload['primary_values'][0]
        self.assertEqual(answer['value'], '20')
        self.assertIn('攻击和施法会解除', answer['condition'])
        self.assertIn('当前剩余', answer['condition'])
        duration = [value for section in payload['numeric_sections'] for value in section.get('values', [])
                    if value['label'] in ('基础持续时间', '默认持续')]
        self.assertEqual(len(duration), 1)

    def test_special_monster_mechanisms_and_boundaries_precede_full_stats(self):
        for identity, expected in [('goo', '双方弹道'), ('eye', '重新瞄准'), ('necromancer', '落点阻塞'),
                                   ('dm300', '当前供能塔'), ('yogfist$rottingfist', '60%'),
                                   ('yogfist$rustedfist', '延迟池'), ('yogfist$soiledfist', '清掉草')]:
            self.open('actors.mobs.'+identity)
            payload = self.host.commands[-1][1]
            self.assertEqual(payload['primary_values'], [])
            self.assertIn(expected, ' '.join(payload['reading_notes']))
            self.assertIn('普通基础参考', payload['primary_note'])
            self.assertTrue(any(row['title']=='常规战斗数值' for row in payload['numeric_sections']))
            self.assertFalse(any(row['title']=='粘咕攻击阶段' for row in payload['numeric_sections']))
            self.lookup.variables['hero_level'].set('1e')
            self.assertEqual(self.host.commands[-1][1]['reading_notes'], [])
            self.lookup.dirty = self.lookup.draft_modified = False

    def test_primary_plant_and_water_effects_keep_activation_conditions(self):
        for identity, condition in (
            ('plants.mageroyal', '守望者'),
            ('plants.mageroyal$seed', '守望者'),
            ('plants.sungrass$seed', '离开原地会中断'),
            ('items.potions.elixirs.elixirofaquaticrejuvenation', '未漂浮'),
        ):
            with self.subTest(identity=identity):
                self.open(identity)
                payload = self.host.commands[-1][1]
                self.assertIn(condition, payload['primary_values'][0]['condition'])
                if identity.endswith('$seed'):
                    self.assertIn('种植触发后', payload['origin_brief'])
                if 'aquaticrejuvenation' in identity:
                    self.assertIn('药水恐惧下不治疗', payload['primary_values'][0]['condition'])
                    self.assertEqual(payload['primary_values'][1]['label'], '水中每回合实际恢复')
                    self.assertIn('逐回合', payload['primary_note'])

    def test_ordinary_monster_leads_with_hidden_combat_rules_and_keeps_full_table(self):
        self.open('actors.mobs.rat')
        payload=self.host.commands[-1][1]
        self.assertEqual([(r['label'],r['value']) for r in payload['primary_values']],
                         [('普攻','1–4'),('减伤','0–1'),('移速','1')])
        combat=next(section for section in payload['numeric_sections'] if section['title']=='常规战斗数值')
        self.assertEqual(len(combat['values']),10)
        self.assertEqual([r['value'] for r in combat['values'][:2]],['8','8'])
        self.open('actors.mobs.necromancer$necroskeleton')
        self.assertTrue(self.host.commands[-1][1]['reading_notes'])
        combat=next(section for section in self.host.commands[-1][1]['numeric_sections'] if section['title']=='常规战斗数值')
        self.assertEqual([r['value'] for r in combat['values'][:2]],['20','25'])

    def test_non_attacking_monster_primary_answer_keeps_mechanism_condition(self):
        self.open('actors.mobs.pylon')
        payload=self.host.commands[-1][1]
        self.assertFalse(payload['primary_values'])
        notes=' '.join(payload['reading_notes'])
        self.assertIn('激活后邻格电击伤害',notes)
        self.assertIn('10–20',notes)
        self.assertIn('未激活时不攻击且无敌',notes)

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

    def test_tenacity_primary_answer_keeps_hp_assumption_and_negative_semantics(self):
        self.open('items.rings.ringoftenacity')
        answers = []
        for hp in (50, 90):
            self.lookup.variables['max_hp'].set('100'); self.lookup.variables['hp'].set(str(hp))
            self.lookup.calculate(); self.finish(); payload = self.host.commands[-1][1]
            self.assertIn(f'当前生命 {hp}/100', payload['primary_note'])
            self.assertIn('负数表示增伤', payload['primary_note'])
            self.assertIn('正常', payload['primary_values'][0]['label'])
            self.assertIn('诅咒', payload['primary_values'][1]['label'])
            answers.append(float(payload['primary_values'][0]['value']))
            self.assertLess(float(payload['primary_values'][1]['value']), 0)
        self.assertGreater(answers[0], answers[1])
        self.lookup.variables['hp'].set('-'); self.lookup.changed('hp')
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

    def test_healing_potion_public_vial_initial_latest_and_undo(self):
        from companion.engine import PREFIX, analyze
        game = {'version': self.session.catalog.data['version_code'], 'challenges': 0, 'depth': 6,
            'hero': {'class': 'WARRIOR', 'lvl': 8, 'HP': 32, 'HT': 90, 'STR': 12, 'buffs': [],
                'inventory': [{'__className': PREFIX+'items.trinkets.VialOfBlood', 'level': 3, 'levelKnown': True}]}}
        snap = self.session.snapshot()
        snap.update(data=analyze(game, self.session.catalog), active_slot=1)
        snap['settings']['mode'] = 'save'
        self.session.snapshot = lambda: snap
        self.open('items.potions.potionofhealing')
        self.assertEqual(self.lookup.raw_params()['vial'], '3')
        payload = self.host.commands[-1][1]
        self.assertEqual(payload['primary_values'][1]['value'], '6')
        self.assertIn('凝血试管 +3', payload['primary_note'])
        self.assertIn('快照', payload['primary_note'])
        self.lookup.variables['vial'].set('2'); self.lookup.calculate(); self.finish()
        snap['data']['items'][0]['level'] = 0
        self.lookup.refresh_origin(snap); self.lookup.emit()
        self.assertEqual(self.lookup.raw_params()['vial'], '2', 'polling preserves deliberate manual reference')
        self.lookup.use_latest(); self.finish()
        self.assertEqual(self.lookup.raw_params()['vial'], '0')
        self.assertEqual(self.host.commands[-1][1]['primary_values'][1]['value'], '18')
        self.lookup.undo_import()
        self.assertEqual(self.lookup.raw_params()['vial'], '2')
        self.assertEqual(self.lookup.input_origins['vial'], '手填')

    def test_healing_potion_captured_context_only_supplements_matching_snapshot(self):
        from companion.engine import PREFIX, analyze
        game = {'version': self.session.catalog.data['version_code'], 'challenges': 0, 'depth': 6,
            'hero': {'class': 'WARRIOR', 'lvl': 8, 'HP': 32, 'HT': 90, 'STR': 12, 'buffs': [],
                'inventory': [{'__className': PREFIX+'items.trinkets.VialOfBlood', 'level': 3, 'levelKnown': True}]}}
        snap = self.session.snapshot(); snap['settings']['mode'] = 'save'
        snap.update(data=analyze(game, self.session.catalog), active_slot=1)
        self.session.snapshot = lambda: snap
        row = copy.deepcopy(next(row for row in self.session.catalog.entries if row['id']=='items.potions.potionofhealing'))
        row['lookup_context'] = {'params': NumericLookup.hero_context(snap), 'stamp': NumericLookup.source_stamp(snap), 'mode': 'save'}
        self.lookup.select_row(row); self.finish()
        self.assertEqual(self.lookup.raw_params()['vial'], '3')
        row['lookup_context']['stamp'] = (None,)*6
        self.lookup.select_row(row); self.finish()
        self.assertNotIn('vial', self.lookup.context['params'])
        self.assertIn('示例', self.host.commands[-1][1]['primary_note'])
        self.assertNotIn('未佩戴', self.host.commands[-1][1]['primary_note'])

    def test_unconfirmed_vial_and_manual_inventory_do_not_claim_absence(self):
        from companion.engine import PREFIX, analyze
        game = {'version': self.session.catalog.data['version_code'], 'challenges': 0, 'depth': 6,
            'hero': {'class': 'WARRIOR', 'lvl': 8, 'HP': 32, 'HT': 90, 'STR': 12, 'buffs': [],
                'inventory': [{'__className': PREFIX+'items.trinkets.VialOfBlood', 'level': 3, 'levelKnown': False}]}}
        snap = self.session.snapshot(); snap['settings']['mode'] = 'save'
        snap.update(data=analyze(game, self.session.catalog), active_slot=1)
        self.session.snapshot = lambda: snap
        for identity in ('items.potions.potionofhealing', 'items.potions.elixirs.elixirofhoneyedhealing'):
            self.open(identity)
            self.assertNotIn('vial', self.lookup.context['params'])
            self.assertIn('示例', self.host.commands[-1][1]['primary_note'])
            self.lookup.use_latest(); self.finish()
            self.assertIn('示例', self.host.commands[-1][1]['primary_note'])
            self.assertIn('未确认', self.lookup.input_origins['vial'])
        snap['settings']['mode'] = 'manual'; snap['data']['items'] = []
        self.assertNotIn('vial', NumericLookup.entry_context(snap, 'items.potions.potionofhealing')['params'])

    def test_dot_primary_answers_state_their_example_or_manual_condition(self):
        for identity, labels, note in (
            ('actors.buffs.poison', ['首次毒伤', '完整毒伤总量'], '后续续毒'),
            ('actors.buffs.bleeding', ['下一次流血', '预计总流血伤害'], '平均估计')):
            self.open(identity)
            payload = self.host.commands[-1][1]
            self.assertEqual([row['label'] for row in payload['primary_values']], labels)
            self.assertIn('示例', payload['primary_note'])
            self.assertIn(note, payload['primary_note'])
            self.lookup.variables['power'].set('4'); self.lookup.calculate(); self.finish()
            self.assertIn('手填', self.host.commands[-1][1]['primary_note'])
            self.lookup.variables['power'].set('1e')
            self.assertEqual(self.host.commands[-1][1]['primary_values'], [])

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
        self.lookup.handle({'action': 'browse', 'category': '随身'})
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
