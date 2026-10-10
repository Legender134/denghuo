"""Real native dispatch/poll stays responsive across held service and file I/O."""
import copy
import json
from pathlib import Path
from queue import Queue
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from companion.native_host import NativeHost, TextState
from companion.native_manager import NativeManager
from companion.native_settings import PlaySettings
from companion.service import Session
from tests.test_native_controllers import Host, Root


class NativeDiskActionsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='lamp-native-disk-')
        # Windows CI may expose TEMP through an 8.3 alias; Session canonicalizes roots.
        self.directory = Path(self.temporary.name).resolve()
        saves = self.directory/'synthetic-saves'
        saves.mkdir()
        config = self.directory/'settings.json'
        config.write_text(json.dumps({'save_root': str(saves), 'slot': 'auto'}), encoding='utf-8')
        self.session = Session(config)
        self.ui, self.host = NativeManager.__new__(NativeManager), Host()
        self.host.threads = []
        command = self.host.command
        def record(action, **payload):
            self.host.threads.append(threading.get_ident())
            command(action, **payload)
        self.host.command = record
        self.manager = SimpleNamespace(session=self.session, root=Root(), play=None, play_settings=None,
            action_error='', action_error_until=0, play_apply_error='', apply_play_settings=Mock(),
            status=TextState(), backup_status=TextState(), hero=TextState(), metrics=TextState(), tray=None)
        self.manager.native_ui = self.ui
        self.ui.manager, self.ui.session, self.ui.host = self.manager, self.session, self.host
        self.ui.exit_events, self.ui.exit_state = Queue(maxsize=32), None
        self.ui.revision, self.ui.reported, self.ui.signature = 0, None, None
        self.ui.frozen, self.ui.references = False, []
        self.ui.error = Mock()
        self.session.register_exit_surface('native', kind='native', notify=self.ui.notify_exit)
        self.bridge = NativeHost.__new__(NativeHost)
        self.bridge.root, self.bridge.dispatch, self.bridge.idle = self.manager.root, self.ui.dispatch, self.ui.process_io
        self.bridge.incoming, self.bridge.closed, self.bridge.failed = Queue(maxsize=128), False, False
        self.releases = []

    def tearDown(self):
        for release in self.releases:
            release.set()
        if hasattr(self.ui, '_io_thread'):
            if self.ui.io_busy:
                self.assertTrue(self.ui._io_job['done'].wait(5))
            self.ui._io_stop.set()
            self.ui._io_thread.join(2)
            self.assertFalse(self.ui._io_thread.is_alive())
        self.assertTrue(self.session.exit_coordinator.flush_checkpoints(5))
        self.session.stop.set()
        self.temporary.cleanup()

    def poll(self, *messages):
        for message in messages:
            self.bridge.incoming.put_nowait(message)
        self.bridge.poll()
        self.assertIsNotNone(self.bridge.timer)
        self.assertIn(self.bridge.timer, self.manager.root.jobs)
        self.ui.error.assert_not_called()

    def finish(self):
        if self.ui.io_busy:
            self.assertTrue(self.ui._io_job['done'].wait(5))
        self.poll()
        self.assertFalse(self.ui.io_busy)
        self.assertEqual(set(self.host.threads), {threading.get_ident()})

    def settings(self):
        self.manager.play = SimpleNamespace(preferences=self.session.play_preferences,
            lookup=None, unlock_layout=Mock())
        self.manager.play_settings = PlaySettings(self.manager)
        self.manager.open_play_settings = Mock()
        return self.manager.play_settings

    def hold_preferences_read(self):
        entered, release = threading.Event(), threading.Event()
        self.releases.append(release)
        target, original = self.session.play_preferences.path, Path.open
        def held(path, *args, **kwargs):
            if path == target and args and args[0] == 'rb':
                entered.set()
                if not release.wait(5):
                    raise AssertionError('held disk was not released')
            return original(path, *args, **kwargs)
        return entered, release, patch.object(Path, 'open', held)

    def test_connection_gate_does_not_block_poll_exit_cancel_or_duplicate_rejection(self):
        with self.session._backup_io_lock:
            self.poll({'action': 'slot', 'index': 2})
            job = self.ui._io_job
            self.assertTrue(self.ui.io_busy)
            state = next(p for a, p in reversed(self.host.commands) if a == 'manager_state')
            self.assertTrue(state['io_busy'])
            self.assertIn('等待', state['error'])
            self.poll({'action': 'directory', 'path': str(self.directory)})
            self.assertIs(self.ui._io_job, job)
            self.poll({'action': 'exit'})
            state = self.session.exit_status()
            self.assertEqual(state['phase'], 'confirming')
            self.poll({'action': 'exit_decision', 'request_id': state['id'], 'decision': 'cancel'})
            self.assertEqual(self.session.exit_status()['phase'], 'cancelled')
            self.assertFalse(job['done'].is_set())
        self.finish()
        self.assertEqual(self.session.settings['slot'], 2)
        self.assertFalse(self.ui.frozen)

    def test_connection_cas_keeps_a_newer_external_commit(self):
        with self.session._backup_io_lock:
            self.poll({'action': 'slot', 'index': 2})
            self.session._update_settings({'slot': 3})
        self.finish()
        self.assertEqual(self.session.settings['slot'], 3)
        self.assertIn('其他位置更新', self.manager.action_error)

    def test_shutdown_rejects_waiting_connection_and_does_not_publish_ui_completion(self):
        original = self.session.config_path.read_bytes()
        with self.session._backup_io_lock:
            self.poll({'action': 'pin_manager', 'checked': not self.session.settings['always_on_top']})
            self.session._shutdown_requested.set()
        self.assertTrue(self.ui._io_job['done'].wait(5))
        commands = copy.deepcopy(self.host.commands)
        self.ui.process_io()
        self.assertFalse(self.ui.io_busy)
        self.assertEqual(self.host.commands, commands)
        self.assertEqual(self.session.config_path.read_bytes(), original)

    def test_directory_and_refresh_disk_work_run_outside_poll_thread(self):
        other = self.directory/'another-synthetic-save-root'
        other.mkdir()
        with self.session._backup_io_lock:
            self.poll({'action': 'directory', 'path': str(other)})
            self.assertFalse(self.ui._io_job['done'].is_set())
        self.finish()
        self.assertEqual(Path(self.session.settings['save_root']), other)
        entered, release = threading.Event(), threading.Event()
        self.releases.append(release)
        original = self.session._read_refresh
        def held(state):
            entered.set()
            if not release.wait(5):
                raise AssertionError('refresh hold not released')
            return original(state)
        with patch.object(self.session, '_read_refresh', held):
            self.poll({'action': 'refresh'})
            self.assertTrue(entered.wait(2))
            self.poll({'action': 'exit'})
            state = self.session.exit_status()
            self.poll({'action': 'exit_decision', 'request_id': state['id'], 'decision': 'cancel'})
            release.set()
            self.finish()

    def test_settings_save_keeps_new_raw_draft_and_only_applies_on_ui_thread(self):
        settings = self.settings()
        settings.vars['offset_x'].set('777')
        entered, release, held = self.hold_preferences_read()
        with held:
            self.poll({'surface': 'settings', 'action': 'settings_save'})
            self.assertTrue(entered.wait(2))
            self.poll({'surface': 'settings', 'action': 'settings_edit', 'values': {'offset_x': '  -  '}})
            self.assertEqual(settings.vars['offset_x'].get(), '  -  ')
            # Opening a fresh form reads a published receipt without the held disk lock.
            fresh = PlaySettings(self.manager)
            self.assertEqual(fresh.vars['offset_x'].get(), '16')
            self.manager.apply_play_settings.assert_not_called()
            release.set()
            self.finish()
        self.assertEqual(self.session.play_preferences.values['offset_x'], 777)
        self.assertEqual(settings.vars['offset_x'].get(), '  -  ')
        self.assertTrue(settings.has_draft())
        self.assertIn('新编辑', settings.status.text)
        self.manager.apply_play_settings.assert_called_once_with()

    def test_settings_cas_conflict_retains_all_inputs(self):
        settings = self.settings()
        settings.vars['offset_x'].set('777')
        preferences = self.session.play_preferences
        with preferences.lock:
            self.poll({'surface': 'settings', 'action': 'settings_save'})
            preferences.update({'offset_y': 888})
        self.finish()
        self.assertEqual(preferences.values['offset_y'], 888)
        self.assertEqual(preferences.values['offset_x'], 16)
        self.assertTrue(settings.has_draft())
        self.assertEqual(settings.vars['offset_x'].get(), '777')
        self.assertIn('另一窗口', settings.status.text)

    def test_settings_shutdown_during_read_does_not_write_or_apply(self):
        settings = self.settings()
        settings.vars['offset_x'].set('777')
        entered, release, held = self.hold_preferences_read()
        with held:
            self.poll({'surface': 'settings', 'action': 'settings_save'})
            self.assertTrue(entered.wait(2))
            self.session._shutdown_requested.set()
            release.set()
            self.assertTrue(self.ui._io_job['done'].wait(5))
            commands = copy.deepcopy(self.host.commands)
            self.ui.process_io()
        self.assertEqual(self.host.commands, commands)
        self.assertFalse(self.session.play_preferences.path.exists())
        self.assertEqual(self.session.play_preferences.generation, 0)
        self.manager.apply_play_settings.assert_not_called()
        self.assertTrue(settings.has_draft())

    def test_reload_requires_decision_and_keeps_edits_arriving_during_read(self):
        settings = self.settings()
        settings.vars['offset_x'].set('-')
        self.poll({'surface': 'settings', 'action': 'settings_reload'})
        self.assertFalse(self.ui.io_busy)
        self.assertTrue(any(a == 'confirm' for a, p in self.host.commands))
        entered, release, held = self.hold_preferences_read()
        with held:
            self.poll({'surface': 'settings', 'action': 'settings_reload_decision', 'decision': 'saved'})
            self.assertTrue(entered.wait(2))
            self.poll({'surface': 'settings', 'action': 'settings_edit', 'values': {'offset_x': '1e'}})
            release.set()
            self.finish()
        self.assertEqual(settings.vars['offset_x'].get(), '1e')
        self.assertTrue(settings.has_draft())
        saved = self.session.load_exit_draft(self.session.list_exit_drafts()[0]['id'])
        self.assertEqual(saved['draft']['values']['offset_x'], '-')
        self.assertIn('新编辑', settings.status.text)
        self.poll({'surface': 'settings', 'action': 'settings_reload_decision', 'decision': 'discard'})
        self.finish()
        self.assertFalse(settings.has_draft())
        self.assertEqual(settings.vars['offset_x'].get(), '16')

    def test_unlock_waits_for_save_and_abandons_layout_change_if_new_input_arrives(self):
        settings = self.settings()
        entered, release, held = self.hold_preferences_read()
        with held:
            self.poll({'surface': 'settings', 'action': 'unlock'})
            self.assertTrue(entered.wait(2))
            self.manager.play.unlock_layout.assert_not_called()
            self.poll({'surface': 'settings', 'action': 'settings_edit', 'values': {'offset_x': '-'}})
            release.set()
            self.finish()
        self.manager.play.unlock_layout.assert_not_called()
        settings.vars['offset_x'].set('20')
        self.poll({'surface': 'settings', 'action': 'unlock'})
        self.finish()
        self.manager.play.unlock_layout.assert_called_once_with(persist=False)


if __name__ == '__main__':
    unittest.main()
