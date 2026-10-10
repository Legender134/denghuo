"""Separate bundled resources from persistent user data."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]


def data_directory():
    if getattr(sys, 'frozen', False):
        return Path(os.environ.get('LOCALAPPDATA') or Path.home()/'AppData'/'Local')/'Denghuo'
    return ROOT/'.local'


def _migration_size(path, maximum):
    from .backups import unlinked
    attrs = unlinked(path).stat()
    if not stat.S_ISREG(attrs.st_mode) or attrs.st_size > maximum:
        raise ValueError('旧资料文件类型或大小不受支持，原件仍保留，尚未迁移')
    return attrs.st_size


def _migration_digest(path, maximum):
    _migration_size(path, maximum)
    digest, size = hashlib.sha256(), 0
    with path.open('rb') as stream:
        while chunk := stream.read(65536):
            size += len(chunk)
            if size > maximum:
                raise ValueError('旧资料在迁移期间超过限制，原件仍保留，尚未迁移')
            digest.update(chunk)
    return size, digest.hexdigest()


def _copy_migration_file(source, target, maximum, *, expected=None):
    original = _migration_digest(source, maximum)
    if expected is not None and original != expected:
        raise ValueError('旧资料在核对后已变化，原件仍保留，尚未迁移')
    shutil.copy2(source, target)
    if (_migration_digest(target, maximum) != original
            or _migration_digest(source, maximum) != original):
        raise ValueError('迁移副本核对失败或旧资料已变化，原件仍保留，尚未迁移')
    return original


def _recovery_migration_files(directory, *, recognised=False):
    from .backups import unlinked
    from .session_exit import DRAFT_ID, MAX_DRAFT_FILE, MAX_RECOVERY_RECORDS, MAX_RECOVERY_BYTES
    directory = unlinked(directory)
    paths, total = [], 0
    if not directory.exists():
        return paths
    if not directory.is_dir():
        raise ValueError('旧自动草稿目录类型不正确，原件仍保留，尚未迁移')
    for path in sorted([*directory.glob('*.json'), *directory.glob('*.json.pending')]):
        identity = path.name[:-13] if path.name.endswith('.json.pending') else path.stem
        if not DRAFT_ID.fullmatch(identity):
            if recognised:
                raise ValueError('旧自动草稿文件名不受支持，原件仍保留，尚未迁移')
            continue
        total += _migration_size(path, MAX_DRAFT_FILE)
        paths.append(path)
        if len(paths) > MAX_RECOVERY_RECORDS or total > MAX_RECOVERY_BYTES:
            raise ValueError('旧自动草稿超过迁移限制，原件仍保留，尚未迁移')
    return paths


def _preserved_migration_files(directory, *, recognised=False):
    from .backups import unlinked
    from .session_exit import DRAFT_ID, MAX_DRAFT_FILE
    directory = unlinked(directory)
    paths, total = [], 0
    if not directory.exists():
        return paths
    if not directory.is_dir():
        raise ValueError('旧原始恢复副本目录类型不正确，原件仍保留，尚未迁移')
    for path in sorted([*directory.glob('*.json'), *directory.glob('*.raw')]):
        if not DRAFT_ID.fullmatch(path.stem):
            if recognised:
                raise ValueError('旧原始恢复副本文件名不受支持，原件仍保留，尚未迁移')
            continue
        total += _migration_size(path, 4096 if path.suffix == '.json' else MAX_DRAFT_FILE)
        paths.append(path)
        if len(paths) > 12000 or total > 600*1024*1024:
            raise ValueError('旧原始恢复副本超过迁移限制，原件仍保留，尚未迁移')
    return paths


def _recognise_default_data(source):
    """Recognise owned records, without trusting raw originals as usable forms."""
    from .backups import unlinked
    from .backup_archive import read_archive
    from .knowledge import KnowledgeWorkspace, MAX_BYTES
    from .session_exit import ExitDraftStore, ExitRecoveryJournal, DRAFT_ID, MAX_DRAFT_FILE
    knowledge = unlinked(source/'knowledge.json')
    if knowledge.exists():
        try:
            _migration_size(knowledge, MAX_BYTES)
            KnowledgeWorkspace(knowledge, None)._read()
            return 'verified-data'
        except ValueError:
            pass
    drafts = ExitDraftStore(source/'exit-drafts')
    for path in sorted(unlinked(drafts.directory).glob('*.json')):
        if DRAFT_ID.fullmatch(path.stem):
            try:
                _migration_size(path, MAX_DRAFT_FILE)
                drafts.load(path.stem)
                drafts.lifecycle(path.stem)
                return 'verified-data'
            except ValueError:
                pass
    recovery = ExitRecoveryJournal(source/'exit-recovery', drafts)
    recovery_paths = _recovery_migration_files(recovery.directory)
    for path in recovery_paths:
        identity = path.name[:-5] if path.name.endswith('.json') else path.name[:-13]+'.pending'
        try:
            recovery._read(identity)
            return 'verified-data'
        except ValueError:
            pass
    preserved_paths = _preserved_migration_files(recovery.preserved_directory)
    for identity in sorted({path.stem for path in preserved_paths}):
        try:
            recovery.read_preserved(identity)
            return 'verified-data'
        except (ValueError, FileNotFoundError):
            pass
    backup = unlinked(source/'backups')
    count, total = 0, 0
    for path in backup.rglob('*'):
        unlinked(path)
        if path.is_dir():
            continue
        total += _migration_size(path, 600*1024*1024)
        count += 1
        if count > 12000 or total > 600*1024*1024:
            raise ValueError('旧备份超过迁移限制，请在旧版内导出重要记录')
        if (path.suffix == '.zip' and re.fullmatch(r'[0-9a-f]{64}', path.stem)
                and re.fullmatch(r'[0-9a-f]{24}', path.parent.name)):
            try:
                read_archive(path, identity=path.stem)
                return 'verified-data'
            except ValueError:
                pass
    return 'bounded-recovery-originals' if recovery_paths or preserved_paths else None


def migrate_data(destination, sources):
    """Copy a recognised previous install, without overwriting either install."""
    from .backups import unlinked
    from .service import validate_settings
    destination = unlinked(Path(destination))
    if destination.exists():
        return None
    for source in sources:
        source = unlinked(Path(source))
        settings = unlinked(source/'settings.json')
        settings_copied = settings.exists()
        if settings_copied:
            settings_digest = _migration_digest(settings, 65536)
            try:
                with settings.open('rb') as stream:
                    raw = stream.read(65537)
                if len(raw) > 65536:
                    raise ValueError('旧设置超过限制')
                value = json.loads(raw.decode('utf-8-sig'))
                if not isinstance(value, dict) or not {'save_root', 'slot', 'mode', 'reveal'}.issubset(value):
                    raise ValueError('旧设置字段不完整')
                validate_settings(value, require_existing_root=False)
            except (ValueError, UnicodeError, RecursionError) as exc:
                raise ValueError('旧设置损坏或版本不兼容，原件仍保留，尚未迁移') from exc
            recognition = 'settings'
        else:
            recognition = _recognise_default_data(source)
            if recognition is None:
                continue
        temporary = unlinked(destination.with_name(destination.name+'.migration-'+uuid.uuid4().hex))
        temporary.mkdir(parents=True)
        copied_sources = {}
        def copy_file(previous, target, maximum, *, expected=None):
            fingerprint = _copy_migration_file(previous, target, maximum, expected=expected)
            copied_sources[previous] = maximum, fingerprint
            return fingerprint
        if settings_copied:
            copy_file(settings, temporary/'settings.json', 65536, expected=settings_digest)
            validate_settings(json.loads((temporary/'settings.json').read_text(encoding='utf-8-sig')),
                              require_existing_root=False)
        carried_preferences = []
        # Retain corrupt but bounded originals too; their readers report the error
        # without preventing unrelated save monitoring or backup work.
        for name, maximum in (('knowledge.json', 16*1024*1024), ('play-mode.json', 16*1024*1024)):
            previous = unlinked(source/name)
            if previous.is_file():
                if previous.stat().st_size > maximum:
                    raise ValueError('旧收藏、方案或游玩设置过大，原文件仍保留，尚未迁移')
                copy_file(previous, temporary/name, maximum)
                carried_preferences.append(name)
        from .session_exit import ExitDraftStore, DRAFT_ID, MAX_DRAFT_FILE
        drafts = ExitDraftStore(source/'exit-drafts')
        copied_drafts, uncarried_drafts = [], []
        if drafts.directory.exists():
            paths = list(unlinked(drafts.directory).glob('*.json'))
            target_store = ExitDraftStore(temporary/'exit-drafts')
            state_paths = {}
            for path in paths:
                if path.name.endswith('.state.json') and DRAFT_ID.fullmatch(path.name[:-11]):
                    unlinked(path)
                    if path.stat().st_size > 4096 or not unlinked(path.with_name(path.name[:-11]+'.json')).is_file():
                        raise ValueError('旧草稿归档状态缺少原件或超过限制，原件仍保留，尚未迁移')
                    state_paths[path.name[:-11]] = path
            for path in paths:
                if path in state_paths.values():
                    continue
                unlinked(path)
                if not DRAFT_ID.fullmatch(path.stem) or path.stat().st_size > MAX_DRAFT_FILE:
                    raise ValueError('旧草稿文件名或大小不受支持，原件仍保留，尚未迁移')
                try:
                    drafts.load(path.stem)
                    drafts.lifecycle(path.stem)
                except ValueError as exc:
                    # Carry bounded incompatible originals out of the active draft list.
                    preserved = temporary/'exit-drafts-preserved'
                    preserved.mkdir(exist_ok=True)
                    copy_file(path, preserved/path.name, MAX_DRAFT_FILE)
                    if path.stem in state_paths:
                        copy_file(state_paths[path.stem], preserved/state_paths[path.stem].name, 4096)
                    uncarried_drafts.append({'file': path.name, 'error': str(exc),
                                             'preserved_copy': 'exit-drafts-preserved/'+path.name})
                    continue
                target_store.directory.mkdir(exist_ok=True)
                copy_file(path, target_store.directory/path.name, MAX_DRAFT_FILE)
                if path.stem in state_paths:
                    copy_file(state_paths[path.stem], target_store.directory/state_paths[path.stem].name, 4096)
                target_store.load(path.stem)  # Validate the actual copy before publication.
                target_store.lifecycle(path.stem)
                copied_drafts.append(path.name)
        from .session_exit import ExitRecoveryJournal
        recovery = ExitRecoveryJournal(source/'exit-recovery', drafts)
        target_recovery = ExitRecoveryJournal(temporary/'exit-recovery', ExitDraftStore(temporary/'exit-drafts'))
        copied_recovery, unavailable_recovery = [], []
        for path in _recovery_migration_files(recovery.directory, recognised=True):
            original = _migration_digest(path, MAX_DRAFT_FILE)
            identity = path.name[:-5] if path.name.endswith('.json') else path.name[:-13]+'.pending'
            error = None
            try:
                recovery._read(identity)
            except ValueError as exc:
                error = str(exc)
            target_recovery.directory.mkdir(exist_ok=True)
            size, digest = copy_file(path, target_recovery.directory/path.name, MAX_DRAFT_FILE,
                                                expected=original)
            if error is not None:
                unavailable_recovery.append({'file': path.name, 'error': error,
                    'preserved_copy': 'exit-recovery/'+path.name, 'bytes': size, 'sha256': digest})
            else:
                target_recovery._read(identity)
                copied_recovery.append(path.name)
        copied_preserved, unavailable_preserved = [], []
        preserved_paths = _preserved_migration_files(recovery.preserved_directory, recognised=True)
        for identity in sorted({path.stem for path in preserved_paths}):
            originals = [path for path in preserved_paths if path.stem == identity]
            fingerprints = {path: _migration_digest(path, 4096 if path.suffix == '.json' else MAX_DRAFT_FILE)
                            for path in originals}
            try:
                recovery.read_preserved(identity)
            except (ValueError, FileNotFoundError) as exc:
                preserved = temporary/'exit-recovery-preserved-unavailable'
                preserved.mkdir(exist_ok=True)
                for path in originals:
                    size, digest = copy_file(path, preserved/path.name,
                        4096 if path.suffix == '.json' else MAX_DRAFT_FILE, expected=fingerprints[path])
                    unavailable_preserved.append({'file': path.name, 'error': str(exc),
                        'preserved_copy': 'exit-recovery-preserved-unavailable/'+path.name,
                        'bytes': size, 'sha256': digest})
            else:
                target_recovery.preserved_directory.mkdir(exist_ok=True)
                for path in originals:
                    copy_file(path, target_recovery.preserved_directory/path.name,
                        4096 if path.suffix == '.json' else MAX_DRAFT_FILE, expected=fingerprints[path])
                target_recovery.read_preserved(identity)
                copied_preserved.append(identity)
        backup = unlinked(source/'backups')
        count, total = 0, 0
        if backup.is_dir():
            for path in backup.rglob('*'):
                unlinked(path)
                if path.is_dir():
                    continue
                if not path.is_file():
                    raise ValueError('旧备份包含不支持的文件，尚未迁移')
                count += 1; total += path.stat().st_size
                if count > 12000 or total > 600*1024*1024:
                    raise ValueError('旧备份超过迁移限制，请在旧版内导出重要记录')
                target = temporary/'backups'/path.relative_to(backup)
                target.parent.mkdir(parents=True, exist_ok=True)
                copy_file(path, target, 600*1024*1024)
        if recognition == 'verified-data' and _recognise_default_data(temporary) != 'verified-data':
            raise ValueError('迁移后的资料无法再次核对，旧原件仍保留，尚未迁移')
        report = {'source':str(source), 'copied_files':count, 'copied_bytes':total,
                  'copied_preferences':carried_preferences, 'original_preserved':True,
                  'copied_exit_drafts': copied_drafts, 'unavailable_exit_drafts': uncarried_drafts,
                  'settings_copied': settings_copied, 'source_recognition': recognition,
                  'copied_exit_recovery': copied_recovery, 'unavailable_exit_recovery': unavailable_recovery,
                  'copied_preserved_recovery': copied_preserved,
                  'unavailable_preserved_recovery': unavailable_preserved,
                  'draft_notice': ('有草稿或恢复原件无法核对，未计为可载入的迁移；原始字节已保留，'
                                   '请按迁移记录中的位置核对并明确处理；未计算或应用。'
                                   if uncarried_drafts or unavailable_recovery or unavailable_preserved
                                   else '已保存原始草稿仅复制，需用户明确载入；未计算或应用。')}
        (temporary/'migration.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        for previous, (maximum, fingerprint) in copied_sources.items():
            if _migration_digest(previous, maximum) != fingerprint:
                raise ValueError('旧资料在迁移期间已变化，原件仍保留，尚未迁移')
        unlinked(destination)
        if destination.exists():
            raise ValueError('目的资料目录已建立，原有资料仍保留，尚未迁移')
        temporary.replace(destination)
        return report
    return None
