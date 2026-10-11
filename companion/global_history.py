"""Independent automatic raw history for badges and rankings, with explicit recovery."""
from __future__ import annotations

from io import BytesIO
from itertools import islice
import json
import math
from pathlib import Path
import re
import stat
import uuid
import zipfile

from . import global_progress as files
from .backups import unlinked, check_capture_deadline

MAX_SNAPSHOTS = 512
MAX_STORAGE = 64 * 1024 * 1024
ID = re.compile(r'[0-9a-f]{64}\Z')
PENDING = re.compile(r'\.global-[0-9a-f]{32}\.pending\Z')


def folder(manager, library):
    return unlinked(manager.scope(library)/'global-history')


def usage(directory):
    total, pending = 0, 0
    for base in (directory, unlinked(directory/'objects')):
        if not base.exists():
            continue
        if not base.is_dir():
            raise ValueError('全局历史目录类型变化，原件仍保留。')
        entries = list(islice(base.iterdir(), 4097))
        if len(entries) > 4096:
            raise ValueError('全局历史目录条目超过容量；尚未新增，原件仍保留。')
        for path in entries:
            unlinked(path)
            if path == directory/'objects' and path.is_dir():
                continue
            attrs = path.stat()
            suffix = '.json' if base == directory else '.dat'
            temporary = bool(PENDING.fullmatch(path.name))
            if (not stat.S_ISREG(attrs.st_mode) or attrs.st_nlink != 1 or attrs.st_size > files.MAX_BYTES
                    or not temporary and not (path.suffix == suffix and ID.fullmatch(path.stem))):
                raise ValueError('全局历史包含未识别或不安全的原件，已暂停新增；请核对保留目录。')
            total += attrs.st_size
            pending += int(temporary)
    return {'bytes': total, 'limit': MAX_STORAGE, 'pending_originals': pending}


def _directory(manager, library, archive_id=None):
    if archive_id is None:
        return folder(manager, library)
    from .global_history_maintenance import archive_directory
    return archive_directory(manager, library, archive_id)


def _record(path, library_key):
    raw = files.read(path)
    if raw is None or len(raw) > 65536 or not ID.fullmatch(path.stem) or files.digest(raw) != path.stem:
        raise ValueError('全局历史清单校验失败，原始清单仍保留。')
    try:
        row = json.loads(raw, object_pairs_hook=files.unique_fields, parse_constant=files.invalid_constant)
    except (ValueError, RecursionError) as exc:
        raise ValueError('全局历史清单损坏，原始清单仍保留。') from exc
    if (not isinstance(row, dict) or set(row) != {'format', 'kind', 'library', 'sequence', 'time', 'files'}
            or type(row['format']) is not int or row['format'] != 1 or row['kind'] != 'denghuo-global-history'
            or row['library'] != library_key or type(row['sequence']) is not int or row['sequence'] < 1
            or type(row['time']) not in (int, float) or not math.isfinite(row['time']) or row['time'] < 0
            or not isinstance(row['files'], dict) or not row['files'] or set(row['files'])-set(files.FILES)):
        raise ValueError('全局历史清单结构不兼容，原始清单仍保留。')
    for item in row['files'].values():
        if (not isinstance(item, dict) or set(item) != {'sha256', 'bytes', 'valid', 'summary', 'error'}
                or not isinstance(item['sha256'], str) or not ID.fullmatch(item['sha256'])
                or type(item['bytes']) is not int or not 0 <= item['bytes'] <= files.MAX_BYTES
                or type(item['valid']) is not bool or not isinstance(item['error'], str) or len(item['error']) > 1000
                or item['valid'] and (not isinstance(item['summary'], dict) or item['error'])
                or not item['valid'] and (item['summary'] is not None or not item['error'])):
            raise ValueError('全局历史文件关联不正确，原始清单仍保留。')
    return {**row, 'id': path.stem}


def _scan(manager, library, archive_id=None, deadline=None):
    directory = _directory(manager, library, archive_id)
    library_key = manager.scope(library).name
    paths = list(islice(directory.glob('*.json'), 4097))
    if len(paths) > 4096:
        raise ValueError('全局历史目录条目超过容量，全部原件仍保留。')
    result, damaged = [], []
    for path in paths:
        check_capture_deadline(deadline)
        try:
            result.append(_record(path, library_key))
        except (OSError, ValueError) as exc:
            try:
                raw = files.read(path)
            except (OSError, ValueError):
                raw = None
            damaged.append({'id': path.stem, 'bytes': len(raw) if raw is not None else None,
                            'sha256': files.digest(raw), 'error': str(exc), 'available': raw is not None})
    manager.ensure_storage()
    check_capture_deadline(deadline)
    return sorted(result, key=lambda row: (row['sequence'], row['time'], row['id']), reverse=True), damaged


