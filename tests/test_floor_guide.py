"""Source-bound public encounter rules, independent of saved hidden contents."""
import unittest
import json
from types import SimpleNamespace
from tests import test_scouting as scouting_tests
from companion.native_manager import NativeManager
from companion.engine import Catalog
from companion.floor_guide import floor_encounters
from companion.values import PlayerValues
from companion.rules import NumericRules


class FloorGuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog=Catalog()

    def guide(self, depth, branch=0, version=922):
        return floor_encounters({'version':version,'depth':depth,'branch':branch},self.catalog)

    def test_floor_one_and_three_slots_and_alternatives_follow_spawner(self):
        first={r['id']:r for r in self.guide(1)['rows']}
        self.assertEqual(set(first),{'actors.mobs.rat','actors.mobs.snake','actors.mobs.albino'})
        self.assertIn('4 个名额中占 3 个',first['actors.mobs.rat']['condition'])
        self.assertEqual(first['actors.mobs.rat']['hp'],'8')
        third={r['id']:r for r in self.guide(3)['rows']}
        self.assertIn('7 个名额中占 3 个',third['actors.mobs.gnoll']['condition'])
        self.assertIn('actors.mobs.hermitcrab',third)
        self.assertNotIn('actors.mobs.slime',third)

    def test_rare_additions_are_per_rotation_and_boss_floor_is_not_rotation(self):
        groups=[r['group'] for r in self.guide(4)['rows']]
        self.assertEqual(groups,sorted(groups,key={'普通轮换':0,'稀有替换':1,'罕见跨区':2,'罕见跨区变种':3}.get))
        fourth={r['id']:r for r in self.guide(4)['rows']}
        self.assertIn('不是每次刷新2.5%',fourth['actors.mobs.thief']['condition'])
        self.assertIn('先满足2.5%',fourth['actors.mobs.bandit']['condition'])
        for depth,boss in ((5,'goo'),(10,'tengu'),(15,'dm300'),(20,'dwarfking'),(25,'yogdzewa')):
            rows=self.guide(depth)['rows'];self.assertEqual([r['id'] for r in rows],['actors.mobs.'+boss])
        self.assertEqual(self.guide(26)['rows'],[])
        self.assertTrue(self.guide(5)['sources'])
        self.assertTrue(self.guide(12,1)['sources'])

    def test_shaman_and_elemental_selector_conditions_are_not_spawn_odds(self):
        cave={r['id']:r for r in self.guide(11)['rows']}
        self.assertIn('40%',cave['actors.mobs.shaman$redshaman']['condition'])
        self.assertIn('20%',cave['actors.mobs.shaman$purpleshaman']['condition'])
        city={r['id']:r for r in self.guide(16)['rows']}
        self.assertIn('未先替换成混沌元素',city['actors.mobs.elemental$fireelemental']['condition'])
        self.assertIn('默认2%先替换',city['actors.mobs.elemental$chaoselemental']['condition'])

    def test_branch_rules_are_distinct_and_unsupported_versions_do_not_guess(self):
        mining=self.guide(12,1)
        self.assertIn('互斥',mining['note'])
        self.assertEqual({r['id'] for r in mining['rows']},{'actors.mobs.'+x for x in ('bat','crystalwisp','gnollguard','fungalspinner')})
        vault=self.guide(17,1)
        self.assertEqual(len(vault['rows']),10)
        self.assertTrue(all(r['id'].startswith('actors.mobs.quest.vault.') for r in vault['rows']))
        for depth,branch,version in ((4,1,922),(4,0,920),(4,0,999),(True,0,922),(4,True,922)):
            self.assertEqual(self.guide(depth,branch,version)['rows'],[])

    def test_all_public_encounters_have_normal_numeric_and_drop_details(self):
        values=PlayerValues(NumericRules(self.catalog))
        identities=set()
        for branch,depths in ((0,range(1,27)),(1,range(11,20))):
            for depth in depths:
                for row in self.guide(depth,branch)['rows']:
                    result=values.detail(row['id'],{'depth':depth,'hero_level':5,'loot_count':0})
                    blocks={block['title']:block for block in result['blocks']}
                    self.assertIn('常规战斗数值',blocks)
                    self.assertIn('掉落物、数量与概率',blocks)
                    self.assertEqual(len(blocks['常规战斗数值']['values']),10)
                    identities.add(row['id'])
        self.assertGreater(len(identities),40)


