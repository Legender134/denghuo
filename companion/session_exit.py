"""One explicit exit decision shared by every live editing surface."""
from __future__ import annotations

import copy
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import threading
import time
import uuid

from .backups import atomic_json, unlinked

SURFACE = re.compile(r'(?:native(?:[-_][a-z0-9]{1,48})?|web-[a-f0-9]{8,64})\Z')
DRAFT_ID = re.compile(r'[a-f0-9]{32}\Z')
MAX_DRAFT = 1024 * 1024
# ASCII escaping and indentation of a bounded raw form can expand on disk.
MAX_DRAFT_FILE = 8 * MAX_DRAFT
# Portable batch bound; explicitly saved local drafts are retained across batches.
MAX_SAVED_DRAFTS = 200
MAX_DRAFT_SET = 16 * 1024 * 1024
MAX_RECOVERY_RECORDS = 200
MAX_RECOVERY_BYTES = 64 * 1024 * 1024
ONLINE_SECONDS = 12
CLEAN_LEASE_SECONDS = 120


def bounded_text(value, maximum, label):
    if (not isinstance(value, str) or len(value) > maximum
            or any(ord(char) < 32 and char not in '\n\t' for char in value)):
        raise ValueError(f'{label}格式不正确')
    return value


def checked_draft(value):
    if not isinstance(value, dict):
        raise ValueError('草稿需要是一个对象')
    try:
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, RecursionError, UnicodeError) as exc:
        raise ValueError('草稿内容无法保存') from exc
    if len(raw) > MAX_DRAFT:
        raise ValueError('草稿超过1 MiB，请先分别保存方案')
    # Own forms have no authentication fields. Never store an entire status response.
    pending = [(value, 0)]
    nodes = 0
    while pending:
        current, depth = pending.pop()
        nodes += 1
        if depth > 20 or nodes > 60000:
            raise ValueError('草稿结构过深或条目过多，原件仍保留')
        if isinstance(current, dict):
            if any(not isinstance(key, str) or len(key) > 120 for key in current):
                raise ValueError('草稿字段名称不正确')
            if any(re.sub(r'[-_\s]', '', key).casefold() in
                   ('token', 'password', 'authorization', 'secret', 'apikey', 'accesstoken',
                    'refreshtoken', 'cookie', 'credentials') for key in current):
                raise ValueError('草稿不能包含运行口令或密码；请只保存表单内容')
            pending.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            pending.extend((item, depth + 1) for item in current)
    return json.loads(raw)


def checked_saved_draft(value, identity=None):
    """Validate a portable record without interpreting or applying its raw form."""
    fields = {'format', 'kind', 'id', 'surface_id', 'draft_kind', 'label', 'saved', 'draft'}
    if (not isinstance(value, dict) or set(value) not in (fields, fields | {'lifecycle'}) or type(value['format']) is not int
            or value['format'] not in (1, 2) or value['kind'] != 'denghuo-unfinished-draft'
            or not isinstance(value['id'], str) or not DRAFT_ID.fullmatch(value['id'])
            or identity is not None and value['id'] != identity
            or not isinstance(value['surface_id'], str) or not SURFACE.fullmatch(value['surface_id'])
            or type(value['saved']) not in (int, float) or not math.isfinite(value['saved'])
            or not 0 <= value['saved'] <= 32503680000):
        raise ValueError('草稿格式或版本不兼容，原件仍保留；尚未载入或应用')
    result = copy.deepcopy(value)
    if 'lifecycle' in result and (result['format'] != 2 or result['lifecycle'] not in ('active', 'archived')):
        raise ValueError('草稿归档状态不兼容，原件仍保留')
    bounded_text(result['draft_kind'], 60, '草稿类型')
    bounded_text(result['label'], 120, '草稿名称')
    result['draft'] = checked_draft(result['draft'])
    return result


def checked_draft_set(value):
    if (not isinstance(value, dict) or set(value) != {'format', 'kind', 'records'}
            or type(value['format']) is not int or value['format'] != 1
            or value['kind'] != 'denghuo-exit-draft-set' or not isinstance(value['records'], list)
            or not 1 <= len(value['records']) <= MAX_SAVED_DRAFTS):
        raise ValueError('已保存草稿迁移成员格式、版本或数量不正确')
    records = [checked_saved_draft(row) for row in value['records']]
    if len({row['id'] for row in records}) != len(records):
        raise ValueError('草稿迁移成员包含重复身份，尚未导入')
    if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')) > MAX_DRAFT_SET:
        raise ValueError('草稿迁移成员超过16 MiB，尚未导入')
    return records


