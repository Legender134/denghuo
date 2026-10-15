"""Real numeric/workspace services with a headless transport, no user data or GUI."""
import copy
import sys
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from companion.native_workspace import NumericLookup
from companion.native_settings import PlaySettings
from companion.native_host import binding_token
from companion.native_manager import NativeManager, overview_insights, pinned_reference_state
from companion.engine import PREFIX, analyze
from companion.service import Session


class Root:
    def __init__(self):
        self.jobs = {}
    def after(self, _, callback):
        key = len(self.jobs)+1
        self.jobs[key] = callback
        return key
    def after_cancel(self, key):
        self.jobs.pop(key, None)


class Host:
    def __init__(self):
        self.commands, self.revision = [], 0
        self.closed, self.visibility = False, {}
    def command(self, action, **payload):
        self.commands.append((action, copy.deepcopy(payload)))
    def is_foreground(self, *_):
        return False


class Worker:
    def __init__(self):
        self.ticket, self.args = 0, None
    def request(self, kind, *args):
        self.ticket += 1
        self.args = kind, args
        return self.ticket


class ControllerFixture(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix='lamp-native-controller-'))
        self.session = Session(self.directory/'settings.json')
        self.session.update_settings({'save_root': str(self.directory), 'always_on_top': False})
        self.session.update_manual({'hp': 4, 'ht': 30, 'level': 5})
        self.host, self.worker = Host(), Worker()
        self.manager = SimpleNamespace(session=self.session, root=Root(), play=None, play_settings=None,
            play_apply_error='', hotkeys=None, native_ui=SimpleNamespace(host=self.host, report_drafts=Mock()))
        self.owner = SimpleNamespace(manager=self.manager, worker=self.worker, native=Mock(), pinned=None,
            peek_key=None, preferences=self.session.play_preferences, state=self.session.play_preferences.values)
        self.manager.play = self.owner
        self.owner.save = lambda patch, expected_generation=None: self.session.play_preferences.update(patch, expected_generation=expected_generation)
        self.manager.apply_play_settings = Mock()
        self.lookup = self.owner.lookup = NumericLookup(self.owner)

    def open(self, identity):
        row = next(row for row in self.session.catalog.entries if row['id'] == identity)
        self.lookup.select_row(row)
        self.finish()

    def finish(self):
        kind, args = self.worker.args
        self.lookup.render(self.session.values.detail(*args))


