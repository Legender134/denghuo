"""Automatic install migration carries the existing external-media identity."""
import json
import unittest

from companion.backup_destination import MARKER, REGISTRY
from companion.paths import migrate_data
from companion.service import Session
import test_backup_destination as fixtures


class ExternalDestinationMigrationTests(unittest.TestCase):
    setUp = fixtures.BackupDestinationTests.setUp
    write_save = fixtures.BackupDestinationTests.write_save
    capture = fixtures.BackupDestinationTests.capture
    request = fixtures.BackupDestinationTests.request
    preview = fixtures.BackupDestinationTests.preview
    switch = fixtures.BackupDestinationTests.switch

    def migrate(self, before_migration=None):
        self.capture()
        self.switch()
        before = self.config.parent/REGISTRY
        original = before.read_bytes()
        if before_migration:
            before_migration()
        destination = self.base/'new-assistant'
        report = migrate_data(destination, [self.config.parent])
        restarted = Session(destination/'settings.json')
        self.assertIn(REGISTRY, report['copied_preferences'])
        self.assertEqual((destination/REGISTRY).read_bytes(), original)
        self.assertEqual(before.read_bytes(), original)
        self.assertEqual(restarted.settings['backup_root'], str(self.target))
        return restarted

    def test_healthy_external_destination_and_history_survive_new_install(self):
        restarted = self.migrate()
        self.assertTrue(restarted.backup_destination_status()['available'])
        self.assertEqual(len(restarted.backup_status()['history']), 1)
        restarted.backups.clock = lambda: self.now+50
        self.write_save(19)
        self.assertIsNotNone(restarted.backups.capture(self.saves, 1))

    def test_offline_media_stays_unavailable_and_originals_remain(self):
        retained = self.base/'offline-original'
        restarted = self.migrate(lambda: self.target.rename(retained))
        self.assertFalse(restarted.backup_destination_status()['available'])
        self.assertFalse(self.target.exists())
        self.assertTrue((retained/MARKER).is_file())
        self.assertTrue((restarted.config_path.parent/REGISTRY).is_file())

    def test_different_media_identity_is_rejected_after_migration(self):
        marker = self.target/MARKER
        restarted = self.migrate(lambda: marker.write_text(
            json.dumps({'format': 1, 'id': 'f'*32}), encoding='utf-8'))
        self.assertFalse(restarted.backup_destination_status()['available'])
        with self.assertRaises(ValueError):
            restarted.backups.capture(self.saves, 1)

    def test_invalid_and_oversize_registry_stop_migration_preserving_original(self):
        for raw in (b'{broken', b'{"root":"not-an-id"}', b'x'*65537):
            with self.subTest(size=len(raw)):
                self.switch()
                record = self.config.parent/REGISTRY
                record.write_bytes(raw)
                destination = self.base/('rejected-'+str(len(raw)))
                with self.assertRaisesRegex(ValueError, '身份记录无法核对'):
                    migrate_data(destination, [self.config.parent])
                self.assertEqual(record.read_bytes(), raw)
                self.assertFalse(destination.exists())
                # A fresh setup is independent of the corrupt source kept above.
                if raw != b'x'*65537:
                    self.setUp()
