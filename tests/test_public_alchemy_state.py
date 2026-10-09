"""Snapshot resources preserve public instance state and hide save-only secrets."""
import json
from pathlib import Path
import tempfile
import unittest

from companion.alchemy import resources_from_snapshot
from companion.engine import Catalog, PREFIX, analyze
from companion.service import Session


def item(relative, **fields):
    return {'__className': PREFIX + relative, 'quantity': 1, **fields}


class PublicAlchemyStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def snapshot(self, items, **hero):
        return analyze({'version': 922, 'depth': 2, 'energy': 30,
                        'hero': {'class': 'WARRIOR', 'STR': 11, 'lvl': 10, 'HP': 20, 'HT': 40,
                                 'buffs': [], 'inventory': items, **hero}}, self.catalog)

    def test_raw_and_cooked_fruit_are_different_public_resources(self):
        rows = self.snapshot([item('items.food.Blandfruit'), item('items.food.Blandfruit',
            potionattrib=item('items.potions.PotionOfInvisibility'))])['items']
        self.assertEqual(rows[0]['alchemy_state'], {'cooked': 'raw', 'potion_id': None})
        self.assertEqual(rows[1]['alchemy_state'], {'cooked': 'cooked', 'potion_id': 'items.potions.potionofinvisibility'})
        self.assertNotEqual(rows[0]['name'], rows[1]['name'])
        self.assertNotEqual(rows[0]['instance_key'], rows[1]['instance_key'])
        bad = self.snapshot([item('items.food.Blandfruit', potionattrib={'unknown': 'secret'})])['items'][0]
        self.assertEqual(bad['alchemy_state']['cooked'], 'unknown')

    def test_wand_base_is_derived_only_from_public_known_grade_and_uncursed_state(self):
        rows = self.snapshot([item('items.wands.WandOfMagicMissile', level=2, resin_bonus=1,
            levelKnown=True, cursedKnown=True, cursed=False), item('items.wands.WandOfMagicMissile',
            level=7, resin_bonus=1, levelKnown=False, cursedKnown=True, cursed=False)])['items']
        self.assertEqual((rows[0]['alchemy_state']['public_level'], rows[0]['alchemy_state']['base_level']), (3, 2))
        self.assertEqual(rows[1]['alchemy_state']['resin_bonus'], 1)  # Wand.info publicly reports resin.
        self.assertIsNone(rows[1]['alchemy_state']['public_level'])
        self.assertIsNone(rows[1]['alchemy_state']['base_level'])
        unknown = self.snapshot([item('items.wands.WandOfMagicMissile', level=2, resin_bonus=1,
            levelKnown=True, cursedKnown=False, cursed=False)])['items'][0]['alchemy_state']
        self.assertIsNone(unknown['base_level'])

    def test_wand_preservation_uses_public_metamorphed_talent_and_valid_class(self):
        row = self.snapshot([item('items.wands.WandOfMagicMissile')],
            replacements={'IRON_STOMACH': 'WAND_PRESERVATION'}, talents_tier_2={'WAND_PRESERVATION': 2})['items'][0]
        self.assertEqual((row['alchemy_state']['hero_class'], row['alchemy_state']['wand_preservation']), ('WARRIOR', 2))

    def test_missile_stacks_keep_grades_and_quantities_but_not_precise_durability(self):
        rows = self.snapshot([item('items.weapon.missiles.ThrowingKnife', quantity=2,
            level=1, levelKnown=True, durability=48.125), item('items.weapon.missiles.ThrowingKnife',
            quantity=3, level=2, levelKnown=True, durability=99.5)])['items']
        self.assertEqual([row['alchemy_state']['level'] for row in rows], [1, 2])
        self.assertEqual([row['quantity'] for row in rows], [2, 3])
        self.assertTrue(all(row['alchemy_state']['tier'] == 1 and row['alchemy_state']['default_quantity'] == 3 for row in rows))
        self.assertTrue(all(row['alchemy_state']['durability'] is None for row in rows))
        self.assertNotIn('48.125', json.dumps(rows))
        with tempfile.TemporaryDirectory(prefix='lamp-public-alchemy-') as directory:
            session = Session(Path(directory) / 'settings.json', self.catalog)
            session.data = self.snapshot([item('items.weapon.missiles.ThrowingKnife', quantity=2,
                level=1, levelKnown=True, cursedKnown=True)])
            result = resources_from_snapshot(session)
        self.assertEqual(result['instances'][0]['state']['durability'], None)
        self.assertEqual(result['instances'][0]['origin'], 'known')

    def test_catalyst_exposes_only_existing_four_choices_and_no_false_equipment_grade(self):
        choices = [item('items.trinkets.' + name) for name in ('MossyClump', 'ParchmentScrap', 'RatSkull', 'WondrousResin')]
        rows = self.snapshot([item('items.trinkets.TrinketCatalyst'),
                              item('items.trinkets.TrinketCatalyst', rolled_trinkets=choices)])['items']
        self.assertEqual(rows[0]['alchemy_state']['catalyst_stage'], 'unrolled')
        self.assertIsNone(rows[0]['alchemy_state']['rolled_choices'])
        self.assertEqual(rows[1]['alchemy_state']['catalyst_stage'], 'awaiting_choice')
        self.assertEqual(len(rows[1]['alchemy_state']['rolled_choices']), 4)
        self.assertFalse(rows[1]['level_applicable'])
        self.assertNotIn('等级未知', rows[1]['details'])

    def test_seed_identity_is_public_and_has_a_real_catalog_entry(self):
        row = self.snapshot([item('plants.Blindweed$Seed', quantity=3)])['items'][0]
        self.assertTrue(row['known'])
        self.assertEqual(row['key'], 'plants.blindweed$seed')
        self.assertIn(row['key'], {entry['id'] for entry in self.catalog.entries})


if __name__ == '__main__':
    unittest.main()
