"""Known food/equipment context preserves public identity and applicable conditions."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from companion.decisions import context_actions
from companion.engine import Catalog, PREFIX, analyze
from companion.service import Session
from companion.rules import NumericRules
from companion.values import PlayerValues


class EquippedHornContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def food_option(self, *, slot='artifact', cursed=True, known=True, lost=False, kept=True):
        horn = {'__className': PREFIX + 'items.artifacts.HornOfPlenty', 'quantity': 1,
                'level': 0, 'levelKnown': True, 'cursedKnown': known, 'cursed': cursed,
                'kept_lost': kept}
        hero = {'class': 'WARRIOR', 'HP': 20, 'HT': 40, 'STR': 12, 'lvl': 3,
                'inventory': [{'__className': PREFIX + 'items.food.Food', 'kept_lost': True}],
                'buffs': [{'__className': PREFIX + 'actors.buffs.Hunger', 'level': 350}]}
        if slot == 'backpack':
            hero['inventory'].append(horn)
        else:
            hero[slot] = horn
        if lost:
            hero['buffs'].append({'__className': PREFIX + 'actors.buffs.LostInventory'})
        source = {'hero': hero, 'depth': 2, 'version': 922}
        snapshot = {'settings': {'mode': 'save'}, 'data': analyze(source, self.catalog),
                    'modified': 123, 'stale': False, 'active_slot': 1, 'error': ''}
        with tempfile.TemporaryDirectory(prefix='lamp-horn-context-') as directory:
            session = Session(Path(directory) / 'settings.json', self.catalog)
            result = context_actions(session, snapshot)
        return next(row for row in result['options'] if row['entry'] == 'items.food.food')

    def test_known_cursed_horn_applies_in_either_legal_equipment_slot(self):
        for slot in ('artifact', 'misc'):
            with self.subTest(slot=slot):
                option = self.food_option(slot=slot)
                values = {row['label']: row['value'] for row in option['values']}
                self.assertEqual(values['已知诅咒丰饶之角下的参考恢复'], '201')
                self.assertEqual(values['进食后饥饿值参考'], '149')

    def test_uncursed_or_carried_or_unavailable_horn_does_not_reduce_food(self):
        for args in ({'slot': 'misc', 'cursed': False}, {'slot': 'backpack'},
                     {'slot': 'misc', 'lost': True, 'kept': False}):
            with self.subTest(args=args):
                option = self.food_option(**args)
                values = {row['label']: row['value'] for row in option['values']}
                self.assertEqual(values['进食后饥饿值参考'], '50')
                self.assertNotIn('已知诅咒丰饶之角下的参考恢复', values)

    def test_unknown_horn_curse_remains_an_explicit_uncertainty_in_both_slots(self):
        for slot in ('artifact', 'misc'):
            option = self.food_option(slot=slot, known=False)
            self.assertIn('诅咒状态未确认', option['calculation_missing'])
            self.assertFalse(any(row['label'] == '已知诅咒丰饶之角下的参考恢复' for row in option['values']))


class PublicEquipmentEffectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()
        cls.values = PlayerValues(NumericRules(cls.catalog))

    def equipment(self, *, armor=False, effect=None, known=False, hardened=False, level_known=True):
        item = {'__className': PREFIX + ('items.armor.MailArmor' if armor else 'items.weapon.melee.Sword'),
                'level': 4, 'levelKnown': level_known, 'cursedKnown': known, 'cursed': False,
                'glyph_hardened' if armor else 'enchant_hardened': hardened}
        if effect:
            item['glyph' if armor else 'enchantment'] = {'__className': PREFIX + effect}
        return item

    def test_normal_effects_and_hardening_are_visible_without_revealing_grade_or_curse(self):
        for armor, effect, label in ((False, 'items.weapon.enchantments.Blazing', '烈焰'),
                                     (True, 'items.armor.glyphs.Brimstone', '狱火')):
            with self.subTest(armor=armor):
                raw = self.equipment(armor=armor, effect=effect, hardened=True, level_known=False)
                item = self.catalog.item(raw, {})
                self.assertIn(label, item['name'])
                self.assertIn(label, item['description'])
                self.assertTrue(any('已硬化' in detail for detail in item['details']))
                self.assertIsNone(item['level'])
                self.assertIsNone(item['cursed'])
                self.assertEqual(item['related'][0]['id'], effect.lower())
                self.assertIn('已硬化', item['related'][1]['conditions'])

    def test_hidden_curse_is_indistinguishable_from_no_visible_effect(self):
        raw = self.equipment(effect='items.weapon.curses.Wayward', hardened=True)
        empty = self.equipment(hardened=True)
        self.assertEqual(self.catalog.item(raw, {}), self.catalog.item(empty, {}))
        raw['cursedKnown'] = True
        known = self.catalog.item(raw, {})
        self.assertEqual(known['equipment_state']['effect_id'], 'items.weapon.curses.wayward')
        self.assertIn('items.weapon.curses.wayward', [row['id'] for row in known['related']])
        raw['cursedKnown'] = False
        self.assertEqual(self.catalog.item(raw, {}, reveal=True)['equipment_state']['effect_id'], 'items.weapon.curses.wayward')

    def test_missing_or_unsupported_effect_does_not_invent_identity(self):
        raw = self.equipment(effect='items.weapon.enchantments.UnknownPrivateEffect', hardened=True)
        item = self.catalog.item(raw, {})
        self.assertIsNone(item['equipment_state']['effect_id'])
        self.assertEqual([row['id'] for row in item['related']], ['items.scrolls.scrollofupgrade'])
        self.assertNotIn('UnknownPrivateEffect', str(item))
        self.assertTrue(item['equipment_state']['hardened'])

    def test_shared_current_lookup_preserves_effect_level_snapshot_and_risk_branch(self):
        game = {'hero': {'class': 'WARRIOR', 'HP': 20, 'HT': 40, 'STR': 12, 'lvl': 3,
                        'weapon': self.equipment(effect='items.weapon.enchantments.Blazing', hardened=True),
                        'inventory': [], 'buffs': []}, 'depth': 2, 'version': 922}
        with tempfile.TemporaryDirectory(prefix='lamp-equipment-effects-') as directory:
            session = Session(Path(directory) / 'settings.json', self.catalog)
            snapshot = {'settings': session.settings, 'data': analyze(game, self.catalog),
                'started': 10, 'revision': 1, 'modified': 123, 'stale': False, 'active_slot': 1, 'error': ''}
            with patch.object(session, 'snapshot', return_value=snapshot):
                current = session.workspace_status()['current']
        effect = next(row for row in current if row['id'] == 'items.weapon.enchantments.blazing')
        risk = next(row for row in current if row['id'] == 'items.scrolls.scrollofupgrade')
        self.assertIn('烈焰', effect['lookup_label'])
        self.assertEqual(effect['lookup_context']['params']['level'], 4)
        self.assertEqual(effect['lookup_context']['stamp'][-1], 123)
        self.assertEqual(effect['lookup_context']['level_origin'], 'known')
        self.assertIn('已硬化', risk['lookup_context']['conditions'])

    def test_negative_known_effect_levels_keep_game_specific_clamping_and_risk(self):
        def values(identity, level):
            return self.values.detail(identity, {'level': level})
        blazing = values('items.weapon.enchantments.blazing', -1)
        table = next(block for block in blazing['blocks'] if block['title'] == '触发概率')
        self.assertEqual(next(row[1] for row in table['rows'] if row[0] == '-1'), next(row[1] for row in table['rows'] if row[0] == '+0'))
        for identity, label, expected in (('items.weapon.enchantments.blocking', '触发时获得护盾', '1'),
                ('items.weapon.enchantments.blooming', '触发后平均高草数量', '1.5'),
                ('items.weapon.enchantments.venomous', '增加毒强度', '3'),
                ('items.armor.glyphs.flow', '水中移动速度倍率', '1'),
                ('items.armor.glyphs.swiftness', '无近敌时移动速度倍率', '1'),
                ('items.armor.glyphs.antimagic', '额外魔法减伤', '0–0')):
            with self.subTest(identity=identity):
                rows = {row['label']: row['value'] for block in values(identity, -1)['blocks'] for row in block.get('values', [])}
                self.assertEqual(rows[label], expected)
        viscosity = values('items.armor.glyphs.viscosity', -6)
        rows = {row['label']: row['value'] for block in viscosity['blocks'] for row in block.get('values', [])}
        self.assertEqual(rows['转为延缓伤害'], '4')
        risk = values('items.scrolls.scrollofupgrade', -1)
        self.assertTrue(any(block['title'] == '从 -1 升到 +0 的风险' for block in risk['blocks']))


class KnownFruitDecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def fruit(self, potion=None, quantity=1):
        row = {'__className': PREFIX + 'items.food.Blandfruit', 'quantity': quantity}
        if potion is not None:
            row['potionattrib'] = {'__className': PREFIX + 'items.potions.' + potion}
        return row

    def options(self, inventory, *, challenges=0, hp=20, buffs=None, horn=None):
        hero = {'class': 'WARRIOR', 'HP': hp, 'HT': 40, 'STR': 12, 'lvl': 3,
                'inventory': inventory, 'buffs': buffs or []}
        if horn:
            hero['artifact'] = horn
        game = {'hero': hero, 'depth': 2, 'version': 922, 'challenges': challenges}
        snapshot = {'settings': {'mode': 'save'}, 'data': analyze(game, self.catalog),
                    'modified': 123, 'stale': False, 'active_slot': 1, 'error': ''}
        with tempfile.TemporaryDirectory(prefix='lamp-fruit-context-') as directory:
            session = Session(Path(directory) / 'settings.json', self.catalog)
            return context_actions(session, snapshot)['options']

    def test_resource_groups_preserve_raw_cooked_and_unknown_identity_independent_of_order(self):
        inventory = [self.fruit(quantity=1), self.fruit('PotionOfHealing', 2), self.fruit('PotionOfToxicGas', 3),
                     self.fruit('PotionOfHealing', 4), self.fruit('UnknownPotion', 5)]
        options = self.options(inventory)
        self.assertEqual(options, self.options(list(reversed(copy.deepcopy(inventory)))))
        self.assertEqual(len(options), 4)
        quantities = {(row['fruit_state']['cooked'], row['fruit_state'].get('potion_id')): row['quantity'] for row in options}
        self.assertEqual(quantities, {('raw', None): 1, ('cooked', 'items.potions.potionofhealing'): 6,
                                     ('cooked', 'items.potions.potionoftoxicgas'): 3, ('unknown', None): 5})
        for row in options:
            if row['fruit_state']['cooked'] != 'cooked':
                self.assertEqual(row['values'], [])
                self.assertIn('烹煮', row['calculation_missing'])

    def test_cooked_fruit_actions_and_healing_challenge_remain_explicit(self):
        inventory = [self.fruit('PotionOfHealing'), self.fruit('PotionOfToxicGas'), self.fruit('PotionOfPurity')]
        options = self.options(inventory, challenges=4, hp=0)
        healing = next(row for row in options if row['fruit_state']['potion_id'].endswith('potionofhealing'))
        toxic = next(row for row in options if row['fruit_state']['potion_id'].endswith('potionoftoxicgas'))
        purity = next(row for row in options if row['fruit_state']['potion_id'].endswith('potionofpurity'))
        self.assertIn('生命值为0', healing['restriction'])
        self.assertIn('改为中毒', healing['restriction'])
        self.assertIn('默认投掷', toxic['restriction'])
        self.assertIn('主动进食仍会', toxic['restriction'])
        self.assertIn('仅适用于主动进食', toxic['note'])
        self.assertIn('选择使用方式', purity['note'])
        self.assertEqual(healing['related'][0]['id'], 'items.potions.potionofhealing')

    def test_cooked_nutrition_keeps_hunger_horn_and_action_lock_conditions(self):
        horn = {'__className': PREFIX + 'items.artifacts.HornOfPlenty', 'level': 0,
                'levelKnown': True, 'cursedKnown': True, 'cursed': True}
        options = self.options([self.fruit('PotionOfHealing')], challenges=1, horn=horn,
            buffs=[{'__className': PREFIX + 'actors.buffs.Paralysis'}])
        row = options[0]
        self.assertIn('限制主动行动', row['restriction'])
        values = {value['label']: value['value'] for value in row['values']}
        self.assertEqual(values['饥饿游戏基础饱食恢复'], '150')
        self.assertEqual(values['已知诅咒丰饶之角下的参考恢复'], '100.5')


if __name__ == '__main__':
    unittest.main()
