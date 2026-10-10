"""Bounded associations for an explicitly resumed restore or undo directory swap."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
import uuid

from . import backups as storage
from .backup_archive import IDENTITY, valid_time

INDEX = 'restores-pending.json'
MAX_INDEX = 256 * 1024
BEFORE = re.compile(r'\.denghuo-before-([1-6])-\d+-[0-9a-f]{8}\Z')
OPERATION = re.compile(r'[0-9a-f]{32}\Z')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                     allow_nan=False).encode()).hexdigest()


def _identity(value):
    return (isinstance(value, list) and len(value) == 2
            and all(type(v) is int and 0 <= v < 2 ** 128 for v in value))


def _unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('恢复关联含有重复字段')
        result[key] = value
    return result


def _progress(value):
    if (not isinstance(value, dict) or set(value) != {'exists', 'digest', 'identity', 'summary', 'legacy_digest'}
            or type(value['exists']) is not bool or not isinstance(value['summary'], dict)):
        return False
    if not value['exists']:
        return all(value[key] is None for key in ('digest', 'identity', 'legacy_digest'))
    return (_identity(value['identity']) and isinstance(value['digest'], str)
            and bool(IDENTITY.fullmatch(value['digest']))
            and isinstance(value['legacy_digest'], str) and bool(IDENTITY.fullmatch(value['legacy_digest'])))


def records(manager, root):
    path = storage.unlinked(manager.scope(root) / INDEX)
    if not path.exists():
        return {}
    try:
        attrs = path.stat()
        if not stat.S_ISREG(attrs.st_mode) or attrs.st_size > MAX_INDEX:
            raise ValueError()
        raw = path.read_bytes()
        if len(raw) > MAX_INDEX:
            raise ValueError()
        value = json.loads(raw, object_pairs_hook=_unique_fields,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if (not isinstance(value, dict) or set(value) != {'format', 'operations'}
                or type(value['format']) is not int or value['format'] != 1
                or not isinstance(value['operations'], dict) or len(value['operations']) > 6):
            raise ValueError()
        rows = value['operations']
        digest(value)  # Reject nonfinite floats anywhere in bounded summaries too.
        ids = set()
        for key, row in rows.items():
            if (key not in ('1', '2', '3', '4', '5', '6') or not isinstance(row, dict)
                    or set(row) != {'id', 'slot', 'kind', 'time', 'root', 'root_identity', 'incoming',
                                    'preserved', 'before', 'target', 'journal_before', 'journal_after',
                                    'change', 'undo_id', 'target_backup'}
                    or type(row['slot']) is not int or str(row['slot']) != key
                    or not isinstance(row['id'], str) or not OPERATION.fullmatch(row['id'])
                    or row['id'] in ids or row['kind'] not in ('restore', 'undo')
                    or not valid_time(row['time']) or not isinstance(row['root'], str)
                    or not 1 <= len(row['root']) <= 4096 or '\x00' in row['root']
                    or not (PurePosixPath(row['root']).is_absolute() or PureWindowsPath(row['root']).is_absolute())
                    or hashlib.sha256(row['root'].casefold().encode()).hexdigest()[:24] != manager.scope(root).name
                    or not _identity(row['root_identity']) or not _progress(row['before']) or not _progress(row['target'])
                    or any(not isinstance(row[k], str) or not IDENTITY.fullmatch(row[k])
                           for k in ('journal_before', 'journal_after'))):
                raise ValueError()
            ids.add(row['id'])
            incoming = storage.STAGE_NAME if row['kind'] == 'restore' else BEFORE
            for name, pattern in ((row['incoming'], incoming), (row['preserved'], BEFORE)):
                match = pattern.fullmatch(name) if isinstance(name, str) else None
                if not match or int(match[1]) != row['slot']:
                    raise ValueError()
            if row['incoming'] == row['preserved']:
                raise ValueError()
            change = row['change']
            if row['kind'] == 'restore':
                if (not row['target']['exists'] or row['undo_id'] is not None
                        or not isinstance(row['target_backup'], str) or not IDENTITY.fullmatch(row['target_backup'])):
                    raise ValueError()
            elif not isinstance(row['undo_id'], str) or not OPERATION.fullmatch(row['undo_id']):
                raise ValueError()
            if row['target_backup'] is not None and (not isinstance(row['target_backup'], str)
                                                     or not IDENTITY.fullmatch(row['target_backup'])):
                raise ValueError()
            if change is None:
                if row['kind'] != 'undo' or row['before']['exists']:
                    raise ValueError()
            elif (not isinstance(change, dict)
                    or set(change) != ({'id', 'slot', 'time', 'original', 'existed', 'digest', 'active', 'before', 'after'}
                                       | ({'target_backup'} if row['kind'] == 'restore' else set()))
                    or change.get('id') != row['id']
                    or change.get('slot') != row['slot'] or change.get('original') != row['preserved']
                    or change.get('existed') is not row['before']['exists']
                    or change.get('digest') != row['before']['legacy_digest']
                    or change.get('active') is not (row['kind'] == 'restore')
                    or change.get('time') != row['time']
                    or change.get('before') != row['before']['summary']
                    or change.get('after') != (row['target']['summary'] if row['kind'] == 'restore' else row['before']['summary'])
                    or (row['kind'] == 'restore' and change.get('target_backup') != row['target_backup'])):
                raise ValueError()
        return rows
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, UnicodeError) as exc:
        raise ValueError('回档恢复关联无法核对，已暂停存档交换并保护全部相关原件；请保留恢复记录和副本：' + str(path)) from exc


def _write(manager, root, rows):
    raw = json.dumps({'format': 1, 'operations': rows}, ensure_ascii=True,
                     allow_nan=False, indent=2).encode()
    if len(raw) > MAX_INDEX:
        raise ValueError('回档恢复关联超过安全容量，尚未交换；全部原件保留')
    path = storage.unlinked(manager.scope(root) / INDEX)
    temporary = storage.unlinked(path.with_name(INDEX + '.pending'))
    if temporary.exists() and (not temporary.is_file() or temporary.stat().st_nlink > 1):
        raise ValueError('回档恢复临时记录无法安全写入，尚未交换')
    path.parent.mkdir(parents=True, exist_ok=True)
    with temporary.open('wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    if path.read_bytes() != raw or records(manager, root) != rows:
        raise ValueError('回档恢复关联未完整保存，尚未交换；全部原件保留')


def tree(path):
    """Hash every file and directory in one participating tree, including empty dirs."""
    path = storage.unlinked(path)
    if not path.exists():
        return {'exists': False, 'digest': None, 'identity': None}
    if not path.is_dir():
        raise ValueError('恢复关联中的目录类型已变化，全部原件保留')
    attrs = path.stat()
    identity = [attrs.st_dev, attrs.st_ino]
    def scan():
        found, total, files = {}, 0, 0
        for member in path.rglob('*'):
            attrs = storage.unlinked(member).stat()
            directory = stat.S_ISDIR(attrs.st_mode)
            if not directory and not stat.S_ISREG(attrs.st_mode) or len(found) >= 20000:
                raise ValueError('恢复目录包含不支持的项目，全部原件保留')
            if not directory:
                total += attrs.st_size
                files += 1
            if total > storage.MAX_TOTAL or files > 10000:
                raise ValueError('恢复目录超过安全大小或数量，全部原件保留')
            found[member.relative_to(path).as_posix()] = (member, directory, attrs.st_size,
                attrs.st_mtime_ns, attrs.st_ctime_ns, attrs.st_dev, attrs.st_ino)
        return found
    before = scan()
    content = []
    for name, (member, directory, size, *_) in sorted(before.items()):
        if directory:
            content.append([name, 'directory'])
        else:
            value, total = hashlib.sha256(), 0
            with member.open('rb') as stream:
                while chunk := stream.read(65536):
                    value.update(chunk)
                    total += len(chunk)
                    if total > size:
                        raise ValueError('恢复目录正在变化，请重新预览')
            if total != size:
                raise ValueError('恢复目录正在变化，请重新预览')
            content.append([name, 'file', size, value.hexdigest()])
    if before != scan() or identity != [path.stat().st_dev, path.stat().st_ino]:
        raise ValueError('恢复目录正在变化，请重新预览')
    return {'exists': True, 'digest': digest({'format': 1, 'entries': content}), 'identity': identity}


def status(manager, root):
    try:
        rows = records(manager, root)
        return {'available': True, 'error': '', 'blocked_slots': sorted(int(k) for k in rows),
                'pending': [{k: row[k] if k not in ('before', 'target') else row[k]['summary']
                             for k in ('id', 'slot', 'kind', 'time', 'before', 'target')}
                            | {'needs_preview': True} for row in rows.values()]}
    except (OSError, ValueError) as exc:
        return {'available': False, 'error': str(exc), 'blocked_slots': list(range(1, 7)), 'pending': []}


def guard(manager, root, slot):
    rows = records(manager, root)
    if str(slot) in rows:
        raise ValueError(f'槽位 {slot} 有未完成的回档或撤回；请先预览恢复关联，原件仍保留')


def protection(manager, root):
    view = status(manager, root)
    if not view['available']:
        return None, None, view['error']
    rows = records(manager, root).values()
    return ({name for row in rows for name in (row['incoming'], row['preserved'])},
            {(row['slot'], row['target_backup']) for row in rows if row['target_backup']}, '')


def _slot_hash(rows, slot):
    return digest([row for row in rows if row['slot'] == slot])


def _after(rows, row):
    result = [dict(r) for r in rows]
    if any(r['id'] == row['id'] for r in result):
        raise ValueError('恢复提交编号已存在，未重复提交')
    if row['kind'] == 'undo':
        old = [r for r in result if r['id'] == row['undo_id']]
        if (len(old) != 1 or old[0]['slot'] != row['slot'] or not old[0]['active']
                or old[0]['original'] != row['incoming'] or old[0]['existed'] != row['target']['exists']
                or old[0].get('digest') != row['target']['legacy_digest']):
            raise ValueError('原撤回关系与恢复目标不一致，全部副本保留')
    for item in result:
        if (row['kind'] == 'restore' and item['slot'] == row['slot']
                or row['kind'] == 'undo' and item['id'] == row['undo_id']):
            item['active'] = False
    if row['change'] is not None:
        result.append(row['change'])
    return result


def begin(manager, root, *, kind, slot, incoming, preserved, before, target, journals,
          before_summary, target_summary, legacy_before, target_backup=None, undo_id=None):
    rows = records(manager, root)
    guard(manager, root, slot)
    root = storage.unlinked(Path(root)).resolve()
    attrs = root.stat()
    operation, timestamp = uuid.uuid4().hex, manager.clock()
    row = {'id': operation, 'slot': slot, 'kind': kind, 'time': timestamp,
           'root': str(root), 'root_identity': [attrs.st_dev, attrs.st_ino],
           'incoming': incoming.name, 'preserved': preserved.name,
           'before': {**before, 'summary': before_summary, 'legacy_digest': legacy_before},
           'target': {**target, 'summary': target_summary,
                      'legacy_digest': manager.directory_digest(incoming) if target['exists'] else None},
           'journal_before': _slot_hash(journals, slot), 'journal_after': '',
           'change': None, 'undo_id': undo_id, 'target_backup': target_backup}
    if kind == 'restore' or before['exists']:
        row['change'] = {'id': operation, 'slot': slot, 'time': timestamp, 'original': preserved.name,
                         'existed': before['exists'], 'digest': legacy_before, 'active': kind == 'restore',
                         'before': before_summary, 'after': target_summary if kind == 'restore' else before_summary}
        if kind == 'restore':
            row['change']['target_backup'] = target_backup
    row['journal_after'] = _slot_hash(_after(journals, row), slot)
    if _slot_hash(manager.journals(root), slot) != row['journal_before']:
        raise ValueError('撤回关系在准备期间变化，尚未交换')
    rows[str(slot)] = row
    _write(manager, root, rows)
    return row


def _observe(manager, root, row):
    root = storage.unlinked(Path(root)).resolve()
    attrs = root.stat()
    if str(root) != row['root'] or [attrs.st_dev, attrs.st_ino] != row['root_identity']:
        raise ValueError('存档根目录身份已变化，无法安全恢复；全部副本保留')
    journals = manager.journals(root)
    journal = _slot_hash(journals, row['slot'])
    if journal not in (row['journal_before'], row['journal_after']):
        raise ValueError('该槽位撤回关系已变化，无法安全恢复；全部副本保留')
    if journal == row['journal_before'] and _slot_hash(_after(journals, row), row['slot']) != row['journal_after']:
        raise ValueError('恢复关联的计划提交无法核对，全部副本保留')
    paths = [root / f"game{row['slot']}", root / row['incoming'], root / row['preserved']]
    incoming, preserved = tree(paths[1]), tree(paths[2])
    empty = {'exists': False, 'digest': None, 'identity': None}
    a, b = ({k: row[name][k] for k in empty} for name in ('before', 'target'))
    if journal == row['journal_after']:
        committed = [r for r in journals if r['id'] == row['id']]
        if committed != ([] if row['change'] is None else [row['change']]):
            raise ValueError('固定恢复提交与撤回记录不一致，全部副本保留')
        if incoming != empty or preserved != a:
            raise ValueError('已提交回档的保留副本或来源路径已变化，全部副本保留')
        # Finishing a recorded commit never writes G: later game saves are allowed.
        try:
            active = tree(paths[0])
        except (OSError, ValueError):
            active = None
        return 'committed', 'after', active != b, {'incoming': incoming, 'preserved': preserved}, journals
    active = tree(paths[0])
    actual = [active, incoming, preserved]
    for layout, expected in (('ready', [a, b, empty]), ('gap', [empty, b, a]), ('target', [b, empty, a])):
        if actual == expected:
            return layout, 'before', False, dict(zip(('active', 'incoming', 'preserved'), actual)), journals
    raise ValueError('活动进度或恢复副本已发生外部变化，未覆盖任何目录；请保留全部副本')


def _selected(manager, root, payload):
    slot = payload.get('slot')
    if type(slot) is not int or slot not in range(1, 7):
        raise ValueError('恢复槽位不正确')
    row = records(manager, root).get(str(slot))
    if row is None or row['id'] != payload.get('id'):
        raise ValueError('恢复关联已变化或已结束，请重新读取')
    return row


def preview(manager, root, payload):
    row = _selected(manager, root, payload)
    layout, journal, changed, observation, _ = _observe(manager, root, row)
    labels = [('finish', '只结束已提交的恢复记录')] if journal == 'after' else [
        ('continue', '继续完成回档' if row['kind'] == 'restore' else '继续完成撤回'),
        ('cancel', '恢复操作开始前的进度')]
    message = ('提交已确认，当前进度后来变化；结束记录不会修改当前进度。' if changed else
               '操作已提交；结束记录不会再次交换或重复添加撤回关系。') if journal == 'after' else '请核对两份进度，再明确选择继续或恢复操作开始前的进度；全部副本保留。'
    return {k: row[k] for k in ('id', 'slot', 'kind')} | {
        'before': row['before']['summary'], 'target': row['target']['summary'],
        'current': manager.current_summary(root, row['slot']), 'layout': layout,
        'journal_state': journal, 'current_changed': changed,
        'copies': [{'role': role, 'file': row[role], 'exists': observation[role]['exists']}
                   for role in ('incoming', 'preserved')],
        'choices': [{'choice': key, 'label': label, 'confirm_phrase': f'{label} 槽位 {row["slot"]}'}
                    for key, label in labels],
        'expected': digest({'row': row, 'layout': layout, 'journal': journal, 'observation': observation}),
        'originals_retained': True, 'message': message}


def _move(source, target):
    storage.unlinked(source)
    storage.unlinked(target)
    if target.exists():
        raise ValueError('恢复目的路径已出现新内容，未覆盖；全部副本保留')
    source.replace(target)


def _finish(manager, root, row):
    rows = records(manager, root)
    if rows.get(str(row['slot'])) != row:
        raise ValueError('恢复关联已变化，未结束记录')
    del rows[str(row['slot'])]
    _write(manager, root, rows)


def _drive(manager, root, row, choice):
    root = Path(root)
    g, i, p = root / f"game{row['slot']}", root / row['incoming'], root / row['preserved']
    layout, journal, _, _, journals = _observe(manager, root, row)
    if journal == 'after':
        if choice != 'finish':
            raise ValueError('操作已提交，只能核对并结束记录')
        _finish(manager, root, row)
        return
    if choice == 'continue':
        if layout == 'ready' and row['before']['exists']:
            _move(g, p)
        _observe(manager, root, row)
        if row['target']['exists'] and i.exists():
            _move(i, g)
        _, _, _, _, journals = _observe(manager, root, row)
        updated = _after(journals, row)
        if _slot_hash(updated, row['slot']) != row['journal_after']:
            raise ValueError('恢复提交内容已变化，全部副本保留')
        path = storage.unlinked(manager.scope(root) / 'restores.json')
        storage.atomic_json(path, updated)
        with path.open('r+b') as stream:
            os.fsync(stream.fileno())
        if _slot_hash(manager.journals(root), row['slot']) != row['journal_after']:
            raise ValueError('恢复提交未完整保存，全部副本保留')
    elif choice == 'cancel':
        if layout == 'target' and row['target']['exists']:
            _move(g, i)
        _observe(manager, root, row)
        if row['before']['exists'] and p.exists():
            _move(p, g)
        layout, journal, _, _, _ = _observe(manager, root, row)
        if layout != 'ready' or journal != 'before':
            raise ValueError('恢复原进度尚未完整结束，全部副本保留')
    else:
        raise ValueError('恢复选择不正确')
    _observe(manager, root, row)
    _finish(manager, root, row)


def run(manager, root, row):
    """Ordinary exceptions can compensate; abrupt exits leave the same association."""
    try:
        manager.closed_check()
        _drive(manager, root, row, 'continue')
    except Exception:
        try:
            if _observe(manager, root, row)[1] == 'before':
                _drive(manager, root, row, 'cancel')
        except Exception:
            pass  # The exact pending record and every extant byte remain protected.
        raise


def execute(manager, root, payload):
    row = _selected(manager, root, payload)
    view = preview(manager, root, payload)
    choice = next((c for c in view['choices'] if c['choice'] == payload.get('choice')), None)
    if (choice is None or payload.get('confirmed') is not True or payload.get('expected') != view['expected']
            or payload.get('confirm') != choice['confirm_phrase']):
        raise ValueError('恢复关联或副本已变化，请重新预览并明确确认选择；尚未交换')
    if choice['choice'] != 'finish':
        manager.closed_check()
    if preview(manager, root, payload)['expected'] != view['expected']:
        raise ValueError('恢复副本在确认期间变化，尚未交换')
    _drive(manager, root, row, choice['choice'])
    manager.last_tick = 0
    manager.slot_health.pop(row['slot'], None)
    manager._storage_cache = None
    message = ('已结束提交记录，当前进度未修改。' if choice['choice'] == 'finish' else
               '已恢复操作开始前的进度，准备目标与原有撤回关系保留。' if choice['choice'] == 'cancel' else
               '恢复操作已完成，所有原进度副本保留。')
    manager._set_notice(root, message)
    return {'ok': True, 'id': row['id'], 'slot': row['slot'], 'kind': row['kind'],
            'choice': choice['choice'], 'journal_committed': choice['choice'] != 'cancel',
            'originals_retained': True, 'message': message}
