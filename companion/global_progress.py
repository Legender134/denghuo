"""Explicit, byte-preserving transfer of the two supported global game files.

Structure reference: SPD 4.0.2, commit 57a4e06a4caf162446d1c28caa7983f0493fecf0,
Badges.java, Rankings.java and SPD-classes Bundle.java/FileUtils.java. No game
objects are instantiated, statistics edited, or version inferred from a slot.
"""
from __future__ import annotations

from contextlib import contextmanager
import gzip
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import stat
import uuid
import zlib

from .backups import unlinked
from .saves import MAX_BYTES, bundle_integer, bundle_float, invalid_constant, file_stamp

FILES = ('badges.dat', 'rankings.dat')
MEMBERS = {'global/' + name for name in FILES} | {'global-progress.json'}
REFERENCE = '57a4e06a4caf162446d1c28caa7983f0493fecf0'
VERSION = '4.0.2'
INDEX = 'global-progress-pending.json'
RECORD_CLASS = 'com.shatteredpixel.shatteredpixeldungeon.Rankings$Record'


@contextmanager
def _transaction_lock(manager, root):
    """Serialize this two-file transaction across local assistant processes.

    The OS releases the lock on process death, so an interrupted import can be
    recovered without deleting a guessed stale lock or touching game files.
    """
    scope = unlinked(manager.scope(root))
    scope.mkdir(parents=True, exist_ok=True)
    path = unlinked(scope / 'global-progress.lock')
    try:
        stream = path.open('x+b')
    except FileExistsError:
        attrs = path.stat()
        if not stat.S_ISREG(attrs.st_mode) or attrs.st_nlink != 1 or attrs.st_size > 1:
            raise ValueError('全局进度协调文件不安全，尚未写入')
        stream = path.open('r+b')
    with stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode) or os.fstat(stream.fileno()).st_nlink != 1:
            raise ValueError('全局进度协调文件不安全，尚未写入')
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError('另一个助手正在处理全局进度，请稍后重新预览') from exc
        try:
            if not path.stat().st_size:
                stream.write(b'\0'); stream.flush(); os.fsync(stream.fileno())
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def digest(raw):
    return hashlib.sha256(raw).hexdigest() if raw is not None else None


def encode(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, allow_nan=False).encode()


def unique_fields(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('全局进度含重复字段')
        value[key] = item
    return value


def decode(raw):
    if not isinstance(raw, bytes) or not 1 < len(raw) <= MAX_BYTES:
        raise ValueError('全局进度文件大小不正确（每文件最多16 MiB）')
    if raw.startswith(b'\x1f\x8b'):
        with gzip.GzipFile(fileobj=BytesIO(raw)) as stream:
            raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('全局进度解压后超过16 MiB')
    value = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique_fields,
                       parse_int=bundle_integer, parse_float=bundle_float,
                       parse_constant=invalid_constant)
    # Bound nested ranking gameData without interpreting private game objects.
    pending, count = [(value, 0)], 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if count > 200000 or depth > 64:
            raise ValueError('全局进度结构超过安全范围')
        if isinstance(item, dict):
            if any(not isinstance(key, str) or len(key) > 200 for key in item):
                raise ValueError('全局进度字段不正确')
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
        elif isinstance(item, str) and len(item) > 65536:
            raise ValueError('全局进度文字超过安全范围')
    return value


def integer(value, minimum=0, maximum=2147483647):
    return type(value) is int and minimum <= value <= maximum


def _record(row):
    required = {'__className', 'win', 'score', 'class', 'tier', 'level', 'depth',
                'ascending', 'custom_seed', 'daily'}
    optional = {'cause', 'gameData', 'gameID', 'date', 'version'}
    if (not isinstance(row, dict) or not required <= set(row) or set(row) - required - optional
            or row['__className'] != RECORD_CLASS
            or row['class'] not in ('WARRIOR', 'MAGE', 'ROGUE', 'HUNTRESS', 'DUELIST', 'CLERIC')
            or any(type(row[key]) is not bool for key in ('win', 'ascending', 'daily'))
            or any(not integer(row[key], -2147483648) for key in ('score', 'tier', 'level', 'depth'))
            or not isinstance(row['custom_seed'], str) or len(row['custom_seed']) > 200
            or any(key in row and (not isinstance(row[key], str) or len(row[key]) > 300)
                   for key in ('cause', 'gameID', 'date', 'version'))
            or 'gameData' in row and not isinstance(row['gameData'], dict)):
        raise ValueError('排行榜记录结构不兼容；未改写原件')


