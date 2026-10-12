"""Explicit, snapshot-bound inspection of one saved inventory item."""
import copy
import hashlib
import json
from pathlib import Path
import re

from .backups import unlinked
from .engine import analyze
from .saves import read_slot
from .scouting import ScoutingConflict, VERSIONS, floor_path


def snapshot_token(session):
    """Memory-only binding for the same public inventory shown to the player."""
    fingerprint = session._fingerprint
    if (session.settings['mode'] != 'save' or session.active_slot not in range(1, 7)
            or not session.data or session.error or session.config_error or not fingerprint
            or session._shutdown_requested.is_set() or session.stop.is_set()):
        return None
    parts = [session.start_time, session.settings_revision, session.backup_context,
             session.active_slot, session.revision, fingerprint[3].hex()]
    return hashlib.sha256(json.dumps(parts, ensure_ascii=True).encode()).hexdigest()


def inspect_item(session, payload):
    if (not isinstance(payload, dict) or set(payload) != {'expected', 'instance_key', 'reveal'}
            or payload['reveal'] is not True or not isinstance(payload['expected'], str)
            or re.fullmatch(r'[0-9a-f]{64}', payload['expected']) is None
            or not isinstance(payload['instance_key'], str)
            or re.fullmatch(r'item-(0|[1-9][0-9]{0,5})', payload['instance_key']) is None):
        raise ValueError('请从当前背包选择一件物品，再主动确认揭示。')
    with session._backup_operation() as context:
        with session.lock:
            if snapshot_token(session) != payload['expected']:
                raise ScoutingConflict('背包或存档连接已变化，请重新选择物品并主动揭示。')
            index = int(payload['instance_key'][5:])
            public_items = session.data.get('items', [])
            if index >= len(public_items) or public_items[index]['instance_key'] != payload['instance_key']:
                raise ValueError('请从当前背包选择一件物品。')
            fingerprint = session._fingerprint
            source = {'started': session.start_time, 'slot': context.active_slot,
                      'settings_revision': context.settings_revision, 'revision': session.revision,
                      'mode': 'save', 'save_root': context.settings['save_root'],
                      'modified': session.modified, 'expected': payload['expected']}
            location = session.data['depth'], session.data.get('branch', 0)
        root = unlinked(Path(context.settings['save_root']))
        directory = unlinked(root / f'game{context.active_slot}')
        unlinked(directory / 'game.dat')
        floor_path(directory, *location)
        game, level, modified, warning = read_slot(root, context.active_slot)
        digest = hashlib.sha256(json.dumps([game, level], sort_keys=True).encode()).digest()
        if fingerprint != (context.active_slot, modified, warning, digest, context.settings['reveal']):
            raise ScoutingConflict('游戏已经保存了新的背包，请等快照更新后重新选择物品。')
        if type(game.get('version')) is not int or game['version'] not in VERSIONS:
            raise ValueError('本件物品揭示已核对官方4.0.1与4.0.2；此存档版本尚未支持。')
        items = analyze(game, session.catalog, level, reveal=True)['items']
        if index >= len(items) or items[index]['instance_key'] != payload['instance_key']:
            raise ScoutingConflict('背包内容已变化，尚未返回本件物品资料。')
        # Re-read the pair, not just its timestamps: cloud replacements may keep them.
        again, again_level, again_modified, again_warning = read_slot(root, context.active_slot)
        again_digest = hashlib.sha256(json.dumps([again, again_level], sort_keys=True).encode()).digest()
        if (again_digest, again_modified, again_warning) != (digest, modified, warning):
            raise ScoutingConflict('读取期间游戏存档发生变化，请重新选择物品并主动揭示。')
        with session.lock:
            if (not session._context_current(context) or session.active_slot != context.active_slot
                    or snapshot_token(session) != payload['expected']):
                raise ScoutingConflict('存档连接已变化，尚未返回本件物品资料。')
        return {'item': copy.deepcopy(items[index]), 'source': source, 'revealed': True,
                'note': '仅揭示这件物品在所选快照中的资料；其他物品、全局剧透设置与游戏鉴定状态保持原样。'}
