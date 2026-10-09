import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from companion.engine import Catalog, analyze, PREFIX
from companion.rules import NumericRules
from companion.values import PlayerValues
from companion.quick_reference import detail_text, peek_reference


class QuickReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog=Catalog();cls.values=PlayerValues(NumericRules(cls.catalog))
        cls.session=SimpleNamespace(values=cls.values)

    def snap(self, equipment=(), *, weapon=None, strength=12, buffs=()):
        data=analyze({'depth':1,'version':920,'challenges':0,'hero':{'class':'WARRIOR','HP':20,'HT':30,
                      'STR':strength,'lvl':1,'buffs':list(buffs), 'weapon':weapon,
                      'inventory':list(equipment)}},self.catalog)
        return {'data':data,'settings':{'mode':'save'},'error':None,'age_seconds':100,'stale':True}

    def test_complete_detail_keeps_values_conditions_tables_and_notes(self):
        detail=self.values.detail('items.scrolls.scrollofupgrade',{'level':4})
        text=detail_text(detail)
        self.assertIn('10 %',text);self.assertIn('未硬化',text)
        self.assertIn('升级前等级',text);self.assertIn('+10',text)
        self.assertNotIn('Random.',text)

    def test_reference_not_current_actor_and_unknown_level_not_invented(self):
        snap=self.snap(strength=10);snap['data']['items']=[{'name':'短剑','key':'items.weapon.melee.shortsword',
                'location':'主武器','known':True,'level_known':False,'tier':2,'level':99}]
        card=peek_reference(self.session,snap)
        self.assertIn('+0基础参考',card['text']);self.assertNotIn('+99',card['text'])
        self.assertIn('旧存档',card['source']);self.assertIn('非此刻局势',card['note'])
        self.assertIn('基础伤害 2–15',card['text'])
        self.assertNotIn('基础力量低于装备基础需求',card['note'])

    def test_unknown_identity_never_queries_undisclosed_numeric_effect(self):
        snap=self.snap();snap['data']['items']=[{'name':'未鉴定物品','key':'hidden-identity',
                      'location':'主武器','known':False,'available':False,'level':99,
                      'level_known':False}]
        values=Mock()
        card=peek_reference(SimpleNamespace(values=values),snap)
        values.detail.assert_not_called()
        self.assertNotIn('hidden-identity',str(card))
        self.assertIn('尚未鉴定',card['text'])
        self.assertIn('遗落行囊：未确认可用',card['text'])
        self.assertNotIn('基础力量低于装备基础需求',card['note'])

    def test_lost_weapon_reference_marks_unconfirmed_availability_but_kept_weapon_is_normal(self):
        for kept in (False,True):
            with self.subTest(kept_lost=kept):
                weapon={'__className':PREFIX+'items.weapon.melee.Sword','level':2,
                        'levelKnown':True}
                if kept:
                    weapon['kept_lost']=True
                snap=self.snap(weapon=weapon,strength=13,
                               buffs=[{'__className':PREFIX+'actors.buffs.LostInventory'}])
                self.assertEqual(snap['data']['items'][0]['available'],kept)
                card=peek_reference(self.session,snap)
                self.assertIn('基础攻击耗时 1 回合',card['text'])
                self.assertIn('基础命中倍率 1 倍',card['text'])
                if kept:
                    self.assertNotIn('未确认可用',card['text'])
                    self.assertNotIn('以下仅作基础参考',card['text'])
                else:
                    self.assertIn('遗落行囊：未确认可用，以下仅作基础参考。',card['text'])

    def test_known_strength_shortfall_conditions_base_values_without_recalculating(self):
        for strength in (12,13,15):
            with self.subTest(strength=strength):
                snap=self.snap(weapon={'__className':PREFIX+'items.weapon.melee.Sword',
                                       'level':2,'levelKnown':True},strength=strength)
                card=peek_reference(self.session,snap)
                self.assertIn('力量需求 13 点',card['text'])
                self.assertIn('基础攻击耗时 1 回合',card['text'])
                self.assertIn('基础命中倍率 1 倍',card['text'])
                if strength==12:
                    self.assertIn('基础力量低于装备基础需求',card['note'])
                    self.assertIn('若总力量仍不足，上述基础值未计力量不足惩罚',card['note'])
                else:
                    self.assertNotIn('基础力量低于装备基础需求',card['note'])
                    self.assertNotIn('力量不足惩罚',card['note'])

    def test_pin_has_encyclopedia_source_not_save_age(self):
        card=peek_reference(self.session,self.snap(),('items.potions.potionofhealing',{'max_hp':100,'hp':10}))
        self.assertIn('百科',card['source']);self.assertNotIn('存档',card['source'])
        self.assertIn('仅列部分数值',card['note']);self.assertIn('治疗池总量',card['text'])
        self.assertIn('你的最大生命 100',card['text']);self.assertIn('你的当前生命 10',card['text'])

    def test_unknown_original_class_armor_tier_is_not_assumed(self):
        snap=self.snap();snap['data']['items']=[{'name':'战士护甲','key':'items.armor.warriorarmor',
                'location':'护甲','known':True,'level_known':True,'level':4,'tier':None}]
        values=Mock()
        card=peek_reference(SimpleNamespace(values=values),snap)
        values.detail.assert_not_called();self.assertIn('原护甲阶数未知',card['text'])
        self.assertNotIn('基础减伤 ',card['text'])

    def test_non_numeric_explanation_is_a_string(self):
        self.assertIn('没有独立战斗数值',detail_text({'non_numeric':True,'blocks':[]}))

    def test_first_save_not_created_yet_is_ready_and_does_not_send_user_to_settings(self):
        card=peek_reference(self.session,{'data':None,'error':'','waiting_for_save':True})
        self.assertIn('已就绪',card['source'])
        self.assertIn('游戏保存后会自动显示',card['text'])
        self.assertIn('无需先配置',card['note'])
        self.assertNotIn('局势不可读',card['source'])


if __name__=='__main__':unittest.main()
