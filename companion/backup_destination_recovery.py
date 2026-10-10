"""Durable, byte-bound recovery of a destination's three container exchanges."""
from __future__ import annotations

import json
from itertools import islice
import os
from pathlib import Path, PurePosixPath
import re
import uuid

from .backups import unlinked

PENDING = 'backup-destination-pending.json'
PREFIX = '.denghuo-destination-transaction-'
TERMINAL = ('completed', 'cancelled', 'rolled_back')
MAX_RECORD = 16 * 1024 * 1024


def identity(path):
    path = unlinked(path)
    if not path.is_dir():
        raise ValueError('切换恢复关联的目录缺失或类型变化；全部原件仍保留。')
    attrs = path.stat()
    return [attrs.st_dev, attrs.st_ino]


def content(tree):
    return {'directories': tree['directories'], 'files': {
        key: {'bytes': row['bytes'], 'sha256': row['sha256']} for key, row in tree['files'].items()}}


def durable_json(path, value):
    raw = json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2).encode('utf-8')
    if len(raw) > MAX_RECORD:
        raise ValueError('切换恢复记录超过容量，尚未发布目录交换；原件仍保留。')
    pending = unlinked(path.with_name(path.name+'.'+uuid.uuid4().hex+'.pending'))
    with pending.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    pending.replace(unlinked(path))
    if os.name == 'posix':
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def save(config_path, record, state):
    record = {**record, 'state': state}
    target = Path(record['target'])
    if identity(target) != record['target_identity']:
        raise ValueError('目标磁盘或目录身份变化；恢复记录与全部原件仍保留。')
    # Complete the target receipt first. A crash between receipts remains pending locally.
    durable_json(target/(PREFIX+record['id']+'.json'), record)
    durable_json(Path(config_path).parent/PENDING, record)
    return record


def load(config_path):
    from . import backup_destination as d
    path = Path(config_path).parent/PENDING
    if not unlinked(path).exists():
        return None
    record = d._json(path, MAX_RECORD)
    keys = {'format', 'id', 'state', 'config', 'source', 'target', 'backup_root',
            'original_backup_root', 'start_new', 'enabled', 'target_identity', 'stage_identity',
            'originals_identity', 'original', 'merged', 'source_content', 'containers', 'manifest_hash', 'destination_id'}
    if (not isinstance(record, dict) or set(record) != keys or type(record['format']) is not int
            or record['format'] != 1 or not isinstance(record['id'], str)
            or not re.fullmatch(r'[0-9a-f]{32}', record['id'])
            or record['state'] not in ('prepared', 'continuing', 'cancelling', *TERMINAL)
            or record['config'] != str(Path(config_path).resolve())
            or any(type(record[key]) is not bool for key in ('start_new', 'enabled'))):
        raise ValueError('备份目录切换恢复关联损坏，尚未操作；原件仍保留。')
    for key in ('source', 'target'):
        if d.normalize_root(record[key]) != record[key]:
            raise ValueError('备份目录切换恢复路径变化；原件仍保留。')
    for key, base in (('backup_root', 'target'), ('original_backup_root', 'source')):
        if (d.normalize_root(record[key]) != record[key]
                or str(d.base_directory(config_path, record[key]).resolve()) != record[base]):
            raise ValueError('备份目录切换恢复路径关联不一致；原件仍保留。')
    if record['source'] == record['target'] or not isinstance(record['containers'], dict) or set(record['containers']) != set(d.CONTAINERS):
        raise ValueError('备份目录切换恢复容器关联不正确；原件仍保留。')
    for tree in (record['original'], record['merged'], record['source_content']):
        if (not isinstance(tree, dict) or set(tree) != {'files', 'directories'}
                or not isinstance(tree['files'], dict) or not isinstance(tree['directories'], list)
                or len(tree['files'])+len(tree['directories']) > 2*d.MAX_ENTRIES):
            raise ValueError('备份目录切换恢复清单不正确；原件仍保留。')
        for relative in [*tree['files'], *tree['directories']]:
            if (not isinstance(relative, str) or '\\' in relative or not relative
                    or PurePosixPath(relative).is_absolute() or '..' in PurePosixPath(relative).parts
                    or PurePosixPath(relative).parts[0] not in d.CONTAINERS):
                raise ValueError('备份目录切换恢复清单路径不正确；原件仍保留。')
    immutable = {key: value for key, value in record.items() if key not in ('state', 'manifest_hash')}
    if d._digest(immutable) != record['manifest_hash']:
        raise ValueError('备份目录切换恢复清单校验失败；原件仍保留。')
    return record


