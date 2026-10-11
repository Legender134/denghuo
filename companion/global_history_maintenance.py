"""Explicit local retention and crash recovery for the global-history quota.

Only the assistant's global-history container moves. Every retained byte remains
local and discoverable; this operation releases active quota, never disk space.
"""
from __future__ import annotations

from io import BytesIO
from itertools import islice
import json
import os
from pathlib import Path
import re
import stat
import uuid
import zipfile

from . import global_progress as files
from .backups import unlinked

INDEX = 'global-history-maintenance.json'
ARCHIVES = 'global-history-archives'
ARCHIVE_ID = re.compile(r'[a-f0-9]{32}\Z')
TERMINAL = ('completed', 'cancelled')


def _history():
    from . import global_history
    return global_history


def _identity(path):
    return files.root_identity(unlinked(path))


def _inventory(directory):
    """Recognize only the existing history schema, retaining even bad contents."""
    h = _history()
    directory = unlinked(directory)
    if not directory.exists():
        return None
    tree = {'identity': _identity(directory), 'objects_identity': None, 'files': {}}
    for base in (directory, unlinked(directory/'objects')):
        if not base.exists():
            continue
        if base != directory:
            tree['objects_identity'] = _identity(base)
        paths = list(islice(base.iterdir(), 4097))
        if len(paths) > 4096:
            raise ValueError('全局历史条目过多，尚未归档；全部原件仍保留。')
        for path in paths:
            unlinked(path)
            if path == directory/'objects' and path.is_dir():
                continue
            suffix = '.json' if base == directory else '.dat'
            attrs = path.stat()
            if (not stat.S_ISREG(attrs.st_mode) or attrs.st_nlink != 1
                    or attrs.st_size > files.MAX_BYTES
                    or not h.PENDING.fullmatch(path.name)
                    and not (path.suffix == suffix and h.ID.fullmatch(path.stem))):
                raise ValueError('历史含未识别或不安全的原件，未移动任何文件；请先核对保留目录。')
            raw = files.read(path)
            if raw is None:
                raise ValueError('历史原件在核对期间变化，请重新预览；全部原件仍保留。')
            tree['files'][path.relative_to(directory).as_posix()] = {'bytes': len(raw), 'sha256': files.digest(raw)}
    if _identity(directory) != tree['identity']:
        raise ValueError('全局历史目录身份变化，请重新预览；全部原件仍保留。')
    return tree


def _source(root):
    identity, raw = _history()._source(root)
    return {'root': str(Path(root).resolve()), 'identity': identity,
            'files': {name: files.digest(raw.get(name)) for name in files.FILES}}


def _scope(manager, library):
    manager.ensure_storage()
    path = unlinked(manager.scope(library))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _binding(manager, root, library):
    scope = _scope(manager, library)
    if files.pending(manager, root) is not None:
        raise ValueError('有未完成的全局进度恢复，请先处理恢复；尚未维护历史。')
    if pending(manager, library) is not None:
        raise ValueError('有未完成的全局历史维护，请先预览并继续或取消。')
    source = _source(root)
    tree = _inventory(scope/'global-history')
    if tree is None or not tree['files']:
        raise ValueError('没有需要保留归档的活动全局历史。')
    return {'library': scope.name, 'storage_identity': _identity(manager.directory),
            'scope_identity': _identity(scope), 'source': source, 'original': tree}


def _summary(manager, library, archive_id=None, *, details=False):
    h = _history()
    rows, damaged = h._scan(manager, library, archive_id)
    inspected = h._inspected_rows(manager, library, rows, archive_id)
    damaged_paths = {row['id']+'.json' for row in damaged}
    damaged_paths.update('objects/'+item['sha256']+'.dat'
                         for row in inspected for item in row['files'].values() if not item['valid'])
    latest = next(({'id': row['id'], 'sequence': row['sequence'], 'time': row['time'],
                   'files': [name for name, item in row['files'].items() if item['valid']]}
                  for row in inspected if any(item['valid'] for item in row['files'].values())), None)
    summary = len(rows)+len(damaged), len(damaged_paths), latest
    return (*summary, damaged_paths) if details else summary


