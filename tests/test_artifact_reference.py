"""Literal 4.0.2 artifact display, resource and grass-drop source vectors."""
import unittest

from companion.engine import Catalog
from companion.rules import NumericRules
from companion.values import PlayerValues


class ArtifactReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.values=PlayerValues(NumericRules(Catalog()))

    def detail(self, identity):
        return self.values.detail('items.artifacts.'+identity)

    def test_chains_only_uses_reachable_display_levels_and_maximum_target15(self):
        detail=self.detail('etherealchains')
        target=next(row for row in detail['blocks'] if row['title']=='虚空锁链储能目标')
        # Artifact.java:124 maps cap5 internal0..5 to displayed0,2,4,6,8,10.
        # EtherealChains.java:290,319 uses 5+2*internalLevel, not displayedLevel.
        self.assertEqual(target['rows'],[['+0','5'],['+2','7'],['+4','9'],['+6','11'],['+8','13'],['+10','15']])
        self.assertEqual(target['columns'][0],'显示等级')
        self.assertIn('不是硬性上限',target['note'])

    def test_sandals_growth_charge_and_all_twelve_seed_cost_vectors(self):
        detail=self.detail('sandalsofnature')
        tables={row['title']:row for row in detail['blocks'] if 'rows' in row}
        # SandalsOfNature.java cap3, chargeGain(3+2*n)/6, growth3+3*n.
        self.assertEqual(tables['自然之履成长与踩草充能']['rows'],
            [['+0','3','0.5'],['+3','6','5/6'],['+7','9','7/6'],['+10','已满级','1.5']])
        costs=tables['自然之履种子效果成本']['rows']
        self.assertEqual(len(costs),12)
        self.assertEqual([row[1] for row in costs],['8','20','20','80','20','20','20','12','40','40','12','12'])
        self.assertTrue(all(row[0] and 'plants.' not in row[0] for row in costs))
        metrics={metric['label']:metric for row in detail['blocks'] for metric in row.get('values',[])}
        self.assertEqual({key:metrics[key]['value'] for key in ('最大充能','每单位神器充能效果恢复','主动施放最大距离','主动施放耗时','每次喂种子耗时')},
                         {'最大充能':'100','每单位神器充能效果恢复':'2','主动施放最大距离':'3','主动施放耗时':'1','每次喂种子耗时':'1'})
        self.assertIn('当前视野',metrics['主动施放最大距离']['condition'])
        self.assertIn('下一阶段可再次使用',tables['自然之履成长与踩草充能']['note'])

    def test_sandals_grass_probability_and_immutable_official_sources(self):
        detail=self.detail('sandalsofnature')
        table=next(row for row in detail['blocks'] if row['title']=='自然之履踩草掉落概率')
        # HighGrass.java uses naturalismLevel=internal+1; seed1/(25-4*n), dew1/(6-n/2).
        expected=[('未装备',4,100/6),('+0',100/21,100/5.5),('+3',100/17,20),('+7',100/13,100/4.5),('+10',100/9,25)]
        for actual,(label,seed,dew) in zip(table['rows'],expected):
            self.assertEqual(actual[0],label)
            self.assertAlmostEqual(float(actual[1]),seed,places=3)
            self.assertAlmostEqual(float(actual[2]),dew,places=3)
        self.assertIn('两项分别判定',table['note'])
        self.assertIn('已践踏草地不能重复',table['note'])
        links=[row['url'] for row in detail['provenance']['links']]
        self.assertTrue(any('/57a4e06a4caf162446d1c28caa7983f0493fecf0/' in url and 'HighGrass.java' in url for url in links))
        self.assertTrue(any('SandalsOfNature.java' in url for url in links))

    def test_toolkit_nominal_time_does_not_claim_to_include_initial_update(self):
        table=next(row for row in self.detail('alchemiststoolkit')['blocks'] if row['title']=='炼金工具箱')
        self.assertEqual([row[1] for row in table['rows']],['100','81','64','49','36','25','16','9','4','1','0'])
        self.assertIn('不含首次更新',table['columns'][1])
        for condition in ('从101设为100','无诅咒','无魔法免疫','浮点','下一次更新'):
            self.assertIn(condition,table['note'])

    def test_chalice_prick_range_and_post_armor_floor_are_distinct(self):
        detail=self.detail('chaliceofblood')
        table=next(row for row in detail['blocks'] if row['title']=='圣杯升级风险与恢复')
        self.assertEqual(table['rows'][0][1],'3–7')
        self.assertEqual(table['rows'][9][1],'206–290')
        self.assertEqual(table['rows'][10][1],'已满级')
        self.assertIn('基础范围',table['columns'][1])
        metrics=next(row for row in detail['blocks'] if row['title']=='圣杯刺伤条件')['values']
        self.assertEqual([row['value'] for row in metrics],['1','1'])
        self.assertIn('不等于必定损失1生命',metrics[0]['condition'])
