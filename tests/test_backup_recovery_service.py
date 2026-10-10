"""Recovery API binds explicit choices to the current connection and preview."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from companion import backup_recovery
from companion.server import Server
from companion.service import Session
import test_backup_recovery as fixtures


class InterruptedSwap(BaseException):
    pass


class BackupRecoveryServiceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='denghuo-recovery-api-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root, _, _ = fixtures.setup_case(self.base, 'restore')
        self.session = Session(self.base/'settings.json')
        self.session.backups.closed_check = lambda: None
        self.session.backups.clock = lambda: 1800000100
        row = self.session.backups.history(self.root)[0]
        preview = self.session.backups.preview(self.root, row)
        count = 0
        original = backup_recovery._move
        def cut(source, target):
            nonlocal count
            original(source, target)
            count += 1
            if count == 2:
                raise InterruptedSwap()
        with patch.object(backup_recovery, '_move', cut), self.assertRaises(InterruptedSwap):
            self.session.backup_action({**row, 'action': 'restore', 'context': self.session.backup_context,
                'confirm': '恢复槽位 1', 'expected_current': preview['expected_current']})
        self.pending = self.session.backup_status()['recovery']['pending'][0]

    def payload(self, action, **extra):
        return {'action': action, 'context': self.session.backup_context,
                'expected_settings_revision': self.session.settings_revision,
                'id': self.pending['id'], 'slot': 1, **extra}

    def test_status_and_explicit_execute_survive_missing_stage_and_commit_once(self):
        before = fixtures.contents(self.root/'game1')
        view = self.session.backup_action(self.payload('recovery_preview'))
        self.assertEqual(view['preview']['layout'], 'target')
        self.assertEqual(view['context'], self.session.backup_context)
        self.assertEqual(view['settings_revision'], self.session.settings_revision)
        choice = next(c for c in view['preview']['choices'] if c['choice'] == 'continue')
        request = self.payload('recovery_execute', choice='continue', expected=view['preview']['expected'],
            confirmed=True, confirm=choice['confirm_phrase'])
        with self.assertRaises(ValueError):
            self.session.backup_action({**request, 'confirmed': False})
        self.assertEqual(fixtures.contents(self.root/'game1'), before)
        result = self.session.backup_action(request)
        self.assertTrue(result['recovery']['journal_committed'])
        self.assertEqual(self.session.backup_status()['recovery']['pending'], [])
        self.assertEqual(len(self.session.backups.journals(self.root)), 1)
        with self.assertRaises(ValueError):
            self.session.backup_action(request)
        self.assertEqual(len(self.session.backups.journals(self.root)), 1)

    def test_changed_settings_or_connection_refuse_preview_and_execution(self):
        payload = self.payload('recovery_preview')
        for field in ('context', 'expected_settings_revision'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.session.backup_action({**payload, field: 'old-generation'})
        view = self.session.backup_action(payload)['preview']
        request = self.payload('recovery_execute', choice='cancel', expected=view['expected'], confirmed=True,
            confirm=next(c['confirm_phrase'] for c in view['choices'] if c['choice'] == 'cancel'))
        self.session.update_settings({'always_on_top': not self.session.settings['always_on_top']})
        with self.assertRaises(ValueError):
            self.session.backup_action(request)
        self.assertEqual(len(self.session.backup_status()['recovery']['pending']), 1)

    def test_http_requires_existing_token_origin_and_bound_preview(self):
        server = Server(self.session)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            def request(headers):
                body = json.dumps(self.payload('recovery_preview')).encode()
                with urlopen(Request(server.origin+'/api/backups', data=body, headers=headers), timeout=5) as response:
                    return json.load(response)
            valid = {'Content-Type': 'application/json', 'X-Companion-Token': server.token, 'Origin': server.origin}
            invalid_headers = [{key: value for key, value in valid.items() if key != 'X-Companion-Token'},
                               {**valid, 'Origin': 'https://unrelated.invalid'}]
            for headers in invalid_headers:
                with self.subTest(headers=headers), self.assertRaises(HTTPError):
                    request(headers)
            result = request(valid)
            self.assertEqual(result['preview']['id'], self.pending['id'])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)
