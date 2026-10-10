"""Manage existing assistant backup libraries without reconnecting a game directory."""
from itertools import islice
import hashlib
import os
import re

from . import backup_workflows as flows
from .backup_archive import read_archive
from .backups import BackupLibrary, MAX_STORAGE, MAX_TOTAL, unlinked

LIBRARY_ID = re.compile(r'[0-9a-f]{24}\Z')


def containers(manager):
    return {'active': manager.directory,
            'retained': manager.directory.parent / 'backup-recycle',
            'quarantine': manager.directory.parent / 'backup-quarantine'}


def resolve_library(manager, identity, current_root):
    if not isinstance(identity, str) or not LIBRARY_ID.fullmatch(identity):
        raise ValueError('备份库编号不正确，请从现有库清单重新选择')
    reference = BackupLibrary(identity)
    found = False
    for container in containers(manager).values():
        path = unlinked(container / identity)
        if path.exists():
            if not path.is_dir():
                raise ValueError('备份库路径不是目录，原件仍保留')
            found = True
    if not found and manager.scope(current_root).name != identity:
        raise ValueError('所选备份库已不存在，请重新读取库清单')
    return reference


def group_bytes(folder):
    folder = unlinked(folder)
    if folder.exists() and not folder.is_dir():
        raise ValueError('备份库路径不是目录')
    total = zip_bytes = zip_count = 0
    for count, path in enumerate(folder.rglob('*')):
        if count >= 20000:
            raise ValueError('备份库内容过多，大小未完整核对；原件仍保留')
        path = unlinked(path)
        if path.is_file():
            size = path.stat().st_size
            total += size
            if path.match('*.zip'):
                zip_count += 1
                zip_bytes += size
    return {'bytes': total, 'zip_bytes': zip_bytes, 'zip_count': zip_count}


def catalog(manager, current_root):
    """Only read indexes; discovering a library must not silently rebuild its history."""
    with manager.lock:
        directories = containers(manager)
        try:
            current_id = manager.scope(current_root).name
        except (ValueError, OSError):
            current_id = None
        identities = {current_id} if current_id else set()
        errors = []
        for kind, container in directories.items():
            try:
                directory = unlinked(container)
                if directory.exists():
                    entries = list(islice(directory.iterdir(), 4097))
                    if len(entries) > 4096:
                        errors.append({'group': kind, 'error': '目录条目超过4096，库清单尚未完整；原件仍保留'})
                    identities.update(path.name for path in entries[:4096] if LIBRARY_ID.fullmatch(path.name))
            except (ValueError, OSError) as exc:
                errors.append({'group': kind, 'error': str(exc)})
        libraries = []
        for identity in sorted(identities):
            row = {'id': identity, 'current': identity == current_id,
                   'source': str(current_root) if identity == current_id else None,
                   'source_status': 'current-connection' if identity == current_id else 'unregistered',
                   'groups': {}, 'record_count': None, 'latest': None, 'errors': []}
            for kind, container in directories.items():
                try:
                    values = group_bytes(container / identity)
                except (ValueError, OSError) as exc:
                    values = {'bytes': None, 'zip_bytes': None, 'zip_count': None}
                    row['errors'].append({'group': kind, 'error': str(exc)})
                row['groups'][kind] = {**values, 'directory': str(container / identity)}
            try:
                records = manager.history(BackupLibrary(identity), discover=False)
                row['record_count'] = len(records)
                if records:
                    latest = max(records, key=lambda record: record['last_seen'])
                    row['latest'] = {key: latest.get(key) for key in
                                     ('slot', 'class', 'level', 'depth', 'saved', 'last_seen', 'label')}
            except (ValueError, OSError) as exc:
                row['errors'].append({'group': 'history', 'error': str(exc)})
            libraries.append(row)
        try:
            used = manager.storage()
            accounted = sum(row['groups']['active']['zip_bytes'] or 0 for row in libraries)
            quota = {'bytes': used, 'limit': MAX_STORAGE,
                     'unclassified_bytes': max(0, used - accounted), 'error': ''}
        except (ValueError, OSError) as exc:
            quota = {'bytes': None, 'limit': MAX_STORAGE, 'unclassified_bytes': None, 'error': str(exc)}
        return {'current_library_id': current_id, 'libraries': libraries, 'quota': quota,
                'discovery_errors': errors, 'read_only_discovery': True}


