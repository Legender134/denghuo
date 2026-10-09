import argparse
import io
import json
import os
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from companion import __main__ as cli
from companion.diagnostics import report_failure
from companion.server import Server
from companion.panel import PanelBridge


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='lamp-startup-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root/'settings.json'
        self.config.write_text(json.dumps({'save_root':str(self.root)}))
        self.servers = []

    def server(self, *args):
        server = Server(*args)
        self.servers.append(server)
        return server

    def assert_port_released(self):
        server = self.servers[0]
        self.assertEqual(server.fileno(),-1)
        with socket.socket() as probe:
            probe.bind(('127.0.0.1',server.server_port))

    def test_failed_runtime_write_releases_bound_port_before_threads_start(self):
        with patch.object(cli,'ROOT',self.root), patch.object(cli,'Server',side_effect=self.server):
            with patch.object(Path,'replace',side_effect=PermissionError('controlled write failure')):
                with self.assertRaises(PermissionError):
                    cli.main(['--config',str(self.config),'--no-browser','--no-overlay'])
        self.assert_port_released()

    def test_browser_failure_stops_running_service(self):
        with patch.object(cli,'ROOT',self.root), patch.object(cli,'Server',side_effect=self.server):
            with patch.object(cli.webbrowser,'open',side_effect=RuntimeError('controlled browser failure')):
                with self.assertRaises(RuntimeError):
                    cli.main(['--config',str(self.config),'--no-overlay'])
        self.assert_port_released()

    def test_startup_surface_and_explicit_flags(self):
        cases = [('panel', [], True, True), ('native', [], False, False),
                 ('native', ['--web'], True, True), ('panel', ['--no-browser'], False, False),
                 ('panel', ['--start-hidden'], False, True), ('native', ['--start-hidden'], False, True)]
        for surface, flags, panel, hidden in cases:
            with self.subTest(surface=surface, flags=flags):
                self.config.write_text(json.dumps({'save_root': str(self.root), 'startup_surface': surface}))
                self.servers = []
                calls = []
                def overlay(session, url, **kwargs):
                    calls.append(kwargs)
                    return SimpleNamespace(run=lambda: session.stop.set())
                with patch.dict('sys.modules', {'companion.overlay': SimpleNamespace(Overlay=overlay)}):
                    with patch('companion.panel.webbrowser.open', return_value=True) as browser, patch.object(cli, 'Server', side_effect=self.server):
                        cli.main(['--config', str(self.config), *flags])
                self.assertEqual(browser.call_count, int(panel))
                self.assertEqual(calls, [{'start_hidden': hidden}])
                self.assert_port_released()

    def test_false_browser_result_exits_with_url_and_releases_port(self):
        with patch.object(cli, 'Server', side_effect=self.server), patch('companion.panel.webbrowser.open', return_value=False):
            with patch('companion.diagnostics.report_failure') as failure:
                self.assertEqual(cli.entrypoint(['--config', str(self.config)]), 1)
        self.assertIn('http://127.0.0.1:', str(failure.call_args.args[0]))
        self.assertIn('复制', str(failure.call_args.args[0]))
        self.assert_port_released()

    def test_web_contradictions_fail_before_session(self):
        with patch.object(cli, 'Session') as session, patch('sys.stderr', io.StringIO()):
            for flags in (['--web', '--no-browser'], ['--web', '--start-hidden']):
                with self.assertRaises(SystemExit) as error:
                    cli.main(flags)
                self.assertEqual(error.exception.code, 2)
        session.assert_not_called()

    def test_no_overlay_explicit_background_modes_do_not_open_browser(self):
        real_session = cli.Session
        def stopped_session(*args, **kwargs):
            session = real_session(*args, **kwargs)
            session.stop.set()
            return session
        for flags in (['--no-browser'], ['--start-hidden']):
            with self.subTest(flags=flags), patch.object(cli, 'Session', side_effect=stopped_session):
                with patch('companion.panel.webbrowser.open') as browser:
                    cli.main(['--config', str(self.config), '--no-overlay', *flags])
                browser.assert_not_called()

    def test_duplicate_shows_existing_native_window_without_browser(self):
        state={'catalog_version':'4.0.1','manager_reuse':True,'panel_reuse':True,'token':'fixture-token','settings':{'startup_surface':'native'}}
        with patch.object(Path,'read_text',return_value=json.dumps({'port':12345})):
            with patch.object(cli,'urlopen',side_effect=[io.StringIO(json.dumps(state)),io.StringIO('{"ok":true}')]) as request:
                with patch.object(cli.webbrowser,'open') as browser:
                    cli.open_existing(self.root/'runtime.json')
        browser.assert_not_called()
        routed=request.call_args.args[0]
        self.assertEqual(routed.full_url,'http://127.0.0.1:12345/api/panel')
        self.assertEqual(json.loads(routed.data),{'action':'show'})

    def test_duplicate_routes_preference_and_web_override_to_reused_panel(self):
        for surface, flags in (('panel', {}), ('native', {'web': True}), ('native', {'no_overlay': True})):
            state = {'catalog_version': '4.0.2', 'manager_reuse': True, 'panel_reuse': True,
                     'token': 'fixture-token', 'settings': {'startup_surface': surface}}
            with self.subTest(surface=surface, flags=flags), patch.object(Path, 'read_text', return_value=json.dumps({'port': 12345})):
                with patch.object(cli, 'urlopen', side_effect=[io.StringIO(json.dumps(state)), io.StringIO('{"ok":true}')]) as request:
                    with patch.object(cli.webbrowser, 'open') as browser:
                        cli.open_existing(self.root/'runtime.json', **flags)
                self.assertEqual(json.loads(request.call_args.args[0].data), {'action': 'open'})
                browser.assert_not_called()

    def test_duplicate_false_browser_reports_url(self):
        with patch.object(Path, 'read_text', return_value=json.dumps({'port': 12345})):
            with patch.object(cli, 'urlopen', return_value=io.StringIO('{"catalog_version":"4.0.2"}')):
                with patch.object(cli.webbrowser, 'open', return_value=False):
                    with self.assertRaisesRegex(RuntimeError, 'http://127.0.0.1:12345'):
                        cli.open_existing(self.root/'runtime.json', timeout=0)

    def test_duplicate_waits_for_metadata_and_opens_verified_loopback(self):
        with patch.object(Path,'read_text',side_effect=[FileNotFoundError(),json.dumps({'port':12345,'url':'https://unused.invalid'})]):
            with patch.object(cli,'urlopen',return_value=io.StringIO('{"catalog_version":"4.0.0"}')) as request:
                with patch.object(cli.webbrowser,'open') as browser, patch.object(cli.time,'sleep'):
                    cli.open_existing(self.root/'runtime.json')
        request.assert_called_once_with('http://127.0.0.1:12345/api/status',timeout=.4)
        browser.assert_called_once_with('http://127.0.0.1:12345')

    def test_stale_duplicate_gives_recoverable_message(self):
        with self.assertRaisesRegex(RuntimeError,'稍后重新双击'):
            cli.open_existing(self.root/'missing.json',timeout=0)

    def test_startup_error_is_visible_and_logged(self):
        output=io.StringIO()
        with patch('companion.diagnostics.sys.stderr',output):
            message=report_failure(ValueError('受控启动错误'),self.root)
        self.assertIn('受控启动错误',output.getvalue())
        self.assertIn('--no-overlay',message)
        self.assertIn('受控启动错误',(self.root/'.local/startup-error.log').read_text(encoding='utf-8'))

    def test_unwritable_project_uses_temp_log(self):
        blocked=self.root/'blocked';blocked.write_text('owned test file')
        fallback=self.root/'fallback'
        with patch('companion.diagnostics.tempfile.gettempdir',return_value=str(fallback)):
            with patch('companion.diagnostics.sys.stderr',io.StringIO()):
                message=report_failure(PermissionError('受控权限错误'),blocked)
        self.assertIn(str(fallback),message)
        self.assertTrue((fallback/'dungeon-companion-startup-error.log').exists())

    @unittest.skipUnless(os.name=='nt','Windows GUI error route')
    def test_pythonw_error_uses_native_dialog(self):
        with patch('companion.diagnostics.sys.stderr',None):
            with patch('companion.diagnostics.ctypes.windll.user32.MessageBoxW') as dialog:
                report_failure(ValueError('受控窗口错误'),self.root)
        self.assertEqual(dialog.call_count,1)
        self.assertIn('受控窗口错误',dialog.call_args.args[1])

    def test_invalid_ports_fail_before_startup(self):
        for value in ('-1','65536','oops'):
            with self.assertRaises(argparse.ArgumentTypeError):cli.port_number(value)


class PanelBridgeTests(unittest.TestCase):
    def test_false_open_is_not_success_or_throttled_retry(self):
        from unittest.mock import Mock
        opener = Mock(side_effect=[False, True])
        bridge = PanelBridge(clock=lambda: 10, opener=opener)
        bridge.bind('http://127.0.0.1:12345')
        with self.assertRaisesRegex(ValueError, 'http://127.0.0.1:12345/#workspace'):
            bridge.request('workspace')
        self.assertEqual(bridge.last_open, -1000)
        self.assertIsNone(bridge.pending)
        bridge.request('workspace')
        self.assertEqual(bridge.last_open, 10)
        self.assertEqual(opener.call_count, 2)

    def test_connected_panel_is_reused_without_new_tab(self):
        from unittest.mock import Mock
        opener = Mock(return_value=True)
        bridge = PanelBridge(clock=lambda: 10, opener=opener)
        bridge.bind('http://127.0.0.1:12345')
        bridge.heartbeat('owned-panel-client-0001')
        bridge.request('workspace')
        command = bridge.heartbeat('owned-panel-client-0001')
        self.assertEqual(command['page'], 'workspace')
        opener.assert_not_called()


if __name__=='__main__':unittest.main()
