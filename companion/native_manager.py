"""Accessible native manager and one exit participant for all helper windows."""
from __future__ import annotations

import json
import copy
import logging
import os
from queue import Queue, Empty, Full
import threading
import time

from .native_host import NativeHost, binding_token


class NativeManager:
    def __init__(self, manager):
        self.manager, self.session = manager, manager.session
        self.exit_events, self.exit_state = Queue(maxsize=32), None
        self.revision, self.reported = 0, None
        self.frozen, self.signature, self.references = False, None, []
        from .window_layout import WindowLayout
        self.layout = WindowLayout(self.session.config_path)
        self.host = NativeHost(manager.root, self.dispatch, self.error)
        from .game_workspace import GameWorkspace
        self.workspace = GameWorkspace(self)
        self.host.idle = self.process_io
        self.session.register_exit_surface('native', kind='native', label='桌面速查与游玩设置', notify=self.notify_exit)
        self.report_drafts()

    def notify_exit(self, state):
        # Called by HTTP/final-capture threads: never touch a control here.
        self.exit_events.put(state, timeout=.5)

    def error(self, message):
        process = getattr(self.host, 'process', None)
        failed = getattr(self.host, 'failed', False)
        if (failed or not process or process.poll() is not None) and not getattr(self, 'disconnected', False):
            self.disconnected = True
            draft = self.drafts()
            try:
                for kind, raw in draft.items():
                    label = {'numeric': '数值速查未完成草稿', 'play-settings': '游玩设置未完成草稿', 'game-workspace': '游戏工作区未完成草稿'}[kind]
                    self.session.save_exit_draft('native', kind, label, raw)
                if draft:
                    message += '\n原始草稿副本已保存；重新启动后可从管理窗口显式载入。'
                self.session.unregister_exit_surface('native', self.revision, bool(draft), draft=draft)
            except (ValueError, OSError, RuntimeError) as exc:
                message += '\n草稿副本尚未保存：'+str(exc)+'；本次会话原始输入仍保留。'
        self.manager.action_error, self.manager.action_error_until = message, time.monotonic()+30
        if process and process.poll() is None and not failed and not self.host.outgoing.full():
            self.host.command('error', message=message)
        elif os.name == 'nt':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, '灯火 · 原生窗口不可用', 0x30)
        logging.error('Native controls unavailable: %s', message)

    def lookup(self):
        return self.manager.play.lookup if self.manager.play else None

    def drafts(self):
        lookup, settings = self.lookup(), self.manager.play_settings
        return {**({'numeric': lookup.draft()} if lookup and lookup.has_draft() else {}),
                **({'play-settings': settings.draft()} if settings and settings.has_draft() else {}),
                **({'game-workspace': self.workspace.drafts()} if getattr(self, 'workspace', None) and self.workspace.drafts() else {})}

    def report_drafts(self):
        if getattr(self, 'disconnected', False):
            return
        if self.session.exit_status()['phase'] in ('backing-up', 'finished'):
            return
        draft = self.drafts()
        fingerprint = json.dumps(draft, ensure_ascii=False, sort_keys=True)
        if fingerprint != self.reported:
            self.revision += 1
            self.reported = fingerprint
        self.session.report_exit_surface('native', self.revision, bool(draft), draft=draft, kind='native')

    def request_exit(self, reason='桌面窗口请求退出'):
        self.report_drafts()
        self.session.request_exit('native', reason)

    @staticmethod
    def finished_exit_message(state):
        result = state.get('backup_result') or {}
        completed = [row for row in result.get('captured', [])
                     if isinstance(row, dict) and type(row.get('slot')) is int and 1 <= row['slot'] <= 6
                     and isinstance(row.get('id'), str) and len(row['id']) == 64
                     and all(char in '0123456789abcdef' for char in row['id'])]
        slots = '、'.join(f"槽位 {row['slot']}（{row['id'][:12]}）" for row in completed)
        global_result = result.get('global_progress') or {}
        global_id = global_result.get('snapshot_id')
        names = global_result.get('files')
        valid_global = (isinstance(global_id, str) and len(global_id) == 64
                        and all(char in '0123456789abcdef' for char in global_id)
                        and isinstance(names, list) and bool(names)
                        and all(name in ('badges.dat', 'rankings.dat') for name in names)
                        and global_result.get('raw_retained') is True)
        global_completed = valid_global and global_result.get('state') == 'protected' and global_result.get('protected') is True
        global_label = ('全局进度：' + '、'.join('成就' if name == 'badges.dat' else '排行' for name in names)
                        + '（' + global_id[:12] + '）') if valid_global else ''
        completed_text = '、'.join(part for part in (slots, global_label if global_completed else '') if part)
        error = state.get('error') or result.get('error')
        if error or result.get('ok') is False:
            message = error or '最后备份未完成；已有备份与活动存档原件仍保留。'
            if completed_text:
                message += ' 已完成的备份：' + completed_text + '。'
        elif result.get('ok') is True and result.get('state') == 'captured' and completed_text:
            message = '最后备份已完成：' + completed_text + '。'
        elif result.get('ok') is True and result.get('state') == 'no-save':
            message = '本次没有游戏存档需要备份。'
        elif result.get('ok') is True and result.get('state') == 'paused':
            message = '自动备份已暂停，本次结束未执行最后备份。'
        else:
            message = '最后备份结果尚未确认，请在下次启动核对退出回执。'
        if valid_global and not global_completed:
            message += ' 已保留原始副本：' + global_label + '；内容可恢复性尚未确认。'
        if result.get('receipt_error'):
            message += ' ' + result['receipt_error']
        return '本次辅助已结束。' + message + ' 明确保存的未完成草稿可在下次启动后找回。'

    def process_exit(self):
        self._process_exit_copies()
        try:
            while True:
                state = self.exit_events.get_nowait()
                current = self.session.exit_status()
                if state['id'] != current['id'] or state['phase'] != current['phase']:
                    continue  # A delayed start callback cannot revive a cancelled request.
                previous = self.exit_state
                self.exit_state = state
                phase = state['phase']
                if phase == 'confirming':
                    if self.frozen and previous and previous['id'] != state['id']:
                        self.host.command('exit_cancelled', request_id=previous['id'])
                    self.frozen = True
                    self.report_drafts()
                    self.host.command('exit_request', state=state)
                elif phase in ('cancelled', 'idle'):
                    self.frozen = False
                    self.host.command('exit_cancelled', request_id=state['id'])
                elif phase == 'backing-up':
                    self.host.command('exit_waiting', state=state, can_cancel=False,
                                      message='草稿确认完成，正在保留最后备份与退出回执。')
                elif phase == 'finished':
                    self.host.command('exit_finished', state=state, message=self.finished_exit_message(state))
        except Empty:
            pass
        current = self.session.exit_status()
        if self.frozen and current['phase'] in ('cancelled', 'idle'):
            self.frozen = False
            self.host.command('exit_cancelled', request_id=current['id'])

    def exit_decision(self, item):
        # Only capture controls here. Persistence never owns this lock or the UI.
        with self.session.exit_coordinator.lock:
            state = self.session.exit_status()
            if state['phase'] != 'confirming' or item.get('request_id') != state['id']:
                return
            captured = self._exit_decision(item, state)
        if captured is None:
            return
        if captured['decision'] == 'cancel':
            self.session.acknowledge_exit(state['id'], 'native', 'cancel', captured['revision'])
            self.frozen = False
            self.host.command('exit_cancelled', request_id=state['id'])
            return
        self._queue_exit_copy(captured)

    def _exit_decision(self, item, state):
        self.frozen = True
        # The helper flushes its newest raw controls before showing the exit dialog.
        if item.get('lookup') and self.lookup():
            self.lookup().handle({'action': 'edit', **item['lookup']})
        if item.get('settings'):
            self.manager.open_play_settings(show=False)
            self.manager.play_settings.handle({'action': 'settings_edit', **item['settings']})
        if item.get('game') and getattr(self, 'workspace', None):
            if not isinstance(item['game'], dict): raise ValueError('工作区退出草稿格式无效；原始输入仍保留')
            for page, values in item['game'].items(): self.workspace.edit(page, values)
        decision = item.get('decision')
        if decision not in ('clean', 'saved', 'discard', 'cancel'):
            raise ValueError('退出选择无效；原始草稿仍保留。')
        self.report_drafts()
        drafts = self.drafts()
        if decision == 'clean' and drafts:
            self.host.command('exit_save_error', state=state, message='当前窗口仍有未保存草稿，请重新确认。')
            return None
        copies = []
        if decision == 'saved':
            lookup, settings = self.lookup(), self.manager.play_settings
            if lookup and lookup.has_draft():
                copies.append(lookup.exit_copy_payload())
            if settings and settings.has_draft():
                copies.append({'kind': 'settings-raw', 'draft': settings.draft()})
            if getattr(self, 'workspace', None) and self.workspace.drafts():
                copies.append({'kind': 'game-raw', 'draft': self.workspace.drafts()})
        return {'request_id': state['id'], 'decision': decision, 'revision': self.revision,
                'fingerprint': json.dumps(drafts, ensure_ascii=False, sort_keys=True),
                'copies': copy.deepcopy(copies)}

    def _ensure_exit_copies(self):
        if hasattr(self, '_exit_copy_queue'):
            return
        self._exit_copy_queue = Queue(maxsize=1)
        self._exit_copy_results = Queue(maxsize=2)
        self._exit_copy_jobs = []
        self._exit_copy_stop = threading.Event()
        self._exit_copy_thread = threading.Thread(target=self._persist_exit_copies,
            daemon=True, name='native-exit-copies')
        self._exit_copy_thread.start()

    def _queue_exit_copy(self, captured):
        self._ensure_exit_copies()
        if any(job['request_id'] == captured['request_id'] for job in self._exit_copy_jobs):
            return
        if len(self._exit_copy_jobs) >= 2:
            raise RuntimeError('之前的草稿副本仍在等待磁盘；当前输入仍保留，可取消后继续编辑，稍后重试。')
        captured['done'] = threading.Event()
        self._exit_copy_jobs.append(captured)
        try:
            self._exit_copy_queue.put_nowait(captured)
        except Full:
            self._exit_copy_jobs.remove(captured)
            raise RuntimeError('草稿保存队列暂时繁忙；原始输入仍保留，可取消退出。')
        current = self.session.exit_status()
        if current['id'] == captured['request_id'] and current['phase'] in ('confirming', 'backing-up'):
            self.host.command('exit_waiting', state=current, can_cancel=current['phase'] == 'confirming',
                message='正在保存草稿副本或确认放弃；磁盘等待期间仍可取消退出。'
                if current['phase'] == 'confirming' else '草稿确认完成，正在保留最后备份与退出回执。')

    def _persist_exit_copies(self):
        while not self._exit_copy_stop.is_set():
            try:
                job = self._exit_copy_queue.get(timeout=.2)
            except Empty:
                continue
            try:
                current = self.session.exit_status()
                if current['id'] != job['request_id'] or current['phase'] != 'confirming':
                    continue
                for payload in job['copies']:
                    if payload['kind'] == 'plan':
                        self.session.knowledge.save(**payload['payload'])
                    else:
                        kind, label = {'settings-raw': ('play-settings', '游玩设置未完成草稿'),
                            'raw': ('numeric', '数值速查未完成草稿'), 'game-raw': ('game-workspace', '游戏工作区未完成草稿')}[payload['kind']]
                        self.session.save_exit_draft('native', kind, label, payload['draft'])
                job['result'] = self.session.acknowledge_exit(job['request_id'], 'native',
                    job['decision'], job['revision'])
            except (ValueError, KeyError, OSError, RuntimeError) as exc:
                job['error'] = str(exc)
                current = self.session.exit_status()
                if current['id'] == job['request_id'] and current['phase'] == 'confirming':
                    logging.exception('Native exit copy not acknowledged; original inputs retained')
                else:
                    logging.info('Retained native exit copy completion for superseded request')
            finally:
                self._exit_copy_results.put(job)
                job['done'].set()

    def _process_exit_copies(self):
        if not hasattr(self, '_exit_copy_results'):
            return
        while True:
            try:
                job = self._exit_copy_results.get_nowait()
            except Empty:
                return
            self._exit_copy_jobs.remove(job)
            current = self.session.exit_status()
            if (current['id'] != job['request_id'] or current['phase'] not in ('confirming', 'backing-up')
                    or self.revision != job['revision']
                    or json.dumps(self.drafts(), ensure_ascii=False, sort_keys=True) != job['fingerprint']):
                continue
            if job.get('error'):
                self.host.command('exit_save_error', state=current, message=job['error'])
            elif job.get('result'):
                self.host.command('exit_waiting', state=current, can_cancel=current['phase'] == 'confirming',
                    message='本窗口草稿已确认，正在等待其他窗口。' if current['phase'] == 'confirming'
                    else '草稿确认完成，正在保留最后备份与退出回执。')

    @property
    def io_busy(self):
        return getattr(self, '_io_job', None) is not None

    def queue_io(self, label, work, finish=None):
        """Capture on the UI thread; run only disk/service work in one bounded worker."""
        if self.io_busy:
            self.manager.action_error = '上一项磁盘操作仍在等待；当前输入仍保留，请完成后重试。'
            self.manager.action_error_until = time.monotonic()+10
            return False
        if not hasattr(self, '_io_queue'):
            self._io_queue, self._io_results = Queue(maxsize=1), Queue(maxsize=1)
            self._io_stop = threading.Event()
            self._io_thread = threading.Thread(target=self._persist_io, daemon=True, name='native-disk-actions')
            self._io_thread.start()
        job = {'label': label, 'work': work, 'finish': finish, 'done': threading.Event()}
        self._io_job = job
        self._io_queue.put_nowait(job)
        return True

    def check_io_current(self):
        stop = getattr(self, '_io_stop', None)
        if (stop is not None and stop.is_set()
                or self.session.stop.is_set() or self.session._shutdown_requested.is_set()):
            raise ValueError('助手正在结束，尚未应用本次磁盘操作；原始输入仍保留。')

    def _persist_io(self):
        while not self._io_stop.is_set():
            try:
                job = self._io_queue.get(timeout=.2)
            except Empty:
                continue
            try:
                self.check_io_current()
                job['result'] = job['work']()
            except Exception as exc:
                job['error'] = str(exc) or '磁盘操作未完成；原始输入仍保留。'
                logging.exception('Native disk action did not complete: %s', job['label'])
            finally:
                self._io_results.put_nowait(job)
                job['done'].set()

    def process_io(self):
        if not self.io_busy or self.frozen:
            return
        try:
            job = self._io_results.get_nowait()
        except Empty:
            return
        self._io_job = None
        if (self._io_stop.is_set() or self.session.stop.is_set()
                or self.session._shutdown_requested.is_set()):
            return  # Late completion never reopens controls or replaces a draft at shutdown.
        try:
            if job['finish']:
                job['finish'](job.get('result'), job.get('error'))
            else:
                self.manager.action_error = job.get('error', '')
                self.manager.action_error_until = time.monotonic()+15
        except Exception as exc:
            logging.exception('Native disk completion could not be displayed')
            self.manager.action_error = str(exc) or '磁盘操作回执未能显示；当前草稿仍保留。'
            self.manager.action_error_until = time.monotonic()+15
        self.update(self.session.snapshot(), force=True)

    def change_connection(self, patch):
        revision = self.session.snapshot()['settings_revision']
        submitted = copy.deepcopy(patch)
        return self.queue_io('正在保存连接设置', lambda: self.session.update_settings(
            submitted, expected_revision=revision))

    def change_preferences(self, patch, finish=None):
        preferences = self.manager.play.preferences
        generation = preferences.published()['revision']
        submitted = copy.deepcopy(patch)
        def complete(receipt, error):
            self.manager.action_error = error or ''
            self.manager.action_error_until = time.monotonic()+15
            if not error:
                self.manager.apply_play_settings()
                if finish:
                    finish()
        return self.queue_io('正在保存游玩显示设置', lambda: preferences.update(submitted,
            expected_generation=generation, check_current=self.check_io_current), complete)

    @staticmethod
    def floor_token(snap):
        return binding_token([snap.get(key) for key in ('started','settings_revision','revision','active_slot','run_id','error')]
            + [snap.get('settings',{}).get(key) for key in ('save_root','mode')])

    def floor_state(self, snap):
        from .floor_guide import floor_encounters
        data = snap.get('data') or {}
        token = self.floor_token(snap)
        available = bool(type(data.get('depth')) is int and not snap.get('error') and snap['settings']['mode']=='save')
        hidden = getattr(self, '_floor_hidden', None)
        if not hidden or hidden['token']!=token:
            hidden = None
            self._floor_hidden = None
        owner=binding_token([snap.get(k) for k in ('started','active_slot','run_id')]+
            [snap.get('settings',{}).get(k) for k in ('save_root','mode')]+[data.get(k) for k in ('depth','branch','version','challenges_mask','challenges_known')])
        result = {'token':token,'owner':owner,'enabled':available and not self.io_busy,'revealed':bool(hidden),
                  'caption':'连接有效存档后显示本层资料。','nodes':[]}
        self._floor_item_references = {}
        if not available: return result
        result['caption']=f"第 {data['depth']} 层"+(f" · 支线 {data['branch']}" if data.get('branch') else '')+' · 最近存档，非实时视野'
        hero=data.get('hero',{})
        result['caption']+=f"\n生命 {hero.get('hp','未确认')} / {hero.get('ht','未确认')} · 等级 {hero.get('level','未确认')}"
        key = binding_token([data.get(k) for k in ('depth','branch','version','challenges_mask','challenges_known')]+[data.get('hero',{}).get('level')])
        if key!=getattr(self,'_floor_public_key',None):
            guide = floor_encounters({'depth':data['depth'],'branch':data.get('branch',0),'version':data.get('version'),
                'challenges':data.get('challenges_mask') if data.get('challenges_known') else None},self.session.catalog)
            rows=[];groups={}
            self._floor_reference_rows={r.get('reference_key',r['id']):r for r in guide['rows']}
            def leaf(identity,text,detail=''): return {'id':identity,'text':text,'detail':detail or text}
            hero = data.get('hero',{}).get('level')
            hero = hero if type(hero) is int and 1<=hero<=30 else 1
            for row in guide['rows']:
                detail=self.session.values.detail(row['id'],{'depth':row.get('reference_depth',data['depth']),'hero_level':hero,'loot_count':0,**row.get('reference_params',{})})
                calculation_params=[f"{field['label']}：{field['value']}" for field in detail['inputs']
                                    if field['key'] not in ('depth','hero_level','loot_count','wealth_bonus','stronger_bosses')]
                blocks=[]
                for i,block in enumerate(detail['blocks']):
                    children=[]
                    for j,value in enumerate(block.get('values',[])):
                        title=f"{value['label']}：{value['value']} {value.get('unit','')}".strip()
                        children.append(leaf(f'v-{i}-{j}',title,'\n'.join(filter(None,[title,value.get('condition')]))))
                    for j,cells in enumerate(block.get('rows',[])):
                        text=' · '.join(str(c) for c in cells[:3])
                        full='\n'.join(f'{label}：{cell}' for label,cell in zip(block['columns'],cells))
                        children.append(leaf(f'r-{i}-{j}',text,full))
                    if block['title']=='特殊攻击与机制' and calculation_params:
                        description='本次参考参数 · '+'；'.join(calculation_params)
                        children.insert(0,leaf('reference-params',description,description+'\n这些是可在完整资料调整的示例条件，未读取敌人的当前状态。'))
                    blocks.append({'id':'b-'+str(i),'text':block['title'],'detail':block.get('note',''),'children':children})
                name=row['name']+('' if row['group']=='普通轮换' else ' · '+row['group'])
                node={'id':row.get('reference_key',row['id']),'text':f"{name} · 生命 {row['hp']} · 普攻 {row['damage']} · 减伤 {row['dr']}",
                    'detail':row['condition']+f'\n本层条件参考；角色等级 {hero}；累计成功掉落示例0次。实际财富、掉落次数、临时状态另查完整数值。',
                    'children':blocks}
                group=row.get('fold_group')
                if group:
                    if group not in groups:
                        groups[group]={'id':'group-'+group,'text':group,'children':[]}
                        rows.append(groups[group])
                    groups[group]['children'].append(node)
                else: rows.append(node)
            for group in groups.values(): group['text']+=f" · {len(group['children'])} 种"
            self._floor_public_key,self._floor_public_nodes=key,{'id':'monsters','text':f"本层可能出现的怪物 · {len(guide['rows'])} 种",
                'detail':guide['note'],'children':rows,'expanded':True}
        contents=[]
        if hidden:
            floor=hidden['result']
            for row in floor['features']:
                if row['hidden'] and row['terrain']==16:
                    contents.append({'id':'door-'+str(row['pos']),'text':f"({row['x']}, {row['y']}) {row['name']}"})
            for row in floor['traps']:
                if not row['visible']:
                    contents.append({'id':'trap-'+str(row['pos']),'text':f"({row['x']}, {row['y']}) {row['name']}"})
            for kind in ('heaps','mobs'):
                entries=[]
                for i,row in enumerate(floor[kind]):
                    children=[]
                    for item in row['items']:
                        identity='item-'+item['instance_key']
                        self._floor_item_references[identity]=(item,floor)
                        children.append({'id':identity,'text':f"{item['name']} ×{item['quantity']}"+(' · 诅咒' if item.get('cursed') is True else ''),
                                         'detail':item['description']+'\n'+item.get('location','')+'\n已主动揭示；游戏鉴定状态未改变，未加入背包。可查看所选资料数值。'})
                    caption=f"{row['name']} ({row['x']}, {row['y']})"
                    if kind=='mobs':
                        caption+=' · '+('保存生命未确认' if row.get('hp') is None else f"保存生命 {row['hp']}")
                        if row.get('ht') is not None:caption+=f" / {row['ht']}"
                    entries.append({'id':f'{kind}-{i}','text':caption,'detail':floor['note'],'children':children})
                if entries:
                    label='地上物品与容器' if kind=='heaps' else '本层已保存生物'
                    contents.append({'id':'hidden-'+kind,'text':f'{label} · {len(entries)} 处',
                        'detail':floor['note'],'children':entries})
        result['nodes']=[{'id':'hidden','text':'本层隐藏内容 · '+('已主动揭示' if hidden else '尚未揭示'),
            'detail':hidden['result']['note'] if hidden else '点击“揭示本层隐藏内容”后只读查看；保存快照更新后自动收起。',
            'children':contents,'expanded':bool(hidden)},self._floor_public_nodes]
        return result

    def reveal_floor(self, item):
        from .scouting import inspect_saved
        snap=self.session.snapshot();token=self.floor_token(snap)
        if item.get('token')!=token: raise ValueError('本层存档已更新，请核对后重新揭示。')
        if getattr(self,'_floor_hidden',None) and self._floor_hidden['token']==token:
            self._floor_hidden=None
            return
        def work():
            if self.floor_token(self.session.snapshot())!=token: raise ValueError('本层连接已变化，尚未揭示。')
            catalog=inspect_saved(self.session,{'action':'catalog'});source=catalog['source']
            data=snap.get('data') or {}
            if (source['depth'],source['branch'])!=(data.get('depth'),data.get('branch',0)):
                raise ValueError('角色正在换层，请等待保存完成后刷新。')
            return inspect_saved(self.session,{'action':'floor','depth':source['depth'],'branch':source['branch'],
                'expected':source['expected'],'reveal':True})
        def complete(result,error):
            if token!=self.floor_token(self.session.snapshot()): return
            self.manager.action_error=error or ''
            self.manager.action_error_until=time.monotonic()+20
            if not error: self._floor_hidden={'token':token,'result':result}
        self.queue_io('正在只读揭示本层隐藏内容',work,complete)

    def dispatch(self, item):
        action = item.get('action')
        try:
            if action == 'ready':
                self.host.command('window_layout', layout=self.layout.values, restored=self.layout.original is not None)
                if self.layout.values['page'] in ('inventory', 'equipment', 'alchemy', 'character', 'map', 'backups'):
                    self.workspace.handle({'action': 'game_page', 'page': self.layout.values['page']})
                self.update(self.session.snapshot(), force=True)
            elif action in ('window_layout', 'layout_reset'):
                self.layout.update(item['layout'], reset=action == 'layout_reset')
            elif action == 'collapse':
                play = self.manager.play
                target = play.native.remembered_game() if play else None
                if target and self.host.process:
                    from .native_focus import return_to_game
                    return_to_game(play.native, target, self.host.process.pid)
                self.host.command('collapse')
            elif action == 'visibility':
                surface = item.get('surface')
                hwnd = item.get('hwnd')
                if self.host.process and hwnd and self.manager.play and self.manager.play.native.process(hwnd) == self.host.process.pid:
                    self.host.handles[surface] = hwnd
                    self.host.visibility[surface] = bool(item.get('visible'))
                    if surface == 'manager':
                        self.companion_collapsed = item.get('collapsed') is True
            elif action == 'exit_decision':
                self.exit_decision(item)
            elif self.frozen:
                return
            elif action == 'exit':
                self.request_exit()
            elif action in ('game_page', 'game_action', 'game_edit', 'game_select'):
                self.workspace.handle(item)
            elif item.get('surface') == 'lookup':
                if self.lookup() is None:
                    self.manager.open_lookup()
                self.lookup().handle(item)
            elif item.get('surface') == 'settings':
                self.manager.open_play_settings(show=False)
                self.manager.play_settings.handle(item)
            elif action == 'show_lookup':
                self.manager.open_lookup()
            elif action == 'show_settings':
                self.manager.open_play_settings()
            elif action == 'panel':
                self.manager.open_panel(item.get('page', 'overview'))
            elif action == 'slot':
                slot = item.get('index', 0)
                self.change_connection({'slot': slot if slot else 'auto', 'mode': 'save'})
            elif action == 'directory' and item.get('path'):
                self.change_connection({'save_root': item['path'], 'mode': 'save', 'slot': 'auto'})
            elif action == 'pin_manager':
                self.change_connection({'always_on_top': bool(item.get('checked'))})
            elif action == 'refresh':
                self.queue_io('正在读取存档', self.session.refresh)
            elif action == 'reveal_floor':
                self.reveal_floor(item)
            elif action == 'floor_reference':
                snap=self.session.snapshot()
                if item.get('token')!=self.floor_token(snap): raise ValueError('楼层参考已更新，请重新选择。')
                identity=item.get('id')
                self.floor_state(snap)
                rows=getattr(self,'_floor_reference_rows',{}) if snap.get('data') and not snap.get('error') and snap['settings']['mode']=='save' else {}
                if identity not in rows:
                    raise ValueError('请从本层可能出现的怪物选择。')
                hero=snap['data'].get('hero',{}).get('level')
                hero=hero if type(hero) is int and 1<=hero<=30 else 1
                from .native_workspace import NumericLookup
                selected=rows[identity]
                name=selected['name']
                row={'entry':selected['id'],'source':{'mode':snap['settings']['mode']},
                    'stamp':NumericLookup.source_stamp(snap),
                    'source_label':name+' · 本层敌人条件参考 · 角色等级来自所选存档；掉落次数为0次示例',
                    'params':{'depth':selected.get('reference_depth',snap['data']['depth']),'hero_level':hero,'loot_count':0,**selected.get('reference_params',{})},
                    'conditions':selected['condition']+'；累计成功掉落示例0次，未读取本局计数或敌人临时状态。',
                    'field_origins':{}}
                if 'reference_depth' in selected:
                    row['field_origins']['depth']='召唤规则固定等效层数，非当前楼层'
                for field in ('stronger_bosses', 'no_herbalism'):
                    if field in selected.get('reference_params',{}):
                        row['field_origins'][field]='所选存档已保存的挑战条件' if snap['data'].get('challenges_known') else '挑战未知，按普通难度假设'
                self.manager.open_reference(row,None,'')
            elif action == 'floor_item_reference':
                snap=self.session.snapshot()
                if item.get('token')!=self.floor_token(snap):raise ValueError('楼层保存已更新，请重新主动揭示后选择物品。')
                self.floor_state(snap)
                selected=self._floor_item_references.get(item.get('id'))
                if not selected:raise ValueError('请先主动揭示本层，再选择其中的物品；尚未打开数值。')
                selected,floor=selected
                params={}
                for source,target in (('level','level'),('tier','tier'),('volume','dew_volume')):
                    if selected.get(source) is not None:params[target]=selected[source]
                source=floor['source']
                label=f"槽位 {source['slot']} · 第 {floor['depth']} 层"+(f" / 支线 {floor['branch']}" if floor['branch'] else '')+' · 已主动揭示的楼层物品'
                from .native_workspace import plan_updated_text
                label+=' · '+plan_updated_text(source['floor_modified'])
                conditions='楼层保存参考；游戏鉴定状态未改变，未加入背包。未合并当前角色、装备或临时状态。'
                if source['version']!=922:conditions+=' 数值手册按4.0.2参考，请核对版本差异。'
                reference={'entry':selected['key'],'params':params,'source':{'mode':'example'},
                    'source_label':selected['name']+' · '+label,'conditions':conditions,
                    'level_origin':'not_applicable' if selected.get('level_applicable') is False else 'unknown' if selected.get('level') is None else 'revealed',
                    'field_origins':{key:label for key in params}}
                self.manager.open_reference(reference,None,'')
            elif action == 'capture':
                self.manager.commands.put(('capture', None))
            elif action == 'reference':
                index = item.get('index', -1)
                if (type(index) is not int or not 0 <= index < len(self.references)
                        or item.get('token') != binding_token(self.references[index])):
                    raise ValueError('参考列表已更新，请核对后重新选择；当前草稿仍保留。')
                row, source, note = self.references[index]
                self.manager.open_reference(row, source, note)
            elif action == 'list_drafts':
                include_archived = item.get('include_archived', False)
                self.host.command('drafts', rows=self.draft_rows(include_archived), include_archived=include_archived)
            elif action == 'load_draft':
                self.restore_draft(self.session.load_exit_draft(item['id']), item.get('component'))
            elif action == 'preserve_raw_draft':
                self.session.exit_recovery.preserve_raw(item['id'], item.get('expected_revision'), item.get('confirmed'))
                self.host.command('drafts', rows=self.draft_rows(item.get('include_archived', False)),
                                  include_archived=item.get('include_archived', False))
            elif action == 'inspect_raw_draft':
                value, _ = self.session.exit_recovery.original(item['id'], item.get('expected_revision'))
                self.host.command('raw_draft', original=value)
            elif action == 'draft_state':
                self.session.set_exit_draft_lifecycle(item['id'], item.get('state'), item.get('expected_revision'))
                self.host.command('drafts', rows=self.draft_rows(item.get('include_archived', False)),
                                  include_archived=item.get('include_archived', False))
            self.report_drafts()
            self.update(self.session.snapshot(), force=True)
        except (ValueError, KeyError, OSError, RuntimeError) as exc:
            if action == 'exit_decision':
                state = self.session.exit_status()
                if state['phase'] == 'confirming' and item.get('request_id') == state['id']:
                    self.host.command('exit_save_error', message=str(exc), state=state)
                logging.exception('Native exit draft save failed; retaining the original draft')
            else:
                self.error(str(exc))

    def draft_rows(self, include_archived=False):
        rows = self.session.list_exit_drafts(include_archived=include_archived)
        for row in rows:
            if row.get('draft_kind') == 'offline-native' and not row.get('error'):
                try:
                    draft = self.session.load_exit_draft(row['id'])['draft']
                    row['components'] = [key for key in ('numeric', 'play-settings', 'game-workspace')
                                         if isinstance(draft.get(key), dict)]
                    if not row['components']:
                        row['error'] = '副本没有当前版本支持的原生表单；原件仍保留。'
                except (ValueError, OSError) as exc:
                    row['error'] = str(exc)
        return rows

    def restore_draft(self, saved, component=None):
        kind = saved['draft_kind']
        draft = saved['draft']
        if kind == 'offline-native':
            if component not in ('numeric', 'play-settings', 'game-workspace') or not isinstance(draft.get(component), dict):
                raise ValueError('请在草稿列表选择此离线副本中的数值或游玩设置表单；原件仍保留。')
            kind, draft = component, draft[component]
        elif component is not None:
            raise ValueError('此副本不含所选原生表单；原件仍保留。')
        if kind == 'game-workspace':
            if self.workspace.drafts(): raise ValueError('当前工作区已有未保存输入；请先命名保存或保留退出副本，再载入其他草稿')
            self.workspace.restore_draft(draft)
            self.workspace.page = next(iter(draft), 'equipment')
            self.workspace.emit()
            self.host.command('game_show', page=self.workspace.page)
        elif kind == 'numeric':
            self.manager.open_lookup()
            lookup = self.lookup()
            lookup.guard('载入未完成草稿', lambda: lookup.restore_draft(draft))
        elif kind == 'play-settings':
            self.manager.open_play_settings()
            settings = self.manager.play_settings
            if settings.has_draft():
                self.error('当前游玩设置已有草稿；请先保存或重新读取后再载入副本。')
            else:
                settings.restore_draft(draft)
        else:
            raise ValueError('此草稿属于完整面板，请在完整面板中载入；尚未应用。')

    def update(self, snap, force=False):
        self.process_exit()
        data = snap.get('data') or {}
        hero = data.get('hero', {})
        backup = snap.get('backup_health', {})
        texts = []
        global_health = backup.get('global_progress', {})
        global_labels = {'protected': '成就与排行榜最近文件已备份', 'warning': '全局进度结构不支持，原始字节已保留',
            'blocked': '全局历史新增受阻', 'paused': '全局自动历史已暂停', 'waiting': '等待游戏产生全局进度',
            'working': '正在核对全局历史', 'unknown': '全局历史尚未确认'}
        if global_health and global_health.get('state') not in ('waiting', 'working', 'unknown'):
            global_label = global_labels.get(global_health.get('state'), '全局历史尚未确认')
            if global_health.get('state') == 'protected' and len(global_health.get('files', {})) == 1:
                global_label = ('成就记录已备份' if 'badges.dat' in global_health['files'] else '排行榜与每日记录已备份')
            texts.append(global_label
                + ('：'+global_health['error'] if global_health.get('error') else ''))
        for buff in data.get('buffs', []):
            if buff.get('reference_id') == 'actors.buffs.healing':
                source = '手动局势' if snap['settings']['mode'] == 'manual' else '最近保存'
                remaining = f"剩余治疗 {buff['left']}" if type(buff.get('left')) is int else '治疗条件不完整'
                next_heal = buff.get('next_heal')
                if type(next_heal) is int:
                    actual = min(next_heal, max(0, hero.get('ht', 0) - hero.get('hp', 0)))
                    remaining += f'；按该局势下一次可回 {actual} 生命'
                texts.append(f"{buff['name']} · {source}：{remaining}")
        texts += [tip['title']+'\n'+tip['body'] for tip in data.get('tips', [])]
        references, reference_texts = [], []
        try:
            decisions = self.session.decisions(snap)
            for risk in decisions['risks']:
                for row in risk['references']:
                    references.append((row, row.get('source'), ''))
                    reference_texts.append(risk['title']+' · '+row['name']+'资料')
            for row in decisions['options']:
                note = '\n'.join(filter(None, (row['restriction'], row['calculation_missing'], row['note'])))
                texts.append(row['name']+f" ×{row['quantity']} · "+decisions['source']['label']+'\n'+note)
                references.append((row, row['source'], note))
                reference_texts.append(row['purpose']+'（参考参数）')
        except (ValueError, KeyError, OSError):
            logging.exception('Native manager references unavailable')
        self.references = references
        caps = snap.get('ui_capabilities', self.session.ui_capabilities)
        registration = '全局快捷键：'+('已完成注册' if caps.get('hotkeys_ready') else '尚未完成注册')
        if caps.get('hotkeys_unavailable'):
            registration += '\n被占用或未生效：'+', '.join(caps['hotkeys_unavailable'])
        registration += '\n托盘：'+('可用' if caps.get('tray_available') else '不可用；可用快捷键重新显示管理窗口')
        registration += '\n'+caps.get('error', '')
        if snap.get('error'):
            texts.append('存档读取完整原因：'+snap['error'])
        if backup.get('error'):
            texts.append('自动备份完整原因：'+backup['error'])
        if snap.get('draft_recovery_notice'):
            texts.append(snap['draft_recovery_notice'])
        protection = {'protected': '保存已备份', 'blocked': '备份受阻', 'paused': '备份暂停'}.get(backup.get('state'),
            '上次保存已备份' if backup.get('last_save_protected') else '等待保存')
        source_text = ('手填局势' if snap['settings']['mode'] == 'manual' else '旧快照 · 请先保存游戏' if snap.get('stale') else '存档快照')
        source_text += f" · 槽位 {snap.get('active_slot') or '?'}"
        source_text += ' · ' + protection
        state = {'text': '\n\n'.join(filter(None, texts)), 'source': source_text,
            'life': f"{hero.get('hp', '?')} / {hero.get('ht', '?')}  生命" if hero else '等待有效存档',
            'statistics': f"{hero.get('class', '')} Lv.{hero.get('level', '?')} · 第 {data.get('depth', '?')} 层\n基础力量 {hero.get('strength', '?')} · 金币 {data.get('gold', '?')}",
            'slot': 0 if snap['settings']['slot'] == 'auto' else snap['settings']['slot'],
            'floor_guide': self.floor_state(snap),
            'io_busy': self.io_busy,
            'topmost': snap['settings']['always_on_top'], 'references': reference_texts,
            'reference_tokens': [binding_token(row) for row in references],
            'capabilities': registration, 'error': '\n'.join(filter(None, [
                self._io_job['label']+'；磁盘等待期间仍可退出或取消。' if self.io_busy else '', self.manager.action_error,
                getattr(getattr(self, 'layout', None), 'error', '')] +
                [row.get('recovery_error', '') for row in snap.get('exit', {}).get('participants', [])
                 if row['surface_id'] == 'native']))}
        if self.exit_state and self.exit_state.get('phase') == 'finished':
            state['error'] = self.finished_exit_message(self.exit_state)
        signature = json.dumps(state, ensure_ascii=False, sort_keys=True)
        if force or signature != self.signature:
            self.signature = signature
            self.host.command('manager_state', **state)
        workspace = getattr(self, 'workspace', None)
        if workspace and workspace.page == 'inventory':
            current = binding_token([snap.get('started'), snap.get('revision'), snap.get('settings_revision'), snap.get('error')])
            if current != getattr(self, '_inventory_revision', None):
                self._inventory_revision = current
                workspace.emit('inventory')
        if self.manager.play_settings:
            self.manager.play_settings.emit()
        self.report_drafts()

    def show(self):
        self.host.command('show', surface='manager')

    def track_game(self, game, visible):
        rect = list(game['rect']) if game else []
        key = (tuple(rect), bool(visible))
        if key != getattr(self, '_game_window_state', None):
            self._game_window_state = key
            self.host.command('game_bounds', rect=rect, visible=bool(visible))

    def hide(self):
        self.host.command('hide' if self.manager.tray is not None else 'minimize_manager', surface='manager')

    def close(self):
        if hasattr(self, 'layout'):
            self.layout.close()
        if hasattr(self, '_io_stop'):
            self._io_stop.set()
        if self.session.exit_status()['phase'] not in ('backing-up', 'finished'):
            self.report_drafts()
            self.session.unregister_exit_surface('native', self.revision, bool(self.drafts()), draft=self.drafts())
        self.host.close()
        if hasattr(self, '_exit_copy_stop'):
            self._exit_copy_stop.set()