def details(manager, identity, current_root):
    with manager.lock:
        reference = resolve_library(manager, identity, current_root)
        view = flows.storage_inventory(manager, reference)
        records = view['groups'][0]['rows']
        latest = {}
        for row in records:
            latest[row['slot']] = max(latest.get(row['slot'], 0), row['last_seen'])
        for row in records:
            if row['last_seen'] == latest[row['slot']]:
                row.update(protected=True, reason=row['reason'] if row['protected'] else '每槽位最新记录始终保留')
        return {**view, 'library_id': identity, 'game_operations_available': False}


def inspect_retained(manager, reference, payload):
    name = payload.get('file')
    if not isinstance(name, str) or not flows.RETAINED.fullmatch(name):
        raise ValueError('请选择清单中的确切保留备份')
    path = unlinked(manager.directory.parent / 'backup-recycle' / reference.key / name)
    if not path.is_file() or path.stat().st_size > MAX_TOTAL:
        raise ValueError('保留备份不存在或超过64 MiB，请重新读取清单')
    raw = path.read_bytes()
    metadata = manager.retained_metadata(path)
    sidecar = unlinked(path.with_suffix('.json'))
    metadata_raw = sidecar.read_bytes() if sidecar.exists() else b''
    archive, _, game, identity = read_archive(path)
    if path.read_bytes() != raw or (sidecar.read_bytes() if sidecar.exists() else b'') != metadata_raw:
        raise ValueError('保留副本或来源记录在核对期间变化，请重新预览')
    if identity != name.split('-')[0] or metadata and metadata['slot'] != archive['slot']:
        raise ValueError('保留副本与来源编号或槽位不一致；原件仍保留')
    signature = {'file': name, 'sha256': hashlib.sha256(raw).hexdigest(),
                 'metadata_sha256': hashlib.sha256(metadata_raw).hexdigest(), 'metadata': metadata}
    preview = {'file': name, 'slot': archive['slot'], 'id': identity, 'label': metadata.get('label', ''),
            'summary': flows.player_summary(game, archive['saved']), 'expected': flows.digest(signature),
            'note': '仅重新加入所选助手库；保留副本继续存在，不恢复或覆盖游戏。'}
    return preview, raw, metadata


def rejoin_preview(manager, reference, payload):
    return inspect_retained(manager, reference, payload)[0]


def bound_expected(identity, action, expected):
    return flows.digest({'library_id': identity, 'action': action, 'expected': expected})


def operate(manager, identity, current_root, action, payload):
    """Expose library actions only. Restore, undo, capture and arbitrary game paths are absent."""
    with manager.lock:
        reference = resolve_library(manager, identity, current_root)
        preview_actions = {'export-preview': lambda: flows.export_preview(manager, reference, payload),
                           'retention-preview': lambda: flows.retention_preview(manager, reference, payload),
                           'rejoin-preview': lambda: rejoin_preview(manager, reference, payload)}
        if action in preview_actions:
            result = preview_actions[action]()
            return {**result, 'expected': bound_expected(identity, action, result['expected']), 'library_id': identity}
        execution = {'batch-export': 'export-preview', 'archive-retention': 'retention-preview', 'rejoin': 'rejoin-preview'}
        if action in execution:
            preview_action = execution[action]
            if action == 'rejoin':
                preview, retained_raw, retained_metadata = inspect_retained(manager, reference, payload)
            else:
                preview = preview_actions[preview_action]()
            if payload.get('expected') != bound_expected(identity, preview_action, preview['expected']):
                raise ValueError('所选库、候选或内容已变化，请重新预览；原件仍保留')
            checked = {**payload, 'expected': preview['expected']}
            if action == 'batch-export':
                return flows.export_batch(manager, reference, checked)
            if action == 'archive-retention':
                result = flows.archive_retention(manager, reference, checked)
            else:
                if payload.get('confirmed') is not True:
                    raise ValueError('请先核对并明确确认重新加入这份保留备份')
                manager.import_archive(reference, retained_raw, retained=retained_metadata)
                manager._storage_cache = None
                manager.notice = '已将保留副本重新加入所选备份库；保留原件仍在，尚未恢复游戏。'
                result = {'ok': True, 'file': payload['file'], 'restored': False, 'message': manager.notice}
            return {**result, 'library_id': identity}
        if action == 'open-folder':
            directory = containers(manager).get(payload.get('kind'))
            if directory is None:
                raise ValueError('请选择活动、移出或隔离目录')
            path = unlinked(directory / identity)
            if not path.is_dir():
                raise ValueError('该备份库目录尚未建立')
            if os.name != 'nt':
                raise ValueError('此环境无法打开Windows文件管理器，请使用显示的目录或导出所选备份')
            os.startfile(str(path))
            return {'opened': True, 'library_id': identity}
        raise ValueError('不支持的备份库操作；请从当前界面重新选择')
