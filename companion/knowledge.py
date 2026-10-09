"""Persistent local favourites, recent references and named fixed plans.

Design references: PoB named calculation sets and Ludusavi's reusable local workflows.
This persistence implementation is project-specific, not copied GUI infrastructure.
"""
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

MAX_BYTES = 1024*1024
MAX_FAVORITES, MAX_RECENT, MAX_PLANS = 64, 30, 200
KEY = re.compile(r'[a-z0-9_.\-$]{1,300}\Z')
RECORD_ID = re.compile(r'[a-f0-9]{32}\Z')


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
    if not isinstance(raw, dict) or set(raw)-{'kind','mode','snapshot_at','slot','fields'}:
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
    if 'fields' in raw:
        fields=raw['fields']
        if not isinstance(fields,dict) or len(fields)>64 or any(not isinstance(key,str) or not re.fullmatch(r'[a-z0-9_]{1,80}',key) for key in fields):
            raise ValueError('字段来源不正确')
        result['fields']={key:text(value,'字段来源',120) for key,value in fields.items()}
    return result


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

    def _read(self):
        try:
            with self.path.open('rb') as stream:
                raw = stream.read(MAX_BYTES+1)
        except FileNotFoundError:
            return {'format':1,'favorites':[],'recent':[],'plans':[]},None
        if len(raw)>MAX_BYTES:
            raise ValueError('收藏与方案库过大；原文件仍保留，请先导出或保留后重建')
        try:
            value = json.loads(raw,parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            self._validate(value)
        except (ValueError,TypeError,KeyError,AttributeError,RecursionError,OverflowError) as exc:
            raise ValueError('收藏与方案库无法读取；原文件仍保留，查资料和自动备份可以继续') from exc
        return value,hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _validate(value):
        if not isinstance(value,dict) or set(value)!={'format','favorites','recent','plans'} or type(value['format']) is not int or value['format']!=1:
            raise ValueError()
        for key,maximum in (('favorites',MAX_FAVORITES),('recent',MAX_RECENT),('plans',MAX_PLANS)):
            if not isinstance(value[key],list) or len(value[key])>maximum:
                raise ValueError()
        favorite_ids = [identity(entry) for entry in value['favorites']]
        if len(favorite_ids)!=len(set(favorite_ids)):
            raise ValueError()
        recent_ids = []
        for row in value['recent']:
            if not isinstance(row,dict) or set(row)!={'entry','opened'} or not 0<finite(row['opened'],'最近查看时间')<1e12:
                raise ValueError()
            recent_ids.append(identity(row['entry']))
        if len(recent_ids)!=len(set(recent_ids)):
            raise ValueError()
        ids = []
        for row in value['plans']:
            if (not isinstance(row,dict) or set(row)-{'note'}!={'id','name','kind','entry','params','rules_version','created','updated','origin'}
                    or not isinstance(row['id'],str) or not RECORD_ID.fullmatch(row['id'])):
                raise ValueError()
            text(row['name'],'方案名称')
            user_note(row.get('note', ''))
            text(row['rules_version'],'资料版本',80)
            if row['kind'] not in ('numeric','equipment','manual','alchemy','character') or row['kind']=='numeric' and not KEY.fullmatch(row['entry']):
                raise ValueError()
            if row['kind']!='numeric' and row['entry'] is not None:
                raise ValueError()
            if not isinstance(row['params'],dict) or len(row['params'])>64 or not row['params']:
                raise ValueError()
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
                    raise ValueError()
                for key,item in row['params'].items():
                    if key == 'character_scene':
                        from companion.character_scene import validate_scene
                        validate_scene(item)
                    elif key == 'scene_ring_slot':
                        if type(item) is not int or item not in (0,1):raise ValueError()
                    elif key == 'investment_mode':
                        if item not in ('all','min_strength'):raise ValueError()
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
                raise ValueError()
            if row['origin']!=origin(row['origin']):raise ValueError()
            if set(row['origin'].get('fields', {})) - set(row['params']):raise ValueError()
            ids.append(row['id'])
        if len(ids)!=len(set(ids)):raise ValueError()

    @staticmethod
    def record_view(row):
        raw = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        return {**copy.deepcopy(row), "note": row.get("note", ""), "record_revision": hashlib.sha256(raw).hexdigest()}

    def status(self):
        with self.lock:
            try:
                value,_ = self._read()
                return {**copy.deepcopy(value), 'plans':[self.record_view(row) for row in value['plans']], 'available':True,'error':''}
            except (OSError,ValueError) as exc:
                # Failure is visible without blocking unrelated session services.
                return {'format':1,'favorites':[],'recent':[],'plans':[], 'available':False,
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
            _,current = self._read()
            if current!=expected:
                raise ValueError('收藏与方案库刚被其他操作修改，请刷新后重试；已有记录仍保留')
            pending.replace(self.path)
            self.generation += 1
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
            _,result = canonical_plan(self.session,row['kind'],row['entry'],row['params'])
            return {'plan':self.record_view(row),'result':result,
                    'source_label':'保存的参考方案 · 固定参数，未跟随当前角色',
                    'rules_changed':row['rules_version']!=self.session.catalog.data['version']}

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
            incoming = json.loads(raw,parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
            self._validate(incoming)
        except (ValueError,TypeError,KeyError,AttributeError,RecursionError,OverflowError) as exc:
            raise ValueError('导入资料格式不正确，已有收藏与方案保持不变') from exc
        with self.lock:
            value,stamp = self._read()
            old_favorites = len(value['favorites'])
            value['favorites'] = list(dict.fromkeys([*value['favorites'],*incoming['favorites']]))
            if len(value['favorites'])>MAX_FAVORITES:
                raise ValueError('合并后收藏超过64项，请先减少收藏；已有资料保持不变')
            added,duplicated = 0,0
            for imported in incoming['plans']:
                same = next((row for row in value['plans'] if row['id']==imported['id']),None)
                if same==imported:
                    continue
                row = copy.deepcopy(imported)
                if same is not None:
                    row['id'] = uuid.uuid4().hex
                    row['name'] = text(row['name'][:74]+'（导入）','方案名称')
                    duplicated += 1
                if len(value['plans'])>=MAX_PLANS:
                    raise ValueError('合并后方案超过200项，请先减少方案；已有资料保持不变')
                value['plans'].append(row)
                added += 1
            # Imported visits never become this installation's recent usage history.
            self._write(value,stamp)
            return {'favorites_added':len(value['favorites'])-old_favorites,
                    'plans_added':added,'conflicting_plans_kept_as_copies':duplicated}

    def _recovery_bytes(self):
        with self.path.open('rb') as stream:
            raw = stream.read(16*MAX_BYTES+1)
        if len(raw)>16*MAX_BYTES:
            raise ValueError('原资料库过大，请先在助手数据目录中保留原件后处理；尚未重建')
        return raw

    def repair_preview(self):
        with self.lock:
            try:
                self._read()
            except ValueError:
                raw = self._recovery_bytes()
                return {'expected':hashlib.sha256(raw).hexdigest(), 'bytes':len(raw),
                        'message':'先保留原收藏与方案文件，再建立空资料库；游戏存档和自动备份不会改动'}
            raise ValueError('收藏与方案库可以正常读取，无需重建')

    def repair(self,expected,confirmed):
        if confirmed is not True:
            raise ValueError('请先确认保留原文件并重建收藏与方案库')
        with self.lock:
            preview = self.repair_preview()
            if expected!=preview['expected']:
                raise ValueError('原资料库刚被修改，请重新预览；尚未重建')
            raw = self._recovery_bytes()
            if hashlib.sha256(raw).hexdigest()!=expected:
                raise ValueError('原资料库刚被修改，请重新预览；尚未重建')
            preserved = self.path.with_name(self.path.stem+'.preserved-'+uuid.uuid4().hex+'.json')
            with preserved.open('xb') as stream:
                stream.write(raw)
            empty = {'format':1,'favorites':[],'recent':[],'plans':[]}
            pending = self.path.with_name(self.path.name+'.'+uuid.uuid4().hex+'.pending')
            try:
                with pending.open('xb') as stream:
                    stream.write(json.dumps(empty).encode('utf-8'))
                if hashlib.sha256(self._recovery_bytes()).hexdigest()!=expected:
                    raise ValueError('原资料库刚被修改，保留副本已建立，但尚未重建；请刷新')
                pending.replace(self.path)
                self.generation += 1
            finally:
                if pending.exists():pending.unlink()
            return {'preserved_file':preserved.name}
