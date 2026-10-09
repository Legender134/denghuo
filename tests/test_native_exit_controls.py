"""Cross-surface native exit protects the real controller drafts."""
from queue import Queue
from contextlib import ExitStack
import os
import time
from unittest.mock import Mock, patch

from tests.test_native_controllers import ControllerFixture
from companion.native_manager import NativeManager
from companion.native_settings import PlaySettings


class NativeExitTests(ControllerFixture):
    def setUp(self):
        super().setUp()
        self.ui = NativeManager.__new__(NativeManager)
        self.ui.manager, self.ui.session, self.ui.host = self.manager, self.session, self.host
        self.ui.exit_events, self.ui.exit_state = Queue(maxsize=32), None
        self.ui.revision, self.ui.reported, self.ui.frozen = 0, None, False
        self.session.register_exit_surface('native', kind='native', notify=self.ui.notify_exit)
        self.manager.native_ui = self.ui
        self.manager.open_play_settings = Mock()

    def test_web_request_then_native_cancel_keeps_raw_generation_and_session(self):
        self.open('items.potions.potionofhealing')
        self.lookup.variables['hp'].set('invalid raw')
        self.ui.report_drafts()
        self.session.request_exit('web-fixture')
        self.ui.process_exit()
        self.assertTrue(self.ui.frozen)
        self.ui.exit_decision({'decision': 'cancel'})
        self.assertFalse(self.session.stop.is_set())
        self.assertEqual(self.lookup.variables['hp'].get(), 'invalid raw')
        self.assertEqual(self.session.exit_status()['phase'], 'cancelled')

    def test_offline_aggregate_routes_selected_member_without_replacing_other_drafts(self):
        from pathlib import Path
        self.open('items.potions.potionofhealing')
        self.lookup.variables['hp'].set('offline invalid hp')
        settings = self.manager.play_settings = PlaySettings(self.manager)
        settings.vars['opacity'].set('offline invalid opacity')
        saved = self.session.save_exit_draft('native', 'offline-native', '离线原始副本', self.ui.drafts())
        source = Path(saved['path'])
        original = source.read_bytes()
        row = next(row for row in self.ui.draft_rows() if row['id'] == saved['id'])
        self.assertEqual(row['components'], ['numeric', 'play-settings'])
        record = self.session.load_exit_draft(saved['id'])
        with self.assertRaisesRegex(ValueError, '选择此离线副本'):
            self.ui.restore_draft(record)
        # The existing numeric draft remains dirty while a clean settings form is restored.
        settings.reload(True)
        self.ui.restore_draft(record, 'play-settings')
        self.assertEqual(settings.vars['opacity'].get(), 'offline invalid opacity')
        self.assertEqual(self.lookup.variables['hp'].get(), 'offline invalid hp')
        settings.vars['opacity'].set('new current draft')
        self.ui.error = Mock()
        self.ui.restore_draft(record, 'play-settings')
        self.ui.error.assert_called_once()
        self.assertEqual(settings.vars['opacity'].get(), 'new current draft')
        self.lookup.guard = Mock()
        self.manager.open_lookup = Mock()
        self.ui.restore_draft(record, 'numeric')
        self.lookup.guard.assert_called_once()
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(len(self.session.list_exit_drafts()), 1)
        with self.assertRaises(ValueError):
            self.ui.restore_draft(record, 'web-session')

    def test_native_picker_defaults_active_and_can_list_restored_archive_with_same_id(self):
        saved = self.session.save_exit_draft('native', 'numeric', '待归档', {'raw_params': {'hp': '-'}})
        row = self.ui.draft_rows()[0]
        self.session.exit_action({'action': 'draft-state', 'id': row['id'], 'state': 'archived', 'expected_revision': row['state_revision']})
        self.assertEqual(self.ui.draft_rows(), [])
        archived = self.ui.draft_rows(True)[0]
        self.assertEqual(archived['id'], saved['id'])
        self.assertEqual(archived['state'], 'archived')
        listing = self.session.exit_action({'action': 'draft-list'})
        self.assertEqual(listing, {'drafts': [], 'archived_count': 1})
        self.session.exit_action({'action': 'draft-state', 'id': row['id'], 'state': 'active', 'expected_revision': archived['state_revision']})
        self.assertEqual(self.ui.draft_rows()[0]['id'], saved['id'])

    def test_save_all_raw_drafts_then_ack_and_finished_close_do_not_register(self):
        self.open('items.potions.potionofhealing')
        self.lookup.variables['hp'].set('invalid raw')
        settings = self.manager.play_settings = PlaySettings(self.manager)
        settings.vars['opacity'].set('bad settings')
        self.ui.report_drafts()
        self.session.request_exit('web-fixture')
        self.ui.process_exit()
        self.ui.exit_decision({'decision': 'saved'})
        self.assertEqual({row['draft_kind'] for row in self.session.list_exit_drafts()}, {'numeric', 'play-settings'})
        deadline = time.monotonic()+4
        while self.session.exit_status()['phase'] != 'finished' and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(self.session.exit_status()['phase'], 'finished')
        self.host.close = Mock()
        self.ui.close()
        self.host.close.assert_called_once()

    def test_stale_clean_ack_rechecks_actual_native_draft(self):
        self.open('items.potions.potionofhealing')
        self.ui.report_drafts()
        self.session.request_exit('web-fixture')
        self.lookup.variables['hp'].set('2')
        self.ui.exit_decision({'decision': 'clean'})
        self.assertEqual(self.session.exit_status()['phase'], 'confirming')
        self.assertFalse(self.session.stop.is_set())

    def test_save_dialog_only_dirty_is_saved_as_a_copy_with_latest_note(self):
        self.open('items.weapon.melee.sword')
        self.lookup.note.set('原备注')
        self.assertTrue(self.lookup.save_plan('原方案'))
        original=self.lookup.saved_plan['id']
        pending={'name':'弹窗未提交名称','note':'未提交第一行\n未提交第二行','update':True}
        self.lookup.handle({'action':'save_dialog_edit','pending_save':pending})
        self.assertTrue(self.lookup.has_draft())
        self.ui.report_drafts();self.session.request_exit('web-fixture');self.ui.process_exit()
        self.ui.exit_decision({'decision':'saved'})
        plans=self.session.workspace_status()['plans']
        copied=next(row for row in plans if row['id']!=original)
        self.assertEqual(copied['name'],'弹窗未提交名称 草稿副本')
        self.assertEqual(copied['note'],pending['note'])
        self.assertEqual(self.session.knowledge.reopen(original)['plan']['note'],'原备注')

    def test_last_exit_payload_captures_save_dialog_before_clean_ack(self):
        self.open('items.weapon.melee.sword')
        self.ui.report_drafts();self.session.request_exit('web-fixture')
        pending = {'name':'最新弹窗','note':'第一行\n第二行\n第三行','update':True}
        self.ui.exit_decision({'decision':'clean','lookup':{'values':self.lookup.raw_params(),'note':'','pending_save':pending}})
        self.assertEqual(self.session.exit_status()['phase'],'confirming')
        self.assertEqual(self.lookup.pending_save,pending)
        self.assertEqual(self.lookup.draft()['note'],pending['note'])

    def test_failed_cas_closed_dialog_exit_keeps_intent_invalid_raw_and_old_revision(self):
        import copy
        from companion.service import Session
        self.ui.update = Mock()  # Ancillary window labels are outside this transport fixture.
        self.open('items.weapon.melee.sword')
        self.lookup.variables['level'].set('-1')
        self.lookup.calculate(); self.finish()
        self.assertTrue(self.lookup.save_plan('原方案'))
        original = copy.deepcopy(self.lookup.saved_plan)
        external = Session(self.directory/'settings.json')
        external.knowledge.save(original['name'], 'numeric', original['entry'], original['params'],
            original['origin'], original['id'], original['record_revision'], note='另一窗口更新')
        latest = external.knowledge.reopen(original['id'])['plan']
        pending = {'name': original['name'], 'note': '本窗口未提交的备注\n保存冲突后必须保留\n退出副本不覆盖另一窗口', 'update': True}
        self.ui.dispatch({'action': 'save_named', 'surface': 'lookup', **pending})
        self.ui.dispatch({'action': 'save_dialog_closed', 'surface': 'lookup', 'cancelled': False})
        self.assertIn('另一窗口', self.lookup.plan_error)
        self.assertEqual(self.lookup.pending_save, pending)
        raw = {'values': {**self.lookup.raw_params(), 'level': '-'}, 'note': pending['note'],
               'draft_revision': self.lookup.edit_revision+1}
        self.ui.dispatch({'action': 'edit', 'surface': 'lookup', **raw})
        self.assertEqual(self.lookup.pending_save, pending)
        self.ui.report_drafts(); self.session.request_exit('web-fixture'); self.ui.process_exit()
        self.ui.dispatch({'action': 'exit_decision', 'decision': 'saved', 'lookup': raw})
        drafts = self.session.list_exit_drafts()
        self.assertEqual(len(drafts), 1)
        saved = self.session.load_exit_draft(drafts[0]['id'])['draft']
        self.assertEqual(saved['raw_params']['level'], '-')
        self.assertEqual(saved['pending_save'], pending)
        self.assertEqual(saved['note'], pending['note'])
        self.assertEqual(saved['saved_plan']['record_revision'], original['record_revision'])
        self.assertEqual(self.session.knowledge.reopen(original['id'])['plan'], latest)
        self.assertEqual(len(self.session.workspace_status()['plans']), 1)
        self.lookup.restore_draft(saved)
        self.assertEqual(self.lookup.raw_params()['level'], '-')
        self.assertEqual(self.lookup.pending_save, pending)
        self.assertEqual(self.lookup.saved_plan['record_revision'], original['record_revision'])
        self.assertIsNone(self.lookup.calculated)
        self.assertIsNone(self.lookup.rendered)

    def test_failed_draft_save_remains_confirming_and_allows_retry_or_cancel(self):
        self.open('items.potions.potionofhealing')
        self.lookup.variables['hp'].set('unsaved raw')
        self.ui.report_drafts()
        self.session.request_exit('web-fixture')
        self.session.save_exit_draft = Mock(side_effect=OSError('disk fixture failure'))
        with self.assertLogs(level='ERROR'):
            self.ui.dispatch({'action': 'exit_decision', 'decision': 'saved'})
        self.assertEqual(self.session.exit_status()['phase'], 'confirming')
        self.assertEqual(self.lookup.variables['hp'].get(), 'unsaved raw')
        self.assertEqual(self.host.commands[-1][0], 'exit_save_error')
        self.ui.exit_decision({'decision': 'cancel'})
        self.assertEqual(self.session.exit_status()['phase'], 'cancelled')

    def test_helper_eof_preserves_individual_raw_drafts_and_marks_surface_offline(self):
        self.open('items.potions.potionofhealing')
        self.lookup.variables['hp'].set('  unfinished EOF raw  ')
        self.ui.report_drafts()
        self.host.process = Mock()
        self.host.process.poll.return_value = 0
        with ExitStack() as stack:
            if os.name == 'nt':
                stack.enter_context(patch('ctypes.windll.user32.MessageBoxW', return_value=1))
            stack.enter_context(self.assertLogs(level='ERROR'))
            self.ui.error('fixture EOF')
        self.ui.report_drafts()
        saved = self.session.load_exit_draft(self.session.list_exit_drafts()[0]['id'])
        self.assertEqual(saved['draft']['raw_params']['hp'], '  unfinished EOF raw  ')
        state = self.session.request_exit('web-fixture')
        native = next(row for row in state['participants'] if row['surface_id'] == 'native')
        self.assertFalse(native['online'])
        self.assertTrue(native['has_recovery_draft'])
