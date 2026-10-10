"""Public build references from synthetic saves; no GUI or personal data."""
import copy
import gzip
import json
from http.client import HTTPConnection
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from companion.engine import Catalog, PREFIX
from companion.native_workspace import NumericLookup
from companion.public_build import project_build, ARMOR_TALENTS, TALENT_PREFIX
from companion.rules import NumericRules
from companion.service import Session
from companion.values import PlayerValues


def game(**fields):
    hero={'class':'WARRIOR','subClass':'BERSERKER','HP':100,'HT':100,'STR':14,'lvl':25,
          'inventory':[],'buffs':[],'talents_tier_1':{'HEARTY_MEAL':2},
          'talents_tier_2':{'RUNIC_TRANSFERENCE':2},'talents_tier_3':{'STRONGMAN':3},
          'talents_tier_4':{'BODY_SLAM':3,'HEROIC_ENERGY':4},
          'armorAbility':{'__className':PREFIX+'actors.hero.abilities.warrior.HeroicLeap'}}
    hero.update(fields)
    return {'version':922,'depth':12,'challenges':0,'hero':hero}


class PublicBuildProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog=Catalog()
        cls.values=PlayerValues(NumericRules(cls.catalog))

    def test_six_class_talents_and_twelve_subclasses_are_eligible(self):
        fixtures=[('WARRIOR','BERSERKER','HEARTY_MEAL','ENDLESS_RAGE'),
                  ('WARRIOR','GLADIATOR','HEARTY_MEAL','CLEAVE'),
                  ('MAGE','BATTLEMAGE','EMPOWERING_MEAL','EMPOWERED_STRIKE'),
                  ('MAGE','WARLOCK','EMPOWERING_MEAL','SOUL_EATER'),
                  ('ROGUE','ASSASSIN','CACHED_RATIONS','ENHANCED_LETHALITY'),
                  ('ROGUE','FREERUNNER','CACHED_RATIONS','EVASIVE_ARMOR'),
                  ('HUNTRESS','SNIPER','NATURES_BOUNTY','FARSIGHT'),
                  ('HUNTRESS','WARDEN','NATURES_BOUNTY','SHIELDING_DEW'),
                  ('DUELIST','CHAMPION','STRENGTHENING_MEAL','VARIED_CHARGE'),
                  ('DUELIST','MONK','STRENGTHENING_MEAL','UNENCUMBERED_SPIRIT'),
                  ('CLERIC','PRIEST','SATIATED_SPELLS','HOLY_LANCE'),
                  ('CLERIC','PALADIN','SATIATED_SPELLS','LAY_ON_HANDS')]
        for cls,sub,first,advanced in fixtures:
            with self.subTest(cls=cls,sub=sub):
                build=project_build(game(**{'class':cls,'subClass':sub,'armorAbility':None,
                    'talents_tier_1':{first:2},'talents_tier_3':{advanced:3}}),self.catalog)
                self.assertEqual(build['state'],'known')
                self.assertEqual(build['talents'][TALENT_PREFIX+first.lower()]['points'],2)
                self.assertEqual(build['talents'][TALENT_PREFIX+advanced.lower()]['points'],3)
                self.assertTrue(set(build['talents']).issubset(self.catalog.entry_index))

    def test_armor_identity_and_all_nineteen_selected_abilities(self):
        for relative,expected in ARMOR_TALENTS.items():
            cls=relative.split('.')[0].upper() if '.' in relative else 'WARRIOR'
            build=project_build(game(**{'class':cls,'subClass':'NONE','armorAbility':{
                '__className':PREFIX+'actors.hero.abilities.'+relative},
                'talents_tier_4':{name:4 for name in (*expected,'HEROIC_ENERGY')}}),self.catalog)
            self.assertEqual(build['ability']['id'],'actors.hero.abilities.'+relative.lower())
            self.assertIn(build['ability']['id'],self.catalog.entry_index)
            self.assertTrue(all(build['talents'][TALENT_PREFIX+name.lower()]['points']==4 for name in expected))
        for identity in ['actors.hero.abilities.warrior.HeroicLeap',PREFIX+'actors.hero.abilities.mage.WildMagic',
                         PREFIX+'actors.hero.abilities.warrior.heroicleap']:
            self.assertEqual(project_build(game(armorAbility={'__className':identity}),self.catalog)['state'],'unknown')

    def test_invalid_points_context_and_wrong_tier_do_not_invent_talents(self):
        for points in [True,'3',-1,{},None]:
            build=project_build(game(talents_tier_3={'STRONGMAN':points}),self.catalog)
            self.assertEqual(build['talents'][TALENT_PREFIX+'strongman']['state'],'unknown')
        for fields in [{'class':'WARRIOR','subClass':'WARDEN'},{'class':'INVALID'},
                       {'replacements':[]},{'talents_tier_2':[]}]:
            build=project_build(game(**fields),self.catalog)
            self.assertFalse(any(row['state']=='learned' and identity==TALENT_PREFIX+'runic_transference' for identity,row in build['talents'].items()))
        build=project_build(game(talents_tier_3={'HEARTY_MEAL':2,'SHIELDING_DEW':3,'STRONGMAN':99}),self.catalog)
        self.assertEqual(build['talents'][TALENT_PREFIX+'strongman']['points'],3)
        self.assertNotIn(TALENT_PREFIX+'shielding_dew',build['talents'])
        for version in [None,True,921,'922']:
            value=game();value['version']=version
            self.assertEqual(project_build(value,self.catalog)['talents'],{})

    def test_one_step_same_tier_replacements_and_duplicate_rejection(self):
        fields={'class':'MAGE','subClass':'NONE','armorAbility':None,
                'replacements':{'WAND_PRESERVATION':'RUNIC_TRANSFERENCE'},
                'talents_tier_2':{'RUNIC_TRANSFERENCE':2,'WAND_PRESERVATION':2}}
        build=project_build(game(**fields),self.catalog)
        self.assertEqual(build['talents'][TALENT_PREFIX+'runic_transference']['points'],2)
        self.assertNotIn(TALENT_PREFIX+'wand_preservation',build['talents'])
        for replacements in [{'WAND_PRESERVATION':'SHIELDING_DEW'},
                             {'WAND_PRESERVATION':'HEARTY_MEAL'},
                             {'WAND_PRESERVATION':'SUNRAY','ENERGIZING_MEAL':'SUNRAY'}]:
            self.assertEqual(project_build(game(**{**fields,'replacements':replacements}),self.catalog)['state'],'unknown')

    def test_rank_input_caps_selected_rows_and_explicit_zero(self):
        for name,cap in [('runic_transference',2),('strongman',3),('body_slam',4)]:
            detail=self.values.detail(TALENT_PREFIX+name,{'talent':cap})
            field=next(row for row in detail['inputs'] if row['key']=='talent')
            self.assertEqual((field['min'],field['max'],field['value']),(0,cap,cap))
            with self.assertRaises(ValueError):self.values.detail(TALENT_PREFIX+name,{'talent':cap+1})
            zero=self.values.detail(TALENT_PREFIX+name,{'talent':0})
            self.assertIn('未投入',zero['blocks'][0]['note'])
        body=self.values.detail(TALENT_PREFIX+'body_slam',{'talent':3,'power':10})
        table=next(row for row in body['blocks'] if row['title']=='各级天赋实际数值')
        self.assertEqual(table['rows'][table['selected_row']],['3','11–20'])


class PublicBuildWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='lamp-build-synthetic-')
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.save=self.root/'synthetic-saves'
        (self.save/'game1').mkdir(parents=True)
        self.config=self.root/'settings.json'
        self.config.write_text(json.dumps({'save_root':str(self.save),'slot':1,'mode':'save'}),encoding='utf-8')
        self.change_save()
        self.session=Session(self.config)
        self.addCleanup(self.session.stop.set)
        self.session.refresh()

    def change_save(self, **fields):
        (self.save/'game1/game.dat').write_bytes(gzip.compress(json.dumps(game(**fields)).encode(),mtime=0))
        if hasattr(self,'session'):self.session.refresh()

    def lookup(self):
        from tests.test_native_controllers import Root,Host,Worker
        self.worker=Worker();host=Host()
        manager=SimpleNamespace(session=self.session,root=Root(),native_ui=SimpleNamespace(host=host,report_drafts=Mock()))
        owner=SimpleNamespace(manager=manager,worker=self.worker,native=Mock(),pinned=None,peek_key=None,
                              preferences=self.session.play_preferences,state=self.session.play_preferences.values)
        return NumericLookup(owner)

    def finish(self,lookup):
        _,args=self.worker.args
        lookup.render(self.session.values.detail(*args))

    def test_saved_talent_and_armor_current_entries_http_fixed_latest_and_undo(self):
        from companion.server import Server
        current=self.session.workspace_status()['current']
        expected={TALENT_PREFIX+name for name in ('hearty_meal','runic_transference','strongman','body_slam','heroic_energy')}
        expected.add('actors.hero.abilities.warrior.heroicleap')
        self.assertTrue(expected.issubset({row['id'] for row in current}))
        with Server(self.session,0) as server:
            thread=threading.Thread(target=server.serve_forever);thread.start()
            try:
                connection=HTTPConnection('127.0.0.1',server.server_port,timeout=3)
                connection.request('GET','/api/workspace')
                response=connection.getresponse();self.assertEqual(response.status,200)
                workspace=json.loads(response.read());connection.close()
                self.assertTrue(expected.issubset({row['id'] for row in workspace['current']}))
            finally:server.shutdown();thread.join(3)
            self.assertFalse(thread.is_alive())
        row=next(row for row in current if row['id']==TALENT_PREFIX+'body_slam')
        lookup=self.lookup();lookup.open_reference({'entry':row['id'],**row['lookup_context']});self.finish(lookup)
        self.assertEqual(lookup.raw_params()['talent'],'3')
        self.assertTrue(lookup.save_plan('三点震地固定参考'))
        saved=copy.deepcopy(lookup.saved_plan)
        self.change_save(talents_tier_4={'BODY_SLAM':1})
        self.assertEqual(lookup.raw_params()['talent'],'3')
        self.assertEqual(self.session.knowledge.reopen(saved['id'])['plan']['params']['talent'],3)
        lookup.use_latest();self.finish(lookup)
        self.assertEqual(lookup.raw_params()['talent'],'1')
        lookup.undo_import()
        self.assertEqual(lookup.raw_params()['talent'],'3')
        self.assertEqual(lookup.saved_plan,saved)

    def test_warden_waterskin_naturally_uses_rank_and_resource_conditions(self):
        self.change_save(**{'class':'HUNTRESS','subClass':'WARDEN','armorAbility':None,
            'talents_tier_1':{},'talents_tier_2':{},'talents_tier_3':{'SHIELDING_DEW':3},'talents_tier_4':{},
            'inventory':[{'__className':PREFIX+'items.Waterskin','volume':20,'quantity':1}]})
        row=next(row for row in self.session.workspace_status()['current'] if row['id']=='items.waterskin')
        params=row['lookup_context']['params']
        for key,value in {'shielding_dew':3,'dew_volume':20,'vial':-1,'current_shield':0}.items():self.assertEqual(params[key],value)
        native=NumericLookup.entry_context(self.session.snapshot(),'items.waterskin')
        self.assertEqual(native['params']['shielding_dew'],3)
        option=next(row for row in self.session.decisions()['options'] if row['entry']=='items.waterskin')
        self.assertEqual(option['calculation_missing'],'')
        cells={cell['label']:cell['value'] for cell in option['values']}
        self.assertEqual((cells['本次消耗露珠'],cells['实际新增屏障']),('12','60'))
        lookup=self.lookup();lookup.open_reference({'entry':row['id'],**row['lookup_context']});self.finish(lookup)
        self.assertEqual(lookup.raw_params()['shielding_dew'],'3')
        self.assertTrue(lookup.save_plan('三点护盾露珠参考'))
        saved=copy.deepcopy(lookup.saved_plan)
        self.change_save(**{'class':'HUNTRESS','subClass':'WARDEN','armorAbility':None,
            'talents_tier_3':{'SHIELDING_DEW':1},'inventory':[{'__className':PREFIX+'items.Waterskin','volume':10,'quantity':1}]})
        self.assertEqual(lookup.raw_params()['shielding_dew'],'3')
        lookup.use_latest();self.finish(lookup)
        self.assertEqual((lookup.raw_params()['shielding_dew'],lookup.raw_params()['dew_volume']),('1','10'))
        lookup.undo_import()
        self.assertEqual((lookup.raw_params()['shielding_dew'],lookup.raw_params()['dew_volume']),('3','20'))
        self.assertEqual(self.session.knowledge.reopen(saved['id'])['plan']['params']['shielding_dew'],3)
