"""Real abrupt exits use private synthetic saves, never a running game or personal data."""
import gzip
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
import uuid

from companion import backup_recovery as recovery
from companion import backup_workflows as workflows
from companion.backups import BackupManager, atomic_json


def write_save(root, hp, slot=1, extra=False):
    folder = root / f'game{slot}'
    folder.mkdir(parents=True, exist_ok=True)
    game = {'version': 922, 'depth': 2, 'branch': 0, 'seed': 9, 'generated_levels': [2],
            'hero': {'class': 'MAGE', 'HP': hp, 'HT': 30, 'STR': 10, 'lvl': 2,
                     'inventory': [], 'buffs': []}}
    level = {'__className': 'com.shatteredpixel.shatteredpixeldungeon.levels.SewerLevel',
             'version': 922, 'width': 4, 'height': 4, 'map': [4] * 16,
             'visited': [False] * 16, 'mapped': [False] * 16}
    for name, value in (('game.dat', game), ('depth2.dat', {'level': level})):
        path = folder / name
        path.write_bytes(gzip.compress(json.dumps(value).encode(), mtime=0))
        os.utime(path, (1800000000 + hp, 1800000000 + hp))
    if extra:
        (folder / 'nested' / 'empty').mkdir(parents=True, exist_ok=True)
        (folder / 'nested' / 'original.bin').write_bytes(b'Complete original bytes\x00\xff')
    return folder


def contents(folder):
    if not folder.exists():
        return None
    return {'files': {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in folder.rglob('*') if p.is_file()},
            'directories': sorted(p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_dir())}


def manager(case):
    return BackupManager(case / 'backups', clock=lambda: 1800000100, closed_check=lambda: None)


def setup_case(case, kind):
    root = case / 'saves'
    root.mkdir(parents=True)
    m = manager(case)
    write_save(root, 20)
    archive = m.capture(root, 1)
    write_save(root, 9, extra=True)
    if kind == 'undo':
        m.restore(root, {**archive, 'confirm': '恢复槽位 1'})
        write_save(root, 15, extra=True)
    atomic_json(case / 'settings.json', {'save_root': str(root), 'slot': 1})
    before = contents(root / 'game1')
    if kind == 'restore':
        _, raw, _, _ = m.checked_archive(root, archive['id'], 1)
        target = {'files': {name: hashlib.sha256(value).hexdigest() for name, value in raw.items()}, 'directories': []}
    else:
        target = contents(root / m.journals(root)[-1]['original'])
    return root, before, target


def execute_choice(m, root, choice):
    row = m.recovery_status(root)['pending'][0]
    view = m.recovery_preview(root, row)
    selected = next(c for c in view['choices'] if c['choice'] == choice)
    return m.recovery_execute(root, {**row, 'choice': choice, 'expected': view['expected'],
                                   'confirmed': True, 'confirm': selected['confirm_phrase']})


def child(case, kind, action, cut, choice):
    m, root = manager(case), case / 'saves'
    real = recovery._move
    calls = []
    def move(source, target):
        real(source, target)
        calls.append([source.name, target.name])
        if len(calls) == cut:
            os._exit(70 + cut)
    recovery._move = move
    if action == 'operation' and cut == 0:
        recovery.run = lambda *_: os._exit(70)
    if action == 'recover':
        execute_choice(m, root, choice)
    elif kind == 'restore':
        row = m.history(root)[0]
        m.restore(root, {**row, 'confirm': '恢复槽位 1',
                         'expected_current': m.preview(root, row)['expected_current']})
    else:
        row = m.undo_status(root)[0]
        m.undo(root, {**row, 'confirm': '撤回槽位 1',
                      'expected_current': m.undo_preview(root, row)['expected_current']})
    raise AssertionError('The real directory move cut point was not reached')


