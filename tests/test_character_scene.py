"""Shared public strength semantics, persistence and explicit manual reuse."""
import copy
from pathlib import Path
import tempfile
import unittest

from companion.character_scene import MIGHT, calculate_scene, empty_scene
from companion.decisions import public_context
from companion.engine import Catalog, PREFIX, analyze
from companion.public_talents import talent_points
from companion.service import Session, manual_game


def ring(level=2, cursed=False, **fields):
    return {'__className': PREFIX + 'items.rings.RingOfMight', 'level': level,
            'levelKnown': True, 'cursedKnown': True, 'cursed': cursed, **fields}


def game(**hero_fields):
    return {'version': 922, 'depth': 2, 'RingOfMight_known': True,
            'hero': {'class': 'WARRIOR', 'lvl': 20, 'STR': 11, 'HP': 20, 'HT': 40,
                     'inventory': [], 'buffs': [], **hero_fields}}


class CharacterSceneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def context(self, source):
        data = analyze(source, self.catalog)
        return data, public_context({'data': data})

    def test_known_equipped_ring_changes_context_total_without_changing_base(self):
        data, context = self.context(game(ring=ring()))
        self.assertEqual((data['hero']['strength'], context['strength']), (11, 14))
        self.assertEqual(data['character_scene']['strength']['components'],
                         {'base': 11, 'might_rings': 3, 'adrenaline': 0, 'strongman': 0})

    def test_strength_talent_uses_base_and_java_float_operations_before_ring_and_surge(self):
        for points, expected in ((1, 32), (2, 33), (3, 34)):
            source = game(STR=25, ring=ring(), talents_tier_3={'STRONGMAN': points},
                          buffs=[{'__className': PREFIX + 'actors.buffs.AdrenalineSurge', 'boost': 2}])
            self.assertEqual(self.context(source)[1]['strength'], expected)
        source['hero']['buffs'].append({'__className': PREFIX + 'actors.buffs.MagicImmune'})
        self.assertEqual(self.context(source)[1]['strength'], 31)

    def test_two_rings_use_solo_bonus_and_known_other_rings_need_no_grade(self):
        source = game(ring=ring(2), misc=ring(2, True))
        self.assertEqual(self.context(source)[1]['strength'], 14)
        source['hero']['misc'] = {'__className': PREFIX + 'items.rings.RingOfHaste'}
        source['RingOfHaste_known'] = True
        self.assertEqual(self.context(source)[1]['strength'], 14)

    def test_unknown_identity_grade_or_curse_is_not_guessed_and_immunity_suppresses_it(self):
        for fields in ({'levelKnown': False}, {'cursedKnown': False}):
            data, context = self.context(game(ring=ring(**fields)))
            self.assertEqual(data['character_scene']['strength']['state'], 'pending')
            self.assertEqual(context['strength'], 11)
        source = game(ring=ring())
        source['RingOfMight_known'] = False
        data, _ = self.context(source)
        self.assertIsNone(data['character_scene']['params']['rings'][0]['identity'])
        self.assertNotIn('ringofmight', str(data['character_scene']))
        source['hero']['buffs'] = [{'__className': PREFIX + 'actors.buffs.MagicImmune'}]
        data, context = self.context(source)
        self.assertEqual((data['character_scene']['strength']['state'], context['strength']), ('known', 11))

    def test_talent_eligibility_replacements_first_match_and_restore_clamp(self):
        hero = game()['hero']
        hero.update(talents_tier_3={'STRONGMAN': 99})
        self.assertEqual(talent_points(hero, 'STRONGMAN'), 3)
        hero['replacements'] = {'STRONGMAN': 'HOLD_FAST'}
        self.assertEqual(talent_points(hero, 'STRONGMAN'), 0)
        hero.update({'class': 'MAGE', 'replacements': {'ENERGIZING_MEAL': 'STRONGMAN', 'DESPERATE_POWER': 'STRONGMAN'},
                     'talents_tier_2': {'STRONGMAN': 2}, 'talents_tier_3': {'STRONGMAN': 3}})
        self.assertEqual(talent_points(hero, 'STRONGMAN'), 2)
        hero['talents_tier_2']['STRONGMAN'] = True
        self.assertIsNone(talent_points(hero, 'STRONGMAN'))
        self.assertEqual(talent_points(game()['hero'], 'WAND_PRESERVATION'), 0)

    def test_spirit_form_uses_talent_grade_only_as_zero_sum_fallback(self):
        form = {'__className': PREFIX + 'actors.hero.spells.SpiritForm$SpiritFormBuff', 'effect': ring(99)}
        source = game(STR=10, **{'class': 'CLERIC'}, armorAbility={
            '__className': PREFIX + 'actors.hero.abilities.cleric.Trinity'},
            talents_tier_4={'SPIRIT_FORM': 4}, buffs=[form])
        data, context = self.context(source)
        self.assertEqual((data['character_scene']['params']['spirit_level'], context['strength']), (4, 15))
        source['hero']['ring'] = ring(2)
        self.assertEqual(self.context(source)[1]['strength'], 13)
        source['hero']['misc'] = ring(-1, True)
        self.assertEqual(self.context(source)[1]['strength'], 15)
        source['hero']['buffs'].append({'__className': PREFIX + 'actors.buffs.MagicImmune'})
        self.assertEqual(self.context(source)[1]['strength'], 10)

    def test_artifact_spirit_effect_is_explicitly_no_virtual_ring(self):
        source = game(buffs=[{'__className': PREFIX + 'actors.hero.spells.SpiritForm$SpiritFormBuff',
                            'effect': {'__className': PREFIX + 'items.artifacts.HornOfPlenty'}}])
        data, context = self.context(source)
        self.assertEqual(data['character_scene']['params']['spirit_ring'], 'none')
        self.assertEqual(context['strength'], 11)

    def test_unavailable_ring_and_carried_ring_do_not_contribute(self):
        source = game(ring=ring(), inventory=[ring(9)],
                      buffs=[{'__className': PREFIX + 'actors.buffs.LostInventory'}])
        self.assertEqual(self.context(source)[1]['strength'], 11)

    def test_malformed_public_temporary_state_remains_pending(self):
        for boost in (None, True, -1, 2.5):
            source = game(buffs=[{'__className': PREFIX + 'actors.buffs.AdrenalineSurge', 'boost': boost}])
            self.assertIsNone(self.context(source)[0]['character_scene']['strength']['effective'])
        raw = empty_scene()
        raw['spirit_form'] = True
        self.assertEqual(calculate_scene(raw)['strength']['state'], 'pending')

    def test_character_plan_reopens_fixed_conditions_and_cas_rejects_stale_update(self):
        with tempfile.TemporaryDirectory(prefix='lamp-character-plan-') as directory:
            session = Session(Path(directory) / 'settings.json', self.catalog)
            raw = empty_scene(11)
            raw['rings'] = [{'identity': MIGHT, 'level': 2, 'cursed': False}]
            original = copy.deepcopy(raw)
            saved = session.knowledge.save('首领前的角色条件', 'character', None, raw,
                    {'mode': 'save', 'snapshot_at': 123, 'slot': 1,
                     'fields': {'base_strength': '快照基础力量', 'rings': '已知装备'}}, note='固定角色条件')
            self.assertEqual(raw, original)
            self.assertIsNone(session.data)
            session.data = analyze(game(STR=20), self.catalog)
            opened = session.knowledge.reopen(saved['id'])
            self.assertEqual(opened['result']['strength']['effective'], 14)
            raw['base_strength'] = 12
            updated = session.knowledge.save(saved['name'], 'character', None, raw, record_id=saved['id'],
                    expected_record_revision=saved['record_revision'])
            with self.assertRaisesRegex(ValueError, '另一窗口'):
                session.knowledge.save(saved['name'], 'character', None, original, record_id=saved['id'],
                    expected_record_revision=saved['record_revision'])
            other = Session(Path(directory) / 'import-profile' / 'settings.json', self.catalog)
            other.knowledge.import_records(session.knowledge.export())
            self.assertEqual(other.knowledge.reopen(updated['id'])['result']['strength']['effective'], 15)
            self.assertIsNone(other.data)

    def test_manual_reuse_carries_base_and_conditions_separately_without_double_counting(self):
        raw = empty_scene(11)
        raw['rings'] = [{'identity': MIGHT, 'level': 2, 'cursed': False}]
        payload = {'strength': 11, 'character_scene': raw}
        source = manual_game(payload)
        data, context = self.context(source)
        self.assertEqual((data['hero']['strength'], context['strength']), (11, 14))
        with self.assertRaisesRegex(ValueError, '不一致'):
            manual_game({**payload, 'strength': 12})


if __name__ == '__main__':
    unittest.main()
