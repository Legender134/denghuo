import gzip
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zipfile import ZipFile, ZIP_STORED

from companion.backups import BackupManager
from companion import backup_workflows as flows


class BackupWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='denghuo-backup-workflow-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / 'synthetic-saves'
        self.root.mkdir()
        self.clock = 1700000000
        self.manager = BackupManager(self.base/'backups', clock=lambda:self.clock,closed_check=lambda:None)

    def capture(self,hp,slot=1):
        self.clock += 120
        folder = self.root / f'game{slot}'
        folder.mkdir(exist_ok=True)
        game={'depth':2,'version':920,'seed':9+slot,'generated_levels':[2],
              'hero':{'class':'MAGE','HP':hp,'HT':30,'STR':10,'lvl':2,'inventory':[],'buffs':[]}}
        level={'__className':'com.shatteredpixel.shatteredpixeldungeon.levels.SewerLevel','version':920,
               'width':4,'height':4,'map':[4]*16,'visited':[False]*16,'mapped':[False]*16}
        for name,value in (('game.dat',game),('depth2.dat',{'level':level})):
            path=folder/name
            path.write_bytes(gzip.compress(json.dumps(value).encode(),mtime=0))
            os.utime(path,(self.clock,self.clock))
        return self.manager.capture(self.root,slot)

    def selected(self,rows):return [{'slot':row['slot'],'id':row['id']} for row in rows]

    def manage(self, root, payload):
        current = self.manager.selected(root, payload)
        self.manager.manage(root, {**payload, 'expected_metadata_revision': current['metadata_revision']})

    def interrupted_stage(self):
        row = self.capture(5)
        self.capture(22)
        actual = Path.replace
        def fail_swap(path, target):
            if path.name.startswith('.denghuo-stage-'):
                raise OSError('controlled interruption before swap')
            return actual(path, target)
        preview = self.manager.preview(self.root, row)
        with patch.object(Path, 'replace', fail_swap):
            with self.assertRaises(OSError):
                self.manager.restore(self.root, {**row, 'confirm': '恢复槽位 1',
                                                'expected_current': preview['expected_current']})
        path = next(self.root.glob('.denghuo-stage-*'))
        return row, path

    def test_interrupted_stage_is_visible_verified_retried_and_originals_preserved(self):
        row, path = self.interrupted_stage()
        original = {p.name: p.read_bytes() for p in path.iterdir()}
        inventory = flows.storage_inventory(self.manager, self.root)
        stage = next(group for group in inventory['groups'] if group['kind'] == 'stage')['rows'][0]
        self.assertEqual(stage['bytes'], sum(map(len, original.values())))
        self.assertIn('controlled interruption', stage['reason'])
        self.assertTrue(stage['owned'])
        inspected = flows.inspect_stage(self.manager, self.root, {'file': path.name})
        self.assertTrue(inspected['verified'])
        preview = flows.stage_preview(self.manager, self.root, {'file': path.name})
        with self.assertRaisesRegex(ValueError, '明确确认'):
            flows.retry_stage(self.manager, self.root, {'file': path.name, 'expected': preview['expected']})
        result = flows.retry_stage(self.manager, self.root,
            {'file': path.name, 'expected': preview['expected'], 'confirmed': True,
             'confirm': preview['confirm_phrase']})
        self.assertTrue(result['original_stage_preserved'])
        self.assertEqual({p.name: p.read_bytes() for p in path.iterdir()}, original)
        self.assertTrue((self.manager.scope(self.root) / (row['id'] + '.zip')).exists())
        self.assertEqual(self.manager.current_summary(self.root, 1)['hp'], 5)
        self.assertEqual(len(list(self.root.glob('.denghuo-before-*'))), 1)

    def test_stage_unknown_incomplete_changed_and_reopened_game_cannot_retry(self):
        row, path = self.interrupted_stage()
        payload = {'file': path.name}
        preview = flows.stage_preview(self.manager, self.root, payload)
        confirmation = {**payload, 'expected': preview['expected'], 'confirmed': True,
                        'confirm': preview['confirm_phrase']}
        self.capture(29)
        with self.assertRaisesRegex(ValueError, '已变化'):
            flows.retry_stage(self.manager, self.root, confirmation)
        self.manager.closed_check = lambda: (_ for _ in ()).throw(ValueError('游戏尚未关闭'))
        with self.assertRaisesRegex(ValueError, '游戏尚未关闭'):
            flows.stage_preview(self.manager, self.root, payload)
        self.manager.closed_check = lambda: None
        (path / 'extra.txt').write_text('keep changed original')
        self.assertFalse(flows.inspect_stage(self.manager, self.root, payload)['retryable'])
        unknown = self.root / '.denghuo-stage-2-123-12345678'
        unknown.mkdir(); (unknown / 'original.txt').write_text('unknown owner')
        inspected = flows.inspect_stage(self.manager, self.root, {'file': unknown.name})
        self.assertFalse(inspected['verified']); self.assertIn('来源记录', inspected['error'])
        self.assertTrue(path.exists()); self.assertTrue(unknown.exists())
        self.assertEqual(self.manager.current_summary(self.root, 1)['hp'], 29)

    def batch(self,rows):
        selected=self.selected(rows)
        preview=flows.export_preview(self.manager,self.root,{'selected':selected})
        raw,_=flows.export_batch(self.manager,self.root,{'selected':selected,'expected':preview['expected']})
        return raw,preview

    def test_two_slots_named_fixed_batch_transfer_preserves_original_observations_without_restoring(self):
        first=self.capture(5,1);second=self.capture(15,2)
        self.manage(self.root,{**self.selected([first])[0],'label':'首领前','locked':True})
        self.manage(self.root,{**self.selected([second])[0],'label':'另一局'})
        raw,preview=self.batch([first,second])
        self.assertEqual(preview['count'],2)
        self.assertEqual({row['slot'] for row in preview['rows']},{1,2})
        destination=self.base/'destination-saves'
        destination.mkdir()
        incoming=BackupManager(self.base/'destination-backups',clock=lambda:self.clock+1000,closed_check=lambda:None)
        inspection=flows.import_preview(incoming,destination,raw)
        self.assertEqual(inspection['valid_count'],2)
        results=flows.import_batch(incoming,destination,raw,inspection['expected'],[row['file'] for row in inspection['rows']],True)
        self.assertEqual((results['success_count'],results['failure_count'],results['restored']),(2,0,False))
        records=incoming.history(destination)
        self.assertEqual({row['label'] for row in records},{'首领前','另一局'})
        protected=next(row for row in records if row['label']=='首领前')
        self.assertTrue(protected['locked'])
        self.assertEqual(protected['time'],first['time'])
        self.assertGreater(protected['imported_at'],protected['last_seen'])
        for result in results['results']:
            source=next(row for row in preview['rows'] if row['id']==result['source_id'])
            self.assertEqual(result['saved'],source['saved'])
            self.assertEqual(result['first_observed'],source['first_observed'])
            self.assertEqual(result['last_observed'],source['last_observed'])
            self.assertEqual(result['bytes'],source['bytes'])
            self.assertEqual(result['source_file'],source['file'])
            self.assertEqual(result['target_id'],result['id'])
            self.assertIn('hp',result['summary'])
        self.assertFalse(list(destination.glob('game*')))

    def test_preview_signature_stable_across_zip_wall_clock_but_rejects_changed_label(self):
        row=self.capture(5)
        selected=self.selected([row])
        preview=flows.export_preview(self.manager,self.root,{'selected':selected})
        with patch('zipfile.time.localtime',return_value=(2030,1,1,0,0,0,0,1,0)):
            raw,_=flows.export_batch(self.manager,self.root,{'selected':selected,'expected':preview['expected']})
        self.assertTrue(raw)
        self.manage(self.root,{**selected[0],'label':'改名'})
        with self.assertRaisesRegex(ValueError,'重新预览'):
            flows.export_batch(self.manager,self.root,{'selected':selected,'expected':preview['expected']})

    def test_corrupt_one_member_reports_partial_import_and_retries_only_selected_failure(self):
        raw,_=self.batch([self.capture(5,1),self.capture(15,2)])
        with ZipFile(BytesIO(raw)) as archive:
            content={row.filename:archive.read(row.filename) for row in archive.infolist()}
        index=json.loads(content['denghuo-transfer.json'])
        bad=index['entries'][1]
        content[bad['file']]=b'not a valid inner ZIP'
        bad.update(bytes=len(content[bad['file']]),sha256=hashlib.sha256(content[bad['file']]).hexdigest())
        content['denghuo-transfer.json']=json.dumps(index).encode()
        output=BytesIO()
        with ZipFile(output,'w',ZIP_STORED) as archive:
            for name,value in content.items():archive.writestr(name,value)
        damaged=output.getvalue()
        incoming=BackupManager(self.base/'import-backups',clock=lambda:self.clock,closed_check=lambda:None)
        inspection=flows.import_preview(incoming,self.root,damaged)
        self.assertEqual(inspection['valid_count'],1)
        names=[row['file'] for row in inspection['rows']]
        before=(self.root/'game1/game.dat').read_bytes()
        results=flows.import_batch(incoming,self.root,damaged,inspection['expected'],names,True)
        self.assertEqual((results['success_count'],results['failure_count']),(1,1))
        failed=[row['file'] for row in results['results'] if not row['ok']]
        retried=flows.import_batch(incoming,self.root,damaged,inspection['expected'],failed,True)
        self.assertEqual((retried['success_count'],retried['failure_count']),(0,1))
        self.assertEqual(len(incoming.history(self.root)),1)
        self.assertEqual((self.root/'game1/game.dat').read_bytes(),before)

    def test_bad_preview_and_duplicate_selection_do_not_import_anything(self):
        row=self.capture(5)
        with self.assertRaises(ValueError):flows.export_preview(self.manager,self.root,{'selected':self.selected([row,row])})
        raw,_=self.batch([row])
        incoming=BackupManager(self.base/'incoming',clock=lambda:self.clock)
        with self.assertRaises(ValueError):flows.import_batch(incoming,self.root,raw,'0'*64,[],True)
        self.assertFalse(incoming.directory.exists())
        with self.assertRaises(ValueError):flows.import_preview(incoming,self.root,b'invalid ZIP')
        self.assertFalse(list(incoming.directory.rglob('*.zip')))

    def test_preserve_all_and_explicit_retention_keep_fixed_latest_and_active_undo(self):
        rows=[self.capture(hp) for hp in (1,2,3,4,5)]
        self.manage(self.root,{**self.selected([rows[0]])[0],'locked':True,'label':'固定'})
        restore={**self.selected([rows[1]])[0],'confirm':'恢复槽位 1'}
        self.manager.restore(self.root,restore)
        inventory=flows.storage_inventory(self.manager,self.root)
        before_group=next(group for group in inventory['groups'] if group['kind']=='before')
        self.assertTrue(before_group['rows'][0]['protected'])
        before_path=self.root/before_group['rows'][0]['file']
        original_digest=self.manager.directory_digest(before_path)
        all_kept=flows.retention_preview(self.manager,self.root,{'policy':{}})
        self.assertEqual(all_kept['candidates'],[])
        policy={'keep_per_slot':1}
        preview=flows.retention_preview(self.manager,self.root,{'policy':policy})
        self.assertEqual({row['id'] for row in preview['candidates']},{rows[2]['id'],rows[3]['id']})
        kept={row['id'] for row in preview['kept']}
        self.assertTrue({rows[0]['id'],rows[1]['id'],rows[4]['id']}<=kept)
        latest=next(row for row in preview['kept'] if row['id']==rows[4]['id'])
        self.assertTrue(latest['protected'])
        self.assertIn('最新',latest['reason'])
        with self.assertRaisesRegex(ValueError,'撤回'):
            self.manager.remove(self.root,{**restore,'confirm':'移出备份 1'})
        original_zips=sorted(hashlib.sha256(path.read_bytes()).hexdigest()
                             for path in self.manager.scope(self.root).glob('*.zip'))
        original_game=(self.root/'game1/game.dat').read_bytes()
        moved=flows.archive_retention(self.manager,self.root,{'policy':policy,'expected':preview['expected'],'confirmed':True})
        self.assertEqual((moved['archived'],moved['deleted']),(2,0))
        self.assertEqual(len(self.manager.retained_status(self.root)),2)
        current_paths=list(self.manager.scope(self.root).glob('*.zip'))
        current_paths+=list((self.manager.directory.parent/'backup-recycle'/self.manager.scope(self.root).name).glob('*.zip'))
        self.assertEqual(sorted(hashlib.sha256(path.read_bytes()).hexdigest() for path in current_paths),original_zips)
        self.assertEqual((self.root/'game1/game.dat').read_bytes(),original_game)
        self.assertEqual(self.manager.directory_digest(before_path),original_digest)
        self.assertTrue(self.manager.undo_status(self.root))
        exported,_=flows.export_preserved(self.manager,self.root,{'kind':'before','file':before_path.name})
        with ZipFile(BytesIO(exported)) as archive:
            manifest=json.loads(archive.read('denghuo-preserved.json'))
            self.assertFalse(manifest['restorable_backup_set'])
            self.assertEqual(archive.read('preserved/game.dat'),(before_path/'game.dat').read_bytes())

    def test_stale_retention_preview_preserves_every_active_archive(self):
        first=self.capture(1);self.capture(2);self.capture(3)
        preview=flows.retention_preview(self.manager,self.root,{'policy':{'keep_per_slot':1}})
        self.manage(self.root,{**self.selected([first])[0],'locked':True})
        paths={path:path.read_bytes() for path in self.manager.scope(self.root).glob('*.zip')}
        with self.assertRaisesRegex(ValueError,'重新预览'):
            flows.archive_retention(self.manager,self.root,{'policy':{'keep_per_slot':1},'expected':preview['expected'],'confirmed':True})
        self.assertTrue(all(path.read_bytes()==raw for path,raw in paths.items()))
        self.assertEqual(self.manager.retained_status(self.root),[])

    def test_actual_http_preview_batch_export_import_confirmation_and_context_guards(self):
        from companion.server import Server
        from companion.service import Session
        session=Session(self.base/'settings.json')
        session.settings['save_root']=str(self.root)
        session.backups=self.manager
        rows=[self.capture(5,1),self.capture(15,2)]
        server=Server(session)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        def request(path,payload=None,*,zip_body=False,extras=None):
            headers={'X-Companion-Token':server.token,'Origin':server.origin}
            if zip_body:
                raw=payload
                headers.update({'Content-Type':'application/zip','X-Companion-Backup-Context':session.backup_context})
            elif payload is not None:
                raw=json.dumps(payload).encode()
                headers['Content-Type']='application/json'
            else:raw=None
            headers.update(extras or {})
            with urlopen(Request(server.origin+path,data=raw,headers=headers),timeout=5) as response:
                value=response.read()
                return value if response.headers.get_content_type()=='application/zip' else json.loads(value)
        try:
            storage=request('/api/backups/storage?context='+session.backup_context)
            self.assertEqual(storage['default_policy'],'preserve-all')
            selected=self.selected(rows)
            preview=request('/api/backups/workflow',{'action':'export-preview','selected':selected,'context':session.backup_context})
            raw=request('/api/backups/workflow',{'action':'batch-export','selected':selected,'expected':preview['expected'],'context':session.backup_context})
            inspection=request('/api/backups/batch-preview',raw,zip_body=True)
            self.assertEqual(inspection['valid_count'],2)
            files=[row['file'] for row in inspection['rows']]
            with self.assertRaises(HTTPError) as confirm:
                request('/api/backups/batch-import',raw,zip_body=True,extras={
                    'X-Companion-Transfer-Digest':inspection['expected'],'X-Companion-Transfer-Selection':json.dumps(files)})
            self.assertEqual(confirm.exception.code,400)
            result=request('/api/backups/batch-import',raw,zip_body=True,extras={
                'X-Companion-Transfer-Digest':inspection['expected'],'X-Companion-Transfer-Selection':json.dumps(files),
                'X-Companion-Transfer-Confirmed':'true'})
            self.assertEqual(result['success_count'],2)
            self.assertFalse(result['restored'])
            with self.assertRaises(HTTPError) as context:
                request('/api/backups/workflow',{'action':'retention-preview','policy':{},'context':'old-connection'})
            self.assertEqual(context.exception.code,400)
        finally:
            server.shutdown();server.server_close();thread.join(timeout=5)
            self.assertFalse(thread.is_alive())

    def reclaim_target(self):
        old=self.capture(5);self.capture(15)
        self.manager.remove(self.root,{**self.selected([old])[0],'confirm':'移出备份 1'})
        group=next(g for g in flows.storage_inventory(self.manager,self.root)['groups'] if g['kind']=='retained')
        return {'kind':'retained','file':group['rows'][0]['file']}

    def external_folder(self):
        temporary=tempfile.TemporaryDirectory(prefix='denghuo-external-archive-')
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name)

    def reclaim_ready(self, selected):
        payload={'selected':selected,'context':'isolated-context'}
        preview=flows.reclaim_preview(self.manager,self.root,payload)
        payload.update(expected=preview['expected'],external_path=str(self.external_folder()/'originals.zip'))
        exported=flows.reclaim_export(self.manager,self.root,payload)
        payload.update(archive_sha256=exported['archive_sha256'],exact_targets=selected,
                       count=preview['count'],confirm=preview['confirm_phrase'],confirmed=True)
        return payload,preview

    def test_reclaim_verifies_external_original_bytes_and_releases_exact_payload_without_game_changes(self):
        target=self.reclaim_target()
        source=self.manager.directory.parent/'backup-recycle'/self.manager.scope(self.root).name/target['file']
        original={p.name:p.read_bytes() for p in (source,source.with_suffix('.json'))}
        game=(self.root/'game1/game.dat').read_bytes()
        payload,preview=self.reclaim_ready([target])
        self.assertEqual(preview['bytes'],sum(map(len,original.values())))
        with ZipFile(payload['external_path']) as archive:
            manifest=json.loads(archive.read('denghuo-reclaim.json'))
            for entry in manifest['rows'][0]['files']:
                self.assertEqual(archive.read(entry['member']),original[entry['file']])
                self.assertEqual(entry['sha256'],hashlib.sha256(original[entry['file']]).hexdigest())
        result=flows.reclaim_execute(self.manager,self.root,payload)
        self.assertEqual((result['success_count'],result['released_bytes']),(1,preview['bytes']))
        self.assertTrue(Path(payload['external_path']).is_file())
        self.assertFalse(source.exists());self.assertFalse(source.with_suffix('.json').exists())
        self.assertEqual((self.root/'game1/game.dat').read_bytes(),game)
        self.assertEqual(len(self.manager.history(self.root)),1)

    def test_reclaim_latest_locked_undo_and_unknown_ownership_are_protected(self):
        old=self.capture(5);latest=self.capture(15)
        # A duplicate of an active protected progress must remain protected.
        self.manager.remove(self.root,{**self.selected([old])[0],'confirm':'移出备份 1'})
        retained=self.manager.retained_status(self.root)[0]
        self.manager.rejoin(self.root,{'file':retained['file']})
        self.manage(self.root,{**self.selected([old])[0],'locked':True})
        with self.assertRaisesRegex(ValueError,'固定'):
            flows.reclaim_preview(self.manager,self.root,{'selected':[{'kind':'retained','file':retained['file']}]})
        self.manage(self.root,{**self.selected([old])[0],'locked':False})
        self.manager.restore(self.root,{**self.selected([old])[0],'confirm':'恢复槽位 1'})
        inventory=flows.storage_inventory(self.manager,self.root)
        before=next(g for g in inventory['groups'] if g['kind']=='before')['rows'][0]
        self.assertFalse(before['reclaimable'])
        with self.assertRaises(ValueError):flows.reclaim_preview(self.manager,self.root,{'selected':[{'kind':'before','file':before['file']}]})
        with self.assertRaisesRegex(ValueError,'撤回'):
            flows.reclaim_preview(self.manager,self.root,{'selected':[{'kind':'retained','file':retained['file']}]})
        # Filename-shaped unrelated copies cannot become eligible.
        unknown=self.root/'.denghuo-before-2-123-abcdef12';unknown.mkdir();(unknown/'foreign.txt').write_bytes(b'foreign')
        quarantine=self.manager.directory.parent/'backup-quarantine'/self.manager.scope(self.root).name
        quarantine.mkdir(parents=True);(quarantine/('a'*64+'-1.zip')).write_bytes(b'unknown')
        inventory=flows.storage_inventory(self.manager,self.root)
        for kind,name in (('before',unknown.name),('quarantine','a'*64+'-1.zip')):
            row=next(r for g in inventory['groups'] if g['kind']==kind for r in g['rows'] if r['file']==name)
            self.assertFalse(row['reclaimable']);self.assertIn('缺少',row['reclaim_reason'])
        # Latest active selection isn't an allowed physical reclaim source.
        with self.assertRaises(ValueError):flows.reclaim_preview(self.manager,self.root,{'selected':[{'kind':'active','file':latest['id']+'.zip'}]})

    def test_reclaim_last_known_progress_when_active_library_empty_is_preserved(self):
        only=self.capture(5)
        self.manager.remove(self.root,{**self.selected([only])[0],'confirm':'移出备份 1'})
        row=next(g for g in flows.storage_inventory(self.manager,self.root)['groups'] if g['kind']=='retained')['rows'][0]
        self.assertFalse(row['reclaimable']);self.assertIn('最新',row['reclaim_reason'])

    def test_reclaim_stale_content_labels_protection_list_context_and_archive_stop_without_deletion(self):
        for change in ('source','label','lock','list','context','archive'):
            with self.subTest(change=change):
                target=self.reclaim_target();payload,preview=self.reclaim_ready([target])
                source=Path(preview['rows'][0]['path']);before=source.read_bytes()
                if change=='source':source.write_bytes(before+b'changed')
                elif change=='label':
                    sidecar=source.with_suffix('.json');owner=json.loads(sidecar.read_text());owner['label']='changed';sidecar.write_text(json.dumps(owner))
                elif change=='lock':
                    self.manager.rejoin(self.root,{'file':target['file']})
                    self.manage(self.root,{'slot':1,'id':preview['rows'][0]['id'],'locked':True})
                elif change=='list':
                    directory=self.root/'.denghuo-before-3-123-abcdef13';directory.mkdir();(directory/'extra').write_bytes(b'extra')
                elif change=='context':payload['context']='changed-context'
                else:
                    path=Path(payload['external_path']);path.write_bytes(path.read_bytes()+b'changed')
                with self.assertRaises(ValueError):flows.reclaim_execute(self.manager,self.root,payload)
                self.assertTrue(source.is_file());self.assertTrue(Path(payload['external_path']).is_file())
                if change=='lock':self.manage(self.root,{'slot':1,'id':preview['rows'][0]['id'],'locked':False})

    def test_reclaim_old_before_and_quarantine_preserve_extra_files_and_corrupt_originals(self):
        first=self.capture(5);second=self.capture(15)
        extra=self.root/'game1'/'extra-directory';extra.mkdir();(extra/'mod.bin').write_bytes(b'full extra payload\x00\xff')
        (extra/'empty').mkdir()
        self.manager.restore(self.root,{**self.selected([first])[0],'confirm':'恢复槽位 1'})
        old=self.manager.journals(self.root)[0]
        self.manager.restore(self.root,{**self.selected([second])[0],'confirm':'恢复槽位 1'})
        current=self.manager.undo_status(self.root)
        original=Path(self.manager.scope(self.root))/(first['id']+'.zip');original.write_bytes(b'corrupt original\x00\xff')
        # Capture same first identity forces app-created quarantine receipt.
        recreated=self.capture(5)
        self.assertEqual(recreated['id'],first['id'])
        self.capture(25)
        quarantine=next(g for g in flows.storage_inventory(self.manager,self.root)['groups'] if g['kind']=='quarantine')['rows'][0]
        selected=[{'kind':'before','file':old['original']},{'kind':'quarantine','file':quarantine['file']}]
        payload,preview=self.reclaim_ready(selected)
        with ZipFile(payload['external_path']) as archive:
            self.assertEqual(archive.read('originals/0/extra-directory/mod.bin'),b'full extra payload\x00\xff')
            self.assertEqual(archive.read('originals/1/'+quarantine['file']),b'corrupt original\x00\xff')
            index=json.loads(archive.read('denghuo-reclaim.json'))
            self.assertIn('extra-directory/empty',index['rows'][0]['directories'])
            self.assertFalse(index['restorable_backup_set'])
        game=(self.root/'game1/game.dat').read_bytes()
        result=flows.reclaim_execute(self.manager,self.root,payload)
        self.assertEqual((result['success_count'],result['released_bytes']),(2,preview['bytes']))
        self.assertEqual((self.root/'game1/game.dat').read_bytes(),game)
        self.assertEqual(self.manager.undo_status(self.root),current)

    def test_reclaim_external_path_links_overwrite_and_exact_confirmation_are_rejected(self):
        target=self.reclaim_target();payload,preview=self.reclaim_ready([target])
        with self.assertRaises(FileExistsError):flows.reclaim_export(self.manager,self.root,payload)
        for path in ('relative.zip',str(self.root/'bad.zip'),str(self.manager.directory/'bad.zip')):
            with self.assertRaises(ValueError):flows.reclaim_export(self.manager,self.root,{**payload,'external_path':path})
        for patch_value in ({'confirmed':False},{'count':2},{'exact_targets':[]},{'confirm':'回收所有'}):
            with self.assertRaises(ValueError):flows.reclaim_execute(self.manager,self.root,{**payload,**patch_value})
        self.assertTrue(Path(preview['rows'][0]['path']).is_file())
        link=self.external_folder()/'linked'
        try:link.symlink_to(Path(payload['external_path']).parent,target_is_directory=True)
        except OSError:pass # Windows without symlink privilege is covered by unlinked tests.
        else:
            with self.assertRaisesRegex(ValueError,'链接'):flows.reclaim_export(self.manager,self.root,{**payload,'external_path':str(link/'copy.zip')})

    def test_reclaim_partial_batch_failure_rolls_back_current_target_and_requires_fresh_preview(self):
        one=self.reclaim_target();two=self.reclaim_target();payload,preview=self.reclaim_ready([one,two])
        originals={row['path']:Path(row['path']).read_bytes() for row in preview['rows']}
        failing=Path(preview['rows'][1]['path'])
        native_unlink=Path.unlink
        def fail(path,*args,**kwargs):
            if path==failing.with_suffix('.json'):raise OSError('synthetic permission denied')
            return native_unlink(path,*args,**kwargs)
        with patch.object(Path,'unlink',fail):result=flows.reclaim_execute(self.manager,self.root,payload)
        self.assertEqual((result['success_count'],result['failure_count']),(1,1))
        self.assertEqual(result['released_bytes'],preview['rows'][0]['bytes'])
        self.assertEqual(failing.read_bytes(),originals[str(failing)])
        self.assertTrue(failing.with_suffix('.json').is_file())
        with self.assertRaises(ValueError):flows.reclaim_execute(self.manager,self.root,payload)
        retry,new_preview=self.reclaim_ready([two])
        retried=flows.reclaim_execute(self.manager,self.root,retry)
        self.assertEqual((retried['success_count'],retried['released_bytes']),(1,new_preview['bytes']))
        self.assertTrue(Path(payload['external_path']).is_file())


    def test_reclaim_source_change_during_unlink_stops_and_preserves_changed_file(self):
        target=self.reclaim_target();payload,preview=self.reclaim_ready([target])
        source=Path(preview['rows'][0]['path']);original=source.read_bytes();sidecar=source.with_suffix('.json')
        sidecar_original=sidecar.read_bytes()
        changed=original+b'changed by another writer';native_unlink=Path.unlink
        def mutate(path,*args,**kwargs):
            result=native_unlink(path,*args,**kwargs)
            if path==sidecar:source.write_bytes(changed)
            return result
        with patch.object(Path,'unlink',mutate):result=flows.reclaim_execute(self.manager,self.root,payload)
        self.assertEqual((result['success_count'],result['failure_count'],result['released_bytes']),(0,1,0))
        self.assertEqual(source.read_bytes(),changed);self.assertEqual(sidecar.read_bytes(),sidecar_original)
        self.assertEqual(result['results'][0]['restored_files'],[sidecar.name])
        self.assertTrue(Path(payload['external_path']).is_file())

    def test_reclaim_rechecks_inner_archive_bytes_even_with_matching_outer_hash(self):
        target=self.reclaim_target();payload,preview=self.reclaim_ready([target])
        path=Path(payload['external_path'])
        with ZipFile(path) as archive:members={name:archive.read(name) for name in archive.namelist()}
        name=preview['rows'][0]['files'][0]['member'];raw=members[name];members[name]=bytes([raw[0]^1])+raw[1:]
        with ZipFile(path,'w',ZIP_STORED) as archive:
            for name,raw in members.items():archive.writestr(name,raw)
        payload['archive_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError,'原件字节'):flows.reclaim_execute(self.manager,self.root,payload)
        self.assertTrue(Path(preview['rows'][0]['path']).is_file());self.assertTrue(path.is_file())



if __name__=='__main__':unittest.main()
