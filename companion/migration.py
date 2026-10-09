"""Selective portable bundles; preview and CAS before writing assistant data.

Project-specific implementation. Ludusavi's preview/select/restore separation is
a design reference; no third-party source code is copied.
"""
from __future__ import annotations

import copy
import hashlib
from io import BytesIO
import json
import re
import stat
from zipfile import BadZipFile, ZipFile, ZipInfo, ZIP_STORED

from . import __version__
from . import backup_workflows as flows
from .backups import MAX_TOTAL, unlinked
from .knowledge import MAX_BYTES, MAX_FAVORITES, MAX_PLANS, canonical_plan
from .play_state import validate_preferences
from .session_exit import MAX_DRAFT_SET, checked_draft_set

PREFERENCE_LABELS = {'enabled': '游玩显示开关', 'alerts': '快照风险提示',
                     'font_scale': '字号比例', 'opacity': '背景透明度',
                     'notice_seconds': '提示停留秒数', 'bindings': '全局快捷键'}
MEMBERS = {'backups.zip', 'knowledge.json', 'preferences.json', 'exit-drafts.json'}
INDEX = 'denghuo-migration.json'


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode('utf-8')


def checksum(raw):
    return hashlib.sha256(raw).hexdigest()


def read_json(raw):
    return json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('无效数值')))


def portable_text(value):
    # Names, notes and provenance labels can contain pasted machine paths.
    value = re.sub(r'(?i)(?:[a-z]:[\\/]|\\\\)[^\s\u3000<>"|]+', '[本机路径已省略]', value)
    value = re.sub(r'(?<![\w:])/(?:Users|home|mnt|tmp|var|private|media|Volumes)/[^\s\u3000<>"|]+', '[本机路径已省略]', value)
    value = re.sub(r'(?i)\b(authorization)\s*[:=]\s*(?:bearer\s+)?[^\s,;]+', r'\1=[已省略]', value)
    return re.sub(r'(?i)\b(token|password|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|cookie|credentials)\s*[:=]\s*[^\s,;]+', r'\1=[已省略]', value)


def portable_record(row):
    row = copy.deepcopy(row)
    row['name'] = portable_text(row['name'])[:80]
    if 'note' in row:
        row['note'] = portable_text(row['note'])[:1200]
    if 'fields' in row['origin']:
        row['origin']['fields'] = {key: portable_text(value)[:120] for key, value in row['origin']['fields'].items()}
    return row


def _zip(contents):
    output = BytesIO()
    with ZipFile(output, 'w', ZIP_STORED) as archive:
        for name, raw in sorted(contents.items()):
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_STORED
            archive.writestr(info, raw)
    raw = output.getvalue()
    if len(raw) > MAX_TOTAL or sum(len(value) for value in contents.values()) > MAX_TOTAL:
        raise ValueError('统一迁移包超过64 MiB，请减少选择后分批导出')
    return raw


def _portable_backups(raw):
    with ZipFile(BytesIO(raw)) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    index = read_json(contents['denghuo-transfer.json'])
    for row in index['entries']:
        label = portable_text(row['label'])[:80]
        if label != row['label']:
            with ZipFile(BytesIO(contents[row['file']])) as archive:
                inner = {name: archive.read(name) for name in archive.namelist()}
            metadata = read_json(inner['manifest.json'])
            metadata['transfer']['label'] = label
            inner['manifest.json'] = encode(metadata)
            contents[row['file']] = _zip(inner)
            row.update(label=label, bytes=len(contents[row['file']]), sha256=checksum(contents[row['file']]))
    contents['denghuo-transfer.json'] = encode(index)
    return _zip(contents)


def _selection(selected, available, *, empty=False):
    if (not isinstance(selected, list) or len(selected) > 600
            or any(not isinstance(item, str) or len(item) > 400 for item in selected)
            or len(set(selected)) != len(selected) or set(selected) - set(available)
            or not empty and not selected):
        raise ValueError('请选择这份清单内的具体项目；没有选择时不会应用')
    return selected


