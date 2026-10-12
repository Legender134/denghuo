"""Public DoT handoff and fixed 4.0.2 boundaries, with synthetic saves only."""
import copy
import gzip
import json
import math
import os
from pathlib import Path
import shutil
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
RUN = Path(os.environ.get('DOT_TEST_RUN') or tempfile.mkdtemp(prefix='lamp-public-dot-'))
if not RUN.is_absolute():
    raise RuntimeError('DOT_TEST_RUN must be an explicit absolute synthetic fixture path')
RUN.mkdir(parents=True, exist_ok=True)
# Before any product-module import, including paths/service defaults.
os.environ['APPDATA'] = str(RUN / 'appdata')
os.environ['LOCALAPPDATA'] = str(RUN / 'localappdata')

from companion.decisions import context_actions
from companion.engine import Catalog, PREFIX, public_dot
from companion.native_workspace import NumericLookup
from companion.rules import NumericRules
from companion.service import Session
from companion.values import PlayerValues

CORROSION = 'actors.buffs.corrosion'
DEFERRED = 'items.armor.glyphs.viscosity$defereddamage'


def metrics(page):
    return {row['label']: row['value'] for section in page['blocks'] for row in section.get('values', [])}


def f32(value):
    return struct.unpack('f', struct.pack('f', value))[0]


