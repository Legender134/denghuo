"""Source-bound public encounter rules, independent of saved hidden contents."""
import unittest
import json
from queue import Queue
from types import SimpleNamespace
from unittest.mock import patch
from tests import test_scouting as scouting_tests
from companion.native_manager import NativeManager
from companion.native_host import MAX_LINE, NativeHost
from companion.engine import Catalog
from companion.floor_guide import floor_encounters
from companion.values import PlayerValues
from companion.rules import NumericRules


class FloorGuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog=Catalog()

    def guide(self, depth, branch=0, version=922, challenges=None):
        return floor_encounters({'version':version,'depth':depth,'branch':branch,'challenges':challenges},self.catalog)

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

    def test_guardian_trap_encounter_is_conditional_folded_and_region_bounded(self):
        identity='levels.traps.guardiantrap$guardian'
        values=PlayerValues(NumericRules(self.catalog))
        for depth in (11,12,13,14,16,17,18,19,21,22,23,24):
            guide=self.guide(depth,challenges=0)
            row=next(r for r in guide['rows'] if r['id']==identity)
            self.assertEqual(row['group'],'机关/陷阱条件')
            self.assertEqual(row['fold_group'],'机关/陷阱条件')
            self.assertIn(f'最多召唤 {(depth-5)//5} 个',row['condition'])
            for phrase in ('存在且激活守卫陷阱','可用生成格','不保证本层存在','不属于普通刷新'):
                self.assertIn(phrase,row['condition'])
            detail=values.detail(identity,{'depth':depth})
            metrics={r['label']:r['value'] for r in detail['blocks'][0]['values']}
            self.assertEqual(row['hp'],metrics['初始生命'])
            self.assertEqual(metrics['基础经验'],'0')
            weapon=next(r for r in detail['blocks'][1]['rows'] if '所持武器' in r[0])
            self.assertEqual(weapon[2],'100%')
            self.assertTrue(any(s['path'].endswith('/GuardianTrap.java') for s in guide['sources']))
        for branch,depths in ((0,(1,6,9,10,15,20,25,26)),(1,range(11,20))):
            for depth in depths:
                self.assertNotIn(identity,{r['id'] for r in self.guide(depth,branch)['rows']})

    def test_floor_pylon_and_barren_land_pass_verified_challenge_parameters(self):
        values=PlayerValues(NumericRules(self.catalog))
        for mask,health in ((0,'50'),(256,'80'),(511,'80'),(None,'50')):
            row=next(r for r in self.guide(15,challenges=mask)['rows'] if r['id']=='actors.mobs.pylon')
            self.assertEqual(row['hp'],health)
            detail=values.detail(row['id'],row['reference_params'])
            self.assertEqual(detail['blocks'][0]['values'][0]['value'],health)
        for mask,active in ((0,0),(1,0),(8,1),(256,0),(511,1),(None,0)):
            guide=self.guide(22,challenges=mask)
            eye=next(r for r in guide['rows'] if r['id']=='actors.mobs.eye')
            self.assertEqual(eye['reference_params'],{'no_herbalism':active})
            detail=values.detail(eye['id'],{'hero_level':20,**eye['reference_params']})
            dew=next(r for r in detail['blocks'][1]['rows'] if r[0]=='露珠')
            self.assertEqual(dew[2],'0%' if active else '50%')
            self.assertEqual(guide['challenges_known'],mask is not None)

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
        self.assertEqual(sum(r['id'].startswith('actors.mobs.quest.vault.') for r in vault['rows']),10)
        mechanisms={r['id']:r for r in vault['rows'] if r['group']=='宝库机关'}
        self.assertEqual(set(mechanisms),{'actors.mobs.npcs.vaultsentry','actors.mobs.npcs.vaultlaser'})
        for row in mechanisms.values():
            self.assertEqual(row['fold_group'],'宝库机关/房间条件')
            self.assertIn('不可破坏',row['condition'])
            self.assertEqual(row['hp'],'不可破坏')
            self.assertEqual(row['damage'],'不使用普通攻击')
        self.assertTrue(any(s['path'].endswith('/VaultLasersRoom.java') for s in vault['sources']))
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

    def test_saved_stronger_bosses_switches_verified_health_and_support_rules(self):
        # HP constants and branches come from the pinned original Java initializers,
        # DwarfKing.summonSubject, YogDzewa pools, and DM300.totalPylonsToActivate.
        values=PlayerValues(NumericRules(self.catalog))
        for depth,boss,ordinary,strong in ((5,'goo',100,120),(10,'tengu',200,250),
                                          (15,'dm300',300,400),(20,'dwarfking',300,450),(25,'yogdzewa',1000,1000)):
            for mask,expected in ((0,ordinary),(256,strong),(511,strong)):
                guide=self.guide(depth,challenges=mask)
                self.assertTrue(guide['challenges_known'])
                self.assertEqual(guide['challenges_mask'],mask)
                row=next(r for r in guide['rows'] if r['id']=='actors.mobs.'+boss)
                self.assertEqual(row['hp'],str(expected))
                detail=values.detail(row['id'],row['reference_params'])
                self.assertEqual(detail['blocks'][0]['values'][0]['value'],row['hp'])
                field=next(r for r in detail['inputs'] if r['key']=='stronger_bosses')
                self.assertEqual(field['value'],int(bool(mask&256)))
        king={r['id']:r for r in self.guide(20,challenges=256)['rows']}
        self.assertEqual(king['actors.mobs.dwarfking$dkgolem']['fold_group'],'绝命头目挑战支援')
        self.assertIn('每第9次',king['actors.mobs.dwarfking$dkgolem']['condition'])
        yog={r['id']:r for r in self.guide(25,challenges=256)['rows']}
        for identity in ('yogeye','yogscorpio'):
            self.assertIn('未读取本局血巢计数',yog['actors.mobs.yogdzewa$'+identity]['condition'])
            self.assertEqual(yog['actors.mobs.yogdzewa$'+identity]['fold_group'],'绝命头目挑战支援')
        self.assertTrue(all('共6拳' in r['condition'] and '同一配对不会同轮' in r['condition'] for r in yog.values() if r['id'].startswith('actors.mobs.yogfist$')))
        self.assertIn('最后2个名额固定',yog['actors.mobs.yogdzewa$yogripper']['condition'])
        pylon=next(r for r in self.guide(15,challenges=256)['rows'] if r['id']=='actors.mobs.pylon')
        self.assertIn('共激活3座',pylon['condition'])

    def test_missing_or_invalid_challenges_are_an_explicit_ordinary_assumption(self):
        for mask in (None,True,False,-1,512,'256',256.0):
            guide=self.guide(20,challenges=mask)
            self.assertFalse(guide['challenges_known'])
            self.assertIsNone(guide['challenges_mask'])
            self.assertIn('挑战信息未确认',guide['note'])
            rows={r['id']:r for r in guide['rows']}
            self.assertEqual(rows['actors.mobs.dwarfking']['hp'],'300')
            self.assertNotIn('actors.mobs.dwarfking$dkgolem',rows)
        for depth in (16,17,18,19):
            self.assertEqual(len([r for r in self.guide(depth,1)['rows'] if r['group']=='宝库机关']),2)

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
        self.assertFalse(public['nodes'][1]['expanded'])
        self.assertTrue(all(not row.get('expanded') for row in public['nodes'][1]['children']))
        self.assert_native_transport(public)
        self.ui.reveal_floor({'token':public['token']})
        work,finish=self.jobs.pop();result=work();finish(result,None)
        revealed=self.ui.floor_state(snap)
        self.assert_native_transport(revealed)
        self.assertTrue(revealed['revealed'])
        saved=next(row for row in revealed['nodes'][0]['children'] if row['id']=='hidden-mobs')
        self.assertFalse(saved.get('expanded',False))
        self.assertTrue(any(row['text'].startswith('黄金宝箱怪') for row in saved['children']))
        self.assertEqual(self.tree(),before)
        self.assertFalse(self.session.settings['reveal'])
        self.ui.reveal_floor({'token':public['token']})
        self.assertFalse(self.ui.floor_state(snap)['revealed'])

    def assert_native_transport(self, state):
        host=NativeHost.__new__(NativeHost)
        host.closed=host.failed=False
        host.serial=host.revision=0
        host.session='a'*32
        host.outgoing=Queue(maxsize=1)
        host.error=self.fail
        self.assertTrue(host.command('manager_state',floor_guide=state))
        wire=host.outgoing.get_nowait()
        self.assertLessEqual(len(wire),MAX_LINE)
        self.assertEqual(json.loads(wire)['floor_guide'],state)

    def test_native_leaf_details_keep_own_fields_and_shared_conditions_on_parent(self):
        block={'title':'战斗与掉落','note':'完整块条件；仅在父节点传输一次。',
               'values':[{'label':'伤害','value':'3–8','unit':'点','condition':'仅已命中时'}],
               'columns':['物品','数量','概率','附加条件'],
               'rows':[['测试物品',1,'25%','第四列条件不得丢失']]}
        with patch.object(PlayerValues,'detail',return_value={'inputs':[],'blocks':[block]}):
            public=self.ui.floor_state(self.session.snapshot())
        monster=next(row for row in public['nodes'][1]['children'] if row['id']=='actors.mobs.crab')
        preview=monster['children'][0]
        self.assertEqual(preview['detail'],block['note'])
        self.assertEqual([row['detail'] for row in preview['children']],
                         ['伤害：3–8 点\n仅已命中时','物品：测试物品\n数量：1\n概率：25%\n附加条件：第四列条件不得丢失'])
        self.assertIn('本层条件参考',monster['detail'])
        self.assert_native_transport(public)

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
        heaps=next(row for row in revealed['nodes'][0]['children'] if row['id']=='hidden-heaps')
        self.assertFalse(heaps.get('expanded',False))
        heap=next(row for row in heaps['children'] if row['id']=='heaps-0')
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
        saved=next(row for row in revealed['nodes'][0]['children'] if row['id']=='hidden-mobs')
        self.assertTrue(any('保存生命 22 / 36' in row['text'] for row in saved['children']))
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
        heaps=next(row for row in revealed['nodes'][0]['children'] if row['id']=='hidden-heaps')
        selected=next(row for row in heaps['children'] if row['id']=='heaps-0')['children'][0]
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
        self.assertEqual(reference['source'],{'mode':'save','slot':snap['active_slot'],'snapshot_at':snap['modified']})
        self.assertEqual(reference['stamp'][4],snap['revision'])
        self.assertIn('下水道螃蟹',reference['source_label'])
        self.assertIn('0次示例',reference['source_label'])
        self.assertIn('未读取本局计数',reference['conditions'])
        self.assertIsNone(source)
        self.assertEqual(self.ui.manager.action_error,'')

    def test_saved_floor_reference_keeps_its_captured_slot_and_time(self):
        from tests.test_native_controllers import ControllerFixture
        controller = ControllerFixture()
        controller.setUp()
        self.addCleanup(controller.doCleanups)
        controller.session = self.session
        controller.manager.session = self.session
        self.ui.manager.open_reference = controller.lookup.open_reference
        self.ui.frozen = False
        snap = self.session.snapshot()
        public = self.ui.floor_state(snap)
        self.ui.dispatch({'action': 'floor_reference', 'token': public['token'], 'id': 'actors.mobs.crab'})
        controller.finish()
        self.assertTrue(controller.lookup.save_plan('本层螃蟹参考'))
        record_id = controller.lookup.saved_plan['id']
        expected = {'slot': snap['active_slot'], 'snapshot_at': snap['modified']}
        self.session.update_settings({'slot': 2})
        self.session.refresh()
        self.assertTrue(controller.lookup.open_plan(record_id, False))
        origin = controller.lookup.saved_plan['origin']
        self.assertEqual({key: origin[key] for key in expected}, expected)
        self.assertTrue(origin['fields']['hero_level'].startswith('快照 · 槽位 1 · '))
        self.assertTrue(origin['fields']['hero_level'].endswith(' 保存'))
        self.assertEqual(controller.lookup.calculated['hero_level'], 5)

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

    def test_challenge_snapshot_catalog_cache_and_full_reference_stay_consistent(self):
        from companion.scouting import inspect_saved
        self.game.update(depth=20,challenges=0)
        self.save();self.session.refresh()
        ordinary=self.ui.floor_state(self.session.snapshot())
        self.assertNotIn('actors.mobs.dwarfking$dkgolem',self.ui._floor_reference_rows)
        self.game['challenges']=256
        self.save();self.session.refresh()
        snap=self.session.snapshot()
        self.assertEqual(snap['data']['challenges_mask'],256)
        self.assertTrue(snap['data']['challenges_known'])
        public=self.ui.floor_state(snap)
        self.assertNotEqual(public['owner'],ordinary['owner'])
        king=next(r for r in public['nodes'][1]['children'] if r['id']=='actors.mobs.dwarfking')
        self.assertIn('生命 450',king['text'])
        health=next(b for b in king['children'] if b['text']=='常规战斗数值')['children'][0]
        self.assertIn('450',health['text'])
        group=next(r for r in public['nodes'][1]['children'] if r['id']=='group-绝命头目挑战支援')
        self.assertFalse(group.get('expanded',False))
        self.assertEqual(group['children'][0]['id'],'actors.mobs.dwarfking$dkgolem')
        catalog=inspect_saved(self.session,{'action':'catalog'})
        self.assertEqual(catalog['source']['challenges_mask'],256)
        self.assertTrue(catalog['source']['challenges_known'])
        self.assertEqual(catalog['encounters']['challenges_mask'],256)
        calls=[];self.ui.manager.open_reference=lambda *args:calls.append(args);self.ui.frozen=False
        self.ui.dispatch({'action':'floor_reference','token':public['token'],'id':'actors.mobs.dwarfking'})
        self.assertEqual(calls[0][0]['params']['stronger_bosses'],1)
        self.assertIn('所选存档',calls[0][0]['field_origins']['stronger_bosses'])
        self.game.pop('challenges');self.save();self.session.refresh()
        unknown=self.ui.floor_state(self.session.snapshot())
        self.assertIn('挑战信息未确认',unknown['nodes'][1]['detail'])
        king=next(r for r in unknown['nodes'][1]['children'] if r['id']=='actors.mobs.dwarfking')
        self.assertIn('生命 300',king['text'])
        self.assertIsNone(self.session.snapshot()['data']['challenges_mask'])

    def test_vault_mechanisms_are_closed_and_reference_existing_numeric_profiles(self):
        self.game.update(depth=17,branch=1,challenges=0)
        self.save();self.session.refresh()
        public=self.ui.floor_state(self.session.snapshot())
        group=next(r for r in public['nodes'][1]['children'] if r['id']=='group-宝库机关/房间条件')
        self.assertFalse(group.get('expanded',False))
        self.assertEqual({r['id'] for r in group['children']},{'actors.mobs.npcs.vaultsentry','actors.mobs.npcs.vaultlaser'})
        for row in group['children']:
            self.assertIn('生命 不可破坏',row['text'])
            self.assertFalse(row.get('expanded',False))
            self.assertTrue(any(b['text']=='特殊攻击与机制' for b in row['children']))


if __name__=='__main__': unittest.main()