def records(manager, library, archive_id=None):
    """Return independently valid manifests; damaged originals remain in status."""
    return _scan(manager, library, archive_id)[0]


def _names(row, selected_names):
    if selected_names is None:
        return list(row['files'])
    if (not isinstance(selected_names, list) or not 1 <= len(selected_names) <= 2
            or any(not isinstance(name, str) or name not in row['files'] for name in selected_names)
            or len(set(selected_names)) != len(selected_names)):
        raise ValueError('请明确选择要处理的全局历史文件。')
    return selected_names


def raw_files(manager, library, row, selected_names=None, archive_id=None):
    directory = _directory(manager, library, archive_id)
    return _raw_files(directory, row, selected_names)


def _raw_files(directory, row, selected_names=None):
    result = {}
    for name in _names(row, selected_names):
        metadata = row['files'][name]
        raw = files.read(directory/'objects'/(metadata['sha256']+'.dat'))
        if raw is None or len(raw) != metadata['bytes'] or files.digest(raw) != metadata['sha256']:
            raise ValueError('全局历史原始副本缺失或字节变化，尚未恢复；保留其他原件。')
        result[name] = raw
    return result


def _inspected_rows(manager, library, history, archive_id=None, deadline=None):
    directory = _directory(manager, library, archive_id)
    result, cache = [], {}
    for row in history:
        entries = {}
        for name, metadata in row['files'].items():
            check_capture_deadline(deadline)
            key = (name, metadata['sha256'], metadata['bytes'])
            if key not in cache:
                try:
                    raw = _raw_files(directory, row, [name])[name]
                except (OSError, ValueError) as exc:
                    cache[key] = {'valid': False, 'integrity': 'damaged', 'summary': None, 'error': str(exc)}
                else:
                    try:
                        summary = files.validate(name, raw)
                        cache[key] = {'valid': True, 'integrity': 'verified', 'summary': summary, 'error': ''}
                    except ValueError as exc:
                        cache[key] = {'valid': False, 'integrity': 'verified', 'summary': None, 'error': str(exc)}
            entries[name] = {**metadata, **cache[key]}
        result.append({**row, 'files': entries})
    manager.ensure_storage()
    check_capture_deadline(deadline)
    return result


def _publish(path, raw):
    temporary = unlinked(path.parent/('.global-'+uuid.uuid4().hex+'.pending'))
    files._write_new(temporary, raw)
    temporary.replace(unlinked(path))


def _source(root, deadline=None):
    check_capture_deadline(deadline)
    identity = files.root_identity(root)
    raw = {}
    for name in files.FILES:
        check_capture_deadline(deadline)
        raw[name] = files.read(Path(root)/name)
    check_capture_deadline(deadline)
    if files.root_identity(root) != identity:
        raise ValueError('读取期间游戏目录身份变化，尚未确认全局进度保护。')
    return identity, {name: value for name, value in raw.items() if value is not None}


def _health(manager, root, state, **extra):
    return {'root': str(Path(root)), 'state': state, 'protected': state == 'protected',
            'raw_retained': False, 'error': '', 'checked_at': manager.clock(), **extra}


def _matching_current(directory, library_key, entries, deadline):
    """Confirm an existing copy of current bytes; timestamps only prioritize reads."""
    paths = list(islice(directory.glob('*.json'), 4097))
    if len(paths) > 4096:
        raise ValueError('全局历史目录条目超过容量，全部原件仍保留。')
    candidates = []
    for path in paths:
        check_capture_deadline(deadline)
        try:
            candidates.append((path.lstat().st_mtime_ns, path))
        except OSError:
            continue
    digests = {name: item['sha256'] for name, item in entries.items()}
    for _, path in sorted(candidates, key=lambda item: item[0], reverse=True):
        check_capture_deadline(deadline)
        try:
            row = _record(path, library_key)
        except (OSError, ValueError):
            continue
        if {name: item['sha256'] for name, item in row['files'].items()} == digests:
            _raw_files(directory, row)
            return row
    return None


