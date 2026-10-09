"""Stable disk snapshots; restoration is explicit and requires a closed game."""

from __future__ import annotations

import hashlib
from io import BytesIO
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import threading
import time
import uuid
from zipfile import ZipFile, ZIP_DEFLATED, BadZipFile

from .saves import read_slot, list_slots, read_bundle, read_bundle_data, open_save, validate_hero, validate_location, validate_level, validate_floor_members
from .backup_archive import read_archive, player_summary, read_records, valid_time, IDENTITY

NODES = (3600, 1800, 600, 300, 120, 60, 50, 40, 30, 20, 10)
SAVE_NAME = re.compile(r"(?:game|depth\d+(?:-branch\d+)?)\.dat\Z")
MAX_TOTAL = 64 * 1024 * 1024
MAX_STORAGE = 512 * 1024 * 1024
STAGE_NAME = re.compile(r'\.denghuo-stage-([1-6])-\d+-[0-9a-f]{8}\Z')


def backup_metadata_revision(row):
    value = {key: row.get(key, '' if key != 'locked' else False)
             for key in ('id', 'slot', 'label', 'locked', 'metadata_generation')}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def check_capture_deadline(deadline):
    if deadline is not None and time.monotonic() >= deadline:
        raise TimeoutError('结束前的备份检查超时；未覆盖活动存档原件')


class TimelineRecordsError(ValueError):
    """A damaged observation index may be repaired only by explicit confirmation."""


