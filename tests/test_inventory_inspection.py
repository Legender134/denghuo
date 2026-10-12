"""One-item opt-in disclosure, save consistency and real HTTP authorization."""
import copy
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler

from companion.engine import Catalog, PREFIX, analyze
from companion.inventory_inspection import inspect_item, snapshot_token
from companion.scouting import ScoutingConflict
from companion.service import Session


def item(kind, **fields):
    return {'__className': PREFIX+'items.'+kind, 'quantity': 1, 'level': 0,
            'levelKnown': False, 'cursedKnown': False, **fields}


class InventoryInspectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base/'saves'
        self.slot = self.root/'game1'
        self.slot.mkdir(parents=True)
        self.game = {'version': 922, 'depth': 4, 'branch': 0, 'seed': 1234,
            'hero': {'class': 'WARRIOR', 'HP': 20, 'HT': 30, 'STR': 12, 'lvl': 5,
                     'pos': 6, 'buffs': [], 'inventory': [
                item('potions.PotionOfHealing'),
                item('weapon.melee.Spear', level=2, cursed=True),
                item('bags.VelvetPouch', inventory=[item('scrolls.ScrollOfUpgrade')]),
                item('wands.WandOfMagicMissile', level=3, levelKnown=True,
                     cursedKnown=True, curCharges=2, curChargeKnown=False)]}}
        self.save()
        self.config = self.base/'settings.json'
        self.config.write_text(json.dumps({'save_root': str(self.root), 'slot': 1,
                                          'reveal': False}), encoding='utf-8')
        self.session = Session(self.config, catalog=self.catalog)
        self.session.refresh()
        self.assertIsNone(self.session.error or None)

    def save(self):
        (self.slot/'game.dat').write_text(json.dumps(self.game), encoding='utf-8')

    def request(self, index=0):
        return {'expected': snapshot_token(self.session), 'instance_key': f'item-{index}',
                'reveal': True}

    def test_unknown_identity_and_nested_item_are_selected_without_global_disclosure(self):
        original = (self.slot/'game.dat').read_bytes()
        settings = self.config.read_bytes()
        before = copy.deepcopy(self.session.data)
        result = inspect_item(self.session, self.request())
        selected = result['item']
        self.assertEqual(selected['key'], 'items.potions.potionofhealing')
        self.assertTrue(selected['revealed'])
        self.assertFalse(selected['known'])
        self.assertFalse(selected['has_hidden_details'])
        self.assertEqual(result['source']['slot'], 1)
        self.assertEqual(result['source']['expected'], snapshot_token(self.session))
        self.assertNotIn('items', result)
        self.assertNotIn('Spear', json.dumps(result))
        self.assertEqual(self.session.data, before)
        self.assertFalse(self.session.settings['reveal'])
        self.assertEqual((self.slot/'game.dat').read_bytes(), original)
        self.assertEqual(self.config.read_bytes(), settings)
        nested = next(row for row in self.session.data['items'] if row['location']=='收纳袋')
        result = inspect_item(self.session, {**self.request(), 'instance_key': nested['instance_key']})
        self.assertEqual(result['item']['key'], 'items.scrolls.scrollofupgrade')
        self.assertEqual(result['item']['location'], nested['location'])

    def test_known_type_can_reveal_level_curse_and_unknown_wand_charge(self):
        spear = self.session.data['items'][1]
        self.assertTrue(spear['known'])
        self.assertTrue(spear['has_hidden_details'])
        self.assertIsNone(spear['level'])
        selected = inspect_item(self.session, self.request(1))['item']
        self.assertEqual(selected['level'], 2)
        self.assertTrue(selected['cursed'])
        self.assertFalse(selected['game_level_known'])
        self.assertFalse(selected['game_curse_known'])
        wand = self.session.data['items'][-1]
        self.assertTrue(wand['known'])
        self.assertTrue(wand['has_hidden_details'])
        selected = inspect_item(self.session, {**self.request(), 'instance_key': wand['instance_key']})['item']
        self.assertIn('2 次充能', selected['details'])

    def test_lost_inventory_availability_is_preserved(self):
        self.game['hero']['buffs'] = [{'__className': PREFIX+'actors.buffs.LostInventory'}]
        self.save()
        self.session.refresh()
        selected = inspect_item(self.session, self.request(1))['item']
        self.assertFalse(selected['available'])
        self.assertIn('遗落行囊：未确认可用', selected['details'])

    def test_no_disclosure_marker_for_fully_known_item_or_identified_consumable(self):
        self.game['hero']['inventory'] = [item('weapon.melee.Sword', levelKnown=True, cursedKnown=True)]
        rows = analyze(self.game, self.catalog)['items']
        self.assertFalse(rows[0]['has_hidden_details'])
        self.assertTrue(analyze(self.game, self.catalog, reveal=True)['items'][0]['revealed'])
        self.game['PotionOfHealing_known'] = True
        self.game['hero']['inventory'] = [item('potions.PotionOfHealing')]
        self.assertFalse(analyze(self.game, self.catalog)['items'][0]['has_hidden_details'])

    def test_supported_versions_read_the_same_selected_instance(self):
        for version in (920, 922):
            self.game['version'] = version
            self.save()
            self.session.refresh()
            with self.subTest(version=version):
                self.assertEqual(inspect_item(self.session, self.request(1))['item']['level'], 2)

    def test_strict_confirmation_and_instance_format_fail_before_file_io(self):
        payloads = [None, {}, {**self.request(), 'reveal': False},
                    {**self.request(), 'reveal': 1}, {**self.request(), 'extra': True},
                    {**self.request(), 'instance_key': 'item-01'},
                    {**self.request(), 'instance_key': 'item--1'},
                    {**self.request(), 'expected': 'not-a-snapshot'}]
        with patch('companion.inventory_inspection.read_slot') as read:
            for payload in payloads:
                with self.subTest(payload=payload), self.assertRaises(ValueError):
                    inspect_item(self.session, payload)
            read.assert_not_called()
        with self.assertRaises(ValueError):
            inspect_item(self.session, self.request(9999))

    def test_file_change_before_poll_invalidates_snapshot_even_with_same_metadata(self):
        request = self.request()
        path = self.slot/'game.dat'
        stamp = path.stat()
        self.game['hero']['HP'] = 21
        self.save()
        os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        with self.assertRaises(ScoutingConflict):
            inspect_item(self.session, request)

    def test_change_during_projection_invalidates_response(self):
        actual = analyze
        def change(*args, **kwargs):
            result = actual(*args, **kwargs)
            self.game['hero']['HP'] = 21
            self.save()
            return result
        with patch('companion.inventory_inspection.analyze', side_effect=change):
            with self.assertRaises(ScoutingConflict):
                inspect_item(self.session, self.request())

    def test_connection_change_closure_and_manual_mode_reject_old_selection(self):
        request = self.request()
        self.session.update_settings({'always_on_top': True})
        with self.assertRaises(ScoutingConflict):
            inspect_item(self.session, request)
        self.session.stop.set()
        self.assertIsNone(snapshot_token(self.session))
        with self.assertRaises(ScoutingConflict):
            inspect_item(self.session, request)
        self.session.stop.clear()
        self.session.settings['mode'] = 'manual'
        self.assertIsNone(snapshot_token(self.session))

    def test_unsupported_versions_do_not_guess_hidden_values(self):
        for version in (919, 923):
            self.game['version'] = version
            self.save()
            self.session.refresh()
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, '版本'):
                inspect_item(self.session, self.request())

    def test_real_http_auth_explicit_opt_in_stale_conflict_and_single_item_response(self):
        from companion.server import Server
        server = Server(self.session)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        opener = build_opener(ProxyHandler({}))
        def send(payload, expected=200, authorized=True):
            headers = {'Content-Type': 'application/json', 'Origin': server.origin}
            if authorized:
                headers['X-Companion-Token'] = server.token
            request = Request(server.origin+'/api/inventory/reveal',
                              data=json.dumps(payload).encode(), headers=headers)
            try:
                with opener.open(request, timeout=5) as response:
                    status, raw = response.status, response.read()
            except HTTPError as exc:
                status, raw = exc.code, exc.read()
            self.assertEqual(status, expected, raw)
            return json.loads(raw)
        try:
            request = self.request()
            send(request, 403, False)
            send({**request, 'reveal': False}, 400)
            result = send(request)
            self.assertEqual(result['item']['key'], 'items.potions.potionofhealing')
            self.assertEqual(set(result), {'item', 'source', 'revealed', 'note'})
            self.game['hero']['HP'] = 21
            self.save()
            send(request, 409)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(5)
            self.assertFalse(thread.is_alive())