def _backup_guard(session):
    scope = unlinked(session.backups.scope(session.settings['save_root']))
    rows = {}
    if scope.exists():
        for path in sorted(scope.iterdir()):
            if path.name.endswith('.json') or path.suffix == '.zip':
                path = unlinked(path)
                attrs = path.stat()
                if not stat.S_ISREG(attrs.st_mode):
                    raise ValueError('助手档案含非普通文件，请先检查本机档案')
                if attrs.st_size > MAX_TOTAL:
                    raise ValueError('本机档案文件超过64 MiB原有上限，请先检查异常原件')
                # Content hashes include out-of-process rewrites with unchanged timestamps.
                with path.open('rb') as stream:
                    digest = hashlib.sha256()
                    while chunk := stream.read(65536):
                        digest.update(chunk)
                rows[path.name] = [attrs.st_size, attrs.st_mtime_ns, digest.hexdigest()]
    return rows


def _preference_disk_stamp(prefs):
    try:
        with unlinked(prefs.path).open('rb') as stream:
            raw = stream.read(16385)
        return checksum(raw)
    except FileNotFoundError:
        return None


def _target(session):
    _, knowledge_stamp = session.knowledge._read()
    prefs = session.play_preferences
    prefs_stamp = _preference_disk_stamp(prefs)
    return {'root': session.settings['save_root'], 'context': session.backup_context,
            'config_error': session.config_error, 'knowledge': knowledge_stamp,
            'preferences_disk': prefs_stamp, 'preferences_loaded': prefs._disk_stamp,
            'preferences_revision': prefs.generation, 'preferences_values': prefs.values,
            'backups': _backup_guard(session), 'exit_drafts': session.exit_drafts.stamp()}


def _locks(session):
    # Caller holds session.lock first, matching existing UI preference workflows.
    from contextlib import ExitStack
    stack = ExitStack()
    stack.enter_context(session.knowledge.lock)
    stack.enter_context(session.play_preferences.lock)
    stack.enter_context(session.backups.lock)
    stack.enter_context(session.exit_drafts.lock)
    return stack


def status(session):
    with session.lock, _locks(session):
        stored = session.knowledge.status()
        backup = session.backups.snapshot(session.settings['save_root'])
        rows = []
        for row in backup.get('history', []):
            if row.get('valid') is False:
                continue
            rows.append({'key': f"backup:{row['slot']}:{row['id']}", 'group': 'backup',
                         'label': row.get('label') or f"槽位 {row['slot']} · 第 {row['depth']} 层",
                         'detail': f"{row['class']} · 等级 {row['level']} · 已校验后导出",
                         'slot': row['slot'], 'id': row['id'], 'valid': True})
        for row in stored['plans']:
            rows.append({'key': 'plan:' + row['id'], 'group': 'plan', 'label': row['name'],
                         'detail': f"{row['kind']} · 资料版本 {row['rules_version']}", 'valid': True,
                         'content': portable_record({key: value for key, value in row.items() if key != 'record_revision'})})
        entries = {row['id']: row for row in session.catalog.entries}
        for identity in stored['favorites']:
            rows.append({'key': 'favorite:' + identity, 'group': 'favorite',
                         'label': entries.get(identity, {}).get('name', identity), 'detail': identity, 'valid': True})
        for row in session.exit_drafts.list():
            valid = not row.get('error')
            content = session.exit_drafts.export_records([row['id']], portable_text)[0] if valid else None
            rows.append({'key': 'draft:' + row['id'], 'group': 'draft',
                         'label': row.get('label') or '已保存未完成草稿', 'valid': valid,
                         'detail': (f"{row.get('draft_kind', '')} · 原窗口 {row.get('surface_id', '')} · 未计算或应用"
                                    if valid else row['error']),
                         'content': content, 'error': row.get('error', '')})
        preference_error = session.play_preferences.error
        if _preference_disk_stamp(session.play_preferences) != session.play_preferences._disk_stamp:
            preference_error = '游玩设置文件已被其他进程修改；请先在游玩显示与快捷键中重新读取，当前选择仍保留'
        for key, label in PREFERENCE_LABELS.items():
            rows.append({'key': 'preference:' + key, 'group': 'preference', 'label': label,
                         'detail': json.dumps(session.play_preferences.values[key], ensure_ascii=False),
                         'valid': not bool(preference_error)})
        return {'rows': rows, 'application_version': __version__, 'rules_version': session.catalog.data['version'],
                'knowledge_error': stored['error'], 'preferences_error': preference_error,
                'save_root': session.settings['save_root'],
                'backup_target': str(session.backups.scope(session.settings['save_root'])),
                'knowledge_target': str(session.knowledge.path), 'preferences_target': str(session.play_preferences.path),
                'note': '仅迁移所选助手资料。进度进入助手档案，回档需另行预览确认；本机目录和位置保持。'}