def validate(name, raw):
    if name not in FILES:
        raise ValueError('仅支持 badges.dat 与 rankings.dat')
    try:
        value = decode(raw)
        if not isinstance(value, dict):
            raise ValueError('全局进度必须是 Bundle 对象')
        if name == 'badges.dat':
            names = value.get('badges')
            if (set(value) != {'badges'} or not isinstance(names, list) or len(names) > 1024
                    or any(not isinstance(item, str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{0,119}', item) for item in names)
                    or len(set(names)) != len(names)):
                raise ValueError('成就文件结构不兼容')
            return {'badges': len(names), 'encoding': 'gzip' if raw.startswith(b'\x1f\x8b') else 'json'}
        required = {'records', 'latest', 'total', 'won'}
        optional = {'latest_daily', 'daily_history_dates', 'daily_history_scores'}
        records = value.get('records')
        if (not required <= set(value) or set(value) - required - optional
                or not isinstance(records, list) or len(records) > 11
                or not integer(value['latest'], -1, max(0, len(records) - 1))
                or not integer(value['total']) or not integer(value['won'])
                or value['won'] > max(value['total'], len(records))):
            raise ValueError('排行榜全局统计结构不兼容')
        for row in records:
            _record(row)
        if 'latest_daily' in value:
            _record(value['latest_daily'])
        dates, scores = value.get('daily_history_dates', []), value.get('daily_history_scores', [])
        if (('daily_history_dates' in value) != ('daily_history_scores' in value)
                or not isinstance(dates, list) or not isinstance(scores, list)
                or len(dates) != len(scores) or len(dates) > 20000
                or any(not integer(item, 0, 2**63-1) for item in dates)
                or len(set(dates)) != len(dates)
                or any(not integer(item, -2147483648) for item in scores)):
            raise ValueError('排行榜每日历史结构不兼容')
        return {'records': len(records), 'total': value['total'], 'won': value['won'],
                'daily_history': len(dates), 'encoding': 'gzip' if raw.startswith(b'\x1f\x8b') else 'json'}
    except (OSError, ValueError, EOFError, RecursionError, OverflowError, zlib.error) as exc:
        raise ValueError('全局进度损坏或结构不支持：' + str(exc)) from exc


def read(path):
    path = unlinked(path)
    try:
        before = path.stat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > MAX_BYTES:
        raise ValueError('全局进度不是安全的普通文件或超过16 MiB')
    with path.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES or file_stamp(before) != file_stamp(path.stat()):
        raise ValueError('全局进度在读取期间变化，请重新预览')
    return raw


def root_identity(root):
    path = unlinked(root)
    attrs = path.stat()
    if not stat.S_ISDIR(attrs.st_mode):
        raise ValueError('连接的游戏存档目录不可用')
    return [attrs.st_dev, attrs.st_ino]


def target(manager, root, names):
    return {'identity': root_identity(root), 'files': {name: digest(read(Path(root) / name)) for name in sorted(names)},
            'journal': digest(read(unlinked(manager.scope(root) / INDEX)))}


def source_rows(root):
    rows = []
    for name in FILES:
        try:
            raw = read(Path(root) / name)
            if raw is None:
                continue
            summary, error = validate(name, raw), ''
        except (OSError, ValueError) as exc:
            summary, error = None, str(exc)
        rows.append({'key': 'global:' + name, 'group': 'global', 'label': name,
                     'valid': not bool(error), 'error': error, 'summary': summary,
                     'detail': '独立全局游戏进度 · 默认不选 · 原始字节保留 · 文件本身不能证明来源游戏版本'})
    return rows


def export(root, selected, payload):
    declared = payload.get('global_version', 'unknown')
    if declared not in ('unknown', VERSION):
        raise ValueError('不支持声明的全局进度游戏版本')
    if declared != 'unknown' and payload.get('global_version_confirmed') is not True:
        raise ValueError('请明确核对全局进度来源游戏版本；不能从助手资料版本推断')
    contents, entries = {}, {}
    for name in sorted(selected):
        raw = read(Path(root) / name)
        if raw is None:
            raise ValueError('所选全局进度原件已变化，请重新预览')
        summary = validate(name, raw)
        contents['global/' + name] = raw
        entries[name] = {'bytes': len(raw), 'sha256': digest(raw), 'summary': summary}
    contents['global-progress.json'] = encode({'format': 1, 'kind': 'denghuo-global-progress',
        'version': declared, 'version_basis': 'unknown' if declared == 'unknown' else 'user-declared',
        'reference': REFERENCE, 'files': entries})
    return contents


def inspect(contents):
    present = set(contents) & MEMBERS
    if not present:
        return None
    if 'global-progress.json' not in present or len(contents['global-progress.json']) > 16384:
        raise ValueError('全局进度清单缺失或过大')
    value = json.loads(contents['global-progress.json'], object_pairs_hook=unique_fields)
    if (not isinstance(value, dict) or set(value) != {'format', 'kind', 'version', 'version_basis', 'reference', 'files'}
            or type(value['format']) is not int or value['format'] != 1
            or value['kind'] != 'denghuo-global-progress' or value['reference'] != REFERENCE
            or not isinstance(value['version'], str) or not re.fullmatch(r'[\w.+-]{1,80}', value['version'])
            or value['version_basis'] not in ('unknown', 'user-declared')
            or (value['version'] == 'unknown') != (value['version_basis'] == 'unknown')
            or not isinstance(value['files'], dict) or not value['files'] or set(value['files']) - set(FILES)
            or {'global/' + name for name in value['files']} != present - {'global-progress.json'}):
        raise ValueError('不支持的全局进度清单')
    for name, item in value['files'].items():
        raw = contents['global/' + name]
        if (not isinstance(item, dict) or set(item) != {'bytes', 'sha256', 'summary'}
                or type(item['bytes']) is not int or item['bytes'] != len(raw)
                or item['sha256'] != digest(raw) or item['summary'] != validate(name, raw)):
            raise ValueError('全局进度清单与原件不一致')
    return value


def _write_new(path, raw):
    with unlinked(path).open('xb') as stream:
        if stream.write(raw) != len(raw):
            raise OSError('全局进度副本写入不完整')
        stream.flush()
        os.fsync(stream.fileno())
    if read(path) != raw:
        raise ValueError('全局进度保留副本校验失败')


def _journal(manager, root, value):
    scope = unlinked(manager.scope(root))
    scope.mkdir(parents=True, exist_ok=True)
    raw = encode(value)
    # Each transaction has an independent retained journal, including completed ones.
    archive = unlinked(scope / value['id'] / 'journal.json')
    temporary = archive.with_name('journal.' + uuid.uuid4().hex + '.json')
    _write_new(temporary, raw)
    temporary.replace(archive)
    temporary = scope / (INDEX + '.' + uuid.uuid4().hex)
    _write_new(temporary, raw)
    unlinked(temporary).replace(unlinked(scope / INDEX))


def _temporary_directory(root, row):
    path = unlinked(Path(root) / ('.denghuo-' + row['id']))
    if row['temporary_identity'] is None or root_identity(path) != row['temporary_identity']:
        raise ValueError('本事务游戏目录暂存身份不能核对，未覆盖任何暂存原件：' + str(path))
    return path


def _temporary_names(names):
    return [prefix + name for name in sorted(names)
            for prefix in ('publish-', 'withdrawn-', *(f'rollback-{attempt}-' for attempt in range(8)))]


def _temporary_summary(root, row):
    if row['temporary_identity'] is None:
        return []  # A crash before registration cannot have published a game file.
    folder = _temporary_directory(root, row)
    rows = []
    # Read only these exact transaction filenames, never glob unknown user data.
    for name in _temporary_names(row['before']):
        raw = read(folder / name)
        if raw is not None:
            rows.append({'file': name, 'bytes': len(raw), 'sha256': digest(raw)})
    return rows


def pending(manager, root):
    scope = unlinked(manager.scope(root))
    raw = read(scope / INDEX)
    if raw is None:
        return None
    if len(raw) > 16384:
        raise ValueError('全局进度恢复记录过大；原件和恢复记录继续保留')
    row = json.loads(raw, object_pairs_hook=unique_fields)
    if (not isinstance(row, dict) or set(row) != {'format', 'id', 'state', 'root', 'identity', 'temporary_identity', 'before', 'after'}
            or type(row['format']) is not int or row['format'] != 1
            or not isinstance(row['id'], str) or not re.fullmatch(r'global-progress-[a-f0-9]{32}', row['id'])
            or row['state'] not in ('pending', 'complete', 'rolled-back')
            or row['root'] != str(Path(root).resolve()) or row['identity'] != root_identity(root)
            or row['temporary_identity'] is not None and (
                not isinstance(row['temporary_identity'], list) or len(row['temporary_identity']) != 2
                or any(type(item) is not int or not 0 <= item < 2**128 for item in row['temporary_identity']))
            or not isinstance(row['before'], dict) or not isinstance(row['after'], dict)
            or not row['before'] or set(row['before']) - set(FILES) or set(row['before']) != set(row['after'])
            or any(value is not None and (not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value))
                   for value in row['before'].values())
            or any(not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value) for value in row['after'].values())):
        raise ValueError('全局进度恢复关联不能核对；请保留原件及 ' + str(scope / INDEX))
    return row if row['state'] == 'pending' else None


