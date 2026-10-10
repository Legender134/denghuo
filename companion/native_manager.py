"""Accessible native manager and one exit participant for all helper windows."""
from __future__ import annotations

import json
import logging
import os
from queue import Queue, Empty
import time

from .native_host import NativeHost


class NativeManager:
    def __init__(self, manager):
        self.manager, self.session = manager, manager.session
        self.exit_events, self.exit_state = Queue(maxsize=32), None
        self.revision, self.reported = 0, None
        self.frozen, self.signature, self.references = False, None, []
        self.host = NativeHost(manager.root, self.dispatch, self.error)
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
                    label = '数值速查未完成草稿' if kind == 'numeric' else '游玩设置未完成草稿'
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
                **({'play-settings': settings.draft()} if settings and settings.has_draft() else {})}

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
        error = state.get('error') or result.get('error')
        if error or result.get('ok') is False:
            message = error or '最后备份未完成；已有备份与活动存档原件仍保留。'
            if slots:
                message += ' 已完成的槽位：' + slots + '。'
        elif result.get('ok') is True and result.get('state') == 'captured' and slots:
            message = '最后备份已完成：' + slots + '。'
        elif result.get('ok') is True and result.get('state') == 'no-save':
            message = '本次没有游戏存档需要备份。'
        elif result.get('ok') is True and result.get('state') == 'paused':
            message = '自动备份已暂停，本次结束未执行最后备份。'
        else:
            message = '最后备份结果尚未确认，请在下次启动核对退出回执。'
        if result.get('receipt_error'):
            message += ' ' + result['receipt_error']
        return '本次辅助已结束。' + message + ' 明确保存的未完成草稿可在下次启动后找回。'

    def process_exit(self):
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
                elif phase == 'finished':
                    self.host.command('exit_finished', state=state, message=self.finished_exit_message(state))
        except Empty:
            pass
        current = self.session.exit_status()
        if self.frozen and current['phase'] in ('cancelled', 'idle'):
            self.frozen = False
            self.host.command('exit_cancelled', request_id=current['id'])

    def exit_decision(self, item):
        # Keep request validation and raw capture atomic with web cancel/restart.
        with self.session.exit_coordinator.lock:
            state = self.session.exit_status()
            if state['phase'] != 'confirming' or item.get('request_id') != state['id']:
                return
            self._exit_decision(item, state)

    def _exit_decision(self, item, state):
        self.frozen = True
        # The helper flushes its newest raw controls before showing the exit dialog.
        if item.get('lookup') and self.lookup():
            self.lookup().handle({'action': 'edit', **item['lookup']})
        if item.get('settings'):
            self.manager.open_play_settings(show=False)
            self.manager.play_settings.handle({'action': 'settings_edit', **item['settings']})
        decision = item.get('decision')
        if decision == 'saved':
            lookup, settings = self.lookup(), self.manager.play_settings
            if lookup and lookup.has_draft():
                lookup.save_draft_copy()
            if settings and settings.has_draft():
                settings.save_draft_copy()
        self.report_drafts()
        if decision == 'clean' and self.drafts():
            self.host.command('exit_save_error', state=state, message='当前窗口仍有未保存草稿，请重新确认。')
            return
        self.session.acknowledge_exit(state['id'], 'native', decision, self.revision)
        if decision == 'cancel':
            self.frozen = False
            self.host.command('exit_cancelled', request_id=state['id'])

    def dispatch(self, item):
        action = item.get('action')
        try:
            if action == 'ready':
                self.update(self.session.snapshot(), force=True)
            elif action == 'visibility':
                surface = item.get('surface')
                hwnd = item.get('hwnd')
                if self.host.process and hwnd and self.manager.play and self.manager.play.native.process(hwnd) == self.host.process.pid:
                    self.host.handles[surface] = hwnd
                    self.host.visibility[surface] = bool(item.get('visible'))
            elif action == 'exit_decision':
                self.exit_decision(item)
            elif self.frozen:
                return
            elif action == 'exit':
                self.request_exit()
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
                self.manager.safely(lambda: self.session.update_settings({'slot': slot if slot else 'auto', 'mode': 'save'}))
            elif action == 'directory' and item.get('path'):
                self.manager.safely(lambda: self.session.update_settings({'save_root': item['path'], 'mode': 'save', 'slot': 'auto'}))
            elif action == 'pin_manager':
                self.manager.safely(lambda: self.session.update_settings({'always_on_top': bool(item.get('checked'))}))
            elif action == 'refresh':
                self.manager.refresh()
            elif action == 'capture':
                self.manager.commands.put(('capture', None))
            elif action == 'reference':
                index = item.get('index', -1)
                if type(index) is int and 0 <= index < len(self.references):
                    row, source, note = self.references[index]
                    self.manager.open_reference(row, source, note)
            elif action == 'list_drafts':
                include_archived = item.get('include_archived', False)
                self.host.command('drafts', rows=self.draft_rows(include_archived), include_archived=include_archived)
            elif action == 'load_draft':
                self.restore_draft(self.session.load_exit_draft(item['id']), item.get('component'))
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
                    row['components'] = [key for key in ('numeric', 'play-settings')
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
            if component not in ('numeric', 'play-settings') or not isinstance(draft.get(component), dict):
                raise ValueError('请在草稿列表选择此离线副本中的数值或游玩设置表单；原件仍保留。')
            kind, draft = component, draft[component]
        elif component is not None:
            raise ValueError('此副本不含所选原生表单；原件仍保留。')
        if kind == 'numeric':
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
        texts = [self.manager.status.cget('text'), self.manager.backup_status.cget('text'),
                 self.manager.hero.cget('text'), self.manager.metrics.cget('text')]
        texts += [tip['title']+'\n'+tip['body'] for tip in data.get('tips', [])]
        references, reference_texts = [], []
        try:
            decisions = self.session.decisions(snap)
            for risk in decisions['risks']:
                for row in risk['references']:
                    references.append((row, None, ''))
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
        state = {'text': '\n\n'.join(filter(None, texts)), 'slot': 0 if snap['settings']['slot'] == 'auto' else snap['settings']['slot'],
            'topmost': snap['settings']['always_on_top'], 'references': reference_texts,
            'capabilities': registration, 'error': '\n'.join(filter(None, [self.manager.action_error] +
                [row.get('recovery_error', '') for row in snap.get('exit', {}).get('participants', [])
                 if row['surface_id'] == 'native']))}
        if self.exit_state and self.exit_state.get('phase') == 'finished':
            state['error'] = self.finished_exit_message(self.exit_state)
        signature = json.dumps(state, ensure_ascii=False, sort_keys=True)
        if force or signature != self.signature:
            self.signature = signature
            self.host.command('manager_state', **state)
        if self.manager.play_settings:
            self.manager.play_settings.emit()
        self.report_drafts()

    def show(self):
        self.host.command('show', surface='manager')

    def hide(self):
        self.host.command('hide' if self.manager.tray is not None else 'minimize_manager', surface='manager')

    def close(self):
        if self.session.exit_status()['phase'] not in ('backing-up', 'finished'):
            self.report_drafts()
            self.session.unregister_exit_surface('native', self.revision, bool(self.drafts()), draft=self.drafts())
        self.host.close()
