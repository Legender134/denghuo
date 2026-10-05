import argparse
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from companion import __main__ as cli
from companion.diagnostics import report_failure
from companion.server import Server


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


if __name__=='__main__':unittest.main()