class NativeFloorGuideTests(unittest.TestCase):
    setUpClass=classmethod(scouting_tests.ScoutingTests.setUpClass.__func__)
    save=scouting_tests.ScoutingTests.save
    write_floor=scouting_tests.ScoutingTests.write_floor
    tree=scouting_tests.ScoutingTests.tree

    def setUp(self):
        scouting_tests.ScoutingTests.setUp(self)
        self.ui=NativeManager.__new__(NativeManager)
        self.ui.session=self.session
        self.ui.manager=SimpleNamespace(action_error='',action_error_until=0)
        self.ui.report_drafts=lambda:None
        self.ui.update=lambda *args,**kwargs:None
        self.jobs=[]
        self.ui.queue_io=lambda label,work,finish:self.jobs.append((work,finish)) or True

    def test_native_collapse_data_starts_public_and_explicit_reveal_is_read_only(self):
        before=self.tree();snap=self.session.snapshot()
        public=self.ui.floor_state(snap)
        self.assertFalse(public['revealed'])
        self.assertEqual(public['nodes'][0]['children'],[])
        self.assertTrue(public['nodes'][1]['expanded'])
        self.assertTrue(all(not row.get('expanded') for row in public['nodes'][1]['children']))
        self.assertLess(len(json.dumps(public,ensure_ascii=False).encode()),524288)
        self.ui.reveal_floor({'token':public['token']})
        work,finish=self.jobs.pop();result=work();finish(result,None)
        revealed=self.ui.floor_state(snap)
        self.assertTrue(revealed['revealed'])
        self.assertTrue(any(row['text'].startswith('黄金宝箱怪') for row in revealed['nodes'][0]['children']))
        self.assertEqual(self.tree(),before)
        self.assertFalse(self.session.settings['reveal'])
        self.ui.reveal_floor({'token':public['token']})
        self.assertFalse(self.ui.floor_state(snap)['revealed'])

    def test_native_old_snapshot_and_late_hidden_result_are_retired(self):
        old=self.ui.floor_state(self.session.snapshot())
        self.ui.reveal_floor({'token':old['token']})
        work,finish=self.jobs.pop();result=work()
        self.game['hero']['HP']=21;self.save();self.session.refresh()
        finish(result,None)
        current=self.ui.floor_state(self.session.snapshot())
        self.assertFalse(current['revealed'])
        self.assertEqual(current['nodes'][0]['children'],[])
        with self.assertRaisesRegex(ValueError,'已更新'):
            self.ui.reveal_floor({'token':old['token']})

    def test_native_floor_reference_uses_lookup_contract_and_current_conditions(self):
        snap=self.session.snapshot();public=self.ui.floor_state(snap)
        calls=[];self.ui.manager.open_reference=lambda *args:calls.append(args)
        self.ui.frozen=False
        self.ui.dispatch({'action':'floor_reference','token':public['token'],'id':'actors.mobs.crab'})
        self.assertEqual(len(calls),1)
        reference,source,note=calls[0]
        self.assertEqual(reference['entry'],'actors.mobs.crab')
        self.assertEqual(reference['params'],{'depth':4,'hero_level':5,'loot_count':0})
        self.assertEqual(reference['source'],{'mode':'save'})
        self.assertEqual(reference['stamp'][4],snap['revision'])
        self.assertIn('下水道螃蟹',reference['source_label'])
        self.assertIn('0次示例',reference['source_label'])
        self.assertIn('未读取本局计数',reference['conditions'])
        self.assertIsNone(source)
        self.assertEqual(self.ui.manager.action_error,'')


if __name__=='__main__': unittest.main()
