"""Session boundaries for first-run exit and newly connected data workflows."""
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from companion import backup_workflows as flows
from companion.engine import Catalog
from companion.service import DEFAULTS, Session


class ServiceR8WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='lamp-r8-service-')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.root = self.directory / 'default-saves'
        self.config = self.directory / 'profile' / 'settings.json'
        patched = patch.dict(DEFAULTS, {'save_root': str(self.root)})
        patched.start()
        self.addCleanup(patched.stop)

    def session(self):
        return Session(self.config, self.catalog)

    def write_save(self):
        folder = self.root / 'game1'
        folder.mkdir(parents=True)
        game = {'depth': 2, 'version': 922, 'generated_levels': [2], 'seed': 9,
                'hero': {'class': 'MAGE', 'HP': 20, 'HT': 40, 'STR': 10, 'lvl': 2,
                         'inventory': [], 'buffs': []}}
        (folder / 'game.dat').write_bytes(gzip.compress(json.dumps(game).encode()))

    def test_first_missing_default_wait_exits_cleanly_and_next_launch_has_no_failure(self):
        session = self.session()
        session.refresh()
        self.assertTrue(session.waiting_for_save)
        result = session.prepare_shutdown(timeout=1)
        self.assertEqual((result['ok'], result['state']), (True, 'no-save'))
        self.assertFalse(self.root.exists())
        self.assertTrue(json.loads((self.config.parent / 'last-exit.json').read_text())['backup']['ok'])
        resumed = self.session()
        self.assertNotIn('备份未完成', resumed.configuration_notice)
        self.assertIsNone(resumed.data)

    def test_custom_missing_folder_and_unrepaired_configuration_remain_real_failures(self):
        session = self.session()
        session.settings['save_root'] = str(self.directory / 'custom-missing')
        session.refresh()
        self.assertFalse(session.waiting_for_save)
        self.assertIn('暂时不可用', session.error)
        self.assertFalse(session.prepare_shutdown(timeout=1)['ok'])
        self.assertIn('备份未完成', self.session().configuration_notice)
        second = Session(self.directory / 'other-profile' / 'settings.json', self.catalog)
        second.config_error = '设置尚未修复'
        self.assertEqual(second.prepare_shutdown(timeout=1)['state'], 'configuration-error')

    def test_observed_progress_survives_mode_resets_when_default_later_disappears(self):
        self.write_save()
        session = self.session()
        session.refresh()
        self.assertEqual(session.active_slot, 1)
        session.update_settings({'mode': 'manual'})
        session.update_settings({'mode': 'save'})
        # Keep the user's original bytes; simulate an offline/moved directory.
        self.root.rename(self.directory / 'temporarily-offline')
        session.active_slot = None
        session.refresh()
        self.assertFalse(session.waiting_for_save)
        self.assertIn('暂时不可用', session.error)
        self.assertFalse(session.prepare_shutdown(timeout=1)['ok'])

    def test_protected_prior_progress_prevents_new_user_skip_in_a_fresh_session(self):
        session = self.session()
        scope = session.backups.scope(self.root)
        scope.mkdir(parents=True, exist_ok=True)
        preserved = scope / 'preserved.zip'
        preserved.write_bytes(b'original protected object remains unchanged')
        session.refresh()
        self.assertFalse(session.waiting_for_save)
        self.assertFalse(session.prepare_shutdown(timeout=1)['ok'])
        self.assertEqual(preserved.read_bytes(), b'original protected object remains unchanged')

    def test_stage_routes_bind_context_and_preserve_confirmation_payload(self):
        session = self.session()
        routes = [('stage-inspect', 'inspect_stage'), ('stage-preview', 'stage_preview'),
                  ('stage-retry', 'retry_stage')]
        for action, name in routes:
            payload = {'file': '.denghuo-stage-1-123-1234abcd', 'context': session.backup_context,
                       'expected': 'original-preview', 'confirmed': True, 'confirm': 'explicit phrase'}
            with self.subTest(action=action), patch.object(flows, name, return_value={'verified': True}) as route:
                result = session.backup_workflow(action, payload)
                route.assert_called_once_with(session.backups, session.settings['save_root'], payload)
                self.assertEqual(result['context'], session.backup_context)
                with self.assertRaises(ValueError):
                    session.backup_workflow(action, {**payload, 'context': 'old-profile'})
                self.assertEqual(route.call_count, 1)

    def test_incompatible_migrated_drafts_are_visible_without_applying_a_draft(self):
        self.config.parent.mkdir(parents=True)
        (self.config.parent / 'migration.json').write_text(json.dumps({
            'copied_exit_drafts': ['valid.json'], 'unavailable_exit_drafts': [{'file': 'old.json'}],
            'draft_notice': '保留原始副本'}), encoding='utf-8')
        session = self.session()
        self.assertIn('未计为可用迁移', session.configuration_notice)
        self.assertIn('原始副本', session.configuration_notice)
        self.assertIsNone(session.data)
        self.assertEqual(session.settings['mode'], 'save')


if __name__ == '__main__':
    unittest.main()