def maintenance_preview(manager, root, library):
    with files._transaction_lock(manager, library):
        binding = _binding(manager, root, library)
        count, damaged, latest, damaged_paths = _summary(manager, library, details=True)
        # Recheck the originals and current source after inspection, before issuing a token.
        if _binding(manager, root, library) != binding:
            raise ValueError('历史或当前源文件在预览期间变化，请重新预览；全部原件仍保留。')
        originals = [{'path': name, **item, 'damaged': name in damaged_paths}
                     for name, item in sorted(binding['original']['files'].items())]
        current_library = manager.scope(root) == manager.scope(library)
        next_protection = ('监控开启时再建立当前源文件的新保护。' if current_library
                           else '恢复此旧库的活动额度；不会在旧库为当前游戏新增保护。')
        return {'mode': 'retain-local', 'records': count, 'bytes': sum(item['bytes'] for item in originals),
                'damaged_count': damaged, 'latest_usable': latest, 'originals': originals,
                'missing_originals': sorted(damaged_paths-set(binding['original']['files'])),
                'active_after': {'count': 0, 'bytes': 0}, 'disk_bytes_released': 0,
                'expected': files.digest(files.encode(binding)),
                'message': '把全部活动历史和损坏原件原样保留为可浏览的本地归档。'+next_protection+
                           '归档后先释放活动512份/64 MiB额度；新保护会占用活动额度。磁盘空间不会减少，单份导出也不会释放额度。'}


def _durable(path, row):
    raw = files.encode(row)
    path = unlinked(path)
    temporary = unlinked(path.parent/('.global-'+uuid.uuid4().hex+'.pending'))
    files._write_new(temporary, raw)
    temporary.rename(path) if not path.exists() else temporary.replace(path)
    _sync(path.parent)


def _sync(path):
    if os.name == 'posix':
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _load(path, library):
    raw = files.read(path)
    if raw is None:
        return None
    try:
        row = json.loads(raw, object_pairs_hook=files.unique_fields, parse_constant=files.invalid_constant)
    except (ValueError, RecursionError) as exc:
        raise ValueError('全局历史维护关联损坏，原件和记录仍保留。') from exc
    keys = {'format', 'kind', 'id', 'state', 'library', 'storage_identity', 'scope_identity',
            'archives_identity', 'container_identity', 'source', 'original', 'fresh_identity', 'seal'}
    if (not isinstance(row, dict) or set(row) != keys or type(row['format']) is not int or row['format'] != 1
            or row['kind'] != 'denghuo-global-history-maintenance'
            or not isinstance(row['id'], str) or not ARCHIVE_ID.fullmatch(row['id'])
            or row['state'] not in ('prepared', 'continuing', 'cancelling', *TERMINAL)
            or row['library'] != library
            or files.digest(files.encode({k: v for k, v in row.items() if k not in ('state', 'seal')})) != row['seal']):
        raise ValueError('全局历史维护关联不能核对，全部原件和记录仍保留。')
    for key in ('storage_identity', 'scope_identity', 'archives_identity', 'container_identity', 'fresh_identity'):
        value = row[key]
        if (not isinstance(value, list) or len(value) != 2
                or any(type(item) is not int or not 0 <= item < 2**128 for item in value)):
            raise ValueError('全局历史维护目录身份记录不正确，全部原件仍保留。')
    if (not isinstance(row['original'], dict) or set(row['original']) != {'identity', 'objects_identity', 'files'}
            or not isinstance(row['original']['files'], dict) or len(row['original']['files']) > 8192
            or not isinstance(row['source'], dict) or set(row['source']) != {'root', 'identity', 'files'}
            or not isinstance(row['source']['root'], str) or not isinstance(row['source']['files'], dict)
            or set(row['source']['files']) != set(files.FILES)):
        raise ValueError('全局历史维护原件关联不正确，全部原件仍保留。')
    return row


