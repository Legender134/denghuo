import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from companion.updates import Updates, NoRedirect, validate_manifest, version_tuple


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name) / 'updates'
        self.stop = threading.Event()
        self.binary = b'MZ' + b'installer-content' * 100
        self.manifest = {'format': 1, 'application': 'denghuo', 'version': '0.8.0',
            'installer': {'filename': 'Denghuo-Setup.exe', 'size': len(self.binary),
                          'sha256': hashlib.sha256(self.binary).hexdigest()}, 'notes': '更新说明'}
        self.requests = []
        def open_file(name):
            self.requests.append(name)
            return io.BytesIO(json.dumps(self.manifest).encode() if name == 'latest.json' else self.binary)
        self.updates = Updates(self.directory, self.stop, opener=open_file, current='0.7.0', can_install=True)

    def finished(self):
        self.updates.worker.join(3)
        self.assertFalse(self.updates.worker.is_alive())
        return self.updates.snapshot()

    def ready(self):
        self.updates.check()
        self.assertEqual(self.finished()['state'], 'available')
        self.updates.download()
        self.assertEqual(self.finished()['state'], 'ready')

    def test_check_is_nonblocking_and_never_downloads_or_creates_files(self):
        release = threading.Event()
        def delayed(name):
            self.assertTrue(release.wait(3))
            return io.BytesIO(json.dumps(self.manifest).encode())
        self.updates.opener = delayed
        self.assertEqual(self.updates.check()['state'], 'checking')
        self.assertFalse(self.directory.exists())
        release.set()
        self.assertEqual(self.finished()['latest_version'], '0.8.0')
        self.assertFalse(self.directory.exists())

    def test_no_update_for_equal_or_older_semantic_versions(self):
        for version in ('0.7.0', '0.6.99'):
            self.manifest['version'] = version
            self.updates.check()
            self.assertEqual(self.finished()['state'], 'current')
            with self.assertRaises(ValueError):
                self.updates.download()
        self.assertGreater(version_tuple('0.10.0'), version_tuple('0.9.9'))

    def test_invalid_or_wrong_product_manifest_is_rejected(self):
        for key, value in [('application', 'other'), ('version', '0.8.0/bad'), ('notes', 'x'*1201)]:
            raw = dict(self.manifest, **{key: value})
            with self.assertRaises(ValueError):
                validate_manifest(raw)
        for key, value in [('size', True), ('size', 256*1024*1024+1), ('filename', '../app.exe'), ('sha256', 'x'*64)]:
            raw = dict(self.manifest, installer=dict(self.manifest['installer'], **{key: value}))
            with self.assertRaises(ValueError):
                validate_manifest(raw)

    def test_offline_and_redirect_leave_application_running(self):
        self.updates.opener = lambda _: (_ for _ in ()).throw(OSError('offline'))
        self.updates.check()
        self.assertEqual(self.finished()['state'], 'error')
        self.assertFalse(self.stop.is_set())
        with self.assertRaises(ValueError):
            NoRedirect().redirect_request(None, None, 302, '', {}, 'http://elsewhere/app.exe')

    def test_download_checks_hash_size_and_reuses_only_verified_installer(self):
        self.ready()
        self.assertEqual((self.directory/'Denghuo-Setup.exe').read_bytes(), self.binary)
        count = len(self.requests)
        self.updates.download()
        self.assertEqual(self.finished()['state'], 'ready')
        self.assertEqual(len(self.requests), count)
        self.assertEqual([p.name for p in self.directory.iterdir()], ['Denghuo-Setup.exe'])

    def test_tampered_download_preserves_previous_valid_cache(self):
        self.ready()
        original = (self.directory/'Denghuo-Setup.exe').read_bytes()
        self.manifest['version'] = '0.9.0'
        self.manifest['installer']['sha256'] = '0'*64
        self.updates.check()
        self.finished()
        self.updates.download()
        self.assertEqual(self.finished()['state'], 'error')
        self.assertEqual((self.directory/'Denghuo-Setup.exe').read_bytes(), original)
        self.assertFalse((self.directory/'Denghuo-Setup.part').exists())

    def test_cancel_download_removes_partial_and_keeps_app_running(self):
        self.updates.check()
        self.finished()
        entered, release = threading.Event(), threading.Event()
        class Slow(io.BytesIO):
            def read1(stream, count):
                entered.set()
                self.assertTrue(release.wait(3))
                return super().read1(count)
        self.updates.opener = lambda _: Slow(self.binary)
        self.updates.download()
        self.assertTrue(entered.wait(3))
        self.updates.cancel_download()
        release.set()
        self.assertEqual(self.finished()['state'], 'available')
        self.assertFalse(self.stop.is_set())
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_cancelled_install_never_launches_on_later_normal_exit(self):
        self.ready()
        self.updates.install(lambda: {'id': 'update-exit', 'phase': 'confirming'})
        self.finished()
        self.assertEqual(self.updates.snapshot({'id':'update-exit', 'phase':'cancelled'})['state'], 'ready')
        with patch('companion.updates.subprocess.Popen') as launch:
            self.assertFalse(self.updates.launch_after_exit({'id':'normal-exit', 'phase':'finished'}))
            launch.assert_not_called()

    def test_install_requires_exact_finished_exit_and_rechecks_bytes(self):
        self.ready()
        self.updates.install(lambda: {'id': 'update-exit', 'phase': 'confirming'})
        self.finished()
        with patch('companion.updates.subprocess.Popen') as launch:
            self.assertFalse(self.updates.launch_after_exit({'id':'update-exit','phase':'confirming'}))
            self.assertTrue(self.updates.launch_after_exit({'id':'update-exit','phase':'finished'}))
            args = launch.call_args.args[0]
            self.assertEqual(args[0], str(self.directory/'Denghuo-Setup.exe'))
            self.assertIn('/NORESTART', args)
            self.assertFalse(any(arg.startswith('/SILENT') for arg in args))
        self.updates._set(state='ready')
        (self.directory/'Denghuo-Setup.exe').write_bytes(b'MZchanged')
        self.updates.install(lambda: self.fail('must not request exit with changed installer'))
        self.assertEqual(self.finished()['state'], 'error')

    def test_source_run_cannot_launch_installer(self):
        self.ready()
        self.updates.can_install = False
        with self.assertRaises(ValueError):
            self.updates.install(lambda: {})

    def test_check_and_download_are_single_flight(self):
        release = threading.Event()
        original = self.updates.opener
        self.updates.opener = lambda name: (release.wait(3), original(name))[1]
        first = self.updates.check()
        second = self.updates.check()
        self.assertEqual(first['state'], second['state'])
        release.set()
        self.finished()
        self.assertEqual(self.requests, ['latest.json'])


