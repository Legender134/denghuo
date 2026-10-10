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


class NumericControllerTests(ControllerFixture):
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
        settings.handle({'action': 'settings_reload_decision', 'decision': 'discard'})
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
