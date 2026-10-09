"""One explicit exit decision shared by every live editing surface."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import re
import threading
import time
import uuid

from .backups import atomic_json, unlinked

SURFACE = re.compile(r'(?:native(?:[-_][a-z0-9]{1,48})?|web-[a-f0-9]{8,64})\Z')
DRAFT_ID = re.compile(r'[a-f0-9]{32}\Z')
MAX_DRAFT = 65536
MAX_SAVED_DRAFTS = 200
MAX_DRAFT_SET = 16 * 1024 * 1024
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
        raise ValueError('草稿超过64 KiB，请先分别保存方案')
    # Own forms have no authentication fields. Never store an entire status response.
    pending = [(value, 0)]
    nodes = 0
    while pending:
        current, depth = pending.pop()
        nodes += 1
        if depth > 20 or nodes > 12000:
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
    if (not isinstance(value, dict) or set(value) != fields or type(value['format']) is not int
            or value['format'] != 1 or value['kind'] != 'denghuo-unfinished-draft'
            or not isinstance(value['id'], str) or not DRAFT_ID.fullmatch(value['id'])
            or identity is not None and value['id'] != identity
            or not isinstance(value['surface_id'], str) or not SURFACE.fullmatch(value['surface_id'])
            or type(value['saved']) not in (int, float) or not math.isfinite(value['saved'])
            or not 0 <= value['saved'] <= 32503680000):
        raise ValueError('草稿格式或版本不兼容，原件仍保留；尚未载入或应用')
    result = copy.deepcopy(value)
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
        value = {'format': 1, 'kind': 'denghuo-unfinished-draft', 'id': identity,
                 'surface_id': surface_id, 'draft_kind': kind, 'label': label,
                 'saved': time.time(), 'draft': draft}
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
                    raw = stream.read(512 * 1024 + 1)
                if len(raw) > 512 * 1024:
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
                if len(rows) >= MAX_SAVED_DRAFTS or path.stat().st_size > 512 * 1024:
                    raise ValueError('已有草稿数量或文件大小超过迁移限制，原件仍保留')
                rows[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
            return rows

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
            records = [checked_saved_draft(portable(self.load(identity))) for identity in identities]
            checked_draft_set({'format': 1, 'kind': 'denghuo-exit-draft-set', 'records': records})
            return records

    def preview_import(self, record):
        record = checked_saved_draft(record)
        with self.lock:
            path = unlinked(self.directory / (record['id'] + '.json'))
            if not path.exists():
                return record, '新增已保存原始草稿；需明确载入，不计算或应用'
            try:
                if self.load(record['id']) == record:
                    return None, '相同草稿已存在，保留本机原件'
            except ValueError:
                pass  # A damaged local original is also preserved, never replaced.
            encoded = json.dumps(record, ensure_ascii=True, sort_keys=True).encode()
            copied = {**record, 'id': hashlib.sha256(encoded).hexdigest()[:32]}
            copied_path = unlinked(self.directory / (copied['id'] + '.json'))
            if copied_path.exists():
                try:
                    if self.load(copied['id']) == copied:
                        return None, '同ID冲突副本已存在，双方均保留'
                except ValueError:
                    pass
                raise ValueError('草稿冲突副本身份已占用，原件仍保留；请先核对本机草稿')
            return copied, '同ID内容不同，保留双方并新增原始草稿副本'

    def import_record(self, record):
        with self.lock:
            record = checked_saved_draft(record)
            addition, message = self.preview_import(record)
            stored_id = addition['id'] if addition else record['id']
            if addition is None:
                try:
                    exact_original = self.load(record['id']) == record
                except ValueError:
                    exact_original = False
                if not exact_original:
                    encoded = json.dumps(record, ensure_ascii=True, sort_keys=True).encode()
                    stored_id = hashlib.sha256(encoded).hexdigest()[:32]
            if addition is not None:
                if len(self.stamp()) >= MAX_SAVED_DRAFTS:
                    raise ValueError('本机已有200份草稿，请减少迁移选择；原件仍保留')
                unlinked(self.directory).mkdir(parents=True, exist_ok=True)
                # Exclusive creation closes the cross-process check/write race.
                path = unlinked(self.directory / (addition['id'] + '.json'))
                with path.open('xb') as stream:
                    stream.write(json.dumps(addition, ensure_ascii=True, indent=2).encode())
            return {'id': stored_id, 'message': message,
                    'loaded': False, 'calculated': False, 'applied': False}

    def list(self):
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
                    rows.append({key: value[key] for key in ('id', 'draft_kind', 'label', 'saved', 'surface_id')})
                except ValueError as exc:
                    rows.append({'id': path.stem, 'error': str(exc), 'saved': 0})
            return sorted(rows, key=lambda row: row['saved'], reverse=True)


class ExitCoordinator:
    def __init__(self, finalize, save_draft, clock=time.time, on_finished=None):
        self.finalize, self.save_draft, self.clock = finalize, save_draft, clock
        self.on_finished = on_finished
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
                    'closed': False, 'notify': notify, 'ack': None}
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
                surface['ack'] = 'saved'
            elif decision == 'discard':
                saved = None
                surface['ack'] = 'discard'
            else:
                raise ValueError('请明确保存最近上报的草稿或放弃')
            self._finish_if_ready()
            return {'exit': self.status(), 'saved': saved}

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
                participants.append(row)
            return copy.deepcopy({**(self.request or {'id': None, 'reason': '', 'initiator': ''}),
                                  'phase': self.phase, 'participants': participants,
                                  'backup_result': self.backup_result, 'error': self.error})
