"""Pinned official 4.0.2 flat terrain sprites for the saved-floor map.

Frames follow DungeonTileSheet.directVisuals/directFlatVisuals. The input must
already be masked for unexplored cells, including neighbours used for water.
"""
import base64
import hashlib
import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THEMES = ('sewers', 'prison', 'caves', 'city', 'halls')
FRAMES = {0:24,1:0,2:2,3:19,4:48,5:56,6:57,7:16,8:17,9:3,10:58,11:20,
          12:49,13:65,14:4,15:66,16:48,17:0,18:0,19:0,20:1,21:61,22:60,
          23:0,24:18,25:72,26:73,27:50,28:64,30:67,31:59,32:0,33:74,
          34:75,35:76,36:76,37:22,38:58,39:32}
WATER_SHORE = {1,2,3,5,6,7,8,9,10,13,15,17,18,19,20,23,24,25,28,30,31,32,33,35,36,38}


def theme_for(level, depth, game=None):
    name = str((level or {}).get('__className', '')).rsplit('.', 1)[-1]
    if name in ('LastShopLevel', 'CityLevel', 'CityBossLevel'): return 'city'
    if name == 'DeadEndLevel': return 'caves'
    if name == 'MiningLevel':
        quests = (game or {}).get('quests') or {}
        smith = quests.get('blacksmith') or {} if isinstance(quests, dict) else {}
        kind = smith.get('type') if isinstance(smith, dict) else None
        return {1: 'caves_crystal', 2: 'caves_gnoll'}.get(kind, 'caves')
    for prefix, theme in (('Sewer','sewers'), ('Prison','prison'), ('Caves','caves'), ('Mining','caves'), ('City','city'), ('Halls','halls'), ('Last','halls')):
        if name.startswith(prefix): return theme
    return THEMES[min(4, max(0, (int(depth or 1)-1)//5))]


@lru_cache(maxsize=16)
def image_data(filename):
    manifest = json.loads((ROOT/'data/map_atlas.json').read_text(encoding='utf8'))
    expected = manifest['files'].get(filename)
    if not expected: return ''
    raw = (ROOT/'web/map-atlas'/filename).read_bytes()
    if len(raw) > 65536 or hashlib.sha256(raw).hexdigest() != expected: return ''
    return base64.b64encode(raw).decode('ascii')


def terrain_art(map_data, depth=1):
    width, height, tiles = map_data['width'], map_data['height'], map_data['tiles']
    theme = map_data.get('theme') or theme_for(None, depth)
    if theme not in (*THEMES, 'caves_crystal', 'caves_gnoll'): theme = theme_for(None, depth)
    frames = []
    for i, tile in enumerate(tiles):
        x, y = i % width, i // width
        # Level.cleanWalls: deep wall interiors are not discoverable. Evaluate
        # only the already-masked view, so hidden neighbours cannot leak.
        if tile in (4, 12) and not any(
                tiles[ny * width + nx] not in (-1, 4, 12)
                for ny in range(max(0, y-1), min(height, y+2))
                for nx in range(max(0, x-1), min(width, x+2))):
            frames.append(-2)
            continue
        if tile == 29:
            neighbours = ((x,y-1,1), (x+1,y,2), (x,y+1,4), (x-1,y,8))
            shore = WATER_SHORE | ({34} if depth > 20 else set())
            frame = 32 + sum(bit for nx,ny,bit in neighbours if 0<=nx<width and 0<=ny<height and tiles[ny*width+nx] in shore)
        else:
            frame = FRAMES.get(tile, -1)
        if tile in (35, 36) and theme == 'caves':
            frame = -1  # no quest type: do not draw the transparent normal-caves frame
        frames.append(frame)
    try:
        atlas = image_data('tiles_'+theme+'.png')
        water_theme = map_data.get('water_theme') or ('caves' if theme.startswith('caves_') else theme)
        if water_theme not in THEMES: water_theme = 'caves'
        water = image_data('water'+str(THEMES.index(water_theme))+'.png')
        items = image_data('items.png')
    except (OSError, ValueError, KeyError):
        atlas = water = items = ''
    return {'frames': frames, 'atlas': atlas, 'water': water, 'items': items}