class CompactOverviewTests(ControllerFixture):
    def game(self):
        from companion.engine import PREFIX
        return {'version': self.session.catalog.data['version_code'], 'challenges': 0, 'depth': 2,
                'PotionOfHealing_known': True,
                'hero': {'class': 'WARRIOR', 'lvl': 5, 'HP': 20, 'HT': 100, 'STR': 10,
                         'buffs': [], 'inventory': [{'__className': PREFIX+'items.potions.PotionOfHealing', 'quantity': 2}]}}

    def render(self, game, *, stale=False, error=''):
        from companion.engine import analyze
        snap = self.session.snapshot()
        snap.update(data=analyze(game, self.session.catalog), active_slot=1, stale=stale, error=error)
        snap['settings']['mode'] = 'save'
        ui = NativeManager.__new__(NativeManager)
        ui.manager, ui.session, ui.host = self.manager, self.session, self.host
        ui.process_exit, ui.report_drafts = Mock(), Mock()
        ui.exit_state, ui.signature = None, None
        ui.update(snap)
        return next(data for action, data in reversed(self.host.commands) if action == 'manager_state'), ui

    def test_default_surfaces_conditional_resource_math_not_repeated_health(self):
        payload, ui = self.render(self.game())
        row = next(row for row in payload['insights'] if row['id'].startswith('resource-'))
        self.assertIn('首次 +24 HP', row['summary'])
        self.assertIn('单瓶', row['summary'])
        self.assertIn('库存 2', row['title'])
        self.assertIn('最终最多 +80 HP', row['summary'])
        self.assertIn('不再受伤', row['assumption'])
        self.assertNotIn('20 / 100', row['summary'])
        self.assertEqual(payload['insights'][0]['id'], 'critical_hp')
        self.assertIn('逐回合', payload['insights'][0]['summary'])
        index = row['actions'][0]['index']
        self.assertEqual(payload['reference_tokens'][index], binding_token(ui.references[index]))
        self.assertEqual(ui.references[index][0]['params']['hp'], 20)

    def test_source_warning_and_startup_notices_are_discoverable_and_clear_without_changing_drafts(self):
        from companion.game_workspace import GameWorkspace
        workspace=GameWorkspace(SimpleNamespace(session=self.session,host=self.host,report_drafts=Mock()))
        workspace.raw['equipment']['level_a']='1e'; workspace.dirty.add('equipment')
        drafts=workspace.drafts()
        payload,ui=self.render(self.game())
        ui.workspace=workspace
        self.assertFalse(payload['source_warning']); self.assertNotIn('有提示',payload['source_brief'])
        for warning,notice in [('存档版本码 913 与参考版本不同',''),('当前楼层地图尚未保存',''),
                               ('','上次结束时的最后一次备份未完成。'),
                               ('','无法打开默认浏览器；请访问 http://127.0.0.1:12345/')]:
            with self.subTest(warning=warning,notice=notice):
                snap=self.session.snapshot();snap.update(warning=warning,configuration_notice=notice)
                ui.update(snap)
                payload=next(value for action,value in reversed(self.host.commands) if action=='manager_state')
                self.assertTrue(payload['source_warning']);self.assertIn('有提示',payload['source_brief'])
                self.assertIn(warning or notice,payload['snapshot_notes'])
                self.assertEqual(workspace.drafts(),drafts)
        snap.update(warning='',configuration_notice='');ui.update(snap)
        payload=next(value for action,value in reversed(self.host.commands) if action=='manager_state')
        self.assertFalse(payload['source_warning']);self.assertNotIn('有提示',payload['source_brief'])
        self.assertNotIn('最后一次备份',payload['snapshot_notes'])
        self.assertEqual(workspace.drafts(),drafts)

    def test_food_escape_and_strength_are_visible_only_with_supported_current_conditions(self):
        game = self.game()
        game['hero']['inventory'] = [
            {'__className': PREFIX+'items.food.Food', 'quantity': 2},
            {'__className': PREFIX+'items.potions.PotionOfInvisibility', 'quantity': 1}]
        game['PotionOfInvisibility_known'] = True
        game['hero']['buffs'] = [{'__className': PREFIX+'actors.buffs.Hunger', 'level': 320}]
        payload, _ = self.render(game)
        primary = {row['id']: row for row in payload['insights']}
        food = primary['resource-items.food.food']
        self.assertIn('每份参考饱食 +300', food['summary'])
        self.assertIn('3 回合', food['summary'])
        self.assertIn('非即时回血', food['assumption'])
        self.assertIn('库存 2', food['title'])
        self.assertIn('多数攻击和施法', primary['resource-items.potions.potionofinvisibility']['assumption'])
        game['PotionOfInvisibility_known'] = False
        game['hero']['HP'] = 35
        payload, _ = self.render(game)
        self.assertNotIn('resource-items.potions.potionofinvisibility', {row['id'] for row in payload['insights']+payload['secondary_advice']})
        self.assertIn('未饥饿时再休息', next(row for row in payload['insights'] if row['id']=='low_hp')['summary'])
        game['hero']['buffs'] = []
        payload, _ = self.render(game)
        self.assertIn('饱食未知', next(row for row in payload['insights'] if row['id']=='low_hp')['summary'])
        game['hero']['HP'] = 0
        payload, _ = self.render(game)
        self.assertFalse(any(row['id'].startswith('resource-') for row in payload['insights']))

    def test_food_detail_keeps_captured_modifiers_and_does_not_save_them_as_generic_parameters(self):
        for challenge, cursed, expected in ((0, False, '300'), (1, False, '100'), (0, True, '201'), (1, True, '67')):
            with self.subTest(challenge=challenge, cursed=cursed):
                game = self.game()
                game['challenges'] = challenge
                game['hero']['inventory'] = [{'__className': PREFIX+'items.food.Food', 'quantity': 2}]
                game['hero']['buffs'] = [{'__className': PREFIX+'actors.buffs.Hunger', 'level': 350}]
                if cursed:
                    game['hero']['artifact'] = {'__className': PREFIX+'items.artifacts.HornOfPlenty',
                        'cursedKnown': True, 'cursed': True, 'levelKnown': True, 'level': 0}
                _, ui = self.render(game)
                row, source, note = next(ref for ref in ui.references if ref[0]['entry'] == 'items.food.food' and 'quantity' in ref[0])
                self.lookup.open_reference(row, source, note)
                self.finish()
                data = self.host.commands[-1][1]
                self.assertEqual(data['primary_values'][0]['value'], expected)
                self.assertEqual(data['primary_values'][1]['value'], '3')
                self.assertEqual('饥饿游戏' in data['primary_note'], bool(challenge))
                self.assertEqual('已知诅咒丰饶之角' in data['primary_note'], cursed)
                self.assertIn('非即时回血', data['primary_note'])
                original = next(section for section in data['numeric_sections'] if section['title'] == '进食数值')
                self.assertEqual(original['values'][0]['value'], '300')
                self.assertFalse(data['can_save'])
                self.assertFalse(self.lookup.save_plan('捕获食物'))
                self.assertIn('参考', data['origin_brief'])
                self.open('items.food.food')
                self.assertEqual(self.host.commands[-1][1]['primary_values'][0]['value'], '300')
                self.assertNotIn('food_reference', self.lookup.context or {})
        game['hero']['artifact']['cursedKnown'] = False
        _, ui = self.render(game)
        row = next(ref[0] for ref in ui.references if ref[0]['entry'] == 'items.food.food' and 'quantity' in ref[0])
        self.assertIn('诅咒状态未确认', row['calculation_missing'])
        self.assertNotIn('food_reference', row)

    def test_confirmed_strength_deficit_is_primary_but_unknowns_do_not_claim_overweight(self):
        tip = {'id':'strength_主武器','title':'原提示','body':'完整条件','severity':'warning'}
        data = {'items':[{'name':'长剑 +2','location':'主武器','available':True,'level_known':True,'strength_requirement':15}],
                'character_scene':{'strength':{'usable':True,'effective':14}}}
        primary, _ = overview_insights(data, [tip], [])
        self.assertIn('力量差 1', primary[0]['title'])
        self.assertIn('命中与攻速', primary[0]['summary'])
        for field in ('level', 'strength'):
            unknown = copy.deepcopy(data)
            if field == 'level': unknown['items'][0]['level_known'] = False
            else: unknown['character_scene']['strength']['usable'] = False
            primary, _ = overview_insights(unknown, [tip], [])
            self.assertNotIn('力量差', primary[0]['title'])
            self.assertIn('不能断定超重', primary[0]['summary'])

    def test_existing_healing_reports_marginal_benefit_with_assumption(self):
        from companion.engine import PREFIX
        game = self.game()
        game['hero']['buffs'] = [{'__className': PREFIX+'actors.buffs.Healing', 'left': 80,
                                 'percent': 0, 'flat': 1, 'vial_level': -1}]
        payload, _ = self.render(game)
        row = next(row for row in payload['insights'] if row['id'].startswith('resource-'))
        self.assertEqual(row['summary'], '再喝一瓶 · 首次恢复 1 → 25 HP · 最终额外恢复 0 HP')
        self.assertIn('不再受伤', row['assumption'])
        self.assertIn('不预测敌方伤害', row['body'])

    def test_water_summary_distinguishes_immediate_and_vial_recovery(self):
        game = self.game()
        game['hero']['inventory'] = [{'__className': PREFIX+'items.Waterskin', 'volume': 20}]
        payload, _ = self.render(game)
        row = next(row for row in payload['insights'] if row['id']=='resource-items.waterskin')
        self.assertEqual(row['summary'], '本次饮用 · 即时恢复 +80 HP · 消耗 16 滴，剩 4 滴')
        self.assertNotIn('逐回合', row['assumption'])
        game['hero']['inventory'].append({'__className': PREFIX+'items.trinkets.VialOfBlood',
                                         'level': 0, 'levelKnown': True})
        payload, _ = self.render(game)
        row = next(row for row in payload['insights'] if row['id']=='resource-items.waterskin')
        self.assertIn('首次 +19 HP', row['summary'])
        self.assertIn('最终最多 +80 HP', row['summary'])
        self.assertIn('消耗 15 滴，剩 5 滴', row['summary'])
        self.assertIn('逐回合', row['assumption'])

    def test_water_cost_and_remainder_are_visible_in_overview_and_compact_reference(self):
        game = self.game()
        game['hero'].update(HP=32, HT=90)
        for volume, cost, remaining in ((14, 13, 1), (20, 13, 7), (0, 0, 0)):
            with self.subTest(volume=volume):
                game['hero']['inventory'] = [{'__className': PREFIX+'items.Waterskin', 'volume': volume}]
                payload, _ = self.render(game)
                row = next(row for row in payload['insights'] if row['id']=='resource-items.waterskin')
                result = self.session.values.detail('items.waterskin', {'hp':32,'max_hp':90,'dew_volume':volume,'vial':-1,'shielding_dew':0,'current_shield':0})
                if volume:
                    text = f'消耗 {cost} 滴，剩 {remaining} 滴'
                    self.assertIn(text, row['summary'])
                    self.assertIn(text, result['blocks'][0]['summary_note'])
                else:
                    self.assertEqual(row['summary'], '水袋已空')
                    self.assertEqual(row['assumption'], '')
                    self.assertIn('无法饮用', result['blocks'][0]['summary_note'])

    def test_scroll_reading_limits_do_not_block_other_escape_resources(self):
        game = self.game()
        game.update(ScrollOfTeleportation_known=True, PotionOfInvisibility_known=True)
        game['hero']['inventory'] += [
            {'__className': PREFIX+'items.scrolls.ScrollOfTeleportation'},
            {'__className': PREFIX+'items.potions.PotionOfInvisibility'},
            {'__className': PREFIX+'items.stones.StoneOfBlink'},
            {'__className': PREFIX+'items.Waterskin','volume':14},
        ]
        for kind, label in (('Blindness','失明'), ('MagicImmune','魔法免疫'), (None,None)):
            with self.subTest(kind=kind):
                game['hero']['buffs'] = [{'__className':PREFIX+'actors.buffs.'+kind}] if kind else []
                payload, ui = self.render(game)
                options = {ref[0]['entry']:ref[0] for ref in ui.references if 'quantity' in ref[0]}
                scroll = next(row for row in payload['insights'] if row['id']=='resource-items.scrolls.scrollofteleportation')
                if kind:
                    self.assertIn(label+'期间无法阅读卷轴', scroll['summary'])
                    self.assertNotIn('本层另一处', scroll['summary'])
                    self.assertEqual(scroll['assumption'], '')
                else:
                    self.assertIn('本层另一处', scroll['summary'])
                    self.assertEqual(options['items.scrolls.scrollofteleportation']['restriction'], '')
                for identity in ('items.potions.potionofhealing','items.potions.potionofinvisibility','items.stones.stoneofblink','items.waterskin'):
                    self.assertEqual(options[identity]['restriction'], '')

    def test_water_answer_keeps_amount_and_origin_visible_with_editor_collapsed(self):
        from companion.decisions import context_actions
        self.open('items.waterskin')
        self.assertIn('露珠 20 滴（示例', self.host.commands[-1][1]['primary_note'])
        for volume, healing in ((2, '10'), (20, '80')):
            game = self.game()
            game['hero']['inventory'] = [{'__className': PREFIX+'items.Waterskin', 'volume': volume}]
            snap = self.session.snapshot()
            snap.update(data=analyze(game, self.session.catalog), active_slot=1)
            snap['settings']['mode'] = 'save'
            reference = next(row for row in context_actions(self.session, snap)['options'] if row['entry']=='items.waterskin')
            self.lookup.open_reference(reference); self.finish()
            state = self.host.commands[-1][1]
            self.assertIn(f'露珠 {volume} 滴（快照', state['primary_note'])
            self.assertEqual(state['primary_values'][0]['value'], healing)

    def test_current_boss_handoff_and_explicit_latest_import_confirmed_challenge_only(self):
        from companion.decisions import context_actions
        game = self.game(); game.update(depth=14, challenges=256)
        snap = self.session.snapshot()
        snap.update(data=analyze(game, self.session.catalog), active_slot=1)
        snap['settings']['mode'] = 'save'
        self.session.snapshot = Mock(return_value=snap)
        reference = next(row for row in context_actions(self.session, snap)['risks'] if row['id']=='boss_next')['references'][0]
        self.assertEqual(reference['params']['stronger_bosses'], 1)
        self.lookup.open_reference(reference); self.finish()
        self.assertEqual(self.lookup.calculated['stronger_bosses'], 1)
        state = self.host.commands[-1][1]
        self.assertIn('绝命头目（快照', state['primary_note'])
        self.assertTrue(any('3座' in note for note in state['reading_notes']))
        self.open('actors.mobs.dm300')
        self.assertEqual(self.lookup.calculated['stronger_bosses'], 0, 'Generic encyclopedia remains an independent example')
        self.assertTrue(self.lookup.save_plan('普通首领参考'))
        self.lookup.use_latest(); self.finish()
        self.assertEqual(self.lookup.calculated['stronger_bosses'], 1)
        self.lookup.undo_import()
        self.assertEqual(self.lookup.calculated['stronger_bosses'], 0)
        self.assertIsNotNone(self.lookup.saved_plan)
        self.lookup.use_latest(); self.finish()
        snap['data'].update(challenges_known=False, challenges_mask=None)
        self.lookup.use_latest(); self.finish()
        self.assertEqual(self.lookup.calculated['stronger_bosses'], 1)
        self.assertIn('最新记录未确认', self.lookup.input_origins['stronger_bosses'])
        self.assertIn('最新记录未确认', self.host.commands[-1][1]['primary_note'])
        snap['data'].update(challenges_known=True, challenges_mask=0)
        self.lookup.use_latest(); self.finish()
        self.assertEqual(self.lookup.calculated['stronger_bosses'], 0)
        self.assertIn('普通首领（快照', self.host.commands[-1][1]['primary_note'])

    def test_unknown_harmful_and_unreadable_conditions_do_not_publish_healing_numbers(self):
        game = self.game(); game.pop('challenges')
        payload, _ = self.render(game)
        row = next(row for row in payload['insights'] if row['id'].startswith('resource-'))
        self.assertEqual(row['summary'], '条件待补全')
        self.assertIn('挑战条件未确认', row['body'])
        game = self.game(); game['challenges'] = 4
        payload, _ = self.render(game)
        row = next(row for row in payload['insights']+payload['secondary_advice'] if row['id'].startswith('resource-'))
        self.assertIn('改为中毒', row['summary'])
        self.assertNotIn('HP', row['summary'])
        payload, _ = self.render(self.game(), error='合成读取错误')
        self.assertEqual(payload['insights'], [])
        self.assertTrue(payload['source_warning'])
        self.assertIn('读取受阻', payload['source_brief'])
        payload, _ = self.render(self.game(), stale=True)
        self.assertTrue(payload['source_warning'])
        self.assertIn('旧快照', payload['source_brief'])

    def test_mechanism_summary_keeps_movement_and_water_conditions(self):
        from companion.engine import PREFIX
        game = self.game()
        game['hero']['buffs'] = [{'__className': PREFIX+'actors.buffs.'+kind} for kind in ('Burning', 'Levitation')]
        payload, _ = self.render(game)
        burning = next(row for row in payload['insights'] if row['id']=='burning')
        self.assertEqual(burning['title'], '漂浮时不能用水灭火')
        game['hero']['buffs'].append({'__className': PREFIX+'actors.buffs.Roots'})
        payload, _ = self.render(game)
        burning = next(row for row in payload['insights'] if row['id']=='burning')
        self.assertEqual(burning['title'], '无法走动，不能立即入水灭火')
        self.assertIn('漂浮', burning['body'])


    def test_critical_lock_without_a_second_tip_is_still_primary_and_roots_do_not_block_items(self):
        tip={'id':'critical_hp','title':'生命值很低','body':'原始行动限制','basis':'原始阈值','actions':[]}
        important,secondary=overview_insights({'buffs':[{'kind':'Paralysis'}]},[tip],[])
        self.assertEqual(important[0]['title'],'麻痹期间不能移动或使用保命物品')
        self.assertEqual(important[0]['body'],tip['body'])
        self.assertEqual(secondary,[])
        resource={'id':'resource-items.waterskin','summary':'保留数值','body':'保留完整条件'}
        important,secondary=overview_insights({'buffs':[{'kind':'Roots'}]},[tip],[resource])
        self.assertEqual({row['id'] for row in important}, {'critical_hp', resource['id']})
        self.assertEqual(next(row for row in important if row['id']==resource['id'])['summary'],resource['summary'])
        self.assertEqual(secondary,[])


    def test_each_action_lock_is_primary_without_repeating_hud_or_resource_restriction(self):
        for kind, name in [('Paralysis', '麻痹'), ('Frost', '冰冻'), ('MagicalSleep', '魔法睡眠'), ('TimeStasis', '时间静止')]:
            with self.subTest(kind=kind):
                game = self.game()
                game['hero']['buffs'] = [{'__className':PREFIX+'actors.buffs.'+kind}]
                payload, ui = self.render(game)
                alert = next(row for row in payload['insights'] if row['id']=='critical_hp')
                self.assertEqual(alert['title'], name+'期间不能移动或使用保命物品')
                self.assertEqual(alert['group'], '行动限制')
                self.assertNotIn('生命值很低', alert['title'])
                self.assertNotIn('paralysis', [row['id'] for row in payload['insights']+payload['secondary_advice']])
                original = analyze(game, self.session.catalog)['tips']
                for tip in original:
                    if tip['id'] in ('critical_hp', 'paralysis'):
                        self.assertIn(tip['body'], alert['body'])
                        self.assertIn(tip['basis'], alert['basis'])
                resource = next(row for row in payload['secondary_advice'] if row['id'].startswith('resource-'))
                self.assertIn('限制主动行动', resource['summary'])
                self.assertEqual(resource['group'], '随身资源')
                self.assertFalse(any(row['id'].startswith('resource-') for row in payload['insights']))
                for action in alert['actions']+resource['actions']:
                    self.assertEqual(payload['reference_tokens'][action['index']], binding_token(ui.references[action['index']]))


    def test_healing_challenge_restriction_is_main_once_and_full_resource_conditions_remain(self):
        game=self.game(); game['challenges']=4
        payload, ui=self.render(game)
        restriction=next(row for row in payload['insights'] if row['id']=='pharmacophobia')
        self.assertEqual(restriction['title'], '治疗药剂会改为中毒')
        self.assertEqual(restriction['group'], '恢复限制')
        resource=next(row for row in payload['secondary_advice'] if row['id']=='resource-items.potions.potionofhealing')
        self.assertIn('改为中毒', resource['body'])
        self.assertNotIn('HP', resource['summary'])
        self.assertEqual(ui.references[resource['actions'][0]['index']][0]['restriction'],resource['summary'])


    def test_routine_groups_are_player_tasks_and_defaults_do_not_emphasize_health(self):
        advice=[{'id':id,'title':id,'body':'完整条件','basis':'原依据','actions':[], 'severity':'info'} for id in
                ('critical_hp','low_hp','hungry','class','unknown','strength_potion','upgrade_scroll','strength_主武器')]
        important, secondary=overview_insights({'buffs':[]},advice,[])
        self.assertEqual({row['id'] for row in important}, {'critical_hp','low_hp','strength_主武器'})
        groups={row['id']:row['group'] for row in important+secondary}
        self.assertEqual(groups['critical_hp'],'恢复准备')
        self.assertEqual(groups['strength_主武器'],'装备准备')
        self.assertEqual(groups['unknown'],'鉴定与未知')
        self.assertEqual(groups['class'],'职业准备')
        self.assertTrue(all(row['body']=='完整条件' and row['basis']=='原依据' for row in secondary))


    def test_each_boss_name_and_action_uses_the_existing_exact_reference(self):
        for depth, identity in [(4,'goo'),(9,'tengu'),(14,'dm300'),(19,'dwarfking'),(24,'yogdzewa')]:
            with self.subTest(depth=depth):
                game=self.game();game['depth']=depth
                payload,ui=self.render(game)
                boss=next(row for row in payload['insights'] if row['id']=='boss_next')
                index=boss['actions'][0]['index']
                bound=ui.references[index]
                self.assertEqual(bound[0]['entry'],'actors.mobs.'+identity)
                self.assertEqual(boss['title'],'下一层：'+bound[0]['name'])
                self.assertEqual(boss['group'],'首领准备')
                self.assertEqual(payload['reference_tokens'][index],binding_token(bound))
                ui.frozen=False;ui.manager.open_reference=Mock();ui.error=Mock()
                ui.dispatch({'action':'reference','index':index,'token':payload['reference_tokens'][index]})
                ui.manager.open_reference.assert_called_once_with(*bound)
                ui.dispatch({'action':'reference','index':index,'token':'stale-token'})
                self.assertEqual(ui.manager.open_reference.call_count,1)
                ui.error.assert_called_once()


    def test_pin_keeps_original_params_and_reports_manual_old_and_unknown_conditions(self):
        snap=self.session.snapshot();snap['settings']['mode']='manual'
        self.owner.pinned=('items.weapon.melee.sword',{'level':0,'strength':10})
        self.owner.pinned_context={'mode':'manual','stamp':NumericLookup.source_stamp(snap),'params':{'level':0,'strength':10},
            'level_unknown':True,'fixed_origins':{'level':'等级未知 · +0示例','strength':'手填','hp':'手动局势'}}
        original=copy.deepcopy((self.owner.pinned,self.owner.pinned_context))
        row=pinned_reference_state(self.owner,snap,self.session.catalog)
        self.assertIn('固定参数，不跟随角色',row['summary'])
        self.assertIn('手填局势来源',row['summary'])
        self.assertIn('含手填参数',row['summary'])
        self.assertIn('含未知条件',row['summary'])
        snap['stale']=True
        self.assertIn('旧手填局势',pinned_reference_state(self.owner,snap,self.session.catalog)['summary'])
        self.assertEqual((self.owner.pinned,self.owner.pinned_context),original)
        self.assertEqual(row['action'],{'action':'view_pin','surface':'lookup','text':'查看固定参考'})
        self.owner.pinned=None
        self.assertIsNone(pinned_reference_state(self.owner,snap,self.session.catalog))


    def test_pin_remains_independent_during_empty_or_failed_read_and_does_not_duplicate_results(self):
        snap=self.session.snapshot();snap['settings']['mode']='save'
        self.owner.pinned=('items.potions.potionofinvisibility',{})
        self.owner.pinned_context={'mode':'example','source_label':'固定参考','fixed_origins':{}}
        row=pinned_reference_state(self.owner,{**snap,'data':None,'error':'合成读取错误'},self.session.catalog)
        self.assertEqual(row['title'],'固定 · 隐形药剂')
        self.assertNotIn('20',row['summary'])
        self.assertNotIn('旧快照',row['summary'])
        payload,ui=self.render(self.game(),error='合成读取错误')
        self.assertEqual(payload['insights'],[])
        self.assertEqual(payload['pinned_reference']['title'],row['title'])
        self.assertTrue(payload['source_warning'])
        self.owner.pinned=('missing.entry',{'level':0});self.owner.pinned_context={}
        missing=pinned_reference_state(self.owner,snap,self.session.catalog)
        self.assertIn('当前资料不可用',missing['summary'])
        self.assertIn('参数来源未确认',missing['summary'])


    def test_view_pin_action_reuses_the_existing_unsaved_draft_guard(self):
        self.open('items.weapon.melee.sword')
        self.lookup.pin()
        pinned=copy.deepcopy(self.owner.pinned)
        self.lookup.variables['level'].set('1e')
        payload,ui=self.render(self.game())
        ui.frozen=False
        ui.dispatch(payload['pinned_reference']['action'])
        self.assertIsNotNone(self.lookup.confirmation)
        self.assertEqual(self.lookup.variables['level'].get(),'1e')
        self.assertEqual(self.owner.pinned,pinned)
        self.assertTrue(any(action=='confirm' and value['surface']=='lookup' for action,value in self.host.commands))