def _export(session, payload):
    view = status(session)
    available = {row['key']: row for row in view['rows'] if row['valid']}
    selected = _selection(payload.get('selected'), available)
    contents = {}
    backups = [{'slot': available[key]['slot'], 'id': available[key]['id']} for key in selected if key.startswith('backup:')]
    if backups:
        preview = flows.export_preview(session.backups, session.settings['save_root'], {'selected': backups})
        raw, _ = flows.export_batch(session.backups, session.settings['save_root'], {'selected': backups, 'expected': preview['expected']})
        contents['backups.zip'] = _portable_backups(raw)
    if any(key.startswith(('plan:', 'favorite:')) for key in selected):
        value, _ = session.knowledge._read()
        value['recent'] = []
        value['plans'] = [portable_record(row) for row in value['plans'] if 'plan:' + row['id'] in selected]
        value['favorites'] = [identity for identity in value['favorites'] if 'favorite:' + identity in selected]
        session.knowledge._validate(value)
        contents['knowledge.json'] = encode(value)
    preferences = {key: copy.deepcopy(session.play_preferences.values[key]) for key in PREFERENCE_LABELS if 'preference:' + key in selected}
    if preferences:
        validate_preferences(preferences)
        contents['preferences.json'] = encode(preferences)
    draft_ids = [key.split(':', 1)[1] for key in selected if key.startswith('draft:')]
    if draft_ids:
        contents['exit-drafts.json'] = encode({'format': 1, 'kind': 'denghuo-exit-draft-set',
            'records': session.exit_drafts.export_records(draft_ids, portable_text)})
    manifest = {'format': 1, 'kind': 'denghuo-portable-bundle',
                'source': {'application': '灯火', 'application_version': __version__, 'rules_version': session.catalog.data['version']},
                'members': {name: {'bytes': len(raw), 'sha256': checksum(raw)} for name, raw in contents.items()}}
    contents[INDEX] = encode(manifest)
    raw = _zip(contents)
    return {'rows': [available[key] for key in selected], 'count': len(selected), 'bytes': len(raw),
            'expected': checksum(raw), 'source': manifest['source'],
            'note': '不含连接口令、旧机器目录、窗口坐标、最近访问记录；名称、备注和草稿原始文字中的路径与标记秘密会脱敏，普通无效文字逐字保留。请预览具体内容后再分享。'}, raw


def export_preview(session, payload):
    with session.lock, _locks(session):
        return _export(session, payload)[0]


def export_bundle(session, payload):
    with session.lock, _locks(session):
        preview, raw = _export(session, payload)
        if payload.get('expected') != preview['expected']:
            raise ValueError('所选资料、名称或偏好已变化，请重新预览导出清单')
        return raw, 'denghuo-portable-bundle.zip'


