"""Offline encyclopedia metadata, using public rules and pinned game artwork."""
from functools import lru_cache
import base64
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def images():
    data = json.loads((ROOT / 'data/reference_images.json').read_text(encoding='utf-8'))
    return data


def image_path(url):
    # Serve only explicitly listed artwork, never arbitrary workspace paths.
    if not re.fullmatch(r'/reference-images/[A-Za-z0-9_.-]+\.png', url):
        raise KeyError(url)
    if not any(row.get('url') == url for row in images()['entries'].values()):
        raise KeyError(url)
    return ROOT / 'web' / url[1:]


@lru_cache(maxsize=512)
def native_artwork(identity):
    """Use the same pinned artwork in the offline native window, without URL I/O."""
    row = images()['entries'].get(identity)
    if not row:
        return {}
    try:
        raw = image_path(row['url']).read_bytes()
        if len(raw) > 8192 or hashlib.sha256(raw).hexdigest() != row['sha256']:
            return {}
    except (OSError, KeyError):
        return {}
    captions = {'identity-icon': '效果图标 · 本局外观随机', 'placeholder': '通用外观',
                'representative-sprite': '代表外观 · 形态可变化', 'public-appearance': '本局公开外观'}
    return {'png': base64.b64encode(raw).decode('ascii'), 'sha256': row['sha256'],
            'alt': row['alt'], 'caption': captions.get(row['kind'], '游戏原始图像')}


def native_item_artwork(item):
    # Mirror the player's public appearance. Never infer a hidden effect identity.
    identity = item.get('appearance_id')
    if not identity:
        identity = item.get('key') if item.get('known') or item.get('revealed') is True else {
            'UnknownPotion': 'unknown.potion', 'UnknownScroll': 'unknown.scroll',
            'UnknownRing': 'unknown.ring'}.get(item.get('kind'), 'unknown.item')
    return native_artwork(identity)


@lru_cache(maxsize=1)
def _encounters():
    from .engine import Catalog
    from .floor_guide import floor_encounters
    catalog = Catalog()
    result = {}
    for branch, depths in ((0, range(1, 27)), (1, (*range(11, 15), *range(16, 20)))):
        for depth in depths:
            for row in floor_encounters({'version': 922, 'depth': depth, 'branch': branch, 'challenges': 0}, catalog)['rows']:
                result.setdefault(row['id'], []).append({
                    'depth': depth, 'branch': branch, 'condition': row['condition'], 'group': row['group'],
                })
    return result


def entry(catalog, identity):
    from .engine import clean_text
    from .monster_reference import monster_record
    source = catalog.entry_index.get(identity)
    monster = monster_record(catalog, identity)
    if source is None and monster is None:
        raise KeyError(identity)
    result = dict(source or {})
    if monster:
        # Some summoned variants inherit the base type's gameplay description.
        inherited = catalog.entry_index.get(monster.get('bestiary_alias', ''), {})
        result = {**inherited, **result, 'id': identity, 'name': monster['name'], 'type_label': '敌人'}
        result.setdefault('description', clean_text(catalog.messages.get(identity + '.desc', '')))
        result.setdefault('category', '敌人与角色')
        result['encounters'] = _encounters().get(identity, [])
        result['encounter_note'] = '普通难度的公开生成条件；不是本局已出现的敌人。绝命头目等挑战的召唤变化请查看相应首领资料。'
    result['image'] = images()['entries'].get(identity)
    result['version'] = catalog.data['version']
    return result
