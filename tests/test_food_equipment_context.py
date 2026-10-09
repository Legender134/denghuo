"""Food decisions depend on available equipped horn state, not its slot label."""
from pathlib import Path
import tempfile
import unittest

from companion.decisions import context_actions
from companion.engine import Catalog, PREFIX, analyze
from companion.service import Session


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


if __name__ == '__main__':
    unittest.main()