def inspect(session, raw):
    if not isinstance(raw, bytes) or not 1 < len(raw) <= MAX_TOTAL:
        raise ValueError('请选择小于64 MiB的灯火统一迁移 ZIP')
    try:
        with ZipFile(BytesIO(raw)) as archive:
            infos = archive.infolist()
            names = {info.filename for info in infos}
            if (not 2 <= len(infos) <= 5 or len(names) != len(infos) or INDEX not in names
                    or names - MEMBERS - {INDEX} or sum(info.file_size for info in infos) > MAX_TOTAL
                    or any(info.flag_bits & 1 or stat.S_IFMT(info.external_attr >> 16) not in (0, stat.S_IFREG) for info in infos)
                    or archive.getinfo(INDEX).file_size > 65536):
                raise ValueError('迁移包条目、路径、文件类型或解压大小不正确')
            manifest = read_json(archive.read(INDEX))
            if (not isinstance(manifest, dict) or set(manifest) != {'format', 'kind', 'source', 'members'}
                    or type(manifest['format']) is not int or manifest['format'] != 1
                    or manifest['kind'] != 'denghuo-portable-bundle'
                    or not isinstance(manifest['source'], dict) or set(manifest['source']) != {'application', 'application_version', 'rules_version'}
                    or manifest['source']['application'] != '灯火'
                    or any(not isinstance(v, str) or not re.fullmatch(r'[\w.+-]{1,80}', v) for k, v in manifest['source'].items() if k != 'application')
                    or not isinstance(manifest['members'], dict) or set(manifest['members']) != names - {INDEX}):
                raise ValueError('不支持的迁移格式或来源摘要，请使用兼容版本重新导出')
            contents = {}
            for name, entry in manifest['members'].items():
                if (not isinstance(entry, dict) or set(entry) != {'bytes', 'sha256'} or type(entry['bytes']) is not int
                        or entry['bytes'] != archive.getinfo(name).file_size or not isinstance(entry['sha256'], str)
                        or not re.fullmatch(r'[a-f0-9]{64}', entry['sha256'])):
                    raise ValueError('迁移清单与实际文件不一致')
                if (name == 'knowledge.json' and entry['bytes'] > MAX_BYTES
                        or name == 'preferences.json' and entry['bytes'] > 16384
                        or name == 'exit-drafts.json' and entry['bytes'] > MAX_DRAFT_SET):
                    raise ValueError('资料或偏好超过原有大小限制')
                contents[name] = archive.read(name)
                if checksum(contents[name]) != entry['sha256']:
                    raise ValueError('迁移包文件校验失败，尚未导入')
        knowledge = read_json(contents['knowledge.json']) if 'knowledge.json' in contents else {'format': 1, 'favorites': [], 'recent': [], 'plans': []}
        session.knowledge._validate(knowledge)
        if knowledge['recent']:
            raise ValueError('迁移包不应包含旧机器最近访问记录')
        preferences = read_json(contents['preferences.json']) if 'preferences.json' in contents else {}
        if not isinstance(preferences, dict) or set(preferences) - set(PREFERENCE_LABELS):
            raise ValueError('迁移偏好包含目录、位置或不支持的字段')
        validate_preferences(preferences)
        if 'exit-drafts.json' in contents:
            checked_draft_set(read_json(contents['exit-drafts.json']))
        return manifest, contents, knowledge, preferences
    except ValueError as exc:
        raise ValueError(str(exc) or '迁移资料不符合已验证的方案契约；尚未导入，原件仍保留') from exc
    except (BadZipFile, KeyError, TypeError, AttributeError, RecursionError, OverflowError, RuntimeError) as exc:
        raise ValueError('迁移包无法读取，尚未导入；已有原件仍保留') from exc


def _merged_plan(value, row):
    original = next((item for item in value['plans'] if item['id'] == row['id']), None)
    result = copy.deepcopy(row)
    action = '新增方案'
    if original == row:
        return None, '相同记录，保留现有原件'
    if original is not None:
        result['id'] = checksum(encode(row))[:32]
        result['name'] = row['name'][:74] + '（导入）'
        copied = next((item for item in value['plans'] if item['id'] == result['id']), None)
        if copied == result:
            return None, '相同冲突副本已存在，不再重复'
        if copied is not None:
            raise ValueError('冲突副本ID已被其他记录使用，请先处理本机资料')
        action = '同ID不同内容，保留双方并新增副本'
    return result, action


