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

    def process_exit(self):
        try:
            while True:
                state = self.exit_events.get_nowait()
                self.exit_state = state
                phase = state['phase']
                if phase == 'confirming':
                    self.frozen = True
                    self.report_drafts()
                    self.host.command('exit_request', state=state)
                elif phase in ('cancelled', 'idle'):
                    self.frozen = False
                    self.host.command('exit_cancelled')
                elif phase == 'finished':
                    self.host.command('exit_finished', state=state)
        except Empty:
            pass
        current = self.session.exit_status()
        if self.frozen and current['phase'] in ('cancelled', 'idle'):
            self.frozen = False
            self.host.command('exit_cancelled')

    def exit_decision(self, item):
        state = self.session.exit_status()
        if state['phase'] != 'confirming':
            return
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
            self.host.command('exit_request', state=state)
            return
        self.session.acknowledge_exit(state['id'], 'native', decision, self.revision)
        if decision == 'cancel':
            self.frozen = False
            self.host.command('exit_cancelled')

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
                self.host.command('drafts', rows=self.session.list_exit_drafts())
            elif action == 'load_draft':
                self.restore_draft(self.session.load_exit_draft(item['id']))
            self.report_drafts()
            self.update(self.session.snapshot(), force=True)
        except (ValueError, KeyError, OSError, RuntimeError) as exc:
            if action == 'exit_decision':
                self.host.command('exit_save_error', message=str(exc), state=self.session.exit_status())
                logging.exception('Native exit draft save failed; retaining the original draft')
            else:
                self.error(str(exc))

    def restore_draft(self, saved):
        kind = saved['draft_kind']
        if kind == 'numeric':
            self.manager.open_lookup()
            lookup = self.lookup()
            lookup.guard('载入未完成草稿', lambda: lookup.restore_draft(saved['draft']))
        elif kind == 'play-settings':
            self.manager.open_play_settings()
            settings = self.manager.play_settings
            if settings.has_draft():
                self.error('当前游玩设置已有草稿；请先保存或重新读取后再载入副本。')
            else:
                settings.restore_draft(saved['draft'])
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
        state = {'text': '\n\n'.join(filter(None, texts)), 'slot': 0 if snap['settings']['slot'] == 'auto' else snap['settings']['slot'],
            'topmost': snap['settings']['always_on_top'], 'references': reference_texts,
            'capabilities': registration, 'error': self.manager.action_error}
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
