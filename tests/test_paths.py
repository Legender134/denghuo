import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from companion.paths import data_directory, migrate_data


class DataPathTests(unittest.TestCase):
    def test_first_install_carries_healthy_generations_for_damaged_or_missing_default_library(self):
        from companion.service import DEFAULTS,Session
        for configured in (False,True):
            for missing in (False,True):
                with self.subTest(configured=configured,missing=missing),tempfile.TemporaryDirectory(prefix='denghuo-generation-migration-') as directory:
                    root=Path(directory);source=root/'old';source.mkdir();saves=root/'synthetic-saves';saves.mkdir()
                    if configured:
                        (source/'settings.json').write_text(json.dumps({'save_root':str(saves),'slot':'auto','mode':'save','reveal':False}),encoding='utf-8')
                    with patch.dict(DEFAULTS,{'save_root':str(saves)}):session=Session(source/'settings.json')
                    plan=session.knowledge.save('原始局势','manual',None,{'hp':3,'ht':30,'buffs':['Poison']})
                    session.knowledge.favorite('items.waterskin',True);session.knowledge.remember('actors.buffs.healing')
                    healthy=session.knowledge.path.read_bytes();identity=hashlib.sha256(healthy).hexdigest()
                    if missing:session.knowledge.path.replace(root/'held-original.json')
                    else:session.knowledge.path.write_bytes(healthy[:32])
                    unavailable=source/'knowledge-healthy'/('f'*64+'.json');unavailable.write_bytes(b'{unavailable original')
                    originals={path.relative_to(source):path.read_bytes() for path in source.rglob('*') if path.is_file()}
                    destination=root/'new';report=migrate_data(destination,[source])
                    self.assertEqual(sum(row['available'] for row in report['copied_knowledge_generations']),3)
                    self.assertEqual((destination/unavailable.relative_to(source)).read_bytes(),unavailable.read_bytes())
                    with patch.dict(DEFAULTS,{'save_root':str(saves)}):restarted=Session(destination/'settings.json')
                    self.assertFalse(restarted.knowledge.status()['available'])
                    self.assertEqual(restarted.knowledge.path.exists(),not missing)
                    for name,raw in originals.items():self.assertEqual((source/name).read_bytes(),raw)
                    preview=restarted.knowledge.repair_preview(identity)
                    receipt=restarted.knowledge.repair(preview['expected'],True,identity)
                    self.assertEqual(restarted.knowledge.reopen(plan['id'])['result']['hero']['hp'],3)
                    self.assertEqual(json.loads(restarted.knowledge.path.read_bytes()),json.loads(healthy))
                    self.assertEqual(receipt['primary_missing'],missing)
                    self.assertEqual(report['settings_copied'],configured)

    def migration_backup_fixture(self,root):
        from companion.backups import BackupManager
        source=root/'old';source.mkdir();saves=root/'synthetic-saves';saves.mkdir()
        (source/'settings.json').write_text(json.dumps({'save_root':str(saves),'slot':'auto','mode':'save','reveal':False}),encoding='utf-8')
        clock=[1700000000]
        manager=BackupManager(source/'backups',clock=lambda:clock[0],closed_check=lambda:None)
        def capture(hp):
            clock[0]+=120;folder=saves/'game1';folder.mkdir(exist_ok=True)
            game={'depth':2,'version':920,'seed':11,'generated_levels':[2],
                  'hero':{'class':'MAGE','HP':hp,'HT':30,'STR':10,'lvl':2,'inventory':[],'buffs':[]}}
            level={'__className':'com.shatteredpixel.shatteredpixeldungeon.levels.SewerLevel','version':920,
                   'width':4,'height':4,'map':[4]*16,'visited':[False]*16,'mapped':[False]*16}
            for name,value in (('game.dat',game),('depth2.dat',{'level':level})):
                path=folder/name;path.write_bytes(gzip.compress(json.dumps(value).encode(),mtime=0));os.utime(path,(clock[0],clock[0]))
            return manager.capture(saves,1)
        return source,saves,manager,capture

    def test_first_install_carries_retained_names_times_and_quarantine_originals(self):
        from companion.backups import BackupManager
        with tempfile.TemporaryDirectory(prefix='denghuo-retained-migration-') as directory:
            root=Path(directory);source,saves,manager,capture=self.migration_backup_fixture(root)
            first=capture(29);capture(28)
            named=next(row for row in manager.history(saves) if row['id']==first['id'])
            manager.manage(saves,{'slot':1,'id':first['id'],'label':'重要节点','expected_metadata_revision':named['metadata_revision']})
            manager.remove(saves,{'slot':1,'id':first['id'],'confirm':'移出备份 1'})
            retained,=manager.retained_status(saves)
            quarantine=source/'backup-quarantine'/manager.scope(saves).name/'original.zip'
            quarantine.parent.mkdir(parents=True);quarantine.write_bytes(b'bounded corrupt original')
            quarantine.with_suffix('.json').write_bytes(b'{bounded unavailable metadata')
            originals={path.relative_to(source):path.read_bytes() for path in source.rglob('*') if path.is_file()}
            destination=root/'new';report=migrate_data(destination,[source])
            self.assertEqual(report['copied_backup_containers'],['backup-quarantine','backup-recycle','backups'])
            migrated=BackupManager(destination/'backups',closed_check=lambda:None)
            self.assertEqual(migrated.retained_status(saves),[retained])
            for name,raw in originals.items():
                self.assertEqual((source/name).read_bytes(),raw)
                if name.parts[0] in ('backups','backup-recycle','backup-quarantine'):self.assertEqual((destination/name).read_bytes(),raw)

    def test_first_install_preserves_and_validates_pending_retention_as_one_unit(self):
        from companion.backups import BackupManager
        from companion import backup_workflows as flows
        class Crash(BaseException):pass
        for absent in (False,True):
            with self.subTest(absent=absent),tempfile.TemporaryDirectory(prefix='denghuo-pending-retention-migration-') as directory:
                root=Path(directory);source,saves,manager,capture=self.migration_backup_fixture(root)
                for hp in (29,28,27,26):capture(hp)
                preview=flows.automatic_preview(manager,saves)
                flows.automatic_save(manager,saves,{'expected_policy':preview['policy']['expected'],'expected':preview['expected'],'confirmed':True},enabled=True)
                replace=Path.replace
                def interrupted(path,target):
                    result=replace(path,target)
                    if path.suffix=='.zip' and Path(target).parent.parent.name=='backup-recycle':raise Crash()
                    return result
                with patch.object(flows,'AUTOMATIC_KEEP',1),patch('companion.backups.MAX_HISTORY',4),patch.object(Path,'replace',interrupted):
                    with self.assertRaises(Crash):capture(25)
                pending=manager.scope(saves)/'automatic-retention-pending.json'
                self.assertTrue(pending.exists())
                retained,=(source/'backup-recycle').rglob('*.zip')
                if absent:retained.replace(root/'held-retained.zip')
                originals={path.relative_to(source):path.read_bytes() for path in source.rglob('*') if path.is_file()}
                destination=root/'new'
                if absent:
                    with self.assertRaises(FileNotFoundError):migrate_data(destination,[source])
                    self.assertFalse(destination.exists())
                else:
                    report=migrate_data(destination,[source])
                    self.assertEqual(report['verified_pending_retention'],[pending.relative_to(source).as_posix()])
                    migrated=BackupManager(destination/'backups',closed_check=lambda:None)
                    self.assertIsNotNone(flows.automatic_recovery_plan(migrated,saves))
                    self.assertFalse(flows.automatic_status(migrated,saves)['enabled'])
                    self.assertIsNotNone(migrated.capture(saves,1))
                    self.assertFalse((migrated.scope(saves)/pending.name).exists())
                for name,raw in originals.items():self.assertEqual((source/name).read_bytes(),raw)

    def test_first_install_refuses_primary_reappearance_and_combined_retained_capacity(self):
        from companion.paths import _migration_size
        from companion.service import Session
        for race in (True,False):
            with self.subTest(race=race),tempfile.TemporaryDirectory(prefix='denghuo-migration-boundary-') as directory:
                root=Path(directory);source,saves,manager,capture=self.migration_backup_fixture(root)
                session=Session(source/'settings.json');session.knowledge.favorite('items.waterskin',True)
                healthy=session.knowledge.path.read_bytes();session.knowledge.path.replace(root/'held-primary.json')
                copy=shutil.copy2
                def competing(previous,target):
                    result=copy(previous,target)
                    if Path(previous).parent.name=='knowledge-healthy':session.knowledge.path.write_bytes(healthy)
                    return result
                destination=root/'new'
                if race:
                    with patch('companion.paths.shutil.copy2',side_effect=competing):
                        with self.assertRaisesRegex(ValueError,'已变化'):migrate_data(destination,[source])
                    self.assertEqual(session.knowledge.path.read_bytes(),healthy)
                else:
                    first=capture(29);capture(28);manager.remove(saves,{'slot':1,'id':first['id'],'confirm':'移出备份 1'})
                    def bounded(path,maximum):
                        actual=_migration_size(path,maximum)
                        return 600*1024*1024 if Path(path).parent.parent.name=='backup-recycle' else actual
                    with patch('companion.paths._migration_size',side_effect=bounded):
                        with self.assertRaisesRegex(ValueError,'合计超过'):migrate_data(destination,[source])
                self.assertFalse(destination.exists())

    def test_default_session_without_settings_migrates_favorites_and_both_draft_kinds(self):
        from companion.service import Session
        with tempfile.TemporaryDirectory(prefix='denghuo-default-data-migration-') as directory:
            root = Path(directory); source = root/'old'
            session = Session(source/'settings.json')
            session.knowledge.favorite('actors.buffs.healing', True)
            saved = session.save_exit_draft('web-12345678', 'workspace', '原始输入', {'raw': '未计算'})
            session.report_exit_surface('web-12345678', 1, True, draft={'raw': '  -unfinished\t'},
                                        kind='web', label='自动原始输入')
            originals = {str(path.relative_to(source)): path.read_bytes()
                         for path in source.rglob('*') if path.is_file()}
            self.assertFalse(session.config_path.exists())
            destination = root/'new'; report = migrate_data(destination, [source])
            restarted = Session(destination/'settings.json')
            self.assertFalse(restarted.config_path.exists())
            self.assertFalse(report['settings_copied'])
            self.assertEqual(report['source_recognition'], 'verified-data')
            self.assertEqual(restarted.knowledge._read()[0]['favorites'], ['actors.buffs.healing'])
            self.assertEqual(restarted.load_exit_draft(saved['id'])['draft'], {'raw': '未计算'})
            recovery, = [row for row in restarted.list_exit_drafts() if row.get('recovery')]
            self.assertEqual(restarted.load_exit_draft(recovery['id'])['draft'], {'raw': '  -unfinished\t'})
            self.assertEqual(len(report['copied_exit_recovery']), 1)
            self.assertEqual(report['unavailable_exit_recovery'], [])
            self.assertIsNone(restarted.data)
            self.assertEqual({name: (source/name).read_bytes() for name in originals}, originals)
            self.assertEqual({name: (destination/name).read_bytes() for name in originals if name != 'exit-recovery/.lock'},
                             {name: raw for name, raw in originals.items() if name != 'exit-recovery/.lock'})

    def test_default_session_backup_only_without_settings_is_recognised_by_verified_archive(self):
        from companion.saves import default_root
        from companion.service import Session
        with tempfile.TemporaryDirectory(prefix='denghuo-default-backup-migration-') as directory:
            root = Path(directory)
            with patch.dict(os.environ, {'APPDATA': str(root/'appdata')}):
                saves = default_root(); folder = saves/'game1'; folder.mkdir(parents=True)
                game = {'depth': 2, 'branch': 0, 'version': 912, 'seed': 9, 'generated_levels': [2],
                        'hero': {'class': 'MAGE', 'HP': 20, 'HT': 30, 'STR': 10, 'lvl': 2,
                                 'inventory': [], 'buffs': []}}
                level = {'__className': 'com.shatteredpixel.shatteredpixeldungeon.levels.SewerLevel',
                         'version': 912, 'width': 4, 'height': 4, 'map': [4]*16,
                         'visited': [False]*16, 'mapped': [False]*16}
                (folder/'game.dat').write_bytes(gzip.compress(json.dumps(game).encode(), mtime=0))
                (folder/'depth2.dat').write_bytes(gzip.compress(json.dumps({'level': level}).encode(), mtime=0))
                with patch.dict('companion.service.DEFAULTS', {'save_root': str(saves)}):
                    source = root/'old'; session = Session(source/'settings.json'); session.refresh()
                    session.backups.tick(saves, force=True)
                    self.assertEqual(session.active_slot, 1)
                    archive, = (source/'backups').rglob('*.zip')
                    original = archive.read_bytes()
                    self.assertFalse(session.config_path.exists())
                    destination = root/'new'; report = migrate_data(destination, [source])
                    restarted = Session(destination/'settings.json')
                    row, = restarted.backups.history(saves)
                    restarted.backups.checked_archive(saves, row['id'], row['slot'])
                    self.assertEqual(report['source_recognition'], 'verified-data')
                    self.assertFalse(report['settings_copied'])
                    self.assertFalse(restarted.config_path.exists())
                    self.assertEqual((destination/archive.relative_to(source)).read_bytes(), original)
                    self.assertEqual(archive.read_bytes(), original)

    def test_recovery_pending_only_without_settings_keeps_valid_and_unverified_originals(self):
        from companion.service import Session
        from companion.session_exit import ExitDraftStore, ExitRecoveryJournal
        for kind in ('valid', 'truncated', 'empty'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(prefix='denghuo-pending-only-migration-') as directory:
                root = Path(directory); source = root/'old'
                journal = ExitRecoveryJournal(source/'exit-recovery', ExitDraftStore(source/'exit-drafts'))
                if kind == 'valid':
                    journal.checkpoint('web-12345678', 1, True, {'raw': '未完成'}, 'workspace', '中断输入')
                    committed, = journal.directory.glob('*.json')
                    pending = committed.with_name(committed.name+'.pending'); committed.rename(pending)
                else:
                    journal.directory.mkdir(parents=True)
                    pending = journal.directory/('a'*32+'.json.pending')
                    pending.write_bytes(b'{"format":1,"kind":"denghuo-recovery' if kind == 'truncated' else b'')
                original = pending.read_bytes()
                destination = root/'new'; report = migrate_data(destination, [source])
                row, = Session(destination/'settings.json').list_exit_drafts()
                self.assertTrue(row['pending'])
                self.assertEqual(pending.read_bytes(), original)
                self.assertEqual((destination/'exit-recovery'/pending.name).read_bytes(), original)
                self.assertFalse((destination/'settings.json').exists())
                if kind == 'valid':
                    self.assertEqual(report['copied_exit_recovery'], [pending.name])
                    self.assertEqual(report['source_recognition'], 'verified-data')
                else:
                    self.assertEqual(report['copied_exit_recovery'], [])
                    self.assertEqual(report['source_recognition'], 'bounded-recovery-originals')
                    self.assertIn('error', row)
                    unavailable, = report['unavailable_exit_recovery']
                    self.assertEqual(unavailable['preserved_copy'], 'exit-recovery/'+pending.name)
                    self.assertEqual(unavailable['bytes'], len(original))
                    self.assertEqual(unavailable['sha256'], hashlib.sha256(original).hexdigest())

    def test_settings_recovery_migration_keeps_committed_and_pending_bytes_independently(self):
        from companion.service import Session
        with tempfile.TemporaryDirectory(prefix='denghuo-recovery-siblings-migration-') as directory:
            root = Path(directory); source = root/'old'; source.mkdir()
            (source/'settings.json').write_text(json.dumps({'save_root': str(root/'saves'),
                'slot': 'auto', 'mode': 'save', 'reveal': False}))
            session = Session(source/'settings.json')
            session.report_exit_surface('web-12345678', 1, True, draft={'raw': '完整原始输入'},
                                        kind='web', label='自动副本')
            self.assertTrue(session.exit_coordinator.flush_checkpoints(5), 'checkpoint did not complete')
            committed, = session.exit_recovery.directory.glob('*.json')
            pending = committed.with_name(committed.name+'.pending'); pending.write_bytes(b'{"format":900}')
            originals = {path.name: path.read_bytes() for path in (committed, pending)}
            destination = root/'new'; report = migrate_data(destination, [source])
            self.assertEqual(report['copied_exit_recovery'], [committed.name])
            self.assertEqual(report['unavailable_exit_recovery'][0]['file'], pending.name)
            self.assertEqual(len(Session(destination/'settings.json').list_exit_drafts()), 2)
            for name, raw in originals.items():
                self.assertEqual((destination/'exit-recovery'/name).read_bytes(), raw)
                self.assertEqual((source/'exit-recovery'/name).read_bytes(), raw)

    def test_preserved_recovery_pairs_and_bounded_orphans_keep_exact_original_bytes(self):
        from companion.session_exit import ExitDraftStore, ExitRecoveryJournal
        with tempfile.TemporaryDirectory(prefix='denghuo-preserved-recovery-migration-') as directory:
            root = Path(directory); source = root/'old'
            preserved = source/'exit-recovery-preserved'; preserved.mkdir(parents=True)
            identity = 'a'*32; raw = b'{"truncated original"\x00'
            metadata = {'format': 1, 'kind': 'denghuo-recovery-original', 'id': identity,
                        'source_name': 'f'*32+'.json.pending', 'saved': 10000,
                        'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
            (preserved/(identity+'.raw')).write_bytes(raw)
            (preserved/(identity+'.json')).write_text(json.dumps(metadata), encoding='utf-8')
            (preserved/('b'*32+'.raw')).write_bytes(b'bad paired original')
            (preserved/('b'*32+'.json')).write_bytes(b'{"format":900}')
            (preserved/('c'*32+'.raw')).write_bytes(b'')
            (preserved/('d'*32+'.json')).write_bytes(b'{"orphaned metadata":true}')
            originals = {path.name: path.read_bytes() for path in preserved.iterdir()}
            destination = root/'new'; report = migrate_data(destination, [source])
            copied = ExitRecoveryJournal(destination/'exit-recovery', ExitDraftStore(destination/'exit-drafts'))
            self.assertEqual(copied.read_preserved(identity), (metadata, raw))
            self.assertEqual(report['copied_preserved_recovery'], [identity])
            self.assertEqual(len(report['unavailable_preserved_recovery']), 4)
            self.assertFalse((destination/'settings.json').exists())
            for row in report['unavailable_preserved_recovery']:
                original = originals[row['file']]
                self.assertEqual((destination/row['preserved_copy']).read_bytes(), original)
                self.assertEqual(row['bytes'], len(original))
                self.assertEqual(row['sha256'], hashlib.sha256(original).hexdigest())
            self.assertEqual({path.name: path.read_bytes() for path in preserved.iterdir()}, originals)

    def test_preserved_recovery_orphan_only_without_settings_is_reported_as_raw_original(self):
        with tempfile.TemporaryDirectory(prefix='denghuo-preserved-only-migration-') as directory:
            root = Path(directory); source = root/'old'
            preserved = source/'exit-recovery-preserved'; preserved.mkdir(parents=True)
            path = preserved/('a'*32+'.raw'); path.write_bytes(b'')
            destination = root/'new'; report = migrate_data(destination, [source])
            self.assertEqual(report['source_recognition'], 'bounded-recovery-originals')
            self.assertEqual(report['copied_preserved_recovery'], [])
            self.assertEqual(report['unavailable_preserved_recovery'][0]['bytes'], 0)
            self.assertEqual((destination/report['unavailable_preserved_recovery'][0]['preserved_copy']).read_bytes(), b'')
            self.assertEqual(path.read_bytes(), b'')

    def test_arbitrary_unrecognised_directory_is_not_migrated(self):
        with tempfile.TemporaryDirectory(prefix='denghuo-unrecognised-migration-') as directory:
            root = Path(directory); source = root/'old'; source.mkdir()
            (source/'knowledge.json').write_text('{}')
            recovery = source/'exit-recovery'; recovery.mkdir(); (recovery/'notes.json.pending').write_bytes(b'')
            backups = source/'backups'; backups.mkdir(); (backups/'unrelated.zip').write_bytes(b'unrelated bytes')
            self.assertIsNone(migrate_data(root/'new', [source]))
            self.assertFalse((root/'new').exists())

    def test_invalid_settings_never_fall_back_to_default_data(self):
        for raw in ('{', '{}', '[]', '{"save_root":"x","slot":99,"mode":"save","reveal":false}'):
            with self.subTest(raw=raw), tempfile.TemporaryDirectory(prefix='denghuo-invalid-settings-migration-') as directory:
                root = Path(directory); source = root/'old'; source.mkdir()
                (source/'settings.json').write_text(raw)
                (source/'knowledge.json').write_text('{"format":1,"favorites":[],"recent":[],"plans":[]}')
                with self.assertRaisesRegex(ValueError, '旧设置损坏或版本不兼容'):
                    migrate_data(root/'new', [source])
                self.assertFalse((root/'new').exists())
                self.assertEqual((source/'settings.json').read_text(), raw)

    def test_copy_corruption_and_source_change_never_publish_partial_destination(self):
        for kind in ('corrupt-copy', 'changed-source', 'changed-earlier-source', 'new-destination'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(prefix='denghuo-copy-verification-') as directory:
                root = Path(directory); source = root/'old'; source.mkdir()
                settings = source/'settings.json'
                settings.write_text(json.dumps({'save_root': str(root/'saves'), 'slot': 'auto', 'mode': 'save', 'reveal': False}))
                if kind == 'changed-earlier-source':
                    (source/'knowledge.json').write_text('{"format":1,"favorites":[],"recent":[],"plans":[]}')
                destination = root/'new'; copy = shutil.copy2
                def damaged_copy(previous, target):
                    result = copy(previous, target)
                    if kind == 'corrupt-copy': Path(target).write_bytes(b'{"corrupt copy":true}')
                    elif kind == 'changed-source': Path(previous).write_bytes(b'{"changed source":true}')
                    elif kind == 'changed-earlier-source':
                        if Path(previous).name == 'knowledge.json': settings.write_bytes(b'{"changed earlier source":true}')
                    else:
                        destination.mkdir(); (destination/'user-owned').write_bytes(b'keep')
                    return result
                with patch('companion.paths.shutil.copy2', side_effect=damaged_copy):
                    with self.assertRaises(ValueError): migrate_data(destination, [source])
                if kind == 'new-destination':
                    self.assertEqual(list(destination.iterdir()), [destination/'user-owned'])
                    self.assertEqual((destination/'user-owned').read_bytes(), b'keep')
                else:
                    self.assertFalse(destination.exists())
                if kind == 'changed-source': self.assertEqual(settings.read_bytes(), b'{"changed source":true}')

    def test_recovery_over_size_or_count_never_publishes_or_changes_originals(self):
        from companion.session_exit import MAX_DRAFT_FILE
        for kind in ('size', 'count'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(prefix='denghuo-bounded-recovery-migration-') as directory:
                root = Path(directory); source = root/'old'; recovery = source/'exit-recovery'; recovery.mkdir(parents=True)
                if kind == 'size':
                    path = recovery/('a'*32+'.json.pending')
                    with path.open('wb') as stream: stream.truncate(MAX_DRAFT_FILE+1)
                else:
                    for index in range(201): (recovery/(f'{index:032x}'+'.json.pending')).write_bytes(b'')
                sizes = {path.name: path.stat().st_size for path in recovery.iterdir()}
                with self.assertRaises(ValueError): migrate_data(root/'new', [source])
                self.assertFalse((root/'new').exists())
                self.assertEqual({path.name: path.stat().st_size for path in recovery.iterdir()}, sizes)

    def test_recovery_and_preserved_readers_must_verify_actual_copied_files(self):
        from companion.session_exit import ExitDraftStore, ExitRecoveryJournal
        for kind in ('recovery', 'preserved'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(prefix='denghuo-recovery-copy-reader-') as directory:
                root = Path(directory); source = root/'old'; source.mkdir()
                (source/'settings.json').write_text(json.dumps({'save_root': str(root/'saves'),
                    'slot': 'auto', 'mode': 'save', 'reveal': False}))
                journal = ExitRecoveryJournal(source/'exit-recovery', ExitDraftStore(source/'exit-drafts'))
                if kind == 'recovery':
                    journal.checkpoint('web-12345678', 1, True, {'raw': '原始输入'}, 'web', '副本')
                    method = '_read'
                else:
                    journal.preserved_directory.mkdir()
                    identity = 'a'*32; raw = b'unparsed original'
                    (journal.preserved_directory/(identity+'.raw')).write_bytes(raw)
                    (journal.preserved_directory/(identity+'.json')).write_text(json.dumps({
                        'format': 1, 'kind': 'denghuo-recovery-original', 'id': identity,
                        'source_name': 'b'*32+'.json.pending', 'saved': 10000,
                        'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}))
                    method = 'read_preserved'
                reader = getattr(ExitRecoveryJournal, method)
                def reject_actual_copy(current, identity):
                    if current.directory.parent != source:
                        raise ValueError('controlled actual-copy validation failure')
                    return reader(current, identity)
                originals = {str(path.relative_to(source)): path.read_bytes()
                             for path in source.rglob('*') if path.is_file()}
                with patch.object(ExitRecoveryJournal, method, reject_actual_copy):
                    with self.assertRaisesRegex(ValueError, 'actual-copy validation failure'):
                        migrate_data(root/'new', [source])
                self.assertFalse((root/'new').exists())
                self.assertEqual({name: (source/name).read_bytes() for name in originals}, originals)

    def test_non_regular_recovery_original_is_rejected_without_opening_it(self):
        with tempfile.TemporaryDirectory(prefix='denghuo-nonregular-recovery-migration-') as directory:
            root = Path(directory); source = root/'old'; recovery = source/'exit-recovery'; recovery.mkdir(parents=True)
            original = recovery/('a'*32+'.json.pending'); original.mkdir()
            with self.assertRaisesRegex(ValueError, '文件类型或大小不受支持'):
                migrate_data(root/'new', [source])
            self.assertFalse((root/'new').exists())
            self.assertTrue(original.exists())

    def test_first_install_preserves_archived_draft_original_and_state(self):
        from companion.session_exit import ExitDraftStore
        with tempfile.TemporaryDirectory(prefix='denghuo-archived-draft-migration-') as directory:
            root = Path(directory); source = root / 'old'; source.mkdir()
            (source / 'settings.json').write_text(json.dumps({'save_root': str(root / 'saves'),
                'slot': 'auto', 'mode': 'save', 'reveal': False}), encoding='utf-8')
            store = ExitDraftStore(source / 'exit-drafts')
            saved = store.save('web-12345678', 'workspace', '已完成但保留原件', {'numeric': {'hp': '未计算'}})
            archived = store.set_lifecycle(saved['id'], 'archived', store.lifecycle(saved['id'])['state_revision'])
            originals = {path.name: path.read_bytes() for path in store.directory.glob('*.json')}
            destination = root / 'new'; report = migrate_data(destination, [source])
            copied = ExitDraftStore(destination / 'exit-drafts')
            self.assertEqual(report['copied_exit_drafts'], [saved['id'] + '.json'])
            self.assertEqual(report['unavailable_exit_drafts'], [])
            self.assertEqual(copied.list(), [])
            self.assertEqual(copied.list(include_archived=True)[0]['id'], saved['id'])
            self.assertEqual(copied.lifecycle(saved['id'])['state_revision'], archived['state_revision'])
            self.assertEqual(copied.load(saved['id'])['draft']['numeric']['hp'], '未计算')
            self.assertEqual({path.name: path.read_bytes() for path in copied.directory.glob('*.json')}, originals)
            self.assertEqual({path.name: path.read_bytes() for path in store.directory.glob('*.json')}, originals)

    def test_first_install_preserves_draft_and_invalid_bound_state_together(self):
        from companion.session_exit import ExitDraftStore
        with tempfile.TemporaryDirectory(prefix='denghuo-invalid-draft-state-migration-') as directory:
            root = Path(directory); source = root / 'old'; source.mkdir()
            (source / 'settings.json').write_text(json.dumps({'save_root': str(root / 'saves'),
                'slot': 'auto', 'mode': 'save', 'reveal': False}), encoding='utf-8')
            store = ExitDraftStore(source / 'exit-drafts')
            saved = store.save('web-12345678', 'workspace', '原草稿', {'raw': '未提交'})
            state_path = store.directory / (saved['id'] + '.state.json')
            state_path.write_bytes(b'{"format":900,"state":"archived"}')
            originals = {path.name: path.read_bytes() for path in store.directory.glob('*.json')}
            destination = root / 'new'; report = migrate_data(destination, [source])
            self.assertEqual(report['copied_exit_drafts'], [])
            self.assertEqual(report['unavailable_exit_drafts'][0]['file'], saved['id'] + '.json')
            self.assertEqual(ExitDraftStore(destination / 'exit-drafts').list(), [])
            self.assertEqual({path.name: path.read_bytes() for path in (destination / 'exit-drafts-preserved').glob('*.json')}, originals)
            self.assertEqual({path.name: path.read_bytes() for path in store.directory.glob('*.json')}, originals)

    def test_first_install_rejects_orphaned_or_oversized_draft_state_without_publishing(self):
        from companion.session_exit import ExitDraftStore
        for state_kind in ('orphaned', 'oversized'):
            with self.subTest(state_kind=state_kind), tempfile.TemporaryDirectory(prefix='denghuo-unbounded-draft-state-') as directory:
                root = Path(directory); source = root / 'old'; source.mkdir()
                (source / 'settings.json').write_text(json.dumps({'save_root': str(root / 'saves'),
                    'slot': 'auto', 'mode': 'save', 'reveal': False}), encoding='utf-8')
                store = ExitDraftStore(source / 'exit-drafts'); store.directory.mkdir()
                identity = 'a' * 32
                if state_kind == 'oversized':
                    identity = store.save('web-12345678', 'workspace', '原草稿', {'raw': '保留'})['id']
                (store.directory / (identity + '.state.json')).write_bytes(b'x' * (4097 if state_kind == 'oversized' else 1))
                originals = {path.name: path.read_bytes() for path in store.directory.glob('*.json')}
                destination = root / 'new'
                with self.assertRaises(ValueError): migrate_data(destination, [source])
                self.assertFalse(destination.exists())
                self.assertEqual({path.name: path.read_bytes() for path in store.directory.glob('*.json')}, originals)

    def test_first_install_preserves_more_than_one_portable_batch_of_drafts(self):
        from companion.session_exit import ExitDraftStore
        with tempfile.TemporaryDirectory(prefix='denghuo-many-draft-migration-') as directory:
            root = Path(directory); source = root / 'old'; source.mkdir()
            (source / 'settings.json').write_text(json.dumps({'save_root': str(root / 'saves'),
                'slot': 'auto', 'mode': 'save', 'reveal': False}), encoding='utf-8')
            store = ExitDraftStore(source / 'exit-drafts')
            for index in range(201):
                store.save('web-12345678', 'workspace', f'未提交草稿{index}',
                           {'raw': '中文原始输入' * 40000 if index == 0 else str(index)})
            originals = {path.name: path.read_bytes() for path in store.directory.glob('*.json')}
            destination = root / 'new'; report = migrate_data(destination, [source])
            self.assertEqual(len(report['copied_exit_drafts']), 201)
            self.assertEqual({path.name: path.read_bytes() for path in (destination / 'exit-drafts').glob('*.json')}, originals)
            self.assertEqual({path.name: path.read_bytes() for path in store.directory.glob('*.json')}, originals)
            self.assertEqual(len(ExitDraftStore(destination / 'exit-drafts').list()), 201)
            self.assertTrue(any(len(raw) > 512 * 1024 for raw in originals.values()))

    def test_first_install_copies_raw_exit_drafts_and_preserves_incompatible_originals(self):
        from companion.session_exit import ExitDraftStore
        from companion.service import Session
        with tempfile.TemporaryDirectory(prefix='denghuo-raw-draft-migration-') as directory:
            root = Path(directory); source = root / 'old'; source.mkdir()
            (source / 'settings.json').write_text(json.dumps({'save_root': str(root / 'saves'),
                'slot': 'auto', 'mode': 'save', 'reveal': False}), encoding='utf-8')
            store = ExitDraftStore(source / 'exit-drafts')
            saved = store.save('web-12345678', 'workspace', '未计算的输入',
                {'format': 1, 'numeric': {'hp': '不是数字', 'level': '-'}, 'open_plan': {'name': '原名', 'note': '原备注'}})
            valid_path = store.directory / (saved['id'] + '.json')
            valid_raw = valid_path.read_bytes()
            invalid_path = store.directory / ('a' * 32 + '.json')
            invalid_raw = b'{"format":900,"raw":"incompatible original"}'
            invalid_path.write_bytes(invalid_raw)
            destination = root / 'new'; report = migrate_data(destination, [source])
            self.assertEqual(report['copied_exit_drafts'], [valid_path.name])
            self.assertEqual(report['unavailable_exit_drafts'][0]['file'], invalid_path.name)
            self.assertEqual((destination / 'exit-drafts' / valid_path.name).read_bytes(), valid_raw)
            self.assertEqual((destination / 'exit-drafts-preserved' / invalid_path.name).read_bytes(), invalid_raw)
            self.assertEqual(valid_path.read_bytes(), valid_raw); self.assertEqual(invalid_path.read_bytes(), invalid_raw)
            loaded = Session(destination / 'settings.json')
            self.assertEqual(len(loaded.exit_drafts.list()), 1); self.assertIsNone(loaded.data)

    def test_frozen_data_is_independent_of_resource_and_executable_locations(self):
        with patch('companion.paths.sys.frozen',True,create=True), patch.dict('os.environ',{'LOCALAPPDATA':'C:/用户数据'}):
            self.assertEqual(data_directory(),Path('C:/用户数据/Denghuo'))
            with patch('companion.paths.ROOT',Path('C:/temporary-unpack')):
                self.assertEqual(data_directory(),Path('C:/用户数据/Denghuo'))

    def test_migration_copies_all_backups_and_preserves_both_old_and_existing_data(self):
        with tempfile.TemporaryDirectory(prefix='denghuo-migrate-') as directory:
            root=Path(directory);source=root/'旧版'/'内置数据';source.mkdir(parents=True)
            settings={'save_root':str(root/'offline-saves'),'slot':3,'mode':'save','reveal':False}
            (source/'settings.json').write_text(json.dumps(settings),encoding='utf-8')
            archive=source/'backups'/'scope'/'retained.zip';archive.parent.mkdir(parents=True);archive.write_bytes(b'original archive bytes')
            destination=root/'应用数据'
            report=migrate_data(destination,[root/'missing',source])
            self.assertEqual(report['copied_files'],1)
            self.assertEqual((destination/'backups/scope/retained.zip').read_bytes(),archive.read_bytes())
            self.assertTrue(archive.exists());self.assertEqual(json.loads((destination/'settings.json').read_text()),settings)
            (destination/'settings.json').write_text('keep current user settings')
            self.assertIsNone(migrate_data(destination,[source]))
            self.assertEqual((destination/'settings.json').read_text(),'keep current user settings')

    def test_failed_migration_never_publishes_partial_destination(self):
        with tempfile.TemporaryDirectory(prefix='denghuo-migrate-failure-') as directory:
            root=Path(directory);source=root/'old';source.mkdir()
            raw=json.dumps({'save_root':str(root),'slot':1,'mode':'save','reveal':False})
            (source/'settings.json').write_text(raw)
            destination=root/'new'
            with patch('companion.paths.shutil.copy2',side_effect=OSError('controlled copy failure')):
                with self.assertRaises(OSError):migrate_data(destination,[source])
            self.assertFalse(destination.exists())
            self.assertEqual((source/'settings.json').read_text(),raw)

    def test_migration_retains_library_and_shared_play_preferences_without_applying_a_draft(self):
        from companion.service import Session
        with tempfile.TemporaryDirectory(prefix='denghuo-workspace-migrate-') as directory:
            root=Path(directory);source=root/'old';source.mkdir()
            settings={'save_root':str(root/'synthetic-saves'),'slot':'auto','mode':'save','reveal':False}
            (source/'settings.json').write_text(json.dumps(settings),encoding='utf-8')
            session=Session(source/'settings.json')
            plan=session.knowledge.save('手动草稿','manual',None,{'hp':3,'ht':30,'buffs':['Poison']})
            session.play_preferences.update({'offset_y':140})
            original_library=(source/'knowledge.json').read_bytes()
            original_play=(source/'play-mode.json').read_bytes()
            destination=root/'new'
            report=migrate_data(destination,[source])
            self.assertEqual(set(report['copied_preferences']),{'knowledge.json','play-mode.json'})
            loaded=Session(destination/'settings.json')
            self.assertEqual(loaded.knowledge.reopen(plan['id'])['result']['hero']['hp'],3)
            self.assertIsNone(loaded.data)
            self.assertEqual(loaded.settings['mode'],'save')
            self.assertEqual(loaded.play_preferences.values['offset_y'],140)
            self.assertEqual((destination/'knowledge.json').read_bytes(),original_library)
            self.assertEqual((source/'knowledge.json').read_bytes(),original_library)
            self.assertEqual((source/'play-mode.json').read_bytes(),original_play)
