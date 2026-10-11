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
        self.assertEqual({key for key,row in first.items() if row['group'] in ('普通轮换','稀有替换')},{'actors.mobs.rat','actors.mobs.snake','actors.mobs.albino'})
        self.assertNotIn('actors.mobs.mimic',first)
        self.assertNotIn('actors.mobs.bee',first)
        self.assertIn('4 个名额中占 3 个',first['actors.mobs.rat']['condition'])
        self.assertEqual(first['actors.mobs.rat']['hp'],'8')
        third={r['id']:r for r in self.guide(3)['rows']}
        self.assertIn('7 个名额中占 3 个',third['actors.mobs.gnoll']['condition'])
        self.assertIn('actors.mobs.hermitcrab',third)
        self.assertNotIn('actors.mobs.slime',third)

    def test_rare_additions_are_per_rotation_and_boss_floor_is_not_rotation(self):
        groups=[r['group'] for r in self.guide(4)['rows'] if r['group'] in ('普通轮换','稀有替换','罕见跨区','罕见跨区变种')]
        self.assertEqual(groups,sorted(groups,key={'普通轮换':0,'稀有替换':1,'罕见跨区':2,'罕见跨区变种':3}.get))
        fourth={r['id']:r for r in self.guide(4)['rows']}
        self.assertIn('不是每次刷新2.5%',fourth['actors.mobs.thief']['condition'])
        self.assertIn('先满足2.5%',fourth['actors.mobs.bandit']['condition'])
        for depth,boss in ((5,'goo'),(10,'tengu'),(15,'dm300'),(20,'dwarfking'),(25,'yogdzewa')):
            rows=self.guide(depth)['rows'];self.assertEqual([r['id'] for r in rows if r['group']=='首领'],['actors.mobs.'+boss])
            self.assertFalse(any(r['group']=='普通轮换' for r in rows))
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
        self.assertEqual({r['id'] for r in mining['rows'] if r['group']=='任务条件'},{'actors.mobs.'+x for x in ('crystalwisp','gnollguard')})
        self.assertLessEqual({'actors.mobs.'+x for x in ('crystalspire','crystalguardian','gnollgeomancer','gnollsapper')},{r['id'] for r in mining['rows']})
        self.assertFalse(any('fungal' in r['id'] for r in mining['rows']))
        self.assertIn('尚未实装',mining['note'])
        self.assertIn('兼容位置',self.guide(11,1)['note'])
        vault=self.guide(17,1)
        self.assertEqual(len(vault['rows']),10)
        self.assertTrue(all(r['id'].startswith('actors.mobs.quest.vault.') for r in vault['rows']))
        for depth,branch,version in ((4,1,922),(4,0,920),(4,0,999),(True,0,922),(4,True,922)):
            self.assertEqual(self.guide(depth,branch,version)['rows'],[])

    def test_quest_depths_and_mutually_exclusive_conditions_are_explicit(self):
        for depth,boss in ((2,'fetidrat'),(3,'gnolltrickster'),(4,'greatcrab')):
            quests={r['id']:r for r in self.guide(depth)['rows'] if r['group']=='任务房间'}
            self.assertIn('actors.mobs.'+boss,quests)
            self.assertIn('玩家接受',quests['actors.mobs.'+boss]['condition'])
        for depth in (7,8,9):
            rows={r['id']:r for r in self.guide(depth)['rows']}
            for enemy in ('rotheart','rotlasher','elemental$newbornfireelemental'):
                self.assertIn('互斥',rows['actors.mobs.'+enemy]['condition'])
                self.assertEqual(rows['actors.mobs.'+enemy]['fold_group'],'房间与任务条件')
        for depth in (1,6,10,11):
            self.assertNotIn('actors.mobs.rotheart',{r['id'] for r in self.guide(depth)['rows']})

    def test_boss_support_preserves_normal_difficulty_and_yog_pair_selection(self):
        king={r['id']:r for r in self.guide(20)['rows']}
        self.assertIn('actors.mobs.dwarfking$dkwarlock',king)
        self.assertNotIn('actors.mobs.dwarfking$dkgolem',king)
        self.assertEqual(king['actors.mobs.dwarfking$dkmonk']['fold_group'],'首领支援与召唤')
        yog={r['id']:r for r in self.guide(25)['rows']}
        self.assertEqual(len([key for key in yog if key.startswith('actors.mobs.yogfist$')]),6)
        self.assertTrue(all('不是6拳都会出现' in row['condition'] for key,row in yog.items() if key.startswith('actors.mobs.yogfist$')))
        self.assertIn('已摧毁恶魔血巢',yog['actors.mobs.yogdzewa$larva']['condition'])
        self.assertIn('仍存活的恶魔血巢',yog['actors.mobs.yogdzewa$yogripper']['condition'])
        self.assertNotIn('actors.mobs.yogdzewa$yogeye',yog)
        self.assertIn('actors.mobs.pylon',{r['id'] for r in self.guide(15)['rows']})

    def test_conditional_enemies_are_unique_and_do_not_turn_room_chances_into_spawn_odds(self):
        for branch,depths in ((0,range(1,27)),(1,range(11,20))):
            for depth in depths:
                rows=self.guide(depth,branch)['rows']
                self.assertEqual(len({r.get('reference_key',r['id']) for r in rows}),len(rows),(depth,branch))
        first={r['id']:r for r in self.guide(1)['rows']}
        self.assertIn('默认10%',first['actors.mobs.armoredstatue']['condition'])
        self.assertIn('不是房间生成概率',first['actors.mobs.phantompiranha']['condition'])
        prison={r['id']:r for r in self.guide(7)['rows']}
        self.assertIn('另可出现',prison['actors.mobs.skeleton']['condition'])
        self.assertIn('actors.mobs.necromancer$necroskeleton',{r['id'] for r in self.guide(8)['rows']})
        self.assertIn('actors.mobs.demonspawner',{r['id'] for r in self.guide(21)['rows']})

    def test_all_public_encounters_have_normal_numeric_and_drop_details(self):
        values=PlayerValues(NumericRules(self.catalog))
        identities=set()
        for branch,depths in ((0,range(1,27)),(1,range(11,20))):
            for depth in depths:
                for row in self.guide(depth,branch)['rows']:
                    result=values.detail(row['id'],{'depth':row.get('reference_depth',depth),'hero_level':5,'loot_count':0})
                    blocks={block['title']:block for block in result['blocks']}
                    self.assertIn('常规战斗数值',blocks)
                    self.assertIn('掉落物、数量与概率',blocks)
                    self.assertEqual(len(blocks['常规战斗数值']['values']),10)
                    identities.add(row['id'])
        self.assertGreater(len(identities),40)

    def test_spectral_summon_has_fixed_depth_and_distinct_room_profile(self):
        rows=[row for row in self.guide(8)['rows'] if row['id']=='actors.mobs.wraith']
        self.assertEqual(len(rows),2)
        room,summon=rows
        self.assertEqual(room['damage'],'5–10')
        self.assertEqual(summon['damage'],'3–6')
        self.assertEqual(summon['reference_depth'],4)
        self.assertNotEqual(room.get('reference_key',room['id']),summon['reference_key'])
        self.assertIn('不使用当前层数或稀有替换',summon['condition'])
        skeleton=next(row for row in self.guide(8)['rows'] if row['id']=='actors.mobs.necromancer$necroskeleton')
        self.assertEqual(skeleton['hp'],'20/25')

    def test_ebony_mimic_is_conditional_reference_only_on_regular_main_floors(self):
        for depth in range(1,27):
            rows=[r for r in self.guide(depth)['rows'] if r['id']=='actors.mobs.ebonymimic']
            if depth in (5,10,15,20,25,26):self.assertEqual(rows,[])
            else:
                self.assertEqual(len(rows),1)
                self.assertEqual(rows[0]['fold_group'],'饰品生成条件')
                for condition in ('宝箱怪之牙','12.5%／25%／37.5%／50%','无效果为0','未读取本局饰品'):
                    self.assertIn(condition,rows[0]['condition'])
        for depth in (12,17):
            self.assertFalse(any(r['id']=='actors.mobs.ebonymimic' for r in self.guide(depth,1)['rows']))


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

    def test_native_revealed_floor_item_opens_exact_level_without_character_assumptions(self):
        before=self.tree();snap=self.session.snapshot()
        public=self.ui.floor_state(snap)
        self.ui.reveal_floor({'token':public['token']})
        work,finish=self.jobs.pop();finish(work(),None)
        revealed=self.ui.floor_state(snap)
        heap=next(row for row in revealed['nodes'][0]['children'] if row['id']=='heaps-0')
        selected=heap['children'][0]
        self.assertIn('item-floor-',selected['id'])
        calls=[];self.ui.manager.open_reference=lambda *args:calls.append(args)
        self.ui.frozen=False
        self.ui.dispatch({'action':'floor_item_reference','token':revealed['token'],'id':selected['id']})
        self.assertEqual(len(calls),1)
        reference,source,note=calls[0]
        self.assertEqual(reference['entry'],'items.weapon.melee.sword')
        self.assertEqual(reference['params'],{'level':3,'tier':3})
        self.assertEqual(reference['level_origin'],'revealed')
        self.assertEqual(reference['source'],{'mode':'example'})
        self.assertNotIn('stamp',reference)
        self.assertIn('未合并当前角色',reference['conditions'])
        self.assertIn('槽位 1',reference['field_origins']['level'])
        self.assertTrue(any('保存生命 22 / 36' in row['text'] for row in revealed['nodes'][0]['children']))
        self.assertEqual(self.tree(),before)
        self.assertFalse(self.session.settings['reveal'])

    def test_native_hidden_item_reference_retires_on_hide_or_snapshot_change(self):
        # This controller fixture has no native child; record the normal error
        # presentation while exercising dispatch and its freshness checks.
        self.ui.error=lambda message:setattr(self.ui.manager,'action_error',message)
        snap=self.session.snapshot();public=self.ui.floor_state(snap)
        self.ui.reveal_floor({'token':public['token']})
        work,finish=self.jobs.pop();finish(work(),None)
        revealed=self.ui.floor_state(snap)
        selected=next(row for row in revealed['nodes'][0]['children'] if row['id']=='heaps-0')['children'][0]
        calls=[];self.ui.manager.open_reference=lambda *args:calls.append(args);self.ui.frozen=False
        self.ui.reveal_floor({'token':revealed['token']})
        self.ui.dispatch({'action':'floor_item_reference','token':revealed['token'],'id':selected['id']})
        self.assertEqual(calls,[])
        self.assertIn('主动揭示',self.ui.manager.action_error)
        self.game['hero']['HP']=21;self.save();self.session.refresh()
        self.ui.dispatch({'action':'floor_item_reference','token':revealed['token'],'id':selected['id']})
        self.assertEqual(calls,[])
        self.assertIn('已更新',self.ui.manager.action_error)

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

    def test_native_public_mechanism_preview_discloses_its_example_inputs(self):
        public=self.ui.floor_state(self.session.snapshot())
        swarm=next(row for row in public['nodes'][1]['children'] if row['id']=='actors.mobs.swarm')
        mechanics=next(row for row in swarm['children'] if row['text']=='特殊攻击与机制')
        parameters=mechanics['children'][0]
        self.assertEqual(parameters['id'],'reference-params')
        self.assertIn('当前生命：40',parameters['text'])
        self.assertIn('整数伤害：20',parameters['text'])
        self.assertIn('未读取敌人',parameters['detail'])

    def test_native_spectral_reference_keeps_fixed_summon_depth(self):
        snap=self.session.snapshot();snap['data']['depth']=8
        self.session.snapshot=lambda:snap
        public=self.ui.floor_state(snap)
        calls=[];self.ui.manager.open_reference=lambda *args:calls.append(args)
        self.ui.frozen=False
        self.ui.dispatch({'action':'floor_reference','token':public['token'],'id':'actors.mobs.wraith@spectral-summon'})
        reference=calls[0][0]
        self.assertEqual(reference['entry'],'actors.mobs.wraith')
        self.assertEqual(reference['params']['depth'],4)
        self.assertIn('固定等效层数',reference['field_origins']['depth'])
        self.ui.dispatch({'action':'floor_reference','token':public['token'],'id':'actors.mobs.wraith'})
        self.assertEqual(calls[1][0]['params']['depth'],8)

    def test_native_condition_groups_are_collapsed_and_nested_references_still_open(self):
        public=self.ui.floor_state(self.session.snapshot())
        groups=[r for r in public['nodes'][1]['children'] if r['id'].startswith('group-')]
        self.assertTrue(groups)
        self.assertTrue(all(not row.get('expanded') for row in groups))
        calls=[];self.ui.manager.open_reference=lambda *args:calls.append(args)
        self.ui.frozen=False
        self.ui.dispatch({'action':'floor_reference','token':public['token'],'id':'actors.mobs.greatcrab'})
        self.assertEqual(calls[0][0]['entry'],'actors.mobs.greatcrab')
        self.assertEqual(self.ui.manager.action_error,'')


if __name__=='__main__': unittest.main()