def official_corrosion(damage, left, depth):
    # Independent transcription of pinned Corrosion.totalIncomingDMG.
    current, sequence = f32(damage), []
    for _ in range(math.ceil(f32(left))):
        sequence.append(int(current))
        current = f32(current + (1 if current < depth//2+2 else .5))
    return sequence


class PublicDotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()
        cls.values = PlayerValues(NumericRules(cls.catalog))

    def test_deferred_pool_boundaries_and_outer_glyph_remain_separate(self):
        for pool, tick, after in ((0, 0, 0), (1, 1, 0), (9, 1, 8), (10, 1, 9), (30, 3, 27)):
            page = self.values.detail(DEFERRED, {'damage': pool, 'level': 100})
            self.assertEqual({field['key'] for field in page['inputs']}, {'damage'})
            self.assertEqual(metrics(page), {'当前剩余池': str(pool), '下一次基础伤害': str(tick),
                '扣池后剩余': str(after), '剩余基础总量': str(pool)})
            self.assertIn('不预测', page['blocks'][0]['note'])
            if not pool:
                self.assertIn('基础1点', page['blocks'][0]['note'])
        glyph = self.values.detail('items.armor.glyphs.viscosity', {'damage': 30, 'level': 0})
        self.assertEqual(metrics(glyph), {'转为延缓伤害': '5', '立即承受': '25'})
        self.assertEqual({field['key'] for field in glyph['inputs']}, {'damage', 'level'})

    def test_corrosion_explicit_exact_schedule_total_and_float_boundary(self):
        params = {'power': 3, 'remaining_turns': 4, 'depth': 4, 'corrosion_public': 0}
        page = self.values.detail(CORROSION, params)
        self.assertEqual(metrics(page)['剩余基础总量'], '16')
        self.assertEqual(next(block['rows'] for block in page['blocks'] if block.get('rows')),
                         [['1', '3'], ['2', '4'], ['3', '4'], ['4', '5']])
        self.assertIn('明确手填精确假设', page['blocks'][0]['note'])
        for power, left, depth in ((3.9999999, 4.0000001, 4), (6.5, 3.999, 10), (0, 0, 1), (10, .001, 30)):
            expected = official_corrosion(power, left, depth)
            actual = self.values.detail(CORROSION, {'power': power, 'remaining_turns': left, 'depth': depth})
            self.assertEqual(int(metrics(actual)['剩余基础总量']), sum(expected))

    def test_missing_conditions_stay_blank_and_no_default_damage_is_calculated(self):
        for identity, params, missing in ((DEFERRED, {}, {'damage'}),
                (CORROSION, {}, {'power', 'remaining_turns'}), (CORROSION, {'power': 3}, {'remaining_turns'})):
            page = self.values.detail(identity, params)
            self.assertEqual(set(page['missing_inputs']), missing)
            self.assertTrue(all(field['value'] == '' for field in page['inputs'] if field['key'] in missing))
            self.assertNotIn('下一次基础伤害', metrics(page))

    def test_public_projection_matches_integer_and_decimal_display_boundaries(self):
        for power, left, expected in ((3.999, 3.995, (3, 3.99)), (3.9999999, 4.005, (4, 4.01)),
                                     (3.5, 4.015, (3, 4.01)), (3.5, 4.0049, (3, 4))):
            fields = public_dot({'damage': power, 'left': left}, CORROSION)['public_dot']
            self.assertEqual(fields, {'power': expected[0], 'remaining_turns': expected[1], 'corrosion_public': 1})
        self.assertEqual(public_dot({'damage': 30}, DEFERRED), {'public_dot': {'damage': 30}})
        self.assertEqual(public_dot({'damage': 30.5}, DEFERRED), {})
        self.assertNotIn('power', public_dot({'damage': 10000.99999}, CORROSION)['public_dot'])
        for bad in (True, '3', -1, float('nan'), float('inf')):
            self.assertEqual(public_dot({'damage': bad, 'left': bad}, CORROSION), {'public_dot': {'corrosion_public': 1}})

    def test_public_range_contains_independent_fractional_outcomes(self):
        for depth in (1, 4, 10, 30):
            previous3 = struct.unpack('f', struct.pack('I', struct.unpack('I', struct.pack('f', 3))[0]-1))[0]
            previous4 = struct.unpack('f', struct.pack('I', struct.unpack('I', struct.pack('f', 4))[0]-1))[0]
            for power in (0, .49, .99, 2, 2.99, previous3, 3, 3.49, 3.5, 3.999, previous4, 4, 6.99, 7, 17.99):
                for left in (0, .0001, .0049, .005, .9949, .995, 1, 1.0001, 3.995, 4, 4.0049, 4.005):
                    params = public_dot({'damage': power, 'left': left}, CORROSION)['public_dot']
                    page = self.values.detail(CORROSION, {**params, 'depth': depth})
                    low, *high = metrics(page)['剩余基础总量范围'].split('–')
                    total = sum(official_corrosion(power, left, depth))
                    self.assertLessEqual(int(low), total, (power, left, depth))
                    self.assertGreaterEqual(int(high[0] if high else low), total, (power, left, depth))
        for bad in ({'power': 3.5, 'remaining_turns': 4}, {'power': 3, 'remaining_turns': 4.001}):
            with self.assertRaisesRegex(ValueError, '公开酸蚀'):
                self.values.detail(CORROSION, {**bad, 'corrosion_public': 1})

    def synthetic_session(self, corrosion=None, deferred=30):
        directory = Path(tempfile.mkdtemp(prefix='case-', dir=RUN))
        saves = directory / 'synthetic-saves'
        slot = saves / 'game1'
        slot.mkdir(parents=True)
        # Explicit save_root exists before Session construction.
        config = directory / 'settings.json'
        config.write_text(json.dumps({'save_root': str(saves), 'slot': 1, 'mode': 'save'}), encoding='utf-8')
        buffs = [{'__className': PREFIX+'actors.buffs.Corrosion', **(corrosion if corrosion is not None else {'damage': 3.75, 'left': 4.0049})},
                 {'__className': PREFIX+'items.armor.glyphs.Viscosity$DeferedDamage', 'damage': deferred}]
        game = {'version': 802, 'depth': 4, 'branch': 0, 'seed': 4213, 'challenges': 0,
                'hero': {'class': 'WARRIOR', 'HP': 15, 'HT': 20, 'STR': 10, 'lvl': 1, 'inventory': [], 'buffs': buffs}}
        raw = gzip.compress(json.dumps(game).encode('utf-8'), mtime=0)
        original = directory / 'original-inputs' / 'game1' / 'game.dat'
        original.parent.mkdir(parents=True)
        original.write_bytes(raw)
        active = slot / 'game.dat'
        shutil.copyfile(original, active)
        session = Session(config, self.catalog)
        session.refresh()
        self.assertFalse(session.snapshot().get('error'), session.snapshot().get('error'))
        self.addCleanup(session.stop.set)
        # Originals and active synthetic inputs remain retained; no cleanup/deletion.
        self.addCleanup(lambda: self.assertEqual(original.read_bytes(), raw))
        self.addCleanup(lambda: self.assertEqual(active.read_bytes(), raw))
        return session, directory

    def test_valid_save_current_risk_native_context_and_plan_roundtrip(self):
        session, directory = self.synthetic_session()
        snapshot = session.snapshot()
        current = {row['id']: row['lookup_context'] for row in session.workspace_status()['current']}
        contexts = []
        for identity, expected in ((CORROSION, {'power': 3, 'remaining_turns': 4, 'corrosion_public': 1}),
                                   (DEFERRED, {'damage': 30})):
            captured = current[identity]
            native = NumericLookup.entry_context(snapshot, identity)
            self.assertEqual({key: captured['params'][key] for key in expected}, expected)
            self.assertEqual({key: native['params'][key] for key in expected}, expected)
            self.assertEqual(captured['field_origins'], native['field_origins'])
            self.assertEqual(captured['source']['snapshot_at'], snapshot['modified'])
            self.assertEqual(captured['source']['slot'], 1)
            page = session.values.detail(identity, captured['params'])
            params = {field['key']: field['value'] for field in page['inputs']}
            source = {key: captured['source'][key] for key in ('mode', 'snapshot_at', 'slot')}
            source['fields'] = {key: captured['field_origins'].get(key, '快照等效层数') for key in params}
            saved = session.knowledge.save(identity, 'numeric', identity, params, source)
            reopened = Session(session.config_path, self.catalog).knowledge.reopen(saved['id'])
            self.assertEqual(reopened['plan']['params'], params)
            self.assertEqual(reopened['plan']['origin']['snapshot_at'], snapshot['modified'])
            self.assertEqual(reopened['result'], page)
            contexts.append({'identity': identity, 'context': captured, 'page': page, 'saved': saved})
        references = [ref for risk in context_actions(session, snapshot)['risks'] for ref in risk['references']]
        for identity, field in ((CORROSION, 'power'), (DEFERRED, 'damage')):
            ref = next(row for row in references if row['entry'] == identity)
            self.assertEqual(ref['params'][field], current[identity]['params'][field])
            self.assertIn(field, ref['field_origins'])
        evidence = {'snapshot': snapshot, 'current': contexts, 'risk_references': references,
                    'retained_directory': str(directory)}
        (RUN / 'public-dot-workflow.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

    def test_presence_only_save_does_not_fill_missing_state_values(self):
        session, _ = self.synthetic_session(corrosion={})
        context = next(row['lookup_context'] for row in session.workspace_status()['current'] if row['id'] == CORROSION)
        self.assertNotIn('power', context['params'])
        self.assertNotIn('remaining_turns', context['params'])
        page = session.values.detail(CORROSION, context['params'])
        self.assertEqual(page['missing_inputs'], ['power', 'remaining_turns'])

    def test_native_controller_latest_undo_save_reopen_and_payload_bound(self):
        session, _ = self.synthetic_session()
        host = SimpleNamespace(command=Mock(), revision=0)
        worker = SimpleNamespace(ticket=0, args=None)
        def request(kind, *args):
            worker.ticket += 1
            worker.args = kind, args
            return worker.ticket
        worker.request = request
        manager = SimpleNamespace(session=session, root=SimpleNamespace(after=Mock(), after_cancel=Mock()),
                                  native_ui=SimpleNamespace(host=host, report_drafts=Mock()))
        owner = SimpleNamespace(manager=manager, worker=worker, native=Mock())
        lookup = NumericLookup(owner)
        def finish():
            lookup.render(session.values.detail(*worker.args[1]))
        lookup.select_row(self.catalog.entry_index[CORROSION])
        finish()
        self.assertEqual(float(lookup.variables['power'].get()), 3)
        self.assertEqual(lookup.variables['corrosion_public'].get(), '1')
        self.assertIn('取整', lookup.input_origins['power'])
        lookup.variables['power'].set('3.5')
        lookup.variables['corrosion_public'].set('0')
        lookup.calculate(); finish()
        manual = copy.deepcopy(lookup.calculated)
        self.assertEqual(manual['power'], 3.5)
        lookup.use_latest(); finish()
        self.assertEqual(lookup.calculated['power'], 3)
        self.assertEqual(lookup.calculated['corrosion_public'], 1)
        lookup.undo_import()
        self.assertEqual(lookup.calculated, manual)
        self.assertTrue(lookup.save_plan('精确酸蚀假设'))
        plan = copy.deepcopy(lookup.saved_plan)
        self.assertTrue(lookup.open_plan(plan['id'], False))
        self.assertEqual(lookup.calculated, manual)
        self.assertEqual(lookup.saved_plan['origin']['fields']['power'], '手填')
        # Largest permitted public table is finite and fits the native line budget.
        from companion.native_host import MAX_LINE
        lookup.clear_params()
        lookup.render(self.values.detail(CORROSION, {'power': 10000, 'remaining_turns': 1000,
                                                   'corrosion_public': 1, 'depth': 30}))
        self.assertLessEqual(len(lookup.rendered['blocks'][-1]['rows']), 1001)
        payload = host.command.call_args.kwargs
        size = len((json.dumps({'version': 1, 'session': 'synthetic', 'request': 1, 'revision': 1,
                               'action': 'lookup_state', **payload}, ensure_ascii=False)+'\n').encode())
        self.assertLess(size, MAX_LINE)
        (RUN / 'native-dot-payload.json').write_text(json.dumps({'bytes': size, 'max_line': MAX_LINE,
            'rows': len(lookup.rendered['blocks'][-1]['rows'])})+'\n', encoding='utf-8')


if __name__ == '__main__':
    unittest.main()
