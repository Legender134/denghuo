import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from companion.service import Session
from companion.session_exit import ExitDraftStore, ExitRecoveryJournal


class RecoveryJournalTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='denghuo-recovery-test-')
        self.addCleanup(self.temporary.cleanup)
        self.directory=Path(self.temporary.name)
        self.config=self.directory/'settings.json'

    def report(self, session, suffix='a', revision=1, dirty=True, raw='  -unfinished\t  '):
        return session.report_exit_surface('web-'+suffix*8,revision,dirty,
            draft={'format':2,'schema':'denghuo-web-session','numeric':[{'identity':'actors.buffs.healing','raw':{'power':raw}}]},
            label='数值与炼金原始输入',kind='web')

    def crash_pending(self, *, initial=False, damaged=False, quota='none', raw='  -unfinished\t  '):
        script='''import os,sys
from pathlib import Path
from unittest.mock import patch
from companion import session_exit
from companion.session_exit import ExitDraftStore,ExitRecoveryJournal
directory=Path(sys.argv[1])
j=ExitRecoveryJournal(directory/'exit-recovery',ExitDraftStore(directory/'exit-drafts'))
def report(revision,raw):
    return j.checkpoint('web-aaaaaaaa',revision,True,{'format':2,'schema':'denghuo-web-session','numeric':[{'identity':'actors.buffs.healing','raw':{'power':raw}}]},'web','raw input')
if sys.argv[2]=='initial':report(1,'committed raw')
if sys.argv[4]=='bytes':session_exit.MAX_RECOVERY_BYTES=4096
if sys.argv[4]=='count':session_exit.MAX_RECOVERY_RECORDS=2
replace=Path.replace
write_text=Path.write_text
def interrupted_replace(path,target):
    if path.name.endswith('.json.pending') and path.parent==j.directory:os._exit(23)
    return replace(path,target)
def interrupted_write(path,text,*args,**kwargs):
    if path.name.endswith('.json.pending') and path.parent==j.directory:
        path.write_bytes(b'{"format": 1, "broken raw": "unfinished')
        os._exit(23)
    return write_text(path,text,*args,**kwargs)
try:
    with patch.object(Path,'replace',interrupted_replace),patch.object(Path,'write_text',interrupted_write if sys.argv[3]=='damaged' else write_text):
        report(2 if sys.argv[2]=='initial' else 1,sys.argv[5])
except ValueError as exc:
    print(str(exc))
    raise SystemExit(24)
'''
        return subprocess.run([sys.executable,'-B','-c',script,str(self.directory),
            'initial' if initial else 'none','damaged' if damaged else 'none',quota,raw],
            cwd=Path(__file__).resolve().parents[1],capture_output=True,timeout=8)

    def journal(self):
        return ExitRecoveryJournal(self.directory/'exit-recovery',ExitDraftStore(self.directory/'exit-drafts'))

    def test_actual_interrupted_write_is_explicitly_recoverable_without_applying(self):
        result=self.crash_pending()
        self.assertEqual(result.returncode,23,result.stderr.decode(errors='replace'))
        restarted=Session(self.config)
        row,=restarted.list_exit_drafts()
        self.assertTrue(row['pending']);self.assertIn('中断副本',row['label'])
        self.assertTrue(row['id'].endswith('.pending'))
        record=restarted.load_exit_draft(row['id'])
        self.assertEqual(record['id'],row['id'][:-8])
        self.assertEqual(record['format'],2)
        self.assertEqual(record['draft']['numeric'][0]['raw']['power'],'  -unfinished\t  ')
        self.assertFalse(self.config.exists())
        self.assertEqual(restarted.exit_status()['participants'],[])
        result=restarted.set_exit_draft_lifecycle(row['id'],'archived',row['state_revision'])
        self.assertFalse(result['applied'])
        self.assertEqual(restarted.list_exit_drafts(),[])
        archived,=restarted.list_exit_drafts(include_archived=True)
        self.assertEqual(restarted.load_exit_draft(archived['id'])['draft'],record['draft'])

    def test_crash_pending_bytes_are_bounded_across_new_sessions(self):
        results=[self.crash_pending(quota='bytes',raw='x'*1000) for _ in range(3)]
        self.assertEqual([row.returncode for row in results],[23,23,24])
        files=list((self.directory/'exit-recovery').glob('*.json.pending'))
        self.assertEqual(len(files),2)
        self.assertLessEqual(sum(path.stat().st_size for path in files),4096)
        before={path.name:path.read_bytes() for path in files}
        from companion import session_exit
        with patch.object(session_exit,'MAX_RECOVERY_BYTES',4096):
            state=self.report(Session(self.config),raw='x'*1000)
        self.assertFalse(state['participants'][0]['recovery_saved'])
        self.assertEqual(before,{path.name:path.read_bytes() for path in files})
        self.assertEqual(len(Session(self.config).list_exit_drafts()),2)

    def test_crash_pending_count_is_bounded_across_new_sessions(self):
        results=[self.crash_pending(quota='count') for _ in range(3)]
        self.assertEqual([row.returncode for row in results],[23,23,24])
        from companion import session_exit
        with patch.object(session_exit,'MAX_RECOVERY_RECORDS',2):
            state=self.report(Session(self.config))
        self.assertFalse(state['participants'][0]['recovery_saved'])
        self.assertEqual(len(list((self.directory/'exit-recovery').glob('*.json.pending'))),2)
        self.assertEqual(len(Session(self.config).list_exit_drafts()),2)

    def test_update_reserves_both_committed_and_interrupted_bytes_and_records(self):
        from companion import session_exit
        session=Session(self.config)
        self.report(session,raw='committed raw')
        path=self.directory/'exit-recovery'/(session.exit_recovery.identity('web-aaaaaaaa')+'.json')
        before=path.read_bytes()
        # Enough for one committed file, but not its interrupted replacement too.
        with patch.object(session_exit,'MAX_RECOVERY_RECORDS',1):
            state=self.report(session,revision=2,raw='current raw')
        self.assertFalse(state['participants'][0]['recovery_saved'])
        with patch.object(session_exit,'MAX_RECOVERY_BYTES',len(before)+100):
            state=self.report(session,revision=2,raw='current raw')
        self.assertFalse(state['participants'][0]['recovery_saved'])
        self.assertEqual(path.read_bytes(),before)
        self.assertFalse(path.with_name(path.name+'.pending').exists())

    def test_byte_quota_uses_physical_json_newlines_at_the_exact_boundary(self):
        from companion import session_exit
        first,second=self.journal(),self.journal()
        with patch.object(session_exit.time,'time',return_value=1234):
            first.checkpoint('web-aaaaaaaa',1,True,{'raw':'same'},'web','same')
            path=self.directory/'exit-recovery'/(first.identity('web-aaaaaaaa')+'.json')
            size=path.stat().st_size
            with patch.object(session_exit,'MAX_RECOVERY_BYTES',2*size-1):
                with self.assertRaisesRegex(ValueError,'空间已满'):
                    second.checkpoint('web-aaaaaaaa',1,True,{'raw':'same'},'web','same')
            with patch.object(session_exit,'MAX_RECOVERY_BYTES',2*size):
                self.assertTrue(second.checkpoint('web-aaaaaaaa',1,True,{'raw':'same'},'web','same'))
        self.assertEqual(sum(path.stat().st_size for path in (self.directory/'exit-recovery').glob('*.json')),2*size)

    def test_committed_and_pending_siblings_are_selected_and_archived_independently(self):
        result=self.crash_pending(initial=True,raw='pending newer raw')
        self.assertEqual(result.returncode,23,result.stderr.decode(errors='replace'))
        restarted=Session(self.config)
        rows=restarted.list_exit_drafts()
        self.assertEqual(len(rows),2)
        pending=next(row for row in rows if row['pending'])
        committed=next(row for row in rows if not row['pending'])
        self.assertEqual(pending['id'],committed['id']+'.pending')
        self.assertEqual(restarted.load_exit_draft(pending['id'])['draft']['numeric'][0]['raw']['power'],'pending newer raw')
        self.assertEqual(restarted.load_exit_draft(committed['id'])['draft']['numeric'][0]['raw']['power'],'committed raw')
        path=self.directory/'exit-recovery'/(committed['id']+'.json')
        before=path.read_bytes()
        restarted.set_exit_draft_lifecycle(pending['id'],'archived',pending['state_revision'])
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual([row['id'] for row in restarted.list_exit_drafts()],[committed['id']])

    def test_same_session_pending_blocks_overwrite_and_clear_until_explicit_archive(self):
        result=self.crash_pending(initial=True,raw='interrupted raw')
        self.assertEqual(result.returncode,23,result.stderr.decode(errors='replace'))
        j=self.journal()
        pending=next(row for row in j.list() if row['pending'])
        pending_path=self.directory/'exit-recovery'/(pending['id'][:-8]+'.json.pending')
        j.session_id=json.loads(pending_path.read_bytes())['session_id']
        paths=list((self.directory/'exit-recovery').glob('*.json*'))
        before={path.name:path.read_bytes() for path in paths}
        for dirty in (True,False):
            with self.assertRaisesRegex(ValueError,'中断副本'):
                j.checkpoint('web-aaaaaaaa',3,dirty,{'raw':'latest'},'web','current')
            self.assertEqual(before,{path.name:path.read_bytes() for path in paths})
        own_pending,=j.list()
        j.archive(own_pending['id'],own_pending['state_revision'])
        self.assertTrue(j.checkpoint('web-aaaaaaaa',3,True,{'raw':'latest'},'web','current'))
        self.assertEqual(j.load(pending['id'][:-8])['draft'],{'raw':'latest'})

    def test_damaged_interrupted_original_is_reported_and_kept_byte_for_byte(self):
        result=self.crash_pending(damaged=True)
        self.assertEqual(result.returncode,23,result.stderr.decode(errors='replace'))
        restarted=Session(self.config)
        row,=restarted.list_exit_drafts()
        self.assertTrue(row['pending']);self.assertTrue(row['error'])
        path=self.directory/'exit-recovery'/(row['id'][:-8]+'.json.pending')
        before=path.read_bytes()
        for action in ('load','archive'):
            with self.assertRaises(ValueError):
                if action=='load':restarted.load_exit_draft(row['id'])
                else:restarted.set_exit_draft_lifecycle(row['id'],'archived',row.get('state_revision'))
            self.assertEqual(path.read_bytes(),before)
        self.assertFalse(self.config.exists())
        self.assertEqual(restarted.exit_drafts.list(include_archived=True),[])
        from companion import session_exit
        with patch.object(session_exit,'MAX_RECOVERY_RECORDS',1):
            state=self.report(restarted)
        self.assertFalse(state['participants'][0]['recovery_saved'])
        self.assertEqual(path.read_bytes(),before)

    def test_pending_archive_copy_and_remove_failures_preserve_original(self):
        self.assertEqual(self.crash_pending().returncode,23)
        j=self.journal()
        row,=j.list()
        path=self.directory/'exit-recovery'/(row['id'][:-8]+'.json.pending')
        before=path.read_bytes()
        with patch.object(j.saved_drafts,'import_record',side_effect=OSError('synthetic disk full')):
            with self.assertRaises(OSError):j.archive(row['id'],row['state_revision'])
        self.assertEqual(path.read_bytes(),before)
        with patch.object(Path,'unlink',side_effect=OSError('synthetic remove denied')):
            with self.assertRaises(OSError):j.archive(row['id'],row['state_revision'])
        self.assertEqual(path.read_bytes(),before)
        archived,=j.saved_drafts.list(include_archived=True)
        self.assertEqual(j.saved_drafts.load(archived['id'])['draft'],j.load(row['id'])['draft'])

    def test_changed_pending_rejects_stale_archive_without_consuming_either_sibling(self):
        self.assertEqual(self.crash_pending(initial=True).returncode,23)
        j=self.journal()
        row=next(row for row in j.list() if row['pending'])
        path=self.directory/'exit-recovery'/(row['id'][:-8]+'.json.pending')
        value=json.loads(path.read_bytes())
        value['revision']+=1;value['record']['draft']['numeric'][0]['raw']['power']='later pending raw'
        path.write_text(json.dumps(value),encoding='utf-8')
        paths=list((self.directory/'exit-recovery').glob('*.json*'))
        before={path.name:path.read_bytes() for path in paths}
        with self.assertRaisesRegex(ValueError,'已更新'):j.archive(row['id'],row['state_revision'])
        self.assertEqual(before,{path.name:path.read_bytes() for path in paths})
        self.assertEqual(j.saved_drafts.list(include_archived=True),[])

    def test_pending_changed_during_archive_keeps_new_bytes_and_verified_old_copy(self):
        self.assertEqual(self.crash_pending().returncode,23)
        j=self.journal()
        row,=j.list()
        path=self.directory/'exit-recovery'/(row['id'][:-8]+'.json.pending')
        old=j.load(row['id'])
        value=json.loads(path.read_bytes())
        value['revision']+=1;value['record']['draft']['numeric'][0]['raw']['power']='external later raw'
        replacement=json.dumps(value).encode()
        original_import=j.saved_drafts.import_record
        def change_during_import(record):
            saved=original_import(record)
            path.write_bytes(replacement)
            return saved
        with patch.object(j.saved_drafts,'import_record',side_effect=change_during_import):
            with self.assertRaisesRegex(ValueError,'归档期间'):j.archive(row['id'],row['state_revision'])
        self.assertEqual(path.read_bytes(),replacement)
        archived,=j.saved_drafts.list(include_archived=True)
        self.assertEqual(j.saved_drafts.load(archived['id'])['draft'],old['draft'])

    def test_pending_archive_serializes_real_writer_and_stale_json_archive_keeps_new_checkpoint(self):
        self.assertEqual(self.crash_pending(initial=True,raw='interrupted raw').returncode,23)
        j=self.journal()
        rows=j.list()
        pending=next(row for row in rows if row['pending'])
        committed=next(row for row in rows if not row['pending'])
        script='''import json,sys,time
from pathlib import Path
from companion.session_exit import ExitDraftStore,ExitRecoveryJournal
directory=Path(sys.argv[1])
j=ExitRecoveryJournal(directory/'exit-recovery',ExitDraftStore(directory/'exit-drafts'))
j.session_id=json.loads((j.directory/(sys.argv[2]+'.json.pending')).read_bytes())['session_id']
(directory/'ready').write_text('ready')
deadline=time.monotonic()+5
while not (directory/'go').exists():
    if time.monotonic()>deadline:raise RuntimeError('go timeout')
    time.sleep(.01)
(directory/'attempting').write_text('attempting')
j.checkpoint('web-aaaaaaaa',3,True,{'raw':'newest checkpoint'},'web','new')
(directory/'done').write_text('done')
'''
        writer=subprocess.Popen([sys.executable,'-B','-c',script,str(self.directory),committed['id']],
            cwd=Path(__file__).resolve().parents[1],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        def finish_writer():
            if writer.poll() is None:writer.kill()
            writer.communicate(timeout=8)
        self.addCleanup(finish_writer)
        def wait_path(name):
            deadline=time.monotonic()+5
            while not (self.directory/name).exists():
                if time.monotonic()>deadline:self.fail(name+' timeout')
                time.sleep(.01)
        wait_path('ready')
        original_import=j.saved_drafts.import_record
        def while_archive_locked(record):
            (self.directory/'go').write_text('go')
            wait_path('attempting')
            time.sleep(.2)
            self.assertFalse((self.directory/'done').exists())
            return original_import(record)
        with patch.object(j.saved_drafts,'import_record',side_effect=while_archive_locked):
            archived=j.archive(pending['id'],pending['state_revision'])
        _,stderr=writer.communicate(timeout=8)
        self.assertEqual(writer.returncode,0,stderr.decode(errors='replace'))
        self.assertEqual(j.saved_drafts.load(archived['id'])['draft']['numeric'][0]['raw']['power'],'interrupted raw')
        self.assertEqual(j.load(committed['id'])['draft'],{'raw':'newest checkpoint'})
        with self.assertRaisesRegex(ValueError,'已更新'):j.archive(committed['id'],committed['state_revision'])
        self.assertEqual(j.load(committed['id'])['draft'],{'raw':'newest checkpoint'})

    def test_actual_process_crash_recovers_last_reported_raw_input_without_applying(self):
        script='''import os,sys
from pathlib import Path
from companion.service import Session
s=Session(Path(sys.argv[1]))
s.report_exit_surface('web-aaaaaaaa',7,True,draft={'format':2,'schema':'denghuo-web-session','numeric':[{'identity':'actors.buffs.healing','raw':{'power':'  -unfinished\\t  '}}]},kind='web',label='原始数值')
os._exit(23)
'''
        result=subprocess.run([sys.executable,'-B','-c',script,str(self.config)],cwd=Path(__file__).resolve().parents[1],capture_output=True)
        self.assertEqual(result.returncode,23,result.stderr.decode(errors='replace'))
        restarted=Session(self.config)
        rows=restarted.list_exit_drafts()
        self.assertEqual(len(rows),1,'a reported dirty draft must survive a real service crash')
        self.assertTrue(rows[0]['recovery'])
        record=restarted.load_exit_draft(rows[0]['id'])
        self.assertEqual(record['draft']['numeric'][0]['raw']['power'],'  -unfinished\t  ')
        self.assertFalse(self.config.exists(),'recovery must not apply configuration or write game data')
        self.assertEqual(restarted.exit_status()['participants'],[])

    def test_each_surface_and_session_has_its_own_revision_and_recovery(self):
        first=Session(self.config)
        self.report(first,'a',2,raw='first-a')
        self.report(first,'b',1,raw='first-b')
        second=Session(self.config)
        self.assertEqual(len(second.list_exit_drafts()),2)
        self.report(second,'a',1,raw='second-a')
        with self.assertRaises(ValueError):self.report(first,'a',1,raw='stale')
        with self.assertRaises(ValueError):self.report(first,'a',2,raw='same-revision-changed')
        self.report(first,'a',3,raw='new-first-a')
        third=Session(self.config)
        raw={third.load_exit_draft(row['id'])['draft']['numeric'][0]['raw']['power'] for row in third.list_exit_drafts()}
        self.assertEqual(raw,{'new-first-a','first-b','second-a'})
        self.report(second,'a',2,False,raw='second-a')
        final=Session(self.config)
        self.assertEqual(len(final.list_exit_drafts()),2,'cleaning one session must not clear another session')

    def test_identical_reports_do_not_rewrite_and_new_revision_retries_failed_storage(self):
        session=Session(self.config)
        with patch('companion.session_exit.atomic_json',side_effect=OSError('synthetic disk full')):
            state=self.report(session)
        own=state['participants'][0]
        self.assertTrue(own['dirty']);self.assertFalse(own['has_recovery_draft'])
        self.assertIn('自动保留',own['recovery_error'])
        self.assertEqual(Session(self.config).list_exit_drafts(),[])
        state=self.report(session)
        self.assertTrue(state['participants'][0]['has_recovery_draft'])
        self.assertEqual(state['participants'][0]['recovery_error'],'')
        with patch('companion.session_exit.atomic_json',side_effect=AssertionError('identical heartbeat must not write')), \
                patch.object(session.exit_recovery,'_storage_lock',side_effect=AssertionError('identical heartbeat must not acquire a disk lock')):
            self.report(session)
        restarted=Session(self.config)
        self.assertEqual(len(restarted.list_exit_drafts()),1)

    def test_cancel_keeps_recovery_and_explicit_discard_clears_only_current_surface(self):
        session=Session(self.config)
        self.report(session)
        request=session.request_exit('web-aaaaaaaa')
        session.acknowledge_exit(request['id'],'web-aaaaaaaa','cancel',1)
        self.assertEqual(len(Session(self.config).list_exit_drafts()),1)
        request=session.request_exit('web-aaaaaaaa')
        with patch.object(session.exit_coordinator,'_finish_if_ready'):
            session.acknowledge_exit(request['id'],'web-aaaaaaaa','discard',1)
        self.assertEqual(Session(self.config).list_exit_drafts(),[])

    def test_archiving_recovery_preserves_a_verified_durable_raw_copy(self):
        original=Session(self.config)
        self.report(original,raw='  invalid 9x  ')
        restarted=Session(self.config)
        row=restarted.list_exit_drafts()[0]
        raw=restarted.load_exit_draft(row['id'])['draft']
        result=restarted.exit_action({'action':'draft-state','id':row['id'],'state':'archived','expected_revision':row['state_revision']})
        self.assertEqual(result['draft_state']['state'],'archived')
        self.assertEqual(restarted.list_exit_drafts(),[])
        archived=restarted.list_exit_drafts(include_archived=True)
        self.assertEqual(len(archived),1);self.assertFalse(archived[0].get('recovery',False))
        self.assertEqual(restarted.load_exit_draft(archived[0]['id'])['draft'],raw)
        self.assertFalse((self.directory/'exit-recovery'/(row['id']+'.json')).exists())

    def test_stale_archive_preserves_a_later_checkpoint(self):
        original=Session(self.config)
        self.report(original,raw='first')
        restarted=Session(self.config)
        row=restarted.list_exit_drafts()[0]
        self.report(original,revision=2,raw='newer')
        with self.assertRaises(ValueError):
            restarted.exit_action({'action':'draft-state','id':row['id'],'state':'archived','expected_revision':row['state_revision']})
        self.assertEqual(restarted.load_exit_draft(row['id'])['draft']['numeric'][0]['raw']['power'],'newer')

    def test_recovery_capacity_error_is_visible_and_existing_originals_remain(self):
        from companion import session_exit
        session=Session(self.config)
        with patch.object(session_exit,'MAX_RECOVERY_RECORDS',1):
            first=self.report(session,'a',raw='preserved')
            self.assertTrue(first['participants'][0]['has_recovery_draft'])
            second=self.report(session,'b',raw='not persisted')
        failed=next(row for row in second['participants'] if row['surface_id']=='web-bbbbbbbb')
        self.assertFalse(failed['has_recovery_draft']);self.assertIn('自动保留',failed['recovery_error'])
        restarted=Session(self.config)
        self.assertEqual(len(restarted.list_exit_drafts()),1)
        self.assertEqual(restarted.load_exit_draft(restarted.list_exit_drafts()[0]['id'])['draft']['numeric'][0]['raw']['power'],'preserved')

    def test_discarded_revision_is_not_recreated_by_a_confirming_heartbeat(self):
        session=Session(self.config)
        self.report(session,'a')
        self.report(session,'b')
        request=session.request_exit('web-aaaaaaaa')
        session.acknowledge_exit(request['id'],'web-aaaaaaaa','discard',1)
        self.report(session,'a')
        restarted=Session(self.config)
        self.assertEqual([row['surface_id'] for row in restarted.list_exit_drafts()],['web-bbbbbbbb'])
        session.acknowledge_exit(request['id'],'web-bbbbbbbb','cancel',1)
        self.report(session,'a')
        self.assertEqual(len(Session(self.config).list_exit_drafts()),2,'cancelled exit keeps all live raw drafts recoverable')

    def test_failed_offline_checkpoint_clear_does_not_acknowledge_or_finish(self):
        session=Session(self.config)
        self.report(session)
        session.unregister_exit_surface('web-aaaaaaaa',1,True,draft=None)
        request=session.request_exit('native')
        with patch.object(session.exit_coordinator,'checkpoint',side_effect=OSError('synthetic denied clear')):
            with self.assertRaises(OSError):
                session.exit_coordinator.resolve_offline(request['id'],'web-aaaaaaaa','discard',1)
        self.assertIsNone(session.exit_status()['participants'][0]['ack'])
        self.assertEqual(session.exit_status()['phase'],'confirming')
        self.assertEqual(len(Session(self.config).list_exit_drafts()),1)

    def test_unchanged_heartbeat_detects_corrupted_disk_copy_and_preserves_it(self):
        session=Session(self.config)
        self.report(session,raw='current raw')
        identity=session.exit_recovery.identity('web-aaaaaaaa')
        path=self.directory/'exit-recovery'/(identity+'.json')
        damaged=b'{incomplete external replacement'
        path.write_bytes(damaged)
        state=self.report(session,raw='current raw')
        own=state['participants'][0]
        self.assertFalse(own['has_recovery_draft'])
        self.assertFalse(own['recovery_saved'])
        self.assertTrue(own['recovery_error'])
        self.assertEqual(path.read_bytes(),damaged)
        self.assertEqual(session.exit_coordinator.surfaces['web-aaaaaaaa']['draft']['numeric'][0]['raw']['power'],'current raw')
        saved=session.save_exit_draft('web-aaaaaaaa','web','explicit current copy',session.exit_coordinator.surfaces['web-aaaaaaaa']['draft'])
        self.assertEqual(session.exit_drafts.load(saved['id'])['draft']['numeric'][0]['raw']['power'],'current raw')

    def test_unchanged_heartbeat_detects_valid_old_bytes_replacing_current_checkpoint(self):
        session=Session(self.config)
        self.report(session,revision=1,raw='older raw')
        identity=session.exit_recovery.identity('web-aaaaaaaa')
        path=self.directory/'exit-recovery'/(identity+'.json')
        older=path.read_bytes()
        self.report(session,revision=2,raw='current raw')
        path.write_bytes(older)
        state=self.report(session,revision=2,raw='current raw')
        own=state['participants'][0]
        self.assertFalse(own['has_recovery_draft'])
        self.assertFalse(own['recovery_saved'])
        self.assertIn('副本已变化',own['recovery_error'])
        self.assertEqual(path.read_bytes(),older)
        self.assertEqual(session.exit_coordinator.surfaces['web-aaaaaaaa']['draft']['numeric'][0]['raw']['power'],'current raw')

    def test_storage_lock_is_released_after_a_process_crash(self):
        script='''import os,sys
from pathlib import Path
from companion.session_exit import ExitDraftStore,ExitRecoveryJournal
j=ExitRecoveryJournal(Path(sys.argv[1])/'exit-recovery',ExitDraftStore(Path(sys.argv[1])/'exit-drafts'))
with j._storage_lock():os._exit(23)
'''
        result=subprocess.run([sys.executable,'-B','-c',script,str(self.directory)],cwd=Path(__file__).resolve().parents[1],capture_output=True)
        self.assertEqual(result.returncode,23,result.stderr.decode(errors='replace'))
        state=self.report(Session(self.config))
        self.assertTrue(state['participants'][0]['has_recovery_draft'])


if __name__=='__main__':unittest.main()
