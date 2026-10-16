"""Learned spell conditions through real saves, services and headless controllers."""
import copy
import gzip
import json
import os
from contextlib import closing
from http.client import HTTPConnection
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from urllib.parse import urlencode

from companion.engine import Catalog, PREFIX, analyze
from companion.public_skills import project_skills, skill_context
from companion.rules import NumericRules
from companion.service import Session
from companion.decisions import public_context
from companion.values import PlayerValues

SPELL = 'actors.hero.spells.'


def game(catalog, **fields):
    hero = {'class': 'CLERIC', 'subClass': 'PRIEST', 'HP': 30, 'HT': 50, 'STR': 12, 'lvl': 15,
            'inventory': [], 'buffs': [], 'replacements': {},
            'talents_tier_1': {'HOLY_INTUITION': 1, 'SHIELD_OF_LIGHT': 2},
            'talents_tier_2': {'SUNRAY': 2, 'DIVINE_SENSE': 1, 'BLESS': 2},
            'talents_tier_3': {'CLEANSE': 3, 'HOLY_LANCE': 2}, 'talents_tier_4': {}}
    hero.update(fields)
    return {'version': catalog.data['version_code'], 'depth': 2, 'challenges': 0,
            'generated_levels': [2], 'hero': hero}


class PublicSkillProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()
        cls.values = PlayerValues(NumericRules(cls.catalog))

    def skills(self, **fields):
        return analyze(game(self.catalog, **fields), self.catalog)['hero']['skills']

    def test_distinct_public_ranks_and_actual_numeric_results(self):
        skills = self.skills()
        for name, points in {'sunray': 2, 'holyintuition': 1, 'divinesense': 1,
                             'blessspell': 2, 'cleanse': 3, 'holylance': 2}.items():
            self.assertEqual((skills[SPELL + name]['state'], skills[SPELL + name]['points']), ('learned', points))
        metrics = lambda name, rank: {row['label']: row['value'] for block in
            self.values.detail(SPELL + name, {'talent': rank})['blocks'] for row in block.get('values', [])}
        self.assertEqual(metrics('sunray', 2)['基础伤害'], '6–12')
        self.assertEqual(metrics('sunray', 1)['基础伤害'], '4–8')
        self.assertEqual(metrics('divinesense', 1)['灵视半径'], '8')
        self.assertEqual(metrics('blessspell', 2)['自身护盾'], '15')
        self.assertEqual(metrics('cleanse', 3)['护盾'], '30')
        clamped = self.skills(talents_tier_2={'SUNRAY': 99}, talents_tier_3={'CLEANSE': 99})
        self.assertEqual(clamped[SPELL+'sunray']['points'], 2)
        self.assertEqual(clamped[SPELL+'cleanse']['points'], 3)

    def test_subclass_and_armor_eligibility_are_required(self):
        skills = self.skills(subClass='PALADIN', talents_tier_3={'HOLY_LANCE': 3, 'LAY_ON_HANDS': 2})
        self.assertEqual(skills[SPELL+'holylance']['state'], 'not_applicable')
        self.assertEqual(skills[SPELL+'layonhands']['points'], 2)
        self.assertEqual(skills[SPELL+'radiance']['state'], 'not_applicable')
        self.assertEqual(skills[SPELL+'smite']['state'], 'learned')
        for ability, spell, talent in (('Trinity', 'spiritform', 'SPIRIT_FORM'),
                                       ('AscendedForm', 'judgement', 'JUDGEMENT'),
                                       ('PowerOfMany', 'stasis', 'STASIS')):
            with self.subTest(ability=ability):
                skills = self.skills(armorAbility={'__className': PREFIX+'actors.hero.abilities.cleric.'+ability},
                                     talents_tier_4={talent: 99})
                self.assertEqual((skills[SPELL+spell]['state'], skills[SPELL+spell]['points']), ('learned', 4))
                other = 'stasis' if spell != 'stasis' else 'spiritform'
                self.assertEqual(skills[SPELL+other]['state'], 'not_applicable')
        for ability in ({}, [], {'__className': []}, {'__className': {}}, {'__className': True},
                        {'__className': PREFIX+'actors.hero.abilities.warrior.HeroicLeap'}):
            skills = self.skills(armorAbility=ability, talents_tier_4={'SPIRIT_FORM': 4})
            self.assertEqual(skills[SPELL+'spiritform']['state'], 'unknown')
            self.assertEqual(skills[SPELL+'sunray']['points'], 2)
        self.assertEqual(self.skills(talents_tier_4={'SPIRIT_FORM': 4})[SPELL+'spiritform']['state'], 'not_applicable')

    def test_metamorphosis_uses_original_to_final_map_and_ignores_wrong_tier_points(self):
        self.assertEqual(self.skills(replacements={'SUNRAY': 'ARCANE_VISION'})[SPELL+'sunray']['state'], 'not_applicable')
        # A later metamorph stores the original key with its final replacement.
        swapped = self.skills(replacements={'SUNRAY': 'ARCANE_VISION', 'BLESS': 'SUNRAY'})
        self.assertEqual(swapped[SPELL+'sunray']['points'], 2)
        self.assertEqual(swapped[SPELL+'blessspell']['state'], 'not_applicable')
        for replacements in ([], {'SUNRAY': 'HOLY_LANCE'}, {'SUNRAY': 'INVALID'},
                             {'HOLY_LANCE': 'CLEANSE'}, {'SUNRAY': 'BLESS'},
                             {'SUNRAY': 'ARCANE_VISION', 'ARCANE_VISION': 'SUNRAY'}):
            with self.subTest(replacements=replacements):
                self.assertEqual(self.skills(replacements=replacements)[SPELL+'sunray']['state'], 'unknown')
        wrong_tier = self.skills(talents_tier_2={}, talents_tier_3={'SUNRAY': 2})[SPELL+'sunray']
        self.assertEqual((wrong_tier['state'], wrong_tier['points']), ('not_learned', 0))

    def test_missing_zero_malformed_and_incompatible_sources_never_become_rank_one(self):
        for fields in ({'talents_tier_2': {}}, {'talents_tier_2': {'SUNRAY': 0}}):
            self.assertEqual(self.skills(**fields)[SPELL+'sunray']['state'], 'not_learned')
        source = game(self.catalog)
        del source['hero']['talents_tier_2']
        self.assertEqual(project_skills(source, self.catalog.data['version_code'])[SPELL+'sunray']['points'], 0)
        for points in (True, -1, 1.5, '2', None):
            self.assertEqual(self.skills(talents_tier_2={'SUNRAY': points})[SPELL+'sunray']['state'], 'unknown')
        self.assertEqual(self.skills(talents_tier_2=[])[SPELL+'sunray']['state'], 'unknown')
        self.assertEqual(self.skills(subClass='WARLOCK')[SPELL+'sunray']['state'], 'unknown')
        self.assertEqual(self.skills(**{'class': 'MAGE'})[SPELL+'sunray']['state'], 'not_applicable')
        self.assertEqual(self.skills(**{'class': 'INVALID'})[SPELL+'sunray']['state'], 'unknown')
        for version in (None, True, self.catalog.data['version_code']+1):
            source = game(self.catalog); source['version'] = version
            self.assertTrue(all(row['state'] == 'unknown' for row in project_skills(source, self.catalog.data['version_code']).values()))

    def test_free_spells_have_no_fictitious_talent_input_or_changed_fixed_values(self):
        for name in ('guidinglight', 'holyweapon', 'holyward', 'radiance', 'smite'):
            with self.subTest(name=name):
                detail = self.values.detail(SPELL+name)
                self.assertNotIn('talent', {field['key'] for field in detail['inputs']})
                self.assertEqual(detail['blocks'], self.values.detail(SPELL+name, {'talent': 4})['blocks'])
        self.assertEqual(self.skills()[SPELL+'guidinglight']['points'], 0)


class PublicSkillWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='lamp-public-skills-synthetic-')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.saves = self.directory/'synthetic-saves'
        self.saves.mkdir()
        config = self.directory/'settings.json'
        config.write_text(json.dumps({'save_root': str(self.saves), 'slot': 1, 'mode': 'save'}), encoding='utf-8')
        self.write_save(game(self.catalog))
        self.session = Session(config, self.catalog)
        self.session.refresh()

    def write_save(self, source):
        folder = self.saves/'game1'; folder.mkdir(exist_ok=True)
        path = folder/'game.dat'
        path.write_bytes(gzip.compress(json.dumps(source).encode(), mtime=0))
        self.stamp = getattr(self, 'stamp', 1700000000)+2
        os.utime(path, (self.stamp, self.stamp))

    def change_save(self, **fields):
        self.write_save(game(self.catalog, **fields))
        self.session.refresh()

    def lookup(self):
        from companion.native_workspace import NumericLookup
        from tests.test_native_controllers import Host, Root, Worker
        self.worker, self.host = Worker(), Host()
        manager = SimpleNamespace(session=self.session, root=Root(), native_ui=SimpleNamespace(host=self.host, report_drafts=Mock()))
        self.owner = SimpleNamespace(manager=manager, worker=self.worker, native=Mock(), pinned=None, peek_key=None)
        self.controller = NumericLookup(self.owner)
        return self.controller

    def finish(self):
        self.controller.render(self.session.values.detail(*self.worker.args[1]))

    def test_current_rows_carry_distinct_ranks_and_no_raw_talents(self):
        snap = self.session.snapshot()
        self.assertFalse(snap['error'])
        self.assertNotIn('talent', public_context(snap))
        rows = {row['id']: row for row in self.session.workspace_status()['current']}
        for name, rank in (('sunray', 2), ('divinesense', 1), ('cleanse', 3)):
            lookup = rows[SPELL+name]['lookup_context']
            self.assertEqual(lookup['params']['talent'], rank)
            self.assertIn('快照', lookup['field_origins']['talent'])
            self.assertIn('不代表当前可施放', lookup['conditions'])
            detail = self.session.values.detail(SPELL+name, lookup['params'])
            self.assertEqual(next(field['value'] for field in detail['inputs'] if field['key']=='talent'), rank)
        self.assertNotIn('talent', rows[SPELL+'guidinglight']['lookup_context']['params'])
        self.assertNotIn('talents_tier', json.dumps(rows))
        self.change_save(talents_tier_2={})
        self.assertNotIn(SPELL+'sunray', {row['id'] for row in self.session.workspace_status()['current']})
        self.assertNotIn('talent', skill_context(self.session.snapshot(), SPELL+'sunray')['params'])

    def test_native_search_current_capture_latest_saved_source_and_undo(self):
        lookup = self.lookup()
        lookup.select_row(next(row for row in self.session.catalog.entries if row['id']==SPELL+'sunray'))
        self.finish()
        self.assertEqual(lookup.raw_params()['talent'], '2')
        self.assertIn('已学 2', lookup.input_origins['talent'])
        self.assertTrue(lookup.save_plan('二点辐光固定参考'))
        saved = copy.deepcopy(lookup.saved_plan)
        self.assertEqual(saved['params'], {'talent': 2})
        self.assertIn('已学 2', saved['origin']['fields']['talent'])
        self.change_save(talents_tier_2={'SUNRAY': 1})
        lookup.search(preserve_detail=True)
        self.assertEqual(lookup.raw_params()['talent'], '2')
        self.assertEqual(self.session.knowledge.reopen(saved['id'])['plan']['params'], {'talent': 2})
        lookup.handle({'action': 'use_latest'}); self.finish()
        self.assertEqual(lookup.raw_params()['talent'], '1')
        self.assertIn('已学 1', lookup.input_origins['talent'])
        self.assertNotIn('固定参数', lookup.origin.text)
        self.assertEqual(lookup.saved_plan['id'], saved['id'])
        self.assertTrue(lookup.save_plan('一点辐光新参考'))
        self.assertEqual(lookup.saved_plan['origin']['snapshot_at'], self.session.snapshot()['modified'])
        lookup.undo_import()
        self.assertEqual(lookup.raw_params()['talent'], '2')
        self.assertEqual(lookup.saved_plan, saved)

    def test_native_unknown_latest_preserves_manual_and_invalid_raw_with_undo(self):
        lookup = self.lookup()
        row = next(row for row in self.session.workspace_status()['current'] if row['id']==SPELL+'sunray')
        lookup.open_reference({'entry': row['id'], **row['lookup_context']}); self.finish()
        lookup.variables['talent'].set('1'); lookup.calculate(); self.finish()
        prior = lookup.draft(include_result=True)
        self.change_save(talents_tier_2={})
        lookup.use_latest(); self.finish()
        self.assertEqual(lookup.raw_params()['talent'], '1')
        self.assertIn('尚未学会', lookup.input_origins['talent'])
        self.assertIn('独立示例', lookup.context['conditions'])
        self.assertNotIn('已投入 2 点', lookup.context['conditions'])
        self.assertEqual(lookup.context['source'], prior['context']['source'])
        lookup.undo_import()
        self.assertEqual(lookup.raw_params(), prior['raw_params'])
        self.assertEqual(lookup.input_origins, prior['origins'])
        lookup.variables['talent'].set('-')
        ticket = self.worker.ticket
        lookup.use_latest()
        self.assertEqual(self.worker.ticket, ticket)
        self.assertEqual(lookup.raw_params()['talent'], '-')
        self.assertTrue(lookup.dirty)
        lookup.undo_import()
        self.assertEqual(lookup.raw_params()['talent'], '-')
        lookup.select_row(next(row for row in self.session.catalog.entries if row['id']==SPELL+'holylance'))
        self.finish()
        self.assertEqual(lookup.raw_params()['talent'], '2')

    def test_native_incompatible_ordinary_query_is_explicit_example(self):
        self.change_save(**{'class': 'MAGE', 'subClass': 'WARLOCK'})
        lookup = self.lookup()
        lookup.select_row(next(row for row in self.session.catalog.entries if row['id']==SPELL+'sunray'))
        self.finish()
        self.assertEqual(lookup.raw_params()['talent'], '1')
        self.assertTrue(lookup.input_origins['talent'].startswith('示例'))
        self.assertIn('不适用', lookup.text.text)

    def test_native_spell_prerequisite_stays_visible_for_fixed_and_undone_trials(self):
        lookup = self.lookup()
        lookup.select_row(next(row for row in self.session.catalog.entries if row['id']==SPELL+'sunray'))
        self.finish()
        self.assertEqual(lookup.spell_availability_notice(), '')
        self.assertTrue(lookup.save_plan('原两点试算'))
        record_id = lookup.saved_plan['id']
        original = copy.deepcopy(lookup.calculated)
        self.change_save(talents_tier_2={})
        self.assertIn('槽位 1 · 尚未学会', lookup.spell_availability_notice())
        lookup.use_latest(); self.finish(); lookup.undo_import()
        self.assertEqual(lookup.calculated, original)
        self.assertIn('以下仅为试算', lookup.spell_availability_notice())
        lookup.open_plan(record_id, False)
        self.assertEqual(lookup.calculated, original)
        lookup.emit()
        self.assertIn('尚未学会', self.host.commands[-1][1]['primary_notice'])
        self.change_save(talents_tier_2={'SUNRAY':1})
        self.assertEqual(lookup.spell_availability_notice(), '')
        self.assertEqual(lookup.calculated, original)
        self.change_save(**{'class':'MAGE','subClass':'WARLOCK'})
        self.assertIn('角色不适用', lookup.spell_availability_notice())

    def test_http_current_reference_and_entry_specific_values_use_actual_save(self):
        from companion.server import Server
        with Server(self.session) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                def get(route):
                    with closing(HTTPConnection('127.0.0.1', server.server_port, timeout=5)) as connection:
                        connection.request('GET', route)
                        response = connection.getresponse()
                        self.assertEqual(response.status, 200)
                        return json.loads(response.read())
                workspace = get('/api/workspace')
                current = next(row for row in workspace['current'] if row['id'] == SPELL+'sunray')
                detail = get('/api/values?' + urlencode({'id': current['id'], **current['lookup_context']['params']}))
                self.assertEqual(next(row['value'] for block in detail['blocks'] for row in block.get('values', []) if row['label']=='基础伤害'), '6–12')
                self.assertEqual(next(row['value'] for row in detail['inputs'] if row['key']=='talent'), 2)
            finally:
                server.shutdown(); thread.join(timeout=5)

    def test_native_latest_reuses_public_healing_and_barrier_presence_rules(self):
        lookup = self.lookup()
        def open_entry(identity):
            lookup.select_row(next(row for row in self.session.catalog.entries if row['id']==identity))
            self.finish()
        open_entry('items.waterskin')
        self.session.data['buffs'] = [{'kind':'Barrier', 'current_shield': 7}]
        lookup.use_latest(); self.finish()
        self.assertEqual(lookup.raw_params()['current_shield'], '7')
        shield_origin = lookup.input_origins['current_shield']
        self.assertTrue(shield_origin.startswith(('最近保存的记录 · 槽位 1 · ', '旧快照记录 · 槽位 1 · ')))
        self.assertTrue(shield_origin.endswith(' 保存'))
        for buffs in ([{'kind':'Barrier'}], [{'kind':'Barrier','current_shield':3}, {'kind':'Barrier','current_shield':4}]):
            self.session.data['buffs'] = buffs
            lookup.variables['current_shield'].set('9')
            lookup.use_latest(); self.finish()
            self.assertEqual(lookup.raw_params()['current_shield'], '9')
            self.assertEqual(lookup.input_origins['current_shield'], '手填 · 最新记录未确认')
        self.session.data['buffs']=[]
        self.session.data['buffs_known']=False
        lookup.use_latest();self.finish()
        self.assertEqual(lookup.raw_params()['current_shield'],'9')
        self.session.data['buffs_known']=True
        lookup.use_latest();self.finish()
        self.assertEqual(lookup.raw_params()['current_shield'],'0')
        open_entry('actors.buffs.healing')
        self.session.data['buffs'] = [{'kind':'Healing','left':80,'percent':.1,'flat':2,'vial_level':-1}]
        lookup.use_latest(); self.finish()
        self.assertEqual(lookup.raw_params()['power'], '80')
        self.assertEqual(lookup.raw_params()['healing_percent'], '10.0')
        power_origin = lookup.input_origins['power']
        self.session.data['buffs'] = [{'kind':'Healing'}]
        lookup.use_latest(); self.finish()
        self.assertEqual(lookup.raw_params()['power'], '80')
        self.assertEqual(lookup.input_origins['power'], power_origin+' · 最新记录未确认')

    def test_old_free_spell_plans_reopen_without_rewriting_or_loosening_new_save(self):
        store = self.session.knowledge
        saved = store.save('旧固定参考', 'numeric', SPELL+'sunray', {'talent':2},
                           {'fields': {'talent':'旧明确参考'}}, note='原始用途')
        template = json.loads(store.export())
        original = template['plans'][0]
        records = []
        for index, name in enumerate(('guidinglight','holyweapon','holyward','radiance','smite')):
            row = copy.deepcopy(original)
            row.update(id=f'{index+1:032x}', name=name, entry=SPELL+name,
                       params={'talent':1, **({'hero_level':17} if name in ('guidinglight','smite') else {})})
            records.append(row)
        bad = copy.deepcopy(records[0]); bad.update(id='a'*32, params={'talent':1,'hero_level':17,'retired_field':2})
        records.append(bad)
        template['plans'] = records
        store.path.write_text(json.dumps(template, ensure_ascii=False), encoding='utf-8')
        disk, exported = store.path.read_bytes(), store.export()
        lookup = self.lookup()
        for row in records[:-1]:
            with self.subTest(name=row['entry']):
                opened = store.reopen(row['id'])
                self.assertEqual(opened['result']['retained_legacy_params'], ['talent'])
                self.assertEqual(opened['plan']['params'], row['params'])
                self.assertIn('不使用该字段', opened['result']['notice'])
                self.assertEqual(opened['result']['blocks'], self.session.values.detail(row['entry'],
                    {key:value for key,value in row['params'].items() if key!='talent'})['blocks'])
                self.assertEqual(store.path.read_bytes(), disk)
                self.assertEqual(store.export(), exported)
                lookup.open_plan(row['id'], False)
                self.assertFalse(lookup.has_draft())
                with self.assertRaises(ValueError):
                    store.save('拒绝新建无关字段', 'numeric', row['entry'], row['params'])
        self.assertIsNone(store.reopen(bad['id'])['result'])
        self.assertEqual(store.path.read_bytes(), disk)
        self.assertEqual(store.export(), exported)


if __name__ == '__main__':
    unittest.main()
