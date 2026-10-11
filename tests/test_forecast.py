"""Forecast source integrity, explicit seed handoff and unchanged save bytes."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, build_opener

from companion.engine import Catalog, ROOT
from companion.forecast import TOTAL_SEEDS, information, read_seed, seed_text
from companion.saves import SaveError
from companion.scouting import ScoutingConflict
from companion.service import Session
from tools.build_forecast import extract


class ForecastTests(unittest.TestCase):
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
        self.game = {'version': 922, 'depth': 4, 'branch': 0, 'seed': 1234, 'challenges': 32,
                     'hero': {'class': 'MAGE', 'HP': 20, 'HT': 30, 'STR': 12, 'lvl': 5}}
        self.save()
        config = self.base/'settings.json'
        config.write_text(json.dumps({'save_root': str(self.root), 'slot': 1}), encoding='utf-8')
        self.session = Session(config, catalog=self.catalog)
        self.session.refresh()

    def save(self):
        (self.slot/'game.dat').write_text(json.dumps(self.game), encoding='utf-8')

    def test_seed_codes_daily_identity_and_invalid_ranges(self):
        self.assertEqual(seed_text(0), 'AAA-AAA-AAA')
        self.assertEqual(seed_text(TOTAL_SEEDS-1), 'ZZZ-ZZZ-ZZZ')
        self.assertEqual(seed_text(TOTAL_SEEDS), '1970-01-01')
        self.assertEqual(seed_text(TOTAL_SEEDS+1_791_676_800_000), '2026-10-11')
        self.assertEqual(seed_text(TOTAL_SEEDS+253402214400000), '9999-12-31')
        for raw in [None, True, -1, '1234', 1.0, TOTAL_SEEDS+1, TOTAL_SEEDS+253402300800000, 2**64-1]:
            with self.subTest(raw=raw), self.assertRaises(SaveError):
                seed_text(raw)

    def test_only_explicit_opt_in_reads_seed_and_reports_actual_source(self):
        path = self.slot/'game.dat'
        before = path.read_bytes()
        for payload in [{}, {'action':'seed'}, {'action':'seed','reveal':False}, {'action':'seed','reveal':1},
                        {'action':'seed','reveal':True,'extra':1}]:
            with self.assertRaises(ValueError):
                read_seed(self.session, payload)
        value = read_seed(self.session, {'action':'seed','reveal':True})
        self.assertEqual(value['seed'], '1234')
        self.assertEqual(value['source']['hero_class'], 'MAGE')
        self.assertEqual(value['source']['challenges'], 32)
        self.assertFalse(value['actual_future_supported'])
        self.assertIn('不可作为本局未来的确定结果', value['note'])
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(value['source']['sha256'], hashlib.sha256(before).hexdigest())

    def test_unknown_version_manual_mode_and_changing_same_stat_source_rejected(self):
        self.game['version'] = 924
        self.save()
        with self.assertRaises(SaveError):
            read_seed(self.session, {'action':'seed','reveal':True})
        self.game['version'] = 920
        self.save()
        self.assertEqual(read_seed(self.session, {'action':'seed','reveal':True})['source']['version_name'], '4.0.1')
        self.session.settings['mode'] = 'manual'
        with self.assertRaises(ValueError):
            read_seed(self.session, {'action':'seed','reveal':True})
        self.session.settings['mode'] = 'save'
        from companion.forecast import read_snapshot
        def changed(path):
            result = read_snapshot(path)
            self.game['seed'] = 4321
            before = path.stat()
            self.save()
            os.utime(path, ns=(before.st_atime_ns,before.st_mtime_ns))
            return result
        with patch('companion.forecast.read_snapshot', side_effect=changed), self.assertRaises(ScoutingConflict):
            read_seed(self.session, {'action':'seed','reveal':True})

    def test_context_changed_during_seed_handoff_rejected(self):
        from companion.forecast import read_snapshot
        def changed(path):
            result = read_snapshot(path)
            self.session.active_slot = 2
            return result
        with patch('companion.forecast.read_snapshot', side_effect=changed), self.assertRaises(ScoutingConflict):
            read_seed(self.session, {'action':'seed','reveal':True})

    def test_all_supported_definitions_resolve_to_catalog_and_bundled_source_matches(self):
        info = information(self.catalog)
        self.assertEqual(info['game_version'], '4.0.2')
        self.assertEqual(len(info['items']), 117)
        self.assertEqual(len({row['id'] for row in info['items']}), 117)
        self.assertTrue(all(row['key'] in self.catalog.entry_index and row['name'] and row['description'] for row in info['items']))
        self.assertTrue(info['effects']['Weapon'].get('blazing'))
        receipt = extract(self.base/'source')
        self.assertEqual(receipt['wasm_sha256'], hashlib.sha256((ROOT/'web/forecast.wasm').read_bytes()).hexdigest())
        self.assertEqual(receipt['game_commit'], '57a4e06a4caf162446d1c28caa7983f0493fecf0')
        self.assertTrue((self.base/'source/crates/denghuo-forecast/src/lib.rs').is_file())
        self.assertTrue((self.base/'source/COPYING').is_file())
        # The exact locked dependency notices travel with both runtime assets
        # and corresponding source, rather than depending on Cargo being online.
        import re
        from tools.build_release import FILES
        notices=(ROOT/'third_party/seed_seeker/CARGO-NOTICES.txt').read_bytes()
        self.assertEqual((self.base/'source/CARGO-NOTICES.txt').read_bytes(),notices)
        locked=(self.base/'source/Cargo.lock').read_text(encoding='utf-8')
        packages=[]
        for section in locked.split('[[package]]')[1:]:
            if 'registry+https://github.com/rust-lang/crates.io-index' not in section:continue
            name=re.search(r'^name = "([^"]+)"',section,re.M).group(1)
            version=re.search(r'^version = "([^"]+)"',section,re.M).group(1)
            checksum=re.search(r'^checksum = "([^"]+)"',section,re.M).group(1)
            packages.append((name,version))
            self.assertIn(f'{name} {version} - '.encode(),notices)
            self.assertIn(f'Package SHA-256: {checksum}'.encode(),notices)
        self.assertEqual(len(packages),13)
        self.assertIn(b'unicode-ident 1.0.24 - LICENSE-UNICODE',notices)
        self.assertIn('third_party/seed_seeker/CARGO-NOTICES.txt',FILES)
        copyright=(self.base/'source/rust-runtime/COPYRIGHT-library.html').read_text(encoding='utf-8')
        for relative in re.findall(r'href="(licenses/[^"#?]+\.txt)"',copyright):
            self.assertTrue((self.base/'source/rust-runtime'/relative).is_file(),relative)

    def test_actual_http_opt_in_and_correct_wasm_mime_and_policy(self):
        from companion.server import Server
        server = Server(self.session)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        opener = build_opener(ProxyHandler({}))
        before = (self.slot/'game.dat').read_bytes()
        def request(path, data=None, token=True):
            return opener.open(Request(server.origin+path, data=None if data is None else json.dumps(data).encode(),
                                      headers={'Content-Type':'application/json', **({'X-Companion-Token':server.token} if token else {})}), timeout=5)
        with self.assertRaises(HTTPError) as caught:
            request('/api/forecast', {'action':'seed','reveal':True}, token=False)
        self.assertEqual(caught.exception.code,403)
        with self.assertRaises(HTTPError) as caught:
            request('/api/forecast', {'action':'seed'})
        self.assertEqual(caught.exception.code,400)
        with request('/api/forecast') as response:
            info = json.load(response)
        self.assertNotIn('seed',info)
        with request('/api/forecast', {'action':'seed','reveal':True}) as response:
            self.assertEqual(json.load(response)['seed'], '1234')
        with request('/forecast.wasm') as response:
            self.assertEqual(response.headers.get_content_type(),'application/wasm')
            self.assertIn("'wasm-unsafe-eval'",response.headers['Content-Security-Policy'])
            self.assertNotIn("'unsafe-eval'",response.headers['Content-Security-Policy'])
            self.assertEqual(response.read()[:4],b'\0asm')
        self.assertEqual((self.slot/'game.dat').read_bytes(),before)