def snapshot_identity(hashes, slot, format=2):
    value = {"slot": slot, "files": hashes} if format == 2 else hashes
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def unlinked(path):
    path = Path(path)
    for component in (path, *path.parents):
        try:
            attrs = component.lstat()
        except FileNotFoundError:
            continue
        if component.is_symlink() or getattr(attrs, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError("存档或备份路径包含链接，已停止操作")
    return path


def game_closed():
    from .game_process import confirm_game_closed
    return confirm_game_closed()


def atomic_json(path, value):
    temporary = path.with_name(path.name + ".pending")
    unlinked(path)
    unlinked(temporary)
    # Escape even isolated surrogate code points present in a malformed save.
    temporary.write_text(json.dumps(value, ensure_ascii=True, indent=2), encoding="utf-8")
    temporary.replace(path)


class BackupManager:
    def __init__(self, directory, clock=time.time, closed_check=game_closed):
        self.directory = Path(directory)
        self.clock, self.closed_check = clock, closed_check
        self.lock = threading.RLock()
        self.last_tick = 0
        self.error = ""
        self.notice = ""
        self.enabled = True
        self.archive_health = {}
        self.scanned = set()
        self.last_success = 0
        self.last_saved = 0
        self.health_root = None
        self.slot_health = {}
        self.tick_failure = ''
        self._storage_cache = None
        preferences = self.directory / "preferences.json"
        if preferences.exists():
            try:
                unlinked(preferences)
                if preferences.stat().st_size > 65536:
                    raise ValueError()
                value = json.loads(preferences.read_text(encoding="utf-8"))
                if type(value.get("enabled")) is not bool:
                    raise ValueError()
                self.enabled = value["enabled"]
            except (OSError, ValueError, AttributeError, RecursionError):
                self.enabled = False
                self.error = "备份设置无法读取，自动备份已暂停；请在存档时光机中重新开启"

    def scope(self, root):
        key = hashlib.sha256(str(unlinked(Path(root)).resolve()).casefold().encode()).hexdigest()[:24]
        return unlinked(self.directory / key)

    def events(self, root):
        path = self.scope(root) / "timeline.json"
        if not path.exists():
            return []
        unlinked(path)
        if path.stat().st_size > 2 * 1024 * 1024:
            raise TimelineRecordsError("备份时间记录过大，原文件仍保留，已暂停操作")
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, RecursionError) as exc:
            raise TimelineRecordsError("备份时间记录损坏，原文件与ZIP仍保留，已暂停操作") from exc
        if not isinstance(rows, list) or len(rows) > 3000:
            raise TimelineRecordsError("备份时间记录损坏，原文件与ZIP仍保留，已暂停操作")
        for row in rows:
            if (not isinstance(row, dict) or type(row.get("slot")) is not int or row["slot"] not in range(1, 7)
                    or type(row.get("time")) not in (int, float) or not 0 <= row["time"] <= 32503680000
                    or type(row.get("saved")) not in (int, float) or not 0 <= row["saved"] <= 32503680000
                    or type(row.get("depth")) is not int or not 1 <= row["depth"] <= 26
                    or not isinstance(row.get("class"), str) or len(row["class"]) > 40
                    or (row.get("version") is not None and (type(row["version"]) is not int or not 0 <= row["version"] <= 2147483647))
                    or not isinstance(row.get("id"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", row["id"])):
                raise TimelineRecordsError("备份时间记录损坏，原文件与ZIP仍保留，已暂停操作")
        return rows

    def set_enabled(self, enabled):
        if type(enabled) is not bool:
            raise ValueError("自动备份开关值不正确")
        with self.lock:
            unlinked(self.directory).mkdir(parents=True, exist_ok=True)
            atomic_json(self.directory / "preferences.json", {"enabled": enabled})
            self.enabled, self.error, self.last_tick = enabled, "", 0

    def storage(self):
        return sum(unlinked(path).stat().st_size for path in self.directory.rglob('*.zip'))

    def storage_breakdown(self, root):
        now = self.clock()
        cached = self._storage_cache
        if cached and cached[0] == str(root) and 0 <= now-cached[1] < 5:
            return cached[2]
        def size(directory):
            if not directory.exists():
                return 0
            return sum(unlinked(p).stat().st_size for p in directory.rglob('*') if p.is_file())
        active = size(self.directory)
        recycle = size(self.directory.parent/'backup-recycle')
        quarantine = size(self.directory.parent/'backup-quarantine')
        before = sum(size(unlinked(p)) for p in Path(root).glob('.denghuo-before-*') if p.is_dir())
        stages = sum(size(unlinked(p)) for p in Path(root).glob('.denghuo-stage-*')
                     if STAGE_NAME.fullmatch(p.name) and p.is_dir())
        result = {'active': active, 'retained': recycle, 'quarantine': quarantine, 'before_restore': before,
                  'interrupted_stage': stages, 'total': active+recycle+quarantine+before+stages}
        self._storage_cache = (str(root), now, result)
        return result

    def retained_status(self, root):
        directory = unlinked(self.directory.parent/'backup-recycle'/self.scope(root).name)
        result = []
        for path in directory.glob('*.zip'):
            unlinked(path)
            if re.fullmatch(r'[0-9a-f]{64}-\d+\.zip', path.name):
                removed = int(path.stem.split('-')[1])/1e9
                info = {'file': path.name, 'time': removed if valid_time(removed) else path.stat().st_mtime,
                        'bytes': path.stat().st_size}
                try:
                    info.update(self.retained_metadata(path))
                except (OSError, ValueError) as exc:
                    info['metadata_error'] = str(exc)
                result.append(info)
        return sorted(result, key=lambda r:r['time'], reverse=True)

    def retained_metadata(self, path):
        metadata = unlinked(path.with_suffix('.json'))
        if not metadata.exists():
            return {}  # Legacy retained files have no player label to recover.
        if metadata.stat().st_size > 16384:
            raise ValueError('保留备份的名称记录过大，请通过导入功能校验原ZIP')
        try:
            row = json.loads(metadata.read_text(encoding='utf-8'))
            if (not isinstance(row, dict) or row.get('id') != path.stem.split('-')[0]
                    or type(row.get('slot')) is not int or row['slot'] not in range(1,7)
                    or not valid_time(row.get('first_seen')) or not isinstance(row.get('label'), str)
                    or len(row['label']) > 80 or any(ord(c)<32 for c in row['label'])):
                raise ValueError()
        except (ValueError, AttributeError, RecursionError) as exc:
            raise ValueError('保留备份的名称记录损坏，请通过导入功能校验原ZIP') from exc
        return {k:row[k] for k in ('id','slot','label','first_seen')}

    def rejoin(self, root, payload):
        name = payload.get('file')
        if not isinstance(name, str) or not re.fullmatch(r'[0-9a-f]{64}-\d+\.zip', name):
            raise ValueError('保留备份编号不正确')
        with self.lock:
            path = unlinked(self.directory.parent/'backup-recycle'/self.scope(root).name/name)
            if not path.is_file() or path.stat().st_size > MAX_TOTAL:
                raise ValueError('保留备份不存在或超过导入大小限制')
            metadata = self.retained_metadata(path)
            self.import_archive(root, path.read_bytes(), retained=metadata)
            self._storage_cache = None
            self.notice = '已将保留备份重新加入活动库，尚未恢复游戏；保留副本仍在。'

    def checked_archive(self, root, identity, slot=None):
        if not isinstance(identity, str) or not IDENTITY.fullmatch(identity):
            raise ValueError('备份编号不正确')
        path = unlinked(self.scope(root) / f'{identity}.zip')
        key = (path.parent.name, identity)
        try:
            result = read_archive(path, slot=slot, identity=identity)
            self.archive_health[key] = {'valid': True, 'error': '', 'checked': self.clock()}
            return result
        except (ValueError, OSError) as exc:
            self.archive_health[key] = {'valid': False, 'error': str(exc), 'checked': self.clock()}
            raise

    @staticmethod
    def _history_records(path):
        rows = read_records(path)
        for row in rows:
            if (not isinstance(row.get('id'), str) or not IDENTITY.fullmatch(row['id'])
                    or type(row.get('slot')) is not int or row['slot'] not in range(1, 7)
                    or not valid_time(row.get('time')) or not valid_time(row.get('last_seen'))
                    or not isinstance(row.get('label', ''), str) or len(row.get('label', '')) > 80
                    or type(row.get('locked', False)) is not bool
                    or 'metadata_generation' in row and (not isinstance(row['metadata_generation'], str)
                        or not re.fullmatch(r'[0-9a-f]{32}', row['metadata_generation']))
                    or 'imported_at' in row and not valid_time(row['imported_at'])
                    or not isinstance(row.get('repair_error', ''), str) or len(row.get('repair_error', '')) > 1000):
                raise ValueError('备份历史记录损坏')
        if len({(r['slot'], r['id']) for r in rows}) != len(rows):
            raise ValueError('备份历史记录重复')
        for row in rows:
            row['metadata_revision'] = backup_metadata_revision(row)
        return rows

    def history(self, root, *, discover=True):
        scope = self.scope(root)
        path = unlinked(scope / 'history.json')
        rows = self._history_records(path)
        if discover and str(scope) not in self.scanned:
            events = self.events(root)
            indexed = {r['id'] for r in rows}
            changed = False
            files = list(scope.glob('*.zip'))
            if len(files) > 10000:
                raise ValueError('备份文件数量过多，请先导出并整理')
            for archive in files:
                if not IDENTITY.fullmatch(archive.stem) or archive.stem in indexed:
                    continue
                try:
                    metadata, _, game, identity = self.checked_archive(root, archive.stem)
                    own = [r for r in events if r['id'] == identity and r['slot'] == metadata['slot']]
                    first = min((r['time'] for r in own), default=archive.stat().st_mtime)
                    last = max((r['time'] for r in own), default=first)
                    rows.append({**player_summary(game, metadata['saved']), 'id': identity,
                                 'slot': metadata['slot'], 'time': first, 'last_seen': last,
                                 'label': '', 'locked': False})
                    changed = True
                except (ValueError, OSError):
                    # An unrecognised/damaged file is not advertised as restorable.
                    continue
            if changed:
                atomic_json(path, rows)
            self.scanned.add(str(scope))
        for row in rows:
            row['metadata_revision'] = backup_metadata_revision(row)
        return rows

    def register(self, root, row, retained=None, transfer=None, imported=False):
        rows = self.history(root)
        existing = next((r for r in rows if r['slot'] == row['slot'] and r['id'] == row['id']), None)
        if existing and imported:
            # Importing an existing object is not a new observation of live gameplay.
            existing['imported_at'] = row['time']
            existing.pop('repair_error', None)
        elif existing:
            if existing.pop('recovered_at', None) is not None:
                existing['time'] = row['time']
            existing.update({**row, 'time': min(existing['time'], row['time']), 'label': existing.get('label', ''),
                              'locked': existing.get('locked', False), 'last_seen': row['time']})
            existing.pop('repair_error', None)  # Capture/import has just verified this object again.
        else:
            target = {**row, 'last_seen': row['time'], 'label': '', 'locked': False}
            if imported:
                target['imported_at'] = row['time']
                if transfer:
                    target.update(label=transfer['label'], locked=transfer['locked'])
                if transfer and transfer['first_observed'] is not None:
                    target.update(time=transfer['first_observed'], last_seen=transfer['last_observed'])
                else:
                    target['recovered_at'] = row['time']
            rows.append(target)
        if retained:
            target = existing if existing is not None else rows[-1]
            target['time'] = min(target['time'], retained['first_seen'])
            if not target.get('label'):
                target['label'] = retained['label']
        if len(rows) > 10000:
            raise ValueError('备份历史已满，请导出并整理旧记录')
        atomic_json(self.scope(root) / 'history.json', rows)
        return existing if existing is not None else rows[-1]

    def selected(self, root, payload):
        slot, identity = payload.get('slot'), payload.get('id')
        if type(slot) is not int or slot not in range(1, 7):
            raise ValueError('槽位不正确')
        # A damaged timeline must never be silently bypassed by a second index.
        events = self.events(root)
        row = next((r for r in self.history(root) if r['slot'] == slot and r['id'] == identity), None)
        if row is None and any(r['slot'] == slot and r['id'] == identity for r in events):
            self.scanned.discard(str(self.scope(root)))
            row = next((r for r in self.history(root) if r['slot'] == slot and r['id'] == identity), None)
        if row is None:
            raise ValueError('备份不属于当前目录或槽位')
        return row

    def manage(self, root, payload):
        with self.lock:
            selected = self.selected(root, payload)
            label = payload.get('label', selected.get('label', ''))
            locked = payload.get('locked', selected.get('locked', False))
            if (not isinstance(label, str) or len(label) > 80 or any(ord(c) < 32 for c in label)
                    or type(locked) is not bool):
                raise ValueError('名称最多80个字，永久保留开关必须有效')
            rows = self.history(root)
            target = next(r for r in rows if r['slot'] == selected['slot'] and r['id'] == selected['id'])
            if payload.get('expected_metadata_revision') != backup_metadata_revision(target):
                raise ValueError('备份名称或永久保留状态已变化；本次未保存。请核对最新信息，原编辑仍保留')
            target.update(label=label.strip(), locked=locked)
            target['metadata_generation'] = uuid.uuid4().hex
            target['metadata_revision'] = backup_metadata_revision(target)
            atomic_json(self.scope(root) / 'history.json', rows)
            self.notice = '备份名称与保留设置已保存'
            return {key: target[key] for key in ('id', 'slot', 'label', 'locked', 'metadata_revision')}

    def validate(self, root):
        with self.lock:
            errors = []
            rows = self.history(root)
            changed = False
            for row in rows:
                try:
                    self.checked_archive(root, row['id'], row['slot'])
                    changed = changed or 'repair_error' in row
                    row.pop('repair_error', None)
                except (ValueError, OSError) as exc:
                    errors.append(f"槽位 {row['slot']}：{exc}")
            if changed:
                atomic_json(self.scope(root) / 'history.json', rows)
            self.notice = f'已检查{len(rows)}份备份，{len(errors)}份不可用。'
            if errors:
                self.notice += ' 自动备份会在相同有效进度再次出现时重建损坏副本。'
            return errors

    def export(self, root, payload):
        with self.lock:
            row = self.selected(root, payload)
            path = unlinked(self.scope(root) / (row['id'] + '.zip'))
            stamp = path.stat()
            metadata, contents, _, _ = self.checked_archive(root, row['id'], row['slot'])
            after = path.stat()
            if (stamp.st_mtime_ns, stamp.st_size, stamp.st_ino) != (after.st_mtime_ns, after.st_size, after.st_ino):
                raise ValueError('备份在导出期间变化，请重新检查')
            metadata['transfer'] = {'label': row.get('label', ''), 'locked': row.get('locked', False),
                                    'first_observed': None if row.get('recovered_at') else row['time'],
                                    'last_observed': None if row.get('recovered_at') else row['last_seen']}
            output = BytesIO()
            with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
                archive.writestr('manifest.json', json.dumps(metadata, ensure_ascii=True))
                for name, data in contents.items():
                    archive.writestr(name, data)
            raw = output.getvalue()
            if len(raw) > MAX_TOTAL:
                raise ValueError('导出的备份超过大小限制')
            return raw, f"denghuo-slot{row['slot']}-{row['id'][:12]}.zip"

    def import_archive(self, root, raw, retained=None):
        with self.lock:
            if not isinstance(raw, bytes) or not 1 < len(raw) <= MAX_TOTAL:
                raise ValueError('导入的备份大小不正确')
            scope = self.scope(root)
            scope.mkdir(parents=True, exist_ok=True)
            incoming = unlinked(scope / ('import-' + uuid.uuid4().hex + '.pending'))
            try:
                incoming.write_bytes(raw)
                metadata, contents, game, _ = read_archive(incoming)
                if retained and retained['slot'] != metadata['slot']:
                    raise ValueError('保留备份的槽位记录与ZIP不一致')
                metadata = {**metadata, 'format': 2}
                identity = snapshot_identity(metadata['files'], metadata['slot'])
                # Discover existing records before installing the imported ZIP.
                self.history(root)
                target = unlinked(scope / (identity + '.zip'))
                if not target.exists():
                    if self.storage() + len(raw) > MAX_STORAGE:
                        raise ValueError('备份目录已接近 512 MiB 上限；请导出并移出不需要的备份')
                    with ZipFile(incoming, 'w', ZIP_DEFLATED) as archive:
                        archive.writestr('manifest.json', json.dumps(metadata, ensure_ascii=True))
                        for name, data in contents.items():
                            archive.writestr(name, data)
                    read_archive(incoming, slot=metadata['slot'], identity=identity)
                    incoming.replace(target)
                else:
                    self.checked_archive(root, identity, metadata['slot'])
                row = {**player_summary(game, metadata['saved']), 'id': identity, 'slot': metadata['slot'], 'time': self.clock()}
                row = self.register(root, row, retained=retained, transfer=metadata.get('transfer'), imported=True)
                self.notice = f"已导入槽位 {metadata['slot']} 的备份，尚未恢复游戏存档。"
                return row
            finally:
                if incoming.exists():
                    unlinked(incoming).unlink()

    def remove(self, root, payload):
        """Recoverable removal from the active library; never delete the archive."""
        with self.lock:
            row = self.selected(root, payload)
            if row.get('locked'):
                raise ValueError('此备份已永久保留，请先取消固定')
            from .backup_workflows import protected_records
            if (row['slot'],row['id']) in protected_records(self,root,self.history(root)):
                raise ValueError('此备份关联当前可撤回的回档，请先核对撤回记录；尚未移出')
            if payload.get('confirm') != f"移出备份 {row['slot']}":
                raise ValueError('请明确确认移出备份')
            scope = self.scope(root)
            recycle = unlinked(self.directory.parent / 'backup-recycle' / scope.name)
            recycle.mkdir(parents=True, exist_ok=True)
            source = unlinked(scope / (row['id'] + '.zip'))
            target = unlinked(recycle / (row['id'] + '-' + str(time.time_ns()) + '.zip'))
            rows, events = self.history(root), self.events(root)
            indexes = {name: unlinked(scope / name).read_bytes() if (scope / name).exists() else None
                       for name in ('history.json', 'timeline.json')}
            source.replace(target)
            try:
                atomic_json(target.with_suffix('.json'), {'id':row['id'], 'slot':row['slot'],
                            'label':row.get('label',''), 'first_seen':row['time'],
                            'last_seen':row['last_seen'], 'locked':row.get('locked',False)})
                atomic_json(scope / 'history.json', [r for r in rows if r['id'] != row['id']])
                atomic_json(scope / 'timeline.json', [r for r in events if r['id'] != row['id']])
            except OSError:
                target.replace(source)
                # Roll back the first index too if the second index could not be published.
                for name, contents in indexes.items():
                    path = unlinked(scope / name)
                    if contents is None:
                        if path.exists():
                            path.unlink()
                    else:
                        temporary = unlinked(path.with_name(name + '.rollback'))
                        temporary.write_bytes(contents)
                        temporary.replace(path)
                raise
            self.error = ''
            self._storage_cache = None
            self.notice = '备份已移出活动库；可在下方保留副本中校验并重新加入，原名称会保留。没有删除文件。'
            self.last_tick = self.clock()  # Do not immediately recreate the same current state.

    def capture(self, root, slot, *, deadline=None):
        check_capture_deadline(deadline)
        root = unlinked(Path(root)).resolve()
        folder = unlinked(root / f"game{slot}")
        game, level, modified, warning = read_slot(root, slot)
        if warning or level is None:
            raise ValueError(f"槽位 {slot}：角色与当前楼层还未形成一致存档，稍后自动重试")
        files = sorted(path for path in folder.iterdir() if SAVE_NAME.fullmatch(path.name))
        validate_floor_members(game,[path.name for path in files])
        if not files or len(files) > 128:
            raise ValueError("槽位文件数量不正确")
        stamps, payloads, total = {}, {}, 0
        for path in files:
            check_capture_deadline(deadline)
            unlinked(path)
            attrs = path.stat()
            if not path.is_file() or attrs.st_size > 16 * 1024 * 1024:
                raise ValueError("存档文件类型或大小不正确")
            stamps[path.name] = (attrs.st_mtime_ns, attrs.st_size, attrs.st_ino)
            total += attrs.st_size
            if total > MAX_TOTAL:
                raise ValueError("此槽位存档超过备份大小限制")
            with open_save(path) as stream:
                payloads[path.name] = stream.read(16 * 1024 * 1024 + 1)
            if len(payloads[path.name]) > 16 * 1024 * 1024:
                raise ValueError("存档文件类型或大小不正确")
            if path.name != 'game.dat':
                validate_level(read_bundle_data(payloads[path.name]))
        if sorted(path.name for path in folder.iterdir() if SAVE_NAME.fullmatch(path.name)) != sorted(payloads):
            raise ValueError("游戏正在保存，下一次重试")
        for name, stamp in stamps.items():
            attrs = (folder / name).stat()
            if stamp != (attrs.st_mtime_ns, attrs.st_size, attrs.st_ino):
                raise ValueError("游戏正在保存，下一次重试")
        # Ensure the validated hero is the same byte snapshot we captured.
        game_again, _, _, _ = read_slot(root, slot)
        if game_again != game:
            raise ValueError("游戏正在保存，下一次重试")
        check_capture_deadline(deadline)
        hashes = {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()}
        identity = snapshot_identity(hashes, slot)
        scope = self.scope(root)
        scope.mkdir(parents=True, exist_ok=True)
        target = unlinked(scope / f"{identity}.zip")
        if target.exists():
            try:
                self.checked_archive(root, identity, slot)
            except (ValueError, OSError):
                quarantine = unlinked(self.directory.parent / 'backup-quarantine' / scope.name)
                quarantine.mkdir(parents=True, exist_ok=True)
                isolated = unlinked(quarantine / f'{identity}-{time.time_ns()}.zip')
                original_size = target.stat().st_size
                with target.open('rb') as stream:
                    original = stream.read(MAX_TOTAL+1)
                atomic_json(isolated.with_suffix('.json'), {
                    'format':1, 'kind':'denghuo-quarantine', 'scope':scope.name, 'id':identity,
                    'slot':slot, 'bytes':original_size,
                    'sha256':hashlib.sha256(original).hexdigest() if len(original)<=MAX_TOTAL else None,
                    'summary':player_summary(game, modified), 'reason':'应用校验失败后隔离原件'})
                target.replace(isolated)
                self.notice = '发现损坏备份，已单独保留原文件并重新备份当前有效进度。'
        if not target.exists():
            used = self.storage()
            if used + total > MAX_STORAGE:
                raise ValueError("备份目录已接近 512 MiB 上限；请保留所需备份后整理目录")
            metadata = {"format": 2, "slot": slot, "files": hashes, "saved": modified,
                        "stamps": {name: stamp[0] for name, stamp in stamps.items()},
                        "depth": game["depth"], "class": game["hero"]["class"], "version": game.get("version")}
            pending = unlinked(target.with_suffix(".pending"))
            with ZipFile(pending, "w", ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(metadata, ensure_ascii=True))
                for name, data in payloads.items():
                    archive.writestr(name, data)
            check_capture_deadline(deadline)
            pending.replace(target)
            self.checked_archive(root, identity, slot)
        row = {**player_summary(game, modified), "time": self.clock(), "slot": slot, "id": identity}
        self.register(root, row)
        return row

    def final_capture(self, root, deadline, *, allow_missing_default=False):
        """A last stable capture, with retries and a shared monotonic deadline."""
        remaining = max(0, deadline - time.monotonic())
        if not self.lock.acquire(timeout=remaining):
            return {'ok': False, 'state': 'timeout', 'captured': [],
                    'error': '最后一次备份未完成：备份任务仍在处理；已有备份与活动存档原件仍保留。'}
        try:
            if not self.enabled:
                return {'ok': True, 'state': 'paused', 'captured': [], 'error': '',
                        'notice': '自动备份已由用户暂停，结束时没有重新开启。'}
            if not Path(root).is_dir():
                if (allow_missing_default is True and not Path(root).exists()
                        and not self.has_protected_progress(root)):
                    return {'ok': True, 'state': 'no-save', 'captured': [], 'error': '',
                            'notice': '默认存档目录尚未创建，本次没有游戏进度需要备份。'}
                return {'ok': False, 'state': 'unavailable', 'captured': [],
                        'error': '最后一次备份未完成：存档目录暂时不可用；已有备份与原件仍保留。'}
            check_capture_deadline(deadline)
            slots = list_slots(Path(root))
            pending, problems, captured = [], {}, []
            for slot in slots:
                if slot['valid']:
                    pending.append(slot['id'])
                elif slot.get('error') and not slot['error'].startswith('空存档'):
                    # A partially written save may become valid during the bounded retry.
                    pending.append(slot['id'])
                    problems[slot['id']] = slot['error']
            while pending and time.monotonic() < deadline:
                for slot in tuple(pending):
                    try:
                        check_capture_deadline(deadline)
                        row = self.capture(root, slot, deadline=deadline)
                        captured.append({'slot': slot, 'id': row['id'], 'saved': row['saved']})
                        pending.remove(slot)
                        problems.pop(slot, None)
                        self.slot_health[slot] = {'error': '', 'saved': row['saved'], 'last_success': self.clock()}
                    except (OSError, ValueError) as exc:
                        problems[slot] = str(exc)
                if pending:
                    time.sleep(min(.1, max(0, deadline - time.monotonic())))
            if captured:
                self.health_root = str(Path(root))
                self.last_success = self.clock()
                self.last_saved = max(row['saved'] for row in captured)
                rows = self.events(root)
                history = self.history(root)
                for row in captured:
                    saved = next(item for item in history if item['slot'] == row['slot'] and item['id'] == row['id'])
                    rows.append({key: saved[key] for key in ('id', 'slot', 'time', 'saved', 'depth', 'class', 'version')})
                # At most six new observations; preserve earlier timeline evidence.
                if len(rows) > 3000:
                    raise ValueError('备份时间记录已满，最后进度已保存在历史中；请打开存档历史检查')
                atomic_json(self.scope(root) / 'timeline.json', rows)
            error = '；'.join(f'槽位 {slot}：{problems.get(slot, "结束前未形成稳定存档")}' for slot in pending)
            if error:
                self.error = error
                return {'ok': False, 'state': 'partial' if captured else 'failed', 'captured': captured,
                        'error': '最后一次备份未完成：' + error + '；已有备份与活动存档原件仍保留。'}
            return {'ok': True, 'state': 'captured' if captured else 'no-save', 'captured': captured, 'error': ''}
        except (OSError, ValueError) as exc:
            return {'ok': False, 'state': 'failed', 'captured': [],
                    'error': '最后一次备份未完成：' + str(exc) + '；已有备份与活动存档原件仍保留。'}
        finally:
            self.lock.release()

    def has_protected_progress(self, root):
        """No-save is allowed only before this root has any observed/protected data."""
        with self.lock:
            if self.health_root == str(root) and (self.last_saved or self.slot_health):
                return True
            scope = self.scope(root)
            return (bool(self.history(root, discover=False)) or bool(self.events(root))
                    or bool(self.journals(root)) or any(scope.glob('*.zip'))
                    or bool(self.retained_status(root)))

    def tick(self, root, force=False):
        with self.lock:
            now = self.clock()
            if not force and (not self.enabled or now - self.last_tick < 10):
                return
            self.last_tick = now
            self.health_root = str(Path(root))
            self.tick_failure = ''
            self.slot_health = {}
            try:
                rows = self.events(root)
                errors = []
                captured = 0
                captured_saved = []
                for slot in list_slots(Path(root)):
                    if not slot["valid"]:
                        if slot.get('error') and not slot['error'].startswith('空存档'):
                            errors.append(f"槽位 {slot['id']}：{slot['error']}")
                            self.slot_health[slot['id']] = {'error': slot['error'], 'saved': 0, 'last_success': 0}
                        continue
                    try:
                        row = self.capture(root, slot["id"])
                        rows.append({key: row[key] for key in ('id','slot','time','saved','depth','class','version')})
                        captured_saved.append(row['saved'])
                        captured += 1
                        self.slot_health[slot['id']] = {'error': '', 'saved': row['saved'], 'last_success': now}
                    except (OSError, ValueError) as exc:
                        errors.append(str(exc))
                        self.slot_health[slot['id']] = {'error': str(exc), 'saved': 0, 'last_success': 0}
                if captured:
                    # Keep one predecessor for every slot at the one-hour edge.
                    old = {slot: max((r for r in rows if r["slot"] == slot and r["time"] < now - 3660),
                                    key=lambda r: r["time"], default=None) for slot in range(1, 7)}
                    rows = [r for r in rows if r["time"] >= now - 3660] + [r for r in old.values() if r]
                    # Keep recurring observations compact; rich summaries live once in history.
                    rows = [{key: r.get(key) for key in ('id','slot','time','saved','depth','class','version')} for r in rows]
                    atomic_json(self.scope(root) / "timeline.json", rows)
                    self.last_success = now
                    self.last_saved = max(captured_saved)
                else:
                    self.last_success = self.last_saved = 0
                self.error = "；".join(errors)
                if force and not captured:
                    raise ValueError(self.error or "没有可备份的有效存档；先在游戏内保存")
            except (OSError, ValueError) as exc:
                self.error = str(exc)
                self.tick_failure = str(exc)
                if force:
                    raise

    def health_status(self, root, slot=None):
        with self.lock:
            current = self.health_root == str(Path(root))
            success, saved = (self.last_success, self.last_saved) if current else (0, 0)
            # Startup/storage failures may precede the first root-bound tick.
            error = (self.error if self.health_root is None else
                     (self.error if slot is None else self.tick_failure) if current else '')
            if slot is not None:
                own = self.slot_health.get(slot, {}) if current else {}
                success, saved = own.get('last_success', 0), own.get('saved', 0)
                error = error or own.get('error', '')
            state = ('paused' if not self.enabled else 'blocked' if error or not Path(root).is_dir()
                     else 'waiting' if not success or self.clock() - saved > 60 else 'protected')
            return {'state': state, 'error': error, 'last_success': success, 'saved': saved, 'slot': slot,
                    'last_save_protected': bool(success and saved and not error),
                    'other_errors': self.error if current and slot is not None and self.error != error else ''}

    def snapshot(self, root):
        with self.lock:
            try:
                rows = self.events(root)
                history = self.history(root)
                summaries = {r['id']: r for r in history}
                rows = [{**summaries.get(r['id'], {}), **r} for r in rows]
                now = self.clock()
                slots = []
                for slot in sorted({r["slot"] for r in rows}):
                    own = [r for r in rows if r["slot"] == slot]
                    latest = max(own, key=lambda r: r["time"])
                    nodes = []
                    for seconds in NODES:
                        chosen = max((r for r in own if r["time"] <= now - seconds), key=lambda r: r["time"], default=None)
                        nodes.append({"seconds": seconds, "backup": chosen})
                    slots.append({"slot": slot, "latest": latest, "nodes": nodes})
                # Slots with older/imported history remain selectable without a current timeline.
                for slot in sorted({r['slot'] for r in history} - {s['slot'] for s in slots}):
                    own = [r for r in history if r['slot'] == slot]
                    latest = max(own, key=lambda r: r['last_seen'])
                    slots.append({'slot': slot, 'latest': latest,
                                  'nodes': [{'seconds': s, 'backup': None} for s in NODES]})
                undo = self.undo_status(root)
                for slot in sorted({r['slot'] for r in undo} - {s['slot'] for s in slots}):
                    slots.append({'slot': slot, 'latest': None,
                                  'nodes': [{'seconds': s, 'backup': None} for s in NODES]})
                scope = self.scope(root)
                history = [{**r, 'integrity': self.archive_health.get((scope.name, r['id']),
                           {'valid': False, 'error': r['repair_error']} if r.get('repair_error') else {'valid': None, 'error': ''})}
                           for r in sorted(history, key=lambda r: r['last_seen'], reverse=True)]
                latest_time = max((r['time'] for r in rows), default=0)
                health = self.health_status(root)
                return {"enabled": self.enabled, "error": health['error'], "notice": self.notice,
                        "slots": sorted(slots, key=lambda s: s['slot']), "directory": str(self.directory), "interval": 10,
                        'history': history, 'storage_bytes': self.storage(), 'storage_limit': MAX_STORAGE,
                        'storage_breakdown': self.storage_breakdown(root), 'retained': self.retained_status(root),
                        'health': health['state'], 'last_success': max(health['last_success'], latest_time),
                        'last_save_protected': health['last_save_protected'],
                        'undo': undo, 'records_available': True, 'repair_timeline_available': False,
                        'repair_timeline_reason': ''}
            except (OSError, ValueError) as exc:
                available, reason = self._timeline_repair_status(root)
                result = {"enabled": self.enabled, "error": str(exc) + ('；' + reason if reason else ''), "slots": [], "notice": self.notice,
                        "directory": str(self.directory), "interval": 10, 'history': [],
                        'health': 'paused' if not self.enabled else 'blocked',
                        'last_success': self.health_status(root)['last_success'], 'undo': [], 'storage_limit': MAX_STORAGE,
                        'records_available': False, 'repair_timeline_available': available,
                        'repair_timeline_reason': reason}
                result.update(self._storage_report(root))
                return result

    def _storage_report(self, root):
        result = {'storage_bytes': None}
        try:
            result['storage_bytes'] = self.storage()
        except (OSError, ValueError):
            pass
        try:
            result['storage_breakdown'] = self.storage_breakdown(root)
        except (OSError, ValueError):
            pass
        return result

    def _timeline_repair_status(self, root):
        try:
            self.events(root)
        except TimelineRecordsError:
            pass
        except (OSError, ValueError):
            return False, '时间记录无法安全读取，请检查备份目录权限或路径；尚未修改原件'
        else:
            return False, ''
        try:
            scope = self.scope(root)
        except (OSError, ValueError):
            return False, '备份路径已变化，不能安全恢复记录；原文件仍在'
        for name, reader in (('history.json', self._history_records), ('restores.json', self._journal_records)):
            try:
                reader(unlinked(scope / name))
            except (OSError, ValueError):
                return False, f'{name} 也无法读取，不能安全保留名称、固定或撤回关系；原文件仍在'
        return True, '可显式校验ZIP并恢复时间记录；过去的时间节点将重新积累'

    @staticmethod
    def _index_bytes(path):
        unlinked(path)
        if not path.exists():
            return None
        before = path.stat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > 32 * 1024 * 1024:
            raise ValueError('备份管理记录不是普通文件或超过安全恢复大小限制')
        with path.open('rb') as stream:
            raw = stream.read(before.st_size + 1)
        after = path.stat()
        if len(raw) != before.st_size or (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError('备份管理记录正在变化，请稍后重试')
        return raw

    @staticmethod
    def _restore_index_bytes(path, raw):
        unlinked(path)
        if raw is None:
            if path.exists():
                path.unlink()
            return
        temporary = unlinked(path.with_name(path.name + '.rollback-' + uuid.uuid4().hex))
        with temporary.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)

    def repair_timeline(self, root, payload):
        """Rebuild only the damaged observation index, preserving every source object."""
        if not isinstance(payload, dict) or payload.get('confirm') != '恢复时间记录':
            raise ValueError('请明确确认恢复时间记录')
        try:
            return self._repair_timeline(root)
        except OSError as exc:
            raise ValueError('无法完整读取或保留备份记录，尚未发布修复；请检查目录权限与剩余空间') from exc

    def _repair_timeline(self, root):
        with self.lock:
            available, reason = self._timeline_repair_status(root)
            if not available:
                raise ValueError(reason or '时间记录完整，无需恢复')
            scope = self.scope(root)
            names = ('timeline.json', 'history.json', 'restores.json')
            originals = {name: self._index_bytes(unlinked(scope / name)) for name in names}
            recovery = unlinked(scope / ('records-recovery-' + str(time.time_ns()) + '-' + uuid.uuid4().hex[:8]))
            recovery.mkdir()
            try:
                for name, raw in originals.items():
                    if raw is not None:
                        with unlinked(recovery / name).open('xb') as stream:
                            if stream.write(raw) != len(raw):
                                raise OSError('incomplete recovery copy')
                            stream.flush()
                            os.fsync(stream.fileno())
                        if self._index_bytes(recovery / name) != raw:
                            raise ValueError('原记录副本未完整保存')
            except (OSError, ValueError) as exc:
                raise ValueError('原记录保留失败，尚未修改索引；请检查备份目录权限与剩余空间') from exc
            # Parse the preserved bytes, never a separately changing source index.
            rows = self._history_records(unlinked(recovery / 'history.json'))
            self._journal_records(unlinked(recovery / 'restores.json'))
            now = self.clock()
            verified, failures = {}, []
            archives = list(scope.glob('*.zip'))
            if len(archives) > 10000:
                raise ValueError('备份文件数量过多，尚未恢复时间记录；原件已保留')
            for archive in archives:
                unlinked(archive)
                before = archive.stat()
                if not stat.S_ISREG(before.st_mode):
                    raise ValueError('备份库包含非普通文件，尚未恢复时间记录')
                if not IDENTITY.fullmatch(archive.stem):
                    failures.append({'file': archive.name, 'error': '文件名不是灯火备份编号，原文件仍保留'})
                    continue
                try:
                    metadata, _, game, identity = self.checked_archive(root, archive.stem)
                    verified[(metadata['slot'], identity)] = player_summary(game, metadata['saved'])
                except (OSError, ValueError) as exc:
                    error = ('备份资料损坏，无法完整校验' if isinstance(exc, (json.JSONDecodeError, UnicodeError))
                             else '备份文件无法读取，原文件仍保留' if isinstance(exc, OSError) else str(exc))
                    self.archive_health[(scope.name, archive.stem)] = {'valid': False, 'error': error, 'checked': now}
                    failures.append({'file': archive.name, 'error': error})
                after = archive.stat()
                if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
                    raise ValueError('备份在校验期间变化，尚未恢复时间记录；请重新检查')
            rebuilt = []
            existing = {(r['slot'], r['id']) for r in rows}
            for row in rows:
                key = (row['slot'], row['id'])
                if key in verified:
                    clean = {**row, **verified[key]}
                    clean.pop('repair_error', None)
                    rebuilt.append(clean)
                else:
                    if any(identity == row['id'] for _, identity in verified):
                        raise ValueError('备份历史的槽位与ZIP不一致，不能安全恢复记录；原件已保留')
                    error = self.archive_health.get((scope.name, row['id']), {}).get('error', '备份无法完整校验，原文件仍保留')
                    if not (scope / (row['id'] + '.zip')).exists():
                        error = '备份ZIP缺失，名称与固定记录仍保留'
                        self.archive_health[(scope.name, row['id'])] = {'valid': False, 'error': error, 'checked': now}
                        failures.append({'file': row['id'] + '.zip', 'error': error})
                    rebuilt.append({**row, 'repair_error': error[:1000]})
            recovered = 0
            for (slot, identity), summary in verified.items():
                if (slot, identity) not in existing:
                    rebuilt.append({**summary, 'id': identity, 'slot': slot, 'time': now, 'last_seen': now,
                                    'label': '', 'locked': False, 'recovered_at': now})
                    recovered += 1
            if len(rebuilt) > 10000:
                raise ValueError('备份历史已满，尚未恢复时间记录；原件已保留')
            manifest = {'created': now, 'originals': {name: {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                        for name, raw in originals.items() if raw is not None},
                        'valid_archives': len(verified), 'registered': recovered, 'unavailable': failures}
            atomic_json(recovery / 'manifest.json', manifest)
            for name, raw in originals.items():
                if self._index_bytes(scope / name) != raw:
                    raise ValueError('备份管理记录在准备期间变化，尚未发布修复；请重新检查')
            attempted = []
            try:
                if rebuilt != rows:
                    attempted.append('history.json')
                    atomic_json(scope / 'history.json', rebuilt)
                # Keep the corrupt timeline in place until all other preparation succeeds.
                attempted.append('timeline.json')
                atomic_json(scope / 'timeline.json', [])
            except Exception as exc:
                failed = []
                for name in reversed(attempted):
                    try:
                        self._restore_index_bytes(scope / name, originals[name])
                    except Exception:
                        failed.append(name)
                if failed:
                    raise ValueError('修复发布及部分回滚失败，请保留备份目录；完整原件位于 ' + str(recovery)) from exc
                raise ValueError('修复发布失败，原索引已恢复；完整原件位于 ' + str(recovery)) from exc
            self.scanned.add(str(scope))
            self._storage_cache = None
            self.last_tick = 0
            if self.health_root == str(Path(root)):
                self.last_success = self.last_saved = 0
                self.slot_health = {}
                self.tick_failure = self.error = ''
            self.notice = (f'已完整校验 {len(verified)} 份有效备份，{len(failures)} 项不可用；'
                           f'名称、固定与撤回记录仍保留，过去的时间节点将重新积累。原记录位于 {recovery}。')
            return {**manifest, 'recovery_directory': str(recovery), **self._storage_report(root)}

    def restore(self, root, payload):
        with self.lock:
            self._stage_attempt = None
            try:
                return self._restore(root, payload)
            except Exception as exc:
                if self._stage_attempt is not None:
                    stage_root, name = self._stage_attempt
                    if (Path(stage_root)/name).is_dir():
                        try:
                            records = self.stage_records(stage_root)
                            records[name]['reason'] = ('回档中断，暂存尚未应用：' + str(exc))[:1000]
                            atomic_json(self.scope(stage_root)/'stages.json', records)
                        except (OSError, ValueError):
                            pass  # The conservative pending reason remains on disk.
                if isinstance(exc, (BadZipFile, KeyError, TypeError, AttributeError, RuntimeError, RecursionError, OverflowError)):
                    raise ValueError("备份无法完整校验，尚未回档") from exc
                raise
            finally:
                self._storage_cache = None
                self._stage_attempt = None

    def stage_records(self, root):
        path = unlinked(self.scope(root)/'stages.json')
        if not path.exists():
            return {}
        if path.stat().st_size > 4*1024*1024:
            raise ValueError('暂存来源记录过大，原件仍保留')
        try:
            records = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(records, dict) or len(records) > 10000:
                raise ValueError()
            for name, row in records.items():
                match = STAGE_NAME.fullmatch(name)
                if (not match or not isinstance(row, dict) or set(row) !=
                        {'format', 'slot', 'backup_id', 'files', 'time', 'reason'}
                        or type(row['format']) is not int or row['format'] != 1
                        or type(row['slot']) is not int or row['slot'] != int(match[1])
                        or not isinstance(row['backup_id'], str) or not IDENTITY.fullmatch(row['backup_id'])
                        or not valid_time(row['time']) or not isinstance(row['reason'], str) or len(row['reason']) > 1000
                        or not isinstance(row['files'], dict) or not 1 <= len(row['files']) <= 10000
                        or any(not SAVE_NAME.fullmatch(key) or not isinstance(value, str)
                               or not IDENTITY.fullmatch(value) for key, value in row['files'].items())):
                    raise ValueError()
            return records
        except (ValueError, TypeError, AttributeError, RecursionError) as exc:
            raise ValueError('暂存来源记录损坏，保留全部暂存；请先导出原件核对') from exc

    @staticmethod
    def _journal_records(path):
        rows = read_records(path)
        for row in rows:
            if (not isinstance(row.get('id'), str) or not re.fullmatch(r'[0-9a-f]{32}', row['id'])
                    or type(row.get('slot')) is not int or row['slot'] not in range(1, 7)
                    or not valid_time(row.get('time')) or type(row.get('existed')) is not bool
                    or type(row.get('active')) is not bool
                    or 'target_backup' in row and (not isinstance(row['target_backup'], str) or not IDENTITY.fullmatch(row['target_backup']))
                    or not isinstance(row.get('original'), str)
                    or not re.fullmatch(r'\.denghuo-before-' + str(row['slot']) + r'-\d+-[0-9a-f]{8}', row['original'])
                    or (row['existed'] and (not isinstance(row.get('digest'), str) or not IDENTITY.fullmatch(row['digest'])))):
                raise ValueError('回档撤回记录损坏，尚未操作存档')
        return rows

    def journals(self, root):
        return self._journal_records(unlinked(self.scope(root) / 'restores.json'))

    @staticmethod
    def directory_digest(folder):
        unlinked(folder)
        if not folder.is_dir():
            raise ValueError('回档前目录不存在或不是目录')
        def collect():
            entries={};total=0
            for path in folder.rglob('*'):
                unlinked(path);attrs=path.stat()
                directory=stat.S_ISDIR(attrs.st_mode)
                if not directory and not stat.S_ISREG(attrs.st_mode) or len(entries)>=20000:
                    raise ValueError('槽位目录包含不支持的文件')
                entries[path.relative_to(folder).as_posix()]=(path,(attrs.st_mtime_ns,attrs.st_size,attrs.st_ino,directory))
                if not directory:total+=attrs.st_size
                if total>MAX_TOTAL:raise ValueError('槽位目录超过安全恢复大小限制')
            if sum(not stamp[3] for _,stamp in entries.values())>10000:
                raise ValueError('槽位目录包含过多文件')
            return entries
        entries=collect();hashes={}
        for name,(path,stamp) in sorted(entries.items()):
            if stamp[3]:continue
            with path.open('rb') as stream:raw=stream.read(stamp[1]+1)
            if len(raw)!=stamp[1]:raise ValueError('槽位目录正在变化，请稍后重试')
            hashes[name]=hashlib.sha256(raw).hexdigest()
        after=collect()
        if {name:stamp for name,(_,stamp) in entries.items()}!={name:stamp for name,(_,stamp) in after.items()}:
            raise ValueError('槽位目录正在变化，请稍后重试')
        return hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()

    def current_summary(self, root, slot):
        try:
            game, _, modified, warning = read_slot(Path(root), slot)
            return {**player_summary(game, modified), 'warning': warning}
        except (OSError, ValueError) as exc:
            return {'empty': True, 'warning': str(exc)}

    def _slot_state(self, folder):
        unlinked(folder)
        if not folder.exists():
            return False, None, None
        before = folder.stat()
        digest = self.directory_digest(folder)
        after = folder.stat()
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            raise ValueError('当前槽位目录正在变化，请重新预览')
        return True, (after.st_dev, after.st_ino), digest

    def preview(self, root, payload):
        with self.lock:
            row = self.selected(root, payload)
            metadata, _, game, _ = self.checked_archive(root, row['id'], row['slot'])
            target = player_summary(game, metadata['saved'])
            folder = unlinked(Path(root).resolve() / f"game{row['slot']}")
            before = self._slot_state(folder)
            current = self.current_summary(root, row['slot'])
            if before != self._slot_state(folder):
                raise ValueError('当前槽位在预览期间变化，请重新预览')
            return {'slot': row['slot'], 'target': target, 'current': current,
                    'expected_current': before[2],
                    'same_run': bool(target['run_id'] and target['run_id'] == current.get('run_id'))}

    def undo_status(self, root):
        rows = self.journals(root)
        return [{k: row.get(k) for k in ('id', 'slot', 'time', 'before', 'after')}
                for row in rows if row['active']]

    def undo_preview(self, root, payload):
        with self.lock:
            slot = payload.get('slot')
            if type(slot) is not int or slot not in range(1, 7):
                raise ValueError('槽位不正确')
            row = next((r for r in self.journals(root)
                        if r['id'] == payload.get('id') and r['slot'] == slot and r['active']), None)
            if row is None:
                raise ValueError('没有可撤回的回档记录，请重新打开存档历史')
            root = unlinked(Path(root)).resolve()
            folder = unlinked(root / f'game{slot}')
            original = unlinked(root / row['original'])
            if row['existed'] and self.directory_digest(original) != row['digest']:
                raise ValueError('回档前副本已变化，无法安全撤回；当前存档未改变')
            before = self._slot_state(folder)
            current = self.current_summary(root, slot)
            if before != self._slot_state(folder):
                raise ValueError('当前槽位在预览期间变化，请重新预览')
            if row['existed'] and self.directory_digest(original) != row['digest']:
                raise ValueError('回档前副本在预览期间变化，请重新打开存档历史')
            target = (row['before'] if isinstance(row.get('before'), dict) else
                      {'empty': True, 'warning': '回档前角色摘要不可读，请核对保留的原进度'})
            return {'id': row['id'], 'slot': slot, 'target': target, 'current': current,
                    'original_existed': row['existed'], 'expected_current': before[2],
                    'same_run': bool(target.get('run_id') and target.get('run_id') == current.get('run_id'))}

    def undo(self, root, payload):
        with self.lock:
            slot = payload.get('slot')
            if type(slot) is not int or slot not in range(1, 7) or payload.get('confirm') != f'撤回槽位 {slot}':
                raise ValueError('请明确确认撤回的槽位')
            rows = self.journals(root)
            row = next((r for r in rows if r['id'] == payload.get('id') and r['slot'] == slot and r['active']), None)
            if row is None:
                raise ValueError('没有可撤回的回档记录')
            self.closed_check()
            root = unlinked(Path(root)).resolve()
            folder = unlinked(root / f'game{slot}')
            original = unlinked(root / row['original'])
            if row['existed'] and self.directory_digest(original) != row['digest']:
                raise ValueError('回档前副本已变化，无法安全撤回；当前存档未改变')
            before = self._slot_state(folder)
            existed_now = before[0]
            current = self.current_summary(root, slot)
            if 'expected_current' in payload:
                expected = payload['expected_current']
                if expected is not None and (not isinstance(expected, str) or not IDENTITY.fullmatch(expected)):
                    raise ValueError('当前进度预览标识无效，请重新预览')
                if expected != before[2]:
                    raise ValueError('当前进度已变化，请重新预览后再确认撤回；当前存档未改变')
            preserved = unlinked(root / f'.denghuo-before-{slot}-{time.time_ns()}-{uuid.uuid4().hex[:8]}')
            self.closed_check()
            if row['existed'] and self.directory_digest(original) != row['digest']:
                raise ValueError('回档前副本已变化，无法安全撤回；当前存档未改变')
            if before != self._slot_state(folder):
                raise ValueError('当前槽位在撤回期间变化，尚未撤回')
            if existed_now:
                folder.replace(preserved)
            moved = False
            try:
                if row['existed']:
                    original.replace(folder)
                    moved = True
                row['active'] = False
                if existed_now:
                    rows.append({'id':uuid.uuid4().hex, 'slot':slot, 'time':self.clock(),
                                 'original':preserved.name, 'existed':True, 'digest':before[2],
                                 'active':False, 'before':current, 'after':current})
                atomic_json(self.scope(root) / 'restores.json', rows)
            except Exception:
                if moved:
                    folder.replace(original)
                if existed_now:
                    preserved.replace(folder)
                raise
            self.last_tick = 0
            self.notice = f'已撤回槽位 {slot} 的上次回档；撤回前进度也已完整保留。'
            self.slot_health.pop(slot, None)
            return self.notice

    def _restore(self, root, payload):
        with self.lock:
            slot, identity = payload.get("slot"), payload.get("id")
            if type(slot) is not int or slot not in range(1, 7) or payload.get("confirm") != f"恢复槽位 {slot}":
                raise ValueError("请明确确认恢复的槽位")
            if 'expected_current' in payload:
                expected = payload['expected_current']
                if expected is not None and (not isinstance(expected, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', expected)):
                    raise ValueError('预览进度摘要不正确，请重新预览')
                expected = expected.lower() if expected is not None else None
            root = unlinked(Path(root)).resolve()
            folder = unlinked(root / f"game{slot}")
            self.closed_check()
            current_state = self._slot_state(folder)
            existed, _, digest = current_state
            if 'expected_current' in payload and expected != digest:
                raise ValueError('当前槽位进度已变化，请重新预览；尚未回档')
            # Check the preview before selected/history can discover and publish any index.
            self.selected(root, payload)
            journals = self.journals(root)
            metadata, contents, game, _ = self.checked_archive(root, identity, slot)
            stamp = str(time.time_ns()) + "-" + uuid.uuid4().hex[:8]
            staging = unlinked(root / f".denghuo-stage-{slot}-{stamp}")
            original = unlinked(root / f".denghuo-before-{slot}-{stamp}")
            before = self.current_summary(root, slot)
            staging.mkdir()
            records = self.stage_records(root)
            records[staging.name] = {'format': 1, 'slot': slot, 'backup_id': identity,
                                    'files': metadata['files'], 'time': self.clock(),
                                    'reason': '上次回档解包、校验或交换未完成；此暂存未应用到活动进度'}
            if len(records) > 10000:
                raise ValueError('回档暂存记录已满；原件仍保留，请先核对空间清单')
            atomic_json(self.scope(root)/'stages.json', records)
            self._stage_attempt = (root, staging.name)
            for name, data in contents.items():
                (staging / name).write_bytes(data)
                recorded = metadata['stamps'][name]
                os.utime(staging / name, ns=(recorded, recorded))
            restored = read_bundle(staging / "game.dat")
            validate_hero(restored)
            validate_location(restored)
            depth_name = f"depth{restored['depth']}" + (f"-branch{restored.get('branch', 0)}" if restored.get("branch", 0) else "") + ".dat"
            if depth_name not in contents:
                raise ValueError("备份缺少当前楼层，尚未回档")
            for name in contents:
                if name != 'game.dat':
                    validate_level(read_bundle(staging / name))
            self.closed_check()  # Recheck immediately before the directory swap.
            if current_state != self._slot_state(folder):
                raise ValueError('原槽位在恢复期间变化，尚未回档')
            if existed:
                if not folder.is_dir():
                    raise ValueError("槽位路径不是目录，尚未回档")
                folder.replace(original)
            try:
                staging.replace(folder)
                for row in journals:
                    if row['slot'] == slot:
                        row['active'] = False
                journals.append({'id': uuid.uuid4().hex, 'slot': slot, 'time': self.clock(),
                                 'original': original.name, 'existed': existed, 'digest': digest,
                                 'active': True, 'target_backup': identity, 'before': before, 'after': player_summary(game, metadata['saved'])})
                atomic_json(self.scope(root) / 'restores.json', journals)
            except Exception:
                if folder.exists():
                    folder.replace(staging)
                if existed and not folder.exists():
                    original.replace(folder)
                raise
            self.notice = f'已恢复槽位 {slot}。回档前进度已完整保留，可点击「撤回上次回档」恢复。'
            self.last_tick = 0
            self.slot_health.pop(slot, None)
            return self.notice
