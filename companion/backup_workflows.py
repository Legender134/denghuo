"""Explicit backup lifecycle previews and bounded, indexed batch transfers.

Default retention is preserve-all. Physical reclamation requires an exact preview,
verified external originals and explicit confirmation; active undo copies stay protected.
"""
from io import BytesIO
from itertools import chain
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid
from zipfile import ZipFile, ZipInfo, ZIP_STORED, ZIP_DEFLATED, BadZipFile

from .backups import MAX_TOTAL, STAGE_NAME, BackupLibrary, unlinked
from .backup_archive import IDENTITY, read_archive, player_summary, valid_time

MAX_BATCH = 32
MEMBER = re.compile(r'backups/slot[1-6]-[0-9a-f]{64}\.zip\Z')
BEFORE = re.compile(r'\.denghuo-before-([1-6])-\d+-[0-9a-f]{8}\Z')
RETAINED = re.compile(r'[0-9a-f]{64}-\d+\.zip\Z')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def folder_size(folder):
    total = 0
    for path in folder.rglob('*'):
        unlinked(path)
        if path.is_file():
            total += path.stat().st_size
    return total


def _stage_stat(path):
    rows = []
    for member in chain((path,), path.rglob('*')):
        attrs = unlinked(member).stat()
        if len(rows) >= 20000:
            raise ValueError('暂存目录条目过多，原件仍保留')
        rows.append([member.relative_to(path).as_posix(), attrs.st_mode, attrs.st_size,
                     attrs.st_mtime_ns, attrs.st_ino])
    return digest(sorted(rows))


def inspect_stage(manager, root, payload):
    """Inspect one exact stage. Never infer ownership from the directory name alone."""
    with manager.lock:
        name = payload.get('file')
        if not isinstance(name, str) or not STAGE_NAME.fullmatch(name):
            raise ValueError('请选择清单中的确切中断暂存目录')
        path = unlinked(Path(root).resolve()/name)
        if not path.is_dir():
            raise ValueError('暂存目录已变化，请重新读取空间清单')
        result = {'file': name, 'path': str(path), 'slot': int(STAGE_NAME.fullmatch(name)[1]),
                  'bytes': folder_size(path), 'retryable': False, 'verified': False,
                  'verification': '未通过完整核验', 'error': '', 'applied': False}
        stamp = _stage_stat(path)
        try:
            owner = manager.stage_records(root).get(name)
            if owner is None:
                raise ValueError('没有匹配的助手暂存来源记录；可导出原件核对，不能直接回档或回收')
            result['reason'] = owner['reason']
            files, directories, _ = _copy_files(path)
            actual = {key: hashlib.sha256(raw).hexdigest() for key, raw in files.items()}
            if actual != owner['files'] or directories != ['.']:
                raise ValueError('暂存内容与来源记录不一致或解包尚未完整；保留原件，不能重试')
            source = manager.selected(root, {'slot': owner['slot'], 'id': owner['backup_id']})
            metadata, _, game, _ = manager.checked_archive(root, owner['backup_id'], owner['slot'])
            if metadata['files'] != actual:
                raise ValueError('原备份与暂存内容不一致，不能重试；原件仍保留')
            from .engine import Catalog
            rules = Catalog().data
            if type(game.get('version')) is not int or not 850 <= game['version'] <= rules['version_code']:
                raise ValueError('原备份版本未通过当前规则兼容检查；请保留并使用兼容版本核对')
            if stamp != _stage_stat(path):
                raise ValueError('暂存目录在检查期间变化，请重新检查；原件仍保留')
            result.update(verified=True, retryable=True, verification='暂存与原备份逐文件校验一致',
                          source={key: source.get(key) for key in ('slot', 'id', 'label', 'locked', 'saved', 'class', 'depth')},
                          source_archive_sha256=hashlib.sha256(unlinked(manager.scope(root)/(owner['backup_id']+'.zip')).read_bytes()).hexdigest(),
                          stage_digest=digest(actual), rules_version=rules['version'],
                          note='重试使用已重新校验的原备份，并重新预览当前活动进度；这个暂存和原备份均完整保留。')
        except (OSError, ValueError, KeyError, BadZipFile) as exc:
            result['error'] = str(exc)
        if not hasattr(manager, 'stage_checks'):
            manager.stage_checks = {}
        manager.stage_checks[(str(Path(root).resolve()), name)] = {'stamp': stamp, **result}
        return result


def stage_preview(manager, root, payload):
    with manager.lock:
        result = inspect_stage(manager, root, payload)
        if not result['retryable']:
            raise ValueError(result['error'] or '暂存未通过检查，原件仍保留')
        manager.closed_check()
        source = result['source']
        preview = manager.preview(root, {'slot': source['slot'], 'id': source['id']})
        result.update(current=preview['current'], target=preview['target'],
                      expected_current=preview['expected_current'],
                      confirm_phrase='重新尝试暂存 ' + result['file'])
        result['expected'] = digest(result)
        return result


def retry_stage(manager, root, payload):
    with manager.lock:
        preview = stage_preview(manager, root, payload)
        if (payload.get('confirmed') is not True or payload.get('expected') != preview['expected']
                or payload.get('confirm') != preview['confirm_phrase']):
            raise ValueError('暂存、原备份或当前进度已变化，请重新预览并明确确认确切目标；尚未回档')
        source = preview['source']
        notice = manager.restore(root, {'slot': source['slot'], 'id': source['id'],
                                       'expected_current': preview['expected_current'],
                                       'confirm': f"恢复槽位 {source['slot']}"})
        return {'ok': True, 'file': preview['file'], 'slot': source['slot'],
                'original_stage_preserved': True, 'restored': True, 'message': notice}


