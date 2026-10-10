"""Explicit, byte-bound copies between local automatic backup destinations."""
from __future__ import annotations

import hashlib
from itertools import islice
import json
import os
from pathlib import Path
import re
import shutil
import stat
import uuid

from .backup_archive import IDENTITY, read_archive
from .backups import BackupLibrary, BackupManager, MAX_HISTORY, MAX_STORAGE, MAX_TOTAL, atomic_json, unlinked

CONTAINERS = ('backups', 'backup-recycle', 'backup-quarantine')
LIBRARY = re.compile(r'[0-9a-f]{24}\Z')
MARKER = '.denghuo-backup-destination.json'
REGISTRY = 'backup-destinations.json'
MAX_ENTRIES = 20000
MAX_COPY = 2 * 1024 * 1024 * 1024


def normalize_root(value):
    if not isinstance(value, str) or len(value) > 1000 or '\x00' in value:
        raise ValueError('备份目录格式不正确')
    value = value.strip()
    if not value:
        return ''
    path = Path(value)
    if not path.is_absolute() or value.startswith(('\\\\', '//')):
        raise ValueError('请选择绝对路径的本地备份目录')
    return str(unlinked(path).resolve())


def base_directory(config_path, backup_root):
    return Path(backup_root) if backup_root else unlinked(Path(config_path).parent).resolve()


def _json(path, maximum=65536):
    attrs = unlinked(path).stat()
    if not stat.S_ISREG(attrs.st_mode) or attrs.st_size > maximum:
        raise ValueError('备份目的地记录类型或大小不正确，原件仍保留')
    with unlinked(path).open('rb') as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError('备份目的地记录过大，原件仍保留')
    try:
        return json.loads(raw)
    except (ValueError, RecursionError) as exc:
        raise ValueError('备份目的地记录损坏，原件仍保留') from exc


def _marker(base):
    path = unlinked(base / MARKER)
    if not path.exists():
        return None
    value = _json(path)
    if (not isinstance(value, dict) or set(value) != {'format', 'id'} or type(value['format']) is not int or value['format'] != 1
            or not isinstance(value['id'], str) or not re.fullmatch(r'[0-9a-f]{32}', value['id'])):
        raise ValueError('备份目的地身份记录损坏，原件仍保留')
    return value['id']


def registry(config_path):
    path = Path(config_path).parent / REGISTRY
    try:
        value = _json(path)
    except FileNotFoundError:
        return {}
    if (not isinstance(value, dict) or len(value) > 256
            or any(not isinstance(root, str) or not isinstance(identity, str)
                   or not re.fullmatch(r'[0-9a-f]{32}', identity) for root, identity in value.items())):
        raise ValueError('备份目的地身份记录损坏，原件仍保留')
    return value


def storage_check(config_path, backup_root):
    """Never mkdir a selected directory: its marker must survive reconnect/restart."""
    if not backup_root:
        return None
    def check():
        base = unlinked(Path(backup_root))
        if not base.is_dir():
            raise ValueError('选定备份目录暂时不可用，自动备份已暂停；请重新连接磁盘或明确更换目录')
        expected = registry(config_path).get(backup_root)
        if not expected or _marker(base) != expected:
            raise ValueError('选定备份目录身份无法确认，自动备份已暂停；请重新连接原磁盘或重新预览并确认目录')
    return check


def manager_for(config_path, backup_root, **kwargs):
    return BackupManager(base_directory(config_path, backup_root) / 'backups',
                         storage_check=storage_check(config_path, backup_root), **kwargs)


def status(session):
    error = ''
    try:
        session.backups.ensure_storage()
    except (OSError, ValueError) as exc:
        error = str(exc)
    return {'backup_root': session.settings.get('backup_root', ''),
            'directory': str(session.backups.directory),
            'default_directory': str(session.config_path.parent.resolve() / 'backups'),
            'settings_revision': session.settings_revision, 'context': session.backup_context,
            'available': not error, 'error': error}


def _stamp(path):
    attrs = unlinked(path).stat()
    if not stat.S_ISREG(attrs.st_mode) or attrs.st_size > MAX_TOTAL or attrs.st_nlink > 1:
        raise ValueError('备份目的地包含非普通文件、硬链接或过大文件，原件仍保留')
    return attrs.st_size, attrs.st_mtime_ns, attrs.st_ino, attrs.st_dev


