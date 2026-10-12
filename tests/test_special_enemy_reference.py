"""Public rule contracts for special enemies, with no game or saved-target reads."""
from types import SimpleNamespace
import unittest

from companion.engine import Catalog
from companion.rules import NumericRules
from companion.values import PlayerValues


class SpecialEnemyReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.values = PlayerValues(NumericRules(Catalog()))

    def detail(self, name, **params):
        return self.values.detail('actors.mobs.' + name, params)

    def block(self, name, title):
        return next(block for block in self.detail(name)['blocks'] if block['title'] == title)

    def metrics(self, name, title='特殊攻击与机制'):
        return {row['label']: row for row in self.block(name, title)['values']}

    def test_exile_reach_is_bounded_by_path_and_passivity_is_conditional(self):
        rules = self.metrics('gnollexile')
        reach = rules['长矛最大攻击距离']
        self.assertEqual((reach['value'], reach['unit']), ('2', '格'))
        for condition in ('相邻时可攻击', '八方向距离', '两步内路径', '实墙', '中间角色'):
            self.assertIn(condition, reach['condition'])
        self.assertIn('不会自动追击', rules['初始行为']['condition'])
        self.assertIn('不能断言本局', rules['初始行为']['condition'])
        self.assertIn('普通游荡', rules['负面状态解除被动']['value'])
        self.assertIn('目标可见且刚被警觉', rules['已警觉时发现敌人']['condition'])
        self.assertIn('单凭吸引不会解除被动', rules['被动时受到吸引']['condition'])

    def test_prize_counts_categories_and_quality_keep_variant_boundaries(self):
        for name, probability in (('goldenmimic', '50'), ('ebonymimic', '100')):
            rules = self.metrics(name, '生成奖励与质量')
            self.assertEqual(rules['生成时新增基础奖励']['value'], '1')
            for category in ('金币', '投掷武器', '护甲', '近战武器', '戒指'):
                self.assertIn(category, rules['生成时新增基础奖励']['condition'])
            self.assertIn('挑战禁物重抽', rules['生成时新增基础奖励']['condition'])
            self.assertIn('仅宝箱怪之牙', rules['宝箱怪之牙额外抽取']['condition'])
            upgrade = rules['生成奖励中 +0 非神器升级']
            self.assertEqual((upgrade['value'], upgrade['unit']), (probability, '%'))
            for condition in ('装备类物品与法杖', '恰为+0', '不是神器', '负等级', '已有正等级'):
                self.assertIn(condition, upgrade['condition'])
            for condition in ('当时已装入', '诅咒附魔', '诅咒刻印', '正常附魔'):
                self.assertIn(condition, rules['生成奖励质量']['condition'])
            self.assertIn('后来偷来的物品不套用', self.block(name, '生成奖励与质量')['note'])
        ebony = self.metrics('ebonymimic', '生成奖励与质量')
        self.assertEqual(ebony['黑檀独立额外抽取']['value'], '1')
        self.assertIn('共2条', ebony['黑檀独立额外抽取']['condition'])
        self.assertIn('共3条', ebony['黑檀独立额外抽取']['condition'])
        crystal = self.metrics('crystalmimic', '生成奖励与质量')
        self.assertEqual(len(crystal), 2)
        self.assertIn('不额外生成基类', crystal['生成奖励数量']['condition'])
        self.assertIn('不另抽宝箱怪之牙', crystal['生成奖励数量']['condition'])
        self.assertIn('预装1件法杖、戒指或神器', crystal['生成奖励数量']['condition'])
        self.assertIn('神器池耗尽时改为戒指', crystal['生成奖励数量']['condition'])
        self.assertIn('不额外升级', crystal['生成时奖励的诅咒标记']['condition'])
        self.assertNotIn('生成奖励与质量', [block['title'] for block in self.detail('mimic')['blocks']])

    def test_crystal_escape_theft_and_target_movement_are_separate_conditions(self):
        rules = self.metrics('crystalmimic')
        self.assertEqual(rules['停止伪装时极速基础持续']['value'], '2／1')
        self.assertIn('仍属中立为2，否则为1', rules['停止伪装时极速基础持续']['condition'])
        self.assertIn('仅尚属中立且命中玩家', rules['伪装首击额外伤害倍率']['condition'])
        self.assertEqual(rules['偷取对象']['value'], '未装备、非唯一、等级小于+1')
        self.assertIn('背包顶层', rules['偷取对象']['condition'])
        self.assertEqual(rules['每次偷取最多随机抽取']['value'], '11')
        self.assertIn('最多重抽10次', rules['每次偷取最多随机抽取']['condition'])
        self.assertIn('没有固定成功率', rules['每次偷取最多随机抽取']['condition'])
        for condition in ('周围8格', '可通行且无人', '移动的是受击目标', '无空位则不移动'):
            self.assertIn(condition, rules['其他命中后的目标移位']['condition'])
        escape = rules['成功逃脱的后果']
        self.assertEqual(escape['value'], '自身与携带物一同消失')
        for condition in ('触发逃脱判断后', '玩家视野外', '至少6格', '未满足则转为游荡', '不是每回合'):
            self.assertIn(condition, escape['condition'])
        loot = self.block('crystalmimic', '掉落物、数量与概率')['rows'][-1]
        self.assertIn('后来偷来的物品另计', loot[-1])
        self.assertIn('正常击杀', loot[-1])

    def test_shared_details_are_public_and_have_fixed_original_sources(self):
        for name, sources in (('gnollexile', ('GnollExile', 'Mob')),
                              ('goldenmimic', ('GoldenMimic', 'Mimic', 'MimicTooth')),
                              ('ebonymimic', ('EbonyMimic', 'Mimic', 'MimicTooth')),
                              ('crystalmimic', ('CrystalMimic', 'Mimic', 'Mob', 'Belongings', 'CrystalVaultRoom'))):
            detail = self.detail(name, depth=4, hero_level=5)
            self.assertEqual([block['title'] for block in detail['blocks'][:2]],
                             ['常规战斗数值', '掉落物、数量与概率'])
            self.assertFalse({'target_hp', 'target_max_hp', 'targets'} & {row['key'] for row in detail['inputs']})
            urls = [row['url'] for row in detail['provenance']['links']]
            for source in sources:
                self.assertTrue(any('/' + source + '.java' in url for url in urls), (name, source))
            self.assertTrue(all('57a4e06a4caf162446d1c28caa7983f0493fecf0' in url for url in urls))

    def test_native_floor_payload_reuses_new_blocks_without_hidden_target_reads(self):
        from companion.native_manager import NativeManager
        owner = NativeManager.__new__(NativeManager)
        owner.session = SimpleNamespace(catalog=self.values.catalog, values=self.values)
        snap = {'started':1, 'settings_revision':1, 'revision':1, 'active_slot':1,
                'run_id':'synthetic-public-only', 'error':None,
                'settings':{'save_root':'synthetic-not-opened', 'mode':'save'},
                'data':{'depth':4, 'branch':0, 'version':922, 'challenges_mask':0,
                        'challenges_known':True, 'hero':{'level':5, 'hp':20, 'ht':30}}}
        result = owner.floor_state(snap)
        def descendants(nodes):
            for node in nodes:
                yield node
                yield from descendants(node.get('children', []))
        nodes = list(descendants(result['nodes']))
        for name in ('gnollexile', 'goldenmimic', 'ebonymimic', 'crystalmimic'):
            node = next(node for node in nodes if node['id'] == 'actors.mobs.' + name)
            details = list(descendants(node['children']))
            self.assertTrue(any(row['text'] == '特殊攻击与机制' for row in details))
            if name != 'gnollexile':
                self.assertTrue(any(row['text'] == '生成奖励与质量' for row in details))
            self.assertFalse(node.get('expanded', False))
        self.assertNotIn('hidden-mobs', {node['id'] for node in nodes})
        self.assertEqual(owner._floor_item_references, {})


if __name__ == '__main__':
    unittest.main()