def protected_records(manager, root, records):
    protected = {(row['slot'], row['id']):'已固定保留' for row in records if row.get('locked')}
    for journal in manager.journals(root):
        if not journal['active']:
            continue
        if journal.get('target_backup'):
            protected[(journal['slot'], journal['target_backup'])] = '关联当前可撤回的回档'
        else:
            # Old journals do not identify the target archive; conservatively retain matches.
            after = journal.get('after') or {}
            for row in records:
                if row['slot']==journal['slot'] and all(row.get(key)==after.get(key) for key in ('saved','run_id','class','hp','ht','depth')):
                    protected[(row['slot'], row['id'])] = '关联当前可撤回的回档（旧记录匹配）'
    return protected


def _storage_inventory(manager, root):
    with manager.lock:
        scope = manager.scope(root)
        records = manager.history(root)
        protected = protected_records(manager, root, records)
        active = []
        for row in records:
            path = unlinked(scope / (row['id']+'.zip'))
            active.append({**row, 'file':path.name, 'bytes':path.stat().st_size if path.is_file() else 0,
                           'reason':protected.get((row['slot'],row['id']), '活动历史；默认保留'),
                           'protected':(row['slot'],row['id']) in protected})
        retained = [{**row,'reason':'用户移出活动库后完整保留，可重新加入'} for row in manager.retained_status(root)]
        quarantine_dir = unlinked(manager.directory.parent/'backup-quarantine'/scope.name)
        quarantine = [{'file':path.name, 'bytes':path.stat().st_size, 'time':path.stat().st_mtime,
                       'reason':'自动校验发现损坏后隔离，保留排查原件'} for path in quarantine_dir.glob('*.zip') if unlinked(path).is_file()]
        journals = manager.journals(root)
        if isinstance(root, BackupLibrary):
            manager._storage_cache = None
            return {'default_policy': 'preserve-all', 'groups': [
                        {'kind': 'active', 'title': '活动历史', 'rows': active, 'directory': str(scope)},
                        {'kind': 'retained', 'title': '移出后保留', 'rows': retained,
                         'directory': str(manager.directory.parent/'backup-recycle'/scope.name)},
                        {'kind': 'quarantine', 'title': '损坏隔离', 'rows': quarantine, 'directory': str(quarantine_dir)}],
                    'totals': manager.storage_breakdown(root),
                    'scope_note': '这里只核对所选助手备份库；没有读取或更改任何游戏存档目录。'}
        before = []
        for path in unlinked(Path(root)).glob('.denghuo-before-*'):
            unlinked(path)
            match = BEFORE.fullmatch(path.name)
            if not match or not path.is_dir():
                continue
            journal = next((row for row in journals if row['original']==path.name), None)
            active_undo = bool(journal and journal['active'] and journal['existed'])
            before.append({'file':path.name,'slot':int(match[1]),'bytes':folder_size(path), 'time':path.stat().st_mtime,
                           'protected':active_undo, 'undo_id':journal['id'] if active_undo else None,
                           'reason':'当前撤回操作需要这个完整副本' if active_undo else
                                    '先前回档的完整原进度，默认保留' if journal else
                                    '撤回前或未关联的完整进度，默认保留，请自行核对'})
        try:
            owners, owner_error = manager.stage_records(root), ''
        except (OSError, ValueError) as exc:
            owners, owner_error = {}, str(exc)
        stages = []
        for path in unlinked(Path(root)).glob('.denghuo-stage-*'):
            path = unlinked(path)
            match = STAGE_NAME.fullmatch(path.name)
            if not match or not path.is_dir():
                continue
            owner = owners.get(path.name)
            checked = getattr(manager, 'stage_checks', {}).get((str(Path(root).resolve()), path.name))
            signature = _stage_stat(path)
            if checked and checked['stamp'] != signature:
                checked = None
            stages.append({'file': path.name, 'slot': int(match[1]), 'bytes': folder_size(path),
                           'time': path.stat().st_mtime, 'owned': bool(owner),
                           'reason': owner['reason'] if owner else owner_error or
                                     '旧版或未关联的回档暂存；未应用到活动存档，归属尚未核验',
                           'verification': checked['verification'] if checked else '尚未检查完整内容',
                           'retryable': bool(checked and checked['retryable']),
                           'error': checked.get('error', '') if checked else '',
                           'protected': not bool(owner)})
        manager._storage_cache = None  # Include newly interrupted stages immediately.
        return {'default_policy':'preserve-all', 'groups':[
                    {'kind':'active','title':'活动历史','rows':active,'directory':str(scope)},
                    {'kind':'retained','title':'移出后保留','rows':retained,'directory':str(manager.directory.parent/'backup-recycle'/scope.name)},
                    {'kind':'quarantine','title':'损坏隔离','rows':quarantine,'directory':str(quarantine_dir)},
                    {'kind':'before','title':'回档与撤回前目录','rows':before,'directory':str(Path(root))},
                    {'kind':'stage','title':'中断回档暂存','rows':stages,'directory':str(Path(root))}],
                'totals':manager.storage_breakdown(root),
                'scope_note':'清单针对当前连接目录；总占用中的活动、移出和隔离项还包含此前连接目录。不会自动整理其他目录。'}


def open_storage(manager, root, payload):
    view = storage_inventory(manager, root)
    group = next((group for group in view['groups'] if group['kind']==payload.get('kind')), None)
    if group is None:
        raise ValueError('请选择活动、移出、隔离、回档前或中断暂存目录')
    path = unlinked(Path(group['directory']))
    if not path.is_dir():
        raise ValueError('该保留目录尚未建立')
    if os.name != 'nt':
        raise ValueError('此环境无法打开 Windows 文件管理器，可导出所选副本')
    try:
        os.startfile(str(path))
    except OSError as exc:
        raise ValueError('本地目录未能打开，请检查权限或系统文件关联') from exc
    return {'opened':True}


def validate_selection(selected):
    if not isinstance(selected,list) or not 1<=len(selected)<=MAX_BATCH:
        raise ValueError(f'请选择1–{MAX_BATCH}份备份，跨槽位也可选择')
    result = []
    for item in selected:
        if (not isinstance(item,dict) or set(item)!={'slot','id'} or type(item['slot']) is not int
                or item['slot'] not in range(1,7) or not isinstance(item['id'],str) or not IDENTITY.fullmatch(item['id'])):
            raise ValueError('备份选择清单不正确')
        result.append(item)
    if len({(item['slot'],item['id']) for item in result})!=len(result):
        raise ValueError('选择清单包含重复备份')
    return result


