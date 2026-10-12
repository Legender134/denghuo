"""Real calculator, plan and draft contracts for the in-game workspace."""
import copy
import json
from types import SimpleNamespace
from unittest.mock import Mock

from tests.test_native_controllers import ControllerFixture
from companion.game_workspace import GameWorkspace


class GameWorkspaceTests(ControllerFixture):
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
        self.workspace.calculate('equipment'); self.assertEqual(self.workspace.calculated['equipment'], original)

    def test_pending_save_never_marks_new_input_saved(self):
        self.equipment(); self.workspace.calculate('equipment'); self.workspace.raw['equipment']['name'] = '原条件'
        self.workspace.handle({'page': 'equipment', 'command': 'save'})
        self.workspace.edit('equipment', {**self.workspace.raw['equipment'], 'level_a': '3'})
        self.finish_job(); self.assertIn('equipment', self.workspace.dirty)
        self.assertEqual(self.workspace.raw['equipment']['level_a'], '3'); self.native.error.assert_called_once()

    def test_alchemy_multitarget_shared_budget_roundtrip_and_undo(self):
        self.alchemy(); self.workspace.calculate('alchemy')
        args = self.workspace.calculated['alchemy']; self.assertEqual(args['resources'][0]['reserve'], 1)
        self.assertIn('能量', self.workspace.results['alchemy'])
        self.workspace.load_alchemy(args); self.assertEqual(self.workspace.alchemy_args(), args)
        raw = copy.deepcopy(self.workspace.raw['alchemy'])
        self.workspace.handle({'page': 'alchemy', 'command': 'add_target'})
        self.workspace.handle({'page': 'alchemy', 'command': 'undo'})
        self.assertEqual(self.workspace.raw['alchemy'], raw)

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
        with self.assertRaises(ValueError): self.workspace.open_plan({'plan': {'kind': 'equipment'}})

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

    def test_inventory_unknown_reading_explicit_reveal_and_stale_selection(self):
        root, slot = self.saved_game()
        original = {p.name: p.read_bytes() for p in slot.iterdir()}
        rows = self.workspace.inventory(); self.assertEqual(len(rows), 2)
        unknown = next(r for r in rows if not r['item']['known'])
        self.select('inventory', unknown)
        with self.assertRaisesRegex(ValueError, '已鉴定'): self.workspace.inventory_action('equip_a')
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
        token = self.workspace.backup_preview['token']
        self.session.backups.closed_check = lambda: (_ for _ in ()).throw(ValueError('游戏仍在运行'))
        self.workspace.handle({'page': 'backups', 'command': 'backup_execute', 'token': token}); self.finish_job()
        self.assertEqual({p.name: p.read_bytes() for p in slot.iterdir()}, current)
        self.assertIn('运行', self.native.error.call_args.args[0])
        self.finish_job(); self.select('backups', self.workspace.rows['backups'][0])
        self.workspace.preview_backup(); self.finish_job()
        self.session.backups.closed_check = lambda: None
        self.workspace.handle({'page': 'backups', 'command': 'backup_execute', 'token': self.workspace.backup_preview['token']}); self.finish_job()
        self.assertEqual({p.name: p.read_bytes() for p in slot.iterdir()}, original)
        retained = list(root.glob('.denghuo-before-1-*'))
        self.assertEqual(len(retained), 1)
        self.assertEqual({p.name: p.read_bytes() for p in retained[0].iterdir()}, current)
