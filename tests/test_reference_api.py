"""Real HTTP encyclopedia paths, public appearance privacy and packaged artwork."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import build_opener, ProxyHandler

from companion.engine import Catalog, PREFIX
from companion.reference import entry, image_path, images
from companion.server import Server
from companion.service import Session


class ReferenceAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def test_randomized_public_appearance_does_not_disclose_effect(self):
        item = {'__className': PREFIX + 'items.potions.PotionOfHealing', 'quantity': 1}
        row = self.catalog.item(item, {'PotionOfHealing_label': 'ivory'})
        self.assertEqual(row['appearance_id'], 'appearance.potion.ivory')
        self.assertEqual(row['key'], 'items.potions.potion')
        self.assertNotIn('potionofhealing', json.dumps(row).lower())
        scroll = {'__className': PREFIX + 'items.scrolls.ScrollOfUpgrade', 'quantity': 1}
        row = self.catalog.item(scroll, {'ScrollOfUpgrade_label': 'KAUNAN'})
        self.assertEqual(row['appearance_id'], 'appearance.scroll.kaunan')

    def test_enemy_encyclopedia_has_description_image_and_public_encounters(self):
        row = entry(self.catalog, 'actors.mobs.rat')
        self.assertIn('弱者', row['description'])
        self.assertTrue(row['image']['url'].startswith('/reference-images/'))
        self.assertTrue(any(r['depth'] == 1 for r in row['encounters']))
        self.assertIn('不是本局', row['encounter_note'])
        summoned = entry(self.catalog, 'actors.mobs.dwarfking$dkghoul')
        self.assertEqual(summoned['description'], self.catalog.entry_index['actors.mobs.ghoul']['description'])

    def test_unknown_and_unlisted_artwork_paths_are_rejected(self):
        for url in ('/reference-images/../app.js', '/reference-images/missing.png',
                    '/reference-images/%2e%2e/app.js', '/reference-images/sub/item.png'):
            with self.subTest(url=url), self.assertRaises(KeyError):
                image_path(url)

    def test_real_http_offline_image_and_reference_routes(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            config = base / 'settings.json'
            config.write_text(json.dumps({'save_root': str(base / 'saves'), 'slot': 1, 'mode': 'manual'}))
            session = Session(config, catalog=self.catalog)
            server = Server(session)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            opener = build_opener(ProxyHandler({}))
            try:
                with opener.open(server.origin + '/api/reference?id=actors.mobs.rat') as response:
                    row = json.load(response)
                with opener.open(server.origin + row['image']['url']) as response:
                    self.assertEqual(response.headers['Content-Type'], 'image/png')
                    self.assertEqual(response.read()[:8], b'\x89PNG\r\n\x1a\n')
                for suffix in ('/api/reference?id=missing', '/reference-images/../app.js'):
                    with self.subTest(suffix=suffix), self.assertRaises(HTTPError) as error:
                        opener.open(server.origin + suffix)
                    self.assertEqual(error.exception.code, 404)
                with opener.open(server.origin + '/references.js') as response:
                    self.assertIn(b'publicReferenceId', response.read())
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)


if __name__ == '__main__':
    unittest.main()