def pending(manager, library):
    scope = manager.scope(library)
    row = _load(unlinked(scope/INDEX), scope.name)
    return row if row and row['state'] not in TERMINAL else None


def _paths(manager, library, row):
    scope = unlinked(manager.scope(library))
    archives_root = unlinked(scope/ARCHIVES)
    container = unlinked(archives_root/row['id'])
    for path, expected in ((manager.directory, row['storage_identity']), (scope, row['scope_identity']),
                           (archives_root, row['archives_identity']), (container, row['container_identity'])):
        if _identity(path) != expected:
            raise ValueError('全局历史库或磁盘目录身份变化，未移动任何原件；请保留并重新核对。')
    for path in container.iterdir():
        unlinked(path)
        if path.name not in ('history', 'fresh', 'journal.json') and not _history().PENDING.fullmatch(path.name):
            raise ValueError('全局历史维护目录含未识别的原件，未移动或覆盖任何文件。')
    return scope, container


def _locations(manager, library, row):
    scope, container = _paths(manager, library, row)
    places = {}
    for label, path in (('active', scope/'global-history'), ('history', container/'history'), ('fresh', container/'fresh')):
        tree = _inventory(path)
        if tree is None:
            places[label] = None
        elif tree == row['original']:
            places[label] = 'original'
        elif tree == {'identity': row['fresh_identity'], 'objects_identity': None, 'files': {}}:
            places[label] = 'fresh'
        else:
            raise ValueError('全局历史在中断后有外部新写字节或目录变化，未覆盖任何原件；请核对后重新预览。')
    if (list(places.values()).count('original') != 1 or list(places.values()).count('fresh') != 1
            or places['history'] not in (None, 'original') or places['fresh'] not in (None, 'fresh')):
        raise ValueError('全局历史维护副本位置不能唯一核对，全部原件仍保留。')
    return places


def _save(manager, library, row, state):
    scope, container = _paths(manager, library, row)
    receipt = _load(unlinked(container/'journal.json'), scope.name)
    pointer = _load(unlinked(scope/INDEX), scope.name)
    if (receipt is not None and receipt['seal'] != row['seal']
            or pointer is not None and pointer['state'] not in TERMINAL and pointer['seal'] != row['seal']):
        raise ValueError('全局历史维护记录有外部新写内容，未覆盖记录或移动原件，请重新核对。')
    row = {**row, 'state': state}
    # A terminal receipt must be durable before the pointer stops reporting pending.
    # Preparation still finishes both copies before any directory exchange.
    _durable(container/'journal.json', row)
    _durable(scope/INDEX, row)
    return row


def _exchange(manager, library, row, direction, check):
    scope, container = _paths(manager, library, row)
    places = _locations(manager, library, row)
    check()
    places = _locations(manager, library, row)
    if direction == 'continue':
        if places['active'] == 'original':
            unlinked(scope/'global-history').rename(unlinked(container/'history'))
            _sync(scope); _sync(container)
        places = _locations(manager, library, row)
        check()
        places = _locations(manager, library, row)
        if places['fresh'] == 'fresh':
            unlinked(container/'fresh').rename(unlinked(scope/'global-history'))
            _sync(scope); _sync(container)
    else:
        if places['active'] == 'fresh':
            unlinked(scope/'global-history').rename(unlinked(container/'fresh'))
            _sync(scope); _sync(container)
        places = _locations(manager, library, row)
        check()
        places = _locations(manager, library, row)
        if places['history'] == 'original':
            unlinked(container/'history').rename(unlinked(scope/'global-history'))
            _sync(scope); _sync(container)
    _locations(manager, library, row)


