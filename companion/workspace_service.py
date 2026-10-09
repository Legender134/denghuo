"""Shared user workflows for knowledge, help and desktop preferences."""
import copy
import os
from pathlib import Path

from .decisions import public_context, source

COMMON = ('items.potions.potionofhealing', 'items.waterskin', 'items.scrolls.scrollofupgrade',
          'items.scrolls.scrollofidentify', 'items.scrolls.scrollofremovecurse')


def workspace_status(session):
    from .alchemy import status as alchemy_status
    stored = session.knowledge.status()
    snap = session.snapshot()
    entries = {row['id']: row for row in session.catalog.entries}
    context = public_context(snap)
    provenance = source(snap)
    # This transient stamp stays in memory and is never written into a saved plan.
    stamp = [snap.get('started'), snap['settings'].get('save_root'),
             snap['settings']['mode'], snap.get('active_slot'), snap.get('revision'), snap.get('modified')]
    current = []
    data = {} if snap.get('error') else snap.get('data') or {}
    for item in data.get('items', []):
        if not item.get('known') or item.get('available') is not True or item.get('key') not in entries:
            continue
        params = dict(context)
        if item.get('level') is not None:
            params['level'] = item['level']
        if item.get('tier') is not None:
            params['tier'] = item['tier']
        if type(item.get('volume')) is int:
            params['dew_volume'] = item['volume']
        level_applies = item.get('level_applicable', item['key'].startswith(('items.weapon.', 'items.armor.', 'items.wands.', 'items.rings.', 'items.artifacts.', 'items.trinkets.')))
        origin = 'not_applicable' if not level_applies else 'known' if item.get('level') is not None else 'unknown'
        current.append({**entries[item['key']], 'lookup_label': item['name'] + ' · ' + provenance['label'],
                        'lookup_context': {'params': params, 'stamp': stamp,
                                           'level_origin': origin, 'level_unknown': origin == 'unknown', 'level_applicable': level_applies,
                                           'mode': provenance['mode'], 'source': provenance,
                                           'source_label': provenance['label'],
                                           'conditions': ('角色总力量已按公开条件计算；其他加成仍需核对' if data.get('character_scene', {}).get('strength', {}).get('usable') else '基础力量参考；总力量条件尚未确认，请核对戒指、天赋与临时状态')}})
    for buff in data.get('buffs', []):
        identity = 'actors.buffs.' + buff['kind'].lower()
        if identity not in entries or any(row['id'] == identity for row in current):
            continue
        current.append({**entries[identity], 'lookup_label': entries[identity]['name'] + ' · ' + provenance['label'],
                        'lookup_context': {'params': dict(context), 'stamp': stamp,
                                           'level_origin': 'example', 'mode': provenance['mode'],
                                           'source': provenance, 'source_label': provenance['label'],
                                           'conditions': '公开当前护盾已带入；其余强度、时长与条件需另行填写' if 'current_shield' in context else '只确认状态存在；剩余强度、时长与其他条件需另行填写'}})
    return {**stored, 'favorite_ids': list(stored['favorites']),
            'favorites': [entries[identity] for identity in stored['favorites'] if identity in entries],
            'recent': [{**entries[row['entry']], 'opened': row['opened']} for row in stored['recent']
                       if row['entry'] in entries],
            'current': current, 'common': [entries[identity] for identity in COMMON if identity in entries],
            'revision': session.knowledge.generation, 'alchemy': alchemy_status(session),
            'character_scene': {'current': data.get('character_scene'), 'source': provenance, 'stamp': stamp}}


