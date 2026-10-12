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

    def test_restore_progress_uses_local_datetime_class_and_short_identity(self):
        summary = {'class': 'MAGE', 'level': 3, 'depth': 2, 'hp': 20, 'ht': 30, 'saved': 1791809981.25, 'run_id': 'abc12345'*8}
        text = GameWorkspace.progress_text(summary)
        self.assertIn('职业 法师', text); self.assertIn('2026-', text)
        self.assertRegex(text, r'\d{2}:\d{2}:\d{2} UTC[+-]\d{4}')
        self.assertIn(summary['run_id'][:12], text); self.assertNotIn(summary['run_id'], text)
        self.assertNotIn(str(summary['saved']), text)

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