def stable_transfer(raw, observation=None):
    """Keep preview signatures independent of ZIP container wall-clock timestamps."""
    output = BytesIO()
    with ZipFile(BytesIO(raw)) as original, ZipFile(output,'w') as target:
        for name in sorted(original.namelist()):
            info = ZipInfo(name, date_time=(1980,1,1,0,0,0))
            info.compress_type = ZIP_DEFLATED
            content = original.read(name)
            if name == 'manifest.json' and observation is not None:
                metadata = json.loads(content)
                metadata['transfer']['last_observed'] = observation['last_observed']
                content = json.dumps(metadata, ensure_ascii=True).encode('utf-8')
            target.writestr(info, content)
    return output.getvalue()


def prepare_export(manager, root, selected, observations=None):
    selected = validate_selection(selected)
    rows, contents, size = [], {}, 0
    for item in selected:
        raw, _ = manager.export(root,item)
        observation = (observations or {}).get((item['slot'], item['id']))
        raw = stable_transfer(raw, observation)
        row = manager.selected(root,item)
        size += len(raw)
        if size>MAX_TOTAL:
            raise ValueError('所选备份合计超过64 MiB，请分批选择；没有省略任何备份')
        member = f"backups/slot{item['slot']}-{item['id']}.zip"
        rows.append({'file':member,'slot':item['slot'],'id':item['id'],'bytes':len(raw),
                     'sha256':hashlib.sha256(raw).hexdigest(), 'label':row.get('label',''),
                     'saved':row['saved'],'first_observed':None if row.get('recovered_at') else row['time'],
                     'last_observed':observation['last_observed'] if observation is not None else None if row.get('recovered_at') else row['last_seen'],
                     'class':row['class'],'level':row['level'],'depth':row['depth']})
        contents[member] = raw
    return rows, contents


def export_preview(manager, root, payload):
    with manager.lock:
        rows, _ = prepare_export(manager,root,payload.get('selected'))
        expected = digest(rows)
        # Retain only small observation metadata, never a cache of entire ZIPs.
        # Separate roots and concurrent previews remain independent, up to 32.
        if not hasattr(manager, '_transfer_export_previews'):
            manager._transfer_export_previews = {}
        manager._transfer_export_previews[(str(unlinked(manager.scope(root))), expected)] = {
            (row['slot'], row['id']): dict(row) for row in rows}
        while len(manager._transfer_export_previews) > MAX_BATCH:
            manager._transfer_export_previews.pop(next(iter(manager._transfer_export_previews)))
        return {'rows':rows,'count':len(rows),'bytes':sum(row['bytes'] for row in rows),
                'expected':expected,'message':'所选进度将逐份完整校验并附迁移索引；保留预览时的观察时间，不会移出或恢复游戏存档'}


def export_batch(manager, root, payload):
    with manager.lock:
        expected = payload.get('expected')
        if not isinstance(expected, str) or not IDENTITY.fullmatch(expected):
            raise ValueError('导出预览无效，请重新预览导出清单')
        observations = getattr(manager, '_transfer_export_previews', {}).get((str(unlinked(manager.scope(root))), expected))
        if observations is None:
            raise ValueError('导出预览已过期，请重新预览导出清单')
        rows, contents = prepare_export(manager,root,payload.get('selected'),observations)
        if payload.get('expected')!=digest(rows):
            raise ValueError('备份内容、名称或选择已变化，请重新预览导出清单')
        output = BytesIO()
        with ZipFile(output,'w',ZIP_STORED) as archive:
            archive.writestr('denghuo-transfer.json',json.dumps({'format':1,'kind':'denghuo-backup-set','entries':rows},ensure_ascii=True))
            for name,raw in contents.items():
                archive.writestr(name,raw)
        raw = output.getvalue()
        if len(raw)>MAX_TOTAL:
            raise ValueError('迁移包超过64 MiB，请减少所选记录后重试')
        return raw, 'denghuo-backup-set.zip'