def _hash(path):
    before = _stamp(path)
    digest, total = hashlib.sha256(), 0
    with path.open('rb') as stream:
        while chunk := stream.read(65536):
            total += len(chunk)
            if total > MAX_TOTAL:
                raise ValueError('备份文件在核对时变化，请重新预览')
            digest.update(chunk)
    if _stamp(path) != before or total != before[0]:
        raise ValueError('备份文件在核对时变化，请重新预览')
    return {'bytes': total, 'sha256': digest.hexdigest(), 'stamp': before}


def _tree(base):
    """Scan only the three owned containers, never arbitrary chosen-folder children."""
    files, directories, total, entries = {}, [], 0, 0
    for name in CONTAINERS:
        container = unlinked(base / name)
        if not container.exists():
            continue
        if not container.is_dir():
            raise ValueError(f'目标的 {name} 不是备份目录，尚未覆盖')
        pending = [container]
        while pending:
            folder = pending.pop()
            directories.append(folder.relative_to(base).as_posix())
            children = list(islice(folder.iterdir(), MAX_ENTRIES + 1))
            for path in sorted(children):
                entries += 1
                unlinked(path)
                relative = path.relative_to(base).as_posix()
                if entries > MAX_ENTRIES:
                    raise ValueError('备份目的地内容超过20000项，未复制；原件仍保留')
                if folder == container and not (path.name == 'preferences.json' and name == 'backups'):
                    if not LIBRARY.fullmatch(path.name) or not path.is_dir():
                        raise ValueError(f'备份目录含未识别内容 {relative}，尚未覆盖；请另选目录或先核对原件')
                if path.is_dir():
                    pending.append(path)
                else:
                    record = _hash(path)
                    total += record['bytes']
                    if total > MAX_COPY:
                        raise ValueError('备份目的地内容超过2 GiB，未复制；原件仍保留')
                    files[relative] = record
    return {'files': files, 'directories': sorted(directories), 'bytes': total}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def _verify(base, tree):
    manager = BackupManager(base / 'backups')
    count = 0
    for relative in tree['files']:
        parts = Path(relative).parts
        if len(parts) == 3 and parts[0] == 'backups' and LIBRARY.fullmatch(parts[1]):
            reference = BackupLibrary(parts[1])
            name = parts[2]
            if name.endswith('.zip'):
                if not IDENTITY.fullmatch(Path(name).stem):
                    raise ValueError(f'活动备份文件名未识别：{relative}；请先核对原件')
                read_archive(base / relative, identity=Path(name).stem)
                count += 1
            elif name == 'history.json':
                rows = manager.history(reference, discover=False)
                for row in rows:
                    read_archive(base / 'backups' / parts[1] / (row['id'] + '.zip'),
                                 identity=row['id'], slot=row['slot'])
            elif name == 'timeline.json':
                manager.events(reference)
            elif name == 'restores.json':
                manager.journals(reference)
            elif name == 'stages.json':
                manager.stage_records(reference)
            elif name == 'restores-pending.json':
                from .backup_recovery import records
                records(manager, reference)
    return count