class NumericControllerTests(ControllerFixture):
    def test_upgrade_scroll_primary_tracks_selected_level_and_exclusive_risk_conditions(self):
        self.open('items.scrolls.scrollofupgrade')
        for level, normal, hardened in ((0, '0', '0'), (6, '40', '10'), (10, '100', '100')):
            with self.subTest(level=level):
                self.lookup.variables['level'].set(str(level))
                self.lookup.calculate(); self.finish()
                state = self.host.commands[-1][1]
                primary = state['primary_values']
                self.assertEqual([(row['label'], row['value'], row['unit']) for row in primary],
                    [('普通附魔 / 刻印消失', normal, '%'), ('硬化保护消失', hardened, '%')])
                self.assertIn('未硬化', primary[0]['condition'])
                self.assertIn('已硬化', primary[1]['condition'])
                self.assertIn('本次保留效果', primary[1]['condition'])
                self.assertIn(f'{level:+d} → {level+1:+d}', state['primary_note'])
                self.assertIn('分别判断', state['primary_note'])
                self.assertTrue(any('诅咒' in str(section) for section in state['numeric_sections']))

    def test_latest_import_replaces_pending_calculation_and_completes(self):
        self.open('items.potions.potionofhealing')
        self.lookup.variables['hp'].set('5')
        self.lookup.calculate()
        abandoned = self.lookup.ticket
        self.session.update_manual({'hp': 8, 'ht': 30, 'level': 5})
        self.lookup.use_latest()
        self.assertGreater(self.lookup.ticket, abandoned)
        self.assertEqual(self.lookup.ticket, self.worker.ticket)
        self.assertTrue(self.lookup.calculating)
        self.assertEqual(self.lookup.raw_params()['hp'], '8')
        self.finish()
        self.assertFalse(self.lookup.calculating)
        self.assertEqual(self.lookup.calculated['hp'], 8)
        self.assertTrue(self.host.commands[-1][1]['can_save'])

    def test_fixed_reference_reopens_original_parameters_and_guards_current_draft(self):
        self.open('items.potions.potionofhealing')
        self.lookup.variables['hp'].set('7')
        self.lookup.variables['max_hp'].set('120')
        self.lookup.note.set('固定时的备注')
        self.lookup.calculate(); self.finish(); self.lookup.pin()
        fixed = copy.deepcopy(self.lookup.calculated)
        origins = dict(self.lookup.input_origins)
        self.assertTrue(self.host.commands[-1][1]['has_pin'])
        self.assertIn('固定到随行', self.lookup.operation_receipt)
        self.open('actors.mobs.rat')
        self.session.update_manual({'hp': 1, 'ht': 200, 'level': 8})
        self.lookup.handle({'action': 'view_pin'}); self.finish()
        self.assertEqual(self.lookup.identity, 'items.potions.potionofhealing')
        self.assertEqual(self.lookup.calculated, fixed)
        self.assertEqual(self.lookup.note.get(), '固定时的备注')
        self.assertEqual(self.lookup.input_origins, origins)
        self.lookup.variables['hp'].set('unfinished')
        self.lookup.handle({'action': 'view_pin'})
        self.assertIsNotNone(self.lookup.confirmation)
        self.lookup.handle({'action': 'replace_decision', 'decision': 'cancel'})
        self.assertEqual(self.lookup.variables['hp'].get(), 'unfinished')
        self.lookup.handle({'action': 'view_pin'})
        self.lookup.handle({'action': 'replace_decision', 'decision': 'saved'}); self.finish()
        self.assertEqual(self.lookup.calculated, fixed)
        self.assertTrue(self.session.list_exit_drafts())
        self.lookup.clear_pin()
        self.assertFalse(self.host.commands[-1][1]['has_pin'])
        self.lookup.view_pin(); self.assertIn('尚未固定', self.lookup.operation_receipt)

    def test_handbook_operation_receipts_survive_origin_refresh(self):
        self.open('items.potions.potionofhealing')
        self.lookup.favorite()
        self.assertIn('已收藏', self.host.commands[-1][1]['operation_receipt'])
        action = self.session.workspace_action
        self.session.workspace_action = Mock(side_effect=OSError('资料库只读'))
        self.lookup.favorite()
        self.lookup.refresh_origin(self.session.snapshot()); self.lookup.emit()
        self.assertEqual(self.host.commands[-1][1]['operation_receipt'], '资料库只读')
        self.session.workspace_action = action
        self.lookup.save_plan('本次治疗')
        self.assertIn('已保存「本次治疗」', self.host.commands[-1][1]['operation_receipt'])
        self.lookup.pin()
        self.assertIn('已固定', self.host.commands[-1][1]['operation_receipt'])

    def test_ready_initializes_restored_handbook_without_showing_window(self):
        self.owner.lookup = None
        ui = NativeManager.__new__(NativeManager)
        ui.manager, ui.session, ui.host = self.manager, self.session, self.host
        ui.layout = SimpleNamespace(values={'page': 'lookup', 'collapsed': True}, original=b'layout')
        ui.update, ui.report_drafts = Mock(), Mock()
        self.host.commands.clear()
        ui.dispatch({'action': 'ready'})
        self.assertIsInstance(self.owner.lookup, NumericLookup)
        payload = next(data for action, data in self.host.commands if action == 'lookup_state')
        self.assertTrue(payload['rows'])
        self.assertFalse(any(action == 'show' for action, data in self.host.commands))
        self.assertTrue(self.host.commands[0][1]['layout']['collapsed'])

    def test_restored_and_filtered_plans_only_publish_list_data(self):
        ui = NativeManager.__new__(NativeManager)
        ui.manager, ui.session, ui.host = self.manager, self.session, self.host
        ui.layout = SimpleNamespace(values={'page': 'plans', 'collapsed': True}, original=b'layout')
        ui.update, ui.report_drafts = Mock(), Mock()
        self.host.commands.clear()
        ui.dispatch({'action': 'ready'})
        self.assertEqual([action for action, _ in self.host.commands], ['window_layout', 'plans'])
        self.assertTrue(self.host.commands[0][1]['layout']['collapsed'])
        self.host.commands.clear()
        self.lookup.handle({'action': 'filter_plans', 'query': '没有匹配的方案'})
        self.assertEqual([action for action, _ in self.host.commands], ['plans', 'lookup_state'])
        self.assertEqual(self.host.commands[0][1]['rows'], [])

    def test_first_plan_actions_initialize_without_opening_handbook(self):
        self.open('items.potions.potionofhealing')
        self.lookup.save_plan('本次治疗')
        ui = NativeManager.__new__(NativeManager)
        ui.manager, ui.session, ui.host = self.manager, self.session, self.host
        ui.frozen = False
        ui.update, ui.report_drafts = Mock(), Mock()
        self.manager.open_lookup = Mock(side_effect=AssertionError('List requests must not navigate'))
        for action in ('choose_plan', 'filter_plans'):
            with self.subTest(action=action):
                self.owner.lookup = None
                self.host.commands.clear()
                ui.dispatch({'action': action, 'surface': 'lookup'})
                self.assertIsInstance(self.owner.lookup, NumericLookup)
                plans = next(data for command, data in self.host.commands if command == 'plans')
                self.assertEqual(len(plans['rows']), 1)
                self.assertFalse(any(command == 'show' for command, _ in self.host.commands))
        self.manager.open_lookup.assert_not_called()

    @unittest.skipUnless(sys.platform == 'win32', 'Windows display controller imports Tk')
    def test_snapshot_update_publishes_changed_origin_without_replacing_result(self):
        from companion.play_overlay import PlayDisplay
        self.open('items.potions.potionofhealing')
        fixed = copy.deepcopy((self.lookup.raw_params(), self.lookup.calculated))
        snap = copy.deepcopy(self.session.snapshot())
        play = PlayDisplay.__new__(PlayDisplay)
        play.lookup, play.notices, play.state = self.lookup, Mock(), self.owner.state
        PlayDisplay.update(play, snap)
        for change in ('revision', 'active_slot', 'stale', 'error'):
            updated = copy.deepcopy(snap)
            updated[change] = True if change == 'stale' else '读取失败' if change == 'error' else 999
            self.host.commands.clear()
            PlayDisplay.update(play, updated)
            payload = next(data for action, data in self.host.commands if action == 'lookup_state')
            self.assertIn('旧参考', payload['origin_brief'], change)
            self.assertEqual((self.lookup.raw_params(), self.lookup.calculated), fixed)
            self.host.commands.clear()
            PlayDisplay.update(play, updated)
            self.assertFalse(any(action == 'lookup_state' for action, data in self.host.commands))
            PlayDisplay.update(play, snap)

    def test_collapse_uses_remembered_game_and_preserves_unfinished_numeric_draft(self):
        self.open('items.potions.potionofhealing')
        self.lookup.variables['hp'].set('  unfinished  ')
        draft = copy.deepcopy(self.lookup.draft())
        ui = NativeManager.__new__(NativeManager)
        ui.manager, ui.session, ui.host = self.manager, self.session, self.host
        ui.report_drafts, ui.update = Mock(), Mock()
        self.owner.native.remembered_game.return_value = {'hwnd': 1234, 'pid': 456, 'rect': (0, 0, 900, 700)}
        self.host.commands.clear()
        ui.dispatch({'action': 'collapse', 'game': {'hwnd': 999, 'pid': 888}})
        self.assertEqual(self.host.commands, [('collapse', {'game': {'hwnd': 1234, 'pid': 456}})])
        self.assertEqual(self.lookup.draft(), draft)
        self.owner.native.remembered_game.return_value = None
        ui.dispatch({'action': 'collapse'})
        self.assertEqual(self.host.commands[-1], ('collapse', {'game': {}}))
        self.assertEqual(self.lookup.draft(), draft)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows shortcut controller imports Tk')
    def test_quick_shortcut_collapses_expanded_workspace_and_reopens_handle(self):
        from companion.play_overlay import PlayDisplay
        ui = SimpleNamespace(workspace=object(), host=self.host, companion_collapsed=False,
                             dispatch=Mock(), show=Mock())
        self.manager.native_ui = ui
        play = PlayDisplay.__new__(PlayDisplay)
        play.manager = self.manager
        self.host.visibility['manager'] = True
        PlayDisplay.toggle_peek(play)
        ui.dispatch.assert_called_once_with({'action': 'collapse'})
        ui.show.assert_not_called()
        ui.companion_collapsed = True
        PlayDisplay.toggle_peek(play)
        ui.show.assert_called_once_with()
        self.assertEqual(ui.dispatch.call_count, 1)

    def test_open_numeric_plan_shows_result_only_after_successful_draft_decision(self):
        self.open('items.weapon.melee.spear')
        self.lookup.variables['level'].set('3'); self.lookup.calculate(); self.finish()
        self.assertTrue(self.lookup.save_plan('任意方案名称'))
        plan = copy.deepcopy(self.lookup.saved_plan)
        self.lookup.query.value = '老鼠'
        self.host.commands.clear()
        self.assertTrue(self.lookup.open_plan(plan['id']))
        self.assertIn(('show', {'surface': 'lookup'}), self.host.commands)
        payload = next(data for action, data in self.host.commands if action == 'lookup_state' and data['focus_result'])
        self.assertEqual((payload['entry_id'], payload['entry_name'], payload['query']),
                         ('items.weapon.melee.spear', '长矛', '老鼠'))
        for decision in ('cancel', 'saved', 'discard'):
            with self.subTest(decision=decision):
                self.open('items.potions.potionofhealing')
                self.lookup.variables['hp'].set('  -  ')
                self.host.commands.clear()
                self.assertFalse(self.lookup.open_plan(plan['id']))
                self.assertFalse(any(action == 'show' for action, _ in self.host.commands))
                self.lookup.handle({'action': 'replace_decision', 'decision': decision})
                shows = [data for action, data in self.host.commands if action == 'show']
                if decision == 'cancel':
                    self.assertFalse(shows)
                    self.assertEqual(self.lookup.raw_params()['hp'], '  -  ')
                    self.lookup.handle({'action': 'replace_decision', 'decision': 'saved'})
                    self.assertFalse(self.session.list_exit_drafts())
                    self.assertFalse(any(action == 'show' for action, _ in self.host.commands))
                else:
                    self.assertEqual(shows, [{'surface': 'lookup'}])
                    self.assertEqual(self.lookup.identity, plan['entry'])
                    self.assertEqual(self.lookup.calculated['level'], 3)
                    self.assertTrue(any(data['focus_result'] for action, data in self.host.commands if action == 'lookup_state'))
        raw_copies = self.session.list_exit_drafts()
        self.assertEqual(len(raw_copies), 1)
        self.assertEqual(self.session.load_exit_draft(raw_copies[0]['id'])['draft']['raw_params']['hp'], '  -  ')

    def test_late_confirmation_or_failed_copy_never_opens_plan_or_discards_newer_input(self):
        self.open('items.weapon.melee.spear'); self.lookup.save_plan('保存的参考')
        plan = self.lookup.saved_plan
        self.lookup.variables['level'].set('1e')
        self.lookup.open_plan(plan['id'])
        self.lookup.variables['level'].set('新输入')
        self.host.commands.clear()
        with self.assertRaisesRegex(ValueError, '确认期间草稿已变化'):
            self.lookup.handle({'action': 'replace_decision', 'decision': 'discard'})
        self.assertEqual(self.lookup.raw_params()['level'], '新输入')
        self.assertFalse(any(action == 'show' for action, _ in self.host.commands))
        self.lookup.open_plan(plan['id'])
        self.lookup.save_draft_copy = Mock(side_effect=OSError('copy blocked'))
        with self.assertRaisesRegex(OSError, 'copy blocked'):
            self.lookup.handle({'action': 'replace_decision', 'decision': 'saved'})
        self.assertEqual(self.lookup.raw_params()['level'], '新输入')
        self.assertFalse(any(action == 'show' for action, _ in self.host.commands))

    def test_late_result_does_not_navigate_or_replace_current_entry_name(self):
        self.open('items.weapon.melee.spear')
        old = copy.deepcopy(self.lookup.rendered)
        self.open('items.potions.potionofhealing')
        self.host.commands.clear()
        self.lookup.render(old)
        self.assertFalse(self.host.commands)
        self.lookup.variables['hp'].set('-')
        payload = self.host.commands[-1][1]
        self.assertEqual(payload['entry_name'], '治疗药剂')
        self.assertEqual(payload['numeric_sections'], [])
        self.assertFalse(any(action == 'show' for action, _ in self.host.commands))

    def test_restored_query_replaces_old_rows_without_recalculating_half_input(self):
        self.open('items.weapon.melee.spear')
        self.lookup.variables['level'].set('  1e  ')
        self.lookup.query.value = '焰浪'
        self.lookup.note.set('原始用途')
        draft = self.lookup.draft()
        self.lookup.query.set('治疗'); self.lookup.search(preserve_detail=True)
        old_rows = copy.deepcopy(self.lookup.rows)
        old_token = binding_token(old_rows[0])
        ticket = self.worker.ticket
        self.lookup.restore_draft(draft)
        expected = self.session.catalog.search('焰浪', limit=30)
        self.assertEqual(self.lookup.rows, expected['entries'])
        self.assertEqual(self.lookup.total, expected['total'])
        self.assertEqual(self.lookup.raw_params(), draft['raw_params'])
        self.assertEqual(self.lookup.input_origins, draft['origins'])
        self.assertEqual(self.lookup.context, draft['context'])
        self.assertEqual(self.lookup.note.get(), draft['note'])
        self.assertEqual(self.worker.ticket, ticket)
        self.assertIsNone(self.lookup.calculated)
        self.assertIsNone(self.lookup.rendered)
        self.lookup.handle({'action': 'select', 'index': 0, 'token': old_token})
        self.assertIn('搜索结果已更新', self.lookup.origin.text)
        self.assertEqual(self.lookup.raw_params()['level'], '  1e  ')

    def test_new_note_or_name_cannot_keep_current_draft_saved_feedback(self):
        self.open('items.weapon.melee.spear'); self.lookup.save_plan('已存方案')
        self.assertIn('已保存', self.lookup.origin.text)
        self.lookup.note.set('更新备注')
        self.assertIn('未保存', self.lookup.origin.text)
        self.assertNotIn('已保存', self.lookup.origin.text)
        self.lookup.save_plan('已存方案', update=True)
        self.lookup.handle({'action': 'save_dialog_edit', 'pending_save': {'name': '未完成名称', 'note': '更新备注', 'update': False}})
        self.assertIn('未保存', self.lookup.origin.text)
        self.assertTrue(self.host.commands[-1][1]['dirty'])

    def test_deathmark_visible_health_calculates_saves_and_reopens(self):
        for identity in ('actors.hero.abilities.rogue.deathmark',
                         'actors.hero.abilities.rogue.deathmark$deathmarktracker'):
            for health in ('100', '10000'):
                with self.subTest(identity=identity, health=health):
                    self.open(identity)
                    self.lookup.variables['target_hp'].set(health)
                    ticket = self.worker.ticket
                    self.lookup.calculate()
                    self.assertEqual(self.worker.ticket, ticket + 1)
                    self.finish()
                    self.assertEqual(self.lookup.calculated['target_hp'], int(health))
                    self.assertTrue(self.lookup.save_plan('死亡耐性 ' + health))
                    plan = self.lookup.saved_plan
                    self.lookup.open_plan(plan['id'], False)
                    self.assertEqual(self.lookup.calculated['target_hp'], int(health))
                    self.assertEqual([field['key'] for field in self.lookup.inputs], ['target_hp'])
            self.lookup.variables['target_hp'].set('未填写')
            ticket = self.worker.ticket
            self.lookup.calculate()
            self.assertEqual(self.worker.ticket, ticket)
            self.assertEqual(self.lookup.variables['target_hp'].get(), '未填写')
        self.open('items.weapon.enchantments.grim')
        self.lookup.variables['target_hp'].set('100')
        self.lookup.variables['target_max_hp'].set('40')
        ticket = self.worker.ticket
        self.lookup.calculate()
        self.assertEqual(self.worker.ticket, ticket)
        self.assertIn('当前生命不能超过最大生命', self.lookup.parameter_error)

    def test_actual_signed_bounds_recompute_save_and_reopen(self):
        self.open('items.weapon.melee.sword')
        self.assertEqual(next(field for field in self.lookup.inputs if field['key'] == 'level')['min'], -100)
        self.lookup.variables['level'].set('-1')
        self.lookup.calculate(); self.finish()
        self.assertEqual(self.lookup.calculated['level'], -1)
        self.assertTrue(self.lookup.save_plan('负一级测试'))
        plan = self.lookup.saved_plan
        self.lookup.open_plan(plan['id'], False)
        self.assertEqual(self.lookup.calculated['level'], -1)
        self.lookup.variables['level'].set('-101'); ticket = self.worker.ticket
        self.lookup.calculate()
        self.assertEqual(self.worker.ticket, ticket)
        self.assertIn('-100', self.lookup.parameter_error)

    def test_valid_padded_input_computes_without_losing_original_raw(self):
        self.open('items.weapon.melee.sword')
        self.lookup.variables['level'].set('  -1  ')
        self.lookup.calculate(); self.finish()
        self.assertEqual(self.lookup.calculated['level'], -1)
        self.assertEqual(self.lookup.raw_params()['level'], '  -1  ')
        self.assertFalse(self.lookup.dirty)

    def test_unsigned_entry_and_raw_empty_remain_invalid_and_unpinned(self):
        self.open('items.potions.potionofhealing')
        self.lookup.variables['hp'].set('')
        self.lookup.calculate(); self.lookup.pin()
        self.assertIsNone(self.owner.pinned)
        self.assertTrue(self.lookup.has_draft())
        self.assertIn('请填写全部', self.lookup.parameter_error)

    def test_late_result_cannot_clear_new_draft(self):
        self.open('items.potions.potionofhealing')
        old = copy.deepcopy(self.lookup.rendered)
        self.lookup.variables['hp'].set('1'); self.lookup.calculate()
        self.lookup.variables['hp'].set('2')
        self.assertIsNone(self.lookup.ticket)
        self.lookup.render(old)
        self.assertTrue(self.lookup.dirty)
        self.assertNotIn('治疗池总量', self.lookup.text.text)

    def test_calculation_does_not_remove_unsaved_draft_protection(self):
        self.open('items.potions.potionofhealing')
        self.lookup.variables['max_hp'].set('77'); self.lookup.calculate(); self.finish()
        self.assertFalse(self.lookup.dirty)
        self.assertTrue(self.lookup.has_draft())
        self.lookup.hide(); self.lookup.show()
        self.assertEqual(self.lookup.variables['max_hp'].get(), '77')

    def test_note_cas_conflict_and_copy(self):
        self.open('items.potions.potionofhealing')
        self.lookup.note.set('用于续航\r\n需先解除已有治疗状态')
        self.assertTrue(self.lookup.save_plan('原方案'))
        self.assertFalse(self.lookup.has_draft())
        self.assertEqual(self.lookup.note.get(), '用于续航\n需先解除已有治疗状态')
        self.assertIn('用于续航\n需先解除已有治疗状态', self.lookup.text.text)
        original = copy.deepcopy(self.lookup.saved_plan)
        external = Session(self.directory/'settings.json')
        external.knowledge.save(original['name'], 'numeric', original['entry'], original['params'], original['origin'], original['id'], original['record_revision'], note='外部备注')
        self.lookup.note.set('本地新备注')
        self.assertFalse(self.lookup.save_plan(original['name'], True))
        self.assertIn('另一窗口', self.lookup.plan_error)
        self.assertEqual(self.lookup.note.get(), '本地新备注')
        self.assertTrue(self.lookup.save_plan('备注副本', False))
        self.assertNotEqual(self.lookup.saved_plan['id'], original['id'])
        self.assertEqual(self.lookup.saved_plan['note'], '本地新备注')

    def test_opaque_nonnumeric_plan_is_forwarded_without_mutation(self):
        plan = self.session.knowledge.save('手动', 'manual', None, {'hp': 3, 'ht': 20})
        self.session.panel.request = Mock()
        self.assertTrue(self.lookup.open_plan(plan['id'], False))
        self.session.panel.request.assert_called_once_with('workspace', plan_id=plan['id'])
        self.assertEqual(self.session.snapshot()['data']['hero']['hp'], 4)

    def test_selected_alchemy_plan_is_forwarded_by_exact_identity(self):
        from companion.alchemy import VERSION
        args = {'recipe': 'potion-healing', 'recipe_version': VERSION, 'batches': 1,
                'energy': 4, 'energy_reserve': 0, 'energy_origin': 'manual',
                'resources': [{'id': 'items.potions.potionofhealing', 'quantity': 1,
                               'reserve': 0, 'origin': 'manual'}], 'reference_version': None}
        self.session.knowledge.save('同名炼金', 'alchemy', None, args)
        selected = self.session.knowledge.save('同名炼金', 'alchemy', None, args)
        before = copy.deepcopy(self.session.workspace_status()['plans'])
        self.session.panel.request = Mock()
        self.lookup.handle({'action': 'filter_plans', 'kind': '炼金方案', 'order': '名称'})
        emitted = next(payload['rows'] for action, payload in reversed(self.host.commands) if action == 'plans')
        self.assertEqual({row['id'] for row in emitted}, {row['id'] for row in before})
        self.lookup.handle({'action': 'open_plan', 'id': selected['id']})
        self.session.panel.request.assert_called_once_with('workspace', plan_id=selected['id'])
        self.assertEqual(self.session.workspace_status()['plans'], before)
        self.assertEqual(self.session.snapshot()['data']['hero']['hp'], 4)

    def test_successful_named_save_clears_pending_intent_after_dialog_closes(self):
        self.open('items.weapon.melee.sword')
        pending = {'name': '命名成功', 'note': '第一行\n第二行\n第三行', 'update': False}
        self.lookup.handle({'action': 'save_dialog_edit', 'pending_save': pending})
        self.lookup.handle({'action': 'save_named', **pending})
        self.lookup.handle({'action': 'save_dialog_closed', 'cancelled': False})
        self.assertIsNone(self.lookup.pending_save)
        self.assertEqual(self.lookup.saved_plan['note'], pending['note'])
        self.assertFalse(self.lookup.has_draft())
        self.lookup.handle({'action': 'edit', 'values': self.lookup.raw_params(), 'note': pending['note']})
        self.assertIsNone(self.lookup.pending_save)

    def test_failed_named_save_keeps_the_modal_raw_draft_after_ok(self):
        self.open('items.weapon.melee.sword')
        self.assertTrue(self.lookup.save_plan('原方案'))
        original = copy.deepcopy(self.lookup.saved_plan)
        external = Session(self.directory/'settings.json')
        external.knowledge.save(original['name'], 'numeric', original['entry'], original['params'],
            original['origin'], original['id'], original['record_revision'], note='外部备注')
        pending = {'name': original['name'], 'note': '弹窗内未成功保存的备注', 'update': True}
        self.lookup.handle({'action': 'save_named', **pending})
        self.lookup.handle({'action': 'save_dialog_closed', 'cancelled': False})
        self.assertIn('另一窗口', self.lookup.plan_error)
        self.assertEqual(self.lookup.pending_save, pending)
        self.assertEqual(self.lookup.note.get(), pending['note'])
        self.assertTrue(self.lookup.has_draft())
        self.lookup.save_draft_copy()
        self.assertNotEqual(self.lookup.saved_plan['id'], original['id'])
        self.assertEqual(self.lookup.saved_plan['note'], pending['note'])

    def test_import_undo_restores_raw_origin_note_and_result_once(self):
        self.open('items.potions.potionofhealing')
        self.lookup.variables['hp'].set('bad draft')
        self.lookup.note.set('原备注')
        prior = self.lookup.draft()
        self.lookup.open_reference({'entry': 'items.weapon.melee.sword', 'params': {'level': -1}}, {'mode': 'manual'}, '参考限制')
        self.lookup.handle({'action': 'replace_decision', 'decision': 'discard'})
        self.finish()
        self.lookup.undo_import()
        self.assertEqual(self.lookup.raw_params(), prior['raw_params'])
        self.assertEqual(self.lookup.input_origins, prior['origins'])
        self.assertEqual(self.lookup.note.get(), '原备注')
        self.assertTrue(self.lookup.dirty)
        self.assertIsNone(self.lookup.undo_state)

    def test_invalid_raw_copy_is_recoverable_without_valid_result(self):
        self.open('items.potions.potionofhealing')
        self.lookup.variables['hp'].set('  invalid raw  ')
        self.lookup.save_draft_copy()
        saved = self.session.load_exit_draft(self.session.list_exit_drafts()[0]['id'])
        self.assertEqual(saved['draft_kind'], 'numeric')
        self.assertEqual(saved['draft']['raw_params']['hp'], '  invalid raw  ')
        saved['draft']['calculated'] = {'hp': 30}
        saved['draft']['rendered'] = {'name': 'untrusted derived result'}
        self.lookup.restore_draft(saved['draft'])
        self.assertTrue(self.lookup.dirty)
        self.assertIsNone(self.lookup.calculated)
        self.assertIsNone(self.lookup.rendered)
        self.assertEqual(self.session.snapshot()['data']['hero']['hp'], 4)

    def test_search_refresh_keeps_existing_unsaved_inputs(self):
        self.open('items.potions.potionofhealing')
        self.lookup.variables['max_hp'].set('88')
        self.lookup.query.set(''); self.lookup.search(preserve_detail=True)
        self.assertEqual(self.lookup.raw_params()['max_hp'], '88')
        self.assertTrue(self.lookup.has_draft())

    def test_empty_search_suggestions_require_an_explicit_selection(self):
        for query, identity in [('隐形药水', 'items.potions.potionofinvisibility'),
                                ('治疗药计', 'items.potions.potionofhealing')]:
            with self.subTest(query=query):
                self.lookup.query.set(query); self.lookup.search()
                payload = next(data for action, data in reversed(self.host.commands) if action == 'lookup_state')
                self.assertEqual(payload['rows'], [])
                suggestion = payload['suggestions'][0]
                self.assertTrue(suggestion['text'].startswith(self.session.catalog.entry_index[identity]['name']))
                previous, ticket = self.lookup.identity, self.worker.ticket
                self.lookup.handle({'action': 'first'})
                self.assertEqual((self.lookup.identity, self.worker.ticket), (previous, ticket))
                response = next(data for action, data in reversed(self.host.commands) if action == 'lookup_state')
                self.assertTrue(response['focus_suggestions'])
                self.assertIn('请选择', response['search_error'])
                self.lookup.handle({'action': 'suggestion', 'index': 0, 'token': suggestion['token']})
                self.finish()
                self.assertEqual(self.lookup.identity, identity)

    def test_suggestion_switch_can_cancel_or_preserve_a_half_input_copy(self):
        self.open('items.potions.potionofhealing')
        self.lookup.variables['hp'].set(' 1e '); self.lookup.note.set('未完成的治疗条件')
        self.lookup.query.set('隐形药水'); self.lookup.search()
        payload = next(data for action, data in reversed(self.host.commands) if action == 'lookup_state')
        selection = {'action': 'suggestion', 'index': 0, 'token': payload['suggestions'][0]['token']}
        self.lookup.handle(selection)
        self.assertIsNotNone(self.lookup.confirmation)
        self.assertEqual(self.lookup.identity, 'items.potions.potionofhealing')
        self.lookup.handle({'action': 'replace_decision', 'decision': 'cancel'})
        self.assertEqual(self.lookup.raw_params()['hp'], ' 1e ')
        self.assertEqual(self.lookup.note.get(), '未完成的治疗条件')
        self.lookup.handle(selection)
        self.lookup.handle({'action': 'replace_decision', 'decision': 'saved'})
        self.finish()
        self.assertEqual(self.lookup.identity, 'items.potions.potionofinvisibility')
        saved = self.session.load_exit_draft(self.session.list_exit_drafts()[0]['id'])
        self.assertEqual(saved['draft']['raw_params']['hp'], ' 1e ')
        self.assertEqual(saved['draft']['note'], '未完成的治疗条件')

    def test_pending_new_query_rejects_a_stale_suggestion_without_losing_draft(self):
        self.open('items.potions.potionofhealing')
        self.lookup.variables['hp'].set(' 1e '); self.lookup.note.set('保留输入')
        for next_query in ('治疗药计', '长剑'):
            with self.subTest(next_query=next_query):
                self.lookup.query.set('隐形药水'); self.lookup.search()
                payload = next(data for action, data in reversed(self.host.commands) if action == 'lookup_state')
                old_token = payload['suggestions'][0]['token']
                ticket = self.worker.ticket
                self.lookup.query.set(next_query)
                self.lookup.handle({'action': 'suggestion', 'index': 0, 'token': old_token})
                updated = next(data for action, data in reversed(self.host.commands) if action == 'lookup_state')
                self.assertIn('搜索建议已更新', updated['search_error'])
                self.assertEqual(self.lookup.identity, 'items.potions.potionofhealing')
                self.assertEqual(self.worker.ticket, ticket)
                self.assertEqual(self.lookup.raw_params()['hp'], ' 1e ')
                self.assertEqual(self.lookup.note.get(), '保留输入')

    def test_suggestions_do_not_leak_into_exact_alias_intent_or_common_results(self):
        self.lookup.query.set('隐形药水'); self.lookup.search()
        for query in ('治疗药水', '血瓶', '怎么逃跑', '力量不足', '', '完全没有这种物品'):
            with self.subTest(query=query):
                self.lookup.query.set(query); self.lookup.search()
                payload = next(data for action, data in reversed(self.host.commands) if action == 'lookup_state')
                self.assertEqual(payload['suggestions'], [])
                if query != '完全没有这种物品':
                    self.assertTrue(payload['rows'])
                else:
                    self.assertEqual(payload['rows'], [])
                    self.assertFalse(payload['can_more'])

    def test_unfinished_save_dialog_raw_fields_restore_without_application(self):
        self.open('items.weapon.melee.sword')
        self.lookup.variables['level'].set('  invalid  ')
        pending={'name':'未完成命名','note':'第一行\n第二行','update':False}
        self.lookup.handle({'action':'save_dialog_edit','pending_save':pending})
        self.lookup.save_draft_copy()
        saved=self.session.load_exit_draft(self.session.list_exit_drafts()[0]['id'])
        self.assertEqual(saved['draft']['pending_save'],pending)
        self.assertEqual(saved['draft']['note'],pending['note'])
        self.lookup.restore_draft(saved['draft'])
        self.assertEqual(self.lookup.pending_save,pending)
        self.assertEqual(self.lookup.raw_params()['level'],'  invalid  ')
        self.assertIsNone(self.lookup.calculated)
        self.assertTrue(self.lookup.has_draft())

    def test_cancel_save_dialog_keeps_the_prior_parameter_and_note_draft(self):
        self.open('items.weapon.melee.sword')
        self.lookup.variables['level'].set('7')
        self.lookup.note.set('先前速查备注')
        self.lookup.handle({'action':'save_dialog_edit','pending_save':{'name':'新名称','note':'弹窗新备注','update':False}})
        self.lookup.handle({'action':'save_dialog_closed','cancelled':True})
        self.lookup.handle({'action':'edit','values':self.lookup.raw_params(),'note':'先前速查备注'})
        self.assertIsNone(self.lookup.pending_save)
        self.assertEqual(self.lookup.note.get(),'先前速查备注')
        self.assertEqual(self.lookup.raw_params()['level'],'7')
        self.assertTrue(self.lookup.has_draft())