class ExitDraftStore:
    """Explicitly saved unfinished forms; loading never applies them to the game."""
    def __init__(self, directory):
        self.directory = Path(directory)
        self.lock = threading.RLock()

    def save(self, surface_id, kind, label, draft):
        if not isinstance(surface_id, str) or not SURFACE.fullmatch(surface_id):
            raise ValueError('草稿窗口身份不正确')
        kind = bounded_text(kind, 60, '草稿类型')
        label = bounded_text(label, 120, '草稿名称')
        draft = checked_draft(draft)
        identity = uuid.uuid4().hex
        # Older clients reject v2 before interpreting newer recovery contracts.
        value = {'format': 2, 'kind': 'denghuo-unfinished-draft', 'id': identity,
                 'surface_id': surface_id, 'draft_kind': kind, 'label': label,
                 'saved': time.time(), 'draft': draft, 'lifecycle': 'active'}
        with self.lock:
            unlinked(self.directory).mkdir(parents=True, exist_ok=True)
            path = unlinked(self.directory / (identity + '.json'))
            atomic_json(path, value)
        return {'id': identity, 'kind': kind, 'label': label, 'saved': value['saved'],
                'path': str(path), 'notice': '未完成草稿副本已保存；重新载入后仍需手动确认。'}

    def load(self, identity):
        if not isinstance(identity, str) or not DRAFT_ID.fullmatch(identity):
            raise ValueError('草稿身份不正确')
        with self.lock:
            path = unlinked(self.directory / (identity + '.json'))
            try:
                with path.open('rb') as stream:
                    raw = stream.read(MAX_DRAFT_FILE + 1)
                if len(raw) > MAX_DRAFT_FILE:
                    raise ValueError('草稿文件过大，原件仍保留')
                value = json.loads(raw)
                return checked_saved_draft(value, identity)
            except (OSError, UnicodeError, RecursionError) as exc:
                raise ValueError('草稿暂时无法读取，原件仍保留') from exc

    def stamp(self):
        """CAS includes invalid originals, so import cannot overwrite unseen edits."""
        with self.lock:
            if not self.directory.exists():
                return {}
            rows = {}
            for path in unlinked(self.directory).glob('*.json'):
                path = unlinked(path)
                if path.stat().st_size > MAX_DRAFT_FILE:
                    raise ValueError('已有草稿文件大小超过迁移限制，原件仍保留')
                rows[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
            return rows

    def lifecycle(self, identity):
        """Keep completion state beside the immutable original, bound to its bytes."""
        with self.lock:
            record = self.load(identity)
            original = unlinked(self.directory / (identity + '.json')).read_bytes()
            digest = hashlib.sha256(original).hexdigest()
            path = unlinked(self.directory / (identity + '.state.json'))
            raw = b''
            state = record.get('lifecycle', 'active')
            if path.exists():
                with path.open('rb') as stream:
                    raw = stream.read(4097)
                try:
                    value = json.loads(raw)
                    if (len(raw) > 4096 or not isinstance(value, dict)
                            or set(value) != {'format', 'id', 'original_sha256', 'state', 'generation'}
                            or type(value['format']) is not int or value['format'] != 1
                            or value['id'] != identity or value['original_sha256'] != digest
                            or value['state'] not in ('active', 'archived')
                            or not isinstance(value['generation'], str) or not DRAFT_ID.fullmatch(value['generation'])):
                        raise ValueError('invalid state')
                    state = value['state']
                except (ValueError, UnicodeError, RecursionError) as exc:
                    raise ValueError('草稿归档状态无法核对；原件仍保留，请先核对副本') from exc
            return {'state': state, 'state_revision': hashlib.sha256(digest.encode() + b'\0' + raw).hexdigest()}

    def set_lifecycle(self, identity, state, expected_revision):
        if state not in ('active', 'archived'):
            raise ValueError('请选择归档或恢复到未完成列表')
        with self.lock:
            current = self.lifecycle(identity)
            if expected_revision != current['state_revision']:
                raise ValueError('草稿或归档状态已变化；请重新读取列表，原副本仍保留')
            path = unlinked(self.directory / (identity + '.json'))
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            atomic_json(unlinked(self.directory / (identity + '.state.json')),
                {'format': 1, 'id': identity, 'original_sha256': digest, 'state': state,
                 'generation': uuid.uuid4().hex})
            return {'id': identity, **self.lifecycle(identity), 'applied': False}

    @staticmethod
    def same_content(first, second):
        # Portable v2 can add lifecycle to a v1 original without changing its form.
        return {**{k: v for k, v in first.items() if k != 'lifecycle'}, 'format': 2} == {
            **{k: v for k, v in second.items() if k != 'lifecycle'}, 'format': 2}

    def export_records(self, identities, text_filter=lambda text: text):
        """Only migration copies are redacted; persisted local drafts are unchanged."""
        if (not isinstance(identities, list) or not 1 <= len(identities) <= MAX_SAVED_DRAFTS
                or any(not isinstance(identity, str) or not DRAFT_ID.fullmatch(identity) for identity in identities)
                or len(set(identities)) != len(identities)):
            raise ValueError('请选择1–200份已保存草稿')
        def portable(value):
            if isinstance(value, str):
                return text_filter(value)
            if isinstance(value, list):
                return [portable(item) for item in value]
            if isinstance(value, dict):
                return {key: portable(item) for key, item in value.items()}
            return value
        with self.lock:
            records = []
            for identity in identities:
                record = portable(self.load(identity))
                record.update(format=2, lifecycle=self.lifecycle(identity)['state'])
                records.append(checked_saved_draft(record))
            checked_draft_set({'format': 1, 'kind': 'denghuo-exit-draft-set', 'records': records})
            return records

    def preview_import(self, record):
        addition, message, _ = self._resolve_import(checked_saved_draft(record))
        return addition, message

    def _resolve_import(self, record):
        with self.lock:
            path = unlinked(self.directory / (record['id'] + '.json'))
            if not path.exists():
                return record, '新增已保存原始草稿；需明确载入，不计算或应用', record['id']
            try:
                if self.same_content(self.load(record['id']), record):
                    return None, '相同草稿已存在，保留本机原件和归档状态', record['id']
            except ValueError:
                pass  # A damaged local original is also preserved, never replaced.
            canonical = {**{k: v for k, v in record.items() if k != 'lifecycle'}, 'format': 2}
            # Recognize copies made by older versions without rewriting either
            # original or its local lifecycle sidecar. Lifecycle is not content.
            variants = (canonical, {**canonical, 'format': 1},
                        {**canonical, 'lifecycle': 'active'}, {**canonical, 'lifecycle': 'archived'})
            identities = list(dict.fromkeys(hashlib.sha256(json.dumps(value,
                ensure_ascii=True, sort_keys=True).encode()).hexdigest()[:32] for value in variants))
            for identity in identities:
                copied = {**record, 'id': identity}
                copied_path = unlinked(self.directory / (identity + '.json'))
                if not copied_path.exists():
                    continue
                try:
                    if self.same_content(self.load(identity), copied):
                        return None, '同ID冲突副本已存在，双方均保留', identity
                except ValueError:
                    pass
            copied = {**record, 'id': identities[0]}
            if unlinked(self.directory / (copied['id'] + '.json')).exists():
                raise ValueError('草稿冲突副本身份已占用，原件仍保留；请先核对本机草稿')
            return copied, '同ID内容不同，保留双方并新增原始草稿副本', copied['id']

    def import_record(self, record):
        with self.lock:
            record = checked_saved_draft(record)
            addition, message, stored_id = self._resolve_import(record)
            if addition is not None:
                # The 200-record limit applies to one portable batch, not to the
                # user's lifetime of explicitly preserved unfinished work.
                unlinked(self.directory).mkdir(parents=True, exist_ok=True)
                # Exclusive creation closes the cross-process check/write race.
                path = unlinked(self.directory / (addition['id'] + '.json'))
                with path.open('xb') as stream:
                    stream.write(json.dumps(addition, ensure_ascii=True, indent=2).encode())
            return {'id': stored_id, 'message': message,
                    'loaded': False, 'calculated': False, 'applied': False}

    def list(self, include_archived=False):
        if type(include_archived) is not bool:
            raise ValueError('草稿归档筛选不正确')
        with self.lock:
            if not self.directory.exists():
                return []
            unlinked(self.directory)
            rows = []
            for path in self.directory.glob('*.json'):
                if not DRAFT_ID.fullmatch(path.stem):
                    continue
                try:
                    value = self.load(path.stem)
                    lifecycle = self.lifecycle(path.stem)
                    if include_archived or lifecycle['state'] == 'active':
                        rows.append({**{key: value[key] for key in ('id', 'draft_kind', 'label', 'saved', 'surface_id')}, **lifecycle})
                except (ValueError, OSError) as exc:
                    rows.append({'id': path.stem, 'error': str(exc), 'saved': 0})
            return sorted(rows, key=lambda row: row['saved'], reverse=True)


class ExitRecoveryJournal:
    """Bounded recent raw reports, separate from explicitly saved user drafts."""
    def __init__(self, directory, saved_drafts):
        self.directory, self.saved_drafts = Path(directory), saved_drafts
        self.preserved_directory = self.directory.with_name('exit-recovery-preserved')
        self.session_id = uuid.uuid4().hex
        self.lock = threading.RLock()
        self.fingerprints = {}

    def identity(self, surface_id, session_id=None):
        return hashlib.sha256(((session_id or self.session_id) + '\0' + surface_id).encode()).hexdigest()[:32]

    @contextmanager
    def _storage_lock(self):
        # One OS lock serializes checkpoint/archive CAS across assistant processes.
        # The OS releases it on a crash; the small lock file can safely stay in place.
        directory = unlinked(self.directory)
        directory.mkdir(parents=True, exist_ok=True)
        with unlinked(directory / '.lock').open('a+b') as stream:
            deadline = time.monotonic() + 1
            while True:
                try:
                    stream.seek(0)
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise ValueError('自动草稿正在由另一个窗口处理，请稍后重试')
                    time.sleep(.02)
            try:
                if stream.seek(0, 2) == 0:
                    stream.write(b'\0')
                    stream.flush()
                yield
            finally:
                stream.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _path(self, identity):
        # A selector distinguishes interrupted bytes from the committed sibling.
        original = identity[:-8] if isinstance(identity, str) and identity.endswith('.pending') else identity
        if not isinstance(original, str) or not DRAFT_ID.fullmatch(original):
            raise ValueError('自动草稿身份不正确')
        return unlinked(self.directory / (original + '.json' + ('.pending' if original != identity else ''))), original

    def _files(self):
        directory = unlinked(self.directory)
        return [*directory.glob('*.json'), *directory.glob('*.json.pending')]

    @staticmethod
    def _bounded_bytes(path, maximum):
        path = unlinked(path)
        before = path.stat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
            raise ValueError('自动草稿文件不是普通文件或超过大小限制，原件保留')
        with path.open('rb') as stream:
            opened = os.fstat(stream.fileno())
            raw = stream.read(maximum + 1)
            after = os.fstat(stream.fileno())
        current = unlinked(path).stat()
        stamps = {(row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns)
                  for row in (before, opened, after, current)}
        # Windows 3.12 stat/fstat can expose different ctime semantics for the
        # same stable file. Compare each API over time, retaining cross-API
        # identity, size and mtime checks; POSIX ctime remains cross-checked too.
        ctime_changed = (before.st_ctime_ns != current.st_ctime_ns
                         or opened.st_ctime_ns != after.st_ctime_ns)
        if os.name != 'nt':
            ctime_changed |= before.st_ctime_ns != opened.st_ctime_ns
        if len(raw) > maximum or len(raw) != before.st_size or len(stamps) != 1 or ctime_changed:
            raise ValueError('自动草稿文件正在变化或超过大小限制，原件保留；请重新核对')
        return raw

    def _raw(self, identity):
        path, _ = self._path(identity)
        return self._bounded_bytes(path, MAX_DRAFT_FILE)

    def _read(self, identity):
        _, original = self._path(identity)
        raw = self._raw(identity)
        return self._parse(original, raw), raw

    def _parse(self, original, raw):
        try:
            value = json.loads(raw)
            if (not isinstance(value, dict) or set(value) != {'format', 'kind', 'session_id', 'revision', 'record'}
                    or type(value['format']) is not int or value['format'] != 1
                    or value['kind'] != 'denghuo-recovery-checkpoint'
                    or not isinstance(value['session_id'], str) or not DRAFT_ID.fullmatch(value['session_id'])
                    or type(value['revision']) is not int or not 0 <= value['revision'] <= 2 ** 53):
                raise ValueError('自动草稿版本不兼容')
            record = checked_saved_draft(value['record'], original)
            if original != self.identity(record['surface_id'], value['session_id']):
                raise ValueError('自动草稿会话与窗口不匹配')
            return value
        except (UnicodeError, RecursionError, ValueError, OverflowError) as exc:
            raise ValueError('自动草稿无法核对，原件仍保留；尚未载入') from exc

    def checkpoint(self, surface_id, revision, dirty, draft, kind, label):
        if not isinstance(surface_id, str) or not SURFACE.fullmatch(surface_id):
            raise ValueError('自动草稿窗口身份不正确')
        identity = self.identity(surface_id)
        signature = None
        with self.lock:
            path = unlinked(self.directory / (identity + '.json'))
            interrupted = unlinked(self.directory / (identity + '.json.pending')).exists()
            if not dirty and not path.exists() and not interrupted:
                self.fingerprints.pop(identity, None)
                return False
            if dirty and draft is not None:
                draft = checked_draft(draft)
                signature = json.dumps([revision, draft, kind, label], ensure_ascii=True, sort_keys=True)
                known = self.fingerprints.get(identity)
                if known and known[0] == signature and path.exists() and not interrupted:
                    _, raw = self._read(identity)
                    if hashlib.sha256(raw).hexdigest() != known[1]:
                        raise ValueError('自动草稿落盘副本已变化，原件保留；请明确保存当前窗口的草稿副本')
                    return True
        with self.lock, self._storage_lock():
            path = unlinked(self.directory / (identity + '.json'))
            if unlinked(self.directory / (identity + '.json.pending')).exists():
                raise ValueError('自动草稿有中断副本，原件保留；请在未完成草稿中核对并明确归档后重试')
            if not dirty:
                if path.exists():
                    value, _ = self._read(identity)
                    if value['session_id'] != self.session_id or revision < value['revision']:
                        raise ValueError('自动草稿版本已变化，原件保留')
                    path.unlink()
                self.fingerprints.pop(identity, None)
                return False
            if draft is None:
                return False
            if path.exists():
                previous, _ = self._read(identity)
                if previous['session_id'] != self.session_id or revision < previous['revision']:
                    raise ValueError('自动草稿版本已变化，原件保留')
            record = {'format': 2, 'kind': 'denghuo-unfinished-draft', 'id': identity,
                'surface_id': surface_id, 'draft_kind': 'offline-native' if kind == 'native' else 'web-session',
                'label': '自动保留 · ' + label[:110], 'saved': time.time(), 'draft': draft, 'lifecycle': 'active'}
            value = {'format': 1, 'kind': 'denghuo-recovery-checkpoint', 'session_id': self.session_id,
                     'revision': revision, 'record': checked_saved_draft(record, identity)}
            size = len(json.dumps(value, ensure_ascii=True, indent=2).replace('\n', os.linesep).encode('utf-8'))
            directory = unlinked(self.directory)
            directory.mkdir(parents=True, exist_ok=True)
            files = self._files()
            # Reserve the physical write peak: a crash can retain both siblings.
            if (len(files) + 1 > MAX_RECOVERY_RECORDS
                    or sum(unlinked(item).stat().st_size for item in files) + size > MAX_RECOVERY_BYTES):
                raise ValueError('自动草稿空间已满；请在未完成草稿中核对并归档旧副本，已有原件保留')
            atomic_json(path, value)
            written, raw = self._read(identity)
            if written != value:
                raise ValueError('自动草稿写入核验未完成，原件保留；请明确保存当前窗口的草稿副本')
            self.fingerprints[identity] = (signature, hashlib.sha256(raw).hexdigest())
            return True

    def load(self, identity):
        with self.lock, self._storage_lock():
            value, _ = self._read(identity)
            return copy.deepcopy(value['record'])

    def contains(self, identity):
        path, _ = self._path(identity)
        return path.exists()

    def list(self):
        with self.lock:
            if not self.directory.exists():
                return []
            with self._storage_lock():
                rows = []
                for path in self._files():
                    pending = path.name.endswith('.json.pending')
                    original = path.name[:-13] if pending else path.stem
                    if not DRAFT_ID.fullmatch(original):
                        continue
                    identity = original + ('.pending' if pending else '')
                    try:
                        value, raw = self._read(identity)
                        if not pending and value['session_id'] == self.session_id:
                            continue
                        record = value['record']
                        rows.append({**{key: record[key] for key in ('draft_kind', 'label', 'saved', 'surface_id')},
                                     'id': identity, 'label': ('中断副本 · ' if pending else '') + record['label'],
                                     'state': 'active', 'state_revision': hashlib.sha256(raw).hexdigest(),
                                     'recovery': True, 'pending': pending})
                    except (ValueError, OSError) as exc:
                        row = {'id': identity, 'saved': 0, 'recovery': True, 'pending': pending,
                               'state': 'active', 'path': str(path), 'raw_preservable': False,
                               'label': '无法核对的中断副本' if pending else '无法核对的自动草稿', 'error': str(exc)}
                        try:
                            raw = self._raw(identity)
                            row.update(raw_preservable=True, bytes=len(raw),
                                       state_revision=hashlib.sha256(raw).hexdigest(),
                                       sha256=hashlib.sha256(raw).hexdigest())
                        except (ValueError, OSError) as read_error:
                            row['error'] = str(read_error)
                        rows.append(row)
            return sorted(rows, key=lambda row: row['saved'], reverse=True)

    def read_preserved(self, identity):
        """Verify the stored original bytes; never interpret them as a form."""
        if not isinstance(identity, str) or not DRAFT_ID.fullmatch(identity):
            raise ValueError('已保留原始文件身份不正确')
        with self.lock:
            metadata_raw = self._bounded_bytes(self.preserved_directory / (identity + '.json'), 4096)
            try:
                value = json.loads(metadata_raw)
                if (not isinstance(value, dict)
                        or set(value) != {'format', 'kind', 'id', 'source_name', 'saved', 'bytes', 'sha256'}
                        or type(value['format']) is not int or value['format'] != 1
                        or value['kind'] != 'denghuo-recovery-original' or value['id'] != identity
                        or not isinstance(value['source_name'], str)
                        or not re.fullmatch(r'[a-f0-9]{32}\.json(?:\.pending)?', value['source_name'])
                        or type(value['saved']) not in (int, float) or not 0 <= value['saved'] <= 32503680000
                        or not math.isfinite(value['saved'])
                        or type(value['bytes']) is not int or not 0 <= value['bytes'] <= MAX_DRAFT_FILE
                        or not isinstance(value['sha256'], str) or not re.fullmatch(r'[a-f0-9]{64}', value['sha256'])):
                    raise ValueError('已保留原始文件的核对记录不兼容')
            except (UnicodeError, RecursionError, ValueError) as exc:
                raise ValueError('已保留原始文件的核对记录无法读取，副本仍保留') from exc
            raw = self._bounded_bytes(self.preserved_directory / (identity + '.raw'), MAX_DRAFT_FILE)
            if len(raw) != value['bytes'] or hashlib.sha256(raw).hexdigest() != value['sha256']:
                raise ValueError('已保留原始文件大小或内容已变化，副本仍保留；尚未获取')
            if self._bounded_bytes(self.preserved_directory / (identity + '.json'), 4096) != metadata_raw:
                raise ValueError('原始文件的核对记录已变化，副本仍保留；请重新核对')
            return value, raw

    def list_preserved(self):
        with self.lock:
            if not self.preserved_directory.exists():
                return []
            directory = unlinked(self.preserved_directory)
            identities = {path.stem for pattern in ('*.json', '*.raw') for path in directory.glob(pattern)
                          if DRAFT_ID.fullmatch(path.stem)}
            rows = []
            for identity in sorted(identities):
                row = {'id': 'raw-' + identity, 'saved': 0, 'state': 'archived', 'raw_original': True,
                       'label': '已保留的原始自动草稿文件', 'path': str(directory / (identity + '.raw'))}
                try:
                    value, raw = self.read_preserved(identity)
                    row.update({key: value[key] for key in ('saved', 'source_name', 'bytes', 'sha256')})
                    row['state_revision'] = value['sha256']
                except (ValueError, OSError) as exc:
                    row['error'] = str(exc)
                rows.append(row)
            return sorted(rows, key=lambda row: row['saved'], reverse=True)

    def original(self, identity, expected_revision):
        if not isinstance(identity, str) or not identity.startswith('raw-'):
            raise ValueError('请选择已保留的原始文件')
        value, raw = self.read_preserved(identity[4:])
        if value['sha256'] != expected_revision:
            raise ValueError('原始文件已变化，请重新读取列表后核对')
        return {**value, 'path': str(self.preserved_directory / (value['id'] + '.raw'))}, raw

    @staticmethod
    def _write_original(path, raw):
        with unlinked(path).open('xb') as stream:
            if stream.write(raw) != len(raw):
                raise OSError('原始副本未完整写入，活动原件保留')
            stream.flush()
            os.fsync(stream.fileno())

    def preserve_raw(self, identity, expected_revision, confirmed):
        if confirmed is not True:
            raise ValueError('请先核对文件位置、字节数和摘要，并明确确认保留原始文件')
        with self.lock, self._storage_lock():
            path, original = self._path(identity)
            raw = self._raw(identity)
            digest = hashlib.sha256(raw).hexdigest()
            if digest != expected_revision:
                raise ValueError('自动草稿已更新，请重新读取列表；原件仍保留')
            try:
                self._parse(original, raw)
            except ValueError:
                pass
            else:
                raise ValueError('这是可核对的完整草稿，请使用载入或普通归档')
            stored = uuid.uuid4().hex
            value = {'format': 1, 'kind': 'denghuo-recovery-original', 'id': stored,
                     'source_name': path.name, 'saved': time.time(), 'bytes': len(raw), 'sha256': digest}
            directory = unlinked(self.preserved_directory)
            directory.mkdir(parents=True, exist_ok=True)
            self._write_original(directory / (stored + '.raw'), raw)
            self._write_original(directory / (stored + '.json'), json.dumps(value, ensure_ascii=True).encode())
            if os.name != 'nt':
                for synced in (directory, directory.parent):
                    descriptor = os.open(synced, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
            checked, copied = self.read_preserved(stored)
            if checked != value or copied != raw:
                raise ValueError('原始副本尚未核对，活动原件保留')
            if self._raw(identity) != raw:
                raise ValueError('保留期间自动草稿已更新；旧原始副本已保留，新原件仍在活动列表，请重新核对')
            path.unlink()
            self.fingerprints.pop(original, None)
            return {'id': 'raw-' + stored, 'state': 'archived', 'state_revision': digest,
                    'raw_original': True, 'path': str(directory / (stored + '.raw')),
                    'bytes': len(raw), 'sha256': digest, 'applied': False}

    def archive(self, identity, expected_revision):
        with self.lock, self._storage_lock():
            value, raw = self._read(identity)
            if not identity.endswith('.pending') and value['session_id'] == self.session_id:
                raise ValueError('这是当前窗口的自动副本，请先保存或明确处理当前草稿')
            if hashlib.sha256(raw).hexdigest() != expected_revision:
                raise ValueError('自动草稿已更新，请重新读取列表；双方内容仍保留')
            # Preserve a durable, independently identified copy before consuming a checkpoint.
            record = {**value['record'], 'id': uuid.uuid4().hex, 'lifecycle': 'archived'}
            saved = self.saved_drafts.import_record(record)
            if not self.saved_drafts.same_content(self.saved_drafts.load(saved['id']), record):
                raise ValueError('归档副本尚未核对，自动草稿原件保留')
            path, _ = self._path(identity)
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected_revision:
                raise ValueError('归档期间自动草稿已更新；旧内容已另行归档，新原件保留，请重新读取')
            path.unlink()
            return {'id': saved['id'], **self.saved_drafts.lifecycle(saved['id']), 'applied': False}


class ExitCoordinator:
    def __init__(self, finalize, save_draft, clock=time.time, on_finished=None, checkpoint=None):
        self.finalize, self.save_draft, self.clock = finalize, save_draft, clock
        self.on_finished = on_finished
        self.checkpoint = checkpoint
        self.lock = threading.RLock()
        self.surfaces = {}
        self.request = None
        self.phase, self.error, self.backup_result = 'idle', '', None

    def _identity(self, surface_id):
        if not isinstance(surface_id, str) or not SURFACE.fullmatch(surface_id):
            raise ValueError('窗口身份不正确')
        return surface_id

    def register(self, surface_id, *, kind='web', label='', notify=None):
        surface_id = self._identity(surface_id)
        if kind not in ('web', 'native'):
            raise ValueError('窗口类型不正确')
        label = bounded_text(label, 120, '窗口名称')
        with self.lock:
            if self.phase in ('backing-up', 'finished'):
                raise ValueError('正在结束本次辅助，请等待；尚未提交的草稿仍在当前窗口')
            if surface_id not in self.surfaces:
                self._prune_clean()
                if len(self.surfaces) >= 32:
                    raise ValueError('打开的编辑窗口过多，请先关闭不用的面板')
                self.surfaces[surface_id] = {'surface_id': surface_id, 'kind': kind, 'label': label or '编辑窗口',
                    'revision': 0, 'dirty': False, 'draft': None, 'last_seen': self.clock(),
                    'closed': False, 'notify': notify, 'ack': None, 'recovery_saved': False, 'recovery_error': ''}
            else:
                surface = self.surfaces[surface_id]
                if surface['kind'] != kind:
                    raise ValueError('窗口身份与类型不匹配')
                surface.update(last_seen=self.clock(), closed=False)
                if notify is not None:
                    surface['notify'] = notify
                if label:
                    surface['label'] = label
            return self.status()

    def report(self, surface_id, revision, dirty, *, draft=None, label=None, kind='web'):
        if type(revision) is not int or not 0 <= revision <= 2 ** 53 or type(dirty) is not bool:
            raise ValueError('草稿版本或修改状态不正确')
        if draft is not None:
            draft = checked_draft(draft)
        with self.lock:
            self.register(surface_id, kind=kind, label=label or '')
            surface = self.surfaces[surface_id]
            if revision < surface['revision']:
                raise ValueError('草稿版本已变化，请重新确认当前窗口')
            changed = (revision, dirty) != (surface['revision'], surface['dirty'])
            if (revision == surface['revision'] and surface['draft'] is not None
                    and draft is not None and draft != surface['draft']):
                raise ValueError('草稿内容已变化，请更新草稿版本')
            surface.update(revision=revision, dirty=dirty, last_seen=self.clock(), closed=False)
            if draft is not None:
                surface['draft'] = draft
            if changed:
                surface['ack'] = None
            if self.checkpoint is not None and (self.phase != 'confirming' or surface['ack'] is None):
                try:
                    surface['recovery_saved'] = self.checkpoint(surface_id, revision, dirty,
                        surface['draft'], surface['kind'], surface['label'])
                    surface['recovery_error'] = ''
                except (ValueError, OSError) as exc:
                    surface['recovery_saved'] = False
                    surface['recovery_error'] = '自动保留草稿尚未完成：' + str(exc) + '。当前窗口输入仍保留，请明确保存副本。'
            return self.status()

    def unregister(self, surface_id, revision, dirty, *, draft=None):
        with self.lock:
            surface = self.surfaces.get(self._identity(surface_id))
            if surface is None:
                return self.status()
            self.report(surface_id, revision, dirty, draft=draft, kind=surface['kind'])
            if dirty:
                surface['closed'], surface['ack'] = True, None
            else:
                self.surfaces.pop(surface_id)
            self._finish_if_ready()
            return self.status()

    def _prune_clean(self):
        now = self.clock()
        for key, surface in list(self.surfaces.items()):
            if not surface['dirty'] and now - surface['last_seen'] > CLEAN_LEASE_SECONDS:
                self.surfaces.pop(key)

    def start(self, initiator='native', reason='结束本次辅助'):
        callbacks = []
        with self.lock:
            if self.phase in ('confirming', 'backing-up', 'finished'):
                return self.status()
            self._prune_clean()
            self.request = {'id': uuid.uuid4().hex, 'reason': bounded_text(reason, 120, '退出原因'),
                            'initiator': bounded_text(initiator, 80, '发起窗口')}
            self.phase, self.error, self.backup_result = 'confirming', '', None
            for surface in self.surfaces.values():
                surface['ack'] = None
                if surface['notify'] is not None and not surface['closed']:
                    callbacks.append(surface['notify'])
            state = self.status()
        for callback in callbacks:
            try:
                callback(copy.deepcopy(state))
            except Exception:
                # A failed UI delivery never counts as permission to discard.
                with self.lock:
                    self.error = '有窗口暂时无法响应退出确认；请取消，或明确保存/放弃其最近上报的草稿。'
        with self.lock:
            self._finish_if_ready()
            return self.status()

    def acknowledge(self, request_id, surface_id, decision, revision):
        with self.lock:
            self._check_request(request_id)
            surface = self.surfaces.get(self._identity(surface_id))
            if surface is None or type(revision) is not int or revision != surface['revision']:
                raise ValueError('窗口或草稿版本已变化，请重新确认')
            if decision == 'cancel':
                self.phase = 'cancelled'
                self.error = ''
                return self.status()
            if decision not in ('clean', 'saved', 'discard'):
                raise ValueError('请选择保存副本、取消或明确放弃')
            if decision == 'clean' and surface['dirty']:
                raise ValueError('当前窗口仍有未保存草稿，请明确选择处理方式')
            self._clear_checkpoint(surface)
            surface['ack'] = decision
            self._finish_if_ready()
            return self.status()

    def _check_request(self, request_id):
        if self.phase != 'confirming' or self.request is None or request_id != self.request['id']:
            raise ValueError('退出确认已过期，请重新发起')

    def resolve_offline(self, request_id, surface_id, decision, revision):
        with self.lock:
            self._check_request(request_id)
            surface = self.surfaces.get(self._identity(surface_id))
            if (surface is None or type(revision) is not int or revision != surface['revision']
                    or (not surface['closed'] and self.clock() - surface['last_seen'] <= ONLINE_SECONDS)):
                raise ValueError('该窗口仍在响应或草稿已更新，请在对应窗口确认')
            if decision == 'save':
                if surface['draft'] is None:
                    raise ValueError('没有可保存的已上报草稿；请取消并返回原窗口，或明确放弃')
                saved = self.save_draft(surface_id, 'offline-' + surface['kind'], surface['label'], surface['draft'])
            elif decision == 'discard':
                saved = None
            else:
                raise ValueError('请明确保存最近上报的草稿或放弃')
            self._clear_checkpoint(surface)
            surface['ack'] = 'saved' if decision == 'save' else 'discard'
            self._finish_if_ready()
            return {'exit': self.status(), 'saved': saved}

    def _clear_checkpoint(self, surface):
        if self.checkpoint is not None:
            self.checkpoint(surface['surface_id'], surface['revision'], False,
                            surface['draft'], surface['kind'], surface['label'])
            surface.update(recovery_saved=False, recovery_error='')

    def _finish_if_ready(self):
        if self.phase != 'confirming':
            return
        self._prune_clean()
        if all(surface['ack'] is not None for surface in self.surfaces.values()):
            self.phase = 'backing-up'
            # Finalization runs off the HTTP/UI thread. No further editing is accepted.
            threading.Thread(target=self._finalize, name='exit-finalize', daemon=True).start()

    def _finalize(self):
        try:
            result = self.finalize()
        except Exception:
            result = {'ok': False, 'state': 'failed', 'error': '结束时的最后一次备份未完成；已有备份与活动存档原件仍保留。'}
        with self.lock:
            self.backup_result = result
            self.phase = 'finished'
            self.error = result.get('error', '')
            state = self.status()
            callbacks = [surface['notify'] for surface in self.surfaces.values() if surface['notify'] is not None]
        for callback in callbacks:
            try:
                callback(copy.deepcopy(state))
            except Exception:
                pass
        if self.on_finished is not None:
            self.on_finished(result)

    def status(self):
        with self.lock:
            now = self.clock()
            participants = []
            for surface in self.surfaces.values():
                row = {key: surface[key] for key in ('surface_id', 'kind', 'label', 'revision', 'dirty', 'last_seen', 'ack')}
                row['online'] = not surface['closed'] and now - surface['last_seen'] <= ONLINE_SECONDS
                row['has_recovery_draft'] = surface['draft'] is not None
                row['has_reported_draft'] = surface['draft'] is not None
                row['recovery_saved'] = surface['recovery_saved']
                row['recovery_error'] = surface['recovery_error']
                if self.checkpoint is not None:
                    row['has_recovery_draft'] = surface['recovery_saved']
                participants.append(row)
            return copy.deepcopy({**(self.request or {'id': None, 'reason': '', 'initiator': ''}),
                                  'phase': self.phase, 'participants': participants,
                                  'backup_result': self.backup_result, 'error': self.error})