def _index_merge(relative, source, target):
    parts = Path(relative).parts
    if len(parts) != 3 or parts[0] != 'backups' or not LIBRARY.fullmatch(parts[1]):
        raise ValueError(f'目标已有不同内容：{relative}；尚未覆盖')
    name, reference = parts[2], BackupLibrary(parts[1])
    a, b = BackupManager(source / 'backups'), BackupManager(target / 'backups')
    if name == 'history.json':
        rows = {(r['slot'], r['id']): r for r in b.history(reference, discover=False)}
        for row in a.history(reference, discover=False):
            key = row['slot'], row['id']
            if key in rows:
                # Target labels, fixed state and CAS generation remain its own.
                rows[key]['time'] = min(rows[key]['time'], row['time'])
                rows[key]['last_seen'] = max(rows[key]['last_seen'], row['last_seen'])
            else:
                rows[key] = row
        if len(rows) > MAX_HISTORY:
            raise ValueError('合并后的历史超过容量，尚未复制；原件仍保留')
        value = list(rows.values())
        for row in value:
            row.pop('metadata_revision', None)
    elif name == 'timeline.json':
        rows = {_digest(row): row for row in b.events(reference) + a.events(reference)}
        value = sorted(rows.values(), key=lambda r: (r['time'], r['slot'], r['id']))
        if len(value) > 3000:
            raise ValueError('合并后的时间记录超过容量，尚未复制；原件仍保留')
    elif name == 'restores.json':
        rows = {r['id']: r for r in b.journals(reference)}
        for row in a.journals(reference):
            old = rows.get(row['id'])
            if old is not None and {k: v for k, v in old.items() if k != 'active'} != {k: v for k, v in row.items() if k != 'active'}:
                raise ValueError('目标撤回关系冲突，尚未复制；原件仍保留')
            rows[row['id']] = row
        value = list(rows.values())
        active = [r['slot'] for r in value if r['active']]
        if len(active) != len(set(active)):
            raise ValueError('目标存在另一条有效撤回关系，尚未复制；原件仍保留')
    elif name == 'stages.json':
        value = b.stage_records(reference)
        for key, row in a.stage_records(reference).items():
            if key in value and value[key] != row:
                raise ValueError('目标暂存来源冲突，尚未复制；原件仍保留')
            value[key] = row
    elif name == 'restores-pending.json':
        from .backup_recovery import records
        value = records(b, reference)
        for key, row in records(a, reference).items():
            if key in value and value[key] != row:
                raise ValueError('目标存在另一条未完成的回档恢复关联，尚未复制；全部副本保留')
            value[key] = row
        value = {'format': 1, 'operations': value}
    else:
        raise ValueError(f'目标已有不同内容：{relative}；尚未覆盖')
    raw = json.dumps(value, ensure_ascii=True, indent=2).encode()
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError('合并后的索引过大，尚未复制；原件仍保留')
    return raw