def _preview(session, raw):
    manifest, contents, knowledge, preferences = inspect(session, raw)
    target = _target(session)
    value, _ = session.knowledge._read()
    rows = []
    if 'backups.zip' in contents:
        incoming = flows.import_preview(session.backups, session.settings['save_root'], contents['backups.zip'])
        history = session.backups.history(session.settings['save_root'], discover=False)
        for row in incoming['rows']:
            duplicate = any(item['slot'] == row['slot'] and item['id'] == row['id'] for item in history)
            rows.append({'key': 'backup:' + row['file'], 'group': 'backup', 'label': row['label'] or f"槽位 {row['slot']} · {row['id'][:10]}",
                         'detail': '同进度已存在，导入时合并档案信息' if duplicate else '导入助手档案；尚未回档',
                         'valid': row['valid'], 'error': row['error'], 'summary': row.get('summary'),
                         'target': str(session.backups.scope(session.settings['save_root']))})
    for row in knowledge['plans']:
        _, action = _merged_plan(value, row)
        available, warning = True, ''
        try:
            canonical_plan(session, row['kind'], row['entry'], row['params'])
        except (ValueError, KeyError, OSError, OverflowError) as exc:
            available, warning = False, str(exc)
        rows.append({'key': 'plan:' + row['id'], 'group': 'plan', 'label': row['name'],
                     'detail': action + f" · 来源资料 {row['rules_version']}", 'valid': True,
                     'available': available, 'error': warning + ('；可保留为旧版本参考，重开需再核对' if not available else ''),
                     'target': str(session.knowledge.path), 'content': row})
    entries = {row['id']: row for row in session.catalog.entries}
    for identity in knowledge['favorites']:
        rows.append({'key': 'favorite:' + identity, 'group': 'favorite', 'label': entries.get(identity, {}).get('name', identity),
                     'detail': '已收藏，保留现有记录' if identity in value['favorites'] else '新增收藏', 'valid': True,
                     'available': identity in entries, 'error': '' if identity in entries else '本版条目不可用；可保留收藏ID供未来版本识别',
                     'target': str(session.knowledge.path)})
    for key, setting in preferences.items():
        preference_error = session.play_preferences.error
        if target['preferences_disk'] != target['preferences_loaded']:
            preference_error = '本机游玩设置磁盘内容已变化；先在游玩显示与快捷键重新读取，再预览迁移'
        rows.append({'key': 'preference:' + key, 'group': 'preference', 'label': PREFERENCE_LABELS[key],
                     'detail': json.dumps({'当前': session.play_preferences.values[key], '导入': setting}, ensure_ascii=False),
                     'valid': not bool(preference_error), 'error': preference_error, 'target': str(session.play_preferences.path)})
    if 'exit-drafts.json' in contents:
        for record in checked_draft_set(read_json(contents['exit-drafts.json'])):
            _, action = session.exit_drafts.preview_import(record)
            rows.append({'key': 'draft:' + record['id'], 'group': 'draft', 'label': record['label'],
                         'detail': action + f" · 草稿类型 {record['draft_kind']} · 来源窗口 {record['surface_id']}",
                         'valid': True, 'content': record, 'target': str(session.exit_drafts.directory)})
    # Preview operations must not hide index updates (e.g. recovery discovery).
    if target != _target(session):
        raise ValueError('本机资料在预览期间变化，请重新预览；尚未导入')
    result = {'rows': rows, 'source': manifest['source'], 'current_application_version': __version__,
              'current_rules_version': session.catalog.data['version'],
              'version_difference': manifest['source']['application_version'] != __version__ or manifest['source']['rules_version'] != session.catalog.data['version'],
              'save_root': session.settings['save_root'], 'config_error': session.config_error,
              'note': '保留本机存档连接。需要换目录时先打开连接设置重新绑定并重新预览。导入进度只进助手档案，回档另行确认。'}
    result['expected'] = checksum(encode({'bundle': checksum(raw), 'target': target, 'preview': result}))
    return result, contents, knowledge, preferences


def import_preview(session, raw):
    with session.lock, _locks(session):
        return _preview(session, raw)[0]


