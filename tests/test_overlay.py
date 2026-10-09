"""Native manager state retains complete context without rebuilding active controls."""
from queue import Queue
from types import SimpleNamespace
from unittest.mock import Mock
from tests.test_native_controllers import ControllerFixture
from companion.native_host import TextState
from companion.native_manager import NativeManager

class OverlayTests(ControllerFixture):
    def test_manager_state_exposes_health_risks_full_errors_and_actual_registration(self):
        ui=NativeManager.__new__(NativeManager);ui.manager=self.manager;ui.session=self.session;ui.host=self.host
        ui.exit_events=Queue();ui.exit_state=None;ui.frozen=False;ui.revision=0;ui.reported=None;ui.signature=None
        self.session.register_exit_surface('native',kind='native')
        self.manager.status=TextState('手动局势');self.manager.backup_status=TextState('备份监控中')
        self.manager.hero=TextState('HP 4/30');self.manager.metrics=TextState('基础力量 10')
        self.manager.action_error='';self.session.data['tips']=[{'title':'风险名称','body':'完整建议正文','severity':'warning'}]
        self.session.error='完整错误'+('路径/'*100)
        snap=self.session.snapshot();ui.update(snap)
        state=next(payload for action,payload in reversed(self.host.commands) if action=='manager_state')
        self.assertIn('HP 4/30',state['text']);self.assertIn('完整建议正文',state['text'])
        self.assertIn(self.session.error,state['text'])
        self.assertIn('全局快捷键',state['capabilities']);self.assertNotIn('play_available',state['capabilities'])
        before=len(self.host.commands);ui.update(snap)
        self.assertEqual(len(self.host.commands),before)
