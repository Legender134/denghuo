"""Separate bundled resources from persistent user data."""
import json
import os
from pathlib import Path
import shutil
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]


def data_directory():
    if getattr(sys, 'frozen', False):
        return Path(os.environ.get('LOCALAPPDATA') or Path.home()/'AppData'/'Local')/'Denghuo'
    return ROOT/'.local'


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
        if not settings.is_file():
            continue
        if settings.stat().st_size > 65536:
            raise ValueError('旧设置文件过大，尚未迁移')
        value = json.loads(settings.read_text(encoding='utf-8-sig'))
        if not {'save_root', 'slot', 'mode', 'reveal'}.issubset(value):
            continue
        validate_settings(value, require_existing_root=False)
        temporary = unlinked(destination.with_name(destination.name+'.migration-'+uuid.uuid4().hex))
        temporary.mkdir(parents=True)
        shutil.copy2(settings, temporary/'settings.json')
        carried_preferences = []
        # Retain corrupt but bounded originals too; their readers report the error
        # without preventing unrelated save monitoring or backup work.
        for name, maximum in (('knowledge.json', 16*1024*1024), ('play-mode.json', 16*1024*1024)):
            previous = unlinked(source/name)
            if previous.is_file():
                if previous.stat().st_size > maximum:
                    raise ValueError('旧收藏、方案或游玩设置过大，原文件仍保留，尚未迁移')
                shutil.copy2(previous, temporary/name)
                carried_preferences.append(name)
        from .session_exit import ExitDraftStore, DRAFT_ID, MAX_SAVED_DRAFTS
        drafts = ExitDraftStore(source/'exit-drafts')
        copied_drafts, uncarried_drafts = [], []
        if drafts.directory.exists():
            paths = list(unlinked(drafts.directory).glob('*.json'))
            if len(paths) > MAX_SAVED_DRAFTS:
                raise ValueError('旧未完成草稿超过200份，原件仍保留，请在旧版分批迁移')
            target_store = ExitDraftStore(temporary/'exit-drafts')
            for path in paths:
                unlinked(path)
                if not DRAFT_ID.fullmatch(path.stem) or path.stat().st_size > 512*1024:
                    raise ValueError('旧草稿文件名或大小不受支持，原件仍保留，尚未迁移')
                try:
                    drafts.load(path.stem)
                except ValueError as exc:
                    # Carry bounded incompatible originals out of the active draft list.
                    preserved = temporary/'exit-drafts-preserved'
                    preserved.mkdir(exist_ok=True)
                    shutil.copy2(path, preserved/path.name)
                    uncarried_drafts.append({'file': path.name, 'error': str(exc),
                                             'preserved_copy': 'exit-drafts-preserved/'+path.name})
                    continue
                target_store.directory.mkdir(exist_ok=True)
                shutil.copy2(path, target_store.directory/path.name)
                target_store.load(path.stem)  # Validate the actual copy before publication.
                copied_drafts.append(path.name)
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
                shutil.copy2(path, target)
        report = {'source':str(source), 'copied_files':count, 'copied_bytes':total,
                  'copied_preferences':carried_preferences, 'original_preserved':True,
                  'copied_exit_drafts': copied_drafts, 'unavailable_exit_drafts': uncarried_drafts,
                  'draft_notice': ('有草稿格式或版本不兼容，未计为可用迁移；有界原始副本单独保留，请在旧版核对。'
                                   if uncarried_drafts else '已保存原始草稿仅复制，需用户明确载入；未计算或应用。')}
        (temporary/'migration.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(destination)
        return report
    return None