def inspect_batch(manager, root, raw):
    if not isinstance(raw,bytes) or not 1<len(raw)<=MAX_TOTAL:
        raise ValueError('迁移包需要小于64 MiB')
    try:
        archive = ZipFile(BytesIO(raw))
        infos = archive.infolist()
        if (not 2<=len(infos)<=MAX_BATCH+1 or len({row.filename for row in infos})!=len(infos)
                or sum(row.file_size for row in infos)>MAX_TOTAL
                or any(row.flag_bits&1 or stat.S_IFMT(row.external_attr>>16) not in (0,stat.S_IFREG) for row in infos)):
            raise ValueError('迁移包条目、文件类型或解压大小不正确')
        info = archive.getinfo('denghuo-transfer.json')
        if info.file_size>65536:
            raise ValueError('迁移索引过大')
        index = json.loads(archive.read(info))
        if not isinstance(index,dict) or set(index)!={'format','kind','entries'} or type(index['format']) is not int or index['format']!=1 or index['kind']!='denghuo-backup-set':
            raise ValueError('不是灯火的备份迁移包')
        rows = index['entries']
        if not isinstance(rows,list) or not 1<=len(rows)<=MAX_BATCH:
            raise ValueError('迁移包记录数量不正确')
        names = []
        for row in rows:
            if (not isinstance(row,dict) or set(row)!={'file','slot','id','bytes','sha256','label','saved','first_observed','last_observed','class','level','depth'}
                    or not isinstance(row['file'],str) or not MEMBER.fullmatch(row['file'])
                    or type(row['slot']) is not int or row['slot'] not in range(1,7)
                    or not isinstance(row['id'],str) or not IDENTITY.fullmatch(row['id'])
                    or row['file']!=f"backups/slot{row['slot']}-{row['id']}.zip"
                    or type(row['bytes']) is not int or not 1<row['bytes']<=MAX_TOTAL
                    or not isinstance(row['sha256'],str) or not IDENTITY.fullmatch(row['sha256'])
                    or not isinstance(row['label'],str) or len(row['label'])>80 or any(ord(c)<32 for c in row['label'])
                    or not valid_time(row['saved']) or not isinstance(row['class'],str) or len(row['class'])>40
                    or type(row['level']) is not int or not 1<=row['level']<=10000
                    or type(row['depth']) is not int or not 1<=row['depth']<=26
                    or not (row['first_observed'] is None and row['last_observed'] is None
                            or valid_time(row['first_observed']) and valid_time(row['last_observed'])
                            and row['first_observed']<=row['last_observed'])):
                raise ValueError('迁移索引包含无效记录')
            names.append(row['file'])
        if len(set(names))!=len(names) or set(names)|{'denghuo-transfer.json'}!={row.filename for row in infos}:
            raise ValueError('迁移索引与实际文件不一致')
        results, contents = [], {}
        scope = manager.scope(root)
        scope.mkdir(parents=True,exist_ok=True)
        for row in rows:
            result = {'file':row['file'],'slot':row['slot'],'id':row['id'],'label':row['label'],'bytes':row['bytes'],
                      'valid':False,'error':''}
            incoming = unlinked(scope/('transfer-preview-'+uuid.uuid4().hex+'.pending'))
            try:
                member = archive.read(row['file'])
                if len(member)!=row['bytes'] or hashlib.sha256(member).hexdigest()!=row['sha256']:
                    raise ValueError('该记录的大小或迁移校验不一致')
                incoming.write_bytes(member)
                metadata, _, game, identity = read_archive(incoming, slot=row['slot'], identity=row['id'])
                transfer = metadata.get('transfer') or {}
                if (transfer.get('label','')!=row['label'] or metadata['saved']!=row['saved']
                        or any(game['hero'].get(key)!=row[field] for key,field in (('class','class'),('lvl','level')))
                        or game['depth']!=row['depth']
                        or transfer.get('first_observed')!=row['first_observed'] or transfer.get('last_observed')!=row['last_observed']):
                    raise ValueError('该记录的名称或游戏保存时间与索引不同')
                result.update(valid=True, summary=player_summary(game,metadata['saved']), saved=row['saved'],
                              first_observed=row['first_observed'], last_observed=row['last_observed'],
                              source_id=row['id'], sha256=row['sha256'])
                contents[row['file']] = member
            except (OSError,ValueError,BadZipFile,RuntimeError) as exc:
                result['error'] = str(exc)
            finally:
                if incoming.exists():incoming.unlink()
            results.append(result)
        return results,contents
    except (BadZipFile,KeyError,TypeError,AttributeError,RecursionError,OverflowError,RuntimeError) as exc:
        raise ValueError('迁移包无法读取，尚未导入任何记录') from exc
    finally:
        if 'archive' in locals():archive.close()


def import_preview(manager, root, raw):
    with manager.lock:
        rows,_ = inspect_batch(manager,root,raw)
        return {'rows':rows,'expected':hashlib.sha256(raw).hexdigest(),'count':len(rows),
                'valid_count':sum(row['valid'] for row in rows), 'message':'只导入所选可用记录到历史；不会自动恢复或覆盖游戏'}


def import_batch(manager, root, raw, expected, selected, confirmed):
    if confirmed is not True or expected!=hashlib.sha256(raw).hexdigest():
        raise ValueError('迁移包或确认已变化，请先重新预览导入清单')
    if not isinstance(selected,list) or not 1<=len(selected)<=MAX_BATCH or any(not isinstance(name,str) or not MEMBER.fullmatch(name) for name in selected) or len(set(selected))!=len(selected):
        raise ValueError('请选择要导入或重试的具体记录')
    with manager.lock:
        rows,contents = inspect_batch(manager,root,raw)
        by_name = {row['file']:row for row in rows}
        if set(selected)-set(by_name):
            raise ValueError('所选记录不属于这份迁移包')
        results = []
        for name in selected:
            row = by_name[name]
            result = {**row, 'source_file':name, 'source_id':row['id'], 'ok':False, 'error':row['error']}
            result.pop('id', None)
            if row['valid']:
                try:
                    imported = manager.import_archive(root,contents[name])
                    result.update(ok=True,id=imported['id'],target_id=imported['id'],
                                  imported_at=imported.get('imported_at'),error='')
                except (OSError,ValueError) as exc:
                    result['error'] = str(exc)
            results.append(result)
        return {'results':results,'success_count':sum(row['ok'] for row in results),
                'failure_count':sum(not row['ok'] for row in results), 'restored':False}


