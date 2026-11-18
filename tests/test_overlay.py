"""Native manager state retains complete context without rebuilding active controls."""
from queue import Queue
from types import SimpleNamespace
from unittest.mock import Mock
from tests.test_native_controllers import ControllerFixture
from companion.native_host import TextState
from companion.native_manager import NativeManager
from companion.overlay import Overlay

class OverlayTests(ControllerFixture):
    def test_exit_confirmation_ignores_user_shortcuts_but_drains_completion_notifications(self):
        ui = Overlay.__new__(Overlay)
        ui.native_ui = Mock(frozen=True)
        ui.play = Mock()
        ui.commands = Queue()
        ui.capture_pending = True
        ui.root = Mock()
        ui.update_capabilities = Mock()
        ui.close = Mock(return_value=False)
        ui.open_play_settings = Mock()
        ui.open_panel = Mock()
        ui.safely = Mock()
        for name in ('show', 'quick', 'play_toggle', 'play_settings', 'library',
                     'panel', 'backups', 'workspace', 'help', 'capture'):
            ui.commands.put((name, None))
        ui.commands.put(('captured', 'synthetic backup result'))
        ui.commands.put(('hotkeys', 'Ctrl+Alt+Q'))
        ui.commands.put(('exit', None))
        self.assertTrue(ui.process_commands())
        ui.native_ui.show.assert_not_called()
        ui.native_ui.workspace.handle.assert_not_called()
        ui.play.assert_not_called()
        ui.safely.assert_not_called()
        ui.open_play_settings.assert_not_called()
        ui.open_panel.assert_not_called()
        self.assertFalse(ui.capture_pending)
        self.assertEqual(ui.action_error, 'synthetic backup result')
        ui.update_capabilities.assert_called_once()
        ui.close.assert_called_once_with(confirm_drafts=True)
        ui.native_ui.frozen = False
        ui.commands.put(('quick', None))
        self.assertTrue(ui.process_commands())
        ui.safely.assert_called_once_with(ui.play.toggle_peek)

    def test_manager_state_exposes_health_risks_full_errors_and_actual_registration(self):
        ui=NativeManager.__new__(NativeManager);ui.manager=self.manager;ui.session=self.session;ui.host=self.host
        ui.exit_events=Queue();ui.exit_state=None;ui.frozen=False;ui.revision=0;ui.reported=None;ui.signature=None
        self.session.register_exit_surface('native',kind='native')
        self.manager.status=TextState('手动局势');self.manager.backup_status=TextState('备份监控中')
        self.manager.hero=TextState('HP 4/30');self.manager.metrics=TextState('基础力量 10')
        self.manager.action_error='';self.session.data['tips']=[{'id':'risk','basis':'test fixture','title':'风险名称','body':'完整建议正文','severity':'warning'}]
        self.session.error='完整错误'+('路径/'*100)
        snap=self.session.snapshot();ui.update(snap)
        state=next(payload for action,payload in reversed(self.host.commands) if action=='manager_state')
        self.assertEqual(state['life'], '4 / 30  生命')
        self.assertIn('完整建议正文',state['text'])
        self.assertIn(self.session.error,state['text'])
        self.assertIn('全局快捷键',state['capabilities']);self.assertNotIn('play_available',state['capabilities'])
        before=len(self.host.commands);ui.update(snap)
        self.assertEqual(len(self.host.commands),before)
