"""Stable disk snapshots; restoration is explicit and requires a closed game."""

from __future__ import annotations

import hashlib
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

from .saves import read_slot, list_slots, read_bundle, read_bundle_data, validate_hero, validate_location, validate_level, validate_floor_members
from .backup_archive import read_archive, player_summary, read_records, valid_time, IDENTITY

NODES = (3600, 1800, 600, 300, 120, 60, 50, 40, 30, 20, 10)
SAVE_NAME = re.compile(r"(?:game|depth\d+(?:-branch\d+)?)\.dat\Z")
MAX_TOTAL = 64 * 1024 * 1024
MAX_STORAGE = 512 * 1024 * 1024


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
    if sys.platform != "win32":
        raise ValueError("自动回档的游戏关闭检查目前仅支持 Windows")
    command = "Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object { $_.Name -match 'shattered|pixel|^java(w)?\\.exe$' } | Select-Object -ExpandProperty Name | ConvertTo-Json -Compress"
    powershell = Path(os.environ.get('SystemRoot') or os.environ.get('WINDIR') or 'C:/Windows')/'System32/WindowsPowerShell/v1.0/powershell.exe'
    try:
        result = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", command],
                                capture_output=True, text=True, timeout=10,
                                creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("无法检查游戏是否关闭，尚未回档") from exc
    if result.returncode:
        raise ValueError("无法检查游戏是否关闭，尚未回档")
    if result.stdout.strip():
        raise ValueError("请先完全退出游戏，再回档。检测到游戏或 Java 进程仍在运行")


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
            raise ValueError("备份时间记录过大，已停止操作")
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except RecursionError as exc:
            raise ValueError("备份时间记录损坏") from exc
        if not isinstance(rows, list) or len(rows) > 3000:
            raise ValueError("备份时间记录损坏")
        for row in rows:
            if (not isinstance(row, dict) or type(row.get("slot")) is not int or row["slot"] not in range(1, 7)
                    or type(row.get("time")) not in (int, float) or not 0 <= row["time"] <= 32503680000
                    or type(row.get("saved")) not in (int, float) or not 0 <= row["saved"] <= 32503680000
                    or type(row.get("depth")) is not int or not 1 <= row["depth"] <= 26
                    or not isinstance(row.get("class"), str) or len(row["class"]) > 40
                    or (row.get("version") is not None and (type(row["version"]) is not int or not 0 <= row["version"] <= 2147483647))
                    or not isinstance(row.get("id"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", row["id"])):
                raise ValueError("备份时间记录损坏")
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
        result = {'active': active, 'retained': recycle, 'quarantine': quarantine, 'before_restore': before,
                  'total': active+recycle+quarantine+before}
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
        try:
            result = read_archive(path, slot=slot, identity=identity)
            self.archive_health[identity] = {'valid': True, 'error': '', 'checked': self.clock()}
            return result
        except (ValueError, OSError) as exc:
            self.archive_health[identity] = {'valid': False, 'error': str(exc), 'checked': self.clock()}
            raise

    def history(self, root, *, discover=True):
        scope = self.scope(root)
        path = unlinked(scope / 'history.json')
        rows = read_records(path)
        for row in rows:
            if (not isinstance(row.get('id'), str) or not IDENTITY.fullmatch(row['id'])
                    or type(row.get('slot')) is not int or row['slot'] not in range(1, 7)
                    or not valid_time(row.get('time')) or not valid_time(row.get('last_seen'))
                    or not isinstance(row.get('label', ''), str) or len(row.get('label', '')) > 80
                    or type(row.get('locked', False)) is not bool):
                raise ValueError('备份历史记录损坏')
        if len({(r['slot'], r['id']) for r in rows}) != len(rows):
            raise ValueError('备份历史记录重复')
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
        return rows

    def register(self, root, row, retained=None):
        rows = self.history(root)
        existing = next((r for r in rows if r['slot'] == row['slot'] and r['id'] == row['id']), None)
        if existing:
            existing.update({**row, 'time': min(existing['time'], row['time']), 'label': existing.get('label', ''),
                             'locked': existing.get('locked', False), 'last_seen': row['time']})
        else:
            rows.append({**row, 'last_seen': row['time'], 'label': '', 'locked': False})
        if retained:
            target = existing if existing is not None else rows[-1]
            target['time'] = min(target['time'], retained['first_seen'])
            if not target.get('label'):
                target['label'] = retained['label']
        if len(rows) > 10000:
            raise ValueError('备份历史已满，请导出并整理旧记录')
        atomic_json(self.scope(root) / 'history.json', rows)

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
            target.update(label=label.strip(), locked=locked)
            atomic_json(self.scope(root) / 'history.json', rows)
            self.notice = '备份名称与保留设置已保存'

    def validate(self, root):
        with self.lock:
            errors = []
            rows = self.history(root)
            for row in rows:
                try:
                    self.checked_archive(root, row['id'], row['slot'])
                except (ValueError, OSError) as exc:
                    errors.append(f"槽位 {row['slot']}：{exc}")
            self.notice = f'已检查{len(rows)}份备份，{len(errors)}份不可用。'
            if errors:
                self.notice += ' 自动备份会在相同有效进度再次出现时重建损坏副本。'
            return errors

    def export(self, root, payload):
        with self.lock:
            row = self.selected(root, payload)
            self.checked_archive(root, row['id'], row['slot'])
            path = unlinked(self.scope(root) / (row['id'] + '.zip'))
            stamp = path.stat()
            raw = path.read_bytes()
            after = path.stat()
            if len(raw) > MAX_TOTAL or (stamp.st_mtime_ns, stamp.st_size, stamp.st_ino) != (after.st_mtime_ns, after.st_size, after.st_ino):
                raise ValueError('备份在导出期间变化，请重新检查')
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
                self.register(root, row, retained=retained)
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
                            'label':row.get('label',''), 'first_seen':row['time']})
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

    def capture(self, root, slot):
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
            unlinked(path)
            attrs = path.stat()
            if not path.is_file() or attrs.st_size > 16 * 1024 * 1024:
                raise ValueError("存档文件类型或大小不正确")
            stamps[path.name] = (attrs.st_mtime_ns, attrs.st_size, attrs.st_ino)
            total += attrs.st_size
            if total > MAX_TOTAL:
                raise ValueError("此槽位存档超过备份大小限制")
            payloads[path.name] = path.read_bytes()
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
                target.replace(unlinked(quarantine / f'{identity}-{time.time_ns()}.zip'))
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
            pending.replace(target)
            self.checked_archive(root, identity, slot)
        row = {**player_summary(game, modified), "time": self.clock(), "slot": slot, "id": identity}
        self.register(root, row)
        return row

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
            error = self.error if slot is None else self.tick_failure
            if slot is not None:
                own = self.slot_health.get(slot, {}) if current else {}
                success, saved = own.get('last_success', 0), own.get('saved', 0)
                error = error or own.get('error', '')
            state = ('paused' if not self.enabled else 'blocked' if error or not Path(root).is_dir()
                     else 'waiting' if not success or self.clock() - saved > 60 else 'protected')
            return {'state': state, 'error': error, 'last_success': success, 'saved': saved, 'slot': slot,
                    'other_errors': self.error if slot is not None and self.error != error else ''}

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
                history = [{**r, 'integrity': self.archive_health.get(r['id'], {'valid': None, 'error': ''})}
                           for r in sorted(history, key=lambda r: r['last_seen'], reverse=True)]
                latest_time = max((r['time'] for r in rows), default=0)
                state = self.health_status(root)['state']
                return {"enabled": self.enabled, "error": self.error, "notice": self.notice,
                        "slots": sorted(slots, key=lambda s: s['slot']), "directory": str(self.directory), "interval": 10,
                        'history': history, 'storage_bytes': self.storage(), 'storage_limit': MAX_STORAGE,
                        'storage_breakdown': self.storage_breakdown(root), 'retained': self.retained_status(root),
                        'health': state, 'last_success': max(self.last_success, latest_time),
                        'undo': undo}
            except (OSError, ValueError) as exc:
                return {"enabled": self.enabled, "error": str(exc), "slots": [], "notice": self.notice,
                        "directory": str(self.directory), "interval": 10, 'history': [], 'health': 'blocked',
                        'last_success': self.last_success, 'undo': [], 'storage_bytes': 0, 'storage_limit': MAX_STORAGE}

    def restore(self, root, payload):
        try:
            return self._restore(root, payload)
        except (BadZipFile, KeyError, TypeError, AttributeError, RuntimeError, RecursionError, OverflowError) as exc:
            raise ValueError("备份无法完整校验，尚未回档") from exc

    def journals(self, root):
        rows = read_records(unlinked(self.scope(root) / 'restores.json'))
        for row in rows:
            if (not isinstance(row.get('id'), str) or not re.fullmatch(r'[0-9a-f]{32}', row['id'])
                    or type(row.get('slot')) is not int or row['slot'] not in range(1, 7)
                    or not valid_time(row.get('time')) or type(row.get('existed')) is not bool
                    or type(row.get('active')) is not bool
                    or not isinstance(row.get('original'), str)
                    or not re.fullmatch(r'\.denghuo-before-' + str(row['slot']) + r'-\d+-[0-9a-f]{8}', row['original'])
                    or (row['existed'] and not IDENTITY.fullmatch(row.get('digest', '')))):
                raise ValueError('回档撤回记录损坏，尚未操作存档')
        return rows

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

    def preview(self, root, payload):
        with self.lock:
            row = self.selected(root, payload)
            metadata, _, game, _ = self.checked_archive(root, row['id'], row['slot'])
            target = player_summary(game, metadata['saved'])
            current = self.current_summary(root, row['slot'])
            return {'slot': row['slot'], 'target': target, 'current': current,
                    'same_run': bool(target['run_id'] and target['run_id'] == current.get('run_id'))}

    def undo_status(self, root):
        rows = self.journals(root)
        return [{k: row.get(k) for k in ('id', 'slot', 'time', 'before', 'after')}
                for row in rows if row['active']]

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
            existed_now = folder.exists()
            current_digest = self.directory_digest(folder) if existed_now else None
            preserved = unlinked(root / f'.denghuo-before-{slot}-{time.time_ns()}-{uuid.uuid4().hex[:8]}')
            self.closed_check()
            if row['existed'] and self.directory_digest(original) != row['digest']:
                raise ValueError('回档前副本已变化，无法安全撤回；当前存档未改变')
            if existed_now != folder.exists() or (existed_now and self.directory_digest(folder) != current_digest):
                raise ValueError('当前槽位在撤回期间变化，尚未撤回')
            if existed_now:
                folder.replace(preserved)
            moved = False
            try:
                if row['existed']:
                    original.replace(folder)
                    moved = True
                row['active'] = False
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
            self.selected(root, payload)
            journals = self.journals(root)
            self.closed_check()
            metadata, contents, game, _ = self.checked_archive(root, identity, slot)
            root = unlinked(Path(root)).resolve()
            folder = unlinked(root / f"game{slot}")
            stamp = str(time.time_ns()) + "-" + uuid.uuid4().hex[:8]
            staging = unlinked(root / f".denghuo-stage-{slot}-{stamp}")
            original = unlinked(root / f".denghuo-before-{slot}-{stamp}")
            existed = folder.exists()
            digest = self.directory_digest(folder) if existed else None
            before = self.current_summary(root, slot)
            staging.mkdir()
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
            if existed != folder.exists() or (existed and self.directory_digest(folder) != digest):
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
                                 'active': True, 'before': before, 'after': player_summary(game, metadata['saved'])})
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