def retention_preview(manager, root, payload):
    policy = payload.get('policy')
    if not isinstance(policy,dict) or set(policy)-{'keep_per_slot','older_than_days','target_mib'}:
        raise ValueError('保留条件不正确')
    for key,maximum in (('keep_per_slot',5000),('older_than_days',36500),('target_mib',512)):
        if policy.get(key) is not None and (type(policy[key]) is not int or not 1<=policy[key]<=maximum):
            raise ValueError('保留数量、天数与活动库目标需要是有效正整数')
    with manager.lock:
        inventory = storage_inventory(manager,root)
        rows = inventory['groups'][0]['rows']
        protected = protected_records(manager,root,rows)
        keep = policy.get('keep_per_slot')
        days = policy.get('older_than_days')
        budget = policy.get('target_mib')
        positions = {}
        for slot in range(1,7):
            own = sorted((row for row in rows if row['slot']==slot),key=lambda row:row['last_seen'],reverse=True)
            positions.update({(row['slot'],row['id']):i for i,row in enumerate(own)})
        candidates,kept = [],[]
        active_bytes = sum(row['bytes'] for row in rows)
        remaining = active_bytes
        for row in sorted(rows,key=lambda row:row['last_seen']):
            key = (row['slot'],row['id'])
            reason = protected.get(key)
            if positions[key]==0:reason = reason or '每个槽位的最新记录始终保留'
            eligible = not reason and bool(keep is not None or days is not None or budget is not None)
            if keep is not None and positions[key]<keep:eligible=False;reason=reason or '处于所选每槽位保留数量内'
            if days is not None and manager.clock()-row['last_seen']<days*86400:eligible=False;reason=reason or '未达到所选观察年龄'
            if budget is not None and remaining<=budget*1048576:eligible=False;reason=reason or '已达到活动库目标'
            if eligible:
                # Actual byte signatures bind the review to concrete files and labels.
                raw,_ = manager.export(root,{'slot':row['slot'],'id':row['id']})
                candidates.append({**row,'archive_signature':hashlib.sha256(stable_transfer(raw)).hexdigest(),'reason':'符合手动整理条件，移入可重新加入的保留目录'})
                remaining-=row['bytes']
            else:
                kept.append({**row,'protected':key in protected or positions[key]==0,
                             'reason':reason or '默认保留全部'})
        selected = [{'slot':row['slot'],'id':row['id']} for row in candidates]
        signature = {'policy':policy,'candidates':[(row['slot'],row['id'],row['archive_signature']) for row in candidates],
                     'kept':[(row['slot'],row['id'],row['protected'],row['reason']) for row in kept]}
        return {'policy':policy,'candidates':candidates,'kept':kept,'selected':selected,'expected':digest(signature),
                'current_bytes':active_bytes,'remaining_active_bytes':remaining,
                'total_bytes_current':inventory['totals']['total'],
                'note':'仅预览，不执行自动整理。移入保留目录只调整活动库占用，原ZIP副本完整保留，不能用移出释放原件空间；整理后会重新统计。固定、最新进度和撤回关联记录不移出，回档前目录始终保留。'}


def archive_retention(manager, root, payload):
    if payload.get('confirmed') is not True:
        raise ValueError('请先核对具体候选，并确认移入可重新加入的保留目录')
    with manager.lock:
        preview = retention_preview(manager,root,payload)
        if payload.get('expected')!=preview['expected']:
            raise ValueError('整理候选已变化，请重新预览；尚未移出任何记录')
        results = []
        for row in preview['candidates']:
            try:
                manager.remove(root,{'slot':row['slot'],'id':row['id'],'confirm':f"移出备份 {row['slot']}"})
                results.append({'slot':row['slot'],'id':row['id'],'ok':True})
            except (ValueError,OSError) as exc:
                results.append({'slot':row['slot'],'id':row['id'],'ok':False,'error':str(exc)})
        return {'results':results,'archived':sum(row['ok'] for row in results),'deleted':0,
                'message':'原ZIP移入可重新加入的保留目录；回档前副本和游戏存档未改变'}


def export_preserved(manager, root, payload):
    with manager.lock:
        inventory = storage_inventory(manager,root)
        group = next((group for group in inventory['groups'] if group['kind']==payload.get('kind')),None)
        if not group or group['kind']=='active':
            raise ValueError('活动进度请用选择导出；这里导出移出、隔离或回档前副本')
        row = next((row for row in group['rows'] if row['file']==payload.get('file')),None)
        if row is None:raise ValueError('所选保留副本已变化，请刷新清单')
        path = unlinked(Path(group['directory'])/row['file'])
        paths = [path] if path.is_file() else [unlinked(p) for p in path.rglob('*') if p.is_file()]
        if not paths or len(paths)>10000:raise ValueError('所选副本为空或文件过多，请打开目录自行核对')
        before = {str(member): (member.stat().st_size, member.stat().st_mtime_ns, member.stat().st_ino) for member in paths}
        total = 0
        output = BytesIO()
        signatures = []
        with ZipFile(output,'w',ZIP_STORED) as archive:
            for member in paths:
                attrs=member.stat()
                total+=attrs.st_size
                if not stat.S_ISREG(attrs.st_mode) or total>MAX_TOTAL:raise ValueError('所选副本超过64 MiB或含特殊文件，请打开目录自行存档')
                data=member.read_bytes()
                after=member.stat()
                if len(data)!=attrs.st_size or (attrs.st_size,attrs.st_mtime_ns,attrs.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino):
                    raise ValueError('副本在导出期间变化，尚未生成存档包')
                name=member.name if path.is_file() else member.relative_to(path).as_posix()
                archive.writestr('preserved/'+name,data)
                signatures.append({'file':name,'sha256':hashlib.sha256(data).hexdigest()})
            archive.writestr('denghuo-preserved.json',json.dumps({'format':1,'kind':group['kind'],'original':row['file'],
                             'reason':row['reason'],'files':signatures,'restorable_backup_set':False},ensure_ascii=True))
        raw=output.getvalue()
        after_paths = [path] if path.is_file() else [unlinked(p) for p in path.rglob('*') if p.is_file()]
        after = {str(member): (member.stat().st_size, member.stat().st_mtime_ns, member.stat().st_ino) for member in after_paths}
        if before!=after:raise ValueError('副本文件清单在导出期间变化，请刷新清单再导出')
        if len(raw)>MAX_TOTAL:raise ValueError('导出包超过64 MiB，请打开目录自行存档')
        return raw,'denghuo-preserved-copy.zip'


