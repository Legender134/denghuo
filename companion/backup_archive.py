"""Bounded archive verification and player-known snapshot summaries."""
from __future__ import annotations

import hashlib
import json
import math
import re
import stat
from zipfile import BadZipFile, ZipFile

from .engine import Catalog, EQUIPMENT, number
from .saves import read_bundle_data, validate_hero, validate_location, validate_level, validate_floor_members

SAVE_NAME = re.compile(r"(?:game|depth\d+(?:-branch\d+)?)\.dat\Z")
IDENTITY = re.compile(r"[0-9a-f]{64}\Z")
MAX_TOTAL = 64 * 1024 * 1024
_catalog = None


def snapshot_identity(hashes, slot, format=2):
    value = {"slot": slot, "files": hashes} if format == 2 else hashes
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def valid_time(value):
    return type(value) in (int, float) and 0 <= value <= 32503680000


def player_summary(game, saved):
    global _catalog
    if _catalog is None:
        _catalog = Catalog()
    hero = game['hero']
    equipment = []
    for key, label in EQUIPMENT.items():
        if isinstance(hero.get(key), dict):
            item = _catalog.item(hero[key], game, label, reveal=False)
            equipment.append({'location': label, 'name': item['name'], 'details': item['details']})
    return {'saved': saved, 'version': game.get('version'), 'depth': game['depth'],
            'branch': game.get('branch', 0), 'class': hero['class'], 'level': hero['lvl'],
            'hp': hero['HP'], 'ht': hero['HT'], 'gold': number(game.get('gold'), None),
            'strength': hero['STR'], 'equipment': equipment,
            'duration': number(game.get('duration'), None), 'experience': number(hero.get('exp'), None),
            'run_id': hashlib.sha256(json.dumps([game.get('seed'), hero['class']]).encode()).hexdigest()
                      if game.get('seed') is not None else None}


def read_archive(path, *, slot=None, identity=None):
    """Verify every member before any save-directory write or success status."""
    try:
        if path.stat().st_size > MAX_TOTAL:
            raise ValueError('备份文件过大')
        with ZipFile(path) as archive:
            entries = archive.infolist()
            if (len(entries) > 129 or len({e.filename for e in entries}) != len(entries)
                    or any(e.file_size > 16 * 1024 * 1024 for e in entries)
                    or sum(e.file_size for e in entries) > MAX_TOTAL):
                raise ValueError('备份条目或解压大小无效')
            if any(stat.S_IFMT(e.external_attr >> 16) not in (0, stat.S_IFREG) for e in entries):
                raise ValueError('备份清单包含非普通文件')
            manifest = archive.getinfo('manifest.json')
            if manifest.file_size > 65536:
                raise ValueError('备份清单过大')
            metadata = json.loads(archive.read(manifest))
            hashes = metadata.get('files')
            saved = metadata.get('saved')
            actual_slot = metadata.get('slot')
            if (type(metadata.get('format')) is not int or metadata['format'] not in (1, 2)
                    or type(actual_slot) is not int or actual_slot not in range(1, 7)
                    or slot is not None and actual_slot != slot
                    or not isinstance(hashes, dict) or 'game.dat' not in hashes
                    or any(not isinstance(n, str) or not SAVE_NAME.fullmatch(n) for n in hashes)
                    or any(not isinstance(h, str) or not IDENTITY.fullmatch(h) for h in hashes.values())
                    or {e.filename for e in entries} != set(hashes) | {'manifest.json'}
                    or not valid_time(saved)):
                raise ValueError('备份清单无效')
            calculated = snapshot_identity(hashes, actual_slot, metadata['format'])
            if identity is not None and calculated != identity:
                raise ValueError('备份清单校验失败')
            transfer = metadata.get('transfer')
            if transfer is not None:
                if (not isinstance(transfer, dict) or set(transfer) != {'label', 'locked', 'first_observed', 'last_observed'}
                        or not isinstance(transfer['label'], str) or len(transfer['label']) > 80
                        or any(ord(c) < 32 for c in transfer['label']) or type(transfer['locked']) is not bool
                        or not (transfer['first_observed'] is None and transfer['last_observed'] is None
                                or valid_time(transfer['first_observed']) and valid_time(transfer['last_observed'])
                                and transfer['first_observed'] <= transfer['last_observed'])):
                    raise ValueError('备份名称、固定状态或原观察时间无效，尚未导入')
            contents = {name: archive.read(name) for name in hashes}
            if any(hashlib.sha256(data).hexdigest() != hashes[name] for name, data in contents.items()):
                raise ValueError('备份文件校验失败，尚未回档')
        game = read_bundle_data(contents['game.dat'])
        validate_hero(game)
        depth, branch = validate_location(game)
        if not 1 <= depth <= 26:
            raise ValueError('备份楼层不受支持')
        if game.get('version') is not None and (type(game['version']) is not int or not 0 <= game['version'] <= 2147483647):
            raise ValueError('备份存档版本无效')
        floor = f'depth{depth}' + (f'-branch{branch}' if branch else '') + '.dat'
        if floor not in contents:
            raise ValueError('备份缺少当前楼层，尚未回档')
        validate_floor_members(game,contents)
        for name, data in contents.items():
            if name != 'game.dat':
                validate_level(read_bundle_data(data))
        stamps = metadata.get('stamps', {})
        if not isinstance(stamps, dict):
            raise ValueError('备份文件时间无效')
        for name in contents:
            stamp = stamps.get(name, int(saved * 1_000_000_000))
            if type(stamp) is not int or not 0 <= stamp <= 32_503_680_000_000_000_000:
                raise ValueError('备份文件时间无效，尚未回档')
            stamps[name] = stamp
        metadata['stamps'] = stamps
        return metadata, contents, game, calculated
    except (BadZipFile, KeyError, TypeError, AttributeError, RuntimeError, RecursionError, OverflowError) as exc:
        raise ValueError('备份无法完整校验，尚未回档') from exc


def read_records(path, limit=10000):
    if not path.exists():
        return []
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError('备份管理记录过大')
    try:
        def finite(text):
            value = float(text)
            if not math.isfinite(value):
                raise ValueError('备份记录包含无效数值')
            return value
        def integer(text):
            if len(text) > 22:
                raise ValueError('备份记录数值过大')
            return int(text)
        def constant(text):
            raise ValueError('备份记录包含无效数值')
        rows = json.loads(path.read_text(encoding='utf-8'), parse_float=finite,
                          parse_int=integer, parse_constant=constant)
    except (ValueError, RecursionError) as exc:
        raise ValueError('备份管理记录损坏，请先保留备份目录') from exc
    if not isinstance(rows, list) or len(rows) > limit or any(not isinstance(r, dict) for r in rows):
        raise ValueError('备份管理记录损坏')
    return rows
