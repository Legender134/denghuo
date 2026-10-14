"""Persistent local favourites, recent references and named fixed plans.

Design references: PoB named calculation sets and Ludusavi's reusable local workflows.
This persistence implementation is project-specific, not copied GUI infrastructure.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading
import time
import uuid

from .backups import unlinked

MAX_BYTES = 1024*1024
MAX_FAVORITES, MAX_RECENT, MAX_PLANS = 64, 30, 200
KEY = re.compile(r'[a-z0-9_.\-$]{1,300}\Z')
RECORD_ID = re.compile(r'[a-f0-9]{32}\Z')
HEALTHY_ID = re.compile(r'[a-f0-9]{64}\Z')
HEALTHY_GENERATIONS = 3


def library_json(raw):
    """Reject ambiguous JSON instead of guessing which duplicate value to retain."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('JSON 含重复字段，无法确定原记录')
            result[key] = value
        return result
    def number(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError('JSON 含非有限数值，无法确定原记录')
        return result
    return json.loads(raw, object_pairs_hook=pairs, parse_float=number,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('JSON 含非有限数值')))


def text(value, label, maximum=80):
    if (not isinstance(value, str) or not value.strip() or len(value)>maximum
            or any(ord(char)<32 or ord(char)==127 for char in value)):
        raise ValueError(f'{label}需要1–{maximum}个字，不能含控制字符')
    return value.strip()


def user_note(value=''):
    """Optional user assumptions, never game facts; old records may omit this field."""
    if (not isinstance(value, str) or len(value) > 1200
            or any((ord(char) < 32 and char not in '\n\r') or ord(char) == 127 for char in value)):
        raise ValueError('用途 / 假设备注最多1200个字，只能包含正文和换行')
    return value.replace('\r\n', '\n').replace('\r', '\n')


def finite(value, label):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f'{label}需要有限数值')
    return value


def identity(value):
    if not isinstance(value, str) or not KEY.fullmatch(value):
        raise ValueError('资料条目不正确')
    return value


def origin(raw=None):
    raw = {} if raw is None else raw
    if not isinstance(raw, dict) or set(raw)-{'kind','mode','snapshot_at','slot','fields','references','mixed_snapshots'}:
        raise ValueError('方案来源不正确')
    mode = raw.get('mode', 'example')
    if mode not in ('example','manual','save'):
        raise ValueError('方案来源不正确')
    at, slot = raw.get('snapshot_at'), raw.get('slot')
    if at is not None and not 0 < finite(at,'快照时间') < 1e12:
        raise ValueError('快照时间不正确')
    if slot is not None and (type(slot) is not int or slot not in range(1,7)):
        raise ValueError('方案槽位不正确')
    # Opening any plan remains a fixed reference, regardless of original mode.
    result = {'kind':'saved_reference', 'mode':mode, 'snapshot_at':at, 'slot':slot}
    if 'mixed_snapshots' in raw:
        if type(raw['mixed_snapshots']) is not bool: raise ValueError('混合保存来源标记不正确')
        result['mixed_snapshots'] = raw['mixed_snapshots']
    if 'fields' in raw:
        fields=raw['fields']
        if not isinstance(fields,dict) or len(fields)>64 or any(not isinstance(key,str) or not re.fullmatch(r'[a-z0-9_]{1,80}',key) for key in fields):
            raise ValueError('字段来源不正确')
        result['fields']={key:text(value,'字段来源',120) for key,value in fields.items()}
    if 'references' in raw:
        references = raw['references']
        if not isinstance(references, dict) or set(references) != {'a', 'b'}:
            raise ValueError('装备公开参考不完整')
        result['references'] = {}
        for side, item in references.items():
            if not isinstance(item, dict) or set(item) != {'id', 'name', 'effect_id', 'user_note'}:
                raise ValueError('装备公开参考不正确')
            note = item['user_note']
            if note is not None:
                if (not isinstance(note, dict) or set(note) != {'title', 'body', 'scope'}
                        or note['scope'] not in ('specific_item', 'item_type')):
                    raise ValueError('装备用户记录不正确')
                for key, maximum in (('title', 50), ('body', 500)):
                    if not isinstance(note[key], str) or len(note[key]) > maximum:
                        raise ValueError('装备用户记录过长')
                    user_note(note[key])
            result['references'][side] = {'id': identity(item['id']),
                'name': text(item['name'], '装备公开名称', 200),
                'effect_id': identity(item['effect_id']) if item['effect_id'] is not None else None,
                'user_note': copy.deepcopy(note)}
    return result


def validate_references(source, kind, params):
    references = source.get('references')
    if references is not None and (kind != 'equipment' or any(
            item['id'] != params.get('id_' + side) for side, item in references.items())):
        raise ValueError('装备公开参考与方案对象不匹配')


