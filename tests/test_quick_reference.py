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

    def snap(self, equipment=()):
        data=analyze({'depth':1,'version':920,'challenges':0,'hero':{'class':'WARRIOR','HP':20,'HT':30,
                      'STR':12,'lvl':1,'buffs':[], 'inventory':list(equipment)}},self.catalog)
        return {'data':data,'settings':{'mode':'save'},'error':None,'age_seconds':100,'stale':True}

    def test_complete_detail_keeps_values_conditions_tables_and_notes(self):
        detail=self.values.detail('items.scrolls.scrollofupgrade',{'level':4})
        text=detail_text(detail)
        self.assertIn('10 %',text);self.assertIn('未硬化',text)
        self.assertIn('升级前等级',text);self.assertIn('+10',text)
        self.assertNotIn('Random.',text)

    def test_reference_not_current_actor_and_unknown_level_not_invented(self):
        snap=self.snap();snap['data']['items']=[{'name':'短剑','key':'items.weapon.melee.shortsword',
                'location':'主武器','known':True,'level_known':False,'tier':2,'level':99}]
        card=peek_reference(self.session,snap)
        self.assertIn('+0基础参考',card['text']);self.assertNotIn('+99',card['text'])
        self.assertIn('旧存档',card['source']);self.assertIn('非此刻局势',card['note'])
        self.assertIn('基础伤害 2–15',card['text'])

    def test_unknown_identity_never_queries_undisclosed_numeric_effect(self):
        snap=self.snap();snap['data']['items']=[{'name':'未鉴定物品','key':'hidden-identity',
                      'location':'主武器','known':False}]
        values=Mock()
        card=peek_reference(SimpleNamespace(values=values),snap)
        values.detail.assert_not_called()
        self.assertNotIn('hidden-identity',str(card))
        self.assertIn('尚未鉴定',card['text'])

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


if __name__=='__main__':unittest.main()