def capture(manager, root, deadline=None):
    """Read only the two game originals; slot validity and restores are independent."""
    check_capture_deadline(deadline)
    manager.ensure_storage()
    if not manager.enabled:
        return _health(manager, root, 'paused')
    from .global_history_maintenance import pending as maintenance_pending
    with files._transaction_lock(manager, root):
        check_capture_deadline(deadline)
        if files.pending(manager, root) is not None:
            raise ValueError('有未完成的全局进度恢复，请先预览恢复原件；自动全局历史暂未更新。')
        if maintenance_pending(manager, root) is not None:
            raise ValueError('有未完成的全局历史维护，请先预览并继续或取消；自动全局历史暂未更新。')
        try:
            initial_identity, source = _source(root, deadline)
        except FileNotFoundError:
            return _health(manager, root, 'waiting')
        if not source:
            return _health(manager, root, 'waiting')
        identity, current = _source(root, deadline)
        if identity != initial_identity or current != source:
            raise ValueError('全局进度正在变化，稍后自动重试；原件仍保留。')
        directory = folder(manager, root)
        entries = {}
        for name, raw in current.items():
            try:
                summary, error = files.validate(name, raw), ''
            except ValueError as exc:
                summary, error = None, str(exc)[:1000]
            entries[name] = {'bytes': len(raw), 'sha256': files.digest(raw), 'valid': not error,
                             'summary': summary, 'error': error}
        error = '；'.join(item['error'] for item in entries.values() if item['error'])
        if deadline is not None:
            row = _matching_current(directory, manager.scope(root).name, entries, deadline)
            if row is not None:
                manager.ensure_storage()
                if _source(root, deadline) != (identity, current):
                    raise ValueError('确认期间全局进度变化，稍后自动重试；尚未确认保护。')
                return _health(manager, root, 'warning' if error else 'protected', raw_retained=True,
                               error=error, snapshot_id=row['id'], files=entries)
        history, damaged = _scan(manager, root, deadline=deadline)
        space = usage(directory)
        if damaged:
            raise ValueError('全局历史有损坏清单，已保留并暂停新增；健康记录仍可用，请预览本地保留归档后重建保护。')
        inspected = _inspected_rows(manager, root, history, deadline=deadline)
        if any(item['integrity'] == 'damaged' for row in inspected for item in row['files'].values()):
            raise ValueError('全局历史原始副本缺失或字节变化，已暂停新增；请预览本地保留归档后重建保护。')
        unchanged = bool(history and {k: v['sha256'] for k, v in history[0]['files'].items()}
                         == {k: v['sha256'] for k, v in entries.items()})
        if unchanged:
            row = history[0]
            raw_files(manager, root, row)
        else:
            if len(history) >= MAX_SNAPSHOTS:
                raise ValueError('全局历史已达512份，已有历史保留；新变化尚未保护，请预览本地保留归档并恢复活动额度。')
            row = {'format': 1, 'kind': 'denghuo-global-history', 'library': manager.scope(root).name,
                   'sequence': max((item['sequence'] for item in history), default=0)+1,
                   'time': manager.clock(), 'files': entries}
            raw_record = files.encode(row)
            required = len(raw_record)
            for raw in current.values():
                path = directory/'objects'/(files.digest(raw)+'.dat')
                if path.exists():
                    if files.read(path) != raw:
                        raise ValueError('全局历史原始副本校验失败，新变化尚未保护；原件仍保留。')
                else:
                    required += len(raw)
            if space['bytes']+required > MAX_STORAGE:
                raise ValueError('全局历史已达64 MiB，已有历史保留；新变化尚未保护，请预览本地保留归档并恢复活动额度。')
            unlinked(directory/'objects').mkdir(parents=True, exist_ok=True)
            for raw in current.values():
                check_capture_deadline(deadline)
                path = directory/'objects'/(files.digest(raw)+'.dat')
                if not path.exists():
                    _publish(path, raw)
            # Confirm the selected volume and current originals immediately before publishing a snapshot.
            manager.ensure_storage()
            if _source(root, deadline) != (identity, current):
                raise ValueError('备份期间全局进度变化，原始副本已保留；稍后重试，尚未确认保护。')
            row['id'] = files.digest(raw_record)
            check_capture_deadline(deadline)
            _publish(directory/(row['id']+'.json'), raw_record)
        manager.ensure_storage()
        if _source(root, deadline) != (identity, current):
            raise ValueError('确认期间全局进度变化，稍后自动重试；尚未确认保护。')
        return _health(manager, root, 'warning' if error else 'protected', raw_retained=True,
            error=error, snapshot_id=row['id'], files=entries, count=len(history)+int(not unchanged),
            pending_originals=space['pending_originals'])


