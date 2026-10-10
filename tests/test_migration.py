import gzip
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zipfile import ZipFile

from companion import migration
from companion.backups import BackupManager
from companion.server import Server
from companion.service import Session


class MigrationTests(unittest.TestCase):
    def setUp(self):
        # Preserve synthetic originals for review; no real profile is consulted.
        self.base = Path(tempfile.mkdtemp(prefix='denghuo-migration-test-'))
        self.source = self.session('source')
        self.target = self.session('target')
        self.capture(self.source, 5, 1)
        self.capture(self.source, 12, 2)
        self.plan = self.source.knowledge.save('保命方案', 'manual', None,
            {'class': 'MAGE', 'hp': 5, 'ht': 30, 'level': 2, 'strength': 10, 'depth': 2,
             'branch': 0, 'healing': 1, 'hunger': None, 'buffs': [], 'challenges': 0}, note='回档前核对')
        self.favorite = self.source.catalog.entries[0]['id']
        self.source.knowledge.favorite(self.favorite, True)
        self.source.play_preferences.update({'font_scale': 1.3, 'alerts': False, 'offset_x': 321})
        self.capture(self.target, 22, 1)
        self.original_game = self.game_bytes(self.target)

    def session(self, name):
        profile, root = self.base / name / 'profile', self.base / name / 'saves'
        profile.mkdir(parents=True); root.mkdir()
        session = Session(config_path=profile / 'settings.json')
        session.update_settings({'save_root': str(root), 'slot': 1})
        session.backups = BackupManager(profile / 'backups', clock=lambda: 1700010000, closed_check=lambda: None)
        return session

    def capture(self, session, hp, slot):
        folder = Path(session.settings['save_root']) / f'game{slot}'
        folder.mkdir(exist_ok=True)
        game = {'depth': 2, 'version': 920, 'seed': slot, 'generated_levels': [2],
                'hero': {'class': 'MAGE', 'HP': hp, 'HT': 30, 'STR': 10, 'lvl': 2, 'inventory': [], 'buffs': []}}
        level = {'__className': 'com.shatteredpixel.shatteredpixeldungeon.levels.SewerLevel', 'version': 920,
                 'width': 4, 'height': 4, 'map': [4]*16, 'visited': [False]*16, 'mapped': [False]*16}
        for name, data in [('game.dat', game), ('depth2.dat', {'level': level})]:
            path = folder / name
            path.write_bytes(gzip.compress(json.dumps(data).encode(), mtime=0))
            os.utime(path, (1700000000 + slot, 1700000000 + slot))
        return session.backups.capture(session.settings['save_root'], slot)

    def game_bytes(self, session):
        root = Path(session.settings['save_root'])
        return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob('*') if path.is_file()}

    def bundle(self, selected=None):
        selected = selected if selected is not None else [row['key'] for row in migration.status(self.source)['rows'] if row['valid']]
        preview = migration.export_preview(self.source, {'selected': selected})
        raw, _ = migration.export_bundle(self.source, {'selected': selected, 'expected': preview['expected']})
        return raw

    def apply(self, raw, selected=None):
        preview = migration.import_preview(self.target, raw)
        selected = selected if selected is not None else [row['key'] for row in preview['rows'] if row['valid']]
        return migration.import_bundle(self.target, raw, {'selected': selected, 'expected': preview['expected'], 'confirmed': True})

    def rewrite(self, raw, change):
        with ZipFile(BytesIO(raw)) as archive:
            contents = {name: archive.read(name) for name in archive.namelist()}
        manifest = migration.read_json(contents[migration.INDEX])
        change(contents, manifest)
        for name in list(manifest['members']):
            manifest['members'][name] = {'bytes': len(contents[name]), 'sha256': migration.checksum(contents[name])}
        contents[migration.INDEX] = migration.encode(manifest)
        return migration._zip(contents)

    def test_independent_categories_import_without_reading_damaged_knowledge(self):
        draft = self.source.exit_drafts.save('web-12345678', 'workspace', '待继续', {'raw': '-'})
        backup = next(row['key'] for row in migration.status(self.source)['rows'] if row['group'] == 'backup')
        packages = [(key, self.bundle([key])) for key in ('preference:font_scale', backup, 'draft:' + draft['id'])]
        original = b'{"plans": damaged original'
        self.target.knowledge.path.write_bytes(original)
        for key, raw in packages:
            with self.subTest(category=key):
                preview = migration.import_preview(self.target, raw)
                self.assertTrue(all(row['valid'] for row in preview['rows']))
                result = self.apply(raw)
                self.assertEqual((result['success_count'], result['failure_count']), (1, 0))
                self.assertEqual(self.target.knowledge.path.read_bytes(), original)
                self.assertEqual(self.game_bytes(self.target), self.original_game)
        self.assertEqual(self.target.play_preferences.values['font_scale'], 1.3)
        self.assertEqual(self.target.exit_drafts.list()[0]['draft_kind'], 'workspace')

    def test_mixed_bundle_isolates_bad_knowledge_and_rechecks_recovery(self):
        raw = self.bundle(['plan:' + self.plan['id'], 'favorite:' + self.favorite, 'preference:font_scale'])
        original = b'{"plans": damaged mixed original'
        self.target.knowledge.path.write_bytes(original)
        preview = migration.import_preview(self.target, raw)
        knowledge = [row for row in preview['rows'] if row['group'] in ('plan', 'favorite')]
        self.assertEqual(len(knowledge), 2)
        self.assertTrue(all(not row['valid'] and '无法读取' in row['error'] for row in knowledge))
        payload = {'selected': ['plan:' + self.plan['id']], 'expected': preview['expected'], 'confirmed': True}
        result = migration.import_bundle(self.target, raw, payload)
        self.assertEqual((result['success_count'], result['failure_count']), (0, 1))
        self.assertIn('无法读取', result['results'][0]['error'])
        result = migration.import_bundle(self.target, raw, {**payload,
            'selected': [row['key'] for row in preview['rows']]})
        self.assertEqual((result['success_count'], result['failure_count']), (1, 2))
        self.assertEqual(self.target.play_preferences.values['font_scale'], 1.3)
        self.assertEqual(self.target.knowledge.path.read_bytes(), original)
        # Recovery of the category changes the preview guard; no stale confirmation.
        preview = migration.import_preview(self.target, raw)
        self.target.knowledge.path.write_text('{"format":1,"plans":[],"favorites":[],"recent":[]}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '重新预览'):
            migration.import_bundle(self.target, raw, {**payload, 'expected': preview['expected'], 'selected': ['preference:font_scale']})
        fresh = migration.import_preview(self.target, raw)
        self.assertTrue(all(row['valid'] for row in fresh['rows']))
        self.assertEqual(self.game_bytes(self.target), self.original_game)

    def test_unavailable_backup_stub_does_not_block_other_migration_categories(self):
        root = self.source.settings['save_root']
        records = self.source.backups.history(root)
        damaged = records[0]
        archive = self.source.backups.scope(root) / (damaged['id'] + '.zip')
        archive.write_bytes(b'damaged synthetic ZIP')
        self.source.backups.validate(root)
        view = migration.status(self.source)
        row = next(row for row in view['rows'] if row['key'] == f"backup:{damaged['slot']}:{damaged['id']}")
        self.assertFalse(row['valid'])
        self.assertTrue(row['error'])
        with self.assertRaises(ValueError):
            migration.export_preview(self.source, {'selected': [row['key']]})
        # A recovered timeline observation has no verified level.
        from companion.backups import atomic_json
        damaged.pop('level', None)
        damaged['repair_error'] = 'ZIP缺失，原时间记录仍保留'
        atomic_json(self.source.backups.scope(root) / 'history.json', records)
        view = migration.status(self.source)
        self.assertFalse(next(row for row in view['rows'] if row['key'].endswith(damaged['id']))['valid'])
        healthy = next(row['key'] for row in view['rows'] if row['group'] == 'backup' and row['valid'])
        self.assertTrue(migration.export_preview(self.source, {'selected': [healthy, 'preference:font_scale']})['expected'])
        self.assertEqual(archive.read_bytes(), b'damaged synthetic ZIP')

    def test_over_200_preserved_drafts_do_not_block_preference_import(self):
        self.source.play_preferences.update({'enabled': False})
        identities = [self.target.exit_drafts.save('web-12345678', 'workspace', f'草稿{n}', {'raw': str(n)})['id']
                      for n in range(201)]
        originals = {identity: self.target.exit_drafts.load(identity) for identity in identities}
        raw = self.bundle(['preference:enabled'])
        preview = migration.import_preview(self.target, raw)
        # An unrelated new draft must not invalidate a preference-only preview.
        self.target.exit_drafts.save('web-87654321', 'workspace', '随后保存', {'raw': 'keep'})
        result = migration.import_bundle(self.target, raw, {'selected': ['preference:enabled'],
            'expected': preview['expected'], 'confirmed': True})
        self.assertEqual((result['success_count'], result['failure_count']), (1, 0))
        self.assertFalse(self.target.play_preferences.values['enabled'])
        self.assertEqual(len(self.target.exit_drafts.list()), 202)
        self.assertEqual({identity: self.target.exit_drafts.load(identity) for identity in identities}, originals)
        self.assertEqual(self.game_bytes(self.target), self.original_game)

    def test_draft_batch_limit_is_independent_of_lifetime_count_and_still_checks_cas(self):
        from companion.session_exit import checked_draft_set
        existing = [self.target.exit_drafts.save('web-12345678', 'workspace', f'草稿{n}', {'raw': str(n)})['id']
                    for n in range(201)]
        before = self.target.exit_drafts.stamp()
        incoming = self.source.exit_drafts.save('web-87654321', 'workspace', '待迁移', {'raw': 'unchanged'})['id']
        raw = self.bundle(['draft:' + incoming])
        result = self.apply(raw)
        self.assertEqual((result['success_count'], result['failure_count']), (1, 0))
        self.assertEqual(self.target.exit_drafts.load(incoming), self.source.exit_drafts.load(incoming))
        self.assertEqual({name: digest for name, digest in self.target.exit_drafts.stamp().items() if name in before}, before)
        preview = migration.import_preview(self.target, raw)
        self.target.exit_drafts.save('web-87654321', 'workspace', '并发编辑', {'raw': 'keep'})
        with self.assertRaisesRegex(ValueError, '变化'):
            migration.import_bundle(self.target, raw, {'selected': ['draft:' + incoming],
                'expected': preview['expected'], 'confirmed': True})
        # Portable batches retain their explicit 200-record bound.
        with self.assertRaises(ValueError):
            self.target.exit_drafts.export_records(existing)
        with self.assertRaises(ValueError):
            checked_draft_set({'format': 1, 'kind': 'denghuo-exit-draft-set',
                               'records': [self.target.exit_drafts.load(identity) for identity in existing]})
        self.assertEqual(self.game_bytes(self.target), self.original_game)

    def test_saved_raw_drafts_select_preview_redact_import_and_preserve_conflict_without_applying(self):
        raw_form = {'format': 1, 'numeric': {'hp': '不是数字', 'level': '-', 'custom': '  原始空白  '},
                    'open_plan': {'name': '原名称', 'note': 'C:\\private\\save token=SECRET Authorization: Bearer AUTH'},
                    'character': {'strength': '尚未确认'}}
        saved = self.source.exit_drafts.save('web-12345678', 'workspace', '原始退出草稿', raw_form)
        identity = saved['id']; source_path = self.source.exit_drafts.directory / (identity + '.json')
        source_raw = source_path.read_bytes(); source_record = self.source.exit_drafts.load(identity)
        target_path = self.target.exit_drafts.directory / (identity + '.json')
        target_path.parent.mkdir(); local_record = {**source_record, 'draft': {'local': '本机未完成输入'}}
        target_path.write_bytes(migration.encode(local_record)); local_raw = target_path.read_bytes()
        raw = self.bundle(['draft:' + identity])
        with ZipFile(BytesIO(raw)) as archive:
            self.assertEqual(set(archive.namelist()), {migration.INDEX, 'exit-drafts.json'})
            portable = migration.read_json(archive.read('exit-drafts.json'))['records'][0]
            self.assertEqual(portable['draft']['numeric'], raw_form['numeric'])
            self.assertNotIn('SECRET', archive.read('exit-drafts.json').decode())
            self.assertNotIn('AUTH', portable['draft']['open_plan']['note'])
            self.assertNotIn('C:\\private', portable['draft']['open_plan']['note'])
        with patch('companion.migration.canonical_plan', side_effect=AssertionError('must not calculate raw forms')):
            preview = migration.import_preview(self.target, raw)
            self.assertIn('保留双方', preview['rows'][0]['detail'])
            self.assertEqual(preview['rows'][0]['content'], portable)
            result = self.apply(raw)
        self.assertEqual(result['success_count'], 1); self.assertFalse(result['restored'])
        self.assertFalse(result['results'][0]['calculated']); self.assertFalse(result['results'][0]['applied'])
        self.assertEqual(len(self.target.exit_drafts.list()), 2)
        self.assertEqual(target_path.read_bytes(), local_raw); self.assertEqual(source_path.read_bytes(), source_raw)
        self.assertEqual(self.game_bytes(self.target), self.original_game); self.assertIsNone(self.target.data)
        repeated = self.apply(raw); self.assertEqual(len(self.target.exit_drafts.list()), 2)
        self.assertEqual(repeated['results'][0]['id'], result['results'][0]['id'])
        source_state = self.source.exit_drafts.lifecycle(identity)
        self.source.exit_drafts.set_lifecycle(identity, 'archived', source_state['state_revision'])
        archived_package = self.bundle(['draft:' + identity])
        archived_import = self.apply(archived_package)
        self.assertEqual(archived_import['results'][0]['id'], result['results'][0]['id'])
        self.assertEqual(len(self.target.exit_drafts.list(include_archived=True)), 2)
        self.assertEqual(target_path.read_bytes(), local_raw)

    def test_draft_import_rejects_stale_target_secrets_structure_and_excess_count(self):
        saved = self.source.exit_drafts.save('web-12345678', 'workspace', '原始草稿', {'raw': '无效数值'})
        raw = self.bundle(['draft:' + saved['id']]); preview = migration.import_preview(self.target, raw)
        self.target.exit_drafts.save('web-87654321', 'workspace', '新增本机草稿', {'raw': '本机'})
        with self.assertRaisesRegex(ValueError, '已变化'):
            migration.import_bundle(self.target, raw, {'selected': ['draft:' + saved['id']], 'expected': preview['expected'], 'confirmed': True})
        for change in ('secret', 'depth', 'count', 'size', 'format'):
            def mutate(contents, manifest):
                value = migration.read_json(contents['exit-drafts.json'])
                if change == 'secret': value['records'][0]['draft']['access_token'] = 'forbidden'
                if change == 'depth':
                    nested = {}; value['records'][0]['draft'] = nested
                    for _ in range(22): nested['nested'] = {}; nested = nested['nested']
                if change == 'count': value['records'] *= 201
                if change == 'size':
                    from companion.session_exit import MAX_DRAFT
                    value['records'][0]['draft']['raw'] = 'x' * MAX_DRAFT
                if change == 'format': value['records'][0]['format'] = 900
                contents['exit-drafts.json'] = migration.encode(value)
            with self.subTest(change=change), self.assertRaises(ValueError):
                migration.import_preview(self.target, self.rewrite(raw, mutate))
        self.assertEqual(len(self.target.exit_drafts.list()), 1)
        self.assertEqual(self.game_bytes(self.target), self.original_game)

    def test_archived_draft_migrates_with_stable_id_and_explicit_restore_only(self):
        saved = self.source.exit_drafts.save('web-12345678', 'web-session', '已完成的原始草稿', {'raw': {'hp': '9'}})
        identity = saved['id']; original = Path(saved['path']).read_bytes()
        row = self.source.exit_drafts.list()[0]
        self.source.exit_drafts.set_lifecycle(identity, 'archived', row['state_revision'])
        status = migration.status(self.source)
        self.assertIn('已归档', next(item for item in status['rows'] if item['key'] == 'draft:'+identity)['detail'])
        raw = self.bundle(['draft:'+identity]); result = self.apply(raw)
        self.assertEqual(result['success_count'], 1); self.assertEqual(result['results'][0]['id'], identity)
        self.assertEqual(self.target.exit_drafts.list(), [])
        target = Session(self.target.config_path, self.target.catalog)
        archived = target.exit_drafts.list(include_archived=True)[0]
        self.assertEqual((archived['id'], archived['state']), (identity, 'archived'))
        target.exit_drafts.set_lifecycle(identity, 'active', archived['state_revision'])
        self.assertEqual(target.exit_drafts.list()[0]['id'], identity)
        self.assertEqual(target.exit_drafts.load(identity)['draft'], {'raw': {'hp': '9'}})
        self.assertEqual(Path(saved['path']).read_bytes(), original)
        self.assertEqual(self.game_bytes(self.target), self.original_game)

    def test_saved_character_conditions_migrate_as_reusable_plan(self):
        from companion.character_scene import empty_scene
        plan = self.source.knowledge.save('共享角色条件', 'character', None, empty_scene(13),
            source={'kind': 'saved_reference', 'mode': 'manual', 'fields': {'base_strength': '明确手填'}})
        raw = self.bundle(['plan:' + plan['id']]); preview = migration.import_preview(self.target, raw)
        self.assertEqual(preview['rows'][0]['content']['kind'], 'character')
        self.assertTrue(preview['rows'][0]['available'])
        self.assertEqual(self.apply(raw)['success_count'], 1)
        imported = self.target.knowledge.reopen(plan['id'])
        self.assertEqual(imported['result']['strength']['effective'], 13)
        self.assertEqual(imported['plan']['origin']['fields']['base_strength'], '明确手填')

    def test_full_bundle_preview_partial_then_full_no_live_saves_or_old_root(self):
        raw = self.bundle()
        with ZipFile(BytesIO(raw)) as archive:
            for name in archive.namelist():
                self.assertNotIn(self.source.settings['save_root'].encode(), archive.read(name))
            preferences = migration.read_json(archive.read('preferences.json'))
            self.assertNotIn('anchor', preferences)
            self.assertNotIn('offset_x', preferences)
        before = self.game_bytes(self.source)
        preview = migration.import_preview(self.target, raw)
        self.assertEqual(preview['save_root'], self.target.settings['save_root'])
        self.assertIn('profile', preview['rows'][0]['target'])
        selected = [row['key'] for row in preview['rows'] if row['group'] == 'plan']
        result = migration.import_bundle(self.target, raw, {'selected': selected, 'expected': preview['expected'], 'confirmed': True})
        self.assertEqual(result['success_count'], 1)
        self.assertEqual(len(self.target.backups.history(self.target.settings['save_root'])), 1)
        result = self.apply(raw)
        self.assertEqual(result['failure_count'], 0)
        self.assertFalse(result['restored'])
        self.assertEqual(self.target.play_preferences.values['font_scale'], 1.3)
        self.assertEqual(self.target.play_preferences.values['offset_x'], 16)
        self.assertEqual(len(self.target.backups.history(self.target.settings['save_root'])), 3)
        self.assertEqual(before, self.game_bytes(self.source))
        self.assertEqual(self.original_game, self.game_bytes(self.target))
        self.assertFalse(result['preferences_runtime']['desktop_available'])

    def test_conflict_copies_are_visible_and_reimport_does_not_duplicate(self):
        raw = self.bundle(['plan:' + self.plan['id']])
        value, stamp = self.target.knowledge._read()
        incoming = {key: value for key, value in self.plan.items() if key != 'record_revision'}
        incoming['note'] = '本机独有备注'
        value['plans'].append(incoming)
        self.target.knowledge._write(value, stamp)
        preview = migration.import_preview(self.target, raw)
        self.assertIn('保留双方', preview['rows'][0]['detail'])
        self.apply(raw)
        self.apply(raw)
        plans = self.target.knowledge.status()['plans']
        self.assertEqual(len(plans), 2)
        self.assertEqual(next(row for row in plans if row['id'] == self.plan['id'])['note'], '本机独有备注')

    def test_edited_import_copy_is_preserved_and_original_can_be_reimported_once(self):
        raw = self.bundle(['plan:' + self.plan['id']])
        store = self.target.knowledge
        value, stamp = store._read()
        local = {key: item for key, item in self.plan.items() if key != 'record_revision'}
        local['note'] = '本机独有备注'
        value['plans'].append(local)
        store._write(value, stamp)
        self.apply(raw)
        copied = next(row for row in store.status()['plans'] if row['id'] != self.plan['id'])
        copied = store.reopen(copied['id'])['plan']
        edited = store.save(copied['name'], copied['kind'], copied['entry'], copied['params'], copied['origin'],
            record_id=copied['id'], expected_record_revision=copied['record_revision'], note='继续修改的导入副本')
        try:
            preview = migration.import_preview(self.target, raw)
        except ValueError as exc:
            self.fail('编辑导入副本后仍应允许预览并保留双方：' + str(exc))
        self.assertIn('保留双方', preview['rows'][0]['detail'])
        result = self.apply(raw)
        self.assertEqual((result['success_count'], result['failure_count']), (1, 0))
        self.assertEqual(store.reopen(edited['id'])['plan'], edited)
        self.assertEqual(next(row for row in store._read()[0]['plans'] if row['id'] == self.plan['id']), local)
        prior = store.path.read_bytes()
        self.assertIn('不再重复', migration.import_preview(self.target, raw)['rows'][0]['detail'])
        self.apply(raw)
        self.assertEqual(store.path.read_bytes(), prior)
        self.assertEqual(len(store.status()['plans']), 3)
        self.assertEqual(self.game_bytes(self.target), self.original_game)

    def test_legacy_json_and_zip_conflict_retries_recognize_each_others_copies(self):
        raw = self.bundle(['plan:' + self.plan['id']])
        shared = json.loads(self.source.knowledge.export())
        shared['favorites'] = []  # Match the plan-only ZIP selection.
        shared = json.dumps(shared, ensure_ascii=False).encode('utf-8')
        for first in ('json', 'zip'):
            with self.subTest(first=first):
                self.target = self.session('target-' + first)
                store = self.target.knowledge
                value, stamp = store._read()
                local = {key: item for key, item in self.plan.items() if key != 'record_revision'}
                local['note'] = '本机独有备注'
                value['plans'].append(local)
                store._write(value, stamp)
                if first == 'json':
                    store.import_records(shared)
                else:
                    self.apply(raw)
                before = store.path.read_bytes()
                if first == 'json':
                    self.apply(raw)
                else:
                    receipt = store.import_records(shared)
                    self.assertEqual((receipt['plans_added'], receipt.get('plans_skipped', -1)), (0, 1))
                self.assertEqual(store.path.read_bytes(), before)
                self.assertEqual(len(store.status()['plans']), 2)

    def test_export_cas_preview_cancel_empty_and_target_rebinding_are_checked(self):
        selected = ['preference:font_scale']
        preview = migration.export_preview(self.source, {'selected': selected})
        self.source.play_preferences.update({'font_scale': 1.5})
        with self.assertRaisesRegex(ValueError, '重新预览'):
            migration.export_bundle(self.source, {'selected': selected, 'expected': preview['expected']})
        raw = self.bundle()
        preview = migration.import_preview(self.target, raw)
        with self.assertRaisesRegex(ValueError, '尚未应用'):
            migration.import_bundle(self.target, raw, {'expected': preview['expected'], 'selected': [], 'confirmed': False})
        with self.assertRaisesRegex(ValueError, '没有选择'):
            migration.import_bundle(self.target, raw, {'expected': preview['expected'], 'selected': [], 'confirmed': True})
        new_root = self.base / 'target' / 'other-saves'; new_root.mkdir()
        self.target.update_settings({'save_root': str(new_root)})
        with self.assertRaisesRegex(ValueError, '重新预览'):
            migration.import_bundle(self.target, raw, {'expected': preview['expected'], 'selected': [preview['rows'][0]['key']], 'confirmed': True})

    def test_export_observation_ticks_keep_original_preview_and_real_change_guards(self):
        selected = [row['key'] for row in migration.status(self.source)['rows'] if row['valid']]
        preview = migration.export_preview(self.source, {'selected': selected})
        root = self.source.settings['save_root']
        observations = {row['id']: row['last_seen'] for row in self.source.backups.history(root)}
        original_game = self.game_bytes(self.source)
        self.source.backups.clock = lambda: 1700010012
        self.source.backups.tick(root, force=True)
        fresh = migration.export_preview(self.source, {'selected': selected})
        self.assertNotEqual(preview['expected'], fresh['expected'])
        raw, _ = migration.export_bundle(self.source,
            {'selected': selected, 'expected': preview['expected']})
        self.assertEqual(migration.checksum(raw), preview['expected'])
        with ZipFile(BytesIO(raw)) as archive:
            with ZipFile(BytesIO(archive.read('backups.zip'))) as backups:
                index = json.loads(backups.read('denghuo-transfer.json'))
                for row in index['entries']:
                    self.assertEqual(row['last_observed'], observations[row['id']])
        self.assertEqual(self.game_bytes(self.source), original_game)
        migration.export_bundle(self.source, {'selected': selected, 'expected': fresh['expected']})
        record = self.source.backups.history(root)[0]
        self.source.backups.manage(root, {'slot': record['slot'], 'id': record['id'],
            'locked': True, 'expected_metadata_revision': record['metadata_revision']})
        with self.assertRaisesRegex(ValueError, '重新预览'):
            migration.export_bundle(self.source, {'selected': selected, 'expected': preview['expected']})

    def test_export_previews_remain_independent_and_expire_with_bounded_history(self):
        selected = ['preference:font_scale']
        previews = []
        for scale in range(33):
            self.source.play_preferences.update({'font_scale': 1 + scale / 100})
            previews.append(migration.export_preview(self.source, {'selected': selected}))
        with self.assertRaisesRegex(ValueError, '预览已过期'):
            migration.export_bundle(self.source, {'selected': selected, 'expected': previews[0]['expected']})
        raw, _ = migration.export_bundle(self.source,
            {'selected': selected, 'expected': previews[-1]['expected']})
        self.assertEqual(migration.checksum(raw), previews[-1]['expected'])
        for invalid in (None, {}, [], 'invalid'):
            with self.subTest(expected=invalid), self.assertRaises(ValueError):
                migration.export_bundle(self.source, {'selected': selected, 'expected': invalid})

    def test_knowledge_or_disk_preference_update_after_preview_rejected(self):
        raw = self.bundle()
        for action in ('knowledge', 'preferences'):
            preview = migration.import_preview(self.target, raw)
            if action == 'knowledge':
                self.target.knowledge.favorite(self.favorite, True)
            else:
                self.target.play_preferences.path.write_text(json.dumps({'font_scale': 1.9}))
            with self.assertRaisesRegex(ValueError, '重新预览'):
                migration.import_bundle(self.target, raw, {'expected': preview['expected'], 'selected': [row['key'] for row in preview['rows']], 'confirmed': True})
        self.assertEqual(len(self.target.knowledge.status()['plans']), 0)

    def test_ordinary_backup_ticks_do_not_invalidate_migration_with_or_without_archives(self):
        for selected in (['preference:font_scale', 'plan:' + self.plan['id']], None):
            with self.subTest(archives=selected is None):
                now = [1700010000]
                self.target.backups.clock = lambda: now[0]
                self.target.backups.tick(self.target.settings['save_root'], force=True)
                raw = self.bundle(selected)
                preview = migration.import_preview(self.target, raw)
                before = migration._backup_guard(self.target)
                for _ in range(3):
                    now[0] += 11
                    self.target.backups.tick(self.target.settings['save_root'])
                self.assertEqual(migration._backup_guard(self.target), before)
                result = migration.import_bundle(self.target, raw, {'selected': [r['key'] for r in preview['rows']],
                    'expected': preview['expected'], 'confirmed': True})
                self.assertEqual(result['failure_count'], 0)
                self.assertEqual(self.game_bytes(self.target), self.original_game)

    def test_archive_import_rejects_real_target_content_protection_and_relationship_changes(self):
        raw = self.bundle()
        scope = self.target.backups.scope(self.target.settings['save_root'])
        for change in ('label', 'lock', 'generation', 'first_observed', 'zip', 'restore'):
            with self.subTest(change=change):
                preview = migration.import_preview(self.target, raw)
                if change in ('label', 'lock', 'generation', 'first_observed'):
                    path = scope / 'history.json'
                    original = path.read_bytes(); rows = json.loads(original)
                    rows[0][{'label': 'label', 'lock': 'locked', 'generation': 'metadata_generation', 'first_observed': 'time'}[change]] = {
                        'label': '新名称', 'lock': True, 'generation': 'a' * 32, 'first_observed': rows[0]['time'] - 1}[change]
                    path.write_bytes(migration.encode(rows))
                elif change == 'zip':
                    path = next(scope.glob('*.zip')); original = path.read_bytes()
                    path.write_bytes(original + b'changed')
                else:
                    path = scope / 'restores.json'; original = path.read_bytes() if path.exists() else None
                    path.write_bytes(b'[]')
                try:
                    with self.assertRaisesRegex(ValueError, '重新预览'):
                        migration.import_bundle(self.target, raw, {'selected': [r['key'] for r in preview['rows']],
                            'expected': preview['expected'], 'confirmed': True})
                finally:
                    if original is None: path.unlink()
                    else: path.write_bytes(original)

    def test_preference_only_import_ignores_unrelated_archive_changes_but_keeps_preferences_cas(self):
        raw = self.bundle(['preference:font_scale'])
        preview = migration.import_preview(self.target, raw)
        self.capture(self.target, 19, 1)
        result = migration.import_bundle(self.target, raw, {'selected': ['preference:font_scale'],
            'expected': preview['expected'], 'confirmed': True})
        self.assertEqual(result['success_count'], 1)
        preview = migration.import_preview(self.target, raw)
        self.target.play_preferences.update({'font_scale': 1.7})
        with self.assertRaisesRegex(ValueError, '重新预览'):
            migration.import_bundle(self.target, raw, {'selected': ['preference:font_scale'],
                'expected': preview['expected'], 'confirmed': True})

    def test_out_of_process_source_preferences_are_not_exported_from_stale_memory(self):
        self.source.play_preferences.path.write_text(json.dumps({'font_scale': 1.8}))
        view = migration.status(self.source)
        self.assertIn('其他进程', view['preferences_error'])
        self.assertTrue(all(not row['valid'] for row in view['rows'] if row['group'] == 'preference'))
        with self.assertRaises(ValueError):
            migration.export_preview(self.source, {'selected': ['preference:font_scale']})

    def test_disk_failure_reports_partial_progress_and_preserves_originals(self):
        raw = self.bundle()
        preview = migration.import_preview(self.target, raw)
        with patch.object(self.target.play_preferences, 'update', side_effect=OSError('synthetic disk denied')):
            result = migration.import_bundle(self.target, raw, {'expected': preview['expected'], 'selected': [row['key'] for row in preview['rows']], 'confirmed': True})
        self.assertGreater(result['success_count'], 0)
        self.assertEqual(result['failure_count'], 6)
        self.assertTrue(all(not row['saved'] for row in result['results'] if row['key'].startswith('preference:')))
        self.assertEqual(self.original_game, self.game_bytes(self.target))
        self.assertEqual(self.target.play_preferences.values['font_scale'], 1)

    def test_unavailable_version_retained_as_reference_and_invalid_fields_rejected(self):
        raw = self.bundle(['plan:' + self.plan['id']])
        def old_version(contents, manifest):
            manifest['source']['application_version'] = '0.1.0'
            value = migration.read_json(contents['knowledge.json'])
            value['plans'][0]['rules_version'] = '0.1.0'
            contents['knowledge.json'] = migration.encode(value)
        raw = self.rewrite(raw, old_version)
        with patch('companion.migration.canonical_plan', side_effect=ValueError('本版条目不可用')):
            preview = migration.import_preview(self.target, raw)
            self.assertTrue(preview['version_difference'])
            self.assertFalse(preview['rows'][0]['available'])
            self.assertIn('旧版本参考', preview['rows'][0]['error'])
        self.apply(raw)
        self.assertEqual(self.target.knowledge.status()['plans'][0]['rules_version'], '0.1.0')
        raw = self.bundle(['preference:bindings'])
        for invalid in ({'offset_x': 200}, {'font_scale': 100}, {'bindings': {'show': 'Ctrl+F9', 'capture': 'Ctrl+F9'}}):
            def change(contents, manifest): contents['preferences.json'] = migration.encode(invalid)
            with self.assertRaises(ValueError): migration.import_preview(self.target, self.rewrite(raw, change))

    def test_archive_rules_hash_duplicate_path_and_format_are_not_relaxed(self):
        raw = self.bundle(['preference:font_scale'])
        with ZipFile(BytesIO(raw)) as archive:
            contents = {name: archive.read(name) for name in archive.namelist()}
        bad = dict(contents); bad['../escape'] = b'x'
        with self.assertRaises(ValueError): migration.import_preview(self.target, migration._zip(bad))
        contents['preferences.json'] = b'{"font_scale":1.2}'
        with self.assertRaisesRegex(ValueError, '校验失败|实际文件不一致'): migration.import_preview(self.target, migration._zip(contents))
        def future(contents, manifest): manifest['format'] = 2
        with self.assertRaisesRegex(ValueError, '不支持'): migration.import_preview(self.target, self.rewrite(raw, future))

    def test_portable_notes_redact_machine_paths_and_marked_secrets(self):
        self.source.knowledge.save('C:\\Users\\private\\plan', 'manual', None, self.plan['params'], note='path /home/private/save token=private-token')
        raw = self.bundle()
        with ZipFile(BytesIO(raw)) as archive:
            knowledge = archive.read('knowledge.json')
        for secret in (b'C:\\', b'/home/private', b'private-token'):
            self.assertNotIn(secret, knowledge)

    def test_one_unavailable_inner_backup_does_not_fake_full_success(self):
        raw = self.bundle()
        def damage(contents, manifest):
            with ZipFile(BytesIO(contents['backups.zip'])) as archive:
                members = {name: archive.read(name) for name in archive.namelist()}
            index = migration.read_json(members['denghuo-transfer.json'])
            broken = index['entries'][0]
            members[broken['file']] = b'not a valid backup ZIP'
            broken.update(bytes=len(members[broken['file']]), sha256=migration.checksum(members[broken['file']]))
            members['denghuo-transfer.json'] = migration.encode(index)
            contents['backups.zip'] = migration._zip(members)
        raw = self.rewrite(raw, damage)
        preview = migration.import_preview(self.target, raw)
        unavailable = [row for row in preview['rows'] if not row['valid']]
        self.assertEqual(len(unavailable), 1)
        self.assertTrue(unavailable[0]['error'])
        result = migration.import_bundle(self.target, raw, {'expected': preview['expected'], 'selected': [row['key'] for row in preview['rows']], 'confirmed': True})
        self.assertEqual(result['failure_count'], 1)
        self.assertGreater(result['success_count'], 0)
        self.assertEqual(self.original_game, self.game_bytes(self.target))

    def test_deadline_cancel_is_consumed_and_new_deadline_can_trigger(self):
        self.target.report_exit_surface('web-' + 'a'*32, 1, True, draft={'message': 'keep'})
        self.target.settings['stop_at'] = '2001-01-01T00:00:00+08:00'
        self.target.refresh()
        state = self.target.exit_status()
        self.target.acknowledge_exit(state['id'], 'web-' + 'a'*32, 'cancel', 1)
        for _ in range(3): self.target.refresh()
        self.assertEqual(self.target.exit_status()['phase'], 'cancelled')
        self.assertEqual(self.target.exit_status()['id'], state['id'])
        self.assertFalse(self.target.stop.is_set())
        self.target.settings['stop_at'] = '2002-01-01T00:00:00+08:00'
        self.target.refresh()
        self.assertNotEqual(self.target.exit_status()['id'], state['id'])

    def test_real_http_guard_export_preview_import_and_utf8(self):
        server = Server(self.target)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            with urlopen(server.origin + '/api/migration') as response:
                self.assertIn('rows', json.load(response))
            raw = self.bundle(['plan:' + self.plan['id'], 'preference:font_scale'])
            headers = {'Content-Type': 'application/zip', 'X-Companion-Token': server.token}
            with self.assertRaises(HTTPError) as failure:
                urlopen(Request(server.origin + '/api/migration/preview', data=raw, headers={'Content-Type': 'application/zip'}))
            self.assertEqual(failure.exception.code, 403)
            for extras in ({'Origin': 'http://example.invalid'}, {'Host': 'example.invalid'}):
                with self.assertRaises(HTTPError) as failure:
                    urlopen(Request(server.origin + '/api/migration/preview', data=raw, headers={**headers, **extras}))
                self.assertEqual(failure.exception.code, 403)
            with urlopen(Request(server.origin + '/api/migration/preview', data=raw, headers=headers)) as response:
                preview = json.load(response)
            headers.update({'X-Companion-Migration-Digest': preview['expected'], 'X-Companion-Migration-Selection': json.dumps([row['key'] for row in preview['rows']]), 'X-Companion-Migration-Confirmed': 'true'})
            with urlopen(Request(server.origin + '/api/migration/import', data=raw, headers=headers)) as response:
                result = json.load(response)
            self.assertEqual(result['success_count'], 2)
            self.assertEqual(self.original_game, self.game_bytes(self.target))
        finally:
            server.shutdown(); server.server_close(); thread.join(3)


if __name__ == '__main__':
    unittest.main()
