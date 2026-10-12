"""Offline reference image provenance, identity separation and reproducibility."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMMIT = '57a4e06a4caf162446d1c28caa7983f0493fecf0'
UPSTREAM = Path(os.environ.get('DENGHUO_UPSTREAM_SOURCE', str(
    ROOT / '.local/polish/round-34-candidate/c/external/game' / ('shattered-pixel-dungeon-'+COMMIT))))
PIL_AVAILABLE = importlib.util.find_spec('PIL') is not None


class ReferenceImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((ROOT / 'data/reference_images.json').read_text(encoding='utf-8'))
        cls.entries = cls.manifest['entries']

    def test_manifest_paths_hashes_and_transparent_png_headers(self):
        self.assertEqual(self.manifest['commit'], COMMIT)
        urls = set()
        for key, row in self.entries.items():
            with self.subTest(key=key):
                self.assertRegex(row['url'], r'^/reference-images/[a-zA-Z0-9_.-]+\.png$')
                self.assertNotIn(row['url'], urls)
                urls.add(row['url'])
                raw = (ROOT / 'web' / row['url'].lstrip('/')).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), row['sha256'])
                self.assertEqual(raw[:8], b'\x89PNG\r\n\x1a\n')
                width, height, bits, color = struct.unpack('>IIBB', raw[16:26])
                self.assertEqual((width, height), (row['width'], row['height']))
                self.assertEqual((bits, color), (8, 6))  # RGBA, no opaque flattening.
                x0, y0, x1, y1 = row['alpha_bbox']
                self.assertTrue(0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height)

    def test_complete_monster_roster_and_explicit_representative_variants(self):
        monsters = json.loads((ROOT / 'data/monster_reference.json').read_text(encoding='utf-8'))
        roster = {key for group in monsters['bestiary_groups'].values() for key in group}
        self.assertEqual(len(roster), 85)
        self.assertEqual(len(monsters['monsters']), 104)
        self.assertFalse(roster - self.entries.keys())
        self.assertFalse(monsters['monsters'].keys() - self.entries.keys())
        for key in ('actors.mobs.shaman', 'actors.mobs.crystalwisp', 'actors.mobs.crystalguardian',
                    'actors.mobs.crystalspire', 'actors.mobs.quest.vault.vaultbosselemental',
                    'actors.mobs.necromancer$necroskeleton'):
            self.assertEqual(self.entries[key]['kind'], 'representative-sprite')
            self.assertTrue(self.entries[key]['source']['note'])

    def test_randomized_appearance_is_separate_from_known_effect_identity(self):
        for key, symbol in [('unknown.potion', 'POTION_HOLDER'), ('unknown.scroll', 'SCROLL_HOLDER'),
                            ('unknown.ring', 'RING_HOLDER'), ('unknown.item', 'SOMETHING')]:
            self.assertEqual(self.entries[key]['kind'], 'placeholder')
            self.assertEqual(self.entries[key]['source']['symbol'], 'ItemSpriteSheet.'+symbol)
            self.assertNotIn('class', self.entries[key]['source'])
        known = self.entries['items.potions.potionofhealing']
        self.assertEqual(known['kind'], 'identity-icon')
        self.assertIn('效果图标', known['alt'])
        for category in ('potion', 'scroll', 'ring', 'exotic-potion', 'exotic-scroll'):
            rows = {key: row for key, row in self.entries.items() if key.startswith('appearance.'+category+'.')}
            self.assertEqual(len(rows), 12)
            for key, row in rows.items():
                self.assertEqual(row['kind'], 'public-appearance')
                self.assertEqual(key.rsplit('.', 1)[-1], row['source']['label'].lower())
                self.assertNotIn('class', row['source'])
        ordinary = self.entries['appearance.potion.ivory']['source']['rect']
        exotic = self.entries['appearance.exotic-potion.ivory']['source']['rect']
        self.assertEqual(exotic[:2], [ordinary[0], ordinary[1]+16])
        self.assertNotEqual(ordinary, exotic)

    @unittest.skipUnless(UPSTREAM.is_dir(), 'Pinned upstream checkout is not present')
    def test_recorded_official_source_hashes(self):
        for path, digest in self.manifest['sources'].items():
            with self.subTest(path=path):
                self.assertEqual(hashlib.sha256((UPSTREAM / path).read_bytes()).hexdigest(), digest)

    @unittest.skipUnless(UPSTREAM.is_dir() and PIL_AVAILABLE, 'Offline crop oracle needs pinned upstream and existing Pillow')
    def test_every_image_is_the_exact_unscaled_official_frame(self):
        from PIL import Image
        atlases = {}
        for key, row in self.entries.items():
            with self.subTest(key=key):
                path = row['source']['atlas']
                if path not in atlases:
                    with Image.open(UPSTREAM / path) as image:
                        atlases[path] = image.convert('RGBA')
                atlas = atlases[path]
                x0, y0, x1, y1 = row['source']['rect']
                self.assertTrue(0 <= x0 < x1 <= atlas.width and 0 <= y0 < y1 <= atlas.height)
                expected = atlas.crop((x0, y0, x1, y1))
                with Image.open(ROOT / 'web' / row['url'].lstrip('/')) as actual:
                    self.assertEqual(actual.convert('RGBA').tobytes(), expected.tobytes())
                    self.assertEqual(list(actual.getchannel('A').getbbox()), row['alpha_bbox'])
        # Independent coordinates traced to RatSprite/FetidRatSprite/Sword and
        # the healing identity icon, covering frame indexing and both atlas grids.
        for key, rect in [('actors.mobs.rat', [0, 0, 16, 15]),
                          ('actors.mobs.fetidrat', [0, 30, 16, 45]),
                          ('items.weapon.melee.sword', [0, 112, 14, 126]),
                          ('items.potions.potionofhealing', [8, 40, 14, 47])]:
            self.assertEqual(self.entries[key]['source']['rect'], rect)
        # The anonymous selector changes a *selected* spell's image; it must not
        # overwrite the class initializer's default neutral elemental spell.
        self.assertEqual(self.entries['items.spells.summonelemental']['source']['symbol'], 'ItemSpriteSheet.SUMMON_ELE')

    @unittest.skipUnless(UPSTREAM.is_dir() and PIL_AVAILABLE, 'Rebuild needs pinned upstream and existing Pillow')
    def test_two_offline_rebuilds_match_the_delivered_manifest_and_assets(self):
        from tools.build_reference_images import build
        with tempfile.TemporaryDirectory(prefix='denghuo-reference-images-') as directory:
            outputs = [Path(directory) / 'first', Path(directory) / 'second']
            first, second = [build(UPSTREAM, output) for output in outputs]
            self.assertEqual(first, second)
            self.assertEqual(first, self.manifest)
            for row in first['entries'].values():
                filename = row['url'].rsplit('/', 1)[-1]
                self.assertEqual((outputs[0] / filename).read_bytes(), (outputs[1] / filename).read_bytes())


if __name__ == '__main__':
    unittest.main()