def recovery_preview(manager, root):
    row = pending(manager, root)
    if row is None:
        return {'pending': False}
    folder = unlinked(manager.scope(root) / row['id'])
    current = {}
    for name, before in row['before'].items():
        if before is not None and digest(read(folder / ('before-' + name))) != before:
            raise ValueError('全局进度原件副本校验失败，未自动覆盖任何文件：' + str(folder))
        if digest(read(folder / ('incoming-' + name))) != row['after'][name]:
            raise ValueError('全局进度输入副本校验失败，全部副本继续保留：' + str(folder))
        current[name] = digest(read(Path(root) / name))
        if current[name] not in (before, row['after'][name]):
            raise ValueError('中断后游戏全局进度已被其他程序更改；未覆盖新字节，保留副本：' + str(folder))
    temporaries = _temporary_summary(root, row)
    return {'pending': True, 'directory': str(folder), 'files': sorted(row['before']),
            'temporary_directory': str(Path(root) / ('.denghuo-' + row['id'])), 'temporaries': temporaries,
            'effect': '恢复导入前全局进度；原先不存在的文件移入保留目录。全部原件与输入副本继续保留。',
            'expected': digest(encode({'journal': row, 'current': current, 'temporaries': temporaries}))}


def _rollback(manager, root, row, check):
    folder = unlinked(manager.scope(root) / row['id'])
    for name, before in row['before'].items():
        check()
        manager.closed_check()
        if root_identity(root) != row['identity']:
            raise ValueError('游戏目录身份变化，未自动恢复；原件仍保留：' + str(folder))
        path = unlinked(Path(root) / name)
        current = digest(read(path))
        if current == before:
            continue
        if current != row['after'][name]:
            raise ValueError('目标已被其他程序改写，未覆盖新字节；全局进度原件保留于 ' + str(folder))
        temporary_folder = _temporary_directory(root, row)
        if before is None:
            # Preserve even a newly introduced file instead of deleting it.
            withdrawn = unlinked(temporary_folder / ('withdrawn-' + name))
            if withdrawn.exists():
                raise ValueError('撤回暂存原件已存在，未覆盖：' + str(withdrawn))
            path.replace(withdrawn)
        else:
            raw = read(folder / ('before-' + name))
            if digest(raw) != before:
                raise ValueError('原件副本校验失败，未继续恢复：' + str(folder))
            temporary = None
            for attempt in range(8):
                candidate = temporary_folder / (f'rollback-{attempt}-' + name)
                existing = read(candidate)
                if existing is None:
                    _write_new(candidate, raw)
                    temporary = candidate
                    break
                if existing == raw:
                    temporary = candidate
                    break
            if temporary is None:
                raise ValueError('本事务恢复暂存已满；原件和中断临时文件继续保留：' + str(temporary_folder))
            if digest(read(path)) != current:
                raise ValueError('恢复期间目标变化，原件仍保留：' + str(folder))
            temporary.replace(path)
    row['state'] = 'rolled-back'
    _journal(manager, root, row)