def prepare(session, binding, stage, originals):
    from . import backup_destination as d
    target = Path(binding['target'])
    operation = stage.name.removeprefix('.denghuo-destination-stage-')
    merged = content(d._tree(stage))
    record = {'format': 1, 'id': operation, 'state': 'prepared', 'config': str(session.config_path.resolve()),
        'source': binding['source'], 'target': binding['target'], 'backup_root': binding['backup_root'],
        'original_backup_root': session.settings.get('backup_root', ''), 'start_new': binding['start_new'],
        'enabled': binding['enabled'], 'target_identity': identity(target), 'stage_identity': identity(stage),
        'originals_identity': identity(originals), 'original': content(binding['target_tree']), 'merged': merged,
        'destination_id': binding['marker'] or uuid.uuid4().hex,
        'source_content': content(binding['source_tree']), 'containers': {}}
    for name in d.CONTAINERS:
        record['containers'][name] = {key: identity(base/name) if (base/name).exists() else None
            for key, base in (('original', target), ('merged', stage))}
    record['manifest_hash'] = d._digest({key: value for key, value in record.items() if key != 'state'})
    # The local pointer exists before the first exchange, including a failed target receipt write.
    durable_json(session.config_path.parent/PENDING, record)
    durable_json(target/(PREFIX+operation+'.json'), record)
    return record


def paths(record):
    target = Path(record['target'])
    return target, target/('.denghuo-destination-stage-'+record['id']), target/('.denghuo-destination-original-'+record['id'])


def locations(record):
    from . import backup_destination as d
    target, stage, originals = paths(record)
    for path, expected in ((target, record['target_identity']), (stage, record['stage_identity']),
                           (originals, record['originals_identity'])):
        if identity(path) != expected:
            raise ValueError('切换恢复目录身份已变化；尚未移动任何原件。')
    result = {}
    for name, expected in record['containers'].items():
        places = {}
        for label, base in (('target', target), ('stage', stage), ('originals', originals)):
            path = unlinked(base/name)
            if not path.exists():
                places[label] = None
                continue
            current = identity(path)
            role = next((key for key in ('original', 'merged') if current == expected[key]), None)
            if role is None or label == 'stage' and role != 'merged' or label == 'originals' and role != 'original':
                raise ValueError('切换恢复容器身份或位置变化；尚未移动任何原件。')
            required = record[role]
            subset = {'directories': [p for p in required['directories'] if p == name or p.startswith(name+'/')],
                      'files': {p: row for p, row in required['files'].items() if p.startswith(name+'/')}}
            if content(d._tree(base, names=(name,))) != subset:
                raise ValueError('切换恢复副本字节或目录清单变化；全部原件保留，请先核对。')
            places[label] = role
        for role in ('original', 'merged'):
            if list(places.values()).count(role) != int(expected[role] is not None):
                raise ValueError('切换恢复缺少唯一对应副本；全部原件保留，请先核对。')
        result[name] = places
    return result


def preview(session):
    from . import backup_destination as d
    record = load(session.config_path)
    if record is None or record['state'] in TERMINAL:
        return None
    places = locations(record)
    can_continue, reason = True, ''
    if not record['start_new']:
        try:
            if content(d._tree(Path(record['source']))) != record['source_content']:
                can_continue, reason = False, '原位置又有新备份或修改；请先取消中断切换，再重新预览完整合并。'
        except (OSError, ValueError) as exc:
            can_continue, reason = False, '原位置暂不可校验：'+str(exc)
    else:
        try:
            d.storage_check(session.config_path, record['original_backup_root'])()
        except (OSError, ValueError):
            pass
        else:
            can_continue, reason = False, '离线旧位置已恢复可用；请取消中断切换，再重新预览并复制完整历史。'
    if getattr(session, 'backup_enabled', session.backups.enabled) != record['enabled']:
        can_continue, reason = False, '备份开关已改变；请先取消中断切换，再重新预览。'
    return {'id': record['id'], 'source_directory': str(Path(record['source'])/'backups'),
        'target_directory': str(Path(record['target'])/'backups'), 'preserved_target_directory': str(paths(record)[2]),
        'state': record['state'], 'can_continue': can_continue, 'continue_reason': reason,
        'history_not_copied': record['start_new'],
        'target_original_bytes': sum(row['bytes'] for row in record['original']['files'].values()),
        'expected': d._digest({'manifest_hash': record['manifest_hash'], 'state': record['state'], 'locations': places,
                              'can_continue': can_continue, 'settings_revision': session.settings_revision}),
        'settings_revision': session.settings_revision, 'context': session.backup_context,
        'message': ('检测到未完成的目录切换，目标原历史仍有恢复关联。核对后可继续切换，或恢复目标原历史并取消；全部副本保留。'
                    + (' 本次离线旧历史未读取、未复制；继续仅在新位置恢复后续备份。' if record['start_new'] else ''))}


