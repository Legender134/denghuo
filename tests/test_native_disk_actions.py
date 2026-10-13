"""Real native dispatch/poll stays responsive across held service and file I/O."""
import copy
import json
from io import BytesIO
from pathlib import Path
from queue import Queue
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from companion.native_host import NativeHost, TextState
from companion.native_manager import NativeManager
from companion.native_settings import PlaySettings
from companion.service import Session
from tests.test_native_controllers import Host, Root


class DirectoryPickerTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='lamp-picker-');self.addCleanup(self.temporary.cleanup)
        self.base=Path(self.temporary.name).resolve();saves=self.base/'synthetic-saves';saves.mkdir()
        self.config=self.base/'settings.json';self.config.write_text(json.dumps({'save_root':str(saves)}),encoding='utf-8')
        self.session=Session(self.config)

    def picker(self, result=None):
        process=Mock(returncode=0)
        process.stdin=BytesIO();process.stdout=BytesIO(json.dumps(result or {'cancelled':False,'path':str(self.base)},ensure_ascii=False).encode())
        process.stderr=BytesIO();process.poll.return_value=0;process.wait.return_value=0
        return process

    def test_selected_and_cancelled_paths_never_apply_settings_or_create_backups(self):
        before={path.name:path.read_bytes() for path in self.base.iterdir() if path.is_file()}
        for kind,result in (('save',{'cancelled':False,'path':str(self.base)}),('backup',{'cancelled':False,'path':str(self.base)}),('save',{'cancelled':True,'path':''})):
            process=self.picker(result)
            with self.subTest(kind=kind,result=result),patch('companion.native_host.sys.platform','win32'),patch.dict('os.environ',{'LAMP_NATIVE_HELPER':str(self.config)}),patch('companion.native_host.subprocess.Popen',return_value=process) as launch:
                actual=self.session.choose_directory({'kind':kind,'initial':'  raw draft  '})
                self.assertEqual(actual,result)
                self.assertEqual(launch.call_args.args[0],[str(self.config),'--choose-directory',kind,'  raw draft  '])
                self.assertNotIn('shell',launch.call_args.kwargs)
                self.assertTrue(process.stdin.closed and process.stdout.closed and process.stderr.closed)
        self.assertEqual({path.name:path.read_bytes() for path in self.base.iterdir() if path.is_file()},before)
        self.assertFalse((self.base/'backups').exists())

    def test_invalid_requests_unavailable_helper_and_busy_dialog_are_actionable(self):
        from companion import native_host
        with patch('companion.native_host.sys.platform','win32'),patch('companion.native_host.subprocess.Popen') as launch:
            for payload in ({},None,{'kind':'save','initial':0},{'kind':'save','initial':'\0'},{'kind':'other','initial':''},{'kind':[],'initial':''}):
                with self.subTest(payload=payload),self.assertRaises(ValueError):self.session.choose_directory(payload)
            with patch.dict('os.environ',{'LAMP_NATIVE_HELPER':str(self.base/'missing.exe')}),self.assertRaisesRegex(ValueError,'控件缺失'):
                self.session.choose_directory({'kind':'backup','initial':''})
            with native_host._directory_picker_lock,self.assertRaisesRegex(ValueError,'已有文件夹'):
                self.session.choose_directory({'kind':'save','initial':''})
            launch.assert_not_called()

    def test_exit_closes_only_owned_picker_and_releases_single_dialog_lock(self):
        from companion.native_host import choose_directory,_directory_picker_lock
        process=self.picker();process.poll.return_value=None
        process.wait.side_effect=[subprocess.TimeoutExpired('owned picker',1),0]
        with patch('companion.native_host.sys.platform','win32'),patch.dict('os.environ',{'LAMP_NATIVE_HELPER':str(self.config)}),patch('companion.native_host.subprocess.Popen',return_value=process):
            with self.assertRaisesRegex(ValueError,'正在结束'):
                choose_directory({'kind':'save','initial':''},Mock(side_effect=[False,True]))
        process.terminate.assert_called_once();self.assertTrue(process.stdin.closed)
        self.assertFalse(_directory_picker_lock.locked())

    def test_invalid_or_disappeared_selected_folder_does_not_apply(self):
        for result in ({'cancelled':'false','path':str(self.base)},{'cancelled':False,'path':str(self.base/'gone')},{'error':'controlled dialog failure'}):
            with self.subTest(result=result),patch('companion.native_host.sys.platform','win32'),patch.dict('os.environ',{'LAMP_NATIVE_HELPER':str(self.config)}),patch('companion.native_host.subprocess.Popen',return_value=self.picker(result)):
                with self.assertRaises(ValueError):self.session.choose_directory({'kind':'save','initial':''})

    def test_http_picker_requires_mutation_token_and_returns_only_draft_path(self):
        from http.client import HTTPConnection
        from companion.server import Server
        server=Server(self.session,0);thread=threading.Thread(target=server.serve_forever);thread.start()
        before=self.config.read_bytes()
        try:
            with patch.object(self.session,'choose_directory',return_value={'cancelled':False,'path':str(self.base)}) as choose:
                for token,expected in ((False,403),(True,200)):
                    connection=HTTPConnection('127.0.0.1',server.server_port,timeout=3)
                    headers={'Content-Type':'application/json'}
                    if token:headers['X-Companion-Token']=server.token
                    try:
                        connection.request('POST','/api/select-directory',json.dumps({'kind':'save','initial':''}),headers)
                        response=connection.getresponse();self.assertEqual(response.status,expected);data=json.loads(response.read())
                        if token:self.assertEqual(data['path'],str(self.base))
                    finally:connection.close()
                choose.assert_called_once_with({'kind':'save','initial':''})
            self.assertEqual(self.config.read_bytes(),before)
        finally:
            server.shutdown();thread.join(3);server.server_close()
        self.assertFalse(thread.is_alive())


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

    def test_overview_reference_artwork_matches_the_bound_public_entry(self):
        from companion.reference import native_artwork
        self.session.update_manual({'hp': 4, 'ht': 30, 'level': 5, 'depth': 4})
        self.ui.update(self.session.snapshot(), force=True)
        state = next(payload for action, payload in reversed(self.host.commands) if action == 'manager_state')
        self.assertTrue(self.ui.references)
        self.assertEqual(len(state['reference_artworks']), len(state['reference_tokens']))
        self.assertTrue(any(state['reference_artworks']))
        for bound, artwork in zip(self.ui.references, state['reference_artworks']):
            expected = native_artwork(bound[0]['entry'])
            self.assertEqual(artwork, expected)

    def test_empty_overview_is_not_an_old_snapshot_and_priority_actions_bind_the_entry(self):
        self.ui.update(self.session.snapshot(), force=True)
        state = next(payload for action, payload in reversed(self.host.commands) if action == 'manager_state')
        self.assertTrue(state['no_data'])
        self.assertIn('尚未读到存档', state['source'])
        self.assertNotIn('旧快照', state['source'])
        self.session.update_manual({'hp': 4, 'ht': 30, 'level': 5, 'depth': 4})
        self.ui.update(self.session.snapshot(), force=True)
        state = next(payload for action, payload in reversed(self.host.commands) if action == 'manager_state')
        self.assertFalse(state['no_data'])
        actionable = [tip for tip in state['advice'] if tip['actions']]
        self.assertTrue(actionable)
        for tip in actionable:
            for action in tip['actions']:
                bound = self.ui.references[action['index']][0]
                self.assertEqual(action['text'], bound['name']+'数值')
                self.assertTrue(state['reference_tokens'][action['index']])

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


    def test_connection_conflict_reload_adopts_disk_and_preserves_play_draft(self):
        settings = self.settings()
        settings.vars['offset_x'].set('1e')
        other = Session(self.session.config_path)
        other.update_settings({'slot': 2})
        self.poll({'action': 'slot', 'index': 3}); self.finish()
        self.assertIn('连接设置', self.manager.action_error)
        self.assertEqual(self.session.settings['slot'], 'auto')
        self.poll({'action': 'reload_connection'}); self.finish()
        self.assertEqual(self.session.settings['slot'], 2)
        self.assertEqual(settings.vars['offset_x'].get(), '1e')
        self.assertTrue(settings.has_draft())
        self.assertEqual(self.manager.action_error, '')
        self.poll({'action': 'slot', 'index': 3}); self.finish()
        self.assertEqual(self.session.settings['slot'], 3)

    def test_expired_action_error_is_removed_from_current_native_state(self):
        self.manager.action_error = '已经过期的保存错误'
        self.manager.action_error_until = time.monotonic()-1
        self.ui.update(self.session.snapshot(), force=True)
        current = [d for action, d in self.host.commands if action == 'manager_state'][-1]
        self.assertNotIn('已经过期', current['error'])
        self.manager.action_error_until = time.monotonic()+30
        self.ui.update(self.session.snapshot(), force=True)
        current = [d for action, d in self.host.commands if action == 'manager_state'][-1]
        self.assertIn('已经过期', current['error'])

if __name__ == '__main__':
    unittest.main()
