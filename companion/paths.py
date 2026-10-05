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
                  'original_preserved':True}
        (temporary/'migration.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(destination)
        return report
    return None