def status(manager, root, library, archive_id=None):
    from . import global_history_maintenance as maintenance
    directory = _directory(manager, library, archive_id)
    history, damaged = _scan(manager, library, archive_id)
    history = _inspected_rows(manager, library, history, archive_id)
    space = usage(directory)
    archives = maintenance.archives(manager, library)
    retained = maintenance.retained_usage(manager, library)
    if archive_id is None:
        active_rows, active_damaged, active_space = history, damaged, space
    else:
        active_rows, active_damaged = _scan(manager, library)
        active_space = usage(folder(manager, library))
    space.update(active_count=len(active_rows)+len(active_damaged), active_bytes=active_space['bytes'],
        archived_count=sum(row['count'] or 0 for row in archives), **retained)
    space['archived_count_complete'] = all(row['count'] is not None for row in archives)
    space['total_local_bytes'] = space['active_bytes']+space['archived_bytes']+space['maintenance_bytes']
    current_library = manager.scope(root).name == manager.scope(library).name
    health = _health(manager, root, 'archived' if not current_library or archive_id else 'paused' if not manager.enabled else 'waiting')
    try:
        pending_maintenance = maintenance.maintenance_recovery_preview(manager, root, library)
    except (OSError, ValueError) as exc:
        pending_maintenance = {'pending': True, 'state': 'unrecognized', 'can_continue': False,
                              'can_cancel': False, 'expected': None, 'continue_reason': str(exc)}
    pending_restore = None
    if current_library:
        try:
            pending_restore = files.pending(manager, root)
        except (OSError, ValueError) as exc:
            pending_restore = {'error': str(exc)}
    integrity_error = bool(damaged or any(item['integrity'] == 'damaged'
        for row in history for item in row['files'].values()))
    if current_library and manager.enabled and not archive_id:
        try:
            if pending_restore or pending_maintenance:
                raise ValueError('有未完成的全局进度恢复或全局历史维护，请先预览并处理；自动保护尚未确认。')
            if integrity_error:
                raise ValueError('全局历史有损坏原件，健康记录仍可用；请预览本地保留归档后重建保护。')
            _, current = _source(root)
            if current:
                match = bool(history and {k: files.digest(v) for k, v in current.items()}
                             == {k: v['sha256'] for k, v in history[0]['files'].items()})
                if match:
                    raw_files(manager, library, history[0])
                    errors = []
                    for name, raw in current.items():
                        try:
                            files.validate(name, raw)
                        except ValueError as exc:
                            errors.append(str(exc))
                    health = _health(manager, root, 'warning' if errors else 'protected', raw_retained=True,
                                     error='；'.join(errors), snapshot_id=history[0]['id'], files=history[0]['files'])
                else:
                    health = _health(manager, root, 'working', error='当前全局文件有新变化，等待自动历史捕获。')
                    published = manager.global_health_status(root)
                    if published['state'] == 'blocked':
                        health = published
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            health = _health(manager, root, 'blocked', error=str(exc))
    return {'library': manager.scope(library).name, 'current_library': current_library, 'health': health,
            'directory': str(directory), 'history': history, 'storage': space, 'snapshot_limit': MAX_SNAPSHOTS,
            'archive': archive_id, 'archives': archives, 'damaged_rows': damaged,
            'pending_maintenance': pending_maintenance, 'pending_restore': bool(pending_restore),
            'version_notice': '文件没有来源版本信息。结构校验使用官方4.0.2参考；恢复需另行确认版本与关闭游戏。'}


def selected(manager, library, snapshot_id, selected_names=None, archive_id=None):
    if not isinstance(snapshot_id, str) or not ID.fullmatch(snapshot_id):
        raise ValueError('请选择现有全局历史快照。')
    row = next((row for row in records(manager, library, archive_id) if row['id'] == snapshot_id), None)
    if row is None:
        raise ValueError('全局历史快照已变化，请重新读取。')
    return row, raw_files(manager, library, row, selected_names, archive_id)


def export(manager, library, snapshot_id, selected_names=None, archive_id=None):
    row, raw = selected(manager, library, snapshot_id, selected_names, archive_id)
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('global-history.json', files.encode({**row, 'files': {
            name: row['files'][name] for name in raw}}))
        for name, value in raw.items():
            archive.writestr('global/'+name, value)
    return buffer.getvalue(), 'global-history-'+snapshot_id[:12]+'.zip'