class BackupRecoveryTests(unittest.TestCase):
    def setUp(self):
        evidence = os.environ.get('DENGHUO_RECOVERY_EVIDENCE')
        if evidence:
            self.base = Path(evidence).resolve() / (self._testMethodName + '-' + uuid.uuid4().hex[:8])
            self.base.mkdir(parents=True, exist_ok=False)
        else:
            temporary = tempfile.TemporaryDirectory(prefix='denghuo-recovery-test-')
            self.addCleanup(temporary.cleanup)
            self.base = Path(temporary.name).resolve()
        self.results = []
        if evidence:
            self.addCleanup(lambda: atomic_json(self.base / 'result.json', self.results))

    def crash(self, case, kind, cut, *, action='operation', choice='continue'):
        env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1])}
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--child', str(case),
                                 kind, action, str(cut), choice], capture_output=True, text=True,
                                env=env, timeout=20)
        self.assertEqual(result.returncode, 70 + cut, result.stdout + result.stderr)
        self.results.append({'case': case.name, 'kind': kind, 'action': action, 'choice': choice,
                             'cut': cut, 'returncode': result.returncode,
                             'folders': {p.name: contents(p) for p in (case / 'saves').iterdir() if p.is_dir()}})

    def test_real_restore_and_undo_abrupt_exit_at_both_moves_can_continue_or_cancel(self):
        for kind in ('restore', 'undo'):
            for cut in (1, 2):
                for choice in ('continue', 'cancel'):
                    with self.subTest(kind=kind, cut=cut, choice=choice):
                        case = self.base / f'{kind}-{cut}-{choice}'
                        root, before, target = setup_case(case, kind)
                        self.crash(case, kind, cut)
                        restarted = manager(case)
                        pending = restarted.recovery_status(root)['pending']
                        self.assertEqual(len(pending), 1)
                        view = restarted.recovery_preview(root, pending[0])
                        self.assertEqual(view['layout'], 'gap' if cut == 1 else 'target')
                        self.assertEqual(restarted.undo_status(root), [])
                        copies = [contents(p) for p in root.iterdir() if p.is_dir()]
                        self.assertIn(before, copies)
                        self.assertIn(target, copies)
                        result = execute_choice(restarted, root, choice)
                        self.assertTrue(result['ok'])
                        self.assertEqual(contents(root / 'game1'), target if choice == 'continue' else before)
                        self.assertEqual(restarted.recovery_status(root)['pending'], [])
                        journals = restarted.journals(root)
                        self.assertEqual(len([r for r in journals if r['id'] == pending[0]['id']]),
                                         int(choice == 'continue'))
                        self.assertEqual(len(restarted.undo_status(root)),
                                         int((kind == 'restore' and choice == 'continue') or
                                             (kind == 'undo' and choice == 'cancel')))
                        copies = [contents(p) for p in root.iterdir() if p.is_dir()]
                        self.assertIn(before, copies)
                        self.assertIn(target, copies)
                        self.results[-1].update(recovered=result, journal_ids=[r['id'] for r in journals],
                                                final_folders={p.name: contents(p) for p in root.iterdir() if p.is_dir()})

    def test_recovery_itself_can_exit_at_each_forward_and_reverse_move(self):
        for kind in ('restore', 'undo'):
            for choice in ('continue', 'cancel'):
                for cut in (1, 2):
                    with self.subTest(kind=kind, choice=choice, cut=cut):
                        case = self.base / f'again-{kind}-{choice}-{cut}'
                        root, before, target = setup_case(case, kind)
                        self.crash(case, kind, 0 if choice == 'continue' else 2)
                        self.crash(case, kind, cut, action='recover', choice=choice)
                        restarted = manager(case)
                        result = execute_choice(restarted, root, choice)
                        self.assertTrue(result['ok'])
                        self.assertEqual(contents(root / 'game1'), target if choice == 'continue' else before)
                        self.assertEqual(restarted.recovery_status(root)['pending'], [])
                        copies = [contents(p) for p in root.iterdir() if p.is_dir()]
                        self.assertIn(before, copies)
                        self.assertIn(target, copies)
                        self.results[-1].update(recovered=result)

    def test_committed_pending_can_finish_after_a_later_game_save_without_moving_it(self):
        for kind in ('restore', 'undo'):
            case = self.base / kind
            root, _, _ = setup_case(case, kind)
            m = manager(case)
            with patch.object(recovery, '_finish', side_effect=OSError('interrupted bookkeeping')):
                with self.assertRaises(OSError):
                    if kind == 'restore':
                        m.restore(root, {**m.history(root)[0], 'confirm': '恢复槽位 1'})
                    else:
                        m.undo(root, {**m.undo_status(root)[0], 'confirm': '撤回槽位 1'})
            write_save(root, 7, extra=True)
            current = contents(root / 'game1')
            journals = (m.scope(root) / 'restores.json').read_bytes()
            restarted = manager(case)
            view = restarted.recovery_preview(root, restarted.recovery_status(root)['pending'][0])
            self.assertEqual([c['choice'] for c in view['choices']], ['finish'])
            self.assertTrue(view['current_changed'])
            restarted.closed_check = lambda: (_ for _ in ()).throw(AssertionError('finish must not require game exit'))
            with patch.object(recovery, '_move', side_effect=AssertionError('finish must not move a directory')):
                execute_choice(restarted, root, 'finish')
            self.assertEqual(contents(root / 'game1'), current)
            self.assertEqual((m.scope(root) / 'restores.json').read_bytes(), journals)
            self.assertEqual(restarted.recovery_status(root)['pending'], [])

    def test_changed_active_original_target_and_empty_directory_are_refused_and_protected(self):
        for role in ('active', 'incoming', 'preserved', 'empty-directory'):
            case = self.base / role
            root, _, _ = setup_case(case, 'restore')
            self.crash(case, 'restore', 2 if role == 'active' else 1)
            m = manager(case)
            row = recovery.records(m, root)['1']
            path = root / ('game1' if role == 'active' else row['incoming'] if role == 'incoming' else row['preserved'])
            if role == 'empty-directory':
                (path / 'new-empty').mkdir()
            else:
                (path / 'external.bin').write_bytes(b'external data must remain')
            before = {p.name: contents(p) for p in root.iterdir() if p.is_dir()}
            with self.assertRaisesRegex(ValueError, '变化'):
                m.recovery_preview(root, row)
            with self.assertRaises(ValueError):
                m.restore(root, {**m.history(root)[0], 'confirm': '恢复槽位 1'})
            inventory = workflows.storage_inventory(m, root)
            protected = [r for g in inventory['groups'] for r in g['rows'] if r.get('recovery_protected')]
            self.assertTrue(protected)
            self.assertTrue(all(r['protected'] and not r['reclaimable'] for r in protected))
            self.assertEqual({p.name: contents(p) for p in root.iterdir() if p.is_dir()}, before)

    def test_corrupt_pending_blocks_swaps_capture_and_reclaim_without_guessing(self):
        case = self.base / 'corrupt'
        root, _, _ = setup_case(case, 'restore')
        m = manager(case)
        (m.scope(root) / recovery.INDEX).write_bytes(b'{broken')
        self.assertFalse(m.recovery_status(root)['available'])
        self.assertEqual(m.recovery_status(root)['blocked_slots'], list(range(1, 7)))
        for operation in (lambda: m.capture(root, 1),
                          lambda: m.restore(root, {**m.history(root)[0], 'confirm': '恢复槽位 1'})):
            with self.assertRaisesRegex(ValueError, '关联无法核对'):
                operation()
        inventory = workflows.storage_inventory(m, root)
        self.assertTrue(all(r['protected'] and not r['reclaimable'] for g in inventory['groups'] for r in g['rows']))
        m.tick(root)
        self.assertIn('恢复关联', m.health_status(root, 1)['error'])

    def test_pending_slot_pause_is_honest_and_another_slot_keeps_working(self):
        case = self.base / 'monitor'
        root, _, _ = setup_case(case, 'restore')
        self.crash(case, 'restore', 1)
        write_save(root, 10, slot=2)
        m = manager(case)
        m.tick(root, force=True)
        self.assertIn('未完成', m.health_status(root, 1)['error'])
        self.assertTrue(m.health_status(root, 2)['last_save_protected'])
        pending = m.recovery_status(root)['pending'][0]
        row2 = next(row for row in m.history(root) if row['slot'] == 2)
        m.restore(root, {**row2, 'confirm': '恢复槽位 2'})
        execute_choice(m, root, 'continue')
        self.assertEqual(len([r for r in m.journals(root) if r['id'] == pending['id']]), 1)

    def test_cancel_keeps_the_previous_undo_relationship_and_prepared_target(self):
        case = self.base / 'prior-undo'
        root, _, _ = setup_case(case, 'undo')
        m = manager(case)
        before_journals = (m.scope(root) / 'restores.json').read_bytes()
        before = contents(root / 'game1')
        self.crash(case, 'restore', 2)
        row = recovery.records(m, root)['1']
        target = contents(root / 'game1')
        execute_choice(manager(case), root, 'cancel')
        self.assertEqual((m.scope(root) / 'restores.json').read_bytes(), before_journals)
        self.assertEqual(contents(root / 'game1'), before)
        self.assertEqual(contents(root / row['incoming']), target)
        self.assertEqual(len(m.undo_status(root)), 1)

    def test_final_capture_skips_only_pending_slot_and_captures_the_other_real_slot(self):
        case = self.base / 'final-two-slots'
        root, _, _ = setup_case(case, 'restore')
        self.crash(case, 'restore', 1)
        write_save(root, 12, slot=2)
        m = manager(case)
        pending = recovery.records(m, root)['1']
        snapshots = {name: contents(root / pending[name]) for name in ('incoming', 'preserved')}
        deadline = time.monotonic() + 3
        observed = []
        with patch.object(m, 'capture', wraps=m.capture) as capture:
            result = m.final_capture(root, deadline, on_capture=observed.append)
        self.assertFalse(result['ok'])
        self.assertEqual(result['state'], 'partial')
        self.assertEqual([r['slot'] for r in result['captured']], [2])
        self.assertEqual(observed, result['captured'])
        self.assertEqual(capture.call_count, 1)
        self.assertEqual(capture.call_args.kwargs['deadline'], deadline)
        self.assertIn('槽位 1', result['error'])
        self.assertIn('未完成', result['error'])
        self.assertFalse((root / 'game1').exists())
        self.assertEqual(recovery.records(m, root)['1'], pending)
        self.assertEqual({name: contents(root / pending[name]) for name in snapshots}, snapshots)
        self.assertTrue(any(r['slot'] == 2 for r in m.events(root)))

        (root / 'game2').rename(case / 'kept-slot-two')
        failed = m.final_capture(root, time.monotonic() + 1)
        self.assertEqual(failed['state'], 'failed')
        self.assertEqual(failed['captured'], [])
        self.assertIn('未完成', failed['error'])

        (m.scope(root) / recovery.INDEX).write_text('{broken', encoding='utf-8')
        write_save(root, 13, slot=2)
        with patch.object(m, 'capture', wraps=m.capture) as capture:
            corrupt = m.final_capture(root, time.monotonic() + 1)
        self.assertEqual(corrupt['state'], 'failed')
        self.assertEqual(corrupt['captured'], [])
        self.assertEqual(capture.call_count, 0)
        self.assertIn('恢复关联无法核对', corrupt['error'])

    def test_absent_before_or_target_slots_and_two_empty_sides_remain_explicit(self):
        for mode in ('restore-absent', 'undo-absent-before', 'undo-absent-target', 'undo-both-absent'):
            for choice in ('continue', 'cancel'):
                case = self.base / f'{mode}-{choice}'
                root, _, _ = setup_case(case, 'undo' if mode == 'undo-absent-before' else 'restore')
                m = manager(case)
                if mode in ('undo-absent-target', 'undo-both-absent'):
                    (root / 'game1').rename(case / 'kept-initial-progress')
                    m.restore(root, {**m.history(root)[0], 'confirm': '恢复槽位 1'})
                if mode in ('restore-absent', 'undo-absent-before', 'undo-both-absent'):
                    (root / 'game1').rename(case / 'kept-before-progress')
                before = contents(root / 'game1')
                kind = 'restore' if mode == 'restore-absent' else 'undo'
                target = None if mode in ('undo-absent-target', 'undo-both-absent') else (
                    contents(root / m.journals(root)[-1]['original']) if kind == 'undo' else None)
                self.crash(case, kind, 0 if mode == 'undo-both-absent' else 1)
                restarted = manager(case)
                row = recovery.records(restarted, root)['1']
                if kind == 'restore':
                    target = contents(root / 'game1')
                execute_choice(restarted, root, choice)
                self.assertEqual(contents(root / 'game1'), target if choice == 'continue' else before)
                self.assertEqual(restarted.recovery_status(root)['pending'], [])

    def test_finish_retains_protection_if_the_committed_original_itself_changes(self):
        case = self.base / 'finish-original-changed'
        root, _, _ = setup_case(case, 'restore')
        m = manager(case)
        with patch.object(recovery, '_finish', side_effect=OSError('bookkeeping interrupted')):
            with self.assertRaises(OSError):
                m.restore(root, {**m.history(root)[0], 'confirm': '恢复槽位 1'})
        row = recovery.records(m, root)['1']
        (root / row['preserved'] / 'new-empty').mkdir()
        with self.assertRaisesRegex(ValueError, '保留副本'):
            m.recovery_preview(root, row)
        self.assertEqual(m.recovery_status(root)['blocked_slots'], [1])

    def test_ambiguous_duplicate_pending_slot_is_corrupt_and_protects_all(self):
        case = self.base / 'ambiguous-index'
        root, _, _ = setup_case(case, 'restore')
        self.crash(case, 'restore', 1)
        m = manager(case)
        row = recovery.records(m, root)['1']
        raw = json.dumps(row)
        (m.scope(root) / recovery.INDEX).write_text(
            '{"format":1,"operations":{"1":' + raw + ',"1":' + raw + '}}', encoding='utf-8')
        view = m.recovery_status(root)
        self.assertFalse(view['available'])
        self.assertEqual(view['blocked_slots'], list(range(1, 7)))
        self.assertIn('恢复关联无法核对', view['error'])
        with self.assertRaises(ValueError):
            m.recovery_preview(root, row)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--child':
        child(Path(sys.argv[2]), sys.argv[3], sys.argv[4], int(sys.argv[5]), sys.argv[6])
    else:
        unittest.main()
