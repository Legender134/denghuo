"""Player journeys across captured items, generated floors and save history."""
import copy
import json
from unittest.mock import patch

from tests import test_game_workspace as fixtures
from companion.engine import PREFIX


class NativeProductWorkflows(fixtures.ControllerFixture):
    def setUp(self):
        super().setUp()
        self.jobs = []
        self.native = fixtures.SimpleNamespace(session=self.session, host=self.host,
            report_drafts=fixtures.Mock(), error=fixtures.Mock(), manager=self.manager,
            queue_io=lambda label, work, finish: self.jobs.append((work, finish)))
        self.workspace = fixtures.GameWorkspace(self.native)
        self.manager.native_ui.workspace = self.workspace

    saved_game = fixtures.GameWorkspaceTests.saved_game
    select = fixtures.GameWorkspaceTests.select
    finish_job = fixtures.GameWorkspaceTests.finish_job

    def item_reference(self, kind, *, known=True):
        root, slot = self.saved_game()
        game = json.loads((slot/'game.dat').read_text())
        game['hero']['inventory'] = [{'__className': PREFIX+'items.'+kind,
            'level': 3, 'levelKnown': known, 'cursedKnown': known, 'cursed': False}]
        if 'Ring' in kind:
            game['RingOfMight_known'] = known
        for number, strength in ((1, 12), (2, 16)):
            folder = root/f'game{number}'
            folder.mkdir(exist_ok=True)
            data = copy.deepcopy(game)
            data['hero']['STR'] = strength
            (folder/'game.dat').write_text(json.dumps(data), encoding='utf-8')
            if number == 2:
                (folder/'depth2.dat').write_bytes((slot/'depth2.dat').read_bytes())
        self.session.refresh()
        self.manager.open_reference = self.lookup.open_reference
        self.select('inventory', self.workspace.inventory()[0])
        if not known:
            self.workspace.inventory_action('reveal'); self.finish_job()
        self.workspace.inventory_action('reference'); self.finish()
        return root, slot

    def switch_slot(self):
        self.session.update_settings({'slot': 2})
        self.session.refresh()

    def test_revealed_item_without_character_inputs_keeps_original_source(self):
        self.item_reference('rings.RingOfMight', known=False)
        self.assertIn('主动揭示', self.lookup.input_origins['level'])
        self.assertIn('未改变游戏鉴定状态', self.lookup.context['conditions'])
        before = self.lookup.draft(include_result=True)
        self.switch_slot()
        ticket = self.worker.ticket
        self.lookup.use_latest()
        self.assertEqual(self.worker.ticket, ticket)
        self.assertEqual(self.lookup.draft(include_result=True), before)
        self.assertIn('没有可带入', self.lookup.operation_receipt)
        self.assertTrue(self.lookup.save_plan('原槽位揭示戒指'))
        self.assertEqual(self.lookup.saved_plan['origin']['slot'], 1)
        self.assertIn('主动揭示', self.lookup.saved_plan['origin']['fields']['level'])

    def test_partial_character_import_persists_distinct_item_and_character_sources(self):
        self.item_reference('weapon.melee.Katana')
        self.switch_slot()
        self.lookup.use_latest(); self.finish()
        self.assertEqual(self.lookup.calculated['level'], 3)
        self.assertEqual(self.lookup.calculated['strength'], 16)
        self.assertIn('槽位 1', self.lookup.input_origins['level'])
        self.assertIn('槽位 2', self.lookup.input_origins['strength'])
        self.assertIn('混合来源', self.lookup.origin_brief)
        self.assertTrue(self.lookup.exit_copy_payload()['payload']['source']['mixed_snapshots'])
        self.assertTrue(self.lookup.save_plan('跨槽位武器试算'))
        record = copy.deepcopy(self.lookup.saved_plan)
        self.assertTrue(record['origin']['mixed_snapshots'])
        self.lookup.open_plan(record['id'], False)
        self.assertEqual(self.lookup.input_origins, record['origin']['fields'])
        self.assertEqual(self.lookup.calculated['strength'], 16)

    def test_manual_item_level_and_raw_draft_survive_character_import_and_undo(self):
        self.item_reference('weapon.melee.Katana')
        self.lookup.variables['level'].set('  1e ')
        before = self.lookup.draft(include_result=True)
        self.switch_slot(); self.lookup.use_latest()
        self.assertEqual(self.lookup.raw_params()['level'], '  1e ')
        self.assertEqual(self.lookup.input_origins['level'], '手填')
        self.lookup.undo_import()
        restored = self.lookup.draft(include_result=True)
        for key in ('raw_params', 'origins', 'context', 'calculated', 'rendered', 'dirty', 'draft_modified'):
            self.assertEqual(restored[key], before[key], key)

    def test_revealed_item_conditions_remain_after_same_snapshot_character_import(self):
        self.item_reference('weapon.melee.Katana', known=False)
        for _ in range(3):
            self.lookup.use_latest(); self.finish()
            self.assertIn('未改变游戏鉴定状态', self.lookup.context['conditions'])
            self.assertIn('主动揭示', self.lookup.input_origins['level'])
            self.assertFalse(self.lookup.context['source'].get('mixed_snapshots'))
        self.assertEqual(self.lookup.context['conditions'].count('未改变游戏鉴定状态'), 1)

    def historical_floor(self, branch=0, count=1):
        root, slot = self.saved_game()
        game = json.loads((slot/'game.dat').read_text())
        game['generated_levels'] = [1 if branch == 0 else 1001, 2]
        (slot/'game.dat').write_text(json.dumps(game), encoding='utf-8')
        current = slot/'depth2.dat'
        current.write_bytes(current.read_bytes())
        level = {'__className': PREFIX+'levels.SewerLevel', 'version': 922,
            'width': 4, 'height': 4, 'map': [1]*16, 'visited': [True]*16, 'mapped': [False]*16,
            'heaps': [{'type': 'CRYSTAL_CHEST', 'pos': 5, 'haunted': True, 'items': [
                {'__className': PREFIX+'items.weapon.melee.Sword', 'level': 3,
                 'levelKnown': False, 'cursedKnown': False, 'cursed': True,
                 'augment': 'SPEED', 'mastery_potion_bonus': True} for _ in range(count)]}],
            'mobs': [{'__className': PREFIX+'actors.mobs.GoldenMimic', 'pos': 8, 'HP': 8,
                'items': [{'__className': PREFIX+'items.rings.RingOfMight', 'level': 2,
                    'levelKnown': False, 'cursedKnown': False, 'cursed': True}]}]}
        path = slot/('depth1.dat' if not branch else 'depth1-branch1.dat')
        path.write_text(json.dumps({'level': level}), encoding='utf-8')
        self.session.refresh()
        self.manager.open_reference = self.lookup.open_reference
        self.workspace.reload('map'); self.finish_job()
        row = next(r for r in self.workspace.rows['map'] if r['floor']['depth'] == 1)
        self.select('map', row); self.workspace.reveal_map(); self.finish_job()
        return root, slot, path

    def map_items(self):
        self.workspace.emit('map')
        return next(r for r in self.host.commands[-1][1]['result_details'] if r['id'] == 'map_items')

    def test_historical_and_branch_floor_items_keep_curse_details_and_numeric_route(self):
        for branch in (0, 1):
            with self.subTest(branch=branch):
                _, slot, _ = self.historical_floor(branch)
                before = {p.name: p.read_bytes() for p in slot.iterdir()}
                items = self.map_items()['items']
                self.assertEqual(len(items), 2)
                for item in items:
                    self.assertIn('诅咒', item['summary'])
                    self.assertTrue(item['text'])
                    if item['entry'] == 'items.weapon.melee.sword':
                        self.assertIn('速度强化', item['text'])
                        self.assertIn('已使用精通药剂', item['text'])
                    self.workspace.handle({'page': 'map', 'command': 'map_item_reference',
                        'id': item['id'], 'token': item['token']})
                    self.finish_job(); self.finish()
                    self.assertEqual(self.lookup.identity, item['entry'])
                    self.assertIn('第 1 层', self.lookup.context['source_label'])
                    self.assertIn('未加入背包', self.lookup.context['conditions'])
                    self.assertIn('主动揭示', self.lookup.input_origins['level'])
                    self.lookup.emit()
                    notice = self.host.commands[-1][1]['primary_notice']
                    self.assertIn('第 1 层', notice)
                    self.assertIn('有诅咒', notice)
                    self.assertEqual('支线 1' in notice, bool(branch))
                    if item['entry'] == 'items.weapon.melee.sword':
                        self.assertIn('速度强化', notice)
                        self.assertIn('已用精通药剂', notice)
                        self.assertIn('基础参考未计', notice)
                        self.assertIn('力量 10', self.lookup.context['conditions'])
                self.assertEqual(before, {p.name: p.read_bytes() for p in slot.iterdir()})

    def test_map_item_actions_reject_hidden_changed_and_late_floor_results(self):
        _, _, path = self.historical_floor()
        item = self.map_items()['items'][0]
        action = {'page': 'map', 'command': 'map_item_reference', 'id': item['id'], 'token': item['token']}
        self.workspace.handle(action)
        self.workspace.handle({'page': 'map', 'command': 'map_hide'})
        self.finish_job()
        self.assertIsNone(self.lookup.identity)
        with self.assertRaises(ValueError): self.workspace.handle(action)
        self.workspace.reveal_map(); self.finish_job()
        item = self.map_items()['items'][0]
        level = json.loads(path.read_text()); level['level']['heaps'][0]['items'][0]['level'] = 4
        path.write_text(json.dumps(level), encoding='utf-8')
        self.workspace.handle({**action, 'id': item['id'], 'token': item['token']}); self.finish_job()
        self.assertIsNone(self.lookup.identity)
        self.assertTrue(self.workspace.native.error.called)

    def test_floor_item_pages_reach_every_instance_without_large_protocol_messages(self):
        self.historical_floor(count=75)
        reached = set()
        while True:
            detail = self.map_items()
            self.assertLessEqual(len(detail['items']), 20)
            reached.update(item['id'] for item in detail['items'])
            self.assertLess(len(json.dumps(self.host.commands[-1][1], ensure_ascii=False).encode()), 524288)
            if not detail['next']: break
            self.workspace.handle({'page': 'map', 'command': 'map_items_next', 'token': detail['token']})
        self.assertEqual(len(reached), 76)

    def test_restore_preview_identifies_target_slot_and_record_while_list_is_folded(self):
        root, slot = self.saved_game()
        other = root/'game2'; other.mkdir()
        for name in ('game.dat', 'depth2.dat'):
            (other/name).write_bytes((slot/name).read_bytes())
        self.session.backups.closed_check = lambda: None
        self.session.backups.capture(root, 2)
        status = self.session.backup_status()
        row = next(r for r in status['history'] if r['slot'] == 2)
        self.session.backup_action({'action': 'manage', 'context': status['context'],
            'slot': 2, 'id': row['id'], 'expected_metadata_revision': row['metadata_revision'],
            'label': '第二槽位的固定记录'})
        self.workspace.reload('backups'); self.finish_job()
        row = next(r for r in self.workspace.rows['backups'] if r['entry']['slot'] == 2 and r['action'] == 'restore')
        self.select('backups', row); self.workspace.preview_backup(); self.finish_job()
        self.assertEqual(self.session.snapshot()['active_slot'], 1)
        brief = self.host.commands[-1][1]['text']
        self.assertIn('槽位 2', brief)
        self.assertIn('第二槽位的固定记录', brief)
        self.assertIn('目标进度', brief)
        state = self.host.commands[-1][1]
        self.assertEqual(state['backup_summary']['heading'], '槽位 2 · 第二槽位的固定记录')
        target = self.workspace.backup_preview['progress']['target']
        self.assertEqual(state['backup_summary']['target'], '目标 · '+self.workspace.progress_brief(target))
        details = next(row for row in state['result_details'] if row['id']=='record_details')
        self.assertIn('当前进度', details['text'])
        self.assertIn('目标进度', details['text'])
        self.assertIn('保存时间', details['text'])
        self.assertFalse(details['expanded'])

    def test_current_floor_reveal_keeps_saved_item_properties_and_container_risk(self):
        from companion.native_manager import NativeManager
        _, slot = self.saved_game()
        level = {'__className': PREFIX+'levels.SewerLevel', 'version': 922,
            'width': 4, 'height': 4, 'map': [1]*16, 'visited': [True]*16, 'mapped': [False]*16,
            'heaps': [{'type': 'TOMB', 'pos': 5, 'haunted': True, 'items': [
                {'__className': PREFIX+'items.weapon.melee.Sword', 'level': 4,
                 'levelKnown': False, 'cursedKnown': False, 'cursed': True,
                 'mastery_potion_bonus': True, 'augment': 'SPEED'},
                {'__className': PREFIX+'items.wands.WandOfFireblast', 'level': 2,
                 'levelKnown': False, 'cursedKnown': False, 'curCharges': 7, 'curChargeKnown': False}]}]}
        (slot/'depth2.dat').write_text(json.dumps({'level': level}), encoding='utf-8')
        self.session.refresh()
        before = {p.name: p.read_bytes() for p in slot.iterdir()}
        ui = NativeManager.__new__(NativeManager)
        ui.manager, ui.session, ui.queue_io = self.manager, self.session, self.native.queue_io
        public = ui.floor_state(self.session.snapshot())
        self.assertEqual(public['nodes'][0]['children'], [])
        ui.reveal_floor({'token': public['token']}); self.finish_job()
        shown = ui.floor_state(self.session.snapshot())
        heap = next(n for n in shown['nodes'][0]['children'] if n['id'] == 'hidden-heaps')['children'][0]
        self.assertIn('闹鬼', heap['text'])
        self.assertEqual(len(heap['children']), 2)
        for node in heap['children']:
            item, _ = ui._floor_item_references[node['id']]
            if item['kind'] == 'Sword':
                self.assertEqual(item['strength_requirement'], 10)
                self.assertIn('速度强化', node['detail'])
                self.assertIn('已使用精通药剂', node['detail'])
            for detail in item['details']: self.assertIn(detail, node['detail'])
            self.assertIn('未加入背包', node['detail'])
        self.assertTrue(any('7 次充能' in n['detail'] for n in heap['children']))
        self.assertEqual(before, {p.name: p.read_bytes() for p in slot.iterdir()})

    def test_shared_item_details_retain_each_saved_equipment_modifier(self):
        for kind, augment, label in [('weapon.melee.Sword', 'SPEED', '速度强化'),
                ('weapon.melee.Sword', 'DAMAGE', '伤害强化'),
                ('armor.MailArmor', 'EVASION', '闪避强化'),
                ('armor.MailArmor', 'DEFENSE', '防御强化')]:
            with self.subTest(augment=augment):
                raw = {'__className': PREFIX+'items.'+kind, 'level': 4, 'levelKnown': False,
                    'cursedKnown': False, 'augment': augment, 'mastery_potion_bonus': True}
                public = self.session.catalog.item(raw, {})
                self.assertIsNone(public['level'])
                self.assertIn(label, public['details'])
                revealed = self.session.catalog.item(raw, {}, reveal=True)
                self.assertIn(label, revealed['details'])
                self.assertIn('已使用精通药剂', revealed['details'])

    def test_saved_receipt_does_not_follow_changed_conditions_or_another_reference(self):
        self.item_reference('weapon.melee.Katana')
        self.assertTrue(self.lookup.save_plan('原始武器条件'))
        self.assertIn('已保存', self.lookup.operation_receipt)
        self.lookup.variables['level'].set('4')
        self.assertEqual(self.lookup.operation_receipt, '')
        self.lookup.calculate(); self.finish()
        self.assertTrue(self.lookup.save_plan('新的武器条件'))
        self.lookup.note.value = '新备注'; self.lookup.note_changed()
        self.assertEqual(self.lookup.operation_receipt, '')
        self.assertTrue(self.lookup.save_plan('含备注的武器条件'))
        draft = self.lookup.draft(include_result=True)
        self.lookup.restore_draft(draft)
        self.assertEqual(self.lookup.operation_receipt, '')
        self.lookup.dirty = self.lookup.draft_modified = False
        self.lookup.open_plan(draft['saved_plan']['id'], False)
        self.assertEqual(self.lookup.operation_receipt, '')
        self.assertTrue(self.lookup.save_plan('切换前的已保存条件'))
        self.lookup.open_reference({'entry': 'items.artifacts.masterthievesarmband',
            'params': {'level': 4}, 'source_label': '楼层中的袖章'})
        self.finish()
        self.assertEqual(self.lookup.identity, 'items.artifacts.masterthievesarmband')
        self.assertIsNone(self.lookup.saved_plan)
        self.assertEqual(self.lookup.operation_receipt, '')
        self.lookup.emit()
        self.assertFalse(self.host.commands[-1][1]['operation_receipt'])

    def test_artifact_charge_details_respect_identification_and_explicit_reveal(self):
        for kind, charge, label in [('MasterThievesArmband', 0, '储存充能 0'),
                ('MasterThievesArmband', 7, '储存充能 7'),
                ('TalismanOfForesight', 75, '储存充能 75%'),
                ('EtherealChains', 0, '储存充能 0')]:
            with self.subTest(kind=kind, charge=charge):
                raw = {'__className': PREFIX+'items.artifacts.'+kind, 'level': 4,
                    'levelKnown': True, 'cursedKnown': True, 'cursed': False, 'charge': charge}
                self.assertIn(label, self.session.catalog.item(raw, {})['details'])
                for changes in ({'levelKnown': False}, {'cursedKnown': False}, {'cursed': True}):
                    hidden = {**raw, **changes}
                    public = self.session.catalog.item(hidden, {})
                    self.assertNotIn(label, public['details'])
                    self.assertTrue(public['has_hidden_details'])
                    self.assertIn(label, self.session.catalog.item(hidden, {}, reveal=True)['details'])
                for invalid in (None, True, '7', -1):
                    item = self.session.catalog.item({**raw, 'charge': invalid}, {}, reveal=True)
                    self.assertFalse(any(text.startswith('储存充能') for text in item['details']))

    def test_healing_primary_keeps_key_assumptions_and_expands_full_source(self):
        self.open('items.potions.potionofhealing')
        source = '快照 · 最近保存的记录 · 槽位 1 · 2026-10-16 11:58 保存'
        self.lookup.input_origins['vial'] = source
        self.lookup.emit()
        state = self.host.commands[-1][1]
        self.assertIn('凝血试管', state['primary_note'])
        self.assertIn('快照 · 槽位 1', state['primary_note'])
        self.assertNotIn('2026-10-16', state['primary_note'])
        self.assertIn(source, str(state))
        for warning in ('手填', '示例 · 请核对', source+' · 最新记录未确认'):
            self.lookup.input_origins['vial'] = warning; self.lookup.emit()
            self.assertIn(warning.split(' · ')[-1], self.host.commands[-1][1]['primary_note'])

    def test_healing_primary_brief_keeps_basis_and_rejects_incomplete_trial(self):
        self.open('items.potions.potionofhealing')
        self.lookup.variables['hp'].set('3')
        self.lookup.variables['max_hp'].set('50')
        self.lookup.calculate(); self.finish()
        state = self.host.commands[-1][1]
        for text in ('生命基准 3/50', '未计后续受伤', '药水恐惧不治疗', '试管'):
            self.assertIn(text, state['primary_brief'])
        self.assertIn('其他生命变化', state['primary_note'])
        self.lookup.input_origins['vial'] = '手填 · 最新记录未确认'
        self.lookup.emit()
        self.assertIn('未确认', self.host.commands[-1][1]['primary_brief'])
        self.lookup.variables['hp'].set('  1e ')
        self.assertEqual(self.host.commands[-1][1]['primary_brief'], '')
        self.assertEqual(self.lookup.raw_params()['hp'], '  1e ')

    def test_receipt_brief_keeps_backup_failure_and_cannot_follow_new_inputs(self):
        self.open('items.potions.potionofhealing')
        self.lookup.pin()
        self.assertIn('本次运行', self.host.commands[-1][1]['operation_brief'])

        self.assertTrue(self.lookup.save_plan('初始试算'))
        self.assertEqual(self.host.commands[-1][1]['operation_brief'], '已保存')
        self.assertTrue(self.lookup.save_plan('更新试算', update=True))
        self.assertEqual(self.host.commands[-1][1]['operation_brief'], '已更新')
        with patch.object(self.session.knowledge, '_retain_healthy', side_effect=OSError('controlled healthy copy failure')):
            self.assertTrue(self.lookup.save_plan('仍保存成功的试算'))
        state = self.host.commands[-1][1]
        self.assertIn('健康副本未完成', state['operation_brief'])
        self.assertIn('controlled healthy copy failure', state['operation_receipt'])
        self.assertEqual(self.session.knowledge.reopen(self.lookup.saved_plan['id'])['plan']['name'], '仍保存成功的试算')
        self.lookup.variables['hp'].set('  1e ')
        self.assertEqual(self.host.commands[-1][1]['operation_brief'], '')
        self.lookup.pin()
        self.assertEqual(self.host.commands[-1][1]['operation_brief'], '')
        self.assertIn('有效参数', self.host.commands[-1][1]['operation_receipt'])

    def test_real_healthy_copy_failure_stays_concise_and_retains_full_cause(self):
        blocker = self.session.knowledge._healthy_directory()
        blocker.write_text('block directory creation', encoding='utf-8')
        self.open('actors.hero.spells.sunray')
        for update in (False, True):
            self.assertTrue(self.lookup.save_plan('长名称试算方案', update=update))
            state = self.host.commands[-1][1]
            self.assertIn('健康副本未完成', state['operation_brief'])
            self.assertEqual(state['origin_brief'], '')
            self.assertIn(repr(str(blocker)), state['operation_receipt'])
            self.assertIn(repr(str(blocker)), state['status'])
            self.assertEqual(len(self.session.knowledge.status()['plans']), 1)
        self.lookup.pin()
        self.lookup.emit()
        state = self.host.commands[-1][1]
        self.assertEqual(state['origin_brief'], '')
        self.assertEqual(state['operation_brief'], '已固定 · 健康副本未完成')
        self.assertIn(repr(str(blocker)), state['status'])
        self.lookup.note.set('备注改变后仍需处理健康副本')
        state = self.host.commands[-1][1]
        self.assertEqual(state['operation_brief'], '健康副本未完成')
        self.assertEqual(state['operation_receipt'], self.lookup.workspace_recovery_warning)
        self.lookup.variables['talent'].set(' 1e ')
        self.lookup.pin()
        state = self.host.commands[-1][1]
        self.assertEqual(state['operation_brief'], '')
        self.assertEqual(self.lookup.raw_params()['talent'], ' 1e ')