def maintenance_recovery_preview(manager, root, library):
    row = pending(manager, library)
    if row is None:
        return None
    try:
        places = _locations(manager, library, row)
        can_cancel, reason = True, ''
    except (OSError, ValueError) as exc:
        return {'pending': True, 'id': row['id'], 'state': row['state'], 'can_continue': False,
                'can_cancel': False, 'continue_reason': str(exc), 'expected': None,
                'message': '发现未完成的全局历史维护；关联原件目前不能核对，未自动移动或覆盖任何文件。'}
    try:
        source = _source(root)
        can_continue = source == row['source'] and files.pending(manager, root) is None
        if not can_continue:
            reason = '当前游戏目录或全局源文件已变化，请取消此次维护后重新预览。'
    except (OSError, ValueError) as exc:
        source, can_continue, reason = None, False, '当前源文件暂不可核对，请恢复连接或取消后重新预览：'+str(exc)
    return {'pending': True, 'id': row['id'], 'state': row['state'], 'can_continue': can_continue,
            'can_cancel': can_cancel, 'continue_reason': reason,
            'expected': files.digest(files.encode({'journal': row, 'locations': places, 'source': source})),
            'message': '中断维护的全部原件仍保留。核对后可继续本地归档，或取消并恢复原活动历史；磁盘释放量均为0。'}


def _receipt(manager, root, library, row, direction):
    h = _history()
    if direction == 'continue' and manager.scope(root) == manager.scope(library):
        try:
            health = h.capture(manager, root)
        except (OSError, ValueError) as exc:
            health = h._health(manager, root, 'blocked', error=str(exc))
        manager.global_health = health
    elif manager.scope(root) != manager.scope(library):
        health = h._health(manager, root, 'archived')
    else:
        health = h.status(manager, root, library)['health']
    rows, damaged = h._scan(manager, library)
    space = h.usage(h.folder(manager, library))
    return {'ok': True, 'pending': False, 'direction': direction, 'archive_id': row['id'], 'mode': 'retain-local',
            'records': sum(name.endswith('.json') for name in row['original']['files']),
            'bytes': sum(item['bytes'] for item in row['original']['files'].values()),
            'active_after': {'count': len(rows)+len(damaged), 'bytes': space['bytes']},
            'disk_bytes_released': 0, 'health': health,
            'message': '已保留本地归档并恢复活动额度；当前保护结果见状态。所有原件仍在本地，磁盘释放量为0。'
                       if direction == 'continue' else '已取消维护并恢复原活动历史；全部原件及维护记录仍保留，磁盘释放量为0。'}


def maintain(manager, root, library, payload, check):
    with files._transaction_lock(manager, library):
        check()
        binding = _binding(manager, root, library)
        if payload.get('confirmed') is not True or payload.get('expected') != files.digest(files.encode(binding)):
            raise ValueError('请重新预览并明确确认本地保留归档；历史或当前源文件可能已变化，尚未移动原件。')
        scope = manager.scope(library)
        archives_root = unlinked(scope/ARCHIVES)
        archives_root.mkdir(exist_ok=True)
        operation = uuid.uuid4().hex
        container = unlinked(archives_root/operation)
        container.mkdir()
        fresh = unlinked(container/'fresh')
        fresh.mkdir()
        row = {'format': 1, 'kind': 'denghuo-global-history-maintenance', 'id': operation,
               'state': 'prepared', **binding, 'archives_identity': _identity(archives_root),
               'container_identity': _identity(container), 'fresh_identity': _identity(fresh)}
        row['seal'] = files.digest(files.encode({k: v for k, v in row.items() if k != 'state'}))
        if _binding(manager, root, library) != binding:
            raise ValueError('历史或当前源文件在准备期间变化；尚未移动原件，暂存和原件全部保留。')
        row = _save(manager, library, row, 'prepared')  # Durable association precedes the first rename.
        def guard():
            check()
            if _source(root) != row['source'] or files.pending(manager, root) is not None:
                raise ValueError('当前源文件或全局恢复状态变化，请重新预览中断维护；全部原件仍保留。')
        row = _save(manager, library, row, 'continuing')
        _exchange(manager, library, row, 'continue', guard)
        guard()
        row = _save(manager, library, row, 'completed')
    return _receipt(manager, root, library, row, 'continue')


