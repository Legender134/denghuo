"""Official map art stays tied to the masked saved map."""
import base64
import hashlib
import json
import unittest
from pathlib import Path

from companion.map_art import ROOT, image_data, terrain_art, theme_for
from companion.scouting import map_view


class OfficialMapArtTests(unittest.TestCase):
    def test_atlases_match_pinned_manifest(self):
        manifest = json.loads((ROOT / 'data/map_atlas.json').read_text(encoding='utf8'))
        self.assertEqual(manifest['commit'], '57a4e06a4caf162446d1c28caa7983f0493fecf0')
        for filename, sha in manifest['files'].items():
            self.assertEqual(hashlib.sha256(base64.b64decode(image_data(filename))).hexdigest(), sha)

    def test_region_and_direct_tiles(self):
        self.assertEqual(theme_for({'__className': 'levels.LastShopLevel'}, 21), 'city')
        self.assertEqual(theme_for({'__className': 'levels.SewerLevel'}, 1), 'sewers')
        art = terrain_art({'width': 4, 'height': 2, 'theme': 'sewers',
                           'tiles': [-1, 4, 1, 7, 8, 15, 16, 29]}, 1)
        self.assertEqual(art['frames'][:7], [-1, 48, 0, 16, 17, 66, 48])
        self.assertTrue(art['atlas'])

    def test_water_edges_only_use_visible_neighbours(self):
        masked = {'width': 3, 'height': 1, 'tiles': [-1, 29, -1]}
        visible = {'width': 3, 'height': 1, 'tiles': [1, 29, -1]}
        self.assertEqual(terrain_art(masked)['frames'][1], 32)
        self.assertEqual(terrain_art(visible)['frames'][1], 40)

    def test_deep_walls_are_background_without_changing_cell_data(self):
        tiles = [4] * 25
        tiles[0] = 1
        tiles[24] = 16
        art = terrain_art({'width': 5, 'height': 5, 'tiles': tiles})
        self.assertEqual(art['frames'][12], -2)
        self.assertEqual(art['frames'][6], 48)
        self.assertEqual(art['frames'][24], 48)
        self.assertEqual(tiles[12], 4)
        unknown = terrain_art({'width': 3, 'height': 1, 'tiles': [4, 4, -1]})
        self.assertEqual(unknown['frames'][:2], [-2, -2])

    def test_mining_uses_quest_atlas_and_missing_type_keeps_obstacles_visible(self):
        level = {'__className': 'levels.MiningLevel'}
        self.assertEqual(theme_for(level, 12, {'quests': {'blacksmith': {'type': 1}}}), 'caves_crystal')
        self.assertEqual(theme_for(level, 12, {'quests': {'blacksmith': {'type': 2}}}), 'caves_gnoll')
        for theme in ('caves_crystal', 'caves_gnoll'):
            art = terrain_art({'width': 1, 'height': 1, 'theme': theme, 'tiles': [35]}, 12)
            self.assertEqual(art['frames'], [76])
            self.assertEqual(art['atlas'], image_data('tiles_' + theme + '.png'))
            self.assertEqual(art['water'], image_data('water2.png'))
        unknown = terrain_art({'width': 1, 'height': 1, 'theme': 'caves', 'tiles': [35]}, 12)
        self.assertEqual(unknown['frames'], [-1])

    def test_public_projection_has_no_revealed_object_art(self):
        public = map_view({'width': 2, 'height': 1, 'tiles': [-1, 1]})
        self.assertEqual(public['markers'], [])
        self.assertEqual(public['art']['icons'], {})
        self.assertEqual(public['art']['frames'], [-1, 0])


if __name__ == '__main__':
    unittest.main()