def import_bundle(session, raw, payload):
    with session.lock, _locks(session):
        preview, contents, incoming, preferences = _preview(session, raw)
        if payload.get('confirmed') is not True or payload.get('expected') != preview['expected']:
            raise ValueError('迁移包、本机目标或资料已变化，请重新预览；尚未应用')
        available = {row['key']: row for row in preview['rows']}
        selected = _selection(payload.get('selected'), available)
        results = []
        value, stamp = session.knowledge._read()
        knowledge_keys = [key for key in selected if key.startswith(('plan:', 'favorite:'))]
        if knowledge_keys:
            try:
                merged = copy.deepcopy(value)
                for row in incoming['plans']:
                    if 'plan:' + row['id'] in knowledge_keys:
                        addition, _ = _merged_plan(merged, row)
                        if addition is not None:
                            merged['plans'].append(addition)
                merged['favorites'] = list(dict.fromkeys([*merged['favorites'], *[identity for identity in incoming['favorites'] if 'favorite:' + identity in knowledge_keys]]))
                if len(merged['plans']) > MAX_PLANS or len(merged['favorites']) > MAX_FAVORITES:
                    raise ValueError('合并后超过原有方案/收藏数量上限，请减少选择')
                if merged != value:
                    session.knowledge._write(merged, stamp)
                results.extend({'key': key, 'ok': True, 'saved': True, 'message': available[key]['detail']} for key in knowledge_keys)
            except (OSError, ValueError) as exc:
                results.extend({'key': key, 'ok': False, 'saved': False, 'error': str(exc)} for key in knowledge_keys)
        preference_keys = [key for key in selected if key.startswith('preference:')]
        if preference_keys:
            try:
                patch = {key.split(':', 1)[1]: preferences[key.split(':', 1)[1]] for key in preference_keys}
                # Actual target settings are retained for every unselected or nonportable field.
                session.play_preferences.update(patch, expected_generation=session.play_preferences.generation)
                if session.manager_available:
                    session.manager_commands.put(('play_settings_changed', session.play_preferences.generation))
                results.extend({'key': key, 'ok': True, 'saved': True, 'message': '磁盘已保存；本会话实际应用/注册状态见下方'} for key in preference_keys)
            except (OSError, ValueError) as exc:
                results.extend({'key': key, 'ok': False, 'saved': False, 'error': str(exc)} for key in preference_keys)
        backup_keys = [key for key in selected if key.startswith('backup:')]
        if backup_keys:
            if session.config_error:
                results.extend({'key': key, 'ok': False, 'saved': False, 'error': '本机连接设置尚未修复，请重新绑定后预览；尚未导入进度'} for key in backup_keys)
            else:
                try:
                    transfer = flows.import_batch(session.backups, session.settings['save_root'], contents['backups.zip'], checksum(contents['backups.zip']), [key.split(':', 1)[1] for key in backup_keys], True)
                    results.extend({**row, 'key': 'backup:' + row['source_file'], 'saved': row['ok'], 'message': '已保存到助手档案；未回档'} for row in transfer['results'])
                    session.backups._storage_cache = None
                except (OSError, ValueError) as exc:
                    results.extend({'key': key, 'ok': False, 'saved': False, 'error': str(exc)} for key in backup_keys)
        if 'exit-drafts.json' in contents:
            for record in checked_draft_set(read_json(contents['exit-drafts.json'])):
                key = 'draft:' + record['id']
                if key not in selected:
                    continue
                try:
                    imported = session.exit_drafts.import_record(record)
                    results.append({'key': key, 'ok': True, 'saved': True, **imported})
                except (OSError, ValueError) as exc:
                    results.append({'key': key, 'ok': False, 'saved': False, 'error': str(exc)})
        runtime = session.play_settings()
        return {'results': results, 'success_count': sum(row['ok'] for row in results),
                'failure_count': sum(not row['ok'] for row in results), 'restored': False,
                'preferences_runtime': runtime, 'note': '结果逐项表示实际磁盘写入；原有资料和活跃游戏存档仍保留。重试前重新预览。'}
