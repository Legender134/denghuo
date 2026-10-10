"""Abrupt process death at every owned container exchange preserves discoverability."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from companion import backup_destination as destinations
from companion import backup_destination_recovery as recovery
from companion.backups import BackupManager
from companion.service import Session
from tests import test_backup_destination as fixtures


CRASHER = r'''
import os,sys
from pathlib import Path
from companion.service import Session
config,target,point = Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3]
session=Session(config)
def request(action,**extra):
    return dict(action=action,backup_root=str(target),expected_settings_revision=session.settings_revision,context=session.backup_context,**extra)
preview=session.backup_destination_action(request('preview'))
rename,replace=Path.rename,Path.replace
counter=[0]
def interrupted_rename(path,destination):
    result=rename(path,destination)
    if path.name in ('backups','backup-recycle','backup-quarantine') and (path.parent==target or path.parent.name.startswith('.denghuo-destination-stage-')):
        counter[0]+=1
        if point==str(counter[0]):os._exit(73)
    return result
def interrupted_replace(path,destination):
    result=replace(path,destination)
    if point=='config' and Path(destination)==config:os._exit(74)
    if point=='journal' and Path(destination)==config.parent/'backup-destination-pending.json':os._exit(75)
    return result
Path.rename,Path.replace=interrupted_rename,interrupted_replace
session.backup_destination_action(request('apply',expected=preview['expected'],confirmed=True))
raise AssertionError('requested crash boundary was not reached')
'''

RECOVERY_CRASHER = r'''
import os,sys
from pathlib import Path
from companion.service import Session
session=Session(Path(sys.argv[1]))
direction=sys.argv[2]
def request(action,**extra):
    return dict(action=action,expected_settings_revision=session.settings_revision,context=session.backup_context,**extra)
preview=session.backup_destination_action(request('recovery-preview'))
original=Path.rename
def interrupted(path,target):
    result=original(path,target)
    if path.name in ('backups','backup-recycle','backup-quarantine'):os._exit(76)
    return result
Path.rename=interrupted
session.backup_destination_action(request('recover',direction=direction,expected=preview['expected'],confirmed=True))
raise AssertionError('recovery exchange was not reached')
'''


class BackupDestinationRecoveryTests(unittest.TestCase):
    write_save = fixtures.BackupDestinationTests.write_save

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='lamp-destination-crash-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.sessions = []
        self.addCleanup(self.stop_sessions)

    def stop_sessions(self):
        for session in self.sessions:
            self.assertTrue(session.exit_coordinator.flush_checkpoints(5))
            session.stop.set()

    def new_session(self, config):
        session = Session(config)
        self.sessions.append(session)
        return session

    def scenario(self, label):
        base = self.base/label
        base.mkdir()
        self.saves, self.target = base/'synthetic-current-game', base/'target'
        self.saves.mkdir(); self.target.mkdir()
        self.config = base/'assistant'/'settings.json'
        self.config.parent.mkdir()
        self.config.write_text(json.dumps({'save_root': str(self.saves), 'slot': 1}), encoding='utf-8')
        session = self.new_session(self.config)
        self.write_save(20)
        source_row = session.backups.capture(self.saves, 1)
        previous = base/'synthetic-previous-game'
        self.write_save(13, previous)
        target_manager = BackupManager(self.target/'backups', clock=lambda: 1700000200, closed_check=lambda: None)
        target_row = target_manager.capture(previous, 1)
        for parent, key, marker in ((self.config.parent, session.backups.scope(self.saves).name, b'source'),
                                    (self.target, target_manager.scope(previous).name, b'target-original')):
            for container in ('backup-recycle', 'backup-quarantine'):
                folder = parent/container/key
                folder.mkdir(parents=True)
                (folder/'retained-original.bin').write_bytes(marker+b'-'+container.encode())
        self.source_content = recovery.content(destinations._tree(self.config.parent))
        self.original_content = recovery.content(destinations._tree(self.target))
        self.previous, self.source_row, self.target_row = previous, source_row, target_row
        return session

    def crash(self, point):
        roaming, local = self.config.parent/'synthetic-roaming', self.config.parent/'synthetic-local'
        roaming.mkdir(); local.mkdir()
        env = dict(os.environ, APPDATA=str(roaming), LOCALAPPDATA=str(local), PYTHONDONTWRITEBYTECODE='1')
        result = subprocess.run([sys.executable, '-B', '-c', CRASHER, str(self.config), str(self.target), str(point)],
            cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True, timeout=25)
        self.assertEqual(result.returncode, {'config': 74, 'journal': 75}.get(point, 73), result.stdout+result.stderr)
        return self.new_session(self.config)

    def request(self, session, action, **extra):
        return dict(action=action, expected_settings_revision=session.settings_revision, context=session.backup_context, **extra)

    def recover(self, session, direction):
        view = session.backup_destination_action(self.request(session, 'recovery-preview'))
        return session.backup_destination_action(self.request(session, 'recover', direction=direction,
            expected=view['expected'], confirmed=True))

    def test_every_exchange_and_config_replace_can_explicitly_continue_or_cancel(self):
        for point in ('journal', 1, 2, 3, 4, 5, 6, 'config'):
            for direction in ('continue', 'cancel'):
                with self.subTest(point=point, direction=direction):
                    self.scenario(f'{point}-{direction}')
                    session = self.crash(point)
                    status = session.backup_destination_status()
                    self.assertTrue(status['recovery']['can_continue'])
                    self.assertGreater(status['recovery']['target_original_bytes'], 0)
                    self.assertTrue(Path(status['recovery']['preserved_target_directory']).is_dir())
                    with self.assertRaisesRegex(ValueError, '未完成'):
                        session.backup_destination_action(self.request(session, 'preview', backup_root=str(self.target)))
                    if point == 'config':
                        self.assertFalse(status['available'])
                        self.assertIn('未完成', status['error'])
                    result = self.recover(session, direction)
                    self.assertTrue(result['ok'])
                    self.assertTrue(result['originals_retained'])
                    self.assertIsNone(session.backup_destination_status()['recovery'])
                    self.assertEqual(recovery.content(destinations._tree(self.config.parent)), self.source_content)
                    if direction == 'cancel':
                        self.assertEqual(session.settings['backup_root'], '')
                        self.assertEqual(recovery.content(destinations._tree(self.target)), self.original_content)
                    else:
                        self.assertEqual(session.settings['backup_root'], str(self.target))
                        self.assertEqual(session.backups.history(self.previous)[0]['id'], self.target_row['id'])
                        self.assertEqual(session.backups.history(self.saves)[0]['id'], self.source_row['id'])
                    restarted = self.new_session(self.config)
                    self.assertTrue(restarted.backup_destination_status()['available'])
                    self.assertIsNone(restarted.backup_destination_status()['recovery'])

    def test_new_source_history_requires_cancel_and_fresh_merge_preview(self):
        self.scenario('new-source')
        session = self.crash(1)
        self.write_save(18)
        newer = session.backups.capture(self.saves, 1)
        view = session.backup_destination_status()['recovery']
        self.assertFalse(view['can_continue'])
        with self.assertRaisesRegex(ValueError, '新备份'):
            session.backup_destination_action(self.request(session, 'recover', direction='continue',
                expected=view['expected'], confirmed=True))
        self.recover(session, 'cancel')
        view = session.backup_destination_action(self.request(session, 'preview', backup_root=str(self.target)))
        session.backup_destination_action(self.request(session, 'apply', backup_root=str(self.target),
            expected=view['expected'], confirmed=True))
        self.assertIn(newer['id'], {row['id'] for row in session.backups.history(self.saves)})
        self.assertEqual(session.backups.history(self.previous)[0]['id'], self.target_row['id'])

    def test_recovery_itself_can_be_interrupted_and_restarted_without_guessing(self):
        for direction, point in (('continue', 1), ('cancel', 6)):
            with self.subTest(direction=direction):
                self.scenario('recovery-death-'+direction)
                self.crash(point)
                env = dict(os.environ, APPDATA=str(self.config.parent/'synthetic-roaming'),
                           LOCALAPPDATA=str(self.config.parent/'synthetic-local'), PYTHONDONTWRITEBYTECODE='1')
                result = subprocess.run([sys.executable, '-B', '-c', RECOVERY_CRASHER, str(self.config), direction],
                    cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True, timeout=25)
                self.assertEqual(result.returncode, 76, result.stdout+result.stderr)
                session = self.new_session(self.config)
                status = session.backup_destination_status()
                self.assertEqual(status['recovery']['state'], 'continuing' if direction == 'continue' else 'cancelling')
                self.recover(session, direction)
                if direction == 'cancel':
                    self.assertEqual(recovery.content(destinations._tree(self.target)), self.original_content)
                else:
                    self.assertEqual(session.backups.history(self.previous)[0]['id'], self.target_row['id'])
                    self.assertEqual(session.backups.history(self.saves)[0]['id'], self.source_row['id'])

    def test_changed_retained_original_is_not_moved_or_silently_merged(self):
        self.scenario('changed-original')
        session = self.crash(1)
        view = session.backup_destination_status()['recovery']
        original = Path(view['preserved_target_directory'])/'backups'
        # Mutate an indexed ZIP without changing the recovery record.
        archive = next(original.glob('*/*.zip'))
        archive.write_bytes(b'controlled changed original bytes')
        before = fixtures.BackupDestinationTests.files(self.target)
        status = session.backup_destination_status()
        self.assertIsNone(status['recovery'])
        self.assertIn('字节', status['recovery_error'])
        for direction in ('continue', 'cancel'):
            with self.assertRaises(ValueError):
                session.backup_destination_action(self.request(session, 'recover', direction=direction,
                    expected=view['expected'], confirmed=True))
        self.assertEqual(fixtures.BackupDestinationTests.files(self.target), before)

    def test_unassociated_old_original_is_visible_as_a_conflict(self):
        session = self.scenario('unknown-original')
        folder = self.target/('.denghuo-destination-original-'+'a'*32)/'backups'
        folder.mkdir(parents=True)
        (folder/'unknown-original.bin').write_bytes(b'not automatically trusted')
        before = fixtures.BackupDestinationTests.files(self.target)
        with self.assertRaisesRegex(ValueError, '未关联'):
            session.backup_destination_action(self.request(session, 'preview', backup_root=str(self.target)))
        self.assertEqual(fixtures.BackupDestinationTests.files(self.target), before)


if __name__ == '__main__':
    unittest.main()