def canonical_plan(session, kind, entry, raw):
    if not isinstance(raw,dict) or len(raw)>64:
        raise ValueError('方案参数不正确')
    if kind == 'numeric':
        from companion.values import INPUTS
        identity(entry)
        if set(raw)-set(INPUTS):
            raise ValueError('方案包含此计算不支持的参数')
        for value in raw.values():
            finite(value,'计算参数')
        result = session.values.detail(entry,raw)
        if result.get('status')=='legacy' or not result['inputs']:
            raise ValueError('这个条目没有可保存的计算条件，可以收藏资料')
        keys = {field['key'] for field in result['inputs']}
        if set(raw)-keys:
            raise ValueError('方案包含此条目不使用的参数')
        return {field['key']:field['value'] for field in result['inputs']}, result
    if kind == 'equipment':
        from companion.values_decisions import compare_equipment
        from companion.values_investment import canonical_comparison
        args = canonical_comparison(session.values,raw)
        return args, compare_equipment(session.values,args)
    if kind == 'alchemy':
        from companion.alchemy import calculate
        if entry is not None:
            raise ValueError('炼金方案不使用数值条目身份')
        return calculate(session.catalog, raw)
    if kind == 'character':
        from companion.character_scene import calculate_scene
        if entry is not None:
            raise ValueError('角色条件不使用数值条目身份')
        result = calculate_scene(raw)
        return result['params'], result
    if kind == 'manual':
        from companion.service import manual_game
        from companion.engine import analyze, short_class
        keys = {'class','hp','ht','level','strength','depth','branch','healing','hunger','buffs','challenges','character_scene'}
        if set(raw)-keys:
            raise ValueError('局势草稿包含不支持的参数')
        game = manual_game(raw)
        hero = game['hero']
        buffs = [short_class(buff).rsplit('$', 1)[-1] for buff in hero['buffs'] if short_class(buff)!='Hunger']
        args = {'class':hero['class'], 'hp':hero['HP'], 'ht':hero['HT'], 'level':hero['lvl'],
                'strength':hero['STR'], 'depth':game['depth'], 'branch':game['branch'],
                'healing':sum(item['quantity'] for item in hero['inventory']),
                'hunger':raw.get('hunger'), 'buffs':buffs, 'challenges':game['challenges']}
        if "character_scene" in hero:
            args["character_scene"] = hero["character_scene"]
        # Deliberately analyze a draft; never update the current session or game files.
        return args, analyze(game,session.catalog)
    raise ValueError('不支持的方案类型')


