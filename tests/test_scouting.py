"""Opt-in floor facts, snapshot consistency, bounds and actual HTTP behavior."""
import copy
import gzip
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler

from companion.engine import PREFIX, Catalog
from companion.scouting import ScoutingConflict, inspect_saved, project_floor
from companion.saves import SaveError
from companion.service import Session


def item(kind, **fields):
    return {'__className': PREFIX+'items.'+kind, 'quantity': 1, 'level': 0,
            'levelKnown': False, 'cursedKnown': False, **fields}


class ScoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base/'saves'
        self.slot = self.root/'game1'
        self.slot.mkdir(parents=True)
        self.game = {'version': 922, 'depth': 4, 'branch': 0, 'seed': 1234,
            'generated_levels': [3, 4, 1004], 'hero': {'class': 'WARRIOR', 'HP': 20,
            'HT': 30, 'STR': 12, 'lvl': 5, 'pos': 6, 'buffs': [], 'inventory': []}}
        self.level = {'__className': PREFIX+'levels.SewerLevel', 'version': 922,
            'width': 4, 'height': 3, 'map': [4,16,4,4,1,17,1,8,1,1,29,7],
            'visited': [False]*12, 'mapped': [False]*12,
            'heaps': [{'type': 'LOCKED_CHEST', 'pos': 8, 'seen': False, 'hidden': True,
                'items': [item('weapon.melee.Sword', level=3, cursed=True),item('potions.PotionOfHealing')]}],
            'traps': [{'__className': PREFIX+'levels.traps.PoisonTrap', 'pos': 5, 'visible': False, 'active': True}],
            'mobs': [{'__className': PREFIX+'actors.mobs.GoldenMimic', 'pos': 9, 'HP': 22, 'HT': 36,
                       'items': [item('rings.RingOfMight', level=2)]},
                     {'__className': PREFIX+'actors.mobs.ArmoredStatue', 'pos': 10,
                       'weapon': item('weapon.melee.Sword',level=1),'armor':item('armor.ScaleArmor')},
                     {'__className': PREFIX+'actors.mobs.Thief', 'pos': 4, 'item':item('scrolls.ScrollOfUpgrade')} ]}
        self.save()
        config = self.base/'settings.json'
        config.write_text(json.dumps({'save_root': str(self.root), 'slot': 1, 'reveal': False}), encoding='utf-8')
        self.session = Session(config, catalog=self.catalog)
        self.session.refresh()

    def save(self):
        (self.slot/'game.dat').write_text(json.dumps(self.game), encoding='utf-8')
        self.write_floor(4, 0, self.level)
        self.write_floor(3, 0, self.level)
        self.write_floor(4, 1, self.level)
        self.write_floor(5, 0, self.level)  # stray file: not part of generated_levels
        now = (self.slot/'game.dat').stat().st_mtime_ns
        os.utime(self.slot/'depth4.dat', ns=(now+100000, now+100000))
        os.utime(self.slot/'depth3.dat', ns=(now-20_000_000_000, now-20_000_000_000))

    def write_floor(self, depth, branch, level):
        name = f'depth{depth}'+(f'-branch{branch}' if branch else '')+'.dat'
        (self.slot/name).write_bytes(gzip.compress(json.dumps({'level': level}).encode()))

    def request(self, depth=4, branch=0, **patches):
        catalog = inspect_saved(self.session, {'action': 'catalog'})
        return {'action': 'floor', 'depth': depth, 'branch': branch,
                'expected': catalog['source']['expected'], 'reveal': True, **patches}

    def tree(self):
        return {p.name:p.read_bytes() for p in self.slot.iterdir()}

    def test_catalog_has_only_generated_floors_and_never_returns_hidden_contents(self):
        original = self.tree()
        result = inspect_saved(self.session, {'action': 'catalog'})
        self.assertEqual([(r['depth'],r['branch']) for r in result['floors']], [(3,0),(4,0),(4,1)])
        self.assertNotIn('heaps', json.dumps(result))
        self.assertNotIn('RingOfMight', json.dumps(result))
        self.assertTrue(result['supported'])
        self.assertEqual(result['source']['slot'],1)
        self.assertEqual(self.tree(),original)
        self.assertFalse(self.session.settings['reveal'])

    def test_solid_non_wall_obstacles_have_named_coordinates(self):
        self.level['map']=[1,13,23,25,26,27,28,33,34,35,36,39]
        self.save()
        result=inspect_saved(self.session,self.request())
        obstacles={r['terrain']:r for r in result['features']}
        self.assertEqual(obstacles[13]['name'],'路障')
        self.assertEqual((obstacles[13]['x'],obstacles[13]['y']),(2,1))
        self.assertEqual(obstacles[27]['name'],'书架')
        self.assertEqual(obstacles[35]['name'],'矿晶')
        self.assertEqual(obstacles[39]['name'],'水中实心装饰')

    def test_explicit_reveal_shows_secrets_traps_exact_contents_and_keeps_game_knowledge(self):
        original = self.tree()
        result = inspect_saved(self.session,self.request())
        self.assertEqual(result['map']['tiles'], self.level['map'])
        self.assertEqual(result['map']['hero'],6)
        hidden = [r for r in result['features'] if r['hidden']]
        self.assertEqual([(r['x'],r['y'],r['name']) for r in hidden], [(2,1,'隐藏门'),(2,2,'隐藏陷阱')])
        self.assertEqual(result['traps'][0]['id'],'levels.traps.poisontrap')
        self.assertFalse(result['traps'][0]['visible'])
        self.assertEqual(result['heaps'][0]['items'][0]['level'],3)
        self.assertTrue(result['heaps'][0]['items'][0]['cursed'])
        potion = result['heaps'][0]['items'][1]
        self.assertEqual(potion['key'],'items.potions.potionofhealing')
        self.assertTrue(potion['revealed'])
        self.assertFalse(potion['known'])
        self.assertFalse(potion['available'])
        ring = result['mobs'][0]['items'][0]
        self.assertEqual(ring['level'],2)
        self.assertFalse(ring['known'])
        self.assertEqual(result['mobs'][0]['hp'],22)
        self.assertEqual(result['mobs'][0]['reference']['id'],'actors.mobs.goldenmimic')
        self.assertEqual(len(result['mobs'][1]['items']),2)
        self.assertEqual(result['mobs'][2]['items'][0]['key'],'items.scrolls.scrollofupgrade')
        self.assertEqual(result['item_count'],6)
        self.assertEqual(self.tree(),original)
        self.assertEqual(self.session.snapshot()['data']['items'],[])
        self.assertFalse(self.session.settings['reveal'])

    def test_saved_bag_contents_keep_individual_values_and_do_not_become_inventory(self):
        level=copy.deepcopy(self.level)
        level['heaps'][0]['items']=[item('bags.VelvetPouch',inventory=[item('rings.RingOfMight',level=3)])]
        result=project_floor(level,self.game,self.catalog,4,0)
        contents=result['heaps'][0]['items']
        self.assertEqual(len(contents),2)
        self.assertEqual(contents[1]['key'],'items.rings.ringofmight')
        self.assertEqual(contents[1]['level'],3)
        self.assertFalse(contents[1]['available'])
        self.assertNotEqual(contents[0]['instance_key'],contents[1]['instance_key'])

    def test_historical_branch_is_exact_and_old_timestamp_does_not_impersonate_current_floor(self):
        older = inspect_saved(self.session,self.request(3))
        branch = inspect_saved(self.session,self.request(4,1))
        self.assertIsNone(older['map']['hero'])
        self.assertIsNone(branch['map']['hero'])
        self.assertEqual(branch['branch'],1)
        self.assertNotEqual(older['source']['floor_modified'],branch['source']['floor_modified'])
        with self.assertRaises(SaveError):
            inspect_saved(self.session,self.request(5))

    def test_disabled_malformed_and_unknown_version_requests_never_expand_hidden_state(self):
        for changes in ({'reveal':False},{'reveal':'true'},{'depth':True},{'branch':'../'}, {'expected':0}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                inspect_saved(self.session,self.request(**changes))
        with self.assertRaises(ValueError):
            inspect_saved(self.session,{'action':'catalog','reveal':True})
        self.game['version']=999
        self.save()
        listing=inspect_saved(self.session,{'action':'catalog'})
        self.assertFalse(listing['supported'])
        with self.assertRaisesRegex(SaveError,'版本尚未支持'):
            inspect_saved(self.session,self.request())
        self.session.settings['mode']='manual'
        with self.assertRaisesRegex(ValueError,'手动局势'):
            inspect_saved(self.session,{'action':'catalog'})

    def test_supported_401_and_402_preserve_exact_saved_facts(self):
        for version in (920,922):
            self.game['version']=self.level['version']=version
            self.save()
            result=inspect_saved(self.session,self.request())
            self.assertEqual(result['source']['version'],version)
            self.assertEqual(result['heaps'][0]['items'][0]['level'],3)

    def test_game_and_connection_changes_invalidate_old_selection(self):
        request=self.request()
        self.game['hero']['HP']=21
        self.save()
        with self.assertRaises(ScoutingConflict):
            inspect_saved(self.session,request)
        request=self.request()
        self.session.update_settings({'always_on_top':True})
        with self.assertRaises(ScoutingConflict):
            inspect_saved(self.session,request)

    def test_changes_during_projection_are_detected_even_with_identical_file_metadata(self):
        actual=project_floor
        for target in ('game.dat','depth4.dat'):
            request=self.request()
            path=self.slot/target
            stat=path.stat()
            raw=path.read_bytes()
            def mutate(*args):
                result=actual(*args)
                if target=='game.dat':
                    changed=raw.replace(b'"HP": 20',b'"HP": 21')
                else:
                    body=gzip.decompress(raw).replace(b'"level": 3',b'"level": 4')
                    changed=gzip.compress(body)
                path.write_bytes(changed)
                os.utime(path,ns=(stat.st_atime_ns,stat.st_mtime_ns))
                return result
            with patch('companion.scouting.project_floor',side_effect=mutate),self.assertRaises(ScoutingConflict):
                inspect_saved(self.session,request)
            path.write_bytes(raw)
            os.utime(path,ns=(stat.st_atime_ns,stat.st_mtime_ns))

    def test_invalid_floor_coordinates_arrays_and_container_formats_fail_closed(self):
        for mutate in (lambda level:level['heaps'][0].update(pos=-1),
                       lambda level:level['traps'][0].update(pos=True),
                       lambda level:level['heaps'][0].update(type=[]),
                       lambda level:level['map'].pop(),
                       lambda level:level['heaps'][0].update(seen='yes'),
                       lambda level:level['mobs'][0].update(items=[{}])):
            level=copy.deepcopy(self.level)
            mutate(level)
            with self.assertRaises(SaveError):
                project_floor(level,self.game,self.catalog,4,0)

    def test_actual_http_requires_token_and_explicit_opt_in_and_rejects_stale_selection(self):
        from companion.server import Server
        server=Server(self.session)
        thread=threading.Thread(target=server.serve_forever)
        thread.start()
        opener=build_opener(ProxyHandler({}))
        original=self.tree()
        def send(payload,status=200,authorized=True):
            headers={'Content-Type':'application/json','Origin':server.origin}
            if authorized:headers['X-Companion-Token']=server.token
            request=Request(server.origin+'/api/scouting',data=json.dumps(payload).encode(),headers=headers)
            try:
                with opener.open(request,timeout=5) as response: code,raw=response.status,response.read()
            except HTTPError as exc:code,raw=exc.code,exc.read()
            self.assertEqual(code,status,raw)
            return json.loads(raw)
        try:
            send({'action':'catalog'},403,False)
            listing=send({'action':'catalog'})
            self.assertEqual(listing['source']['hero_level'],5)
            self.assertIn('actors.mobs.crab',[r['id'] for r in listing['encounters']['rows']])
            # Conditional room possibilities are public rules. They must not
            # expose the saved mimic's current HP, position or held ring.
            mimic=next(r for r in listing['encounters']['rows'] if r['id']=='actors.mobs.goldenmimic')
            self.assertEqual(mimic['group'],'特殊房间')
            self.assertEqual(mimic['hp'],'36')
            self.assertNotEqual(mimic['hp'],str(self.level['mobs'][0]['HP']))
            self.assertTrue({'pos','items','reference'}.isdisjoint(mimic))
            self.assertNotIn('mobs',listing)
            self.assertNotIn('features',listing)
            self.assertNotIn('heaps',listing)
            request={'action':'floor','depth':4,'branch':0,'expected':listing['source']['expected'],'reveal':True}
            send({**request,'reveal':False},400)
            result=send(request)
            self.assertEqual(result['item_count'],6)
            self.assertEqual(self.tree(),original)
            self.game['hero']['HP']=21
            self.save()
            send(request,409)
        finally:
            server.shutdown();server.server_close();thread.join(5)
            self.assertFalse(thread.is_alive())
