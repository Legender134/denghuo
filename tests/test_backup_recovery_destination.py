"""Pending exchange metadata stays protected across explicit destination copies."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid

from companion import backup_destination as destinations
from companion import backup_recovery as recovery
from companion.backups import BackupLibrary, atomic_json
from test_backup_recovery import manager, setup_case


class BackupRecoveryDestinationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='denghuo-recovery-destination-')
        self.addCleanup(temporary.cleanup)
        self.case = Path(temporary.name).resolve()
        self.root, _, _ = setup_case(self.case / 'source', 'restore')
        self.m = manager(self.case / 'source')
        self.context = SimpleNamespace(config_path=self.case / 'source' / 'settings.json', backups=self.m,
            settings={'save_root': str(self.root)}, settings_revision='frozen-revision',
            backup_context='frozen-context', backup_enabled=self.m.enabled)
        self.target = self.case / 'destination'
        self.target.mkdir()

    def pending(self):
        with patch.object(recovery, 'run', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.m.restore(self.root, {**self.m.history(self.root)[0], 'confirm': '恢复槽位 1'})

    def test_pending_index_is_copied_and_verified_without_reading_the_save_root(self):
        self.pending()
        view = destinations.plan(self.context, str(self.target))[0]
        committed = []
        destinations.apply(self.context, str(self.target), view['expected'],
                           lambda root, m: committed.append(m))
        reference = BackupLibrary(self.m.scope(self.root).name)
        copied = committed[0]
        self.assertEqual(recovery.records(copied, reference), recovery.records(self.m, self.root))
        with patch.object(recovery, 'tree', side_effect=AssertionError('offline verification cannot open save root')):
            self.assertEqual(destinations._verify(self.target, destinations._tree(self.target)), 1)

    def test_conflicting_pending_same_slot_refuses_union_and_preserves_both_indexes(self):
        self.pending()
        rows = recovery.records(self.m, self.root)
        destination_scope = self.target / 'backups' / self.m.scope(self.root).name
        destination_scope.mkdir(parents=True)
        different = json.loads(json.dumps(rows))
        different['1']['id'] = uuid.uuid4().hex
        different['1']['change']['id'] = different['1']['id']
        atomic_json(destination_scope / recovery.INDEX, {'format': 1, 'operations': different})
        before = (destination_scope / recovery.INDEX).read_bytes()
        with self.assertRaisesRegex(ValueError, '另一条未完成'):
            destinations.plan(self.context, str(self.target))
        self.assertEqual((destination_scope / recovery.INDEX).read_bytes(), before)
        self.assertEqual(recovery.records(self.m, self.root), rows)

    def test_all_check_current_failure_points_roll_back_containers_before_configuration_commit(self):
        for fail_at in (1, 2, 3):
            with self.subTest(fail_at=fail_at):
                target = self.target / str(fail_at)
                (target / 'backups').mkdir(parents=True)
                atomic_json(target / 'backups' / 'preferences.json', {'enabled': False})
                original = destinations._tree(target)
                source = destinations._tree(self.context.config_path.parent)
                view = destinations.plan(self.context, str(target))[0]
                calls = []
                def check():
                    calls.append(1)
                    if len(calls) == fail_at:
                        raise ValueError('settings changed or shutdown started')
                persist = Mock()
                with self.assertRaisesRegex(ValueError, 'shutdown'):
                    destinations.apply(self.context, str(target), view['expected'], persist, check_current=check)
                persist.assert_not_called()
                # Rename changes directory stamps, but every original file byte remains.
                self.assertEqual({k: v['sha256'] for k, v in destinations._tree(target)['files'].items()},
                                 {k: v['sha256'] for k, v in original['files'].items()})
                self.assertEqual(destinations._tree(self.context.config_path.parent), source)

    def test_frozen_enabled_projection_is_used_at_copy_and_configuration_commit(self):
        self.context.backup_enabled = False
        view = destinations.plan(self.context, str(self.target))[0]
        self.m.enabled = True
        committed = []
        destinations.apply(self.context, str(self.target), view['expected'], lambda _, m: committed.append(m))
        self.assertFalse(committed[0].enabled)
        self.assertEqual(json.loads((self.target / 'backups' / 'preferences.json').read_text()), {'enabled': False})


if __name__ == '__main__':
    unittest.main()