def portable_export(manager, library, payload):
    """Use the existing migration format, after an explicit source-version declaration."""
    from . import __version__, migration
    names = payload.get('selected')
    if names is None:
        raise ValueError('请明确选择要导出的全局历史文件。')
    _, raw = selected(manager, library, payload['id'], names, payload.get('archive'))
    if payload.get('version') != files.VERSION or payload.get('version_confirmed') is not True:
        raise ValueError('请核对历史来源为官方4.0.2；不能从助手资料版本推断来源。')
    contents, entries = {}, {}
    for name in sorted(names):
        summary = files.validate(name, raw[name])
        contents['global/'+name] = raw[name]
        entries[name] = {'bytes': len(raw[name]), 'sha256': files.digest(raw[name]), 'summary': summary}
    contents['global-progress.json'] = files.encode({'format': 1, 'kind': 'denghuo-global-progress',
        'version': files.VERSION, 'version_basis': 'user-declared', 'reference': files.REFERENCE, 'files': entries})
    contents[migration.INDEX] = files.encode({'format': 1, 'kind': 'denghuo-portable-bundle',
        'source': {'application': '灯火', 'application_version': __version__, 'rules_version': files.VERSION},
        'members': {name: {'bytes': len(value), 'sha256': files.digest(value)} for name, value in contents.items()}})
    return migration._zip(contents), 'global-history-migration-'+payload['id'][:12]+'.zip'


def preview(manager, root, library, snapshot_id, selected_names=None, archive_id=None):
    row, raw = selected(manager, library, snapshot_id, selected_names, archive_id)
    manager.closed_check()
    target = files.target(manager, root, raw)
    rows = []
    for name, value in raw.items():
        original = files.read(Path(root)/name)
        try:
            summary, error = files.validate(name, value), ''
        except ValueError as exc:
            summary, error = None, str(exc)
        rows.append({'name': name, 'source': summary, 'valid': not error, 'error': error, 'bytes': len(value),
                     'target_exists': original is not None, 'same_bytes': original == value})
    binding = {'snapshot': snapshot_id, 'library': manager.scope(library).name, 'archive': archive_id,
               'selected': sorted(raw), 'source': {name: files.digest(value) for name, value in raw.items()}, 'target': target,
               'storage_identity': files.root_identity(manager.directory),
               'scope_identity': files.root_identity(manager.scope(library)),
               'history_identity': files.root_identity(_directory(manager, library, archive_id))}
    if archive_id:
        binding['archive_journal'] = files.digest(files.read(_directory(manager, library, archive_id).parent/'journal.json'))
    expected = files.digest(files.encode(binding))
    return {'id': snapshot_id, 'library': manager.scope(library).name, 'files': rows, 'expected': expected,
            'message': '逐份选择要恢复的文件。确认后先保留当前原件，再恢复所选全局文件；请关闭游戏并核对来源与当前游戏版本。'}


def restore(manager, root, library, payload, check):
    view = preview(manager, root, library, payload['id'], payload.get('selected'), payload.get('archive'))
    if payload.get('expected') != view['expected']:
        raise ValueError('全局文件或历史快照已变化，请重新预览；尚未恢复。')
    if payload.get('confirmed') is not True or payload.get('version') != files.VERSION or payload.get('version_confirmed') is not True:
        raise ValueError('请明确确认恢复，并核对来源和当前游戏均为官方4.0.2；不能从局内存档推断。')
    choices = payload.get('choices')
    names = {row['name'] for row in view['files']}
    if (not isinstance(choices, dict) or set(choices) != names or any(value not in ('keep', 'replace') for value in choices.values())):
        raise ValueError('请逐份选择保留当前文件或恢复历史副本。')
    chosen = [name for name in files.FILES if choices.get(name) == 'replace']
    if not chosen:
        raise ValueError('请至少明确选择一份要恢复的全局文件。')
    if any(not row['valid'] for row in view['files'] if row['name'] in chosen):
        raise ValueError('所选全局历史文件损坏或结构不支持；可导出原始字节，尚未恢复。')
    row, raw = selected(manager, library, payload['id'], payload.get('selected'), payload.get('archive'))
    target = files.target(manager, root, chosen)
    if preview(manager, root, library, payload['id'], payload.get('selected'), payload.get('archive'))['expected'] != payload['expected']:
        raise ValueError('全局文件在确认期间变化，请重新预览；尚未恢复。')
    result = files.apply(manager, root, {'global/'+name: raw[name] for name in chosen}, chosen, target, check)
    return {**result, 'ok': True, 'restored': chosen,
            'message': '所选全局文件已恢复，原文件和历史快照均保留；局内存档与槽位撤回关系保持原状。'}


# The separate module owns only local history directory exchanges, never game writes.
from .global_history_maintenance import (maintenance_preview, maintain, maintenance_recovery_preview,
    recover_maintenance, archive_export, damaged_export)
