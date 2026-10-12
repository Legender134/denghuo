"""Opt-in, read-only inspection of already generated official save floors.

Bundle keys and terrain IDs follow SPD 4.0.1/4.0.2 Level, Terrain, Heap,
Trap, Mimic and Statue (GPL-3.0-or-later; Oleg Dolya, Evan Debenham).
This module never generates a floor or predicts an enemy's random death loot.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .backups import unlinked
from .engine import PREFIX
from .saves import MAX_BYTES, SaveError, file_stamp, open_save, read_bundle_data, validate_hero, validate_level, validate_location

VERSIONS = {920: '4.0.1', 922: '4.0.2'}
HEAPS = {'HEAP': '地面物品', 'FOR_SALE': '待售物品', 'CHEST': '宝箱', 'LOCKED_CHEST': '上锁宝箱',
         'CRYSTAL_CHEST': '水晶宝箱', 'TOMB': '墓碑', 'SKELETON': '骸骨', 'REMAINS': '遗骸'}
FEATURES = {7: '上行楼梯', 8: '下行楼梯', 10: '上锁的门', 16: '隐藏门', 17: '隐藏陷阱',
            18: '已发现陷阱', 19: '失效陷阱', 21: '锁住的出口', 22: '解锁的出口',
            24: '水井', 28: '炼金装置', 31: '水晶门', 37: '特殊入口', 38: '骷髅钥匙锁门'}
FEATURES.update({13:'路障',23:'实心环境装饰',25:'石像',26:'特殊石像',27:'书架',33:'区域障碍',
                 34:'特殊区域障碍',35:'矿晶',36:'矿石巨岩',39:'水中实心装饰'})
MIMICS = {'Mimic', 'GoldenMimic', 'CrystalMimic', 'EbonyMimic'}


class ScoutingConflict(SaveError):
    """A selected saved snapshot changed before it could be inspected."""


def read_snapshot(path):
    path = unlinked(path)
    before = path.stat()
    if not path.is_file() or not 1 <= before.st_size <= MAX_BYTES:
        raise SaveError('存档文件为空、过大或不是普通文件，尚未展开探查。')
    with open_save(path) as stream:
        raw = stream.read(MAX_BYTES + 1)
    if file_stamp(before) != file_stamp(path.stat()) or len(raw) != before.st_size:
        raise ScoutingConflict('游戏正在保存，尚未展开探查；请等待保存完成后重新读取。')
    return read_bundle_data(raw), hashlib.sha256(raw).hexdigest(), file_stamp(before), before.st_mtime


def floor_locations(game):
    depth, branch = validate_location(game)
    if not 1 <= depth <= 26:
        raise SaveError('此位置不支持楼层探查。')
    generated = game.get('generated_levels')
    if not isinstance(generated, list) or len(generated) > 128:
        raise SaveError('已生成楼层清单缺失或无效，尚未猜测历史楼层。')
    locations = {(depth, branch)}
    for value in generated:
        if type(value) is not int or not 0 < value <= 20026:
            raise SaveError('已生成楼层编号无效。')
        b, d = divmod(value, 1000)
        if not 1 <= d <= 26 or not 0 <= b <= 20:
            raise SaveError('已生成楼层编号无效。')
        locations.add((d, b))
    return sorted(locations, key=lambda row: (row[1], row[0]))


def floor_path(directory, depth, branch):
    return unlinked(directory / (f'depth{depth}' + (f'-branch{branch}' if branch else '') + '.dat'))


def inspect_saved(session, payload):
    if not isinstance(payload, dict) or payload.get('action') not in ('catalog', 'floor'):
        raise ValueError('请选择读取楼层清单或主动揭示一个楼层。')
    action = payload['action']
    required = {'action'} if action == 'catalog' else {'action', 'depth', 'branch', 'expected', 'reveal'}
    if set(payload) != required:
        raise ValueError('探查请求字段不完整或不受支持。')
    if action == 'floor' and (payload['reveal'] is not True or not isinstance(payload['expected'], str)
            or len(payload['expected']) != 64 or type(payload['depth']) is not int or type(payload['branch']) is not int):
        raise ValueError('请主动勾选揭示，并从当前已生成楼层清单选择。')
    with session._backup_operation() as context:
        with session.lock:
            if (context.config_error or context.settings['mode'] != 'save' or context.active_slot not in range(1, 7)
                    or session.error or session._shutdown_requested.is_set() or session.stop.is_set()):
                raise ValueError('请先连接有效存档，再读取已生成楼层；手动局势不提供探查。')
        directory = unlinked(Path(context.settings['save_root']) / f'game{context.active_slot}')
        game_path = unlinked(directory / 'game.dat')
        game, game_hash, game_stamp, modified = read_snapshot(game_path)
        validate_hero(game)
        if type(game.get('version')) is not int:
            raise SaveError('存档版本数据缺失或无效，隐藏内容未展开。')
        locations = floor_locations(game)
        expected = hashlib.sha256(json.dumps([context.settings_revision, context.backup_context,
            context.settings['save_root'], context.active_slot, game_hash], ensure_ascii=True).encode()).hexdigest()
        source = {'slot': context.active_slot, 'depth': game['depth'], 'branch': game.get('branch', 0),
                  'version': game.get('version'), 'version_name': VERSIONS.get(game.get('version')),
                  'modified': modified, 'expected': expected}
        hero_level = game.get('hero', {}).get('lvl')
        source['hero_level'] = hero_level if type(hero_level) is int and 1 <= hero_level <= 30 else None
        mask = game.get('challenges')
        source['challenges_known'] = type(mask) is int and 0 <= mask <= 511
        source['challenges_mask'] = mask if source['challenges_known'] else None
        if action == 'catalog':
            floors = []
            for depth, branch in locations:
                try:
                    path = floor_path(directory, depth, branch)
                    available = path.is_file() and 1 <= path.stat().st_size <= MAX_BYTES
                except (OSError, ValueError):
                    available = False
                floors.append({'depth': depth, 'branch': branch, 'available': available,
                    'current': (depth, branch) == (game['depth'], game.get('branch', 0))})
            from .floor_guide import floor_encounters
            result = {'source': source, 'floors': floors, 'supported': source['version'] in VERSIONS,
                      'encounters': floor_encounters(game, session.catalog),
                      'note': '只列本局已生成楼层；不展开隐藏内容。尚未生成的楼层不在此清单。'}
        else:
            if expected != payload['expected']:
                raise ScoutingConflict('角色存档或连接已变化，旧探查已失效；请重新读取楼层清单后主动揭示。')
            location = payload['depth'], payload['branch']
            if location not in locations:
                raise SaveError('此楼层未记录为本局已生成，不能将其他文件当作当前冒险。')
            if source['version'] not in VERSIONS:
                raise SaveError('楼层探查已核对官方4.0.1与4.0.2；此存档版本尚未支持，隐藏内容未展开。')
            path = floor_path(directory, *location)
            bundle, level_hash, level_stamp, level_modified = read_snapshot(path)
            level = validate_level(bundle)
            if level['version'] not in VERSIONS:
                raise SaveError('此楼层的保存版本尚未支持，隐藏内容未展开。')
            if location == (game['depth'], game.get('branch', 0)) and not 0 <= level_stamp[0] - game_stamp[0] <= 10_000_000_000:
                raise ScoutingConflict('当前楼层与角色保存时间不一致，尚未混合展示；请在游戏内完成保存后重读。')
            result = project_floor(level, game, session.catalog, *location)
            result.update(source={**source, 'floor_modified': level_modified, 'floor_sha256': level_hash,
                                  'floor_version': level['version']}, revealed=True)
            # Re-read hashes as well as metadata: cloud copies can preserve times.
            if read_snapshot(path)[1] != level_hash:
                raise ScoutingConflict('楼层在探查期间变化，结果未发布；请重新读取。')
        if read_snapshot(game_path)[1] != game_hash:
            raise ScoutingConflict('角色存档在读取期间变化，结果未发布；请重新读取。')
        with session.lock:
            if not session._context_current(context) or session.active_slot != context.active_slot:
                raise ScoutingConflict('存档连接已变化，结果未发布；请重新读取楼层清单。')
        return result


def project_floor(level, game, catalog, depth, branch):
    from .saves import validate_map
    validate_map(level, maximum=128)
    width, height = level['width'], level['height']
    cells = width * height
    def at(pos):
        if type(pos) is not int or not 0 <= pos < cells:
            raise SaveError('楼层对象坐标无效，尚未展开探查。')
        return {'pos': pos, 'x': pos % width + 1, 'y': pos // width + 1}
    def collection(name):
        values = level.get(name, [])
        if not isinstance(values, list) or len(values) > cells or any(not isinstance(row, dict) for row in values):
            raise SaveError('楼层对象清单无效，尚未展开探查。')
        return values
    item_count = 0
    def flag(row, key, default=False):
        value = row.get(key, default)
        if type(value) is not bool:
            raise SaveError('楼层对象标记无效，隐藏内容未展开。')
        return value
    def items(values, location, nesting=0):
        nonlocal item_count
        if not isinstance(values, list) or len(values) > 1000 or nesting > 12:
            raise SaveError('楼层物品清单无效，尚未展开探查。')
        projected = []
        for raw in values:
            item_count += 1
            if item_count > 5000 or not isinstance(raw, dict) or not isinstance(raw.get('__className'), str) or not raw['__className'].startswith(PREFIX + 'items.'):
                raise SaveError('楼层物品格式无效或超出探查数量限制。')
            row = catalog.item(raw, game, location, reveal=True)
            row.update(available=False, instance_key=f'floor-{depth}-{branch}-item-{item_count}')
            projected.append(row)
            if 'inventory' in raw:
                projected.extend(items(raw['inventory'], location+' · '+row['name'], nesting+1))
        return projected
    heaps = []
    for index, heap in enumerate(collection('heaps')):
        kind = heap.get('type')
        if not isinstance(kind, str) or kind not in HEAPS:
            raise SaveError('楼层容器类型尚未支持，隐藏内容未展开。')
        label = HEAPS[kind]
        heaps.append({'id': f'heap-{index}', **at(heap.get('pos')), 'type': kind, 'name': label,
            'seen': flag(heap, 'seen'), 'hidden': flag(heap, 'hidden'),
            'haunted': flag(heap, 'haunted'), 'items': items(heap.get('items', []), label)})
    traps = []
    for trap in collection('traps'):
        if not isinstance(trap.get('__className'), str) or not trap['__className'].startswith(PREFIX + 'levels.traps.'):
            raise SaveError('陷阱类型无效，隐藏内容未展开。')
        traps.append({**at(trap.get('pos')), 'name': catalog.name(trap), 'id': catalog.key(trap),
                      'visible': flag(trap, 'visible'), 'active': flag(trap, 'active', True)})
    mobs = []
    for mob in collection('mobs'):
        kind = str(mob.get('__className', '')).removeprefix(PREFIX)
        if not kind.startswith(('actors.mobs.', 'items.quest.', 'levels.rooms.', 'levels.traps.')):
            raise SaveError('楼层生物类型无效，隐藏内容未展开。')
        short = kind.rsplit('.', 1)[-1]
        saved_items = []
        if short in MIMICS:
            saved_items = mob.get('items') or []
            if not isinstance(saved_items, list):
                raise SaveError('宝箱怪随身物品清单无效，隐藏内容未展开。')
            saved_items = list(saved_items)
        if short in ('Statue', 'ArmoredStatue'):
            saved_items.extend(mob[field] for field in ('weapon', 'armor') if isinstance(mob.get(field), dict))
        if short in ('Thief', 'Bandit') and isinstance(mob.get('item'), dict):
            saved_items.append(mob['item'])
        identity = catalog.key(mob)
        reference = catalog.entry_index.get(identity) if identity in catalog.data.get('enemy_ids', []) else None
        mobs.append({**at(mob.get('pos')), 'id': identity, 'name': catalog.name(mob),
                     'reference': reference,
                     'hp': mob.get('HP') if type(mob.get('HP')) is int and 0 <= mob['HP'] <= 2147483647 else None,
                     'ht': mob.get('HT') if type(mob.get('HT')) is int and 1 <= mob['HT'] <= 2147483647 else None,
                     'items': items(saved_items, '生物随身保存物品')})
    features = [{**at(pos), 'terrain': tile, 'name': FEATURES[tile], 'hidden': tile in (16, 17)}
                for pos, tile in enumerate(level['map']) if tile in FEATURES]
    hero = game.get('hero', {}).get('pos') if (depth, branch) == (game['depth'], game.get('branch', 0)) else None
    if type(hero) is not int or not 0 <= hero < cells:
        hero = None
    return {'depth': depth, 'branch': branch, 'map': {'width': width, 'height': height,
        'tiles': list(level['map']), 'hero': hero, 'caption': '主动揭示的已保存完整楼层；非实时视野'},
        'features': features, 'heaps': heaps, 'traps': traps, 'mobs': mobs,
        'item_count': item_count, 'note': '存档中已生成且仍保存的内容，不是未来随机掉落。宝箱、售卖、墓碑、生物持有物品不等于可立即取得；房间或奖励可能互斥。秘密门位置来自地形，房间名称未从地图猜测。',
        'sources': [{'label': '官方楼层存档格式', 'url': 'https://github.com/00-Evan/shattered-pixel-dungeon/blob/v' + VERSIONS[game['version']] + '/core/src/main/java/com/shatteredpixel/shatteredpixeldungeon/levels/Level.java'}]}
