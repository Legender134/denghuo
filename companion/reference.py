"""Offline encyclopedia metadata, using public rules and pinned game artwork."""
from functools import lru_cache
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
