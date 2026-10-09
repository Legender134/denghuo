"""Player workflow boundaries grounded in official 4.0.2 source examples."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from companion.decisions import context_actions, public_context
from companion.engine import Catalog, PREFIX, analyze
from companion.rules import NumericRules
from companion.service import Session, validate_settings
from companion.values import PlayerValues
from companion.values_decisions import compare_equipment


class MatureContextTests(unittest.TestCase):
    def test_failed_delayed_browser_open_does_not_break_save_monitoring(self):
        with tempfile.TemporaryDirectory(prefix='lamp-panel-polling-') as directory:
            session=Session(Path(directory)/'settings.json')
            healthy={'hero':{'hp':8,'ht':40}}
            def refresh():
                session.data=healthy
            def backup_tick(root):
                session.stop.set()
            with patch.object(session.panel,'tick',side_effect=ValueError('browser unavailable')), \
                 patch.object(session,'refresh',side_effect=refresh) as refresh_call, \
                 patch.object(session.backups,'tick',side_effect=backup_tick) as backup_call, \
                 self.assertLogs(level='ERROR') as logs:
                session.run()
            self.assertIs(session.data,healthy)
            self.assertEqual(session.error,'')
            refresh_call.assert_called_once()
            backup_call.assert_called_once()
            self.assertIn('Panel opening failed',logs.output[0])

    @classmethod
    def setUpClass(cls):
        cls.catalog=Catalog()
        cls.values=PlayerValues(NumericRules(cls.catalog))

    def game(self, *, buffs=(), items=(), challenges=0):
        return {'version':922,'depth':2,'challenges':challenges,
                'hero':{'HP':8,'HT':40,'lvl':3,'STR':12,'class':'WARRIOR',
                        'buffs':list(buffs),'inventory':list(items)}}

    def buff(self,name,**fields):
        return {'__className':PREFIX+'actors.buffs.'+name,**fields}

    def item(self,name,quantity=1,**fields):
        return {'__className':PREFIX+'items.'+name,'quantity':quantity,**fields}

    def snapshot(self,game,stale=False):
        return {'settings':{'mode':'save'},'data':analyze(game,self.catalog),'modified':123,
                'stale':stale,'active_slot':1,'error':''}

    def actions(self,snapshot):
        with tempfile.TemporaryDirectory(prefix='lamp-mature-context-') as d:
            session=Session(Path(d)/'settings.json',catalog=self.catalog)
            return context_actions(session,snapshot)

    def comparison(self,**params):
        return compare_equipment(self.values,{'id_a':'items.weapon.melee.sword',
             'id_b':'items.weapon.melee.longsword','level_a':0,'level_b':0,'strength':12,**params})

    def test_negative_known_weapon_retains_damage_and_nonnegative_strength_rule(self):
        # Sword inherits MeleeWeapon tier3: -1 is 2..16, +0 is 3..20, both require14.
        result=self.comparison(level_a=-1)
        sword=result['choices'][0]
        self.assertEqual([sword['current'][k] for k in ('最低基础伤害','最高基础伤害','力量需求')],['2','16','14'])
        self.assertEqual([sword['upgraded'][k] for k in ('最低基础伤害','最高基础伤害','力量需求')],['3','20','14'])
        detail=self.values.detail('items.weapon.melee.sword',{'level':-1})
        self.assertEqual(next(v['min'] for v in detail['inputs'] if v['key']=='level'),-100)
        self.assertTrue(any(b['title']=='当前 -1 装备数值' for b in detail['blocks']))
        with self.assertRaises(ValueError):self.values.detail('items.wands.wandofmagicmissile',{'level':-1})

    def test_budget_exposes_remaining_gap_and_minimum_investment(self):
        # Longsword tier4: at STR13, +3 still needs14; +6 reaches13.
        result=self.comparison(planning='1',upgrade_budget=3,strength_budget=1)
        plan=result['planning']['choices'][1]
        self.assertEqual(result['planning']['effective_strength'],13)
        self.assertEqual((plan['needed_upgrades'],plan['spent_upgrades'],plan['planned_level'],plan['remaining_strength_deficit'],plan['within_budget']),(6,3,3,1,False))
        enough=self.comparison(planning='1',upgrade_budget=8,strength_budget=1)['planning']['choices'][1]
        self.assertEqual((enough['spent_upgrades'],enough['remaining_strength_deficit'],enough['within_budget']),(6,0,True))
        self.assertNotIn('planning',self.comparison())
        with self.assertRaisesRegex(ValueError,'规划有效力量.*1–1000'):self.comparison(strength=1000,planning='1',strength_budget=1)

    def test_full_budget_keeps_minimum_mode_and_consistent_structured_units(self):
        full=self.comparison(planning='1',upgrade_budget=8,strength_budget=1,investment_mode='all')
        choice=full['planning']['choices'][1]
        self.assertEqual((choice['planned_level'],choice['spent_upgrades'],choice['remaining_upgrades']),(8,8,0))
        self.assertEqual([r['upgrades'] for r in choice['alternatives']],list(range(9)))
        self.assertEqual(full['planning']['mode'],'all')
        self.assertEqual(self.comparison(planning='1',upgrade_budget=8,strength_budget=1)['planning']['choices'][1]['spent_upgrades'],6)
        units={cell['label']:cell['unit'] for cell in choice['metric_rows']}
        self.assertEqual((units['最低基础伤害'],units['攻击耗时'],units['攻击距离']),('HP','回合','格'))
        self.assertTrue(all(row['unit']==units[row['label']] for row in full['rows']))
        self.assertTrue(all(change['unit']==units[change['label']] for item in choice['alternatives'] for change in item['changes']))
        capped=self.comparison(level_a=99,planning='1',upgrade_budget=4,investment_mode='all')['planning']['choices'][0]
        self.assertEqual((capped['planned_level'],capped['remaining_upgrades']),(100,3))

    def test_ring_known_curse_same_type_combination_and_unknown_boundary(self):
        args={'id_a':'items.rings.ringofhaste','id_b':'items.rings.ringofhaste','level_a':1,'level_b':1,'strength':12,
              'curse_a':'0','curse_b':'1','ring_pair_a':'1','ring_pair_level_a':0,'ring_pair_curse_a':'0'}
        result=compare_equipment(self.values,args)
        self.assertEqual(result['choices'][0]['current']['合计戒指效果等级'],'3')
        self.assertAlmostEqual(float(result['choices'][0]['current']['移动速度倍率']),1.15**3,places=5)
        self.assertEqual(result['choices'][1]['current']['合计戒指效果等级'],'-1')
        self.assertIn('after_curse_removed',result['choices'][1])
        unknown=compare_equipment(self.values,{**args,'curse_b':'unknown'})['choices'][1]
        self.assertNotIn('移动速度倍率',unknown['current'])
        self.assertEqual(unknown['current']['戒指效果'],'诅咒状态未确认')
        # Official RingOfForce min/max forces tier=1 only in the base range when bonus<=0.
        # Brawler extra retains the STR-derived tier (STR22 => tier6), giving +5 at bonus-2.
        force=compare_equipment(self.values,{'id_a':'items.rings.ringofforce','id_b':'items.rings.ringofforce',
            'level_a':0,'level_b':0,'strength':22,'curse_a':'1','curse_b':'0'})['choices'][0]['current_metrics']
        unarmed=next(cell for cell in force if '徒手' in cell['label'] and '拳击' not in cell['label'])
        brawler=next(cell for cell in force if '拳击' in cell['label'])
        self.assertEqual((unarmed['value'],brawler['value'],unarmed['unit'],brawler['unit']),('0–6','5–11','HP','HP'))
        with self.assertRaisesRegex(ValueError,'B等级.*0–99'):compare_equipment(self.values,{**args,'level_b':-1})
        with self.assertRaisesRegex(ValueError,'同一类别'):compare_equipment(self.values,{**args,'id_b':'items.wands.wandofmagicmissile'})

    def test_wand_context_charge_branches_units_and_cursed_normal_effect_exclusion(self):
        params={'id_a':'items.wands.wandoffireblast','id_b':'items.wands.wandofblastwave','level_a':1,'level_b':1,'strength':12,'charges_a':2}
        result=compare_equipment(self.values,params)
        self.assertEqual(result['choices'][0]['current']['本次焰浪基础伤害'],'4–12')
        self.assertEqual(next(r['unit'] for r in result['rows'] if r['label']=='本次焰浪基础伤害'),'HP')
        self.assertEqual(next(r['unit'] for r in result['rows'] if r['label']=='中心击退力'),'格')
        cursed=compare_equipment(self.values,{**params,'curse_b':'1'})['choices'][1]
        self.assertNotIn('最低基础伤害',cursed['current'])
        self.assertIn('after_curse_removed',cursed)
        transfusion=compare_equipment(self.values,{'id_a':'items.wands.wandoftransfusion','id_b':'items.wands.wandoftransfusion',
            'target_hp_a':5,'target_max_hp_a':40,'max_hp_a':60,'level_a':2})
        self.assertEqual(transfusion['params']['target_hp_a'],5)
        self.assertEqual(transfusion['choices'][0]['current']['目标实际治疗'],'9')

    def test_bridge_selected_plan_reuses_client_and_fresh_url_validates_identity(self):
        from companion.panel import PanelBridge
        opened=[];clock=[10]
        bridge=PanelBridge(clock=lambda:clock[0],opener=lambda url:opened.append(url) or True);bridge.bind('http://127.0.0.1:12345')
        identity='a'*32;bridge.request('workspace',plan_id=identity)
        self.assertEqual(opened,['http://127.0.0.1:12345/?plan='+identity+'#workspace'])
        first=bridge.heartbeat('abcdefgh12345678');self.assertEqual(first['plan_id'],identity)
        bridge.heartbeat('abcdefgh12345678',first['serial']);bridge.request('workspace',plan_id='b'*32)
        self.assertEqual(bridge.heartbeat('abcdefgh12345678')['plan_id'],'b'*32)
        self.assertEqual(len(opened),1)
        with self.assertRaises(ValueError):bridge.request('workspace',plan_id='../../bad')

    def test_comparison_rejects_fractional_boolean_and_out_of_range_budgets(self):
        for params in ({'level_a':-.5},{'level_a':True},{'planning':'1','upgrade_budget':101},
                       {'planning':'1','strength_budget':True},{'planning':'maybe'}):
            with self.subTest(params=params),self.assertRaises(ValueError):self.comparison(**params)

    def test_water_blocks_and_source_current_shield_are_not_duplicated(self):
        detail=self.values.detail('items.waterskin')
        for title in ('按所填露珠条件计算','露珠生效条件'):
            self.assertEqual(sum(b['title']==title for b in detail['blocks']),1)
        snapshot=self.snapshot(self.game(buffs=[self.buff('Barrier',shielding=25)],
            items=[self.item('Waterskin',volume=20)]),stale=True)
        self.assertEqual(public_context(snapshot)['current_shield'],25)
        water=next(o for o in self.actions(snapshot)['options'] if o['entry']=='items.waterskin')
        self.assertEqual((water['params']['current_shield'],water['params']['dew_volume']),(25,20))
        self.assertEqual(water['source']['label'],'旧快照记录')
        self.assertNotIn('shielding_dew',water['params'])

    def test_only_whitelisted_valid_single_barrier_is_public(self):
        for buffs in ([self.buff('Barrier',shielding=True)],[self.buff('Barrier',shielding=-1)],
                      [self.buff('Barrier',shielding=10001)],[self.buff('Barrier')],
                      [self.buff('Barrier',shielding=25),self.buff('Barrier',shielding=40)],
                      [{'__className':'unknown.private.Barrier','shielding':999}],
                      [self.buff('FireShield',shielding=999)]):
            with self.subTest(buffs=buffs):
                snapshot=self.snapshot(self.game(buffs=buffs))
                self.assertNotIn('current_shield',public_context(snapshot))
                self.assertNotIn('999',str(snapshot['data']['buffs']))

    def test_hunger_links_known_available_food_with_action_and_challenge_boundary(self):
        snapshot=self.snapshot(self.game(buffs=[self.buff('Hunger',level=455)],
            items=[self.item('food.Food',quantity=2),self.item('food.Pasty')]))
        actions=self.actions(snapshot)
        food=next(o for o in actions['options'] if o['entry']=='items.food.food')
        pie=next(o for o in actions['options'] if o['entry']=='items.food.pasty')
        cells={v['label']:v['value'] for v in food['values']}
        self.assertEqual((food['quantity'],pie['quantity']),(2,1))
        self.assertEqual((cells['恢复饱食'],cells['进食耗时'],cells['进食后饥饿值参考']),('300','3','155'))
        self.assertIn('节庆',pie['note'])
        risk=next(r for r in actions['risks'] if r['id']=='starving')
        self.assertTrue(any(r['entry']=='actors.buffs.hunger' for r in risk['references']))
        snapshot=self.snapshot(self.game(buffs=[self.buff('Hunger',level=455),self.buff('Paralysis')],
            items=[self.item('food.Food')],challenges=1))
        food=next(o for o in self.actions(snapshot)['options'] if o['entry']=='items.food.food')
        self.assertEqual(next(v['value'] for v in food['values'] if v['label']=='饥饿游戏基础饱食恢复'),'100')
        self.assertIn('限制主动行动',food['restriction'])

    def test_lost_food_is_not_offered_and_hidden_potion_identity_is_absent(self):
        snapshot=self.snapshot(self.game(buffs=[self.buff('Hunger',level=455),self.buff('LostInventory')],
            items=[self.item('food.Food',quantity=2),self.item('food.Pasty',kept_lost=True),
                   self.item('potions.PotionOfHealing')]))
        actions=self.actions(snapshot)
        self.assertFalse(any(o['entry']=='items.food.food' for o in actions['options']))
        self.assertTrue(any(o['entry']=='items.food.pasty' for o in actions['options']))
        self.assertFalse(any(o['entry']=='items.potions.potionofhealing' for o in actions['options']))

    def test_promoted_intents_resolve_with_category_scope_and_official_sources(self):
        for query in ('力量不足','怎么逃跑','脱离接触'):
            with self.subTest(query=query):
                found=self.catalog.search(query)
                self.assertGreater(found['total'],0)
                self.assertEqual(found['query_interpretation'],'需求查询')
                self.assertTrue(all(row['numeric_refs'] for row in found['entries']))
                scoped=self.catalog.search(query,'物品')
                self.assertTrue(all(row['category']=='物品' for row in scoped['entries']))

    def test_direct_panel_default_and_persisted_preference_are_validated(self):
        with tempfile.TemporaryDirectory(prefix='lamp-startup-surface-') as d:
            p=Path(d)/'settings.json'
            session=Session(p,catalog=self.catalog)
            self.assertEqual(session.settings['startup_surface'],'panel')
            session.update_settings({'startup_surface':'native'})
            self.assertEqual(Session(p,catalog=self.catalog).settings['startup_surface'],'native')
        with self.assertRaises(ValueError):validate_settings({'startup_surface':'unknown'})