class KnowledgeWorkspace:
    def __init__(self,path,session):
        self.path, self.session = Path(path), session
        self.lock = threading.RLock()
        self.generation = 0
        self.recovery_warning = ''
        self._protection_checked = False

    @contextmanager
    def _storage_lock(self):
        unlinked(self.path.parent).mkdir(parents=True, exist_ok=True)
        with unlinked(self.path.with_name(self.path.stem+'.lock')).open('a+b') as stream:
            try:
                stream.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ValueError('另一个窗口正在保存资料库，请稍后重试') from exc
            try:
                if stream.seek(0, 2) == 0:
                    stream.write(b'\0'); stream.flush()
                yield
            finally:
                stream.seek(0)
                if os.name == 'nt':msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _healthy_directory(self):
        return unlinked(self.path.with_name(self.path.stem+'-healthy'))

    def _healthy_bytes(self, identity):
        if not isinstance(identity, str) or not HEALTHY_ID.fullmatch(identity):
            raise ValueError('请选择清单中的健康副本')
        path = unlinked(self._healthy_directory()/(identity+'.json'))
        with path.open('rb') as stream:raw = stream.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES or hashlib.sha256(raw).hexdigest()!=identity:
            raise ValueError('健康副本字节已变化或无法核验，原件仍保留；请重新预览')
        self._validate(library_json(raw))
        return raw

    def _healthy_copies(self):
        directory = self._healthy_directory()
        if not directory.exists():return []
        rows = []
        for path in directory.glob('*.json'):
            if not HEALTHY_ID.fullmatch(path.stem):continue
            row = {'id':path.stem, 'available':False, 'error':''}
            try:
                raw = self._healthy_bytes(path.stem)
                value = library_json(raw)
                row.update(available=True, bytes=len(raw), time=path.stat().st_mtime, time_ns=path.stat().st_mtime_ns,
                           counts={key:len(value[key]) for key in ('favorites','recent','plans')})
            except (OSError,ValueError,TypeError,KeyError,AttributeError,RecursionError,OverflowError) as exc:
                row['error'] = str(exc) or '副本无法核验，原件仍保留'
            rows.append(row)
        return sorted(rows, key=lambda row:(row.get('time_ns',0),row['id']), reverse=True)

    def _retain_healthy(self, raw):
        """Called only after a successful primary commit, while holding the storage lock."""
        self._validate(library_json(raw))
        if len(raw)>MAX_BYTES:raise ValueError('健康副本超过资料库容量')
        identity = hashlib.sha256(raw).hexdigest()
        directory = self._healthy_directory(); directory.mkdir(exist_ok=True)
        target = unlinked(directory/(identity+'.json'))
        pending = unlinked(directory/(identity+'.'+uuid.uuid4().hex+'.pending'))
        try:
            if target.exists():
                if self._healthy_bytes(identity)!=raw:raise ValueError('健康副本已变化')
            else:
                with pending.open('xb') as stream:
                    stream.write(raw); stream.flush(); os.fsync(stream.fileno())
                if pending.read_bytes()!=raw:raise ValueError('健康副本写入校验失败')
                # Keep two existing healthy generations before publishing another.
                # Failed rotation must not accumulate unbounded new healthy files.
                healthy = [row for row in self._healthy_copies() if row['available']]
                for row in healthy[HEALTHY_GENERATIONS-1:]:
                    self._healthy_bytes(row['id'])
                    unlinked(directory/(row['id']+'.json')).unlink()
                pending.replace(target)
                self._healthy_bytes(identity)
            target.touch()  # Reusing A after A -> B -> A makes A the latest successful generation.
            healthy = [row for row in self._healthy_copies() if row['available'] and row['id']!=identity]
            for row in healthy[HEALTHY_GENERATIONS-1:]:
                self._healthy_bytes(row['id'])
                unlinked(directory/(row['id']+'.json')).unlink()
            self.recovery_warning = ''
        finally:
            if pending.exists():pending.unlink()

    def _checkpoint_saved(self, raw):
        try:self._retain_healthy(raw)
        except (OSError,ValueError,TypeError,KeyError,AttributeError,RecursionError,OverflowError) as exc:
            self.recovery_warning = '资料库已保存，但健康副本尚未完成：'+str(exc)+'。请检查助手数据目录；当前资料库和已有副本仍保留。'

    def ensure_protection(self):
        """Protect an existing valid library once on first use, outside Session.lock."""
        with self.lock:
            if self._protection_checked:return
            self._protection_checked = True
            try:
                _,stamp = self._read()
                if stamp is None:return
                with self._storage_lock():
                    raw = self._recovery_bytes()
                    if hashlib.sha256(raw).hexdigest()!=stamp:raise ValueError('资料库已由其他窗口修改，请重新读取')
                    self._checkpoint_saved(raw)
            except (OSError,ValueError) as exc:
                self.recovery_warning = '健康副本尚未完成：'+str(exc)

    def _read(self):
        try:
            with self.path.open('rb') as stream:
                raw = stream.read(MAX_BYTES+1)
        except FileNotFoundError:
            if self._healthy_copies():
                raise ValueError('收藏与方案库主文件缺失；现有副本仍保留，写入暂停，请在资料库预览并明确选择恢复来源') from None
            return {'format':1,'favorites':[],'recent':[],'plans':[]},None
        if len(raw)>MAX_BYTES:
            raise ValueError('收藏与方案库过大；原文件仍保留，请先导出或保留后重建')
        try:
            value = library_json(raw)
            self._validate(value)
        except (ValueError,TypeError,KeyError,AttributeError,RecursionError,OverflowError) as exc:
            raise ValueError('收藏与方案库无法读取；原文件仍保留，查资料和自动备份可以继续') from exc
        return value,hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _validate(value):
        if not isinstance(value,dict) or set(value)!={'format','favorites','recent','plans'} or type(value['format']) is not int or value['format']!=1:
            raise ValueError('资料库根字段或版本不正确')
        for key,maximum in (('favorites',MAX_FAVORITES),('recent',MAX_RECENT),('plans',MAX_PLANS)):
            if not isinstance(value[key],list) or len(value[key])>maximum:
                raise ValueError(f'{key} 需要不超过 {maximum} 条的记录列表')
        favorite_ids = [identity(entry) for entry in value['favorites']]
        if len(favorite_ids)!=len(set(favorite_ids)):
            raise ValueError('收藏身份重复冲突')
        recent_ids = []
        for row in value['recent']:
            if not isinstance(row,dict) or set(row)!={'entry','opened'} or not 0<finite(row['opened'],'最近查看时间')<1e12:
                raise ValueError('最近查看需要 entry 和有效的 opened 时间')
            recent_ids.append(identity(row['entry']))
        if len(recent_ids)!=len(set(recent_ids)):
            raise ValueError('最近查看身份重复冲突')
        ids = []
        for row in value['plans']:
            if (not isinstance(row,dict) or set(row)-{'note'}!={'id','name','kind','entry','params','rules_version','created','updated','origin'}
                    or not isinstance(row['id'],str) or not RECORD_ID.fullmatch(row['id'])):
                raise ValueError('方案必要字段不完整、含未知字段或记录 ID 不正确')
            text(row['name'],'方案名称')
            user_note(row.get('note', ''))
            text(row['rules_version'],'资料版本',80)
            if row['kind'] not in ('numeric','equipment','manual','alchemy','character') or row['kind']=='numeric' and (not isinstance(row['entry'],str) or not KEY.fullmatch(row['entry'])):
                raise ValueError('方案类型或数值条目身份不正确')
            if row['kind']!='numeric' and row['entry'] is not None:
                raise ValueError('非数值方案的 entry 必须为空')
            if not isinstance(row['params'],dict) or len(row['params'])>64 or not row['params']:
                raise ValueError('方案参数需要含 1–64 个字段的对象')
            # Type validation is independent of currently available rules: retain old plans.
            if row['kind']=='numeric':
                for key,item in row['params'].items():
                    identity(key)
                    finite(item,'方案参数')
            elif row['kind']=='equipment':
                base_keys = {'strength',*(f'{field}_{suffix}' for suffix in ('a','b') for field in ('id','level','tier','mastery','augment'))}
                planning_keys = {'planning','upgrade_budget','strength_budget'} if row['params'].get('planning') == '1' else set()
                from companion.values_investment import EXTRA_KEYS, CONTEXT_KEYS
                if not base_keys.issubset(row['params']) or set(row['params'])-base_keys-planning_keys-EXTRA_KEYS:
                    raise ValueError('装备参数缺少必要字段或含不支持字段')
                if 'combat_model' in row['params'] and (row['params']['combat_model']!='ordinary-v1' or any(
                        not isinstance(row['params'].get('id_'+side),str) or not row['params']['id_'+side].startswith('items.weapon.melee.') for side in ('a','b'))):
                    raise ValueError('普通持械近战模型仅用于普通近战武器')
                if 'target_context' in row['params'] and row['params'].get('combat_model')!='ordinary-v1':
                    raise ValueError('目标条件需要明确启用普通持械近战模型')
                for key,item in row['params'].items():
                    if key == 'combat_model':
                        continue
                    elif key == 'target_context':
                        from companion.combat_context import validate_target
                        if not isinstance(item,dict):raise ValueError('目标条件需要完整对象')
                        validate_target(item)
                    elif key == 'character_scene':
                        from companion.character_scene import validate_scene
                        validate_scene(item)
                    elif key == 'scene_ring_slot':
                        if type(item) is not int or item not in (0,1):raise ValueError()
                    elif key == 'investment_mode':
                        if item not in ('all','min_strength'):raise ValueError()
                    elif key.startswith('resin_'):
                        if type(item) is not int or not 0<=item<=3:raise ValueError()
                    elif key.startswith('infusion_'):
                        if item not in ('0','1','unknown'):raise ValueError()
                    elif key.startswith('hardened_'):
                        if item not in ('0','1'):raise ValueError()
                    elif key.startswith(('level_known_','ring_pair_')) and not key.startswith(('ring_pair_level_','ring_pair_curse_')):
                        if item not in ('0','1'):raise ValueError()
                    elif key.startswith(('curse_','ring_pair_curse_')):
                        if item not in ('0','1','unknown'):raise ValueError()
                    elif key.startswith('ring_pair_level_') or key.rsplit('_',1)[0] in CONTEXT_KEYS:
                        if type(item) is not int:raise ValueError()
                    elif key == 'planning':
                        if item != '1':raise ValueError()
                    elif key in ('upgrade_budget','strength_budget'):
                        if type(item) is not int or not 0 <= item <= (100 if key == 'upgrade_budget' else 99):raise ValueError()
                    elif key.startswith('id_'):identity(item)
                    elif key=='strength' or key.startswith(('level_','tier_')):
                        if type(item) is not int:raise ValueError()
                    elif key.startswith('mastery_'):
                        if item not in ('0','1'):raise ValueError()
                    elif item not in ('NONE','SPEED','DAMAGE','EVASION','DEFENSE'):raise ValueError()
            elif row['kind']=='character':
                from companion.character_scene import validate_scene
                validate_scene(row['params'])
            elif row['kind']=='alchemy':
                from companion.alchemy import validate_plan
                validate_plan(row['params'])
            else:
                from companion.service import manual_game
                manual_game(row['params'])
            if not 0<finite(row['created'],'创建时间')<=finite(row['updated'],'更新时间')<1e12:
                raise ValueError('方案创建、更新时间无效或顺序不正确')
            if row['origin']!=origin(row['origin']):raise ValueError('方案来源不是完整固定参考')
            if set(row['origin'].get('fields', {})) - set(row['params']):raise ValueError('方案字段来源包含未保存的参数')
            validate_references(row['origin'], row['kind'], row['params'])
            ids.append(row['id'])
        if len(ids)!=len(set(ids)):raise ValueError('方案 ID 重复冲突')

    @staticmethod
    def record_view(row):
        raw = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        return {**copy.deepcopy(row), "note": row.get("note", ""), "record_revision": hashlib.sha256(raw).hexdigest()}

    def status(self):
        with self.lock:
            try:
                value,stamp = self._read()
                try:copies = self._healthy_copies()
                except (OSError,ValueError) as exc:
                    copies = []
                    self.recovery_warning = '资料库可读取，但健康副本暂不可核对：'+str(exc)
                warning = self.recovery_warning or ('当前资料库健康副本尚未完成；已有资料仍可使用。' if stamp and not any(row['available'] and row['id']==stamp for row in copies) else '')
                return {**copy.deepcopy(value), 'plans':[self.record_view(row) for row in value['plans']], 'available':True,'error':'',
                        'recovery_warning':warning, 'healthy_copy_count':sum(row['available'] for row in copies)}
            except (OSError,ValueError) as exc:
                # Failure is visible without blocking unrelated session services.
                return {'format':1,'favorites':[],'recent':[],'plans':[], 'available':False,
                        'primary_missing':not self.path.exists(),
                        'error':str(exc) if isinstance(exc,ValueError) else '收藏与方案库暂时无法访问；原文件仍保留，请检查助手数据目录权限'}

    def _write(self,value,expected):
        self._validate(value)
        raw = json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False).encode('utf-8')
        if len(raw)>MAX_BYTES:raise ValueError('收藏与方案库已满，请减少方案后重试')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        pending = self.path.with_name(self.path.name+'.'+uuid.uuid4().hex+'.pending')
        try:
            with pending.open('xb') as stream:
                stream.write(raw)
                stream.flush()
            with self._storage_lock():
                _,current = self._read()
                if current!=expected:
                    raise ValueError('收藏与方案库刚被其他操作修改，请刷新后重试；已有记录仍保留')
                pending.replace(self.path)
                self.generation += 1
                self._checkpoint_saved(raw)
        finally:
            if pending.exists():pending.unlink()

    def remember(self,entry):
        identity(entry)
        with self.lock:
            value,stamp = self._read()
            value['recent'] = [{'entry':entry,'opened':time.time()},
                               *(row for row in value['recent'] if row['entry']!=entry)][:MAX_RECENT]
            self._write(value,stamp)

    def favorite(self,entry,enabled):
        identity(entry)
        if type(enabled) is not bool:raise ValueError('收藏开关不正确')
        with self.lock:
            value,stamp = self._read()
            entries = value['favorites']
            if enabled and entry not in entries:
                if len(entries)>=MAX_FAVORITES:raise ValueError('收藏已达64项，请先移除不需要的收藏')
                entries.append(entry)
            elif not enabled:
                value['favorites'] = [item for item in entries if item!=entry]
            else:return
            self._write(value,stamp)

    def save(self,name,kind,entry,params,source=None,record_id=None,expected_record_revision=None,note=None):
        name = text(name,'方案名称')
        if note is not None:note = user_note(note)
        canonical,result = canonical_plan(self.session,kind,entry,params)
        provenance = origin(source)
        if set(provenance.get('fields',{}))-set(canonical):
            raise ValueError('字段来源包含此方案不使用的条件')
        validate_references(provenance, kind, canonical)
        with self.lock:
            value,stamp = self._read()
            prior = next((row for row in value['plans'] if row['id']==record_id),None)
            if record_id is not None and prior is None:raise ValueError('方案已变化，请重新读取；本地草稿仍保留，可以另存副本')
            if prior is not None and expected_record_revision != self.record_view(prior)['record_revision']:
                raise ValueError('另一窗口已修改此方案；原方案和本地草稿仍保留。请重新读取最新已保存方案，或另存副本')
            if prior is None and len(value['plans'])>=MAX_PLANS:raise ValueError('方案已达200项，请先移除不需要的方案')
            now = time.time()
            row = {'id':prior['id'] if prior else uuid.uuid4().hex, 'name':name,'kind':kind,
                   'entry':entry if kind=='numeric' else None, 'params':canonical,
                   'rules_version':self.session.catalog.data['version'],
                   'created':prior['created'] if prior else now,'updated':now,'origin':provenance,
                   'note': note if note is not None else prior.get('note','') if prior else ''}
            value['plans'] = [row,*(item for item in value['plans'] if item['id']!=row['id'])]
            self._write(value,stamp)
            return self.record_view(row)

    def reopen(self,record_id):
        with self.lock:
            value,_ = self._read()
            row = next((row for row in value['plans'] if row['id']==record_id),None)
            if row is None:raise ValueError('方案已不存在，请刷新方案库')
            row = copy.deepcopy(row)
            plan = self.record_view(row)
        # Numeric calculation can acquire Session.lock; migration takes that
        # lock before this store's lock. Keep calculation outside the store.
        calculation_error = None
        try:
            _,result = canonical_plan(self.session,row['kind'],row['entry'],row['params'])
        except ValueError as exc:
            # Structural validation already succeeded. Keep unsupported old
            # inputs available for explicit correction; never
            # rewrite their historical parameters to today's canonical defaults.
            result,calculation_error = None,str(exc)
            from .public_skills import FREE_SPELLS, SPELL_PREFIX
            points = row['params'].get('talent')
            if (row['kind']=='numeric' and row['entry'] in {SPELL_PREFIX+name for name in FREE_SPELLS}
                    and type(points) in (int,float) and 1 <= points <= 4 and int(points)==points):
                try:
                    current = self.session.values.detail(row['entry'],{key:value for key,value in row['params'].items() if key!='talent'})
                    keys = {field['key'] for field in current['inputs']}
                    if current.get('status')!='legacy' and set(row['params']) <= keys | {'talent'}:
                        result,calculation_error = current,None
                        result['retained_legacy_params'] = ['talent']
                        result['notice'] += ' 旧方案的天赋点数字段完整保留；此法术不使用该字段，当前公式结果不受其影响。'
                except (ValueError,KeyError):
                    pass
        return {'plan':plan,'result':result,
                'source_label':'保存的参考方案 · 固定参数，未跟随当前角色',
                'rules_changed':row['rules_version']!=self.session.catalog.data['version'],
                **({'calculation_error':calculation_error} if calculation_error else {})}

    def remove(self,record_id,expected_record_revision=None):
        with self.lock:
            value,stamp = self._read()
            prior = next((row for row in value['plans'] if row['id']==record_id), None)
            if prior is None:raise ValueError('方案已不存在，请刷新方案库；本地草稿仍保留')
            if expected_record_revision != self.record_view(prior)['record_revision']:
                raise ValueError('另一窗口已修改此方案，旧删除确认已失效；请查看最新方案后重新确认，本地草稿仍保留')
            value['plans'] = [row for row in value['plans'] if row['id']!=record_id]
            self._write(value,stamp)

    def export(self):
        with self.lock:
            value,_ = self._read()
            return json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False).encode('utf-8')

    def import_records(self,raw):
        if not isinstance(raw,bytes) or not 0<len(raw)<=MAX_BYTES:
            raise ValueError('请选择小于1 MiB的灯火收藏与方案 JSON')
        try:
            incoming = library_json(raw)
            self._validate(incoming)
        except (ValueError,TypeError,KeyError,AttributeError,RecursionError,OverflowError) as exc:
            raise ValueError('导入资料格式不正确，已有收藏与方案保持不变') from exc
        with self.lock:
            value,stamp = self._read()
            old_favorites = len(value['favorites'])
            value['favorites'] = list(dict.fromkeys([*value['favorites'],*incoming['favorites']]))
            if len(value['favorites'])>MAX_FAVORITES:
                raise ValueError('合并后收藏超过64项，请先减少收藏；已有资料保持不变')
            added,duplicated,skipped = 0,0,0
            for imported in incoming['plans']:
                same = next((row for row in value['plans'] if row['id']==imported['id']),None)
                if same==imported:
                    skipped += 1
                    continue
                row = copy.deepcopy(imported)
                if same is not None:
                    row['name'] = text(row['name'][:74]+'（导入）','方案名称')
                    # Recognize complete imported copies even when an older import
                    # assigned a different ID, before charging another plan slot.
                    if any({**item,'id':row['id']}==row for item in value['plans']):
                        skipped += 1
                        continue
                    row['id'] = uuid.uuid4().hex
                    duplicated += 1
                if len(value['plans'])>=MAX_PLANS:
                    raise ValueError('合并后方案超过200项，请先减少方案；已有资料保持不变')
                value['plans'].append(row)
                added += 1
            # Imported visits never become this installation's recent usage history.
            self._write(value,stamp)
            return {'favorites_added':len(value['favorites'])-old_favorites,
                    'plans_added':added,'plans_skipped':skipped,'conflicting_plans_kept_as_copies':duplicated}

    def _recovery_bytes(self):
        with self.path.open('rb') as stream:
            raw = stream.read(16*MAX_BYTES+1)
        if len(raw)>16*MAX_BYTES:
            raise ValueError('原资料库过大，请先在助手数据目录中保留原件后处理；尚未重建')
        return raw

    def _recovery_candidate(self, raw):
        recovered = {'format':1,'favorites':[],'recent':[],'plans':[]}
        categories = {key:{'healthy':0,'invalid':0,'ambiguous':0,'blocked':False,'total':None}
                      for key in ('favorites','recent','plans')}
        issues = []
        root_error = ''
        try:
            if len(raw)>MAX_BYTES:
                raise ValueError('原资料库超过 1 MiB，不能按记录安全恢复')
            value = library_json(raw)
            if (not isinstance(value,dict) or set(value)!=set(recovered)
                    or type(value['format']) is not int or value['format']!=1):
                raise ValueError('根格式不是完整的第 1 版资料库，无法证明记录结构')
        except (ValueError,TypeError,RecursionError,OverflowError) as exc:
            root_error = str(exc) or 'JSON 无法完整读取，无法证明记录结构'
            for counts in categories.values():
                counts['blocked'] = True
            issues.append({'category':'library','index':None,'reason':root_error})
        else:
            for category,maximum in (('favorites',MAX_FAVORITES),('recent',MAX_RECENT),('plans',MAX_PLANS)):
                rows = value[category]
                categories[category]['total'] = len(rows) if isinstance(rows,list) else None
                if not isinstance(rows,list) or len(rows)>maximum:
                    categories[category]['blocked'] = True
                    reason = '类别需要记录列表' if not isinstance(rows,list) else f'类别超过 {maximum} 条上限，整类保留在原件，不截断恢复'
                    issues.append({'category':category,'index':None,'reason':reason})
                    continue
                identities = []
                for row in rows:
                    key = row if category=='favorites' else row.get('entry' if category=='recent' else 'id') if isinstance(row,dict) else None
                    identities.append(key if isinstance(key,str) else None)
                duplicate_ids = {key for key in identities if key is not None and identities.count(key)>1}
                for index,row in enumerate(rows):
                    key = identities[index]
                    issue = {'category':category,'index':index+1}
                    if key is not None:
                        issue['identity'] = key
                    if key in duplicate_ids:
                        categories[category]['ambiguous'] += 1
                        issues.append({**issue,'reason':'身份重复冲突；所有同身份记录均不选择，保留在原件'})
                        continue
                    single = {'format':1,'favorites':[],'recent':[],'plans':[]}
                    single[category] = [row]
                    try:
                        self._validate(single)
                    except (ValueError,TypeError,KeyError,AttributeError,RecursionError,OverflowError) as exc:
                        categories[category]['invalid'] += 1
                        issues.append({**issue,'reason':str(exc) or '记录字段、类型、范围或来源不符合资料库结构'})
                    else:
                        recovered[category].append(copy.deepcopy(row))
                        categories[category]['healthy'] += 1
        self._validate(recovered)
        count = sum(row['healthy'] for row in categories.values())
        preview = {'expected':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),
                   'mode':'recover' if count else 'empty','categories':categories,'issues':issues,
                   'healthy_count':count,'can_export':bool(count),
                   'message':f'先完整保留原文件，再恢复 {count} 条结构健康记录；损坏和冲突记录留在原件中'
                             if count else '未能证明有健康记录；先完整保留原文件，再建立空资料库',
                   'root_error':root_error}
        return preview,recovered

    def _recovery_stamp(self):
        try:return hashlib.sha256(self._recovery_bytes()).hexdigest()
        except FileNotFoundError:return 'missing'

    def _repair_candidate(self, source='current'):
        try:
            raw = self._recovery_bytes()
        except FileNotFoundError:
            raw = None
        if raw is not None:
            try:
                if len(raw)>MAX_BYTES:raise ValueError('资料库超出读取上限')
                self._validate(library_json(raw))
            except (ValueError,TypeError,KeyError,AttributeError,RecursionError,OverflowError):
                pass
            else:
                raise ValueError('收藏与方案库可以正常读取，无需恢复')
        preview,recovered = self._recovery_candidate(raw if raw is not None else b'')
        try:copies = self._healthy_copies()
        except (OSError,ValueError) as exc:
            if raw is None:raise ValueError('主文件缺失，健康副本暂不可核对；原件保留，请检查资料目录') from exc
            copies = []
            preview['copy_warning'] = '健康副本暂不可核对：'+str(exc)+'；原件保留'
        if raw is None:
            if not copies:raise ValueError('收藏与方案库可以正常读取，无需恢复')
            preview.update(expected='missing', bytes=0, primary_missing=True,
                           can_repair=not any(row['available'] for row in copies),root_error='',issues=[],
                           categories={key:{'healthy':0,'invalid':0,'ambiguous':0,'blocked':False,'total':0}
                                       for key in ('favorites','recent','plans')})
            preview['message'] = ('当前主文件缺失，请明确选择一个健康副本，重新预览后恢复；尚未建立空资料库'
                if not preview['can_repair'] else '当前主文件缺失，现有副本均无法核验；确认后建立空资料库，全部现有副本原字节仍保留')
        if source!='current':
            selected = self._healthy_bytes(source)
            selected_preview,recovered = self._recovery_candidate(selected)
            preview = {**selected_preview, 'expected':hashlib.sha256(raw).hexdigest() if raw is not None else 'missing',
                       'bytes':len(raw) if raw is not None else 0, 'primary_missing':raw is None,
                       'mode':'recover', 'can_export':True, 'can_repair':True,
                       'message':(('当前主文件缺失，现有健康副本仍保留；' if raw is None else '先完整保留当前损坏原件，再')+
                                  f"从所选健康副本恢复 {selected_preview['healthy_count']} 条记录")}
        preview.update(source=source, healthy_copies=copies)
        return raw,preview,recovered

    def repair_preview(self, source='current'):
        with self.lock:
            return self._repair_candidate(source)[1]

    @staticmethod
    def _recovery_document(value):
        raw = json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False).encode('utf-8')
        if len(raw)>MAX_BYTES:
            # Pretty formatting must not make an otherwise bounded subset unusable.
            raw = json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
        if len(raw)>MAX_BYTES:
            raise ValueError('健康记录仍超过资料库容量；原文件未替换，不能截断恢复')
        return raw

    def repair_export(self, expected, source='current'):
        with self.lock:
            _,preview,recovered = self._repair_candidate(source)
            if expected!=preview['expected']:
                raise ValueError('原资料库刚被修改，请重新预览；尚未导出')
            if not preview['can_export']:
                raise ValueError('没有可证明健康的记录可以导出；现有原件与副本不会改动')
            raw = self._recovery_document(recovered)
            if self._recovery_stamp()!=expected:
                raise ValueError('原资料库刚被修改，请重新预览；尚未导出')
            if source!='current' and library_json(self._healthy_bytes(source))!=recovered:
                raise ValueError('所选健康副本已变化，尚未导出')
            return raw

    def repair(self,expected,confirmed,source='current'):
        if confirmed is not True:
            raise ValueError('请先核对恢复预览并明确确认；尚未恢复资料库')
        with self.lock, self._storage_lock():
            raw,preview,recovered = self._repair_candidate(source)
            if expected!=preview['expected']:
                raise ValueError('原资料库刚被修改，请重新预览；尚未重建')
            if self._recovery_stamp()!=expected:
                raise ValueError('原资料库刚被修改，请重新预览；尚未重建')
            if preview.get('can_repair') is False:
                raise ValueError('主文件缺失，请先选择一个健康副本并重新预览；尚未建立空资料库')
            recovered_raw = self._recovery_document(recovered)
            preserved = None
            if raw is not None:
                preserved = self.path.with_name(self.path.stem+'.preserved-'+uuid.uuid4().hex+'.json')
                with preserved.open('xb') as stream:
                    stream.write(raw)
                    stream.flush()
                if preserved.read_bytes()!=raw:
                    raise ValueError('原件保留副本校验失败；尚未恢复资料库')
            pending = self.path.with_name(self.path.name+'.'+uuid.uuid4().hex+'.pending')
            try:
                with pending.open('xb') as stream:
                    stream.write(recovered_raw)
                    stream.flush()
                staged = pending.read_bytes()
                if len(staged)>MAX_BYTES or library_json(staged)!=recovered:
                    raise ValueError('恢复资料库校验失败；原文件未替换')
                self._validate(library_json(staged))
                if self._recovery_stamp()!=expected:
                    raise ValueError('原资料库刚被修改'+('，保留副本已建立' if preserved is not None else '')+'，尚未恢复；请刷新后重新预览')
                if source!='current' and library_json(self._healthy_bytes(source))!=recovered:
                    raise ValueError('所选健康副本已变化，尚未恢复')
                if raw is None:
                    # Publish only if absent: a non-cooperating writer must not be overwritten.
                    try:os.link(pending,self.path)
                    except FileExistsError:
                        raise ValueError('主文件已重新出现，未覆盖；请重新预览') from None
                else:
                    pending.replace(self.path)
                self.generation += 1
                self._checkpoint_saved(recovered_raw)
            finally:
                if pending.exists():pending.unlink()
            return {'preserved_file':preserved.name if preserved is not None else None,
                    'primary_missing':raw is None,'mode':preview['mode'],'source':source,
                    'recovered_count':preview['healthy_count'],'categories':preview['categories']}