def recover(manager, root, payload, check):
    with _transaction_lock(manager, root):
        return _recover(manager, root, payload, check)


def _recover(manager, root, payload, check):
    preview = recovery_preview(manager, root)
    if (not preview['pending'] or payload.get('confirmed') is not True
            or payload.get('expected') != preview['expected']):
        raise ValueError('请重新预览并明确确认全局进度中断恢复')
    row = pending(manager, root)
    _rollback(manager, root, row, check)
    return {'pending': False, 'directory': preview['directory'],
            'temporary_directory': preview['temporary_directory'],
            'message': '已恢复导入前原件；备份副本与游戏根目录本事务暂存仍保留'}


def apply(manager, root, contents, names, expected, check):
    with _transaction_lock(manager, root):
        return _apply(manager, root, contents, names, expected, check)


def _apply(manager, root, contents, names, expected, check):
    if pending(manager, root) is not None:
        raise ValueError('有未完成的全局进度导入，请先预览恢复原件')
    check()
    manager.closed_check()
    if target(manager, root, names) != expected:
        raise ValueError('全局进度目标已变化，请重新预览；尚未写入')
    row = {'format': 1, 'id': 'global-progress-' + uuid.uuid4().hex, 'state': 'pending',
           'root': str(Path(root).resolve()), 'identity': root_identity(root), 'temporary_identity': None,
           'before': {}, 'after': {}}
    folder = unlinked(manager.scope(root) / row['id'])
    folder.mkdir(parents=True)
    for name in names:
        raw = read(Path(root) / name)
        incoming = contents['global/' + name]
        validate(name, incoming)
        row['before'][name], row['after'][name] = digest(raw), digest(incoming)
        if raw is not None:
            _write_new(folder / ('before-' + name), raw)
        _write_new(folder / ('incoming-' + name), incoming)
    if target(manager, root, names) != expected:
        raise ValueError('准备副本期间全局进度已变化；尚未写入，副本保留于 ' + str(folder))
    _journal(manager, root, row)  # Durable originals and journal precede every game write.
    installed = set()
    temporary_folder = Path(root) / ('.denghuo-' + row['id'])
    try:
        temporary_folder = unlinked(temporary_folder)
        temporary_folder.mkdir()  # Exclusive: never reuse a user-owned collision.
        row['temporary_identity'] = root_identity(temporary_folder)
        _journal(manager, root, row)
        for name in names:
            check()
            manager.closed_check()
            if root_identity(root) != row['identity'] or any(
                    digest(read(Path(root) / other)) != row['before'][other] for other in names
                    if other not in installed):
                raise ValueError('全局进度目标在提交期间变化')
            temporary_folder = _temporary_directory(root, row)
            temporary = temporary_folder / ('publish-' + name)
            _write_new(temporary, contents['global/' + name])
            if digest(read(Path(root) / name)) != row['before'][name]:
                raise ValueError('全局进度目标在提交期间变化')
            temporary.replace(unlinked(Path(root) / name))
            installed.add(name)
        check()
        if root_identity(root) != row['identity'] or any(digest(read(Path(root) / name)) != row['after'][name] for name in names):
            raise ValueError('全局进度写入后校验失败')
        row['state'] = 'complete'
        _journal(manager, root, row)
    except Exception as exc:
        try:
            row['state'] = 'pending'
            _rollback(manager, root, row, check)
        except (OSError, ValueError) as rollback:
            raise ValueError('全局进度导入未完成，原件保留；需显式恢复：' + str(folder)
                             + '；本事务游戏根暂存位置：' + str(temporary_folder) + '；' + str(rollback)) from exc
        raise ValueError('全局进度导入失败，已恢复原件；副本保留于 ' + str(folder)
                         + '；本事务游戏根暂存位置：' + str(temporary_folder)) from exc
    return {'retained_directory': str(folder), 'temporary_directory': str(temporary_folder)}
