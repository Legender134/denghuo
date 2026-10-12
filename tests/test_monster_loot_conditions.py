"""Bounded ordinary-loot conditions from the pinned Mob and Trinket rules."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from companion.engine import Catalog
from companion.monster_reference import loot_rows, monster_record, reference
from companion.rules import NumericRules
from companion.values import PlayerValues


class OblivionLootTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.values = PlayerValues(NumericRules(Catalog()))

    def loot(self, name, **params):
        identity = 'actors.mobs.'+name
        return loot_rows(self.values, identity, monster_record(self.values.catalog, identity),
                         {'depth':4, 'hero_level':1, 'loot_count':0, 'swarm_generation':0, **params})

    def chance(self, name, item, **params):
        return sum(row['probability'] for row in self.loot(name, **params) if row.get('id') == item)

    def test_shard_and_wealth_add_in_mob_bonus_instead_of_multiplying(self):
        # HermitCrab.java:37 sets 0.5f. ShardOfOblivion.java:196-223
        # gives +0.2 per eligible item, capped by level+1. Mob.java:1091
        # adds only the fragment's excess to Wealth's 1.2^bonus.
        meat = 'items.food.mysterymeat'
        for wealth, level, count, expected in ((0,-1,7,.5), (0,0,0,.5), (0,0,1,.6),
                                               (1,0,1,.7), (0,0,7,.6), (0,1,7,.7),
                                               (0,2,7,.8), (0,3,7,.9), (-1,0,1,31/60)):
            with self.subTest(wealth=wealth, level=level, count=count):
                self.assertAlmostEqual(self.chance('hermitcrab', meat, wealth_bonus=wealth,
                    oblivion_shard=level, unidentified_equipment=count), expected, places=7)
        detail = self.values.detail('actors.mobs.hermitcrab',
            {'wealth_bonus':1, 'oblivion_shard':0, 'unidentified_equipment':1})
        meat_row = next(row for row in detail['blocks'][1]['rows'] if row[0] == '神秘的肉')
        self.assertEqual(meat_row[2], '70%')
        self.assertIn('与财富、赏金猎人相加', meat_row[3])

    def test_count_decay_generation_level_gates_and_cap_follow_bonus(self):
        args = {'wealth_bonus':1, 'oblivion_shard':0, 'unidentified_equipment':1}
        # Skeleton's base .1667 and 1/3 limited-drop decay; Swarm explicitly
        # replaces its base with 1/(6*(generation+1)), then applies 4/5.
        self.assertAlmostEqual(sum(row['probability'] for row in self.loot('skeleton', loot_count=1, **args)),
                               .1667*1.4/3, places=7)
        self.assertAlmostEqual(self.chance('swarm', 'items.potions.potionofhealing',
            swarm_generation=1, loot_count=1, **args), 7/75, places=7)
        self.assertEqual(self.chance('swarm', 'items.potions.potionofhealing', loot_count=5, **args), 0)
        for hero, expected in ((11,1), (12,0)):
            self.assertEqual(self.chance('hermitcrab', 'items.food.mysterymeat', hero_level=hero,
                wealth_bonus=2, oblivion_shard=3, unidentified_equipment=7), expected)

    def test_exotic_conversion_keeps_same_conditioned_ordinary_total(self):
        args = {'wealth_bonus':1, 'oblivion_shard':0, 'unidentified_equipment':1,
                'exotic_crystals':0, 'loot_count':1}
        total = .1667*1.4*6/7
        rows = self.loot('bat', **args)
        self.assertAlmostEqual(sum(row['probability'] for row in rows), total, places=7)
        self.assertAlmostEqual(self.chance('bat', 'items.potions.exotic.potionofshielding', **args),
                               total/5, places=7)

    def test_fixed_rewards_and_constant_vault_overrides_keep_their_paths(self):
        args = {'wealth_bonus':-1, 'oblivion_shard':3, 'unidentified_equipment':7}
        for name, item in (('causticslime','items.quest.gooblob'), ('dm201','items.quest.metalshard'),
                           ('rotheart','plants.rotberry$seed'), ('elemental$newbornfireelemental','items.quest.embers')):
            self.assertEqual(self.chance(name, item, **args), 1)
        armor = [row for row in self.loot('hermitcrab', **args) if row['id'].startswith('items.armor.')]
        self.assertAlmostEqual(sum(row['probability'] for row in armor), 1)
        for name in ('vaultdm200','vaultgolem','vaultshaman','vaultskeleton'):
            identity = 'actors.mobs.quest.vault.'+name
            self.assertEqual(self.chance('quest.vault.'+name, 'items.quest.dwarftoken', **args), 1)
            keys = {field['key'] for field in self.values.detail(identity)['inputs']}
            self.assertFalse(keys & {'oblivion_shard','unidentified_equipment'})
        # These Vault variants inherit Mob.lootChance instead of returning 1.
        inherited = {'wealth_bonus':-1, 'oblivion_shard':0, 'unidentified_equipment':1}
        for name in ('vaultdm100','vaultghoul','vaultelemental$fire'):
            self.assertAlmostEqual(self.chance('quest.vault.'+name, 'items.quest.dwarftoken', **inherited), 1, places=7)
        self.assertEqual(self.loot('gnollexile'), self.loot('gnollexile', **args))
        # Acidic overrides createLoot, but still reaches Mob.lootChance.
        self.assertAlmostEqual(self.chance('acidic', 'items.potions.potionofexperience',
            wealth_bonus=-1, oblivion_shard=0, unidentified_equipment=0), 5/6, places=7)

    def test_defaults_are_disabled_and_explicit_conditions_are_finite_integers(self):
        for identity in reference()['monsters']:
            name = identity.removeprefix('actors.mobs.')
            if not identity.startswith('actors.mobs.'): continue
            self.assertEqual(self.loot(name), self.loot(name, oblivion_shard=-1, unidentified_equipment=0))
        detail = self.values.detail('actors.mobs.hermitcrab')
        fields = {field['key']:field for field in detail['inputs']}
        for key, expected in (('oblivion_shard',(-1,-1,3,1)), ('unidentified_equipment',(0,0,7,1))):
            self.assertEqual(tuple(fields[key][name] for name in ('value','min','max','step')), expected)
        for key, invalids in (('oblivion_shard',(-2,4,True,.5,float('inf'),'NaN')),
                              ('unidentified_equipment',(-1,8,False,.5,float('nan'),'Infinity'))):
            for invalid in invalids:
                with self.subTest(key=key, value=invalid), self.assertRaises(ValueError):
                    self.values.detail('actors.mobs.hermitcrab', {key:invalid})

    def test_condition_notes_and_provenance_keep_manual_scope_explicit(self):
        detail = self.values.detail('actors.mobs.hermitcrab')
        self.assertIn('不会自动鉴定', detail['blocks'][1]['note'])
        self.assertIn('近期使用', detail['blocks'][1]['note'])
        self.assertIn('不计算财富额外战利品', detail['blocks'][1]['note'])
        urls = [row['url'] for row in detail['provenance']['links']]
        self.assertTrue(any('ShardOfOblivion.java#L196' in url for url in urls))
        self.assertTrue(any('Mob.java#L1075' in url for url in urls))
        self.assertTrue(any('Trinket.java#L48' in url for url in urls))
        self.assertTrue(any('不从存档推定' in row for row in detail['provenance']['limits']))
        source = 'core/src/main/java/com/shatteredpixel/shatteredpixeldungeon/items/trinkets/ShardOfOblivion.java'
        self.assertIn(source, reference()['verified_source_files'])

    def test_successful_sleeve_theft_closes_only_the_ordinary_loot_channel(self):
        # Mob.rollToDropLoot skips createLoot after a successful StolenTracker.
        # A failed attempt has counter 0 and does not close the death-loot gate.
        self.assertAlmostEqual(sum(r['probability'] for r in self.loot('skeleton', loot_count=1)), .1667/3)
        stolen = {'loot_stolen':1, 'loot_count':1, 'bounty_hunter':3, 'preparation_level':4}
        self.assertEqual(sum(r['probability'] for r in self.loot('skeleton', **stolen)), 0)
        for name, item in (('causticslime','items.quest.gooblob'), ('dm201','items.quest.metalshard'),
                           ('spectralnecromancer','items.scrolls.scrollofremovecurse'),
                           ('elemental$newbornfireelemental','items.quest.embers')):
            self.assertEqual(self.chance(name, item, **stolen), 1)
        armor = [r for r in self.loot('hermitcrab', **stolen) if r['id'].startswith('items.armor.')]
        self.assertAlmostEqual(sum(r['probability'] for r in armor), 1)
        for name in ('vaultdm200','vaultgolem','vaultshaman','vaultskeleton'):
            self.assertEqual(self.chance('quest.vault.'+name, 'items.quest.dwarftoken', **stolen), 0)
        self.assertEqual(self.loot('gnollexile'), self.loot('gnollexile', **stolen))
        self.assertIn('失败尝试', self.loot('skeleton')[0]['condition'])
        self.assertIn('已被袖章成功偷取', self.loot('skeleton', **stolen)[0]['condition'])

    def test_bounty_hunter_adds_to_wealth_before_shard_count_and_level_gates(self):
        # Pinned Mob.java:1083-1093: .02f * 2^(prep-1) * talentPoints,
        # added to Wealth, then Shard excess. These expected values are derived
        # from that branch; the normal Skeleton base is .1667f.
        for points, prep, expected in ((0,4,.1667), (3,0,.1667), (1,1,.170034),
                                       (2,2,.180036), (3,3,.206708), (3,4,.246716)):
            self.assertAlmostEqual(sum(r['probability'] for r in self.loot('skeleton',
                bounty_hunter=points, preparation_level=prep)), expected, places=7)
        args = {'wealth_bonus':1,'bounty_hunter':3,'preparation_level':4,
                'oblivion_shard':0,'unidentified_equipment':1}
        self.assertAlmostEqual(sum(r['probability'] for r in self.loot('skeleton', loot_count=1, **args)),
                               .1667*1.88/3, places=7)
        self.assertAlmostEqual(self.chance('bat', 'items.potions.exotic.potionofshielding',
            loot_count=1, exotic_crystals=0, **args), .1667*1.88*6/7/5, places=7)
        self.assertEqual(self.chance('hermitcrab','items.food.mysterymeat', hero_level=12, **args), 0)
        self.assertEqual(self.chance('hermitcrab','items.food.mysterymeat', **{**args,'wealth_bonus':100}), 1)
        for name in ('vaultdm200','vaultgolem','vaultshaman','vaultskeleton'):
            self.assertEqual(self.chance('quest.vault.'+name,'items.quest.dwarftoken', **args), 1)

    def test_target_and_bounty_conditions_are_bounded_and_have_fixed_sources(self):
        fields = {r['key']:r for r in self.values.detail('actors.mobs.skeleton')['inputs']}
        for key, limits in (('loot_stolen',(0,0,1,1)), ('bounty_hunter',(0,0,3,1)),
                            ('preparation_level',(0,0,4,1))):
            self.assertEqual(tuple(fields[key][f] for f in ('value','min','max','step')), limits)
            for invalid in (True, False, -.5, 'NaN', float('inf'), limits[2]+1):
                with self.subTest(key=key, invalid=invalid), self.assertRaises(ValueError):
                    self.values.detail('actors.mobs.skeleton', {key:invalid})
        for name in ('gnollexile','crystalmimic'):
            self.assertNotIn('loot_stolen', {r['key'] for r in self.values.detail('actors.mobs.'+name)['inputs']})
        fixed = {r['key'] for r in self.values.detail('actors.mobs.quest.vault.vaultskeleton')['inputs']}
        self.assertIn('loot_stolen', fixed)
        self.assertFalse(fixed & {'bounty_hunter','preparation_level'})
        detail = self.values.detail('actors.mobs.skeleton')
        urls = [r['url'] for r in detail['provenance']['links']]
        self.assertTrue(any('MasterThievesArmband.java#L141' in url for url in urls))
        self.assertTrue(any('Preparation.java#L62' in url for url in urls))
        self.assertTrue(any('Talent.java#L139' in url for url in urls))
        self.assertIn('未满足填0', detail['blocks'][1]['note'])
        self.assertNotIn('未计财富额外战利品、赏金猎人', detail['blocks'][1]['note_summary'])


class OblivionPlanWorkflowTests(unittest.TestCase):
    def test_native_form_fixed_reopen_and_export_import_retain_manual_loot_conditions(self):
        # Test runners isolate APPDATA/LOCALAPPDATA before imports. Every
        # Session also starts from an explicit synthetic save_root in its file.
        from companion.native_workspace import NumericLookup
        from companion.service import Session
        directory = Path(tempfile.mkdtemp(prefix='lamp-oblivion-plan-'))
        save_root = directory/'synthetic-saves'
        save_root.mkdir()
        marker = save_root/'unrelated.bin'
        marker.write_bytes(b'synthetic-save-preserved\x00\xff')
        settings = directory/'settings.json'
        settings.write_text(json.dumps({'save_root':str(save_root), 'mode':'manual', 'always_on_top':False}), encoding='utf-8')
        session = Session(settings)
        session.update_manual({'hp':4, 'ht':30, 'level':5})
        host = SimpleNamespace(commands=[], revision=0, closed=False)
        host.command = lambda action, **payload: host.commands.append((action, copy.deepcopy(payload)))
        worker = SimpleNamespace(ticket=0, args=None)
        def request(kind, *args):
            worker.ticket += 1
            worker.args = kind, args
            return worker.ticket
        worker.request = request
        manager = SimpleNamespace(session=session, root=Mock(), play=None, play_settings=None,
            play_apply_error='', hotkeys=None, native_ui=SimpleNamespace(host=host, report_drafts=Mock()))
        owner = SimpleNamespace(manager=manager, worker=worker, native=Mock(), pinned=None,
            peek_key=None, preferences=session.play_preferences, state=session.play_preferences.values)
        manager.play = owner
        owner.save = lambda patch, expected_generation=None: session.play_preferences.update(patch, expected_generation=expected_generation)
        lookup = owner.lookup = NumericLookup(owner)
        lookup.select_row(session.values.rules.entries['actors.mobs.hermitcrab'])
        lookup.render(session.values.detail(*worker.args[1]))
        state = next(payload for action, payload in reversed(host.commands) if action == 'lookup_state')
        fields = {field['key']:field for field in state['fields']}
        self.assertEqual(fields['oblivion_shard']['raw'], '-1')
        self.assertIn('示例', fields['oblivion_shard']['origin'])
        for key, raw in (('wealth_bonus','1'), ('oblivion_shard','0'), ('unidentified_equipment','1'),
                         ('loot_stolen','1'), ('bounty_hunter','3'), ('preparation_level','4')):
            lookup.variables[key].set(raw)
        lookup.calculate()
        lookup.render(session.values.detail(*worker.args[1]))
        for key in ('oblivion_shard','unidentified_equipment','loot_stolen','bounty_hunter','preparation_level'):
            self.assertEqual(lookup.input_origins[key], '手填')
        self.assertTrue(lookup.save_plan('碎片普通掉落条件'))
        saved = copy.deepcopy(lookup.saved_plan)
        self.assertEqual(saved['params']['oblivion_shard'], 0)
        self.assertEqual(saved['params']['unidentified_equipment'], 1)
        self.assertEqual(saved['params']['loot_stolen'], 1)
        self.assertEqual(saved['params']['bounty_hunter'], 3)
        self.assertEqual(saved['params']['preparation_level'], 4)
        self.assertTrue(lookup.open_plan(saved['id'], False))
        self.assertEqual(lookup.calculated, saved['params'])
        self.assertEqual(lookup.input_origins['unidentified_equipment'], '手填')
        exported = session.knowledge.export()
        row = json.loads(exported)['plans'][0]
        self.assertEqual(row['params'], saved['params'])
        self.assertEqual(row['origin']['fields']['oblivion_shard'], '手填')
        target_path = directory/'target'/'settings.json'
        target_path.parent.mkdir()
        target_path.write_bytes(settings.read_bytes())
        target = Session(target_path, session.catalog)
        self.assertEqual(target.knowledge.import_records(exported)['plans_added'], 1)
        reopened = target.knowledge.reopen(saved['id'])
        self.assertEqual(reopened['plan']['params'], saved['params'])
        meat = next(row for row in reopened['result']['blocks'][1]['rows'] if row[0] == '神秘的肉')
        self.assertEqual(meat[2], '0%')
        armor = [r for r in reopened['result']['blocks'][1]['rows'] if '额外固定获得一件护甲' in r[3]]
        self.assertAlmostEqual(sum(float(r[2].removesuffix('%')) for r in armor), 100)
        self.assertEqual(marker.read_bytes(), b'synthetic-save-preserved\x00\xff')
        session.stop.set()
        target.stop.set()


if __name__ == '__main__':
    unittest.main()
