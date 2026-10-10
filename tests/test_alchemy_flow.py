"""Focused synthetic acceptance of the pinned 39 alchemy workflows."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from companion.alchemy import COMMIT, MAX_INT, calculate, recipe_list, validate_plan
from companion.alchemy_flow import BOMBS, SEED_POTIONS, TRINKETS, Ledger, discover, family_list, metal_quantity, resource_catalog
from companion.engine import Catalog
from companion.service import Session


def stock(identity, quantity=1, reserve=0, key='s1', state=None, origin='manual'):
    return {'key': key, 'id': identity, 'quantity': quantity, 'reserve': reserve,
            'origin': origin, 'state': state or {}}


def goal(recipe, quantity=1, choices=None, key='g1'):
    return {'key': key, 'recipe': recipe, 'quantity': quantity, 'choices': choices or {}}


def params(targets, resources=(), energy=100, reserve=0, chains=None):
    return {'format': 2, 'recipe_version': '4.0.2', 'targets': targets,
            'resources': list(resources), 'energy': energy, 'energy_reserve': reserve,
            'energy_origin': 'manual', 'reference_version': None, 'chains': chains or {}}


class TargetAlchemyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def run_plan(self, targets, resources=(), energy=100, reserve=0, chains=None):
        return calculate(self.catalog, params(targets, resources, energy, reserve, chains))[1]

    def test_every_registered_fixed_family_uses_exact_arrays_cost_and_yield(self):
        families = self.catalog.data['alchemy_families']
        self.assertEqual(len({row['family'] for row in families}), 39)
        self.assertTrue(all(row['source']['commit'] == COMMIT for row in families))
        for recipe in recipe_list(self.catalog):
            with self.subTest(recipe=recipe['id']):
                rows = [stock(i['id'], i['quantity'], key='s' + str(index)) for index, i in enumerate(recipe['inputs'])]
                result = self.run_plan([goal(recipe['id'], recipe['quantity'])], rows, recipe['cost'])
                self.assertTrue(result['complete'])
                self.assertEqual(result['outputs'][0]['id'], recipe['output'])
                self.assertEqual(result['outputs'][0]['quantity'], recipe['quantity'])
                self.assertEqual(result['energy']['remaining'], 0)
                self.assertTrue(all(row['remaining'] == 0 for row in result['materials']))
        self.assertEqual(sum(row['mode'] == 'fixed' for row in families), 28)  # 25 declarations, three conversion families.

    def test_inventory_picker_uses_concrete_items_and_calculation_rejects_translated_subentries(self):
        resources = resource_catalog(self.catalog)
        self.assertEqual(tuple(len(resources[name]) for name in ('wands', 'missiles', 'darts', 'stones')), (13, 15, 13, 12))
        offered = {row['id'] for row in resources['items']}
        self.assertIn('items.weapon.missiles.darts.adrenalinedart', offered)
        self.assertIn('items.weapon.missiles.darts.dart', offered)
        self.assertIn('items.honeypot$shatteredpot', offered)
        self.assertIn('plants.blindweed$seed', offered)
        excluded = ('items.wands.wandoflightning$lightningcharge', 'items.wands.wandoflivingearth$earthguardian',
                    'items.wands.wandoflivingearth$rockarmor', 'items.wands.wandofmagicmissile$magiccharge',
                    'items.wands.wandofregrowth$dewcatcher', 'items.wands.wandofregrowth$lotus',
                    'items.wands.wandofregrowth$seedpod', 'items.weapon.missiles.shuriken$shurikeninstanttracker',
                    'items.weapon.missiles.boomerang')
        for identity in excluded:
            with self.subTest(identity=identity):
                self.assertNotIn(identity, offered)
                with self.assertRaisesRegex(ValueError, '不能登记'):
                    self.run_plan([goal('resin', 0)], [stock(identity)])
        # Existing explicit assumptions about a new concrete class are not falsely
        # classified as a buff or assigned the constants of a different missile.
        from types import SimpleNamespace
        future = SimpleNamespace(data=self.catalog.data, entries=self.catalog.entries + [{'id': 'items.weapon.missiles.futureweapon'}])
        args = params([goal('liquid-metal', choices={'source_keys': ['s1']})], [stock('items.weapon.missiles.futureweapon')], 3)
        result = calculate(future, args)[1]
        self.assertIsNone(result['outputs'][0]['quantity'])
        self.assertTrue(result['pending_conditions'])

    def test_c2_chain_and_competing_goal_share_the_one_frost_and_energy(self):
        frost = stock('items.potions.potionoffrost')
        targets = [goal('recipe-elixiroficytouch'), goal('potion-frost', key='g2')]
        result = self.run_plan(targets, [frost], 10)
        self.assertEqual([s['recipe'] for s in result['steps']], ['potion-frost', 'recipe-elixiroficytouch'])
        self.assertEqual(result['outputs'][0]['id'], 'items.potions.elixirs.elixiroficytouch')
        self.assertEqual(result['energy']['remaining'], 0)
        self.assertEqual(result['materials'][0]['remaining'], 0)
        self.assertEqual(result['surplus'], [])
        self.assertEqual([t['planned_quantity'] for t in result['targets']], [1, 0])
        self.assertTrue(any(s['target'] == 'g2' and s['missing'] == 1 for s in result['shortages']))

    def test_yield_ceil_and_generated_surplus_are_shared_without_reusing_final_claims(self):
        ingredients = [stock('plants.blindweed$seed', 3), stock('items.stones.stoneofintuition', 3, key='s2')]
        choices = {'seed_id': ingredients[0]['id'], 'stone_id': ingredients[1]['id']}
        result = self.run_plan([goal('alchemize', 9, choices)], ingredients, 4)
        self.assertEqual(result['steps'][0]['batches'], 2)
        self.assertEqual(result['outputs'][0]['surplus'], 7)
        self.assertEqual([m['spent'] for m in result['materials']], [2, 2])
        # A fixed-yield result's unused newly made output is available to another target.
        result = self.run_plan([goal('recipe-beaconofreturning', 6), goal('recipe-beaconofreturning', 1, key='g2')],
                               [stock('items.scrolls.exotic.scrollofpassage', 2)], 24)
        self.assertEqual(len(result['steps']), 1)
        self.assertEqual(result['outputs'][1]['from_surplus'], 1)
        self.assertEqual(result['energy']['spent'], 24)

    def test_one_strength_potion_and_reserves_cannot_satisfy_two_targets(self):
        result = self.run_plan([goal('potion-strength'), goal('recipe-elixirofmight', key='g2')],
                               [stock('items.potions.potionofstrength', 2, reserve=1)], 100)
        self.assertEqual([t['planned_quantity'] for t in result['targets']], [1, 0])
        self.assertEqual(result['materials'][0]['remaining'], 1)
        self.assertEqual(result['energy']['spent'], 4)
        result = self.run_plan([goal('recipe-elixiroficytouch')], [stock('items.potions.potionoffrost')], 10, reserve=1)
        self.assertEqual(result['steps'], [])  # Failed target does not commit orphan prerequisites.
        self.assertEqual(result['materials'][0]['remaining'], 1)
        self.assertEqual(result['energy']['remaining'], 10)

    def test_cooking_mixed_batches_agree_with_independent_small_oracle_and_intmax(self):
        costs = [0]
        for n in range(1, 40):
            costs.append(min(costs[n - amount] + cost for amount, cost in ((1, 1), (2, 2), (3, 2)) if amount <= n))
            result = self.run_plan([goal('cook-meat', n)], [stock('items.food.mysterymeat', n)], 100)
            self.assertEqual(result['energy']['spent'], costs[n])
            self.assertEqual(result['outputs'][0]['quantity'], n)
        result = self.run_plan([goal('cook-meat', 4)], [stock('items.food.mysterymeat', 4)], 3)
        self.assertEqual(result['steps'][0]['cooking_counts']['recipe-stewedmeat-threemeat'], 1)
        self.assertEqual(result['outputs'][0]['quantity'], 4)
        result = self.run_plan([goal('cook-meat', MAX_INT)], [stock('items.food.mysterymeat', MAX_INT)], MAX_INT)
        self.assertEqual(result['energy']['spent'], 1431655765)
        self.assertEqual(len(result['steps']), 1)
        self.assertEqual(result['outputs'][0]['quantity'], MAX_INT)

    def test_all_twelve_fruits_remain_stateful_and_cooked_fruit_is_ineligible(self):
        for seed, potion in SEED_POTIONS.items():
            with self.subTest(seed=seed):
                rows = [stock('items.food.blandfruit', state={'cooked': 'raw'}), stock(seed, key='s2')]
                result = self.run_plan([goal('cook-fruit', choices={'seed_id': seed})], rows, 2)
                self.assertEqual(result['outputs'][0]['state'], {'cooked': 'cooked', 'potion_id': potion})
                rows[0]['state'] = {'cooked': 'cooked', 'potion_id': potion}
                result = self.run_plan([goal('cook-fruit', choices={'seed_id': seed})], rows, 2)
                self.assertFalse(result['within_budget'])
                self.assertEqual(result['materials'][0]['spent'], 0)
        self.assertIn('plants.blindweed$seed', {r['id'] for r in self.catalog.entries})

    def test_bombs_all_ten_variants_and_real_food_alternatives(self):
        for ingredient, output, cost in BOMBS:
            identity = 'items.' + ingredient.replace('/', '.').lower()
            result = self.run_plan([goal('enhance-bomb', choices={'ingredient_id': identity})],
                                   [stock('items.bombs.bomb'), stock(identity, key='s2')], cost)
            self.assertTrue(result['complete'])
            self.assertEqual(result['outputs'][0]['id'], 'items.bombs.' + output.lower())
        for pastry in ('pasty', 'phantommeat'):
            for meat in ('mysterymeat', 'stewedmeat', 'chargrilledmeat', 'frozencarpaccio'):
                choices = {'pasty_id': 'items.food.' + pastry, 'meat_id': 'items.food.' + meat}
                result = self.run_plan([goal('meat-pie', choices=choices)],
                                       [stock(choices['pasty_id']), stock('items.food.food', key='s2'), stock(choices['meat_id'], key='s3')], 6)
                self.assertTrue(result['complete'])
                self.assertEqual(result['outputs'][0]['id'], 'items.food.meatpie')

    def test_unstable_usage_randomness_does_not_make_crafting_output_random(self):
        seed, stone = 'plants.blindweed$seed', 'items.stones.stoneofintuition'
        for recipe, choices in [('unstable-brew', {'potion_id': 'items.potions.potionofstrength', 'seed_id': seed}),
                                ('unstable-spell', {'scroll_id': 'items.scrolls.scrollofupgrade', 'stone_id': stone})]:
            rows = [stock(identity, key='s' + str(n)) for n, identity in enumerate(choices.values())]
            result = self.run_plan([goal(recipe, choices=choices)], rows, 1)
            self.assertTrue(result['complete'])
            self.assertTrue(result['outcome_boundaries'])
            self.assertEqual(result['outputs'][0]['certainty'], 'known')

    def test_seed_probabilities_hidden_counter_and_no_expected_output_chain(self):
        sun = 'plants.sungrass$seed'
        result = self.run_plan([goal('seed-potion', 2, {'seed_ids': [sun] * 3})], [stock(sun, 6)], 0)
        self.assertTrue(result['within_budget'])
        self.assertFalse(result['complete'])
        self.assertIsNone(result['outputs'][0]['id'])
        self.assertIn('隐藏', result['outcome_boundaries'][0]['message'])
        self.assertEqual(result['materials'][0]['spent'], 6)
        self.assertEqual(result['surplus'], [])
        rot = 'plants.rotberry$seed'
        result = self.run_plan([goal('seed-potion', choices={'seed_ids': [rot] * 3})], [stock(rot, 3)], 0)
        self.assertEqual(result['outputs'][0]['id'], 'items.potions.potionofstrength')
        mixed = [sun, sun, 'plants.blindweed$seed']
        result = self.run_plan([goal('seed-potion', choices={'seed_ids': mixed})],
                               [stock(sun, 2), stock(mixed[2], key='s2')], 0)
        self.assertEqual(result['steps'][0]['probability']['default_pool_chance'], .25)
        probability = result['steps'][0]['probability']
        self.assertEqual(probability['default_pool_weight_total'], 30)
        self.assertEqual(probability['initial_probabilities_before_healing_reroll']['items.potions.potionofhealing'],
                         {'numerator': 11, 'denominator': 20})
        self.assertEqual(probability['default_pool_weights']['items.potions.potionofstrength'], 0)
        result = self.run_plan([goal('recipe-elixirofmight')],
                               [stock(sun, 3)], 16,
                               chains={'items.potions.potionofstrength': {'recipe': 'seed-potion', 'choices': {'seed_ids': [sun] * 3}}})
        self.assertFalse(result['within_budget'])
        self.assertEqual(result['materials'][0]['spent'], 0)

    def test_resin_base_public_bonus_talent_and_unknown_output(self):
        state = {'cursed': False, 'base_level': 2, 'public_level': 3, 'resin_bonus': 1, 'hero_class': 'MAGE'}
        row = stock('items.wands.wandofmagicmissile', state=state)
        result = self.run_plan([goal('resin', 6, {'source_keys': ['s1']})], [row], 5)
        self.assertEqual(result['outputs'][0]['quantity'], 6)
        self.assertEqual(result['energy']['spent'], 5)
        row['state']['hero_class'], row['state']['wand_preservation'] = 'WARRIOR', 2
        result = self.run_plan([goal('resin', 8, {'source_keys': ['s1']})], [row], 5)
        self.assertEqual(result['outputs'][0]['quantity'], 8)
        row['state'] = {'cursed': False, 'hero_class': 'MAGE'}
        result = self.run_plan([goal('resin', 1, {'source_keys': ['s1']})], [row], 5)
        self.assertEqual(result['materials'][0]['spent'], 1)
        self.assertEqual(result['energy']['spent'], 5)
        self.assertIsNone(result['outputs'][0]['quantity'])
        self.assertTrue(result['pending_conditions'])

    def test_resin_legal_preservation_points_and_shared_input_boundary(self):
        state = {'cursed': False, 'base_level': 0, 'public_level': 0,
                 'resin_bonus': 0, 'hero_class': 'WARRIOR'}
        original = params([goal('resin', 5, {'source_keys': ['s1']})],
                          [stock('items.wands.wandofmagicmissile', state=state)], 5)
        for points in (0, 1, 2):
            with self.subTest(points=points):
                args = copy.deepcopy(original)
                args['resources'][0]['state']['wand_preservation'] = points
                result = calculate(self.catalog, args)[1]
                self.assertEqual(result['outputs'][0]['produced_quantity'], 2 + points)
                self.assertEqual(result['targets'][0]['planned_quantity'], 2 + points)
                self.assertEqual(result['targets'][0]['shortfall'], 3 - points)
                self.assertFalse(result['complete'])
                self.assertEqual((result['materials'][0]['spent'], result['energy']['spent']), (1, 5))
                candidates = discover(self.catalog, args)
                resin = next(row for row in candidates['recipes'] if row['id'] == 'resin')
                self.assertTrue(resin['complete'])
                self.assertEqual(resin['steps'][0]['output']['quantity'], 2 + points)
        for points in (3, 4, True, False):
            for hero in ('WARRIOR', 'MAGE'):
                with self.subTest(points=points, hero=hero):
                    args = copy.deepcopy(original)
                    args['resources'][0]['state'].update(hero_class=hero, wand_preservation=points)
                    before = copy.deepcopy(args)
                    with self.assertRaises(ValueError):
                        calculate(self.catalog, args)
                    with self.assertRaises(ValueError):
                        discover(self.catalog, args)
                    # Even a currently unused resource cannot certify impossible
                    # fixed shared inputs as a successful calculation.
                    args['targets'] = [goal('potion-healing', 0)]
                    with self.assertRaises(ValueError):
                        calculate(self.catalog, args)
                    self.assertEqual(args['resources'], before['resources'])
        unknown = calculate(self.catalog, original)[1]
        self.assertIsNone(unknown['outputs'][0]['quantity'])
        self.assertFalse(unknown['complete'])
        self.assertTrue(unknown['pending_conditions'])
        mage = copy.deepcopy(original)
        mage['targets'][0]['quantity'] = 2
        mage['resources'][0]['state'].update(hero_class='MAGE', wand_preservation=2)
        self.assertEqual(calculate(self.catalog, mage)[1]['outputs'][0]['quantity'], 2)

    def test_historical_invalid_resin_remains_readable_until_explicit_correction(self):
        with tempfile.TemporaryDirectory(prefix='denghuo-old-resin-') as directory:
            root = Path(directory)
            session = Session(root / 'source' / 'settings.json', self.catalog)
            args = params([goal('resin', 5, {'source_keys': ['s1']})],
                          [stock('items.wands.wandofmagicmissile', state={
                              'cursed': False, 'base_level': 0, 'public_level': 0,
                              'resin_bonus': 0, 'hero_class': 'WARRIOR', 'wand_preservation': 2})], 5)
            first = session.knowledge.save('旧树脂方案', 'alchemy', None, args, note='保留原条件与备注')
            normal = session.knowledge.save('正常方案', 'alchemy', None, params([goal('potion-healing', 0)]))
            historical = json.loads(session.knowledge.export())
            old = next(row for row in historical['plans'] if row['id'] == first['id'])
            old['params']['resources'][0]['state']['wand_preservation'] = 3
            raw = (json.dumps(historical, ensure_ascii=False, indent=1) + '\n').encode('utf-8')
            session.knowledge.path.write_bytes(raw)
            store = Session(session.config_path, self.catalog).knowledge
            status = store.status()
            self.assertTrue(status['available'])
            self.assertEqual(len(status['plans']), 2)
            opened = store.reopen(first['id'])
            self.assertEqual(opened['plan']['params'], old['params'])
            self.assertIsNone(opened['result'])
            self.assertIn('法杖保存天赋点数必须为0–2', opened['calculation_error'])
            self.assertTrue(store.reopen(normal['id'])['result']['complete'])
            self.assertNotIn('calculation_error', store.reopen(normal['id']))
            self.assertEqual(json.loads(store.export()), historical)
            self.assertEqual(store.path.read_bytes(), raw)
            draft_raw = copy.deepcopy(old['params'])
            for name in ('energy', 'energy_reserve'):
                draft_raw[name] = str(draft_raw[name])
            for target_row in draft_raw['targets']:
                target_row['quantity'] = str(target_row['quantity'])
            for resource in draft_raw['resources']:
                for name in ('quantity', 'reserve'):
                    resource[name] = str(resource[name])
                resource['state'] = {name: str(value).lower() if type(value) is bool else str(value)
                                     for name, value in resource['state'].items()}
            draft_raw['resources'][0]['state']['wand_preservation'] = ' 3 '
            draft = {'format': 2, 'schema': 'denghuo-web-session',
                     'alchemy': {'raw': draft_raw, 'note': '非法点数仍是未计算原始草稿'}}
            saved_draft = session.exit_drafts.save('web-12345678', 'web-session', '未完成树脂', draft)
            resumed = Session(session.config_path, self.catalog)
            self.assertEqual(resumed.exit_drafts.load(saved_draft['id'])['draft'], draft)
            self.assertNotIn('result', draft['alchemy'])
            self.assertEqual(store.path.read_bytes(), raw)
            with self.assertRaisesRegex(ValueError, '法杖保存天赋'):
                store.save('不得保存成功', 'alchemy', None, old['params'])
            with self.assertRaisesRegex(ValueError, '法杖保存天赋'):
                store.save('不得更新成功', 'alchemy', None, old['params'], record_id=first['id'],
                           expected_record_revision=opened['plan']['record_revision'])
            self.assertEqual(store.path.read_bytes(), raw)
            target = Session(root / 'imported' / 'settings.json', self.catalog).knowledge
            self.assertEqual(target.import_records(raw)['plans_added'], 2)
            imported_bytes = target.path.read_bytes()
            self.assertEqual(target.reopen(first['id'])['plan'], opened['plan'])
            self.assertIsNone(target.reopen(first['id'])['result'])
            self.assertEqual(json.loads(target.export()), historical)
            self.assertEqual(target.path.read_bytes(), imported_bytes)
            self.assertEqual(store.path.read_bytes(), raw)
            corrected = copy.deepcopy(opened['plan']['params'])
            corrected['resources'][0]['state']['wand_preservation'] = 2
            result = calculate(self.catalog, corrected)[1]
            self.assertEqual((result['targets'][0]['planned_quantity'], result['targets'][0]['shortfall']), (4, 1))
            with self.assertRaisesRegex(ValueError, '另一窗口'):
                store.save('修正', 'alchemy', None, corrected, record_id=first['id'],
                           expected_record_revision='0' * 64)
            self.assertEqual(store.path.read_bytes(), raw)
            updated = store.save('修正', 'alchemy', None, corrected, record_id=first['id'],
                                 expected_record_revision=opened['plan']['record_revision'])
            self.assertEqual(updated['id'], first['id'])
            self.assertEqual(updated['created'], first['created'])
            self.assertEqual(updated['note'], first['note'])
            self.assertNotEqual(updated['record_revision'], opened['plan']['record_revision'])
            self.assertEqual(store.reopen(first['id'])['result']['targets'][0]['shortfall'], 1)
            self.assertEqual(old['params']['resources'][0]['state']['wand_preservation'], 3)
            with self.assertRaisesRegex(ValueError, '另一窗口'):
                store.save('旧版本覆盖', 'alchemy', None, corrected, record_id=first['id'],
                           expected_record_revision=opened['plan']['record_revision'])

    def test_missile_whole_stack_states_reserve_and_exact_durability_is_manual(self):
        state = {'cursed': False, 'is_upgradable': True, 'level': 0, 'tier': 1, 'default_quantity': 3, 'durability': 100}
        rows = [stock('items.weapon.missiles.throwingstone', 3, state=state),
                stock('items.weapon.missiles.throwingstone', 2, key='s2', state={**state, 'level': 2, 'durability': 50})]
        result = self.run_plan([goal('liquid-metal', 1, {'source_keys': ['s1']})], rows, 3)
        self.assertEqual([r['spent'] for r in result['materials']], [3, 0])
        self.assertEqual(result['outputs'][0]['produced_quantity'], 30)
        rows[0]['reserve'] = 1
        result = self.run_plan([goal('liquid-metal', 1, {'source_keys': ['s1']})], rows, 3)
        self.assertFalse(result['within_budget'])
        self.assertEqual(result['materials'][0]['spent'], 0)
        rows[0]['reserve'], rows[0]['state']['durability'] = 0, None
        result = self.run_plan([goal('liquid-metal', 1, {'source_keys': ['s1']})], rows, 3)
        self.assertIsNone(result['outputs'][0]['quantity'])
        self.assertEqual(result['materials'][0]['spent'], 3)
        rows[0]['state']['durability'], rows[0]['origin'] = 50, 'known'
        with self.assertRaisesRegex(ValueError, '精确耐久'):
            validate_plan(params([goal('liquid-metal', choices={'source_keys': ['s1']})], rows))
        self.assertEqual(metal_quantity(MAX_INT, 5, 3, 5, 100), MAX_INT)

    def test_all_seventeen_trinkets_use_existing_rules_per_successive_level(self):
        expensive = {'MossyClump', 'ParchmentScrap', 'WondrousResin'}
        for trinket in TRINKETS:
            identity = 'items.trinkets.' + trinket.lower()
            costs = [10, 15, 20] if trinket in expensive else [6, 8, 10]
            result = self.run_plan([goal('trinket-upgrade', choices={'source_key': 's1', 'target_level': 3})],
                                   [stock(identity, state={'level': 0})], sum(costs))
            self.assertEqual([step['energy']['spent'] for step in result['steps']], costs)
            self.assertEqual([step['level_after'] for step in result['steps']], [1, 2, 3])
            self.assertEqual(result['outputs'][0]['state']['level'], 3)
            self.assertEqual(result['materials'][0]['spent'], 1)

    def test_catalyst_paid_selection_and_random_placeholder_remain_distinct(self):
        identity = 'items.trinkets.trinketcatalyst'
        row = stock(identity, state={'catalyst_stage': 'unrolled'})
        result = self.run_plan([goal('trinket-catalyst', choices={'source_key': 's1'})], [row], 6)
        self.assertEqual(result['energy']['spent'], 6)
        self.assertIsNone(result['outputs'][0]['id'])
        options = ['items.trinkets.' + name.lower() for name in TRINKETS[:4]]
        row['state'] = {'catalyst_stage': 'awaiting_choice', 'rolled_choices': options}
        result = self.run_plan([goal('trinket-catalyst', choices={'source_key': 's1', 'selection': 2})], [row], 0)
        self.assertEqual(result['outputs'][0]['id'], options[2])
        self.assertEqual(result['energy']['spent'], 0)
        options[2] = 'items.trinkets.trinketcatalyst$randomtrinket'
        result = self.run_plan([goal('trinket-catalyst', choices={'source_key': 's1', 'selection': 2})], [row], 0)
        self.assertIsNone(result['outputs'][0]['id'])

    def test_cycles_structural_retention_and_discovery_leave_input_unchanged(self):
        original = params([goal('recipe-elixiroficytouch')], [stock('items.potions.potionoffrost')], 10)
        before = copy.deepcopy(original)
        result = discover(self.catalog, {k: v for k, v in original.items() if k != 'targets'})
        self.assertEqual(original, before)
        icy = next(r for r in result['recipes'] if r['id'] == 'recipe-elixiroficytouch')
        self.assertTrue(icy['craftable'])
        self.assertEqual(len(icy['steps']), 2)
        future = copy.deepcopy(original); future['targets'][0]['recipe'] = 'future-recipe'
        self.assertEqual(validate_plan(future), future)
        loop = {'items.potions.potionoffrost': {'recipe': 'recipe-elixiroficytouch', 'choices': {}}}
        result = self.run_plan([goal('recipe-elixiroficytouch')], [], 10, chains=loop)
        self.assertTrue(result['pending_conditions'])
        duplicate = copy.deepcopy(original); duplicate['resources'] *= 2
        with self.assertRaisesRegex(ValueError, '库存实例'): validate_plan(duplicate)
        for field in ('quantity',):
            bad = copy.deepcopy(original); bad['targets'][0][field] = True
            with self.assertRaises(ValueError): validate_plan(bad)

    def test_dynamic_surplus_is_shared_and_does_not_spend_a_second_batch(self):
        seed, stone = 'plants.blindweed$seed', 'items.stones.stoneofintuition'
        choices = {'seed_id': seed, 'stone_id': stone}
        result = self.run_plan([goal('alchemize', 9, choices), goal('alchemize', 1, choices, 'g2')],
                               [stock(seed, 2), stock(stone, 2, key='s2')], 4)
        self.assertTrue(result['complete'])
        self.assertEqual(len(result['steps']), 1)
        self.assertEqual(result['outputs'][1]['from_surplus'], 1)
        self.assertEqual(sum(row['quantity'] for row in result['surplus']), 6)
        self.assertEqual(result['energy']['spent'], 4)

    def test_seed_and_whole_stack_prerequisites_then_explicit_alternative_selection(self):
        result = self.run_plan([goal('recipe-elixiroficytouch')], [stock('plants.icecap$seed', 3)], 10)
        self.assertTrue(result['complete'])
        self.assertEqual([s['recipe'] for s in result['steps']], ['seed-potion', 'potion-frost', 'recipe-elixiroficytouch'])
        state = {'cursed': False, 'is_upgradable': True, 'level': 0, 'tier': 1, 'default_quantity': 3, 'durability': 100}
        rows = [stock('items.weapon.missiles.throwingstone', 3, state=state),
                stock('items.weapon.missiles.throwingstone', 3, key='s2', state=state)]
        result = self.run_plan([goal('recipe-telekineticgrab', 8)], rows, 13)
        self.assertFalse(result['within_budget'])
        self.assertEqual(len(result['shortages'][0]['options']), 2)
        result = self.run_plan([goal('recipe-telekineticgrab', 8)], rows, 13,
                               chains={'items.liquidmetal': {'recipe': 'liquid-metal', 'choices': {'source_keys': ['s2']}}})
        self.assertTrue(result['complete'])
        self.assertEqual([r['spent'] for r in result['materials']], [0, 3])
        self.assertEqual([s['recipe'] for s in result['steps']], ['liquid-metal', 'recipe-telekineticgrab'])
        self.assertEqual(result['surplus'][0]['quantity'], 20)

    def test_paid_catalyst_selection_can_be_one_upgrade_prerequisite_but_unrolled_cannot(self):
        options = ['items.trinkets.' + name.lower() for name in TRINKETS[:4]]
        row = stock('items.trinkets.trinketcatalyst', state={'catalyst_stage': 'awaiting_choice', 'rolled_choices': options})
        chain = {options[0]: {'recipe': 'trinket-catalyst', 'choices': {'source_key': 's1', 'selection': 0}}}
        target = goal('trinket-upgrade', choices={'source_key': 's1', 'target_level': 3})
        result = self.run_plan([target], [row], 24, chains=chain)
        self.assertTrue(result['complete'])
        self.assertEqual([s['energy']['spent'] for s in result['steps']], [0, 6, 8, 10])
        self.assertEqual(result['outputs'][0]['id'], options[0])
        self.assertEqual(result['outputs'][0]['state']['level'], 3)
        self.assertEqual(result['materials'][0]['spent'], 1)
        self.assertEqual(result['surplus'], [])
        row['state'] = {'catalyst_stage': 'unrolled'}
        result = self.run_plan([target], [row], 30, chains=chain)
        self.assertFalse(result['within_budget'])
        self.assertTrue(result['pending_conditions'])
        self.assertEqual(result['energy']['spent'], 0)
        self.assertEqual(result['materials'][0]['spent'], 0)

    def test_unknown_upgrade_fee_never_becomes_a_free_upgrade(self):
        row = stock('items.trinkets.ratskull')
        result = self.run_plan([goal('trinket-upgrade', choices={'source_key': 's1', 'target_level': 3})], [row], 0)
        self.assertFalse(result['within_budget'])
        self.assertTrue(result['pending_conditions'])
        self.assertEqual((result['energy']['spent'], result['materials'][0]['spent']), (0, 0))

    def test_unknown_durability_has_bounds_and_float_rounding_known_examples(self):
        state = {'cursed': False, 'is_upgradable': True, 'level': 0, 'tier': 1, 'default_quantity': 3}
        result = self.run_plan([goal('liquid-metal', choices={'source_keys': ['s1']})],
                               [stock('items.weapon.missiles.throwingstone', 3, state=state)], 3)
        output = result['outputs'][0]
        self.assertIsNone(output['quantity'])
        self.assertEqual((output['yield_bounds']['minimum'], output['yield_bounds']['maximum']), (23, 30))
        self.assertEqual(result['energy']['spent'], 3)
        for args, expected in [((1, 1, 3, 0, 0), 3), ((1, 1, 3, 0, 100), 10),
                               ((2, 1, 3, 0, 0), 13), ((1, 5, 5, 0, 100), 1),
                               ((3, 1, 3, 5, 100), 135), ((7, 3, 3, 2, 100), 255)]:
            self.assertEqual(metal_quantity(*args), expected)

    def test_signed_public_levels_are_preserved_without_turning_unknown_into_zero(self):
        row = stock('items.weapon.missiles.throwingstone', 3,
                    state={'cursed': False, 'is_upgradable': True, 'level': -1,
                           'tier': 1, 'default_quantity': 3, 'durability': 100})
        original = params([goal('liquid-metal', choices={'source_keys': ['s1']})], [row], 3)
        self.assertEqual(validate_plan(original)['resources'][0]['state']['level'], -1)
        result = calculate(self.catalog, original)[1]
        self.assertEqual(result['outputs'][0]['produced_quantity'], 22)
        row = stock('items.wands.wandofmagicmissile', state={'cursed': False, 'base_level': -1,
                    'public_level': 0, 'resin_bonus': 1, 'hero_class': 'MAGE'})
        result = self.run_plan([goal('resin', choices={'source_keys': ['s1']})], [row], 5)
        self.assertFalse(result['within_budget'])
        self.assertEqual((result['materials'][0]['spent'], result['energy']['spent']), (0, 0))

    def test_fixed_missile_type_constants_cannot_be_overridden_by_a_manual_tier(self):
        row = stock('items.weapon.missiles.throwingstone', 3,
                    state={'cursed': False, 'level': 0, 'durability': 100})
        result = self.run_plan([goal('liquid-metal', choices={'source_keys': ['s1']})], [row], 3)
        self.assertEqual(result['outputs'][0]['produced_quantity'], 30)
        row['state']['tier'] = 5
        with self.assertRaisesRegex(ValueError, '固定种类'):
            self.run_plan([goal('liquid-metal', choices={'source_keys': ['s1']})], [row], 3)
        row['id'] = 'items.weapon.missiles.darts.dart'
        row['state'] = {'cursed': False, 'level': 0, 'is_upgradable': True, 'durability': 100}
        with self.assertRaisesRegex(ValueError, '不可升级'):
            self.run_plan([goal('liquid-metal', choices={'source_keys': ['s1']})], [row], 3)

    def test_maxint_partial_output_uses_at_most_32_feasibility_probes(self):
        seed, stone = 'plants.blindweed$seed', 'items.stones.stoneofintuition'
        calls = []
        original = Ledger.goal
        def counted(ledger, target, quantity):
            calls.append(quantity)
            return original(ledger, target, quantity)
        with patch.object(Ledger, 'goal', counted):
            result = self.run_plan([goal('alchemize', MAX_INT, {'seed_id': seed, 'stone_id': stone})],
                                   [stock(seed, MAX_INT), stock(stone, MAX_INT, key='s2')], MAX_INT)
        self.assertLessEqual(len(calls), 33)
        self.assertEqual(result['outputs'][0]['quantity'], MAX_INT - 7)
        self.assertEqual(len(result['steps']), 1)
        self.assertEqual(result['energy']['spent'], 536870910)

    def test_real_cycle_is_rejected_with_no_committed_orphan_consumption(self):
        definitions = recipe_list(self.catalog)
        a, b = copy.deepcopy(definitions[0]), copy.deepcopy(definitions[1])
        a.update(id='cycle-a', output='items.potions.potionofstrength', inputs=[{'id': 'items.potions.potionofhealing', 'quantity': 1}])
        b.update(id='cycle-b', output='items.potions.potionofhealing', inputs=[{'id': 'items.potions.potionofstrength', 'quantity': 1}])
        with patch('companion.alchemy_flow.recipe_list', return_value=[a, b]):
            result = self.run_plan([goal('cycle-a')], [], 100,
                                   chains={a['output']: {'recipe': 'cycle-a', 'choices': {}},
                                           b['output']: {'recipe': 'cycle-b', 'choices': {}}})
        self.assertFalse(result['within_budget'])
        self.assertIn('循环', result['shortages'][0]['reason'])
        self.assertEqual((result['steps'], result['energy']['spent']), ([], 0))

    def test_discovery_skips_cursed_first_instance_and_missing_levels_stay_conditional(self):
        rows = [stock('items.wands.wandofmagicmissile', state={'cursed': True}),
                stock('items.wands.wandofmagicmissile', key='s3', state={'cursed': False}),
                stock('items.wands.wandofmagicmissile', key='s2', state={'cursed': False, 'base_level': 0, 'hero_class': 'MAGE'})]
        result = discover(self.catalog, {k: v for k, v in params([goal('resin')], rows, 5).items() if k != 'targets'})
        resin = next(r for r in result['recipes'] if r['id'] == 'resin')
        self.assertTrue(resin['complete'])
        self.assertEqual(resin['target']['choices']['source_keys'], ['s2'])
        self.assertEqual(len(result['recipes']), len(family_list(self.catalog)))

    def test_v2_save_reopen_copy_import_and_future_recipe_retention(self):
        with tempfile.TemporaryDirectory(prefix='denghuo-target-alchemy-') as directory:
            root = Path(directory)
            session = Session(root / 'source' / 'settings.json', self.catalog)
            original = params([goal('recipe-elixiroficytouch')], [stock('plants.icecap$seed', 3)], 10)
            first = session.knowledge.save('三步炼金', 'alchemy', None, original, note='明确手填与种子前置')
            original['resources'][0]['quantity'] = 0
            opened = session.knowledge.reopen(first['id'])
            self.assertEqual(opened['plan']['params']['resources'][0]['quantity'], 3)
            self.assertEqual(len(opened['result']['steps']), 3)
            target = Session(root / 'target' / 'settings.json', self.catalog)
            self.assertEqual(target.knowledge.import_records(session.knowledge.export())['plans_added'], 1)
            self.assertEqual(target.knowledge.reopen(first['id'])['result']['outputs'], opened['result']['outputs'])
            archive = json.loads(session.knowledge.export())
            archive['plans'][0]['params']['targets'][0]['recipe'] = 'future-family'
            future = Session(root / 'future' / 'settings.json', self.catalog)
            with patch('companion.alchemy.calculate', side_effect=AssertionError('Import must not calculate')):
                self.assertEqual(future.knowledge.import_records(json.dumps(archive).encode())['plans_added'], 1)
            self.assertEqual(future.knowledge.status()['plans'][0]['params']['targets'][0]['recipe'], 'future-family')
            unsupported = future.knowledge.reopen(first['id'])
            self.assertIsNone(unsupported['result'])
            self.assertIn('尚未收录', unsupported['calculation_error'])
            self.assertEqual(unsupported['plan']['params'], archive['plans'][0]['params'])


if __name__ == '__main__':
    unittest.main()
