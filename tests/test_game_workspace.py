"""Real calculator, plan and draft contracts for the in-game workspace."""
import copy
import json
import os
import time
from types import SimpleNamespace
from unittest.mock import Mock

from tests.test_native_controllers import ControllerFixture
from companion.game_workspace import GameWorkspace
from companion.character_scene import calculate_scene, empty_scene


class GameWorkspaceTests(ControllerFixture):
    def test_field_help_keeps_unknowns_visible_and_moves_routine_origins_to_details(self):
        self.workspace.emit('equipment')
        payload=self.host.commands[-1][1]
        specs={row['key']:row for row in payload['fields']}
        self.assertFalse(specs['strength']['help_visible'])
        self.assertIn('手填',specs['strength']['help'])
        self.assertTrue(specs['id_a']['help_visible'])
        self.assertFalse(specs['note']['help_visible'])
        self.workspace.sources['equipment']={'mixed_snapshots':True,'fields':{'strength':'来自两次保存'}}
        self.workspace.emit('equipment')
        specs={row['key']:row for row in self.host.commands[-1][1]['fields']}
        self.assertTrue(specs['strength']['help_visible'])
        self.assertEqual(specs['strength']['help'],'来自两次保存')

    def test_inventory_comparison_preserves_public_equipment_properties_and_unknowns(self):
        prefix = 'com.shatteredpixel.shatteredpixeldungeon.'
        for source, expected in [
            ({'__className': prefix+'items.armor.WarriorArmor', 'armortier': 5,
              'mastery_potion_bonus': True, 'augment': 'DEFENSE', 'glyph_hardened': True},
             {'tier_a': '5', 'mastery_a': '1', 'augment_a': 'DEFENSE', 'hardened_a': '1'}),
            ({'__className': prefix+'items.weapon.melee.Sword', 'augment': 'SPEED', 'enchant_hardened': True},
             {'mastery_a': '0', 'augment_a': 'SPEED', 'hardened_a': '1'}),
            ({'__className': prefix+'items.wands.WandOfFireblast', 'resin_bonus': 2}, {'resin_a': '2'}),
        ]:
            public = self.session.catalog.item({**source, 'level': 0, 'levelKnown': True, 'cursedKnown': True}, {})
            self.workspace.import_equipment(public, 'a')
            for key, value in expected.items():
                self.assertEqual(self.workspace.raw['equipment'][key], value)
                self.assertIn('已知公开', self.workspace.sources['equipment']['fields'][key])
        public = {'key': 'items.armor.warriorarmor', 'name': '职业护甲', 'location': '背包'}
        self.workspace.import_equipment(public, 'a')
        self.assertEqual(self.workspace.raw['equipment']['tier_a'], '')
        self.assertEqual(self.workspace.raw['equipment']['augment_a'], 'unknown')
        self.assertEqual(self.workspace.raw['equipment']['hardened_a'], 'unknown')
        self.assertEqual(self.workspace.sources['equipment']['fields']['tier_a'], '未确认')

    def test_task_actions_explain_requirements_and_do_not_overclaim_snapshot_import(self):
        self.workspace.emit('inventory')
        payload = self.host.commands[-1][1]
        reference = next(row for row in payload['actions'] if row['id']=='reference')
        self.assertTrue(reference['disabled'])
        self.assertIn('选择', reference['reason'])
        self.workspace.emit('equipment')
        payload = self.host.commands[-1][1]
        actions = {row['id']: row for row in payload['actions']}
        self.assertEqual(actions['import']['text'], '带入手填局势力量')
        self.assertTrue(actions['save']['disabled'])
        self.equipment(); self.workspace.calculate('equipment'); self.workspace.emit('equipment')
        self.assertFalse(next(row for row in self.host.commands[-1][1]['actions'] if row['id']=='save')['disabled'])
        self.workspace.edit('equipment', {**self.workspace.raw['equipment'], 'level_a':'1e'})
        self.workspace.emit('equipment')
        self.assertTrue(next(row for row in self.host.commands[-1][1]['actions'] if row['id']=='save')['disabled'])

    def test_known_consumable_has_no_reveal_or_equipment_actions(self):
        item={'instance_key':'item-0','key':'items.potions.potionofhealing','name':'治疗药剂','quantity':2,
              'location':'背包','description':'已知种类','details':[],'known':True,'available':True,'has_hidden_details':False}
        self.session.data['items']=[item]
        rows=self.workspace.inventory(); self.workspace.selected['inventory']=rows[0]['id']; self.workspace.selected_tokens['inventory']=rows[0]['token']
        self.workspace.emit('inventory')
        actions={row['id']:row for row in self.host.commands[-1][1]['actions']}
        self.assertFalse(actions['reference']['disabled'])
        self.assertNotIn('reveal',actions)
        self.assertNotIn('equip_a',actions)
        self.assertNotIn('equip_b',actions)

    def test_alchemy_goal_is_presented_before_shared_budget_without_changing_inputs(self):
        before=copy.deepcopy(self.workspace.raw['alchemy'])
        specs=self.workspace.alchemy_fields()
        self.assertLess(next(i for i,row in enumerate(specs) if row['key']=='t0.recipe'),
                        next(i for i,row in enumerate(specs) if row['key']=='energy'))
        self.assertEqual(self.workspace.raw['alchemy'],before)

    def test_fixed_task_source_marks_new_snapshot_slot_connection_and_errors_without_overwriting(self):
        from companion.native_workspace import plan_updated_text
        snap=copy.deepcopy(self.session.snapshot())
        snap['settings']['mode']='save'; snap.update(active_slot=1,modified=1000,stale=False,error='')
        snap['data']['character_scene']=calculate_scene(empty_scene(12)); snap['data']['hero']['strength']=12
        self.session.snapshot=lambda:copy.deepcopy(snap)
        self.equipment(); self.workspace.import_snapshot('equipment'); self.workspace.calculate('equipment')
        before=copy.deepcopy((self.workspace.raw,self.workspace.calculated,self.workspace.results))
        self.workspace.emit('equipment'); payload=self.host.commands[-1][1]
        self.assertFalse(payload['task_source']['stale'])
        self.assertIn('槽位 1',payload['task_source']['brief'])
        self.assertIn(plan_updated_text(1000),payload['task_source']['brief'])
        self.assertIn('快照',next(row['help'] for row in payload['fields'] if row['key']=='strength'))
        original=copy.deepcopy(snap)
        for change in ('new_save','slot','connection','error','expired'):
            snap=copy.deepcopy(original)
            if change=='new_save':snap['modified']=2000; snap['data']['hero']['strength']=18
            elif change=='slot':snap['active_slot']=2
            elif change=='connection':snap['settings']['save_root']='another-root'
            elif change=='error':snap['error']='暂时不可读'
            else:snap['stale']=True
            self.workspace.emit('equipment'); payload=self.host.commands[-1][1]
            self.assertTrue(payload['task_source']['stale'],change)
            self.assertIn('旧参考',payload['task_source']['brief'])
            self.assertIn('槽位 1',payload['task_source']['brief'])
            self.assertEqual((self.workspace.raw,self.workspace.calculated,self.workspace.results),before)

    def test_fixed_source_manual_edit_and_explicit_reimport_have_honest_field_labels(self):
        snap=copy.deepcopy(self.session.snapshot()); snap['settings']['mode']='save'
        snap.update(active_slot=1,modified=1000,stale=False,error='')
        snap['data']['character_scene']=calculate_scene(empty_scene(12)); snap['data']['hero']['strength']=12
        self.session.snapshot=lambda:copy.deepcopy(snap)
        self.equipment(); self.workspace.import_snapshot('equipment')
        self.workspace.edit('equipment',{**self.workspace.raw['equipment'],'strength':'  1e  '})
        self.workspace.emit('equipment')
        self.assertIn('手填',next(row['help'] for row in self.host.commands[-1][1]['fields'] if row['key']=='strength'))
        snap['modified']=2000; snap['data']['hero']['strength']=18; snap['data']['character_scene']=calculate_scene(empty_scene(18))
        self.workspace.import_snapshot('equipment'); self.workspace.emit('equipment')
        self.assertFalse(self.host.commands[-1][1]['task_source']['stale'])
        self.assertEqual(self.workspace.raw['equipment']['strength'],'18')
        self.workspace.handle({'action':'game_action','page':'equipment','command':'undo'})
        self.assertEqual(self.workspace.raw['equipment']['strength'],'  1e  ')
        self.assertTrue(self.host.commands[-1][1]['task_source']['stale'])

    def test_map_actions_explain_unavailable_selection_and_reveal(self):
        self.workspace.emit('map')
        actions={row['id']:row for row in self.host.commands[-1][1]['actions']}
        self.assertTrue(actions['map_reveal']['disabled'])
        self.assertIn('选择',actions['map_reveal']['reason'])
        self.assertTrue(actions['map_hide']['disabled'])

    def test_mixed_equipment_imports_keep_each_field_source_and_do_not_claim_one_current_snapshot(self):
        snap=copy.deepcopy(self.session.snapshot()); snap['settings']['mode']='save'
        snap.update(active_slot=1,modified=1000,stale=False,error='')
        snap['data']['character_scene']=calculate_scene(empty_scene(12)); snap['data']['hero']['strength']=12
        self.session.snapshot=lambda:copy.deepcopy(snap)
        self.equipment(); self.workspace.import_snapshot('equipment')
        first_strength_origin=self.workspace.sources['equipment']['fields']['strength']
        snap.update(active_slot=2,modified=2000)
        item={'key':'items.weapon.melee.sword','name':'单手剑','location':'背包','level':1,'cursed':False}
        self.workspace.import_equipment(item,'a'); self.workspace.emit('equipment')
        self.assertEqual(self.workspace.sources['equipment']['fields']['strength'],first_strength_origin)
        self.assertIn('槽位 1',first_strength_origin)
        self.assertIn('槽位 2',self.workspace.sources['equipment']['fields']['id_a'])
        self.assertTrue(self.host.commands[-1][1]['task_source']['stale'])
        self.assertIn('不同保存条件',self.host.commands[-1][1]['task_source']['brief'])

    def test_saved_connection_binding_survives_reopen_and_old_unbound_records_remain_readable(self):
        snap = copy.deepcopy(self.session.snapshot()); snap['settings']['mode'] = 'save'
        snap.update(active_slot=1, modified=1000, stale=False, error='')
        snap['data']['character_scene'] = calculate_scene(empty_scene(12)); snap['data']['hero']['strength'] = 12
        snap['settings']['save_root'] = 'synthetic-original-root'
        self.session.snapshot = lambda: copy.deepcopy(snap)
        self.equipment(); self.workspace.import_snapshot('equipment'); self.workspace.calculate('equipment')
        params = copy.deepcopy(self.workspace.calculated['equipment'])
        self.workspace.raw['equipment']['name'] = '固定连接'
        self.workspace.handle({'page': 'equipment', 'command': 'save'}); self.finish_job()
        saved = copy.deepcopy(self.workspace.saved['equipment'])
        self.assertEqual(len(saved['origin']['context_token']), 64)
        self.assertNotIn('synthetic-original-root', json.dumps(saved['origin']))
        snap['settings']['save_root'] = 'synthetic-other-root'
        self.assertTrue(self.workspace.source_status('equipment')['stale'])
        self.workspace.dirty.clear(); self.workspace.open_plan(self.session.knowledge.reopen(saved['id']))
        self.assertTrue(self.workspace.source_status('equipment')['stale'])
        self.assertEqual(self.workspace.calculated['equipment'], params)
        legacy = {key: value for key, value in saved['origin'].items() if key not in ('context_token', 'state_revision')}
        old = self.session.knowledge.save('旧格式固定条件', 'equipment', None, params, legacy)
        self.workspace.dirty.clear(); self.workspace.open_plan(self.session.knowledge.reopen(old['id']))
        self.assertIn('来源连接未确认', self.workspace.source_status('equipment')['brief'])
        self.assertEqual(self.workspace.calculated['equipment'], params)
        with self.assertRaises(ValueError):
            self.session.knowledge.save('无效绑定', 'equipment', None, params, {'mode': 'save', 'context_token': 'plain-directory'})

    def test_new_native_inventory_comparison_saves_both_public_objects_and_reopens_their_records(self):
        from companion.engine import PREFIX, analyze
        items, records = [], []
        for index, (effect, title) in enumerate((('Blazing', '主武器'), ('Chilling', '备用武器'))):
            items.append({'__className': PREFIX+'items.weapon.melee.Sword', 'level': 2,
                'levelKnown': True, 'cursedKnown': True, 'cursed': False, 'custom_note_id': index+1,
                'enchantment': {'__className': PREFIX+'items.weapon.enchantments.'+effect}})
            records.append({'__className': PREFIX+'journal.Notes$CustomRecord', 'id_number': index+1,
                'title': title, 'body': title+'的独立用途'})
        self.session.data = analyze({'version': self.session.catalog.data['version_code'], 'depth': 2,
            'challenges': 0, 'hero': {'class': 'WARRIOR', 'lvl': 5, 'HP': 4, 'HT': 30,
                'STR': 14, 'inventory': items, 'buffs': []}, 'records': records}, self.session.catalog)
        expected = {side: {'id': item['key'], 'name': item['name'],
            'effect_id': item['equipment_state']['effect_id'], 'user_note': copy.deepcopy(item['user_note'])}
            for side, item in zip(('a', 'b'), self.session.data['items'])}
        for index, side in enumerate(('a', 'b')):
            row = self.workspace.inventory()[index]
            self.workspace.handle({'action': 'game_select', 'page': 'inventory', 'id': row['id'], 'token': row['token']})
            self.workspace.handle({'action': 'game_action', 'page': 'inventory', 'command': 'equip_'+side})
            self.assertEqual(self.workspace.sources['equipment'].get('references', {}).get(side), expected[side])
        self.workspace.raw['equipment'].update(planning='0', name='小窗新建比较')
        self.workspace.handle({'page': 'equipment', 'command': 'calculate', 'values': self.workspace.display_raw('equipment')})
        params = copy.deepcopy(self.workspace.calculated['equipment'])
        self.workspace.handle({'page': 'equipment', 'command': 'save'}); self.finish_job()
        self.native.error.assert_not_called()
        saved = self.workspace.saved['equipment']
        opened = self.session.knowledge.reopen(saved['id'])  # Shared native/web reopen contract.
        self.assertEqual(opened['plan']['origin']['references'], expected)
        self.workspace.open_plan(opened, confirmed=True)
        self.assertEqual(self.workspace.calculated['equipment'], params)
        for reference in expected.values():
            for text in (reference['name'], self.workspace.names[reference['effect_id']], reference['user_note']['title'], reference['user_note']['body']):
                self.assertIn(text, self.workspace.results['equipment'])
        self.assertIn('效果身份仅用于辨认，未计额外收益', self.workspace.results['equipment'])
        self.assertEqual(self.workspace.structured_results['equipment']['rows'], opened['result']['rows'])
        self.workspace.emit('equipment')
        self.assertEqual(self.host.commands[-1][1]['result_details'], [])  # Reuse existing expandable full comparison.

    def test_single_native_object_completes_manual_counterpart_and_identity_edit_clears_old_record(self):
        self.equipment()
        item = {'key': 'items.weapon.melee.sword', 'name': '烈焰单手剑 +2', 'location': '背包',
            'level': 2, 'cursed': False, 'mastery': False, 'augmentation': 'NONE',
            'equipment_state': {'hardened': False, 'effect_id': 'items.weapon.enchantments.blazing'},
            'user_note': {'title': '主武器', 'body': '保留此记录', 'scope': 'specific_item'}}
        self.workspace.import_equipment(item, 'a')
        self.workspace.raw['equipment'].update(planning='0', name='背包与手填比较')
        self.workspace.calculate('equipment')
        references = copy.deepcopy(self.workspace.sources['equipment']['references'])
        self.assertEqual(references['b'], {'id': 'items.weapon.melee.longsword', 'name': '长剑', 'effect_id': None, 'user_note': None})
        self.workspace.handle({'page': 'equipment', 'command': 'save'}); self.finish_job()
        self.native.error.assert_not_called()
        self.assertEqual(self.session.knowledge.reopen(self.workspace.saved['equipment']['id'])['plan']['origin']['references'], references)
        self.workspace.edit('equipment', {**self.workspace.raw['equipment'], 'id_a': 'items.weapon.melee.shortsword'})
        self.workspace.calculate('equipment')
        self.assertEqual(self.workspace.sources['equipment']['references']['b'], references['b'])
        self.assertIsNone(self.workspace.sources['equipment']['references']['a']['user_note'])
        self.assertNotIn('保留此记录', self.workspace.results['equipment'])
        self.workspace.handle({'page': 'equipment', 'command': 'undo'})
        self.workspace.calculate('equipment')
        self.assertEqual(self.workspace.sources['equipment']['references'], references)

    def test_native_equipment_roundtrip_retains_references_and_only_replaces_the_selected_object(self):
        self.equipment(); self.workspace.raw['equipment']['planning'] = '0'; self.workspace.calculate('equipment')
        references = {side: {'id': self.workspace.raw['equipment']['id_'+side], 'name': side+' 捕获的装备',
            'effect_id': 'items.weapon.enchantments.'+effect,
            'user_note': {'title': side+' 的用途', 'body': '这件装备的独立记录', 'scope': 'specific_item'}}
            for side, effect in (('a','blazing'),('b','chilling'))}
        saved = self.session.workspace_action({'action':'save','kind':'equipment','entry':None,'name':'双侧固定参考',
            'note':'共同备注','params':self.workspace.calculated['equipment'],
            'source':{'mode':'example','references':references}})['plan']
        self.workspace.open_plan(self.session.knowledge.reopen(saved['id']), confirmed=True)
        self.workspace.handle({'page':'equipment','command':'import','values':self.workspace.display_raw('equipment')})
        self.assertEqual(self.workspace.sources['equipment'].get('references'), references)
        self.workspace.calculate('equipment');self.workspace.handle({'page':'equipment','command':'update'});self.finish_job()
        self.assertEqual(self.session.knowledge.reopen(saved['id'])['plan']['origin'].get('references'),references)
        self.workspace.raw['character']['base_strength']='14'
        self.workspace.handle({'page':'equipment','command':'use_character'})
        self.assertEqual(self.workspace.sources['equipment'].get('references'),references)
        self.workspace.handle({'page':'equipment','command':'undo'})
        item={'key':'items.weapon.melee.sword','name':'新捕获的单手剑','location':'背包','level':3,'cursed':False,
            'mastery':False,'augmentation':'NONE','equipment_state':{'hardened':False,'effect_id':'items.weapon.enchantments.kinetic'},
            'user_note':{'title':'新用途','body':'替换 A 的记录','scope':'specific_item'}}
        self.workspace.import_equipment(item,'a')
        self.assertEqual(self.workspace.sources['equipment']['references']['b'],references['b'])
        self.assertEqual(self.workspace.sources['equipment']['references']['a'],
            {'id':item['key'],'name':item['name'],'effect_id':item['equipment_state']['effect_id'],'user_note':item['user_note']})
        self.workspace.calculate('equipment');self.workspace.handle({'page':'equipment','command':'update'});self.finish_job()
        self.assertEqual(self.session.knowledge.reopen(saved['id'])['plan']['origin']['references'],self.workspace.sources['equipment']['references'])

    def test_native_equipment_reopen_keeps_disabled_planning_off_through_real_action_payloads(self):
        self.equipment();self.workspace.raw['equipment'].update(planning='0',name='无预算方案')
        self.workspace.calculate('equipment');self.workspace.handle({'page':'equipment','command':'save'});self.finish_job()
        saved=self.workspace.saved['equipment'];self.assertNotIn('planning',saved['params'])
        self.workspace.open_plan(self.session.knowledge.reopen(saved['id']),confirmed=True)
        specs={row['key']:row for row in self.workspace.equipment_fields()}
        self.assertEqual(specs['planning']['raw'],'0');self.assertNotIn('upgrade_budget',specs)
        self.workspace.handle({'page':'equipment','command':'calculate','values':self.workspace.display_raw('equipment')})
        self.workspace.handle({'page':'equipment','command':'update','values':self.workspace.display_raw('equipment')});self.finish_job()
        self.assertNotIn('planning',self.session.knowledge.reopen(saved['id'])['plan']['params'])
        self.workspace.raw['equipment']['planning']='1'
        self.assertIn('upgrade_budget',{row['key'] for row in self.workspace.equipment_fields()})

    def test_snapshot_strength_requires_confirmed_total_and_preserves_input_before_explicit_manual_use(self):
        from tests.test_character_scene import game,ring
        for condition,fields in [('known',{}),('unknown_level',{'levelKnown':False}),('unknown_curse',{'cursedKnown':False})]:
            with self.subTest(condition=condition):
                fixture=GameWorkspaceTests();fixture.setUp();root,slot=fixture.saved_game()
                data=game(ring=ring(**fields));data.update(challenges=0,generated_levels=[2],branch=0,seed=9)
                (slot/'game.dat').write_text(json.dumps(data),encoding='utf-8')
                stamp=(slot/'game.dat').stat().st_mtime_ns+1_000_000_000
                os.utime(slot/'depth2.dat',ns=(stamp,stamp));fixture.session.refresh();fixture.equipment()
                fixture.workspace.raw['equipment']['planning']='0'
                if condition=='known':
                    fixture.workspace.import_snapshot('equipment')
                    self.assertEqual(fixture.workspace.raw['equipment']['strength'],'14')
                else:
                    before=copy.deepcopy((fixture.workspace.raw,fixture.workspace.sources,fixture.workspace.undo))
                    with self.assertRaisesRegex(ValueError,'总力量未确认.*手填游戏面板总力量'):
                        fixture.workspace.import_snapshot('equipment')
                    self.assertEqual((fixture.workspace.raw,fixture.workspace.sources,fixture.workspace.undo),before)
                    fixture.workspace.edit('equipment',{**fixture.workspace.display_raw('equipment'),'strength':'14'})
                fixture.workspace.calculate('equipment');fixture.workspace.raw['equipment']['name']=condition
                fixture.workspace.handle({'page':'equipment','command':'save'});fixture.finish_job()
                saved=fixture.workspace.saved['equipment'];fixture.workspace.dirty.clear()
                fixture.workspace.open_plan(fixture.session.knowledge.reopen(saved['id']))
                self.assertEqual(fixture.workspace.calculated['equipment']['strength'],14)

    def test_same_mtime_game_and_floor_changes_mark_fixed_sources_old_across_reopen_and_session(self):
        from companion.service import Session
        root,slot=self.saved_game();stamp=int(time.time())
        for file in slot.iterdir():os.utime(file,(stamp,stamp))
        self.session.refresh();self.equipment();self.workspace.import_snapshot('equipment');self.workspace.calculate('equipment')
        self.workspace.raw['equipment']['name']='固定快照';self.workspace.handle({'page':'equipment','command':'save'});self.finish_job()
        saved=copy.deepcopy(self.workspace.saved['equipment']);before=copy.deepcopy((self.workspace.raw,self.workspace.results))
        original=self.session.snapshot();file=slot/'game.dat';stat=file.stat();data=json.loads(file.read_text())
        data['hero']['STR']=18;file.write_text(json.dumps(data),encoding='utf-8');os.utime(file,ns=(stat.st_atime_ns,stat.st_mtime_ns))
        self.session.refresh();changed=self.session.snapshot()
        self.assertEqual(changed['modified'],original['modified'])
        self.assertTrue(self.workspace.source_status('equipment')['stale']);self.assertEqual((self.workspace.raw,self.workspace.results),before)
        self.workspace.open_plan(self.session.knowledge.reopen(saved['id']),confirmed=True)
        self.assertTrue(self.workspace.source_status('equipment')['stale'])
        restarted=Session(self.session.config_path);restarted.refresh();restarted.revision=saved['origin']['state_revision']
        self.workspace.session=restarted;self.assertTrue(self.workspace.source_status('equipment')['stale']);self.workspace.session=self.session
        self.workspace.import_snapshot('equipment');self.assertFalse(self.workspace.source_status('equipment')['stale'])
        file=slot/'depth2.dat';stat=file.stat();data=json.loads(file.read_text());data['level']['visited'][0]=True
        file.write_text(json.dumps(data),encoding='utf-8');os.utime(file,ns=(stat.st_atime_ns,stat.st_mtime_ns));self.session.refresh()
        self.assertTrue(self.workspace.source_status('equipment')['stale'])
        self.workspace.import_snapshot('equipment')
        self.session.update_settings({'always_on_top':True});self.session.refresh()
        self.assertFalse(self.workspace.source_status('equipment')['stale'])

    def test_independent_restored_drafts_cannot_update_an_unrelated_saved_plan(self):
        for page in ('equipment', 'alchemy', 'character'):
            with self.subTest(page=page):
                if page == 'equipment': self.equipment()
                elif page == 'alchemy': self.alchemy()
                else: self.workspace.raw[page]['base_strength'] = '14'
                self.workspace.calculate(page); self.workspace.raw[page]['name'] = '原方案 A '+page
                self.workspace.handle({'page': page, 'command': 'save'}); self.finish_job()
                original = copy.deepcopy(self.workspace.saved[page])
                others = {key: copy.deepcopy(value) for key, value in self.workspace.saved.items() if key != page}
                values = {**self.workspace.raw[page], 'name': '独立草稿 B '+page, 'note': 'B 的独立备注'}
                if page == 'equipment': values['level_a'] = '7'
                elif page == 'character': values['base_strength'] = '20'
                else: values['t0.quantity'] = '3'
                self.workspace.restore_draft({page: {'values': values, 'source': {'mode': 'example'}}})
                self.workspace.calculate(page); self.workspace.emit(page)
                self.assertNotIn(page, self.workspace.saved)
                self.assertFalse(any(row['id'] == 'update' for row in self.host.commands[-1][1]['actions']))
                self.workspace.handle({'page': page, 'command': 'name_plan'})
                dialog = next(data for command, data in reversed(self.host.commands) if command == 'game_name_plan')
                self.assertFalse(dialog['existing'])
                with self.assertRaises(ValueError): self.workspace.handle({'page': page, 'command': 'update'})
                self.assertEqual(self.session.knowledge.reopen(original['id'])['plan'], original)
                self.workspace.handle({'page': page, 'command': 'save'}); self.finish_job()
                self.assertNotEqual(self.workspace.saved[page]['id'], original['id'])
                self.assertEqual(self.session.knowledge.reopen(original['id'])['plan'], original)
                for key, prior in others.items(): self.assertEqual(self.workspace.saved[key], prior)

    def setUp(self):
        super().setUp()
        self.jobs = []
        self.native = SimpleNamespace(session=self.session, host=self.host, report_drafts=Mock(),
            error=Mock(), manager=self.manager, queue_io=lambda label, work, finish: self.jobs.append((work, finish)))
        self.workspace = GameWorkspace(self.native)
        self.manager.native_ui.workspace = self.workspace

    def finish_job(self):
        work, finish = self.jobs.pop(0)
        try: result, error = work(), None
        except (ValueError, OSError) as exc: result, error = None, str(exc)
        finish(result, error)

    def equipment(self):
        raw = self.workspace.raw['equipment']
        raw.update(id_a='items.weapon.melee.sword', id_b='items.weapon.melee.longsword',
            curse_a='0', curse_b='0', planning='1', upgrade_budget='2')
        self.workspace.dirty.add('equipment')

    def test_late_background_receipts_preserve_active_inventory_and_its_refresh(self):
        from companion.engine import PREFIX
        from companion.native_manager import NativeManager
        item = self.session.catalog.item({'__className': PREFIX+'items.potions.PotionOfHealing',
            'quantity': 1}, {'PotionOfHealing_known': True})
        item.update(instance_key='item-0', location='背包', available=True)
        self.session.data['items'] = [item]
        for job in ('backups', 'save'):
            with self.subTest(job=job):
                if job == 'backups':
                    self.workspace.handle({'action': 'game_page', 'page': 'backups'})
                else:
                    self.equipment(); self.workspace.calculate('equipment')
                    self.workspace.raw['equipment']['name'] = '后台保存'
                    self.workspace.handle({'page': 'equipment', 'command': 'save'})
                self.workspace.handle({'action': 'game_page', 'page': 'inventory'})
                self.finish_job()
                self.assertEqual(self.workspace.page, 'inventory')
                self.assertFalse(self.native.error.called)
                self.host.commands.clear()
                self.session.data['items'][0]['quantity'] += 1
                self.session.revision += 1
                ui = NativeManager.__new__(NativeManager)
                ui.manager, ui.session, ui.host, ui.workspace = self.manager, self.session, self.host, self.workspace
                ui.process_exit, ui.report_drafts = Mock(), Mock()
                ui.exit_state, ui.signature = None, None
                ui.update(self.session.snapshot(), force=True)
                updates = [state for action, state in self.host.commands
                           if action == 'game_state' and state['page'] == 'inventory']
                self.assertEqual(len(updates), 1)
                self.assertIn('×'+str(self.session.data['items'][0]['quantity']), updates[0]['rows'][0]['text'])

    def test_comparison_summary_keeps_speed_tradeoff_and_distinct_equipment_identity(self):
        self.equipment()
        self.workspace.raw['equipment'].update(id_b='items.weapon.melee.sword', strength='16',
            augment_a='SPEED', augment_b='DAMAGE', level_known_a='1', level_known_b='1')
        self.workspace.calculate('equipment'); self.workspace.emit('equipment')
        comparison = self.host.commands[-1][1]['comparison']
        self.assertEqual([choice['summary_name'] for choice in comparison['choices']],
                         ['单手剑 +0 · 速度', '单手剑 +0 · 伤害'])
        rows = {row['label']: row['values'] for row in comparison['summary_rows']}
        self.assertEqual(rows['最高基础伤害'], ['14', '17', '30', '36'])
        self.assertEqual(rows['攻击耗时'], ['0.666667', '0.666667', '1.66667', '1.66667'])
        self.assertNotIn('力量缺口', rows)
        self.workspace.raw['equipment'].update(id_a='items.weapon.melee.flail', strength='10')
        self.workspace.calculate('equipment'); self.workspace.emit('equipment')
        rows = {row['label']: row['values'] for row in self.host.commands[-1][1]['comparison']['summary_rows']}
        self.assertIn('力量缺口', rows); self.assertIn('命中倍率', rows)
        self.assertEqual(rows['力量与武器允许偷袭'][0], '否')

    def test_comparison_primary_includes_both_random_upgrade_outcomes_and_pending_conditions(self):
        self.equipment()
        self.workspace.raw['equipment'].update(strength='20', level_a='6', infusion_a='1', hardened_a='0', planning='0')
        self.workspace.calculate('equipment'); self.workspace.emit('equipment')
        comparison = self.host.commands[-1][1]['comparison']
        damage = next(row for row in comparison['summary_rows'] if row['label'] == '最高基础伤害')
        self.assertEqual(damage['values'][1], '52 / 44')
        self.assertEqual(comparison['summary_branches'], ['A 升级可能：注魔保留 / 注魔消失'])
        self.assertIn('非保证', ' '.join(comparison['summary_notes']))
        self.assertEqual(len(comparison['choices'][0]['upgrade_branches']), 2)
        self.assertIn('+8 ·', self.host.commands[-1][1]['text'])
        self.assertIn('+6 ·', self.host.commands[-1][1]['text'])
        self.workspace.raw['equipment'].update(infusion_a='unknown', planning='0')
        self.workspace.calculate('equipment'); self.workspace.emit('equipment')
        comparison = self.host.commands[-1][1]['comparison']
        self.assertIn('A 注魔未确认，升级待计算', comparison['summary_notes'])
        self.assertFalse(comparison.get('planning'))

    def test_armor_and_missile_summaries_keep_their_relevant_penalties_and_conditions(self):
        self.equipment()
        self.workspace.raw['equipment'].update(id_a='items.armor.platearmor', id_b='items.armor.platearmor',
            strength='16', augment_a='EVASION', augment_b='DEFENSE')
        self.workspace.calculate('equipment'); self.workspace.emit('equipment')
        comparison = self.host.commands[-1][1]['comparison']
        labels = [row['label'] for row in comparison['summary_rows']]
        for label in ('常规减伤', '力量缺口', '护甲闪避惩罚倍率', '护甲强化闪避加值', '移动速度倍率'):
            self.assertIn(label, labels)
        self.workspace.raw['equipment'].update(id_a='items.weapon.missiles.shuriken',
            id_b='items.weapon.missiles.throwingknife', augment_a='NONE', augment_b='NONE')
        self.workspace.calculate('equipment'); self.workspace.emit('equipment')
        comparison = self.host.commands[-1][1]['comparison']
        self.assertIn('未确认快速投掷就绪', ' '.join(comparison['summary_notes']))
        labels = [row['label'] for row in comparison['summary_rows']]
        self.assertIn('目标投掷耗时', labels)
        self.assertIn('相邻投掷命中倍率', labels); self.assertIn('非相邻投掷命中倍率', labels)
        self.assertNotIn('快速投掷就绪耗时', labels)

    def alchemy(self):
        self.workspace.raw['alchemy'].update(energy='12', resources='1', **{
            'r0.id': 'items.potions.potionofhealing', 'r0.quantity': '3', 'r0.reserve': '1', 'r0.origin': 'manual',
            't0.quantity': '2'})
        self.workspace.dirty.add('alchemy')

    def test_half_inputs_survive_page_switch_and_exit_copy_roundtrip(self):
        self.equipment()
        values = copy.deepcopy(self.workspace.raw['equipment']); values.update(level_a='1e', name='半输入')
        self.workspace.handle({'action': 'game_edit', 'page': 'equipment', 'values': values, 'draft_revision': 4})
        for page in ('inventory', 'alchemy', 'character', 'equipment'): self.workspace.emit(page)
        draft = self.workspace.drafts(); reopened = GameWorkspace(self.native); reopened.restore_draft(draft)
        self.assertEqual(reopened.raw['equipment']['level_a'], '1e')
        with self.assertRaises(ValueError): reopened.calculate('equipment')
        self.assertEqual(reopened.drafts(), draft)

    def test_equipment_calculation_save_name_edit_and_reopen(self):
        self.equipment(); self.workspace.calculate('equipment')
        original = copy.deepcopy(self.workspace.calculated['equipment'])
        self.workspace.edit('equipment', {**self.workspace.raw['equipment'], 'name': '两件武器', 'note': '固定预算'})
        self.assertEqual(self.workspace.calculated['equipment'], original)
        self.workspace.handle({'action': 'game_action', 'page': 'equipment', 'command': 'save'})
        self.finish_job(); self.assertFalse(self.native.error.called)
        plan = self.workspace.saved['equipment']; self.assertNotIn('equipment', self.workspace.dirty)
        self.workspace.open_plan(self.session.knowledge.reopen(plan['id']))
        self.assertEqual(self.workspace.page, 'equipment')
        self.workspace.calculate('equipment'); self.assertEqual(self.workspace.calculated['equipment'], original)

    def test_comparison_artwork_is_presentation_only_and_keeps_calculated_inputs(self):
        from companion.reference import native_artwork
        self.equipment(); self.workspace.calculate('equipment')
        calculated = copy.deepcopy(self.workspace.calculated['equipment'])
        structured = copy.deepcopy(self.workspace.structured_results['equipment'])
        self.workspace.emit('equipment')
        state = next(value for action, value in reversed(self.host.commands) if action == 'game_state')
        for choice in state['comparison']['choices']:
            self.assertEqual(choice['artwork']['sha256'], native_artwork(choice['id'])['sha256'])
        self.assertEqual(self.workspace.calculated['equipment'], calculated)
        self.assertEqual(self.workspace.structured_results['equipment'], structured)

    def test_pending_save_never_marks_new_input_saved(self):
        self.equipment(); self.workspace.calculate('equipment'); self.workspace.raw['equipment']['name'] = '原条件'
        self.workspace.handle({'page': 'equipment', 'command': 'save'})
        self.workspace.edit('equipment', {**self.workspace.raw['equipment'], 'level_a': '1e'})
        self.finish_job(); self.assertIn('equipment', self.workspace.dirty)
        self.assertEqual(self.workspace.raw['equipment']['level_a'], '1e'); self.native.error.assert_called_once()
        self.assertFalse(self.host.commands[-1][1]['notice'])
        self.assertFalse(self.host.commands[-1][1]['calculated'])

    def test_saved_notice_is_revoked_by_edits_and_not_copied_into_result(self):
        self.equipment(); self.workspace.calculate('equipment'); self.workspace.raw['equipment']['name'] = '原条件'
        self.workspace.handle({'page': 'equipment', 'command': 'save'}); self.finish_job()
        self.assertIn('已保存', self.host.commands[-1][1]['notice'])
        self.assertNotIn('已保存', self.workspace.results['equipment'])
        self.workspace.edit('equipment', {**self.workspace.raw['equipment'], 'note': '补充假设'})
        self.workspace.emit('equipment')
        self.assertFalse(self.host.commands[-1][1]['notice'])
        self.assertNotIn('已保存', self.host.commands[-1][1]['text'])
        self.workspace.edit('equipment', {**self.workspace.raw['equipment'], 'level_a': '1e'})
        self.workspace.emit('equipment')
        self.assertEqual(self.workspace.raw['equipment']['level_a'], '1e')
        self.assertFalse(self.host.commands[-1][1]['notice'])
        self.assertTrue(self.host.commands[-1][1]['dirty'])

    def test_save_revision_cannot_acknowledge_a_newer_edit_even_with_same_values(self):
        self.equipment(); self.workspace.calculate('equipment'); self.workspace.raw['equipment']['name'] = '原条件'
        self.workspace.handle({'page': 'equipment', 'command': 'save', 'draft_revision': 1})
        self.workspace.handle({'action': 'game_edit', 'page': 'equipment', 'values': copy.deepcopy(self.workspace.raw['equipment']), 'draft_revision': 2})
        self.finish_job()
        self.assertIn('equipment', self.workspace.dirty)
        self.assertFalse(self.host.commands[-1][1]['notice'])
        self.native.error.assert_called_once()

    def test_alchemy_multitarget_shared_budget_roundtrip_and_undo(self):
        self.alchemy(); self.workspace.calculate('alchemy')
        args = self.workspace.calculated['alchemy']; self.assertEqual(args['resources'][0]['reserve'], 1)
        self.assertIn('能量', self.workspace.results['alchemy'])
        self.workspace.load_alchemy(args); self.assertEqual(self.workspace.alchemy_args(), args)
        raw = copy.deepcopy(self.workspace.raw['alchemy'])
        self.workspace.handle({'page': 'alchemy', 'command': 'add_target'})
        self.workspace.handle({'page': 'alchemy', 'command': 'undo'})
        self.assertEqual(self.workspace.raw['alchemy'], raw)

    def test_alchemy_result_prioritizes_steps_and_separates_unused_stock_without_changing_result(self):
        from tests.test_alchemy_flow import params, goal, stock
        original = params([goal('potion-healing')], [stock('items.potions.potionofhealing', 3, key='item-0'),
            stock('items.weapon.melee.sword', key='item-1')], energy=12)
        self.workspace.load_alchemy(original); self.workspace.calculate('alchemy')
        calculated = copy.deepcopy(self.workspace.calculated['alchemy'])
        structured = copy.deepcopy(self.workspace.structured_results['alchemy'])
        self.workspace.emit('alchemy'); state = self.host.commands[-1][1]; text = state['text']
        self.assertTrue(text.startswith('可以制作'))
        self.assertIn('耗能 4 · 余 8', text)
        self.assertNotIn('制作顺序', text)
        steps = state['result_details'][0]
        self.assertEqual(steps['id'], 'crafting_steps'); self.assertFalse(steps['expanded'])
        self.assertTrue(steps['text'].startswith('制作顺序'))
        self.assertNotIn('可以制作', steps['text'])
        self.assertIn('材料：治疗药剂 ×1', steps['text'])
        self.assertIn('能量：12 − 4 = 8', steps['text'])
        self.assertNotIn('单手剑', text)
        self.assertNotIn('item-0', text); self.assertNotIn('item-1', text)
        self.assertEqual(len(state['result_details']), 2)
        detail = state['result_details'][1]
        self.assertEqual(detail['id'], 'unused_inventory'); self.assertFalse(detail['expanded'])
        self.assertIn('单手剑', detail['text']); self.assertIn('未消耗', detail['text'])
        self.assertEqual(self.workspace.calculated['alchemy'], calculated)
        self.assertEqual(self.workspace.structured_results['alchemy'], structured)
        self.assertEqual(self.workspace.alchemy_args(), original)
        self.workspace.edit('alchemy', {**self.workspace.raw['alchemy'], 'energy': '1e'})
        self.workspace.emit('alchemy')
        self.assertEqual(self.host.commands[-1][1]['result_details'], [])

    def test_random_alchemy_cannot_appear_guaranteed_when_details_are_closed(self):
        from tests.test_alchemy_flow import params, goal, stock
        sun = 'plants.sungrass$seed'
        self.workspace.load_alchemy(params([goal('seed-potion', 2, {'seed_ids': [sun]*3})], [stock(sun, 6)], 0))
        self.workspace.calculate('alchemy'); self.workspace.emit('alchemy')
        result = self.workspace.structured_results['alchemy']; state = self.host.commands[-1][1]
        self.assertTrue(result['within_budget']); self.assertFalse(result['complete'])
        self.assertIn('产出未确定', state['text']); self.assertIn('不能保证指定物品', state['text'])
        self.assertNotIn('可以制作', state['text']); self.assertNotIn('预算内可完成', state['text'])
        self.assertIn('不能保证治疗', state['result_details'][0]['text'])
        self.assertFalse(state['result_details'][0]['expanded'])

    def test_inventory_description_is_optional_but_identity_and_unavailability_stay_visible(self):
        item = {'instance_key': 'item-0', 'key': 'items.potions.potionofhealing', 'name': '治疗药剂', 'quantity': 2,
                'location': '背包', 'description': '完整物品说明', 'details': ['完整属性'], 'known': True, 'available': True}
        for known, revealed, available, expected in [(True, False, True, ''), (False, False, True, '身份未鉴定'),
                (False, True, False, '游戏鉴定状态未改变')]:
            self.session.data['items'] = [{**item, 'known': known, 'revealed': revealed, 'available': available}]
            rows = self.workspace.inventory()
            self.workspace.selected['inventory'] = rows[0]['id']; self.workspace.selected_tokens['inventory'] = rows[0]['token']
            self.workspace.emit('inventory'); state = self.host.commands[-1][1]
            self.assertTrue(state['text'].startswith('治疗药剂 ×2')); self.assertIn(expected, state['text'])
            self.assertNotIn('完整物品说明', state['text']); self.assertNotIn('已知公开资料', state['text'])
            if not available: self.assertIn('当前不可用', state['text'])
            self.assertFalse(state['result_details'][0]['expanded'])
            self.assertIn('完整物品说明', state['result_details'][0]['text'])
            self.assertIn('完整属性', state['result_details'][0]['text'])

    def test_alchemy_shortages_show_local_names_counts_and_specific_candidate_targets(self):
        from tests.test_alchemy_flow import params, goal, stock
        for resources, energy, expected in (([], 12, '治疗药剂 · 需用 1 / 可用 0 / 还缺 1'),
                ([stock('items.potions.potionofhealing')], 0, '能量 · 需用 4 / 可用 0 / 还缺 4')):
            with self.subTest(expected=expected):
                self.workspace.load_alchemy(params([goal('potion-healing')], resources, energy=energy))
                self.workspace.calculate('alchemy'); text = self.workspace.results['alchemy']
                self.assertIn(expected, text)
                self.assertIn('缺口 · 目标1 · 奥术护盾合剂', text)
        state = {'cursed': False, 'is_upgradable': True, 'level': 0, 'tier': 1, 'default_quantity': 3, 'durability': 100}
        original = params([goal('recipe-telekineticgrab', 8)], [stock('items.weapon.missiles.throwingstone', 3, key='item-0', state=state),
            stock('items.weapon.missiles.throwingstone', 3, key='item-1', state=state)], energy=13)
        self.workspace.load_alchemy(original); self.workspace.calculate('alchemy')
        text = self.workspace.results['alchemy']; result = self.workspace.structured_results['alchemy']
        self.assertEqual(len(result['shortages'][0]['options']), 2)
        self.assertIn('缺口 · 目标1', text)
        self.assertIn(self.workspace.names['items.liquidmetal'], text)
        self.assertIn('候选1', text); self.assertIn('候选2', text)
        stock_name = self.workspace.names['items.weapon.missiles.throwingstone']
        self.assertIn('库存1 · '+stock_name, text); self.assertIn('库存2 · '+stock_name, text)
        self.assertNotIn('item-0', text); self.assertNotIn('item-1', text)
        self.assertLess(text.index('待确认'), text.index('实际消耗材料'))
        original = params([goal('trinket-upgrade', choices={'source_key': 'item-0', 'target_level': 3})],
            [stock('items.trinkets.ratskull', key='item-0')], energy=0)
        self.workspace.load_alchemy(original); self.workspace.calculate('alchemy')
        text = self.workspace.results['alchemy']
        self.assertIn('需用 1 / 可用 0 / 还缺 1', text)
        self.assertIn('对应材料：库存1 · '+self.workspace.names['items.trinkets.ratskull'], text)
        self.assertIn('初始等级与目标等级', text)
        self.assertNotIn('item-0', text)

    def test_character_unknown_and_complete_inputs(self):
        self.workspace.raw['character']['base_strength'] = ''
        self.workspace.calculate('character'); self.assertIn('尚未确认', self.workspace.results['character'])
        from companion.character_scene import empty_scene
        scene = empty_scene(12); self.workspace.load_character(scene)
        self.workspace.calculate('character'); self.assertIn('总力量 12', self.workspace.results['character'])
        self.assertEqual(self.workspace.character_args(), scene)

    def test_structure_counts_and_boolean_invalid_raw_not_coerced(self):
        self.workspace.raw['alchemy']['resources'] = '99999999'
        with self.assertRaises(ValueError): self.workspace.alchemy_fields()
        self.workspace.raw['character']['magic_immune'] = 'maybe'
        with self.assertRaises(ValueError): self.workspace.character_args()
        self.assertEqual(self.workspace.raw['character']['magic_immune'], 'maybe')

    def test_stale_edit_revision_does_not_replace_new_raw(self):
        raw = copy.deepcopy(self.workspace.raw['equipment']); raw['level_a'] = '1e'
        self.workspace.handle({'action': 'game_edit', 'page': 'equipment', 'values': raw, 'draft_revision': 9})
        self.workspace.handle({'action': 'game_edit', 'page': 'equipment', 'values': {**raw, 'level_a': '0'}, 'draft_revision': 8})
        self.assertEqual(self.workspace.raw['equipment']['level_a'], '1e')

    def test_open_plan_cannot_replace_unsaved_work(self):
        self.equipment()
        before = copy.deepcopy(self.workspace.raw['equipment'])
        self.assertFalse(self.workspace.open_plan({'plan': {'kind': 'equipment'}}))
        self.assertEqual(self.workspace.raw['equipment'], before)
        self.assertEqual(self.host.commands[-1][1]['purpose'], 'game_replace')
        self.workspace.replace_decision('cancel')
        self.assertEqual(self.workspace.raw['equipment'], before)

    def test_half_input_switch_preserves_raw_or_explicitly_discards_all_task_kinds(self):
        from companion.character_scene import empty_scene
        for page, key in [('equipment', 'level_a'), ('alchemy', 'energy'), ('character', 'base_strength')]:
            with self.subTest(page=page):
                self.equipment(); self.alchemy(); self.workspace.load_character(empty_scene(12), dirty=False)
                self.workspace.calculate(page)
                self.workspace.raw[page]['name'] = '固定'+page
                self.workspace.handle({'page': page, 'command': 'save'}); self.finish_job()
                plan = self.session.knowledge.reopen(self.workspace.saved[page]['id'])
                self.workspace.open_plan(plan)
                baseline = copy.deepcopy(self.workspace.raw[page])
                state = [d for action, d in self.host.commands if action == 'game_state' and d['page'] == page][-1]
                ui_raw = {**state['raw'], **{spec['key']: spec['raw'] for spec in state['fields']}}
                self.workspace.edit(page, ui_raw)
                self.assertIn(page, self.workspace.calculated)
                self.assertNotIn(page, self.workspace.dirty)
                raw = {**baseline, key: '1e'}
                self.workspace.edit(page, raw)
                raw = copy.deepcopy(self.workspace.raw[page])
                self.assertFalse(self.workspace.open_plan(plan))
                self.workspace.replace_decision('cancel')
                self.assertEqual(self.workspace.raw[page], raw)
                self.workspace.open_plan(plan); self.workspace.replace_decision('saved')
                saved = self.session.load_exit_draft(self.session.list_exit_drafts()[0]['id'])
                self.assertEqual(saved['draft'][page]['values'][key], '1e')
                self.assertEqual(self.workspace.raw[page], baseline)
                self.assertNotIn(page, self.workspace.dirty)
                self.workspace.edit(page, raw); self.workspace.open_plan(plan)
                self.workspace.replace_decision('discard')
                self.assertEqual(self.workspace.raw[page], baseline)
                self.workspace.edit(page, raw)
                self.workspace.handle({'page': page, 'command': 'undo'})
                self.assertEqual(self.workspace.raw[page], baseline)

    def test_plan_confirmation_never_discards_newer_input_or_failed_copy(self):
        self.equipment(); self.workspace.calculate('equipment')
        self.workspace.raw['equipment']['name'] = '固定武器'
        self.workspace.handle({'page': 'equipment', 'command': 'save'}); self.finish_job()
        plan = self.session.knowledge.reopen(self.workspace.saved['equipment']['id'])
        self.workspace.edit('equipment', {**self.workspace.raw['equipment'], 'level_a': '1e'})
        self.workspace.open_plan(plan)
        self.workspace.edit('equipment', {**self.workspace.raw['equipment'], 'level_a': '-'})
        with self.assertRaisesRegex(ValueError, '变化'):
            self.workspace.replace_decision('discard')
        self.workspace.open_plan(plan)
        from unittest.mock import patch
        with patch.object(self.session, 'save_exit_draft', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): self.workspace.replace_decision('saved')
        self.assertEqual(self.workspace.raw['equipment']['level_a'], '-')
        self.assertIn('equipment', self.workspace.dirty)

    def test_revealed_equipment_handoff_and_reversible_disclosure_are_read_only(self):
        from companion.engine import PREFIX
        root, slot = self.saved_game()
        path = slot/'game.dat'; game = json.loads(path.read_text(encoding='utf-8'))
        game['hero']['inventory'].append({'__className': PREFIX+'items.rings.RingOfMight',
            'level': 2, 'levelKnown': False, 'cursed': False, 'cursedKnown': False})
        path.write_text(json.dumps(game), encoding='utf-8'); self.session.refresh()
        original = path.read_bytes()
        ring = next(r for r in self.workspace.inventory() if r['item']['name'] == '未鉴定戒指')
        self.select('inventory', ring)
        with self.assertRaises(ValueError): self.workspace.inventory_action('equip_a')
        self.workspace.inventory_action('reveal'); self.finish_job()
        self.workspace.inventory_action('equip_a')
        self.assertEqual(self.workspace.raw['equipment']['level_a'], '2')
        self.assertIn('主动揭示', self.workspace.sources['equipment']['fields']['id_a'])
        self.workspace.inventory_action('hide_reveal')
        self.assertFalse(self.workspace.revealed)
        self.workspace.inventory_action('reveal')
        self.workspace.hide_inventory_reveals(); self.finish_job()
        self.assertFalse(self.workspace.revealed)
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(self.session.settings['reveal'])

    def test_ready_restores_persisted_plan_list_without_overwriting_lookup_draft(self):
        from companion.native_manager import NativeManager
        self.equipment(); self.workspace.calculate('equipment'); self.workspace.raw['equipment']['name'] = '持久方案'
        self.workspace.handle({'page': 'equipment', 'command': 'save'}); self.finish_job()
        self.open('items.weapon.melee.sword'); self.lookup.variables['level'].set('1e')
        ui = NativeManager.__new__(NativeManager)
        ui.manager, ui.session, ui.host, ui.workspace = self.manager, self.session, self.host, self.workspace
        ui.layout = SimpleNamespace(values={'page': 'plans'}, original={'page': 'plans'})
        ui.update, ui.error = Mock(), Mock()
        ui.report_drafts = Mock()
        ui.dispatch({'action': 'ready'})
        ui.error.assert_not_called()
        plans = [d for action, d in self.host.commands if action == 'plans'][-1]
        self.assertIn('持久方案', plans['rows'][0]['text'])
        self.assertEqual(self.lookup.variables['level'].get(), '1e')

    def test_backup_execute_requires_unchanged_explicit_preview(self):
        with self.assertRaises(ValueError): self.workspace.handle({'page': 'backups', 'command': 'backup_execute', 'token': 'guess'})
        self.assertFalse(self.jobs)

    def test_shared_character_target_and_each_budget_option_use_real_engine(self):
        self.equipment()
        self.workspace.raw['character']['base_strength'] = '14'
        self.workspace.handle({'page': 'equipment', 'command': 'use_character'})
        self.workspace.raw['equipment'].update({'context.combat_model': 'ordinary-v1', 'context.target_enabled': '1',
            'context.target.name': '普通目标', 'context.target.base_accuracy': '20', 'context.target.evasion': '10',
            'context.target.dr_min': '1', 'context.target.dr_max': '3', 'context.investment_mode': 'all'})
        self.workspace.calculate('equipment')
        canonical = self.workspace.calculated['equipment']
        self.assertEqual(canonical['character_scene']['base_strength'], 14)
        self.assertEqual(canonical['target_context']['evasion'], 10)
        for text in ('目标模型命中率参考', '投入 0 卷', '投入 1 卷', '投入 2 卷', '当前 / 升级一次'):
            self.assertIn(text, self.workspace.results['equipment'])
        self.workspace.raw['character']['base_strength'] = '30'
        self.assertEqual(self.workspace.equipment_args()['character_scene']['base_strength'], 14)
        self.workspace.raw['equipment']['context.scene_enabled'] = '0'
        self.assertNotIn('character_scene', self.workspace.equipment_args())
        self.workspace.raw['equipment']['context.target.evasion'] = '1e'
        with self.assertRaises(ValueError): self.workspace.calculate('equipment')
        self.assertEqual(self.workspace.raw['equipment']['context.target.evasion'], '1e')

    def test_shared_character_transfer_keeps_old_source_actual_strength_and_saved_origin(self):
        from companion.character_scene import empty_scene, calculate_scene
        snap = copy.deepcopy(self.session.snapshot())
        snap['settings']['mode'] = 'save'
        snap.update(active_slot=1, modified=1000, stale=False, error='')
        snap['data']['character_scene'] = calculate_scene(empty_scene(10))
        self.session.snapshot = lambda: copy.deepcopy(snap)
        self.equipment(); self.workspace.import_snapshot('character')
        snap.update(active_slot=2, modified=2000)
        snap['data']['character_scene'] = calculate_scene(empty_scene(18))
        self.workspace.import_snapshot('equipment')
        original = copy.deepcopy((self.workspace.raw['equipment'], self.workspace.sources['equipment']))
        self.workspace.handle({'page': 'equipment', 'command': 'use_character'})
        self.workspace.calculate('equipment'); self.workspace.emit('equipment')
        data = self.host.commands[-1][1]
        self.assertTrue(data['task_source']['stale'])
        self.assertIn('不同保存条件', data['task_source']['brief'])
        self.assertEqual(self.workspace.sources['equipment']['slot'], 1)
        self.assertIn('槽位 1', self.workspace.sources['equipment']['fields']['character_scene'])
        self.assertIn('槽位 2', self.workspace.sources['equipment']['fields']['strength'])
        strength = next(row for row in data['fields'] if row['key'] == 'strength')
        self.assertEqual(strength['raw'], '18')
        self.assertIn('停用角色条件后生效', strength['label'])
        self.assertEqual(data['comparison']['summary_context'], '当前角色力量 10 · 覆盖独立力量')
        self.assertEqual(data['comparison']['choices'][0]['character_scene']['strength']['effective'], 10)
        self.workspace.raw['equipment']['name'] = '跨槽位角色'
        self.workspace.handle({'page': 'equipment', 'command': 'save'}); self.finish_job()
        saved = self.workspace.saved['equipment']
        self.assertTrue(saved['origin']['mixed_snapshots'])
        self.workspace.dirty.clear(); self.workspace.open_plan(self.session.knowledge.reopen(saved['id']))
        self.assertTrue(self.workspace.sources['equipment']['mixed_snapshots'])
        self.assertTrue(self.workspace.source_status('equipment')['stale'])
        self.assertIn('槽位 1', self.workspace.sources['equipment']['fields']['character_scene'])
        self.workspace.raw['equipment']['context.scene_enabled'] = '0'
        self.workspace.calculate('equipment'); self.workspace.emit('equipment')
        self.assertNotIn('character_scene', self.workspace.calculated['equipment'])
        self.assertFalse(self.host.commands[-1][1]['comparison']['summary_context'])
        # The transfer can also be undone without changing either original source.
        self.workspace.raw['equipment'], self.workspace.sources['equipment'] = copy.deepcopy(original)
        self.workspace.handle({'page': 'equipment', 'command': 'use_character'})
        self.workspace.handle({'page': 'equipment', 'command': 'undo'})
        self.assertEqual((self.workspace.raw['equipment'], self.workspace.sources['equipment']), original)

    def test_manual_character_transfer_has_no_claim_of_current_snapshot(self):
        self.equipment()
        self.workspace.raw['character']['base_strength'] = '14'
        self.workspace.handle({'page': 'equipment', 'command': 'use_character'})
        self.workspace.calculate('equipment'); self.workspace.emit('equipment')
        self.assertEqual(self.workspace.sources['equipment']['mode'], 'example')
        self.assertIn('手填', self.workspace.sources['equipment']['fields']['character_scene'])
        self.assertIn('含手填假设', self.host.commands[-1][1]['task_source']['brief'])

    def test_alchemy_saved_instance_keys_and_hidden_state_roundtrip(self):
        from tests.test_alchemy_flow import params, goal, stock
        original = params([goal('resin', 6, {'source_keys': ['saved-wand']}, key='retained-target')],
            [stock('items.wands.wandofmagicmissile', key='saved-wand', state={'cursed': False,
                'base_level': 2, 'public_level': 3, 'resin_bonus': 1, 'hero_class': 'MAGE'})], energy=5)
        self.workspace.load_alchemy(original)
        self.assertEqual(self.workspace.raw['alchemy']['t0.source_keys'], 'r0')
        self.assertEqual(self.workspace.alchemy_args(), original)
        self.workspace.calculate('alchemy')
        self.assertIn('×6', self.workspace.results['alchemy'])
        self.assertEqual(self.workspace.calculated['alchemy']['targets'][0]['choices']['source_keys'], ['saved-wand'])

    def test_legacy_alchemy_copy_is_editable_and_original_raw_can_be_undone(self):
        legacy = {'recipe': 'stone-identify', 'recipe_version': '4.0.2', 'batches': 2,
            'energy': 0, 'energy_reserve': 0, 'energy_origin': 'manual', 'reference_version': None,
            'resources': [{'id': 'items.scrolls.scrollofidentify', 'quantity': 2, 'reserve': 0, 'origin': 'manual'}]}
        self.workspace.legacy_alchemy = legacy
        self.workspace.raw['alchemy'] = {'legacy': json.dumps(legacy), 'name': '原方案', 'note': '保留备注'}
        self.workspace.saved['alchemy'] = {'id': 'original'}
        before = copy.deepcopy(self.workspace.raw['alchemy'])
        self.workspace.handle({'page': 'alchemy', 'command': 'convert_legacy'})
        self.assertNotIn('alchemy', self.workspace.saved)
        self.assertEqual(self.workspace.raw['alchemy']['t0.quantity'], '4')
        self.workspace.calculate('alchemy'); self.assertIn('×4', self.workspace.results['alchemy'])
        self.workspace.handle({'page': 'alchemy', 'command': 'undo'})
        self.assertEqual(self.workspace.raw['alchemy'], before)

    def saved_game(self, hp=20):
        root = self.directory/'saves'; slot = root/'game1'; slot.mkdir(parents=True, exist_ok=True)
        from companion.engine import PREFIX
        game = {'version': 922, 'seed': 9, 'depth': 2, 'branch': 0, 'generated_levels': [2],
            'hero': {'class': 'MAGE', 'HP': hp, 'HT': 30, 'STR': 12, 'lvl': 3, 'buffs': [], 'inventory': [
                {'__className': PREFIX+'items.weapon.melee.Sword', 'level': 2, 'levelKnown': True, 'cursedKnown': True},
                {'__className': PREFIX+'items.potions.PotionOfHealing', 'quantity': 3, 'levelKnown': False, 'cursedKnown': False}]}}
        (slot/'game.dat').write_text(json.dumps(game), encoding='utf8')
        (slot/'depth2.dat').write_text(json.dumps({'level': {'__className': PREFIX+'levels.SewerLevel', 'version': 922,
            'width': 4, 'height': 4, 'map': [4]*16, 'visited': [False]*16, 'mapped': [False]*16}}), encoding='utf8')
        self.session.update_settings({'save_root': str(root), 'slot': 1, 'mode': 'save', 'reveal': False})
        self.session.refresh()
        return root, slot

    def select(self, page, row):
        self.workspace.handle({'action': 'game_select', 'page': page, 'id': row['id'], 'token': row['token']})

    def test_backup_target_version_survives_history_preview_confirmation_and_receipt(self):
        for version in (849, 922, None):
            with self.subTest(version=version):
                root, slot = self.saved_game()
                game_path = slot/'game.dat'; game = json.loads(game_path.read_text())
                if version is None: game.pop('version')
                else: game['version'] = version
                game_path.write_text(json.dumps(game), encoding='utf-8')
                level_path=slot/'depth2.dat'; level=json.loads(level_path.read_text())
                level['level']['version']=version if version is not None else 922
                level_path.write_text(json.dumps(level),encoding='utf-8')
                self.session.refresh(); self.session.backups.closed_check = lambda: None
                self.session.backup_action({'action': 'capture'})
                self.saved_game(hp=3)
                before = {p.name:p.read_bytes() for p in slot.iterdir()}
                self.workspace.reload('backups'); self.finish_job()
                row = next(row for row in self.workspace.rows['backups'] if row['action']=='restore'
                           and row['entry'].get('version')==version and row['entry'].get('hp')==20)
                self.select('backups', row); self.workspace.preview_backup(); self.finish_job()
                submitted = copy.deepcopy(self.workspace.backup_preview)
                state=self.host.commands[-1][1]
                self.assertTrue(state['text'].startswith('目标进度'))
                self.assertNotIn('保存时间',state['text'])
                self.assertFalse(state['result_details'][0]['expanded'])
                self.assertIn(submitted['text'],state['result_details'][0]['text'])
                self.workspace.handle({'page':'backups','command':'backup_confirm'})
                confirmation = next(value for action,value in reversed(self.host.commands) if action=='game_confirm')
                expected = '来源版本未知' if version is None else '版本码 '+str(version)
                for text in (row['text'], self.workspace.backup_row_summary('restore',row['entry']), state['text'],
                             submitted['text'], confirmation['text']):
                    self.assertIn(expected,text)
                    if version==849:self.assertIn('无法继续此旧档',text)
                self.assertEqual(submitted['progress']['target']['version'],version)
                self.assertEqual({p.name:p.read_bytes() for p in slot.iterdir()},before)
                self.workspace.backup_done({'ok':True},None,submitted)
                self.assertIn(expected,self.workspace.notices['backups'])
                self.finish_job()

    def test_undo_preview_uses_preserved_original_version_and_same_seed_does_not_prove_identity(self):
        root, slot = self.saved_game()
        self.session.backups.closed_check = lambda: None
        self.session.backup_action({'action':'capture'})
        self.saved_game(hp=3)
        game_path=slot/'game.dat'; game=json.loads(game_path.read_text())
        game.update(version=849,depth=1,duration=0,generated_levels=[1])
        game['hero'].update(lvl=1)
        game_path.write_text(json.dumps(game),encoding='utf-8')
        (slot/'depth1.dat').write_bytes((slot/'depth2.dat').read_bytes())
        self.session.refresh()
        before={p.name:p.read_bytes() for p in slot.iterdir()}
        self.workspace.reload('backups'); self.finish_job()
        row=next(row for row in self.workspace.rows['backups'] if row['action']=='restore')
        self.select('backups',row); self.workspace.preview_backup(); self.finish_job()
        preview=self.workspace.backup_preview
        self.assertTrue(preview['progress']['same_run'])
        self.assertIn('种子和职业一致，请核对是否同一局',preview['text'])
        self.assertNotIn('同一次冒险',preview['text'])
        self.assertNotIn(preview['progress']['target']['run_id'][:12],preview['text'])
        self.workspace.handle({'page':'backups','command':'backup_execute','token':preview['token']})
        self.finish_job(); self.finish_job()
        row=next(row for row in self.workspace.rows['backups'] if row['action']=='undo')
        self.select('backups',row); self.workspace.preview_backup(); self.finish_job()
        preview=self.workspace.backup_preview
        self.assertEqual(preview['progress']['current']['version'],922)
        self.assertEqual(preview['progress']['target']['version'],849)
        self.workspace.handle({'page':'backups','command':'backup_confirm'})
        confirmation=next(value for action,value in reversed(self.host.commands) if action=='game_confirm')
        self.assertIn('版本码 849',confirmation['text']); self.assertIn('无法继续此旧档',confirmation['text'])
        self.workspace.handle({'page':'backups','command':'backup_execute','token':preview['token']})
        self.finish_job(); self.finish_job()
        self.assertEqual({p.name:p.read_bytes() for p in slot.iterdir()},before)
        self.assertIn('版本码 849',self.workspace.notices['backups'])

    def test_unreadable_current_progress_is_not_presented_as_an_empty_slot(self):
        root,slot=self.saved_game();self.session.backups.closed_check=lambda:None
        self.session.backup_action({'action':'capture'})
        (slot/'game.dat').write_bytes(b'{broken json')
        self.session.refresh();before={p.name:p.read_bytes() for p in slot.iterdir()}
        self.workspace.reload('backups');self.finish_job()
        row=next(row for row in self.workspace.rows['backups'] if row['action']=='restore')
        self.select('backups',row);self.workspace.preview_backup();self.finish_job()
        preview=self.workspace.backup_preview;warning=preview['progress']['current']['warning']
        self.assertTrue(warning);self.assertIn('进度无法读取',preview['brief'])
        self.assertNotIn('空槽位',preview['brief'])
        self.workspace.handle({'page':'backups','command':'backup_confirm'})
        confirmation=next(value for action,value in reversed(self.host.commands) if action=='game_confirm')
        self.assertIn(warning,confirmation['text']);self.assertIn(warning,preview['brief'])
        self.assertEqual({p.name:p.read_bytes() for p in slot.iterdir()},before)

    def test_inventory_unknown_reading_explicit_reveal_and_stale_selection(self):
        root, slot = self.saved_game()
        original = {p.name: p.read_bytes() for p in slot.iterdir()}
        rows = self.workspace.inventory(); self.assertEqual(len(rows), 2)
        unknown = next(r for r in rows if not r['item']['known'])
        self.select('inventory', unknown)
        with self.assertRaisesRegex(ValueError, '主动揭示'): self.workspace.inventory_action('equip_a')
        self.workspace.inventory_action('reveal'); self.finish_job()
        self.assertTrue(self.workspace.revealed[unknown['id']]['revealed'])
        self.assertFalse(self.workspace.revealed[unknown['id']]['known'])
        self.assertEqual({p.name: p.read_bytes() for p in slot.iterdir()}, original)
        self.assertFalse(self.session.settings['reveal'])
        known = next(r for r in self.workspace.inventory() if r['item']['key'] == 'items.weapon.melee.sword')
        self.select('inventory', known); self.workspace.inventory_action('equip_a')
        self.assertEqual(self.workspace.raw['equipment']['level_a'], '2')
        self.saved_game(hp=19)
        with self.assertRaisesRegex(ValueError, '重新选择'): self.workspace.inventory_action('equip_b')

    def test_saved_map_is_opt_in_and_selected_generation_bound(self):
        root, slot = self.saved_game(); original = {p.name: p.read_bytes() for p in slot.iterdir()}
        self.workspace.reload('map'); self.finish_job()
        self.assertIsNone(self.workspace.map_result)
        row = self.workspace.rows['map'][0]; self.select('map', row)
        self.workspace.reveal_map(); self.finish_job()
        self.assertEqual(self.workspace.map_result['depth'], 2)
        self.assertEqual(self.workspace.map_result['map']['width'], 4)
        self.assertEqual({p.name: p.read_bytes() for p in slot.iterdir()}, original)
        self.workspace.handle({'page': 'map', 'command': 'map_hide'}); self.assertIsNone(self.workspace.map_result)

    def test_native_backup_preview_keeps_closed_game_guard_and_preserves_original(self):
        root, slot = self.saved_game()
        self.session.backups.closed_check = lambda: None
        self.session.backup_action({'action': 'capture'})
        original = {p.name: p.read_bytes() for p in slot.iterdir()}
        self.saved_game(hp=3); current = {p.name: p.read_bytes() for p in slot.iterdir()}
        self.workspace.reload('backups'); self.finish_job()
        self.select('backups', self.workspace.rows['backups'][0])
        self.workspace.preview_backup(); self.finish_job()
        self.assertIsNotNone(self.workspace.backup_preview)
        self.workspace.handle({'page': 'backups', 'command': 'backup_confirm'})
        self.assertEqual(self.host.commands[-2][0], 'game_confirm')
        confirmation = self.host.commands[-2][1]
        self.assertEqual(confirmation['slot'], 1)
        self.assertEqual(confirmation['save_root'], str(root.resolve()))
        self.assertIn(str(root.resolve()), confirmation['text'])
        self.assertFalse(confirmation['undo'])
        token = self.workspace.backup_preview['token']
        submitted = copy.deepcopy(self.workspace.backup_preview)
        selection = self.workspace.selected['backups']
        self.session.backups.closed_check = lambda: (_ for _ in ()).throw(ValueError('游戏仍在运行'))
        self.workspace.handle({'page': 'backups', 'command': 'backup_execute', 'token': token}); self.finish_job()
        self.assertEqual({p.name: p.read_bytes() for p in slot.iterdir()}, current)
        self.assertIn('运行', self.native.error.call_args.args[0])
        self.assertIn('游戏仍在运行', self.workspace.notices['backups'])
        self.assertIn(submitted['payload']['id'], self.workspace.notices['backups'])
        self.assertIsNone(self.workspace.backup_preview)
        with self.assertRaisesRegex(ValueError, '预览已变化'):
            self.workspace.handle({'page': 'backups', 'command': 'backup_execute', 'token': token})
        self.finish_job()
        self.assertEqual(self.workspace.selected['backups'], selection)
        self.workspace.preview_backup(); self.finish_job()
        self.session.backups.closed_check = lambda: None
        self.workspace.handle({'page': 'backups', 'command': 'backup_execute', 'token': self.workspace.backup_preview['token']}); self.finish_job()
        self.assertEqual({p.name: p.read_bytes() for p in slot.iterdir()}, original)
        self.assertIn('完整保留', self.workspace.notices['backups'])
        self.assertIn(submitted['payload']['id'], self.workspace.notices['backups'])
        retained = list(root.glob('.denghuo-before-1-*'))
        self.assertEqual(len(retained), 1)
        self.assertEqual({p.name: p.read_bytes() for p in retained[0].iterdir()}, current)
        self.finish_job()
        undo = next(r for r in self.workspace.rows['backups'] if r['action'] == 'undo')
        self.select('backups', undo); self.workspace.preview_backup(); self.finish_job()
        self.assertEqual(self.workspace.backup_preview['payload']['confirm'], '撤回槽位 1')
        self.workspace.handle({'page': 'backups', 'command': 'backup_confirm'})
        confirmation = self.host.commands[-2][1]
        self.assertEqual(confirmation['save_root'], str(root.resolve()))
        self.assertIn(str(root.resolve()), confirmation['text'])
        self.assertTrue(confirmation['undo'])
        self.workspace.handle({'page': 'backups', 'command': 'backup_execute', 'token': self.workspace.backup_preview['token']})
        self.finish_job()
        self.assertEqual({p.name: p.read_bytes() for p in slot.iterdir()}, current)

    def native_update(self):
        from companion.native_manager import NativeManager
        ui = NativeManager.__new__(NativeManager)
        ui.session, ui.manager, ui.host, ui.workspace = self.session, self.manager, self.host, self.workspace
        ui.process_exit, ui.report_drafts, ui.floor_state = Mock(), Mock(), Mock(return_value={})
        ui.exit_state, ui.signature = None, None
        self.manager.action_error = ''
        ui.update(self.session.snapshot())

    def test_public_map_masks_unknown_and_secret_tiles_before_opt_in(self):
        _, slot = self.saved_game()
        path = slot/'depth2.dat'; bundle = json.loads(path.read_text(encoding='utf8'))
        bundle['level'].update(map=[16, 17, 1, 8]+[4]*12, visited=[True]*3+[False]*13)
        path.write_text(json.dumps(bundle), encoding='utf8'); self.session.refresh()
        self.workspace.emit('map')
        state = self.host.commands[-1][1]
        self.assertEqual(state['map']['tiles'][:4], [4, 1, 1, -1])
        self.assertFalse(state['map_revealed'])
        self.assertIn('已探索地形', state['text'])
        self.assertIn('非实时视野', state['text'])
        self.assertEqual(state['result_details'][0]['id'], 'map_discoveries')
        self.assertFalse(state['result_details'][0]['expanded'])
        self.assertGreater(len(state['result_details'][0]['text']), len(state['text']))
        self.assertIn('map_known', [row['id'] for row in state['actions']])
        self.assertIsNone(self.workspace.map_result)

    def test_map_sources_invalidate_visible_results_and_keep_unrelated_drafts(self):
        for change in ('save', 'slot', 'directory', 'manual', 'error'):
            with self.subTest(change=change):
                root, slot = self.saved_game()
                self.equipment(); self.workspace.raw['equipment']['level_a'] = '1e'
                self.workspace.reload('map'); self.finish_job()
                self.select('map', self.workspace.rows['map'][0])
                self.workspace.reveal_map(); self.finish_job()
                self.assertIsNotNone(self.workspace.map_result)
                before = copy.deepcopy(self.workspace.drafts())
                if change == 'save': self.saved_game(hp=19)
                elif change == 'slot':
                    target = root/'game2'; target.mkdir(exist_ok=True)
                    for path in slot.iterdir(): (target/path.name).write_bytes(path.read_bytes())
                    self.session.update_settings({'slot': 2}); self.session.refresh()
                elif change == 'directory':
                    target = self.directory/'other-saves'; target.mkdir(exist_ok=True)
                    self.session.update_settings({'save_root': str(target)}); self.session.refresh()
                elif change == 'manual': self.session.update_manual({'hp': 4, 'ht': 30, 'level': 5})
                else:
                    (slot/'game.dat').write_text('broken', encoding='utf8'); self.session.refresh()
                self.native_update()
                self.assertIsNone(self.workspace.map_result)
                self.assertIsNone(self.workspace.map_catalog)
                self.assertEqual(self.workspace.rows['map'], [])
                self.assertNotIn('map', self.workspace.selected)
                self.assertEqual(self.workspace.drafts(), before)
                states = [value for action, value in self.host.commands if action == 'game_state' and value['page'] == 'map']
                self.assertFalse(states[-1]['map_revealed'])
                self.assertNotIn('已主动揭示', states[-1]['text'])

    def test_old_map_catalog_and_reveal_callbacks_cannot_publish(self):
        self.saved_game()
        self.workspace.reload('map')
        work, finish = self.jobs.pop(0); result = work()
        self.saved_game(hp=19); self.native_update()
        count = len(self.host.commands); finish(result, None)
        self.assertIsNone(self.workspace.map_catalog)
        self.assertEqual(len(self.host.commands), count)
        self.workspace.reload('map'); self.finish_job()
        self.select('map', self.workspace.rows['map'][0]); self.workspace.reveal_map()
        work, finish = self.jobs.pop(0); result = work()
        self.saved_game(hp=18); self.native_update()
        count = len(self.host.commands); finish(result, None)
        self.assertIsNone(self.workspace.map_result)
        self.assertEqual(len(self.host.commands), count)

    def test_late_callback_detecting_source_change_still_publishes_invalidation(self):
        for pending in ('catalog', 'reveal'):
            with self.subTest(pending=pending):
                self.saved_game()
                self.workspace.reload('map'); self.finish_job()
                self.select('map', self.workspace.rows['map'][0])
                self.workspace.reveal_map(); self.finish_job()
                self.assertTrue(self.host.commands[-1][1]['map_revealed'])
                self.equipment(); self.workspace.raw['equipment']['level_a'] = '1e'
                before = copy.deepcopy(self.workspace.drafts())
                if pending == 'catalog': self.workspace.reload('map')
                else: self.workspace.reveal_map()
                work, finish = self.jobs.pop(0); result = work()
                self.saved_game(hp=17)
                count = len(self.host.commands); finish(result, None)
                self.assertEqual(len(self.host.commands), count)
                self.assertIsNone(self.workspace.map_result)
                self.assertTrue(self.workspace.map_publication_pending)
                self.native_update()
                states = [data for command, data in self.host.commands[count:] if command == 'game_state']
                self.assertEqual(len(states), 1)
                self.assertFalse(states[0]['map_revealed'])
                self.assertFalse(self.workspace.map_publication_pending)
                self.assertFalse(self.workspace.sync_map_source())
                self.assertEqual(self.workspace.drafts(), before)

    def test_hide_revokes_pending_map_reveal(self):
        self.saved_game(); self.workspace.reload('map'); self.finish_job()
        self.select('map', self.workspace.rows['map'][0]); self.workspace.reveal_map()
        work, finish = self.jobs.pop(0); result = work()
        self.workspace.handle({'page': 'map', 'command': 'map_hide'})
        finish(result, None)
        self.assertIsNone(self.workspace.map_result)
        self.assertFalse(self.host.commands[-1][1]['map_revealed'])
        self.assertTrue(self.host.commands[-1][1]['map'])

    def test_saved_origin_survives_reopen_note_update_and_copy_for_all_kinds(self):
        for page in ('equipment', 'alchemy', 'character'):
            with self.subTest(page=page):
                self.workspace = GameWorkspace(self.native)
                if page == 'equipment': self.equipment()
                elif page == 'alchemy': self.alchemy()
                self.workspace.calculate(page)
                params = copy.deepcopy(self.workspace.calculated[page])
                key = {'equipment': 'strength', 'alchemy': 'energy', 'character': 'base_strength'}[page]
                source = {'mode': 'save', 'slot': 2, 'snapshot_at': 1791809981.25, 'fields': {key: '已知快照 · 固定条件'}}
                if page == 'equipment':
                    source['references'] = {side: {'id': params['id_'+side], 'name': self.workspace.names[params['id_'+side]],
                        'effect_id': 'items.weapon.enchantments.blazing', 'user_note': {'title': side, 'body': '公开备注', 'scope': 'specific_item'}} for side in ('a', 'b')}
                saved = self.session.knowledge.save('网页来源 '+page, page, None, params, source)
                self.workspace.dirty.clear()
                self.workspace.open_plan(self.session.knowledge.reopen(saved['id']))
                self.workspace.edit(page, {**self.workspace.raw[page], 'note': '只改备注'})
                self.workspace.handle({'page': page, 'command': 'update'}); self.finish_job()
                self.native.error.assert_not_called()
                updated = self.workspace.saved[page]
                self.assertEqual(updated['origin'], saved['origin'])
                self.assertEqual(updated['params'], saved['params'])
                self.workspace.edit(page, {**self.workspace.raw[page], 'name': '副本 '+page})
                self.workspace.handle({'page': page, 'command': 'save'}); self.finish_job()
                self.assertEqual(self.workspace.saved[page]['origin'], saved['origin'])
                self.assertNotEqual(self.workspace.saved[page]['id'], saved['id'])

    def test_related_manual_edit_changes_only_matching_field_provenance(self):
        self.equipment(); self.workspace.calculate('equipment')
        source = {'mode': 'save', 'slot': 2, 'snapshot_at': 1791809981.25,
                  'fields': {'strength': '快照', 'level_a': '快照', 'id_a': '快照'}}
        saved = self.session.knowledge.save('固定条件', 'equipment', None, self.workspace.calculated['equipment'], source)
        self.workspace.dirty.clear(); self.workspace.open_plan(self.session.knowledge.reopen(saved['id']))
        self.workspace.edit('equipment', {**self.workspace.raw['equipment'], 'level_a': '4'})
        self.assertEqual(self.workspace.sources['equipment']['fields']['strength'], '快照')
        self.assertEqual(self.workspace.sources['equipment']['fields']['level_a'], '手填 · 固定假设')
        self.assertEqual(self.workspace.sources['equipment']['slot'], 2)

    def test_alchemy_identity_switch_ignores_hidden_state_and_preserves_half_input(self):
        identities = [self.workspace.resources[key][0] for key in ('wands', 'missiles', 'trinkets', 'catalyst')]
        identities.append('items.food.blandfruit')
        shielding = next(row['id'] for row in self.workspace.recipes if row.get('output', '').endswith('.potionofshielding'))
        for identity in identities:
            with self.subTest(identity=identity):
                self.alchemy()
                raw = copy.deepcopy(self.workspace.raw['alchemy'])
                raw.update({'r0.id': identity, 'r0.reserve': '0', 't0.recipe': shielding, 't0.quantity': '1'})
                self.workspace.edit('alchemy', raw)
                fields = [row for row in self.workspace.alchemy_fields() if row['key'].startswith('r0.state.')]
                self.assertTrue(fields)
                state_key = fields[0]['key']; raw[state_key] = '1e'
                self.workspace.edit('alchemy', raw)
                raw = {**self.workspace.raw['alchemy'], 'r0.id': 'items.potions.potionofhealing'}
                self.workspace.edit('alchemy', raw)
                self.assertEqual(self.workspace.alchemy_args()['resources'][0]['state'], {})
                self.workspace.calculate('alchemy')
                result = self.workspace.structured_results['alchemy']
                self.assertTrue(result['within_budget']); self.assertEqual(result['energy']['remaining'], 8)
                self.assertEqual(result['materials'][0]['remaining'], 2)
                self.workspace.edit('alchemy', {**self.workspace.raw['alchemy'], 'r0.id': identity})
                self.assertEqual(self.workspace.raw['alchemy'][state_key], '1e')
                self.assertEqual(next(row['raw'] for row in self.workspace.alchemy_fields() if row['key'] == state_key), '1e')
                with self.assertRaises(ValueError): self.workspace.calculate('alchemy')

    def test_equipment_summary_prioritizes_pending_conditions_and_comparison(self):
        self.equipment(); self.workspace.raw['equipment'].update(infusion_a='unknown', upgrade_budget='0')
        self.workspace.calculate('equipment'); self.workspace.emit('equipment')
        text = self.workspace.results['equipment']
        self.assertLess(text.index('注魔假设未确认'), text.index('最低基础伤害'))
        self.assertLess(text.index(' B '), text.index('条件与投入明细'))
        state = self.host.commands[-1][1]
        self.assertEqual(state['comparison']['rows'], self.workspace.structured_results['equipment']['rows'])
        self.assertTrue(state['planning']['choices'][0]['upgrade_pending'])

    def test_equipment_choices_exclude_reference_pages_and_all_compute(self):
        choices = self.workspace.equipment_choices()
        self.assertFalse(any('.glyphs.' in identity or '.curses.' in identity or identity.endswith('.ability') for identity, _ in choices))
        for identity, _ in choices:
            with self.subTest(identity=identity):
                self.workspace.raw['equipment'].update(id_a=identity, id_b=identity)
                self.workspace.calculate('equipment')

    def test_restore_progress_uses_local_datetime_class_without_opaque_run_identity(self):
        summary = {'class': 'MAGE', 'level': 3, 'depth': 2, 'hp': 20, 'ht': 30, 'saved': 1791809981.25, 'run_id': 'abc12345'*8}
        text = GameWorkspace.progress_text(summary)
        self.assertIn('法师 Lv.3', text); self.assertIn('2026-', text)
        self.assertRegex(text, r'\d{2}:\d{2}:\d{2} UTC[+-]\d{4}')
        self.assertNotIn(summary['run_id'][:12], text)
        self.assertNotIn(str(summary['saved']), text)

    def test_native_backup_rows_use_labels_saved_time_and_summary_without_changing_selection(self):
        from datetime import datetime, timezone
        from companion.native_host import binding_token
        saved, observed = 1791809981.25, 1791896381.25
        history = {'id': 'a'*64, 'slot': 2, 'label': '进入矿洞前', 'name': '不应使用的名称',
            'saved': saved, 'last_seen': observed, 'class': 'WARRIOR', 'depth': 4, 'hp': 17, 'ht': 40}
        undo = {'id': 'b'*64, 'slot': 2, 'time': observed,
            'before': {'saved': saved, 'class': 'MAGE', 'depth': 3, 'hp': 10, 'ht': 30}}
        status = {'context': {'scope': '测试备份库'}, 'history': [history], 'undo': [undo]}
        before = copy.deepcopy(status); self.session.backup_status = Mock(return_value=status)
        self.workspace.reload('backups'); self.finish_job()
        restore_row, undo_row = self.workspace.rows['backups']
        stamp = datetime.fromtimestamp(saved, timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M:%S UTC%z')
        text = restore_row['text']
        self.assertIn('进入矿洞前', text); self.assertNotIn(history['name'], text)
        self.assertIn('保存时间（存档文件） '+stamp, text)
        self.assertLess(text.index('保存时间'), text.index('最近观察'))
        self.assertIn('战士 · 第 4 层 · 生命 17/40', text)
        self.assertIn(history['id'][:12], text); self.assertNotIn(history['id'], text)
        self.assertIn('保存时间（回档前存档） '+stamp, undo_row['text'])
        self.assertIn('法师 · 第 3 层 · 生命 10/30', undo_row['text'])
        self.assertIn('回档时间', undo_row['text']); self.assertNotIn('最近观察', undo_row['text'])
        self.assertEqual(restore_row['id'], 'restore:'+history['id'])
        self.assertEqual(restore_row['token'], binding_token([status['context'], 'restore', history]))
        self.assertEqual(undo_row['token'], binding_token([status['context'], 'undo', undo]))
        self.assertEqual(status, before)
        self.assertIn('保存时间（存档文件） 未记录', GameWorkspace.backup_row_text('restore', {'id': 'c'*64, 'slot': 1, 'time': observed}))

    def test_ready_restores_settings_values_without_creating_or_saving_a_draft(self):
        from companion.native_manager import NativeManager
        from companion.native_settings import PlaySettings
        ui = NativeManager.__new__(NativeManager)
        ui.manager, ui.session, ui.host, ui.workspace = self.manager, self.session, self.host, self.workspace
        ui.layout = SimpleNamespace(values={'page': 'settings'}, original={'page': 'settings'})
        ui.update, ui.error = Mock(), Mock()
        ui.reported, ui.revision = None, 0
        self.session.register_exit_surface('native', kind='native', label='测试工作区', notify=Mock())
        self.manager.native_ui = ui
        def open_settings(show=True):
            self.assertFalse(show)
            self.manager.play_settings = PlaySettings(self.manager)
        self.manager.open_play_settings = Mock(side_effect=open_settings)
        before = self.session.play_preferences.published()
        ui.dispatch({'action': 'ready'})
        ui.error.assert_not_called(); self.manager.open_play_settings.assert_called_once_with(show=False)
        settings = self.manager.play_settings
        self.assertFalse(settings.has_draft())
        self.assertEqual(settings.vars['enabled'].get(), before['settings']['enabled'])
        self.assertEqual(settings.vars['offset_x'].get(), str(before['settings']['offset_x']))
        self.assertEqual({key: value.get() for key, value in settings.bindings.items()}, before['settings']['bindings'])
        self.assertEqual(self.session.play_preferences.published(), before)