def recover_maintenance(manager, root, library, payload, direction, check):
    with files._transaction_lock(manager, library):
        check()
        view = maintenance_recovery_preview(manager, root, library)
        if (not view or direction not in ('continue', 'cancel') or payload.get('confirmed') is not True
                or not view['expected'] or payload.get('expected') != view['expected']):
            raise ValueError('请重新预览并明确确认继续或取消全局历史维护；全部原件仍保留。')
        if not view['can_'+direction]:
            raise ValueError(view['continue_reason'])
        row = pending(manager, library)
        def guard():
            check()
            if direction == 'continue' and (_source(root) != row['source'] or files.pending(manager, root) is not None):
                raise ValueError('当前源文件已变化，请取消此次维护后重新预览；全部原件仍保留。')
        row = _save(manager, library, row, 'continuing' if direction == 'continue' else 'cancelling')
        _exchange(manager, library, row, direction, guard)
        guard()
        row = _save(manager, library, row, 'completed' if direction == 'continue' else 'cancelled')
    return _receipt(manager, root, library, row, direction)


def archive_directory(manager, library, archive_id):
    if not isinstance(archive_id, str) or not ARCHIVE_ID.fullmatch(archive_id):
        raise ValueError('请选择现有本地全局历史归档。')
    scope = manager.scope(library)
    container = unlinked(scope/ARCHIVES/archive_id)
    row = _load(unlinked(container/'journal.json'), scope.name)
    if not row or row['id'] != archive_id or row['state'] != 'completed':
        raise ValueError('全局历史归档关联不能核对，请先处理未完成的维护；原件仍保留。')
    # Completed receipts retain the source disk identities as evidence. A verified
    # backup-destination copy is a new container, so reads use the current storage
    # check and independently verify each selected manifest/object instead.
    manager.ensure_storage()
    _identity(scope)
    _identity(container)
    path = unlinked(container/'history')
    _identity(path)
    return path


def archives(manager, library):
    scope = manager.scope(library)
    base = unlinked(scope/ARCHIVES)
    if not base.exists():
        return []
    _identity(base)
    result = []
    # Each archive is a closed independent generation; its count never consumes active quota.
    for container in sorted(base.iterdir(), key=lambda path: path.name):
        try:
            unlinked(container)
            if not ARCHIVE_ID.fullmatch(container.name) or not container.is_dir():
                raise ValueError('本地全局归档含未识别的目录，未自动覆盖或移除；请核对保留位置。')
            row = _load(unlinked(container/'journal.json'), scope.name)
            if row is None:
                result.append({'id': container.name, 'state': 'unassociated', 'directory': str(container),
                               'count': 0, 'damaged_count': 0, 'bytes': 0, 'metadata_bytes': 0,
                               'disk_bytes_released': 0, 'error': '准备阶段保留目录尚无维护关联，未当作可恢复归档。'})
                continue
            if row['state'] != 'completed':
                continue
            directory = archive_directory(manager, library, container.name)
            count, damaged, latest = _summary(manager, library, container.name)
            tree = _inventory(directory)
            result.append({'id': container.name, 'state': 'completed', 'directory': str(directory),
                           'count': count, 'damaged_count': damaged, 'latest_usable': latest,
                           'bytes': sum(item['bytes'] for item in tree['files'].values()),
                           'disk_bytes_released': 0})
        except (OSError, ValueError) as exc:
            result.append({'id': container.name, 'state': 'damaged', 'directory': str(container),
                           'count': None, 'damaged_count': None, 'bytes': None,
                           'disk_bytes_released': 0, 'error': str(exc)})
    return result


