"""Synthetic ordinary-combat references, never live game inputs."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from companion.character_scene import calculate_scene, empty_scene, validate_scene, scene_from_game, MIGHT, PREFIX
from companion.combat_context import hit_probability, ring_effect, validate_target
from companion.engine import Catalog
from companion.game_math import float32 as f
from companion.rules import NumericRules
from companion.service import Session
from companion.values import PlayerValues
from companion.values_decisions import compare_equipment

FORCE = 'items.rings.ringofforce'
FUROR = 'items.rings.ringoffuror'
ACCURACY = 'items.rings.ringofaccuracy'


class CombatContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()
        cls.values = PlayerValues(NumericRules(cls.catalog))

    def args(self, **overrides):
        return {'id_a': 'items.weapon.melee.shortsword', 'id_b': 'items.weapon.melee.dagger',
                'level_a': 0, 'level_b': 0, 'strength': 14, 'combat_model': 'ordinary-v1', **overrides}

    def scene(self, *rings, **overrides):
        return {**empty_scene(14), 'format': 2, 'enhanced_rings': False,
                'rings': [{'identity': identity, 'level': level, 'cursed': cursed} for identity, level, cursed in rings], **overrides}

    def target(self, **overrides):
        return {'format': 1, 'name': '首领前 · 手填参考', 'base_accuracy': 20,
                'evasion': 10, 'dr_min': 2, 'dr_max': 5, **overrides}

    def test_known_force_furor_change_combined_metrics_only(self):
        bare = compare_equipment(self.values, self.args())['choices'][0]['current']
        result = compare_equipment(self.values, self.args(character_scene=self.scene((FORCE, 3, False), (FUROR, 3, False))))
        current = result['choices'][0]['current']
        self.assertEqual((bare['普通近战命中前伤害范围'], current['普通近战命中前伤害范围']), ('2–17', '6–21'))
        self.assertLess(float(current['普通近战攻击耗时']), float(bare['普通近战攻击耗时']))
        for label in ('最低基础伤害', '最高基础伤害', '命中倍率', '攻击耗时'):
            self.assertEqual(current[label], bare[label])

    def test_ring_type_sums_curse_negative_unknown_and_immunity(self):
        self.assertEqual(ring_effect(self.scene(), FORCE)['value'], 0)
        self.assertEqual(ring_effect(self.scene((FORCE, 2, False), (FORCE, 1, False)), FORCE)['value'], 5)
        self.assertEqual(ring_effect(self.scene((FORCE, -2, True), (FORCE, 1, False)), FORCE)['value'], -2)
        unknown = self.scene((FORCE, None, False), (FUROR, 2, False))
        self.assertIsNone(ring_effect(unknown, FORCE)['value'])
        self.assertEqual(ring_effect(unknown, FUROR)['value'], 3)
        self.assertIsNone(ring_effect(self.scene((None, 0, False)), ACCURACY)['value'])
        unknown['magic_immune'] = True
        self.assertEqual(ring_effect(unknown, FORCE)['value'], 0)
        self.assertIsNone(ring_effect(self.scene((FORCE, 0, False), magic_immune=None), FORCE)['value'])

    def test_spirit_fallback_uses_buffed_sum_and_enhanced_never_adds_might_strength(self):
        scene = self.scene((FORCE, 2, False), (FORCE, -1, True), spirit_form=True,
                           spirit_ring=FORCE, spirit_level=4, spirit_cursed=False)
        self.assertEqual(ring_effect(scene, FORCE)['value'], 5)
        scene['enhanced_rings'] = True
        self.assertEqual(ring_effect(scene, FORCE)['value'], 2)  # Ordinary 4-2 is nonzero, so no fallback.
        scene = self.scene((MIGHT, 2, False), enhanced_rings=True)
        self.assertEqual(calculate_scene(scene)['strength']['effective'], 17)
        scene['rings'] = [{'identity': FORCE, 'level': 2, 'cursed': False}]
        self.assertEqual(ring_effect(scene, FORCE)['value'], 4)
        scene['enhanced_rings'] = None
        self.assertIsNone(ring_effect(scene, FORCE)['value'])
        scene['rings'] = []
        self.assertEqual(ring_effect(scene, FORCE)['value'], 0)

    def test_float_boundaries_and_accuracy_rounding(self):
        # Weapon.baseDelay uses float augment first, then compound double pow;
        # delayFactor uses float reciprocal and multiplication. Hero uses float Math.round.
        scene = self.scene((FUROR, 3, False), (ACCURACY, 2, False))
        result = compare_equipment(self.values, self.args(strength=10, character_scene={**scene, 'base_strength': 10},
                    augment_a='SPEED', target_context=self.target(base_accuracy=17)))
        rows = {row['label']: row for row in result['choices'][0]['current_metrics']}
        expected_delay = f(f(f(f(2) / 3) * 1.2 ** 2) * f(f(1) / f(1.09051 ** 4)))
        # Presentation may round; the calculation does not re-read the rounded base row.
        self.assertEqual(float(rows['普通近战攻击耗时']['value']), round(expected_delay, 6))
        self.assertEqual(rows['目标模型有效命中']['value'], '17')
        self.assertEqual(rows['目标模型命中后扣血范围']['value'], '0–9')

    def test_target_pending_and_infinite_precedence(self):
        self.assertEqual(hit_probability(1000000, 1000000), 0)
        self.assertEqual(hit_probability(1000000, 9), 1)
        self.assertEqual(hit_probability(20, 10), .75)
        self.assertEqual(hit_probability(10, 20), .25)
        result = compare_equipment(self.values, self.args(target_context=self.target(base_accuracy=None, dr_max=None)))
        current = result['choices'][0]['current']
        self.assertEqual(current['目标模型有效命中'], '待确认')
        self.assertEqual(current['目标模型命中率参考'], '待确认')
        self.assertEqual(current['目标模型命中后扣血范围'], '待确认')
        self.assertIsNone(result['params']['target_context']['dr_max'])

    def test_public_enhanced_state_and_unknown_ring_grade_are_effect_specific(self):
        game = {'hero': {'class': 'WARRIOR', 'lvl': 20, 'STR': 14,
                         'buffs': [{'__className': PREFIX + 'actors.buffs.EnhancedRings'}]}}
        scene = scene_from_game(game, self.catalog, [])['params']
        self.assertEqual(scene['format'], 2)
        self.assertIs(scene['enhanced_rings'], True)
        scene['rings'] = [{'identity': FORCE, 'level': None, 'cursed': False},
                          {'identity': FUROR, 'level': 3, 'cursed': False}]
        result = compare_equipment(self.values, self.args(character_scene=scene))
        current = result['choices'][0]['current']
        self.assertEqual(current['普通近战武力加值'], '待确认')
        self.assertEqual(current['普通近战命中前伤害范围'], '待确认')
        self.assertNotEqual(current['普通近战攻击耗时'], '待确认')
        self.assertNotEqual(current['普通近战精准戒指倍率'], '待确认')

    def test_upgrade_and_budget_use_same_scene_and_target(self):
        result = compare_equipment(self.values, self.args(character_scene=self.scene((FORCE, 3, False), (FUROR, 3, False)),
            target_context=self.target(), planning='1', upgrade_budget=2, strength_budget=1, investment_mode='all'))
        a = result['choices'][0]
        self.assertEqual(a['upgraded']['普通近战武力加值'], '4')
        for option in result['planning']['choices'][0]['alternatives']:
            self.assertEqual(option['metrics']['普通近战武力加值'], '4')
            self.assertIn('首领前 · 手填参考', str(option['metric_rows']))
        self.assertNotEqual(a['current']['普通近战命中前伤害范围'], a['upgraded']['普通近战命中前伤害范围'])

    def test_legacy_scene_and_params_keep_exact_meaning_and_missiles_exclude_force(self):
        old = empty_scene(14)
        self.assertEqual(validate_scene(old), old)
        with self.assertRaises(ValueError):
            validate_scene({**old, 'enhanced_rings': False})
        args = self.args(character_scene=self.scene((FORCE, 3, False)))
        args.pop('combat_model')
        result = compare_equipment(self.values, args)
        self.assertNotIn('combat_model', result['params'])
        self.assertFalse(any('普通近战' in key for key in result['choices'][0]['current']))
        missile = {**args, 'id_a': 'items.weapon.missiles.kunai', 'id_b': 'items.weapon.missiles.kunai'}
        current = compare_equipment(self.values, missile)['choices'][0]['current']
        plain = compare_equipment(self.values, {k: v for k, v in missile.items() if k != 'character_scene'})['choices'][0]['current']
        self.assertEqual(current, plain)
        with self.assertRaises(ValueError):
            compare_equipment(self.values, {**missile, 'combat_model': 'ordinary-v1'})

    def test_two_named_targets_save_reopen_export_with_unknowns_and_no_input_mutation(self):
        with tempfile.TemporaryDirectory(prefix='lamp-combat-') as directory:
            def session(name):
                path = Path(directory) / name / 'settings.json'
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps({'save_root': str(Path(directory) / 'synthetic-save-root')}), encoding='utf-8')
                return Session(path, self.catalog)
            source, other = session('source'), session('other')
            expected = {}
            for name, dr_max in (('第一目标', 5), ('第二目标', None)):
                args = self.args(character_scene=self.scene((FORCE, 2, False)), target_context=self.target(name=name, dr_max=dr_max))
                original = copy.deepcopy(args)
                result = compare_equipment(self.values, args)
                self.assertEqual(args, original)
                saved = source.knowledge.save(name, 'equipment', None, result['params'], note='独立目标假设')
                expected[saved['id']] = result
                self.assertEqual(source.knowledge.reopen(saved['id'])['result'], result)
            other.knowledge.import_records(source.knowledge.export())
            for identity, result in expected.items():
                self.assertEqual(other.knowledge.reopen(identity)['result'], result)
            self.assertIsNone(other.data)

    def test_invalid_model_and_target_are_rejected_without_defaulting(self):
        for target in (self.target(dr_min=6), self.target(name=' '), self.target(evasion=True), self.target(dr_min=-1)):
            with self.assertRaises(ValueError):
                validate_target(target)
        with self.assertRaises(ValueError):
            compare_equipment(self.values, {**self.args(), 'combat_model': 'all-effects'})
        args = self.args(target_context=self.target())
        args.pop('combat_model')
        with self.assertRaises(ValueError):
            compare_equipment(self.values, args)


if __name__ == '__main__':
    unittest.main()