class SettingsControllerTests(ControllerFixture):
    def test_native_settings_apply_only_follow_and_shortcuts_preserving_legacy_raw_drafts(self):
        self.host.ready = True
        settings = self.manager.play_settings = PlaySettings(self.manager)
        before = copy.deepcopy(self.session.play_preferences.values)
        settings.vars['enabled'].set(False); settings.bindings['quick'].set('')
        settings.vars['offset_x'].set(' 1e '); settings.vars['opacity'].set('unfinished')
        self.assertTrue(settings.save())
        after = self.session.play_preferences.values
        self.assertFalse(after['enabled']); self.assertEqual(after['bindings']['quick'], '')
        for key in ('alerts', 'anchor', 'offset_x', 'offset_y', 'font_scale', 'opacity', 'notice_seconds'):
            self.assertEqual(after[key], before[key])
        self.assertEqual(settings.vars['offset_x'].get(), ' 1e ')
        self.assertEqual(settings.vars['opacity'].get(), 'unfinished')
        self.assertTrue(settings.has_draft())
        self.assertIn('备用提示卡草稿未应用', settings.status.text)
        self.manager.play_apply_error = '跟随配置尚未应用，请重试'
        self.assertTrue(settings.save())
        self.assertEqual(settings.status.text, self.manager.play_apply_error)

    def test_old_native_unlock_action_shows_real_window_without_saving_or_hiding_it(self):
        self.host.ready = True
        self.manager.native_ui.show = Mock(); self.manager.native_ui.queue_io = Mock()
        settings = self.manager.play_settings = PlaySettings(self.manager)
        settings.vars['offset_x'].set(' 1e ')
        before = copy.deepcopy(settings.draft())
        settings.save_async(unlock=True)
        self.manager.native_ui.show.assert_called_once()
        self.manager.native_ui.queue_io.assert_not_called()
        self.assertEqual(settings.draft(), before)
        self.assertIn('标题栏或灯柄', settings.status.text)

    def test_actual_wire_values_become_clean_after_edit_and_revert(self):
        settings = self.manager.play_settings = PlaySettings(self.manager)
        values, bindings = settings.draft_values()
        wire = {key: value if type(value) is bool else str(value) for key, value in values.items()}
        settings.handle({'action': 'settings_edit', 'values': {**wire, 'offset_x': '777'},
            'bindings': bindings, 'draft_revision': 1})
        self.assertTrue(settings.has_draft())
        settings.handle({'action': 'settings_edit', 'values': wire,
            'bindings': bindings, 'draft_revision': 2})
        self.assertFalse(settings.has_draft())
        self.assertIn('没有未保存草稿', settings.status.text)

    @unittest.skipUnless(sys.platform == 'win32', 'PlayDisplay imports native Tk runtime')
    def test_actual_overlay_save_acknowledges_only_its_own_preference_write(self):
        from companion.play_overlay import PlayDisplay
        settings = self.manager.play_settings = PlaySettings(self.manager)
        self.owner.manager = self.manager
        self.owner.save = lambda patch, expected_generation=None: PlayDisplay.save(
            self.owner, patch, expected_generation=expected_generation)
        self.manager.apply_play_settings.side_effect = lambda: self.session.play_preferences.update(
            {'anchor': 'bottom_right', 'offset_y': 222}, expected_generation=1)
        settings.vars['offset_x'].set('777')
        self.assertTrue(settings.save())
        self.assertEqual(settings.revision, 1)
        self.assertEqual(settings.saved_baseline['anchor'], 'top_left')
        self.assertEqual(self.session.play_preferences.generation, 2)
        self.assertFalse(settings.has_draft())
        original = self.session.play_preferences.path.read_bytes()
        settings.vars['offset_x'].set('778')
        self.assertFalse(settings.save())
        self.assertEqual(self.session.play_preferences.path.read_bytes(), original)
        self.assertTrue(settings.has_draft())

    def test_conflict_keeps_all_raw_fields_and_reload_requires_decision(self):
        settings = self.manager.play_settings = PlaySettings(self.manager)
        settings.vars['opacity'].set('invalid raw')
        self.session.play_preferences.update({'font_scale': 1.75}, expected_generation=settings.revision)
        self.assertFalse(settings.save())
        self.assertEqual(settings.vars['opacity'].get(), 'invalid raw')
        settings.reload()
        self.assertEqual(settings.vars['opacity'].get(), 'invalid raw')
        settings.reload(True)
        self.assertEqual(float(settings.vars['font_scale'].get()), 1.75)
        self.assertFalse(settings.has_draft())

    def test_original_settings_draft_copy_never_applies(self):
        settings = self.manager.play_settings = PlaySettings(self.manager)
        settings.vars['opacity'].set('invalid raw')
        settings.bindings['quick'].set('Ctrl+Alt+Q')
        settings.save_draft_copy()
        saved = self.session.load_exit_draft(self.session.list_exit_drafts()[0]['id'])
        self.assertEqual(saved['format'], 2)
        with self.assertRaisesRegex(ValueError, '已有草稿'):
            settings.restore_draft(saved['draft'])
        settings.reload(True)
        settings.restore_draft(saved['draft'])
        self.assertEqual(settings.vars['opacity'].get(), 'invalid raw')
        self.assertNotEqual(self.session.play_preferences.values['opacity'], 'invalid raw')
        self.assertIn('尚未保存', settings.status.text)

    def test_scoped_restore_keeps_new_unedited_values_across_generation_reset(self):
        settings = self.manager.play_settings = PlaySettings(self.manager)
        settings.vars['offset_x'].set('-')
        raw = settings.draft()
        self.assertEqual(raw['changed'], ['offset_x'])
        self.session.play_preferences.update({'anchor': 'bottom_right', 'offset_y': 222,
            'bindings': {'capture': 'Ctrl+Alt+X'}}, expected_generation=0)
        self.session = Session(self.directory/'settings.json')
        self.manager.session = self.session
        self.owner.preferences = self.session.play_preferences
        settings = self.manager.play_settings = PlaySettings(self.manager)
        self.assertEqual(settings.revision, 0)
        original = self.session.play_preferences.path.read_bytes()
        settings.restore_draft(raw)
        self.assertIsNone(settings.recovery_pending)
        self.assertEqual(settings.vars['offset_x'].get(), '-')
        self.assertEqual(settings.vars['anchor'].get(), '右下')
        self.assertEqual(settings.vars['offset_y'].get(), '222')
        self.assertEqual(settings.bindings['capture'].get(), 'Ctrl+Alt+X')
        self.assertEqual(self.session.play_preferences.path.read_bytes(), original)
        self.assertFalse(settings.save())
        self.assertEqual(self.session.play_preferences.path.read_bytes(), original)
        settings.vars['offset_x'].set('777')
        self.assertTrue(settings.save())
        self.assertEqual(self.session.play_preferences.values['anchor'], 'bottom_right')
        self.assertEqual(self.session.play_preferences.values['offset_y'], 222)
        self.assertEqual(self.session.play_preferences.values['bindings']['capture'], 'Ctrl+Alt+X')

    def test_same_field_restore_requires_choice_and_keeps_cas_after_choice(self):
        settings = self.manager.play_settings = PlaySettings(self.manager)
        settings.vars['offset_x'].set('777')
        draft = settings.draft()
        settings.reload(True)
        self.session.play_preferences.update({'offset_x': 222}, expected_generation=settings.revision)
        settings.read_values()
        original = self.session.play_preferences.path.read_bytes()
        settings.restore_draft(draft)
        self.assertTrue(settings.recovery_pending['rows'][0]['conflict'])
        self.assertEqual(settings.vars['offset_x'].get(), '222')
        settings.finish_recovery({'offset_x': 'draft'})
        self.assertEqual(settings.vars['offset_x'].get(), '777')
        self.assertTrue(settings.has_draft())
        self.assertIn('核对后保存', settings.status.text)
        self.assertEqual(self.session.play_preferences.path.read_bytes(), original)
        self.session.play_preferences.update({'offset_x': 333}, expected_generation=settings.revision)
        self.assertFalse(settings.save())
        self.assertEqual(self.session.play_preferences.values['offset_x'], 333)
        self.assertEqual(settings.vars['offset_x'].get(), '777')

    def test_recovery_keep_current_reports_clean_without_writing_or_applying(self):
        settings = self.manager.play_settings = PlaySettings(self.manager)
        settings.vars['offset_x'].set('777')
        draft = settings.draft()
        settings.reload(True)
        self.session.play_preferences.update({'offset_x': 222}, expected_generation=settings.revision)
        settings.read_values()
        original = self.session.play_preferences.path.read_bytes()
        settings.restore_draft(draft)
        settings.finish_recovery({'offset_x': 'current'})
        self.assertEqual(settings.vars['offset_x'].get(), '222')
        self.assertFalse(settings.has_draft())
        self.assertEqual(settings.status.text, '已保留当前保存值，没有待保存修改。')
        self.assertEqual(self.session.play_preferences.path.read_bytes(), original)

    def test_recovery_confirmation_rejects_later_edit_or_saved_generation(self):
        for later in ('edit', 'saved'):
            with self.subTest(later=later):
                settings = self.manager.play_settings = PlaySettings(self.manager)
                values, bindings = settings.draft_values()
                legacy = {'values': {**values, 'offset_x': '777'}, 'bindings': bindings}
                settings.restore_draft(legacy)
                choices = {row['key']: 'draft' for row in settings.recovery_pending['rows']}
                if later == 'edit':
                    settings.vars['offset_x'].set('999')
                else:
                    self.session.play_preferences.update({'offset_x': 333}, expected_generation=settings.revision)
                before = copy.deepcopy(settings.draft_values())
                with self.assertRaisesRegex(ValueError, '又有变化'):
                    settings.finish_recovery(choices)
                self.assertEqual(settings.draft_values(), before)

    def test_legacy_restore_can_cancel_or_select_only_one_field(self):
        settings = self.manager.play_settings = PlaySettings(self.manager)
        values, bindings = settings.draft_values()
        legacy = {'values': {**values, 'offset_x': '777'}, 'bindings': bindings, 'preferences_revision': 0}
        self.session.play_preferences.update({'anchor': 'bottom_right'}, expected_generation=0)
        settings.read_values()
        before = copy.deepcopy(settings.draft_values())
        settings.restore_draft(legacy)
        self.assertTrue(all(row['conflict'] for row in settings.recovery_pending['rows']))
        settings.handle({'action': 'settings_recovery_decision', 'decision': 'cancel'})
        self.assertEqual(settings.draft_values(), before)
        self.assertFalse(settings.has_draft())
        settings.restore_draft(legacy)
        choices = {row['key']: 'current' for row in settings.recovery_pending['rows']}
        choices['offset_x'] = 'draft'
        settings.finish_recovery(choices)
        self.assertEqual(settings.vars['offset_x'].get(), '777')
        self.assertEqual(settings.vars['anchor'].get(), '右下')
        self.assertEqual(settings.draft()['changed'], ['offset_x'])

    def test_invalid_scope_or_future_format_keeps_current_form(self):
        settings = self.manager.play_settings = PlaySettings(self.manager)
        before = copy.deepcopy(settings.draft_values())
        for change in ({'changed': ['not-a-field']}, {'changed': ['offset_x', 'offset_x']}, {'format': 900}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                settings.restore_draft({**settings.draft(), **change})
            self.assertEqual(settings.draft_values(), before)

    def test_registration_readout_distinguishes_disabled_occupied_and_applied(self):
        settings = self.manager.play_settings = PlaySettings(self.manager)
        prefs = self.session.play_preferences.values['bindings']
        self.session.ui_capabilities.update(hotkeys_ready=True, bindings=dict(prefs), hotkeys_unavailable=[prefs['quick']])
        text = settings.key_status()
        self.assertIn('被占用/尚未生效', text)
        self.assertIn('已注册', text)


if __name__ == '__main__':
    unittest.main()