def plan(session, backup_root, *, start_new=False):
    if type(start_new) is not bool:
        raise ValueError('新位置继续备份选项必须是布尔值')
    backup_root = normalize_root(backup_root)
    source = unlinked(session.backups.directory.parent).resolve()
    target = unlinked(base_directory(session.config_path, backup_root))
    if not target.is_dir():
        raise ValueError('备份目的地目录不存在；请先在本地磁盘创建目录再预览')
    if not os.access(target, os.W_OK):
        raise ValueError('备份目的地不可写，请检查本地目录的访问权限')
    save = Path(session.settings['save_root']).resolve()
    if backup_root and (target == save or save in target.parents):
        raise ValueError('备份目的地不能位于活动游戏存档目录中')
    if source != target:
        for left in CONTAINERS:
            for right in CONTAINERS:
                a, b = source / left, target / right
                if a == b or a in b.parents or b in a.parents:
                    raise ValueError('新旧备份目录相互包含，请选择独立目录')
    source_error = ''
    try:
        session.backups.ensure_storage()
    except (OSError, ValueError) as exc:
        source_error = str(exc)
        if not start_new or source == target:
            raise ValueError(source_error + '；如需先在另一位置继续，请明确选择保留离线旧历史并重新预览') from exc
    if start_new and not source_error:
        raise ValueError('原备份目录仍可用，请取消“旧盘暂不可用”选项后预览并复制完整历史')
    # Explicit offline recovery never scans the now-unmounted source path.
    source_tree = {'files': {}, 'directories': [], 'bytes': 0} if start_new else _tree(source)
    target_tree = source_tree if source == target else _tree(target)
    verified = 0 if start_new else _verify(source, source_tree)
    if source != target:
        _verify(target, target_tree)
    merged = {}
    enabled = getattr(session, 'backup_enabled', session.backups.enabled)
    preferences = json.dumps({'enabled': enabled}, indent=2).encode()
    if source != target:
        for relative in source_tree['files'].keys() & target_tree['files'].keys():
            if relative == 'backups/preferences.json':
                continue
            if source_tree['files'][relative]['sha256'] != target_tree['files'][relative]['sha256']:
                merged[relative] = _index_merge(relative, source, target)
    identity = _marker(target) if backup_root else None
    binding = {'source': str(source), 'target': str(target), 'backup_root': backup_root,
               'source_tree': source_tree, 'target_tree': target_tree, 'marker': identity,
               'settings_revision': session.settings_revision, 'context': session.backup_context,
               'save_root': session.settings['save_root'], 'enabled': enabled,
               'start_new': start_new, 'source_error': source_error,
               'target_identity': [target.stat().st_dev, target.stat().st_ino],
               'marker_bytes': _hash(target / MARKER)['sha256'] if identity else None,
               'merged': {name: hashlib.sha256(raw).hexdigest() for name, raw in merged.items()}}
    used = sum(record['bytes'] for relative, record in target_tree['files'].items()
               if relative.startswith('backups/') and relative.endswith('.zip'))
    used += sum(record['bytes'] for relative, record in source_tree['files'].items()
                if relative.startswith('backups/') and relative.endswith('.zip') and relative not in target_tree['files'])
    if used > MAX_STORAGE:
        raise ValueError('合并后的活动备份超过512 MiB，尚未复制；原件仍保留')
    required = source_tree['bytes'] + target_tree['bytes'] + sum(len(raw) for raw in merged.values())
    union = {**target_tree['files'], **source_tree['files']}
    if sum(len(merged[name]) if name in merged else record['bytes'] for name, record in union.items()) > MAX_COPY:
        raise ValueError('合并后的备份超过2 GiB，尚未复制；原件仍保留')
    free = shutil.disk_usage(target).free
    if source != target and free < required:
        raise ValueError('目标磁盘剩余空间不足，尚未复制；原件仍保留')
    view = {'backup_root': backup_root, 'source_directory': str(source / 'backups'),
            'target_directory': str(target / 'backups'), 'bytes': source_tree['bytes'],
            'file_count': len(source_tree['files']), 'verified_archives': verified,
            'library_count': len({Path(p).parts[1] for p in source_tree['directories'] if len(Path(p).parts) == 2}),
            'target_bytes': target_tree['bytes'], 'required_bytes': required, 'free_bytes': free,
            'merged_indexes': sorted(merged), 'same_directory': source == target,
            'start_new': start_new, 'source_unavailable': bool(source_error),
            'history_not_copied': start_new, 'source_error': source_error,
            'settings_revision': session.settings_revision, 'context': session.backup_context,
            'expected': _digest(binding), 'originals_retained': True,
            'message': '确认后复制现有备份、保留区和隔离区，切换后持续写入目标目录。原目录全部保留；已有目标记录的名称和固定状态保留。'}
    if start_new:
        view['message'] = '原备份磁盘暂不可用：本次不会读取或复制旧历史。确认后在新位置继续备份，旧目的地与身份记录全部保留；请重新连接旧磁盘后再预览合并历史。'
    return view, binding, merged, preferences


def _copy_file(source, target, record):
    if _stamp(source) != record['stamp']:
        raise ValueError('复制期间备份内容已变化，尚未切换；请重新预览')
    target.parent.mkdir(parents=True, exist_ok=True)
    digest, total = hashlib.sha256(), 0
    with unlinked(source).open('rb') as incoming, unlinked(target).open('xb') as outgoing:
        while chunk := incoming.read(65536):
            total += len(chunk)
            if total > record['bytes']:
                raise ValueError('复制期间备份内容已变化，尚未切换；请重新预览')
            digest.update(chunk)
            outgoing.write(chunk)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    if (total != record['bytes'] or digest.hexdigest() != record['sha256']
            or _stamp(source) != record['stamp'] or _hash(target)['sha256'] != record['sha256']):
        raise ValueError('复制后的备份字节校验失败；尚未切换，原件仍保留')