def exchange(record, direction, check_current=None):
    from . import backup_destination as d
    target, stage, originals = paths(record)
    locations(record)  # Validate every container before the first rename.
    for name in d.CONTAINERS:
        places = locations(record)[name]
        if check_current:
            check_current()
        if direction == 'continue':
            if places['target'] == 'original':
                unlinked(target/name).rename(unlinked(originals/name))
            if places['stage'] == 'merged':
                unlinked(stage/name).rename(unlinked(target/name))
        else:
            if places['target'] == 'merged':
                unlinked(target/name).rename(unlinked(stage/name))
            if places['originals'] == 'original':
                unlinked(originals/name).rename(unlinked(target/name))
    locations(record)


def recover(session, expected, direction, persist, check_current=None):
    from . import backup_destination as d
    view = preview(session)
    if not view or direction not in ('continue', 'cancel') or view['expected'] != expected:
        raise ValueError('切换恢复预览已变化，请重新核对；原件仍保留。')
    if direction == 'continue' and not view['can_continue']:
        raise ValueError(view['continue_reason'])
    record = load(session.config_path)
    record = save(session.config_path, record, 'continuing' if direction == 'continue' else 'cancelling')
    exchange(record, direction, check_current)
    root = record['backup_root'] if direction == 'continue' else record['original_backup_root']
    if direction == 'continue':
        d._register_destination(session.config_path, Path(record['target']), root, record['target_identity'], record['destination_id'])
    manager = d.manager_for(session.config_path, root, clock=session.backups.clock, closed_check=session.backups.closed_check)
    manager.enabled = record['enabled'] if direction == 'continue' or session.settings.get('backup_root', '') != record['original_backup_root'] else session.backups.enabled
    if check_current:
        check_current()
    persist(root, manager)
    save(session.config_path, record, 'completed' if direction == 'continue' else 'cancelled')
    error = ''
    try:
        manager.ensure_storage()
    except (OSError, ValueError) as exc:
        error = str(exc)
    return {**view, 'ok': True, 'direction': direction, 'originals_retained': True,
            'available': not error, 'error': error,
            'message': '已继续切换，原位置和目标原历史副本全部保留。' if direction == 'continue'
                       else '已恢复目标原历史并取消切换；暂存合并副本和原位置全部保留，可重新预览。'}


def guard_target(config_path, target):
    from . import backup_destination as d
    local = load(config_path)
    if local and local['state'] not in TERMINAL:
        raise ValueError('存在未完成的备份目录切换；请先在备份位置中核对并继续或取消恢复。')
    originals = list(islice(target.glob('.denghuo-destination-original-*'), 257))
    if len(originals) > 256:
        raise ValueError('目标保留副本超过容量，请先核对原件或选择另一目录。')
    for folder in originals:
        operation = folder.name.removeprefix('.denghuo-destination-original-')
        record = d._json(target/(PREFIX+operation+'.json'), MAX_RECORD) if re.fullmatch(r'[0-9a-f]{32}', operation) and unlinked(target/(PREFIX+operation+'.json')).exists() else None
        if (not isinstance(record, dict) or record.get('id') != operation or record.get('state') not in TERMINAL
                or record.get('target') != str(target) or record.get('target_identity') != identity(target)
                or record.get('manifest_hash') != d._digest({k: v for k, v in record.items() if k not in ('state', 'manifest_hash')})):
            raise ValueError('目标含未关联或未完成的切换原件：'+str(folder)+'；尚未把它当作空目录，请先核对或恢复。')
