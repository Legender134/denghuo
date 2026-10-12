"""Extract reference PNGs from the pinned official game, without executing Java.

Run with an existing Pillow runtime and --upstream pointing at the official
57a4e06 checkout. Randomized unidentified appearances are never assigned to an
item identity: those entries use the game's identity icons instead.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
from pathlib import Path
import re
import struct
import zlib

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
COMMIT = '57a4e06a4caf162446d1c28caa7983f0493fecf0'
PREFIX = 'com.shatteredpixel.shatteredpixeldungeon.'
JAVA = 'core/src/main/java/com/shatteredpixel/shatteredpixeldungeon/'
ASSETS = 'core/src/main/assets/'
SOURCE = 'https://github.com/00-Evan/shattered-pixel-dungeon'


class Unmapped(ValueError):
    """The source does not establish a single static image."""


def integer(expression, values=None):
    """Only the small integer grammar used in atlas coordinates is supported."""
    values = values or {}
    def visit(node):
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return node.value
        if isinstance(node, ast.Name) and node.id in values:
            return values[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -visit(node.operand)
        if isinstance(node, ast.BinOp):
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add): return left + right
            if isinstance(node.op, ast.Sub): return left - right
            if isinstance(node.op, ast.Mult): return left * right
            if isinstance(node.op, (ast.Div, ast.FloorDiv)): return left // right
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'xy' and len(node.args) == 2:
            return visit(node.args[0]) - 1 + 16 * (visit(node.args[1]) - 1)
        raise Unmapped('Unsupported atlas integer: '+expression)
    try:
        return visit(ast.parse(expression.strip(), mode='eval').body)
    except (SyntaxError, KeyError) as exc:
        raise Unmapped('Unsupported atlas integer: '+expression) from exc


def atlas_constants(text, size, assign):
    text = re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)
    values = {}
    for name, expression in re.findall(r'(?:public|private)\s+static\s+final\s+int\s+(\w+)\s*=\s*([^;]+);', text):
        values[name] = integer(expression, values)
    rects = {}
    pattern = (r'for\s*\(int i\s*=\s*([^;]+);\s*i\s*<\s*([^;]+);\s*i\+\+\)\s*'+assign+
               r'\(\s*i\s*,\s*(\d+)\s*,\s*(\d+)\s*\)|'+assign+r'\(\s*(\w+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)')
    for match in re.finditer(pattern, text):
        if match[1] is not None:
            low, high = integer(match[1], values), integer(match[2], values)
            assignments = [(name, match[3], match[4]) for name, number in values.items() if low <= number < high]
        else:
            assignments = [(match[5], match[6], match[7])]
        for symbol, width, height in assignments:
            number = values[symbol]
            x, y = number % 16 * size, number // 16 * size
            rects[symbol] = [x, y, x+int(width), y+int(height)]
    return values, rects


def png_bytes(bitmap):
    """Canonical RGBA PNG independent of Pillow/libpng/zlib encoder versions.

    A stored DEFLATE block is inexpensive for these tiny frames and avoids
    compressor heuristics changing source-controlled PNG checksums.
    """
    rgba = bitmap.convert('RGBA')
    pixels = rgba.tobytes()
    stride = rgba.width * 4
    scanlines = b''.join(b'\0'+pixels[offset:offset+stride] for offset in range(0, len(pixels), stride))
    compressed = bytearray(b'\x78\x01')
    for offset in range(0, len(scanlines), 65535):
        block = scanlines[offset:offset+65535]
        final = offset+len(block) == len(scanlines)
        compressed.extend(bytes([int(final)]))
        compressed.extend(struct.pack('<HH', len(block), len(block)^65535))
        compressed.extend(block)
    compressed.extend(struct.pack('>I', zlib.adler32(scanlines)))
    def chunk(kind, payload):
        return struct.pack('>I', len(payload))+kind+payload+struct.pack('>I', zlib.crc32(kind+payload))
    return (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('>IIBBBBB', rgba.width, rgba.height, 8, 6, 0, 0, 0))
            +chunk(b'IDAT', bytes(compressed))+chunk(b'IEND', b''))


def build(upstream, output, data_root=ROOT / 'data'):
    catalog = json.loads((data_root / 'catalog.json').read_text(encoding='utf-8'))
    index = json.loads((data_root / 'numeric_rules.json').read_text(encoding='utf-8'))
    monsters = json.loads((data_root / 'monster_reference.json').read_text(encoding='utf-8'))
    if any(document['commit'] != COMMIT for document in (catalog, index, monsters)):
        raise ValueError('Reference inputs must use the pinned game commit')
    classes = index['classes']
    expected = {row['path']: row['sha256'] for row in index['coverage']['files']}
    sources, texts, images = {}, {}, {}

    def read(path):
        if path not in texts:
            raw = (upstream / path).read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if path in expected and digest != expected[path]:
                raise ValueError('Official source hash mismatch: '+path)
            sources[path] = digest
            texts[path] = raw.decode('utf-8')
        return texts[path]

    def image(path):
        if path not in images:
            raw = (upstream / path).read_bytes()
            sources[path] = hashlib.sha256(raw).hexdigest()
            images[path] = Image.open(io.BytesIO(raw)).convert('RGBA')
        return images[path]

    def chain(key):
        seen = set()
        while key in classes and key not in seen:
            seen.add(key)
            row = classes[key]
            read(row['path'])
            yield row
            key = row.get('base')
            # The numeric index leaves some qualified nested bases unresolved.
            # Resolve only against verified Java imports, never a short-name guess.
            if not key and row.get('external_base'):
                try: key = resolve(row['external_base'], row)
                except Unmapped: pass

    def resolve(raw, row):
        root, *nested = raw.split('.')
        candidates = []
        if root in row['imports']:
            candidates.append(row['imports'][root])
        current = row
        while current:
            candidates.append(current['fullname']+'$'+root)
            current = classes.get(current.get('parent'))
        candidates += [row['package']+'.'+root, PREFIX+'sprites.'+root]
        for candidate in candidates:
            key = (candidate+''.join('$'+part for part in nested)).lower()
            if key in classes: return key
        raise Unmapped('Unresolved source class: '+raw)

    sheet_path = JAVA+'sprites/ItemSpriteSheet.java'
    sheet = read(sheet_path)
    main_sheet, icon_sheet = sheet.split('public static class Icons {', 1)
    _, item_rects = atlas_constants(main_sheet, 16, 'assignItemRect')
    _, icon_rects = atlas_constants(icon_sheet, 8, 'assignIconRect')
    assets_path = JAVA+'Assets.java'
    assets = dict(re.findall(r'public static final String (\w+)\s*=\s*"(sprites/[^\"]+)"', read(assets_path)))
    read('SPD-classes/src/main/java/com/watabou/noosa/TextureFilm.java')

    def item_mapping(key):
        lineage = list(chain(PREFIX+key))
        if not any(row['id'] == PREFIX+'items.item' for row in lineage):
            raise Unmapped('Not an Item class with a static sprite')
        for row in lineage:
            # Initializers describe the default item, avoiding later state changes.
            body = '\n'.join(rule['body'] for rule in row['rules'] if rule['kind'] == 'initializer'
                             or rule['kind'] == 'field' and rule['name'] in ('image', 'icon'))
            icons = re.findall(r'\bicon\s*=\s*ItemSpriteSheet\.Icons\.(\w+)\s*;', body)
            sprites = re.findall(r'\bimage\s*=\s*ItemSpriteSheet\.(\w+)\s*;', body)
            if sprites:
                symbol = sprites[-1]
                if symbol == 'SOMETHING': raise Unmapped('Only generic Item default is available')
                return {'atlas': ASSETS+assets['ITEMS'], 'rect': item_rects[symbol], 'symbol': 'ItemSpriteSheet.'+symbol,
                        'class': row['fullname'], 'java': row['path'], 'kind': 'item-sprite'}
            if icons:
                symbol = icons[-1]
                return {'atlas': ASSETS+assets['ITEM_ICONS'], 'rect': icon_rects[symbol], 'symbol': 'ItemSpriteSheet.Icons.'+symbol,
                        'class': row['fullname'], 'java': row['path'], 'kind': 'identity-icon',
                        'note': 'Official identity icon; appearance is randomized per run.'}
        raise Unmapped('No unconditional fixed image or identity icon')

    def mob_mapping(key):
        mob_rows = list(chain(PREFIX+key))
        sprite_key = None
        note = 'First official idle frame; dynamic equipment and particle effects are omitted.'
        if key == 'actors.mobs.shaman':
            result = mob_mapping(key+'$redshaman')
            result['kind'] = 'representative-sprite'
            result['note'] = 'Official RedShaman representative of the abstract Shaman family; color variants differ.'
            return result
        for row in mob_rows:
            body = '\n'.join(rule['body'] for rule in row['rules'] if rule['kind'] in ('initializer', 'field'))
            if key in ('actors.mobs.crystalguardian', 'actors.mobs.crystalspire', 'actors.mobs.crystalwisp'):
                constructors = '\n'.join(rule['body'] for rule in row['rules'] if rule['name'] == row['name'])
                blue = re.search(r'\bspriteClass\s*=\s*([\w.]+\.Blue)\.class\s*;', constructors)
                if blue:
                    body = 'spriteClass = '+blue[1]+'.class;'
                    note = 'Official blue representative; the game also randomly selects green and red variants.'
            match = re.search(r'\bspriteClass\s*=\s*([\w.]+)\.class\s*;', body)
            if match:
                sprite_key = resolve(match[1], row)
                mob_owner = row
                break
        if not sprite_key: raise Unmapped('No fixed spriteClass assignment')
        sprite_rows = list(chain(sprite_key))
        if sprite_key.endswith('necromancer$necroskeleton$necroskeletonsprite'):
            note = 'Official skeleton atlas representative; NecroSkeleton applies runtime brightness(0.75), omitted from this original-pixel reference.'
        values = {}
        for row in sprite_rows:
            for rule in row['rules']:
                match = re.fullmatch(r'return\s+([\d +*\-/]+)\s*;', rule['body'].strip())
                if match and rule['name'] not in values:
                    values[rule['name']] = integer(match[1])
        for row in sprite_rows:
            for rule in row['rules']:
                if rule['name'] != row['name']: continue
                body = rule['body']
                adapter_env = {}
                # Explicit, pinned-source adapters for constructors which delegate
                # animation initialization. These select documented normal states.
                adapters = {
                    'DM300Sprite': ('updateChargeState', 'updateChargeState(false);', {'c': 0}),
                    'GnollGeomancerSprite': ('updateAnims', 'updateAnims();', {'ofs': 0}),
                    'VaultBossElementalSprite': ('updateAnimations', 'updateAnimations();', {'c': 0}),
                    'RatKingSprite': ('resetAnims', 'resetAnims();', {'c': 0, 'height': 16}),
                }
                if row['name'] in adapters:
                    method, call, adapter_env = adapters[row['name']]
                    if call not in body: raise ValueError('Pinned sprite constructor changed: '+row['name'])
                    animation = next(r for r in row['rules'] if r['name'] == method)
                    body += '\n'+animation['body']
                    if row['name'] == 'VaultBossElementalSprite':
                        note = 'Official first elemental-form idle frame; fire/frost/shock forms use different atlas rows.'
                    elif row['name'] == 'RatKingSprite':
                        note = 'Official ordinary Rat King appearance; seasonal and armor-ability variants are omitted.'
                texture = re.search(r'texture\(\s*Assets\.Sprites\.(\w+)\s*\)', body)
                if not texture: continue
                atlas = ASSETS+assets[texture[1]]
                bitmap = image(atlas)
                env = {}
                for name, expression in re.findall(r'\bint\s+(\w+)\s*=\s*([^;]+);', body):
                    expression = re.sub(r'(\w+)\(\)', lambda m: str(values[m[1]]) if m[1] in values else m[0], expression)
                    try: env[name] = integer(expression, env)
                    except Unmapped: pass
                env.update(adapter_env)
                direct = re.search(r'idle\.frames\(\s*texture\.uvRect\((.*?)\)\s*\)\s*;', body)
                if direct:
                    rect = [integer(term, env) for term in direct[1].split(',')]
                    return {'atlas': atlas, 'rect': rect, 'class': classes[sprite_key]['fullname'], 'java': row['path'],
                            'mob_java': mob_owner['path'], 'kind': 'mob-idle', 'note': note}
                film = re.search(r'TextureFilm\s+(\w+)\s*=\s*new TextureFilm\(\s*texture\s*,\s*(.+?),\s*(.+?)\s*\)\s*;', body)
                idle = re.search(r'idle\.frames\(\s*(\w+)\s*,\s*([^,;)]+)', body)
                if not film or not idle or film[1] != idle[1]:
                    raise Unmapped('Sprite uses a dynamic or non-grid idle frame')
                def dimension(expression):
                    expression = re.sub(r'(\w+)\(\)', lambda m: str(values[m[1]]) if m[1] in values else m[0], expression)
                    return integer(expression, env)
                width, height = dimension(film[2]), dimension(film[3])
                frame = integer(idle[2], env)
                columns = bitmap.width // width
                x, y = frame % columns * width, frame // columns * height
                return {'atlas': atlas, 'rect': [x, y, x+width, y+height], 'frame': frame,
                        'class': classes[sprite_key]['fullname'], 'java': row['path'], 'mob_java': mob_owner['path'],
                        'kind': 'representative-sprite' if 'representative' in note or 'variants' in note or 'forms use' in note else 'mob-idle', 'note': note}
        raise Unmapped('No statically readable sprite constructor')

    entries, unmapped = {}, {}
    output.mkdir(parents=True, exist_ok=True)

    def emit(key, name, mapping):
        bitmap = image(mapping['atlas'])
        left, top, right, bottom = mapping['rect']
        if not (0 <= left < right <= bitmap.width and 0 <= top < bottom <= bitmap.height):
            raise ValueError('Frame outside official atlas: '+key)
        crop = bitmap.crop((left, top, right, bottom))
        bbox = crop.getchannel('A').getbbox()
        if bbox is None: raise ValueError('Empty official frame: '+key)
        # Keep the complete declared frame; trimming must not shift the sprite.
        filename = re.sub(r'[^a-zA-Z0-9_.-]', '-', key)+'.png'
        raw = png_bytes(crop)
        (output / filename).write_bytes(raw)
        suffix = '（游戏官方效果图标）' if mapping['kind'] == 'identity-icon' else '（游戏原始图像）'
        entries[key] = {'url': '/reference-images/'+filename, 'name': name, 'alt': name+suffix,
                        'width': crop.width, 'height': crop.height, 'sha256': hashlib.sha256(raw).hexdigest(),
                        'alpha_bbox': list(bbox), 'kind': mapping['kind'], 'source': mapping}

    selected = {row['id']: row for row in catalog['entries'] if row['id'].startswith(('items.', 'actors.mobs.', 'plants.')) or row['id'] in monsters['monsters']}
    for key, row in sorted(selected.items()):
        try:
            lineage = list(chain(PREFIX+key))
            is_mob = any(member['id'] == PREFIX+'actors.mobs.mob' for member in lineage)
            mapping = mob_mapping(key) if is_mob else item_mapping(key)
            emit(key, row['name'], mapping)
        except Unmapped as exc:
            unmapped[key] = str(exc)
    for category, symbol, name in [('potion', 'POTION_HOLDER', '未鉴定药剂'), ('scroll', 'SCROLL_HOLDER', '未鉴定卷轴'),
                                   ('ring', 'RING_HOLDER', '未鉴定戒指'), ('item', 'SOMETHING', '未知物品')]:
        emit('unknown.'+category, name, {'atlas': ASSETS+assets['ITEMS'], 'rect': item_rects[symbol],
             'symbol': 'ItemSpriteSheet.'+symbol, 'java': sheet_path, 'kind': 'placeholder',
             'note': 'Official neutral placeholder; contains no hidden identity.'})
    for category, path in [('potion', 'items/potions/Potion.java'), ('scroll', 'items/scrolls/Scroll.java'), ('ring', 'items/rings/Ring.java')]:
        for label, symbol in re.findall(r'put\("(\w+)"\s*,\s*ItemSpriteSheet\.(\w+)\)', read(JAVA+path)):
            key = 'appearance.'+category+'.'+label.lower()
            name = catalog['messages'].get('items.'+('potions.potion' if category == 'potion' else 'scrolls.scroll' if category == 'scroll' else 'rings.ring')+'.'+label.lower(), label)
            emit(key, name, {'atlas': ASSETS+assets['ITEMS'], 'rect': item_rects[symbol], 'symbol': 'ItemSpriteSheet.'+symbol,
                 'java': JAVA+path, 'label': label, 'kind': 'public-appearance',
                 'note': 'Public randomized appearance label only; conveys no effect identity.'})
            if category != 'ring':
                exotic_path = JAVA+('items/potions/exotic/ExoticPotion.java' if category == 'potion' else 'items/scrolls/exotic/ExoticScroll.java')
                if 'image = handler.image(exoToReg.get(this.getClass())) + 16;' not in read(exotic_path):
                    raise ValueError('Pinned exotic appearance offset changed')
                exotic_symbol = 'EXOTIC_'+symbol.split('_', 1)[1]
                emit('appearance.exotic-'+category+'.'+label.lower(), name+'（合剂外观）' if category == 'potion' else name+'（秘卷外观）',
                     {'atlas': ASSETS+assets['ITEMS'], 'rect': item_rects[exotic_symbol], 'symbol': 'ItemSpriteSheet.'+exotic_symbol,
                      'java': exotic_path, 'label': label, 'kind': 'public-appearance',
                      'note': 'Public exotic appearance: regular randomized label with the official +16 atlas offset; no effect identity.'})
    bestiary = {key for group in monsters['bestiary_groups'].values() for key in group}
    coverage = {'catalog_entries': len(catalog['entries']), 'selected': len(selected), 'mapped': len(selected)-len(unmapped),
                'unmapped': len(unmapped), 'placeholders': 4, 'monster_reference_total': len(monsters['monsters']),
                'public_appearances': sum(key.startswith('appearance.') for key in entries),
                'monster_reference_mapped': len(set(monsters['monsters']) & entries.keys()),
                'bestiary_total': len(bestiary), 'bestiary_mapped': len(bestiary & entries.keys())}
    manifest = {'format': 1, 'commit': COMMIT, 'source': SOURCE, 'license': 'GPL-3.0-or-later',
                'rendering': 'Unscaled transparent original pixels; use nearest-neighbor display scaling.',
                'coverage': coverage, 'sources': dict(sorted(sources.items())), 'entries': entries, 'unmapped': unmapped}
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstream', required=True, type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / 'web/reference-images')
    parser.add_argument('--manifest', type=Path, default=ROOT / 'data/reference_images.json')
    args = parser.parse_args()
    manifest = build(args.upstream.resolve(), args.output)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':'))+'\n', encoding='utf-8', newline='\n')
    print(json.dumps(manifest['coverage'], ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
