"""Visible grades and lookup provenance from the pinned 4.0.2 item contracts."""
from pathlib import Path
import tempfile
import unittest

from companion.engine import Catalog, PREFIX, analyze
from companion.service import Session


def item(relative, **fields):
    return {'__className': PREFIX + 'items.' + relative, 'quantity': 1,
            'level': 0, 'levelKnown': True, 'cursedKnown': True, 'cursed': False, **fields}


def game(items=(), hero_level=10):
    return {'depth': 2, 'version': 922, 'hero': {'class': 'MAGE', 'lvl': hero_level,
            'HP': 20, 'HT': 40, 'STR': 12, 'inventory': list(items), 'buffs': []}}


class PublicItemLevelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def workspace_rows(self, source):
        with tempfile.TemporaryDirectory(prefix='lamp-public-grade-') as directory:
            session = Session(Path(directory) / 'settings.json', self.catalog)
            session.data = analyze(source, self.catalog)
            session.modified = 123
            return session.workspace_status()['current']

    def test_resin_is_in_the_known_title_and_the_same_lookup_parameter(self):
        source = game([item('wands.WandOfMagicMissile', level=2, resin_bonus=1)])
        row = analyze(source, self.catalog)['items'][0]
        self.assertEqual(row['level'], 3)
        self.assertTrue(row['name'].endswith(' +3'))
        lookup = self.workspace_rows(source)[0]['lookup_context']
        self.assertEqual((lookup['params']['level'], lookup['level_origin']), (3, 'known'))

    def test_wand_infusion_only_remains_on_the_cursed_branch(self):
        # Wand.level removes infusion after uncursing; resin stays. Weapon division
        # uses Java's truncation toward zero for a negative stored base grade.
        cases = [(-1, 3, True, 3), (6, 2, False, 8), (6, 2, True, 10)]
        for base, resin, cursed, expected in cases:
            with self.subTest(base=base, resin=resin, cursed=cursed):
                source = item('wands.WandOfMagicMissile', level=base, resin_bonus=resin,
                              curse_infusion_bonus=True, cursed=cursed)
                self.assertEqual(self.catalog.item(source, game())['level'], expected)

    def test_hidden_or_invalid_grade_is_not_replaced_by_a_derived_guess(self):
        for fields in ({'levelKnown': False, 'level': 7, 'resin_bonus': 3},
                       {'resin_bonus': -1}, {'resin_bonus': True}, {'level': 2.5}):
            with self.subTest(fields=fields):
                row = self.catalog.item(item('wands.WandOfMagicMissile', **fields), game())
                self.assertIsNone(row['level'])
                self.assertNotIn('+', row['name'])
        revealed = self.catalog.item(item('wands.WandOfMagicMissile', levelKnown=False,
                                         level=2, resin_bonus=1), game(), reveal=True)
        self.assertEqual(revealed['level'], 3)

    def test_spirit_bow_title_requirement_and_lookup_share_hero_derived_grade(self):
        for hero_level, grade, requirement in ((1, 0, 10), (5, 1, 9), (10, 2, 9),
                                               (15, 3, 8), (30, 6, 7)):
            with self.subTest(hero_level=hero_level):
                source = game([item('weapon.SpiritBow', level=77, mastery_potion_bonus=True)], hero_level)
                row = analyze(source, self.catalog)['items'][0]
                self.assertEqual((row['level'], row['strength_requirement']), (grade, requirement))
                self.assertTrue(row['name'].endswith(f' +{grade}'))
                lookup = self.workspace_rows(source)[0]['lookup_context']
                self.assertEqual(lookup['params']['level'], grade)
                self.assertFalse(row['is_upgradable'])
        infused = self.catalog.item(item('weapon.SpiritBow', curse_infusion_bonus=True), game(hero_level=30))
        self.assertEqual((infused['level'], infused['strength_requirement']), (8, 7))
        sword = self.catalog.item(item('weapon.melee.Sword', level=2, mastery_potion_bonus=True), game())
        self.assertEqual(sword['strength_requirement'], 11)

    def test_spirit_bow_missing_hero_context_is_unknown_and_not_zero(self):
        for source in ({}, {'hero': {}}, {'hero': {'lvl': True}}, {'hero': {'lvl': 0}}):
            with self.subTest(source=source):
                row = self.catalog.item(item('weapon.SpiritBow'), source)
                self.assertIsNone(row['level'])
                self.assertIsNone(row['strength_requirement'])
                self.assertIn('等级暂缺上下文', row['details'])
        hidden = self.catalog.item(item('weapon.SpiritBow', levelKnown=False), game(hero_level=30))
        self.assertIsNone(hidden['level'])

    def test_consumables_have_no_equipment_grade_while_unknown_equipment_stays_unknown(self):
        source = game([item('food.Food', levelKnown=False), item('Waterskin', levelKnown=False),
                       item('potions.PotionOfHealing', levelKnown=False),
                       item('scrolls.ScrollOfIdentify', levelKnown=False),
                       item('weapon.melee.Sword', levelKnown=False),
                       item('armor.LeatherArmor', levelKnown=False),
                       item('rings.RingOfMight', levelKnown=False)])
        source.update(PotionOfHealing_known=True, ScrollOfIdentify_known=True, RingOfMight_known=True)
        rows = analyze(source, self.catalog)['items']
        for row in rows[:4]:
            self.assertFalse(row['level_applicable'])
            self.assertFalse(row['is_upgradable'])
            self.assertNotIn('等级未知', row['details'])
        for row in rows[4:]:
            self.assertTrue(row['level_applicable'])
            self.assertIsNone(row['level'])
            self.assertIn('等级未知', row['details'])
        lookup = {row['id']: row['lookup_context'] for row in self.workspace_rows(source)}
        self.assertTrue(all(lookup[row['key']]['level_origin'] == 'not_applicable' for row in rows[:4]))
        self.assertTrue(all(lookup[row['key']]['level_unknown'] for row in rows[4:]))

    def test_artifact_scaled_display_and_dart_scroll_eligibility_are_preserved(self):
        chains = self.catalog.item(item('artifacts.EtherealChains', level=2), game())
        beacon = self.catalog.item(item('artifacts.LloydsBeacon', level=2), game())
        self.assertEqual((chains['level'], beacon['level']), (4, 7))
        self.assertFalse(chains['is_upgradable'])
        self.assertTrue(chains['level_applicable'])
        dart = self.catalog.item(item('weapon.missiles.darts.Dart'), game())
        self.assertFalse(dart['is_upgradable'])
        self.assertTrue(dart['level_applicable'])


if __name__ == '__main__':
    unittest.main()