class UpdatePublishingTests(unittest.TestCase):
    def test_manifest_matches_installer_bytes_and_version(self):
        from tools.publish_update import manifest_for
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory)/'denghuo-setup-0.8.0.exe'
            binary.write_bytes(b'MZ-test-installer')
            result = manifest_for(binary, '0.8.0', 'New release')
            self.assertEqual(result['installer']['size'], binary.stat().st_size)
            self.assertEqual(result['installer']['sha256'], hashlib.sha256(binary.read_bytes()).hexdigest())
            self.assertEqual(validate_manifest(result)['version'], '0.8.0')

    def test_ssh_sends_lf_bytes_and_preserves_host_verification(self):
        from tools.publish_update import ssh
        with patch('tools.publish_update.subprocess.run') as run:
            run.return_value.stdout=b'{}'
            self.assertEqual(ssh('known-alias', 'set -eu\r\nprintf ok\n'), '{}')
            self.assertEqual(run.call_args.kwargs['input'], b'set -eu\nprintf ok\n')
            self.assertIn('StrictHostKeyChecking=yes', run.call_args.args[0])

    def test_wrong_instance_stops_before_upload_or_filesystem_changes(self):
        from tools.publish_update import publish
        with patch('tools.publish_update.ssh', return_value='{"instanceId":"i-00000000"}') as probe, patch('tools.publish_update.subprocess.run') as upload:
            with self.assertRaises(ValueError):
                publish('unused.exe', {}, 'known-alias', 'i-11111111')
            self.assertEqual(probe.call_count, 1)
            upload.assert_not_called()


class UpdateHTTPTests(unittest.TestCase):
    def test_static_script_and_protected_actions_are_wired(self):
        from companion.service import Session
        from companion.server import Server
        with tempfile.TemporaryDirectory() as directory:
            session = Session(Path(directory)/'settings.json')
            server = Server(session)
            worker = threading.Thread(target=server.serve_forever)
            worker.start()
            try:
                with urlopen(server.origin+'/updates.js', timeout=3) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn(b'function renderUpdate', response.read())
                payload = json.dumps({'action':'check'}).encode()
                for headers in ({}, {'X-Companion-Token':server.token,'Origin':'https://elsewhere.invalid'}):
                    with self.assertRaises(HTTPError) as error:
                        urlopen(Request(server.origin+'/api/update', data=payload, headers=headers), timeout=3)
                    self.assertEqual(error.exception.code, 403)
                with patch.object(session.updates, 'check', return_value={'state':'checking'}) as check:
                    request = Request(server.origin+'/api/update', data=payload,
                                      headers={'X-Companion-Token':server.token,'Content-Type':'application/json'})
                    with urlopen(request, timeout=3) as response:
                        self.assertEqual(json.load(response)['update']['state'], 'checking')
                    check.assert_called_once_with()
            finally:
                session.stop.set()
                server.shutdown()
                server.server_close()
                worker.join(3)


if __name__ == '__main__':
    unittest.main()