def _write_file(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with unlinked(path).open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def apply(session, backup_root, expected, persist, *, start_new=False, check_current=None):
    """Caller serializes the frozen manager; persist performs the final session CAS."""
    view, binding, merged, preferences = plan(session, backup_root, start_new=start_new)
    if not isinstance(expected, str) or expected != view['expected']:
        raise ValueError('备份目录或内容已变化，请重新预览并确认')
    source, target = Path(binding['source']), Path(binding['target'])
    stage = preserved = None
    published, displaced = [], []
    try:
        if source != target:
            if [target.stat().st_dev, target.stat().st_ino] != binding['target_identity']:
                raise ValueError('目标目录已变化，尚未复制；请重新预览')
            stage = unlinked(target / ('.denghuo-destination-stage-' + uuid.uuid4().hex))
            stage.mkdir()
            files = {**binding['target_tree']['files'], **binding['source_tree']['files']}
            for relative in sorted(set(binding['source_tree']['directories'] + binding['target_tree']['directories'])):
                (stage / relative).mkdir(parents=True, exist_ok=True)
            for relative, record in files.items():
                if relative in merged:
                    _write_file(stage / relative, merged[relative])
                elif relative != 'backups/preferences.json':
                    origin = source if relative in binding['source_tree']['files'] else target
                    _copy_file(origin / relative, stage / relative, record)
            (stage / 'backups').mkdir(exist_ok=True)
            _write_file(stage / 'backups' / 'preferences.json', preferences)
            _verify(stage, _tree(stage))
            # Stat AND bytes are bound; a same-size edit with restored mtime is stale too.
            if start_new:
                try:
                    session.backups.ensure_storage()
                except (OSError, ValueError):
                    pass
                else:
                    raise ValueError('原备份目录已恢复可用，尚未切换；请重新预览并复制完整历史')
            elif _tree(source) != binding['source_tree']:
                raise ValueError('复制期间备份内容已变化，尚未切换；请重新预览')
            if _tree(target) != binding['target_tree']:
                raise ValueError('复制期间备份内容已变化，尚未切换；请重新预览')
            if binding['backup_root'] and _marker(target) != binding['marker']:
                raise ValueError('复制期间目标磁盘身份已变化，尚未切换')
            if binding['marker_bytes'] and _hash(target / MARKER)['sha256'] != binding['marker_bytes']:
                raise ValueError('复制期间目标磁盘身份记录已变化，尚未切换')
            if [target.stat().st_dev, target.stat().st_ino] != binding['target_identity']:
                raise ValueError('复制期间目标目录已变化，尚未切换')
            if check_current is not None:
                check_current()
            preserved = unlinked(target / ('.denghuo-destination-original-' + uuid.uuid4().hex))
            preserved.mkdir()
            for name in CONTAINERS:
                original, copied = unlinked(target / name), unlinked(stage / name)
                if original.exists():
                    original.rename(preserved / name)
                    displaced.append(name)
                if copied.exists():
                    copied.rename(original)
                    published.append(name)
        if check_current is not None:
            check_current()
        if binding['backup_root']:
            if [target.stat().st_dev, target.stat().st_ino] != binding['target_identity']:
                raise ValueError('目标目录已变化，尚未切换；请重新预览')
            identity = binding['marker']
            if identity is None:
                identity = uuid.uuid4().hex
                with unlinked(target / MARKER).open('x', encoding='utf-8') as stream:
                    json.dump({'format': 1, 'id': identity}, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
            roots = registry(session.config_path)
            roots[binding['backup_root']] = identity
            if len(roots) > 256:
                raise ValueError('已记住的备份目的地过多，尚未切换')
            atomic_json(session.config_path.parent / REGISTRY, roots)
        manager = manager_for(session.config_path, binding['backup_root'],
                              clock=session.backups.clock, closed_check=session.backups.closed_check)
        manager.enabled = binding['enabled']
        if check_current is not None:
            check_current()
        persist(binding['backup_root'], manager)
    except Exception:
        # Rename only our published copies; keep both failed stage and target originals.
        if stage is not None:
            for name in reversed(published):
                unlinked(target / name).rename(stage / name)
            for name in reversed(displaced):
                unlinked(preserved / name).rename(target / name)
        raise
    return {**view, 'ok': True, 'copied': source != target and not start_new,
            'preserved_target_directory': str(preserved) if preserved else None,
            'message': ('自动备份目的地已切换；离线旧历史未复制，旧目录与身份记录全部保留。'
                        if start_new else '自动备份目的地已切换；原目录和目标原记录全部保留。')}
