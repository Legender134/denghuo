"""Short behavioral acceptance for local knowledge and support workflows."""
import copy
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from companion.engine import Catalog, PREFIX
from companion.server import Server
from companion.service import Session
from companion.values_resources import water_drink


class WorkspaceTests(unittest.TestCase):
    def test_connection_receipt_keeps_its_normalized_values_after_a_later_write(self):
        original_refresh = self.session.refresh
        competing = False
        def refresh():
            nonlocal competing
            if not competing:
                competing = True
                self.session.update_settings({'slot': 2})
            original_refresh()
        with patch.object(self.session, 'refresh', side_effect=refresh):
            receipt = self.session.update_settings({'save_root': '  '+str(self.directory)+'  ', 'slot': 1},
                expected_revision=self.session.settings_revision, return_receipt=True)
        self.assertEqual(receipt['settings']['save_root'], str(self.directory.resolve()))
        self.assertEqual(receipt['settings']['slot'], 1)
        self.assertEqual(self.session.settings['slot'], 2)
        self.assertNotEqual(receipt['settings_revision'], self.session.settings_revision)
        with self.assertRaisesRegex(ValueError, '其他位置'):
            self.session.update_settings(receipt['settings'], expected_revision=receipt['settings_revision'])

    def test_backup_receipt_is_captured_before_refresh_changes_connection(self):
        own = {'id': 'a'*64, 'slot': 1, 'label': '提交名称', 'locked': False, 'metadata_revision': 'b'*64}
        context, root = self.session.backup_context, self.session.settings['save_root']
        def later_refresh():
            self.session.backup_context = 'new-connection'
            self.session.settings['save_root'] = '/synthetic/other-root'
        with patch.object(self.session.backups, 'manage', return_value=own), patch.object(self.session, 'refresh', side_effect=later_refresh):
            receipt = self.session.backup_action({'action': 'manage', 'context': context})
        self.assertEqual(receipt, {'ok': True, 'metadata': own, 'context': context, 'save_root': root})

    def test_play_save_and_reload_receipts_never_borrow_a_competing_generation(self):
        from companion.workspace_service import reload_play, update_play
        for operation in ('save', 'reload'):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as directory:
                session = Session(Path(directory) / 'settings.json', self.catalog)
                session.manager_available = True
                def competing_native_write(_):
                    session.play_preferences.update({'anchor': 'bottom_right', 'offset_y': 222},
                        expected_generation=1)
                session.manager_commands = SimpleNamespace(put=competing_native_write)
                receipt = (update_play(session, {'settings': {'offset_x': 777}, 'revision': 0})
                    if operation == 'save' else reload_play(session, {'revision': 0}))
                self.assertEqual(receipt['revision'], 1)
                self.assertEqual(receipt['settings']['anchor'], 'top_left')
                self.assertEqual(receipt['settings']['offset_y'], 100)
                self.assertEqual(session.play_preferences.generation, 2)
                original = session.play_preferences.path.read_bytes()
                session.manager_available = False
                with self.assertRaisesRegex(ValueError, '另一窗口'):
                    update_play(session, {'settings': {**receipt['settings'], 'offset_x': 778},
                        'revision': receipt['revision']})
                self.assertEqual(session.play_preferences.path.read_bytes(), original)

    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='denghuo-workspace-')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.session = Session(self.directory / 'settings.json', self.catalog)
        self.session.settings['save_root'] = str(self.directory / 'synthetic-saves')

    def test_reading_shared_views_does_not_create_personal_library_or_preferences(self):
        view = self.session.workspace_status()
        self.assertTrue(view['available'])
        self.assertGreaterEqual(len(view['common']), 4)
        self.session.play_settings()
        self.assertFalse((self.directory / 'knowledge.json').exists())
        self.assertFalse((self.directory / 'play-mode.json').exists())

    def test_alias_intent_official_and_zero_result_suggestion(self):
        for query in ('血瓶', '治疗药水', '加血', '治疗药剂', '  血瓶  '):
            self.assertEqual(self.catalog.search(query)['entries'][0]['id'], 'items.potions.potionofhealing')
        self.assertEqual(self.catalog.search('力量药水')['entries'][0]['id'], 'items.potions.potionofstrength')
        self.assertEqual(self.catalog.search('治疗药纪')['suggestions'][0]['id'], 'items.potions.potionofhealing')
        self.assertEqual(self.catalog.search('血瓶', '怪物')['entries'], [])
        self.assertEqual(self.catalog.search('!no-match-xyz!')['suggestions'], [])

    def test_three_plan_kinds_survive_new_session_and_drafts_do_not_apply(self):
        store = self.session.knowledge
        healing = 'items.potions.potionofhealing'
        self.session.workspace_action({'action':'favorite', 'entry':healing, 'enabled':True})
        self.session.workspace_action({'action':'remember', 'entry':healing})
        one = store.save('保命治疗', 'numeric', healing, {'hp':3, 'max_hp':30, 'hero_level':5, 'vial':-1},
                         {'mode':'save', 'snapshot_at':1700000010, 'slot':2, 'fields':{'hp':'旧快照基础参数'}})
        two = store.save('两把武器', 'equipment', None,
                         {'id_a':'items.weapon.melee.shortsword', 'id_b':'items.weapon.melee.longsword',
                          'level_a':2, 'level_b':0, 'strength':12},
                         {'fields':{'level_b':'等级未知：+0参考'}})
        three = store.save('延缓伤害局势', 'manual', None,
                           {'hp':3, 'ht':30, 'level':5, 'healing':2, 'buffs':['DeferedDamage', 'Poison']})
        self.session.update_manual({'hp':20, 'ht':30, 'healing':1})
        previous = copy.deepcopy(self.session.snapshot())
        resumed = Session(self.session.config_path, self.catalog)
        resumed.settings['save_root'] = str(self.directory / 'synthetic-saves')
        self.assertEqual(len(resumed.knowledge.status()['plans']), 3)
        self.assertEqual(resumed.workspace_status()['favorite_ids'], [healing])
        self.assertEqual(resumed.workspace_status()['recent'][0]['id'], healing)
        opened = resumed.knowledge.reopen(one['id'])
        self.assertEqual(opened['plan']['params'], one['params'])
        self.assertEqual(opened['plan']['origin']['fields']['hp'], '旧快照基础参数')
        self.assertEqual(resumed.knowledge.reopen(two['id'])['plan']['origin']['fields']['level_b'], '等级未知：+0参考')
        self.assertEqual(resumed.knowledge.reopen(three['id'])['result']['hero']['hp'], 3)
        for key in ('data', 'modified', 'revision', 'settings'):
            self.assertEqual(self.session.snapshot()[key], previous[key])
        self.assertIsNone(resumed.data)
        self.assertEqual(resumed.settings['mode'], 'save')

    def test_record_compare_and_swap_preserves_other_records_and_export_schema(self):
        store = self.session.knowledge
        first = store.save('原名称', 'numeric', 'items.potions.potionofhealing', {'hp':11,'max_hp':40})
        other = Session(self.session.config_path, self.catalog).knowledge
        opened = other.reopen(first['id'])['plan']
        store.favorite('items.waterskin', True)
        updated = store.save('窗口一', first['kind'], first['entry'], {'hp':8,'max_hp':40},
                             record_id=first['id'], expected_record_revision=first['record_revision'])
        self.assertNotEqual(updated['record_revision'], first['record_revision'])
        prior = store.path.read_bytes()
        for expected in (None, opened['record_revision']):
            with self.assertRaisesRegex(ValueError, '另一窗口'):
                other.save('窗口二草稿', opened['kind'], opened['entry'], {'hp':27,'max_hp':40},
                           record_id=opened['id'], expected_record_revision=expected)
            self.assertEqual(store.path.read_bytes(), prior)
        again = store.save('窗口一再次更新', first['kind'], first['entry'], {'hp':9,'max_hp':40},
                           record_id=first['id'], expected_record_revision=updated['record_revision'])
        self.assertEqual(store.status()['plans'][0]['record_revision'], again['record_revision'])
        exported = json.loads(store.export())
        self.assertNotIn('record_revision', exported['plans'][0])
        self.assertEqual(set(exported['plans'][0]), {'id','name','kind','entry','params','rules_version','created','updated','origin','note'})
        self.assertEqual(other.reopen(first['id'])['plan']['name'], '窗口一再次更新')
        copied = other.save('保留窗口二草稿', opened['kind'], opened['entry'], {'hp':27,'max_hp':40})
        self.assertNotEqual(copied['id'], first['id'])
        self.assertEqual(len(store.status()['plans']), 2)

    def test_optional_notes_all_types_legacy_import_and_compare_and_swap(self):
        store=self.session.knowledge
        payloads=[('numeric','items.potions.potionofhealing',{'hp':8,'max_hp':40}),
                  ('equipment',None,{'id_a':'items.weapon.melee.sword','id_b':'items.weapon.melee.longsword'}),
                  ('manual',None,{'hp':8,'ht':40})]
        for kind,entry,params in payloads:
            row=self.session.workspace_action({'action':'save','name':kind,'kind':kind,'entry':entry,'params':params,'note':'首领前核对\n目标抗性尚未确认'})['plan']
            self.assertEqual(store.reopen(row['id'])['plan']['note'],'首领前核对\n目标抗性尚未确认')
            updated=store.save(kind+'2',kind,entry,params,record_id=row['id'],expected_record_revision=row['record_revision'],note='新假设')
            with self.assertRaisesRegex(ValueError,'另一窗口'):
                store.save(kind+'3',kind,entry,params,record_id=row['id'],expected_record_revision=row['record_revision'],note='覆盖')
            self.assertEqual(store.reopen(row['id'])['plan']['note'],'新假设')
            copy=store.save(kind+'副本',kind,entry,params,note=updated['note'])
            self.assertEqual(copy['note'],'新假设')
        exported=store.export();other=Session(self.directory/'other'/'settings.json',self.catalog).knowledge
        other.import_records(exported);self.assertTrue(all(row['note'] for row in other.status()['plans']))
        legacy=json.loads(exported)
        for row in legacy['plans']:row.pop('note')
        old=Session(self.directory/'old'/'settings.json',self.catalog).knowledge
        old.import_records(json.dumps(legacy).encode());opened=old.status()['plans'][0]
        self.assertEqual(old.reopen(opened['id'])['plan']['note'],'')
        modified=old.save(opened['name'],opened['kind'],opened['entry'],opened['params'],record_id=opened['id'],expected_record_revision=opened['record_revision'],note='旧版新增备注')
        self.assertEqual(modified['note'],'旧版新增备注')
        prior=store.path.read_bytes()
        for note in ('a'*1201,'不可保存\x00','不可保存\t',None if False else 7):
            with self.assertRaises(ValueError):store.save('错误','manual',None,{'hp':8,'ht':40},note=note)
            self.assertEqual(store.path.read_bytes(),prior)

    def test_wand_ring_full_investment_save_reopen_export_and_import(self):
        for prefix,a,b in [('items.wands.','wandofblastwave','wandofmagicmissile'),('items.rings.','ringofhaste','ringofaccuracy')]:
            params={'id_a':prefix+a,'id_b':prefix+b,'level_a':1,'level_b':2,'strength':12,'planning':'1','investment_mode':'all','upgrade_budget':3,'strength_budget':0,
                    'level_known_a':'1','curse_a':'0','level_known_b':'0','curse_b':'0'}
            row=self.session.knowledge.save(a,'equipment',None,params,note='同一预算独立试算')
            reopened=self.session.knowledge.reopen(row['id'])
            self.assertEqual(reopened['plan']['params'],row['params'])
            for choice in reopened['result']['planning']['choices']:
                self.assertEqual([r['upgrades'] for r in choice['alternatives']],[0,1,2,3])
                self.assertEqual([r['remaining_upgrades'] for r in choice['alternatives']],[3,2,1,0])
                self.assertTrue(all('unit' in cell and 'condition' in cell for r in choice['alternatives'] for cell in r['metric_rows']))
            self.assertEqual(self.session.knowledge.import_records(self.session.knowledge.export())['plans_added'],0)

    def test_equipment_planning_parameters_survive_save_reopen_and_import(self):
        store = self.session.knowledge
        args = {'id_a':'items.weapon.melee.longsword','id_b':'items.weapon.melee.shortsword',
                'level_a':0,'level_b':-1,'strength':12}
        basic = store.save('默认比较', 'equipment', None, args)
        self.assertFalse(set(basic['params']) & {'planning','upgrade_budget','strength_budget'})
        planned = store.save('三卷一药', 'equipment', None,
                             {**args,'planning':'1','upgrade_budget':3,'strength_budget':1},
                             {'fields':{'upgrade_budget':'手填预算','strength_budget':'旧快照已知可用资源'}})
        opened = store.reopen(planned['id'])
        self.assertEqual(opened['plan']['params'], planned['params'])
        self.assertEqual(opened['result']['planning']['effective_strength'], 13)
        choice = opened['result']['planning']['choices'][0]
        self.assertEqual((choice['planned_level'], choice['spent_upgrades'], choice['remaining_strength_deficit']), (3,3,1))
        self.assertFalse(choice['within_budget'])
        self.assertEqual(store.import_records(store.export())['plans_added'], 0)
        self.assertTrue(store.status()['available'])
        prior = store.path.read_bytes()
        for params in ({'upgrade_budget':101}, {'upgrade_budget':-1}, {'strength_budget':100}, {'strength_budget':1.5}):
            with self.assertRaises(ValueError):
                store.save('错误预算', 'equipment', None,
                           {**args,'planning':'1','upgrade_budget':3,'strength_budget':1,**params})
            self.assertEqual(store.path.read_bytes(), prior)
        with self.assertRaises(ValueError):
            store.save('未启用预算', 'equipment', None, {**args,'upgrade_budget':3})
        with self.assertRaises(ValueError):
            store.save('不使用预算的来源', 'equipment', None, args, {'fields':{'upgrade_budget':'手填'}})
        self.assertEqual(store.path.read_bytes(), prior)

    def test_invalid_save_and_import_do_not_replace_prior_bytes(self):
        store = self.session.knowledge
        store.save('治疗', 'numeric', 'items.potions.potionofhealing', {'hp':3, 'max_hp':30})
        prior = store.path.read_bytes()
        for params in ({'hp':True}, {'hp':float('nan')}, {'hp':31, 'max_hp':30}, {'level':1}):
            with self.assertRaises(ValueError):
                store.save('错误', 'numeric', 'items.potions.potionofhealing', params)
            self.assertEqual(store.path.read_bytes(), prior)
        malformed = json.loads(prior)
        malformed['plans'][0]['origin']['fields'] = {'arbitrary':'不适用'}
        with self.assertRaises(ValueError):
            store.import_records(json.dumps(malformed).encode('utf-8'))
        self.assertEqual(store.path.read_bytes(), prior)

    def test_corrupt_library_repair_preserves_exact_original_and_rejects_stale_preview(self):
        store = self.session.knowledge
        store.path.write_bytes(b'{corrupt one')
        preview = store.repair_preview()
        store.path.write_bytes(b'{corrupt two')
        with self.assertRaises(ValueError):
            store.repair(preview['expected'], True)
        self.assertEqual(store.path.read_bytes(), b'{corrupt two')
        result = store.repair(store.repair_preview()['expected'], True)
        self.assertEqual((self.directory / result['preserved_file']).read_bytes(), b'{corrupt two')
        self.assertTrue(store.status()['available'])

    def test_waterskin_known_volume_and_java_float_boundaries(self):
        unknown = self.catalog.item({'__className':PREFIX+'items.Waterskin'}, {})
        self.assertIsNone(unknown['volume'])
        self.assertIn('露珠量未知', unknown['details'])
        self.assertEqual(water_drink(3, 30, 20)['consumed'], 18)
        gradual = water_drink(3, 30, 20, vial=3)
        self.assertEqual((gradual['consumed'], gradual['first_heal'], gradual['actual_heal']), (12, 3, 27))
        self.assertEqual(water_drink(29, 30, 1, vial=3)['actual_heal'], 1)
        split = water_drink(15, 30, 20, shielding=1, vial=3)
        self.assertEqual((split['consumed'], split['actual_heal'], split['shield']), (11, 15, 6))
        no_shield_branch = water_drink(3, 30, 20, shielding=1, vial=3)
        self.assertEqual((no_shield_branch['actual_heal'], no_shield_branch['shield']), (27, 0))
        detail = self.session.values.detail('items.waterskin', {'hp':3, 'max_hp':30, 'dew_volume':20, 'vial':3})
        self.assertEqual({row['key'] for row in detail['inputs']}, {'hp','max_hp','dew_volume','shielding_dew','current_shield','vial'})
        self.assertTrue(all(self.catalog.data['commit'] in link['url'] for link in detail['provenance']['links']))
        self.assertTrue(any('Waterskin.java' in link['url'] for link in detail['provenance']['links']))

    def test_risk_reference_and_resource_boundaries(self):
        self.session.update_manual({'hp':3, 'ht':30, 'level':5, 'healing':2, 'buffs':['Burning']})
        decisions = self.session.decisions()
        healing = next(row for row in decisions['options'] if row['entry']=='items.potions.potionofhealing')
        self.assertTrue(healing['values'])
        burning = next(row for row in decisions['risks'] if row['id']=='burning')
        self.assertEqual(burning['references'][0]['entry'], 'actors.buffs.burning')
        self.session.data['tips'].append({'id':'strength_potion', 'title':'保留力量成长'})
        strength = next(row for row in self.session.decisions()['risks'] if row['id']=='strength_potion')
        self.assertEqual(strength['references'][0]['entry'], 'items.potions.potionofstrength')
        for changes in ({'buffs':['Paralysis']}, {'challenges':4}, {'hp':0}):
            self.session.update_manual({'hp':3, 'ht':30, 'level':5, 'healing':2, **changes})
            options = self.session.decisions()['options']
            for option in options:
                if option['entry']=='items.potions.potionofhealing':
                    self.assertEqual(option['values'], [])
        self.session.update_manual({'hp':3, 'ht':30, 'level':5, 'healing':2, 'buffs':['LostInventory']})
        # Manual healing is explicitly marked as kept; losing the bag does not negate it.
        self.assertTrue(self.session.decisions()['options'][0]['values'])
        self.session.data['items'][0]['available'] = False
        self.assertEqual(self.session.decisions()['options'], [])
        self.session.data['items'][0]['available'] = True
        self.session.data['items'][0]['known'] = False
        self.assertEqual(self.session.decisions()['options'], [])

    def test_public_shield_context_has_visible_origin_and_unknown_is_not_zero(self):
        self.session.update_manual({'hp':8,'ht':40,'healing':1})
        self.session.data['buffs'] = [{'kind':'Barrier','name':'屏障','current_shield':7}]
        current = self.session.workspace_status()['current']
        barrier = next(row for row in current if row['id']=='actors.buffs.barrier')
        self.assertEqual(barrier['lookup_context']['params']['current_shield'], 7)
        self.assertIn('公开当前护盾已带入', barrier['lookup_context']['conditions'])
        self.session.data['buffs'][0].pop('current_shield')
        unknown = next(row for row in self.session.workspace_status()['current'] if row['id']=='actors.buffs.barrier')
        self.assertNotIn('current_shield', unknown['lookup_context']['params'])
        self.assertIn('剩余强度', unknown['lookup_context']['conditions'])

    def test_play_generation_conflict_external_changes_reload_and_queue(self):
        session = self.session
        session.manager_available = True
        original = session.play_settings()
        saved = session.update_play_settings({'settings':{'offset_y':120}, 'revision':original['revision']})
        self.assertEqual(saved['revision'], original['revision']+1)
        self.assertEqual(session.manager_commands.get_nowait(), ('play_settings_changed', saved['revision']))
        prior = session.play_preferences.path.read_bytes()
        with self.assertRaises(ValueError):
            session.update_play_settings({'settings':{'offset_y':999}, 'revision':original['revision']})
        self.assertEqual(session.play_preferences.path.read_bytes(), prior)
        external = json.loads(prior)
        external['offset_y'] = 140
        external_raw = json.dumps(external).encode('utf-8')
        session.play_preferences.path.write_bytes(external_raw)
        with self.assertRaises(ValueError):
            session.update_play_settings({'settings':{'offset_y':150}, 'revision':saved['revision']})
        self.assertEqual(session.play_preferences.path.read_bytes(), external_raw)
        from companion.workspace_service import reload_play
        reread = reload_play(session, {'revision':saved['revision']})
        self.assertEqual(reread['settings']['offset_y'], 140)
        session.update_play_settings({'settings':{'offset_y':160}, 'revision':reread['revision']})

    def test_help_diagnostic_allowlist_and_local_location_failure(self):
        session = self.session
        session.error = 'D:\\private-person\\secret-save token-secret'
        session.config_error = 'private configuration error'
        help_view = session.help_status()
        self.assertEqual(help_view['reading_state'], 'configuration-error')
        self.assertEqual(help_view['next_steps'][0]['page'], 'settings')
        for private in ('private-person','secret-save','token-secret',str(self.directory),'params','hero'):
            self.assertNotIn(private, help_view['diagnostic_text'])
        self.assertGreaterEqual(len(help_view['faq']), 10)
        self.assertEqual(help_view['shortcut_state'], 'defaults-unconfirmed')
        with self.assertRaises(ValueError):
            session.support_action({'action':'open-log'})

    def test_real_http_saved_plan_play_conflicts_import_redaction_and_guards(self):
        server = Server(self.session)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def request(path, payload=None, *, token=True):
            headers = {}
            raw = None
            if payload is not None:
                raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode('utf-8')
                headers = {'Content-Type':'application/json','Origin':server.origin}
                if token:headers['X-Companion-Token'] = server.token
            with urlopen(Request(server.origin+path, data=raw, headers=headers), timeout=5) as response:
                return response.status, json.loads(response.read())
        try:
            self.assertTrue(request('/api/workspace')[1]['available'])
            with self.assertRaises(HTTPError) as missing_token:
                request('/api/workspace', {'action':'favorite','entry':'items.waterskin','enabled':True}, token=False)
            self.assertEqual(missing_token.exception.code, 403)
            plan = request('/api/workspace', {'action':'save', 'name':'露珠方案','kind':'numeric','entry':'items.waterskin',
                            'params':{'hp':3,'max_hp':30,'dew_volume':20,'vial':3}})[1]['plan']
            self.assertEqual(request('/api/workspace/plan?id='+plan['id'])[1]['plan']['params'], plan['params'])
            exported = request('/api/workspace/export')[1]
            self.assertTrue(request('/api/workspace/import', json.dumps(exported).encode('utf-8'))[1]['ok'])
            play = request('/api/play-settings')[1]
            saved = request('/api/play-settings', {'settings':{'alerts':False},'revision':play['revision']})[1]
            with self.assertRaises(HTTPError) as conflict:
                request('/api/play-settings', {'settings':{'alerts':True},'revision':play['revision']})
            self.assertEqual(conflict.exception.code, 400)
            self.assertFalse(request('/api/play-settings')[1]['settings']['alerts'])
            self.assertGreater(request('/api/play-settings/reload', {'revision':saved['revision']})[1]['revision'], saved['revision'])
            diagnostic = request('/api/help/export')[1]
            self.assertNotIn(str(self.directory), json.dumps(diagnostic))
            with self.assertRaises(HTTPError) as bad:
                request('/api/workspace', [])
            self.assertEqual(bad.exception.code, 400)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())


if __name__ == '__main__':
    unittest.main()