def retained_usage(manager, library):
    """Count every local retained byte, including cancelled/pending receipts."""
    scope = manager.scope(library)
    base = unlinked(scope/ARCHIVES)
    content, metadata, unaccounted = 0, 0, 0
    if base.exists():
        for container in base.iterdir():
            try:
                unlinked(container)
                _identity(container)
                if not ARCHIVE_ID.fullmatch(container.name):
                    raise ValueError('未识别的归档目录')
            except (OSError, ValueError):
                unaccounted += 1
                continue
            for name in ('history', 'fresh'):
                try:
                    tree = _inventory(container/name)
                    if tree:
                        content += sum(item['bytes'] for item in tree['files'].values())
                except (OSError, ValueError):
                    unaccounted += 1
            for path in container.iterdir():
                if path.name in ('history', 'fresh'):
                    continue
                try:
                    if path.name != 'journal.json' and not _history().PENDING.fullmatch(path.name):
                        raise ValueError('未识别的归档原件')
                    raw = files.read(path)
                    metadata += len(raw) if raw is not None else 0
                except (OSError, ValueError):
                    unaccounted += 1
    try:
        raw = files.read(unlinked(scope/INDEX))
        metadata += len(raw) if raw is not None else 0
    except (OSError, ValueError):
        unaccounted += 1
    for path in scope.glob('.global-*.pending'):
        try:
            if not _history().PENDING.fullmatch(path.name):
                raise ValueError('未识别的维护原件')
            raw = files.read(path)
            metadata += len(raw) if raw is not None else 0
        except (OSError, ValueError):
            unaccounted += 1
    return {'archived_bytes': content, 'maintenance_bytes': metadata,
            'inventory_complete': not unaccounted, 'unaccounted_containers': unaccounted}


def archive_export(manager, library, archive_id):
    directory = archive_directory(manager, library, archive_id)
    tree = _inventory(directory)
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('archive.json', files.encode({'format': 1, 'kind': 'denghuo-global-history-archive',
            'library': manager.scope(library).name, 'archive': archive_id, 'files': tree['files'],
            'notice': '原始全局历史归档，包含损坏原件；不是迁移包。导出不减少本地空间或活动额度。'}))
        for name, metadata in sorted(tree['files'].items()):
            raw = files.read(directory/name)
            if raw is None or len(raw) != metadata['bytes'] or files.digest(raw) != metadata['sha256']:
                raise ValueError('归档原件在导出期间变化，请重新读取；全部原件仍保留。')
            archive.writestr('history/'+name, raw)
    if _inventory(directory) != tree:
        raise ValueError('归档目录在导出期间变化，请重新读取；全部原件仍保留。')
    return buffer.getvalue(), 'global-history-archive-'+archive_id[:12]+'.zip'


def damaged_export(manager, library, snapshot_id, archive_id=None):
    h = _history()
    if not isinstance(snapshot_id, str) or not h.ID.fullmatch(snapshot_id):
        raise ValueError('请选择现有损坏清单原件。')
    directory = h._directory(manager, library, archive_id)
    _, damaged = h._scan(manager, library, archive_id)
    if not any(row['id'] == snapshot_id for row in damaged):
        raise ValueError('所选损坏清单已变化，请重新读取。')
    raw = files.read(directory/(snapshot_id+'.json'))
    if raw is None:
        raise ValueError('所选清单原件不存在，请重新读取。')
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('damaged-manifest/'+snapshot_id+'.json', raw)
        archive.writestr('retained-original.json', files.encode({'bytes': len(raw), 'sha256': files.digest(raw),
            'notice': '损坏清单原始字节，不是有效历史或迁移包；导出不释放活动额度或磁盘空间。'}))
    return buffer.getvalue(), 'global-history-damaged-'+snapshot_id[:12]+'.zip'