def workspace_action(session, payload):
    if not isinstance(payload, dict):
        raise ValueError('资料库请求格式不正确')
    action = payload.get('action')
    store = session.knowledge
    if action == 'character-calculate':
        from .character_scene import calculate_scene
        if set(payload) != {'action', 'params'}:
            raise ValueError('角色条件计算请求格式不正确')
        return calculate_scene(payload['params'])
    if action == 'alchemy-calculate':
        from .alchemy import calculate
        if set(payload) != {'action', 'params'}:
            raise ValueError('炼金计算请求格式不正确')
        args, result = calculate(session.catalog, payload['params'])
        return {'params': args, 'result': result}
    if action == 'alchemy-discover':
        from .alchemy_flow import discover
        if set(payload) != {'action', 'params'}:
            raise ValueError('炼金发现请求格式不正确')
        return discover(session.catalog, payload['params'], session.values)
    if action == 'alchemy-resources':
        from .alchemy import resources_from_snapshot
        if set(payload) != {'action'}:
            raise ValueError('炼金资源请求格式不正确')
        return resources_from_snapshot(session)
    if action in ('remember', 'favorite'):
        entry = payload.get('entry')
        if entry not in session.rules.entries and ('com.shatteredpixel.shatteredpixeldungeon.' + str(entry)) not in session.rules.classes:
            raise ValueError('资料条目尚未收录')
        if action == 'remember':
            store.remember(entry)
        else:
            store.favorite(entry, payload.get('enabled'))
        return {'revision': store.generation}
    if action == 'save':
        return {'plan': store.save(payload.get('name'), payload.get('kind'), payload.get('entry'),
                                   payload.get('params'), payload.get('source'), payload.get('record_id'),
                                   payload.get('expected_record_revision'), note=payload.get('note')),
                'revision': store.generation}
    if action == 'remove':
        if payload.get('confirmed') is not True:
            raise ValueError('请确认移除所选方案；收藏、游戏与备份不会删除')
        store.remove(payload.get('id'), payload.get('expected_record_revision'))
        return {'revision': store.generation}
    if action == 'repair-preview':
        return store.repair_preview()
    if action == 'repair':
        return store.repair(payload.get('expected'), payload.get('confirmed'))
    raise ValueError('不支持的资料库操作')


def play_status(session):
    with session.lock:
        prefs = session.play_preferences
        with prefs.lock:
            caps = copy.deepcopy(session.ui_capabilities)
            return {'settings': copy.deepcopy(prefs.values), 'error': prefs.error,
                    'revision': prefs.generation,
                    'desktop_available': bool(session.manager_available and caps.get('play_available')),
                    'desktop_status': caps}


def update_play(session, payload):
    if not isinstance(payload, dict) or set(payload) != {'settings', 'revision'}:
        raise ValueError('游玩设置请求格式不正确')
    with session.lock:
        session.play_preferences.update(payload['settings'], expected_generation=payload['revision'])
        if session.manager_available:
            session.manager_commands.put(('play_settings_changed', session.play_preferences.generation))
    return play_status(session)


def reload_play(session, payload):
    if not isinstance(payload, dict) or set(payload) != {'revision'} or type(payload['revision']) is not int:
        raise ValueError('重新读取游玩设置请求格式不正确')
    with session.lock:
        prefs = session.play_preferences
        with prefs.lock:
            if payload['revision'] != prefs.generation:
                raise ValueError('另一窗口刚修改配置，请先查看当前已保存设置再重新读取')
            prefs.reload()
        if session.manager_available:
            session.manager_commands.put(('play_settings_changed', prefs.generation))
    return play_status(session)


def help_status(session):
    from .support import help_status as support_status
    result = support_status(session)
    result['links'] = [{'label': '灯火项目与问题反馈', 'url': 'https://github.com/Legender134/denghuo'},
                       {'label': '原游戏与玩法资料', 'url': 'https://github.com/00-Evan/shattered-pixel-dungeon'}]
    # Paths are for explicitly opening this instance's local files, never diagnostic exports.
    result['locations'] = {'data': {'label': '助手数据目录', 'available': session.config_path.parent.is_dir()},
                           'log': {'label': '本次运行日志', 'available': bool(session.log_path and session.log_path.is_file())}}
    return result


def open_support_location(session, payload):
    if not isinstance(payload, dict) or set(payload) != {'action'}:
        raise ValueError('本地帮助请求格式不正确')
    action = payload['action']
    if action == 'open-data':
        path = session.config_path.parent
    elif action == 'open-log':
        path = session.log_path
    else:
        raise ValueError('不支持的本地帮助操作')
    if path is None or not Path(path).exists():
        raise ValueError('本次运行尚未建立这个本地位置，请先查看排查摘要')
    if os.name != 'nt':
        raise ValueError('此运行环境无法打开 Windows 本地文件；可先导出排查摘要')
    try:
        os.startfile(str(path))
    except OSError as exc:
        raise ValueError('本地位置未能打开，请检查系统文件关联或数据目录权限') from exc
    return {'opened': True}