def _copy_files(path):
    """Snapshot every original byte and empty directory, without following links."""
    path = unlinked(path)
    def walk():
        pending,found = [path],[]
        while pending:
            member = unlinked(pending.pop())
            found.append(member)
            if len(found)>20000:
                raise ValueError('original entries exceed the safe limit')
            if stat.S_ISDIR(member.lstat().st_mode):
                # Check each directory before enumeration, including Windows junctions.
                pending.extend(unlinked(child) for child in member.iterdir())
        return found
    paths = walk()
    if len(paths)>20000:
        raise ValueError('原件条目过多，请分批核对')
    files, directories, stamps, total = {}, [], {}, 0
    for member in sorted(paths):
        attrs = unlinked(member).stat()
        name = member.name if path.is_file() else member.relative_to(path).as_posix()
        stamps[name] = [attrs.st_dev,attrs.st_ino,attrs.st_size,attrs.st_mtime_ns,attrs.st_mode]
        if stat.S_ISDIR(attrs.st_mode):
            directories.append(name)
            continue
        if not stat.S_ISREG(attrs.st_mode):
            raise ValueError('原件含特殊文件，已停止操作')
        total += attrs.st_size
        if total>MAX_TOTAL:
            raise ValueError('原件超过64 MiB，请分批存档')
        with member.open('rb') as stream:
            raw = stream.read(attrs.st_size+1)
        if len(raw)!=attrs.st_size:
            raise ValueError('原件在读取期间变化，请重新预览')
        files[name] = raw
    after = {}
    for member in walk():
        attrs = unlinked(member).stat()
        name = member.name if path.is_file() else member.relative_to(path).as_posix()
        after[name] = [attrs.st_dev,attrs.st_ino,attrs.st_size,attrs.st_mtime_ns,attrs.st_mode]
    if stamps!=after:
        raise ValueError('原件文件清单或内容在读取期间变化，请重新预览')
    return files, directories, stamps


def _reclaim_inventory(manager, root):
    view = _storage_inventory(manager, root)
    records = manager.history(root)
    protected = protected_records(manager,root,records)
    latest = {}
    for record in records:
        if record['slot'] not in latest or record['last_seen']>latest[record['slot']]['last_seen']:
            latest[record['slot']] = record
    protected.update({(row['slot'],row['id']):'每槽位最新记录始终保留' for row in records
                      if row['last_seen']==latest[row['slot']]['last_seen']
                      and (row['slot'],row['id']) not in protected})
    journals = manager.journals(root)
    for group in view['groups']:
        for row in group['rows']:
            path = unlinked(Path(group['directory'])/row['file'])
            row['path'] = str(path)
            if group['kind'] in ('retained','quarantine') and path.with_suffix('.json').exists():
                row['bytes'] += unlinked(path.with_suffix('.json')).stat().st_size
            row['reclaimable'] = False
            row['reclaim_reason'] = '活动记录需先明确移出，原件默认保留'
            if group['kind']=='active':
                reason = protected.get((row['slot'],row['id']))
                if reason:
                    row.update(protected=True,reason=reason,reclaim_reason=reason)
                continue
            try:
                if group['kind']=='retained':
                    meta,_,game,identity = read_archive(path)
                    retained = manager.retained_metadata(path)
                    if identity!=path.stem.split('-')[0] or not retained or retained.get('slot')!=meta['slot']:
                        raise ValueError('缺少可信的应用移出记录，保持原件')
                    row.update(id=identity,slot=meta['slot'],summary=player_summary(game,meta['saved']),saved=meta['saved'])
                    owner = json.loads(unlinked(path.with_suffix('.json')).read_text(encoding='utf-8'))
                    row['last_seen'] = owner.get('last_seen',retained['first_seen'])
                    if not valid_time(row['last_seen']):
                        raise ValueError('移出来源观察时间损坏，保持原件')
                    if owner.get('locked') is True:
                        raise ValueError('移出来源记录已固定，保持原件')
                elif group['kind']=='quarantine':
                    sidecar = unlinked(path.with_suffix('.json'))
                    if not sidecar.is_file() or sidecar.stat().st_size>16384:
                        raise ValueError('缺少可信隔离来源记录；文件名不能证明归属，保持原件')
                    owner = json.loads(sidecar.read_text(encoding='utf-8'))
                    raw = path.read_bytes() if path.stat().st_size<=MAX_TOTAL else b''
                    if (not isinstance(owner,dict) or owner.get('format')!=1 or owner.get('kind')!='denghuo-quarantine'
                            or owner.get('scope')!=manager.scope(root).name or owner.get('id')!=path.stem.split('-')[0]
                            or type(owner.get('slot')) is not int or owner['slot'] not in range(1,7)
                            or owner.get('bytes')!=len(raw) or owner.get('sha256')!=hashlib.sha256(raw).hexdigest()):
                        raise ValueError('隔离来源记录与原件不一致，保持原件')
                    row.update(id=owner['id'],slot=owner['slot'],summary=owner.get('summary'),
                               saved=(owner.get('summary') or {}).get('saved'))
                    row['reclaim_reason'] = '损坏原件可逐字节外部存档；不代表可恢复进度'
                elif group['kind']=='stage':
                    checked = inspect_stage(manager, root, {'file': row['file']})
                    if not checked['verified']:
                        raise ValueError(checked['error'])
                    row.update(source_id=checked['source']['id'], verification=checked['verification'])
                else:
                    journal = next((j for j in journals if j['original']==row['file'] and j['existed']),None)
                    if journal is None or journal.get('digest')!=manager.directory_digest(path):
                        raise ValueError('缺少匹配完整内容的应用回档记录，保持原件')
                    row.update(summary=journal.get('before'),saved=(journal.get('before') or {}).get('saved'))
                    if journal['active']:
                        raise ValueError('当前撤回操作需要这个完整目录')
                reason = protected.get((row.get('slot'),row.get('id')))
                if reason:
                    raise ValueError(reason)
                row['reclaimable'] = True
                if group['kind']!='quarantine':
                    row['reclaim_reason'] = '可选：外部存档完整校验并明确确认后回收原件'
            except (OSError,ValueError,BadZipFile,KeyError,TypeError,AttributeError) as exc:
                row.update(protected=True,reclaim_reason=str(exc),reason=str(exc))
    # Preserve a slot's last known progress even when its active library is empty.
    retained = next(g['rows'] for g in view['groups'] if g['kind']=='retained')
    for slot in range(1,7):
        candidates = [r for r in retained if r.get('slot')==slot and valid_time(r.get('last_seen'))]
        if not candidates:
            continue
        newest = max(candidates,key=lambda r:r['last_seen'])
        if slot not in latest or newest['last_seen']>=latest[slot]['last_seen']:
            for row in candidates:
                if row['last_seen']==newest['last_seen']:
                    row['reclaimable'] = False
                    row['reclaim_reason'] = '每槽位最新已知进度始终保留'
                    row['protected'] = True
                    row['reason'] = row['reclaim_reason']
    return view


