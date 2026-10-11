import copy
import json
import multiprocessing
from pathlib import Path
import tempfile
import unittest

from companion.play_state import PlayPreferences, SnapshotNotices, place, risk_summary, source_label, validate_preferences


def snapshot(tips=(), hp=30, modified=1, **changes):
    row = {'settings': {'save_root':'C:/fixture', 'mode':'save'}, 'active_slot':1, 'run_id':'run-a',
           'data': {'hero': {'hp':hp,'ht':30}, 'buffs':[], 'tips':list(tips)},
           'modified':modified, 'stale':False, 'error':None, 'age_seconds':2}
    row.update(changes)
    return row


FIRE = {'id':'burning','title':'燃烧','severity':'warning'}
CRITICAL = {'id':'critical_hp','title':'危险血量','severity':'critical'}


def save_preferences_while_held(directory, ready, release, results):
    try:
        preferences = PlayPreferences(directory)
        calls = 0
        def check():
            nonlocal calls
            calls += 1
            if calls == 2:
                ready.set()
                if not release.wait(10):
                    raise RuntimeError('test owner release timed out')
        result = preferences.update({'enabled': False}, expected_generation=0, check_current=check)
        results.put(('saved', result))
    except Exception as exc:
        results.put(('error', repr(exc)))


class PlayStateTests(unittest.TestCase):
    def test_independent_owners_reject_busy_and_stale_saves_then_reload(self):
        with tempfile.TemporaryDirectory() as folder:
            first, second = PlayPreferences(folder), PlayPreferences(folder)
            draft = {'font_scale': 1.5}
            before = second.published()
            with first._storage_lock():
                with self.assertRaisesRegex(ValueError, '另一个助手'):
                    second.update(draft, expected_generation=0)
                with self.assertRaisesRegex(ValueError, '另一个助手'):
                    second.reload(expected_generation=0)
                self.assertEqual(second.published(), before)
                self.assertFalse(first.path.exists())
            first.update({'enabled': False}, expected_generation=0)
            saved = first.path.read_bytes()
            with self.assertRaisesRegex(ValueError, '文件刚被修改'):
                second.update(draft, expected_generation=0)
            self.assertEqual(second.published(), before)
            self.assertEqual(first.path.read_bytes(), saved)
            self.assertEqual(draft, {'font_scale': 1.5})
            second.reload(expected_generation=0)
            second.update(draft, expected_generation=1)
            reopened = PlayPreferences(folder)
            self.assertFalse(reopened.values['enabled'])
            self.assertEqual(reopened.values['font_scale'], 1.5)

    def test_separate_process_owner_holds_lock_through_final_replacement(self):
        with tempfile.TemporaryDirectory() as folder:
            second = PlayPreferences(folder)
            ctx = multiprocessing.get_context('spawn')
            ready, release, results = ctx.Event(), ctx.Event(), ctx.Queue()
            owner = ctx.Process(target=save_preferences_while_held, args=(folder, ready, release, results))
            owner.start()
            try:
                self.assertTrue(ready.wait(10), 'first owner must reach its final commit check')
                with self.assertRaisesRegex(ValueError, '另一个助手'):
                    second.update({'font_scale': 1.5}, expected_generation=0)
                self.assertEqual(second.generation, 0)
                self.assertFalse(second.path.exists())
            finally:
                release.set()
                owner.join(10)
            self.assertFalse(owner.is_alive())
            self.assertEqual(owner.exitcode, 0)
            status, result = results.get(timeout=3)
            results.close()
            results.join_thread()
            self.assertEqual(status, 'saved', result)
            self.assertEqual(result['revision'], 1)
            with self.assertRaisesRegex(ValueError, '文件刚被修改'):
                second.update({'font_scale': 1.5}, expected_generation=0)
            second.reload(expected_generation=0)
            second.update({'font_scale': 1.5}, expected_generation=1)
            reopened = PlayPreferences(folder)
            self.assertFalse(reopened.values['enabled'])
            self.assertEqual(reopened.values['font_scale'], 1.5)

    def test_preferences_reject_invalid_or_duplicate_bindings(self):
        for patch in ({'font_scale':float('nan')},{'opacity':.1},{'offset_x':True}, {'enabled':1},
                      {'anchor':'center'}, {'bindings':{'quick':'Ctrl+Alt+L'}}, {'unexpected':1}):
            with self.subTest(patch=patch),self.assertRaises(ValueError):validate_preferences(patch)
        value=validate_preferences({'bindings':{'quick':'Alt+Shift+F2','capture':''}})
        self.assertEqual(value['bindings']['quick'],'Alt+Shift+F2')
        self.assertEqual(value['bindings']['capture'],'')

    def test_corrupt_preferences_are_preserved_on_explicit_repair(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'play-mode.json';path.write_bytes(b'broken original')
            prefs=PlayPreferences(folder)
            self.assertFalse(prefs.values['enabled']);self.assertTrue(prefs.error)
            prefs.update({'enabled':True})
            self.assertEqual(next(Path(folder).glob('play-mode.recovery-*.json')).read_bytes(),b'broken original')
            self.assertTrue(PlayPreferences(folder).values['enabled'])
            before=path.read_bytes()
            with self.assertRaises(ValueError):prefs.update({'opacity':0})
            self.assertEqual(path.read_bytes(),before)

    def test_startup_old_manual_and_new_run_never_pop(self):
        notices=SnapshotNotices()
        self.assertIsNone(notices.update(snapshot([FIRE]),0))
        self.assertIsNone(notices.update(snapshot([],modified=2),1))
        self.assertIsNone(notices.update(snapshot([CRITICAL],modified=3,stale=True),2))
        self.assertIsNone(notices.update(snapshot([CRITICAL],modified=4),3))
        self.assertIsNone(notices.update(snapshot([FIRE],modified=5,run_id='run-b'),4))
        manual=snapshot([CRITICAL],modified=6);manual['settings']['mode']='manual'
        self.assertIsNone(notices.update(manual,5))
        self.assertIsNone(notices.update(snapshot([CRITICAL],modified=7),6))

    def test_new_risk_is_single_short_notice_not_repeated_each_poll(self):
        notices=SnapshotNotices();notices.update(snapshot(),0)
        current=snapshot([FIRE],modified=2)
        self.assertEqual(notices.update(current,1)['id'],'burning')
        self.assertEqual(notices.until,6)
        current['modified']=3
        self.assertIsNotNone(notices.update(current,3));self.assertEqual(notices.until,6)
        self.assertIsNone(notices.update(current,6))
        notices.update(snapshot([],modified=4),7)
        self.assertIsNotNone(notices.update(snapshot([FIRE],modified=5),8))
        self.assertIsNone(notices.update(snapshot([FIRE],modified=5,error='read error'),9))

    def test_disabled_alerts_and_staleness_cancel_immediately(self):
        notices=SnapshotNotices();notices.update(snapshot(),0)
        self.assertIsNotNone(notices.update(snapshot([CRITICAL],modified=2),1))
        self.assertIsNone(notices.update(snapshot([CRITICAL],modified=2),2,enabled=False))
        self.assertIsNone(notices.update(snapshot([CRITICAL],modified=2),3))

    def test_new_content_revision_with_same_timestamp_notifies_once(self):
        notices=SnapshotNotices()
        notices.update(snapshot(modified=500,revision=40),0)
        fire=snapshot([FIRE],modified=500,revision=41)
        self.assertEqual(notices.update(fire,1)['id'],'burning')
        self.assertEqual(notices.until,6)
        self.assertEqual(notices.update(copy.deepcopy(fire),2)['id'],'burning')
        self.assertEqual(notices.until,6,'polling the same content must not extend the notice')
        self.assertIsNone(notices.update(snapshot(modified=500,revision=42),3))
        self.assertEqual(notices.update(snapshot([CRITICAL],modified=500,revision=43),4)['id'],'critical_hp')
        self.assertIsNone(notices.update(snapshot([FIRE],modified=500,revision=44,run_id='run-b'),5))

    def test_revision_changes_do_not_replay_stale_or_disabled_risks(self):
        notices=SnapshotNotices()
        notices.update(snapshot(modified=500,revision=1),0)
        self.assertIsNone(notices.update(snapshot([FIRE],modified=500,revision=2,stale=True),1))
        self.assertIsNone(notices.update(snapshot([FIRE],modified=500,revision=3),2))
        notices.update(snapshot(modified=500,revision=4),3)
        self.assertIsNone(notices.update(snapshot([CRITICAL],modified=500,revision=5),4,enabled=False))
        self.assertIsNone(notices.update(snapshot([CRITICAL],modified=500,revision=6),5))
        notices.update(snapshot(modified=500,revision=7),6)
        self.assertEqual(notices.update(snapshot([CRITICAL],modified=500,revision=8),7)['id'],'critical_hp')

    def test_risk_respects_action_locks_and_water_limits(self):
        data={'buffs':[{'kind':'Levitation'}]}
        self.assertIn('不能灭火',risk_summary(data,FIRE))
        data['buffs'].append({'kind':'Paralysis'})
        self.assertIn('暂不能移动或用物品',risk_summary(data,FIRE))
        self.assertIn('水不能',risk_summary({'buffs':[]},{'id':'corrosion'}))
        self.assertIn('先受到一次伤害',risk_summary({'buffs':[]},FIRE))

    def test_positions_support_negative_monitor_coordinates(self):
        for anchor in ('top_left','top_right','bottom_left','bottom_right'):
            prefs=validate_preferences({'anchor':anchor,'offset_x':16000,'offset_y':16000})
            x,y=place((-1920,-100,0,980),580,130,prefs,2)
            self.assertGreaterEqual(x,-1920);self.assertLessEqual(x+580,0)
            self.assertGreaterEqual(y,-100);self.assertLessEqual(y+130,980)

    def test_source_age_manual_and_failed_read_are_unambiguous(self):
        row=snapshot(age_seconds=123,stale=True)
        self.assertEqual(source_label(row),'旧存档 · 2分钟前')
        row['settings']['mode']='manual'
        self.assertEqual(source_label(row),'手填局势已过期')
        row['error']='broken'
        self.assertEqual(source_label(row),'局势不可读')


if __name__=='__main__':unittest.main()
