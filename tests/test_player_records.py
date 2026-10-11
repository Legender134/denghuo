"""Player records and public status identity across existing read-only entry points."""
import copy
from types import SimpleNamespace
import unittest

from companion.decisions import context_actions
from companion.engine import Catalog, PREFIX, analyze
from companion.workspace_service import workspace_status


class PlayerRecordsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def game(self):
        return {'hero': {'class': 'WARRIOR', 'lvl': 5, 'STR': 14, 'HP': 35, 'HT': 40,
                         'inventory': [], 'buffs': []}, 'depth': 4, 'version': 918}

    def record(self, title, body='', **fields):
        return {'__className': PREFIX + 'journal.Notes$CustomRecord', 'type': 'SPECIFIC_ITEM',
                'title': title, 'body': body, **fields}

    def session(self, game, reveal=False):
        snapshot = {'data': analyze(game, self.catalog, reveal=reveal), 'settings': {'mode': 'save', 'save_root': '/synthetic'},
                    'started': 1, 'active_slot': 1, 'revision': 1, 'modified': 1}
        knowledge = SimpleNamespace(generation=0, status=lambda: {'favorites': [], 'recent': [], 'plans': []})
        return SimpleNamespace(catalog=self.catalog, knowledge=knowledge, snapshot=lambda: snapshot), snapshot

    def test_explicit_reveal_opens_item_calculation_without_changing_game_knowledge(self):
        game=self.game()
        game['hero']['inventory']=[{'__className':PREFIX+'items.rings.RingOfMight','quantity':1,
            'level':3,'levelKnown':False,'cursedKnown':False,'cursed':False}]
        original=copy.deepcopy(game)
        hidden,off=self.session(game)
        self.assertFalse(off['data']['items'][0]['identity_visible'])
        self.assertNotIn('items.rings.ringofmight',[row['id'] for row in workspace_status(hidden)['current']])
        shown,on=self.session(game,reveal=True)
        item=on['data']['items'][0]
        self.assertFalse(item['known'])
        self.assertFalse(item['game_level_known'])
        self.assertTrue(item['revealed'])
        self.assertTrue(item['identity_visible'])
        self.assertEqual(item['level'],3)
        row=next(row for row in workspace_status(shown)['current'] if row['id']=='items.rings.ringofmight')
        self.assertEqual(row['lookup_context']['params']['level'],3)
        self.assertEqual(row['lookup_context']['level_origin'],'revealed')
        self.assertIn('主动揭示',row['lookup_context']['field_origins']['level'])
        from companion.rules import NumericRules
        from companion.values import PlayerValues
        result=PlayerValues(NumericRules(self.catalog)).detail(row['id'],row['lookup_context']['params'])
        self.assertTrue(result['blocks'])
        self.assertEqual(next(field['value'] for field in result['inputs'] if field['key']=='level'),3)
        self.assertEqual(game,original)
        self.assertEqual(self.session(game)[1]['data']['items'][0]['key'],'items.rings.ring')

    def test_reveal_does_not_call_unknown_consumables_identified_or_import_them_as_known_resources(self):
        game=self.game()
        game['hero'].update(HP=3,HT=40)
        game['hero']['inventory']=[{'__className':PREFIX+'items.potions.PotionOfHealing','quantity':1},
            {'__className':PREFIX+'items.potions.PotionOfStrength','quantity':1},
            {'__className':PREFIX+'items.scrolls.ScrollOfUpgrade','quantity':1}]
        shown=analyze(game,self.catalog,reveal=True)
        self.assertTrue(all(row['revealed'] and not row['known'] for row in shown['items']))
        self.assertNotIn('strength_potion',[row['id'] for row in shown['tips']])
        self.assertNotIn('upgrade_scroll',[row['id'] for row in shown['tips']])
        critical=next(row for row in shown['tips'] if row['id']=='critical_hp')
        self.assertNotIn('有已鉴定的治疗药剂',critical['body'])

    def test_exact_item_notes_distinguish_same_grade_and_survive_workspace_context(self):
        game = self.game()
        sword = {'__className': PREFIX+'items.weapon.melee.Sword', 'level': 2,
                 'levelKnown': True, 'cursedKnown': True, 'custom_note_id': 7}
        game['hero']['inventory'] = [sword, {**sword, 'custom_note_id': 8}]
        game['records'] = [self.record('保留_<剑>', '第一行\n第二行 & <不是标签>', id_number=7),
                           self.record('备用剑', id_number=8),
                           self.record('种类备注', type='ITEM_TYPE', item_class=sword['__className'])]
        original = copy.deepcopy(game)
        session, snapshot = self.session(game)
        notes = [item['user_note'] for item in snapshot['data']['items']]
        self.assertEqual([note['title'] for note in notes], ['保留_<剑>', '备用剑'])
        self.assertEqual(notes[0]['body'], '第一行\n第二行 & <不是标签>')
        self.assertEqual(notes[0]['scope'], 'specific_item')
        rows = [row for row in workspace_status(session)['current'] if row['id'] == 'items.weapon.melee.sword']
        self.assertEqual([row['lookup_context']['user_note'] for row in rows], notes)
        self.assertIn('用户记录：保留_<剑>', rows[0]['lookup_label'])
        self.assertNotIn('保留_<剑>', snapshot['data']['items'][0]['description'])
        self.assertEqual(game, original)

    def test_type_note_fallback_never_identifies_unknown_potion(self):
        game = self.game()
        potion = {'__className': PREFIX+'items.potions.PotionOfHealing', 'custom_note_id': 99}
        game['PotionOfHealing_label'] = 'crimson'
        game['records'] = [self.record('治疗药剂备忘', '隐藏种类的备注', type='ITEM_TYPE', item_class=potion['__className'])]
        self.assertIsNone(self.catalog.item(potion, game)['user_note'])
        self.assertIsNone(self.catalog.item(potion, game, reveal=True)['user_note'])
        game['PotionOfHealing_known'] = True
        self.assertEqual(self.catalog.item(potion, game)['user_note']['scope'], 'item_type')
        game['PotionOfHealing_known'] = False
        game['records'].append(self.record('我自己标记的未知药剂', id_number=99))
        item = self.catalog.item(potion, game)
        self.assertFalse(item['known'])
        self.assertEqual(item['key'], 'items.potions.potion')
        self.assertEqual(item['user_note']['title'], '我自己标记的未知药剂')
        self.assertNotIn('治疗药剂备忘', str(item))

    def test_internal_tracker_is_not_player_status_but_nested_public_status_remains(self):
        game = self.game()
        classes = ['actors.hero.Talent$CombinedEnergyAbilityTracker',
                   'actors.hero.abilities.duelist.MonkEnergy$MonkAbility$FlurryCooldownTracker',
                   'items.armor.glyphs.Viscosity$DeferedDamage',
                   'actors.hero.spells.BodyForm$BodyFormBuff', 'actors.buffs.Burning',
                   'actors.buffs.Poison', 'actors.buffs.Bleeding']
        game['hero']['buffs'] = [{'__className': PREFIX+kind} for kind in classes]
        original = copy.deepcopy(game)
        session, snapshot = self.session(game)
        buffs = snapshot['data']['buffs']
        self.assertFalse(any('Tracker' in row['kind'] or '$' in row['name'] for row in buffs))
        identities = {row['reference_id'] for row in buffs}
        self.assertEqual(identities, {kind.lower() for kind in classes[2:]})
        current = {row['id'] for row in workspace_status(session)['current']}
        self.assertTrue(identities <= current)
        risks = context_actions(session, snapshot)['risks']
        dot = next(row for row in risks if row['id'] == 'dot')
        self.assertEqual({row['entry'] for row in dot['references']},
                         {'items.armor.glyphs.viscosity$defereddamage', 'actors.buffs.poison', 'actors.buffs.bleeding'})
        self.assertEqual(game, original)


if __name__ == '__main__':
    unittest.main()