def _reclaim_snapshot(manager, root, payload):
    selected = payload.get('selected')
    if not isinstance(selected,list) or not 1<=len(selected)<=MAX_BATCH:
        raise ValueError('请选择1–32项具体保留原件')
    for item in selected:
        if (not isinstance(item,dict) or set(item)!={'kind','file'}
                or item['kind'] not in ('retained','quarantine','before','stage') or not isinstance(item['file'],str)):
            raise ValueError('原件选择清单不正确')
    if len({(item['kind'],item['file']) for item in selected})!=len(selected):
        raise ValueError('原件选择清单包含重复项')
    view = _reclaim_inventory(manager,root)
    rows, contents, total = [], {}, 0
    for number,item in enumerate(selected):
        group = next(g for g in view['groups'] if g['kind']==item['kind'])
        row = next((r for r in group['rows'] if r['file']==item['file']),None)
        if row is None or not row['reclaimable']:
            raise ValueError('所选原件已变化或受保护：'+(row['reclaim_reason'] if row else item['file']))
        path = unlinked(Path(row['path']))
        files,dirs,stamps = _copy_files(path)
        # Sidecars are part of the exact target and must be preserved too.
        if path.is_file() and path.with_suffix('.json').exists():
            sidecar = unlinked(path.with_suffix('.json'))
            extra,_,extra_stamps = _copy_files(sidecar)
            files.update(extra); stamps.update(extra_stamps)
        total += sum(len(raw) for raw in files.values())
        if total>MAX_TOTAL:
            raise ValueError('所选原件合计超过64 MiB，请分批选择')
        entries = []
        for name,raw in sorted(files.items()):
            member = f'originals/{number}/{name}'
            entries.append({'file':name,'member':member,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
            contents[member] = raw
        rows.append({**row,'kind':item['kind'],'bytes':sum(len(raw) for raw in files.values()),
                     'files':entries,'directories':dirs,'stamps':stamps})
    indexes = {}
    for name in ('history.json','restores.json','timeline.json'):
        path = unlinked(manager.scope(root)/name)
        indexes[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    signature = {'root':str(unlinked(Path(root)).resolve()),'scope':str(manager.scope(root)),
                 'context':payload.get('context'), 'groups':view['groups'],'indexes':indexes,'rows':rows}
    expected = digest(signature)
    return {'rows':rows,'selected':selected,'expected':expected,'count':len(rows),'bytes':total,
            'confirm_phrase':f'回收 {len(rows)} 项原件','active_bytes_released':0,
            'note':'默认保留全部。实际回收只涉及所选原件内容字节；不增加活动额度，不恢复游戏。损坏原件归档不代表可恢复。'},contents


def reclaim_preview(manager, root, payload):
    with manager.lock:
        return _reclaim_snapshot(manager,root,payload)[0]


def _external_archive(manager, root, payload):
    name = payload.get('external_path')
    if not isinstance(name,str) or not name.strip() or not Path(name).is_absolute():
        raise ValueError('请填写外部归档 ZIP 的完整绝对路径，浏览器下载位置不能作为核验证据')
    path = unlinked(Path(name)).resolve()
    for forbidden in (unlinked(manager.directory.parent).resolve(),unlinked(Path(root)).resolve()):
        if path==forbidden or forbidden in path.parents:
            raise ValueError('外部归档不得位于助手数据目录、游戏存档目录或待回收目标内')
    if path.suffix.lower()!='.zip' or not unlinked(path.parent).is_dir():
        raise ValueError('外部归档需要已有目录内的 .zip 完整路径')
    return path


def _manifest(preview):
    return {'format':1,'kind':'denghuo-reclaim-originals','expected':preview['expected'],
            'restorable_backup_set':False,'rows':preview['rows']}


def _verify_external(path, preview, contents):
    attrs = unlinked(path).stat()
    if not stat.S_ISREG(attrs.st_mode) or attrs.st_size>MAX_TOTAL+2*1048576:
        raise ValueError('外部归档不是完整的普通 ZIP 文件')
    raw = path.read_bytes()
    try:
        with ZipFile(BytesIO(raw)) as archive:
            names = archive.namelist()
            if len(names)!=len(set(names)) or set(names)!=set(contents)|{'denghuo-reclaim.json'}:
                raise ValueError('外部归档逐文件清单与预览不一致')
            index = archive.getinfo('denghuo-reclaim.json')
            if index.file_size>2*1048576 or json.loads(archive.read(index))!=_manifest(preview):
                raise ValueError('外部归档索引与预览不一致')
            for name,original in contents.items():
                info = archive.getinfo(name)
                if info.file_size!=len(original) or archive.read(info)!=original:
                    raise ValueError('外部归档原件字节不一致，不能回收')
    except (BadZipFile,KeyError,RuntimeError) as exc:
        raise ValueError('外部归档损坏，不能回收') from exc
    after = unlinked(path).stat()
    if (attrs.st_dev,attrs.st_ino,attrs.st_size,attrs.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):
        raise ValueError('外部归档在校验期间变化')
    return hashlib.sha256(raw).hexdigest()


def reclaim_export(manager, root, payload):
    with manager.lock:
        preview,contents = _reclaim_snapshot(manager,root,payload)
        if payload.get('expected')!=preview['expected']:
            raise ValueError('原件、保护或连接已变化，请重新预览')
        path = _external_archive(manager,root,payload)
        # Exclusive creation preserves every existing external file.
        with unlinked(path).open('xb') as stream:
            with ZipFile(stream,'w',ZIP_STORED) as archive:
                archive.writestr('denghuo-reclaim.json',json.dumps(_manifest(preview),ensure_ascii=True))
                for name,raw in contents.items():
                    archive.writestr(name,raw)
            stream.flush(); os.fsync(stream.fileno())
        if _reclaim_snapshot(manager,root,payload)[0]['expected']!=preview['expected']:
            raise ValueError('原件或保护在归档期间变化，请重新预览；外部归档已保留')
        checksum = _verify_external(path,preview,contents)
        return {**preview,'external_path':str(path),'archive_sha256':checksum,'verified':True,
                'message':'已重新读取真实外部路径，逐文件核验索引和所有原件字节；尚未回收'}


def reclaim_execute(manager, root, payload):
    with manager.lock:
        preview,contents = _reclaim_snapshot(manager,root,payload)
        if payload.get('expected')!=preview['expected']:
            raise ValueError('原件、清单、名称、保护或连接已变化，请重新预览；尚未回收')
        if (payload.get('confirmed') is not True or payload.get('exact_targets')!=preview['selected']
                or type(payload.get('count')) is not int or payload['count']!=preview['count']
                or payload.get('confirm')!=preview['confirm_phrase']):
            raise ValueError('请核对确切目标、数量，并填写回收确认短语')
        path = _external_archive(manager,root,payload)
        checksum = _verify_external(path,preview,contents)
        if payload.get('archive_sha256')!=checksum:
            raise ValueError('外部归档已变化，请重新外部存档并核验')
        if _reclaim_snapshot(manager,root,payload)[0]['expected']!=preview['expected']:
            raise ValueError('原件或保护在核验期间变化，请重新预览；尚未回收')
        guard_groups = _reclaim_inventory(manager,root)['groups']
        def indexes():
            return {name:manager._index_bytes(manager.scope(root)/name)
                    for name in ('history.json','restores.json','timeline.json')}
        guard_indexes = indexes()
        results,halted = [],False
        for row in preview['rows']:
            result = {'kind':row['kind'],'file':row['file'],'path':row['path'],'ok':False,
                      'released_bytes':0,'deleted_files':[],'error':''}
            if halted:
                result['error'] = '前项未完成，已停止；请重新读取剩余原件并预览'
            else:
                try:
                    if indexes()!=guard_indexes or _reclaim_inventory(manager,root)['groups']!=guard_groups:
                        raise ValueError('保护、名称或源清单在执行期间变化，停止回收')
                    if _verify_external(path,preview,contents)!=checksum:
                        raise ValueError('外部归档已变化，停止回收')
                    target = unlinked(Path(row['path']))
                    members = [(target/name if target.is_dir() else target.parent/name,entry)
                               for entry in row['files'] for name in [entry['file']]]
                    for member,entry in members:
                        attrs = unlinked(member).stat()
                        stamp = [attrs.st_dev,attrs.st_ino,attrs.st_size,attrs.st_mtime_ns,attrs.st_mode]
                        if stamp!=row['stamps'][entry['file']] or member.read_bytes()!=contents[entry['member']]:
                            raise ValueError('原件在执行期间变化，已停止；外部归档仍保留')
                    for member,entry in members:
                        if indexes()!=guard_indexes:
                            raise ValueError('保护记录在回收期间变化，已停止')
                        attrs = unlinked(member).stat()
                        if ([attrs.st_dev,attrs.st_ino,attrs.st_size,attrs.st_mtime_ns,attrs.st_mode]!=row['stamps'][entry['file']]
                                or member.read_bytes()!=contents[entry['member']]):
                            raise ValueError('原件在回收期间变化，已停止')
                        unlinked(member).unlink()
                        result['released_bytes'] += entry['bytes']
                        result['deleted_files'].append(entry['file'])
                    for name in sorted(row['directories'],key=lambda name:(name.count('/'),len(name)),reverse=True):
                        unlinked(target if name=='.' else target/name).rmdir()
                    if any(unlinked(member).exists() for member,_ in members):
                        raise ValueError('原件路径在回收期间重新出现，已停止；保持外部新增内容')
                    result['ok'] = True
                    for group in guard_groups:
                        if group['kind']==row['kind']:
                            group['rows'] = [item for item in group['rows'] if item['file']!=row['file']]
                except (OSError,ValueError) as exc:
                    # A failed target is reconstructed from the verified external originals;
                    # never overwrite a file created by somebody else during the operation.
                    result['restored_files'], result['rollback_errors'] = [], []
                    if result['deleted_files']:
                        target = Path(row['path'])
                        for name in sorted(row['directories'],key=lambda name:(name.count('/'),len(name))):
                            try:
                                unlinked(target if name=='.' else target/name).mkdir(exist_ok=True)
                            except (OSError,ValueError) as error:
                                result['rollback_errors'].append(str(error))
                        for entry in row['files']:
                            if entry['file'] not in result['deleted_files']:
                                continue
                            member = target/entry['file'] if row['directories'] else target.parent/entry['file']
                            try:
                                original = contents[entry['member']]
                                with unlinked(member).open('xb') as stream:
                                    stream.write(original); stream.flush(); os.fsync(stream.fileno())
                                if member.read_bytes()!=original:
                                    raise ValueError('失败项原件重建校验不一致')
                                stamp = row['stamps'][entry['file']]
                                os.utime(member,ns=(stamp[3],stamp[3]))
                                result['restored_files'].append(entry['file'])
                                result['released_bytes'] -= entry['bytes']
                            except (OSError,ValueError) as error:
                                result['rollback_errors'].append(entry['file']+': '+str(error))
                    result['error'] = str(exc)+'；外部归档仍保留，重试须刷新并重新预览剩余原件'
                    halted = True
            results.append(result)
        manager._storage_cache = None
        return {'results':results,'released_bytes':sum(row['released_bytes'] for row in results),
                'success_count':sum(row['ok'] for row in results),'failure_count':sum(not row['ok'] for row in results),
                'external_path':str(path),'archive_sha256':checksum,'restored':False,
                'message':'已按明确目标回收原件；外部归档保持。部分失败时已停止，结果列出实际释放字节和已回收文件。'}


def storage_inventory(manager, root):
    with manager.lock:
        if isinstance(root, BackupLibrary):
            return _storage_inventory(manager, root)
        return _reclaim_inventory(manager,root)
