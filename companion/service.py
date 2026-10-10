"""Local session state and a read-only save polling service."""

from __future__ import annotations

import copy
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import json
import hashlib
import logging
from pathlib import Path
from queue import Queue
import threading
import time
import uuid
from types import SimpleNamespace

from .engine import Catalog, CLASSES, analyze, number
from .saves import SaveError, default_root, list_slots, read_slot
from .rules import NumericRules
from .paths import ROOT, data_directory

CST = timezone(timedelta(hours=8))
DEFAULTS = {"save_root": str(default_root()), "slot": "auto", "mode": "save", "reveal": False,
            "always_on_top": False, "stop_at": "", "startup_surface": "panel", "backup_root": ""}


class SettingsConflict(ValueError):
    """The saved connection changed after a browser form was loaded."""


def validate_settings(patch, *, require_existing_root=True):
    if not isinstance(patch, dict) or set(patch) - set(DEFAULTS):
        raise ValueError("包含不支持的设置")
    clean = {}
    for key, value in patch.items():
        if key == "backup_root":
            from .backup_destination import normalize_root
            clean[key] = normalize_root(value)
        elif key == "save_root":
            if not isinstance(value, str) or not value.strip() or len(value) > 1000:
                raise ValueError("请输入存档目录")
            path = Path(value.strip()).expanduser()
            standard = path.resolve() == Path(DEFAULTS['save_root']).resolve()
            if require_existing_root and not path.is_dir() and (not standard or path.exists()):
                raise ValueError("存档目录不存在")
            if path.name.startswith("game") and (path / "game.dat").exists():
                path = path.parent
            clean[key] = str(path.resolve())
        elif key == "slot":
            if value != "auto" and (type(value) is not int or value not in range(1, 7)):
                raise ValueError("槽位必须是自动或 1–6")
            clean[key] = value
        elif key == "mode":
            if value not in ("save", "manual"):
                raise ValueError("不支持的模式")
            clean[key] = value
        elif key == "startup_surface":
            if value not in ("panel", "native"):
                raise ValueError("请选择完整面板或桌面窗口作为启动入口")
            clean[key] = value
        elif key in ("reveal", "always_on_top"):
            if not isinstance(value, bool):
                raise ValueError("开关值必须是布尔值")
            clean[key] = value
        elif key == "stop_at":
            if not isinstance(value, str):
                raise ValueError("截止时间格式不正确")
            if value:
                try:
                    parsed = datetime.fromisoformat(value)
                except ValueError as exc:
                    raise ValueError("截止时间格式不正确") from exc
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=CST)
                value = parsed.astimezone(CST).isoformat()
            clean[key] = value
    return clean


def manual_game(payload):
    if not isinstance(payload, dict):
        raise ValueError("局势必须是一个对象")
    values = {}
    for key, default, lower, upper in (("hp", 20, 0, 10000), ("ht", 20, 1, 10000),
                                       ("level", 1, 1, 100), ("strength", 10, 1, 1000),
                                       ("depth", 1, 1, 26), ("branch", 0, 0, 1),
                                       ("healing", 0, 0, 99)):
        value = payload.get(key, default)
        if type(value) is not int or not lower <= value <= upper:
            raise ValueError(f"{key} 需要是 {lower}–{upper} 的整数")
        values[key] = value
    hunger = payload.get("hunger")
    if hunger is not None and (type(hunger) is not int or not 0 <= hunger <= 450):
        raise ValueError("饱食状态需要是未知或 0–450 的整数")
    if values["hp"] > values["ht"]:
        raise ValueError("当前生命不能大于最大生命")
    hero_class = payload.get("class", "WARRIOR")
    if hero_class not in CLASSES:
        raise ValueError("请选择角色职业")
    buffs = payload.get("buffs", [])
    allowed = {"Burning", "Ooze", "Corrosion", "Poison", "Bleeding", "Cripple", "Roots", "Paralysis",
               "Frost", "MagicalSleep", "TimeStasis", "Levitation", "Berserk", "DeferedDamage", "LostInventory"}
    if not isinstance(buffs, list) or any(not isinstance(b, str) or b not in allowed for b in buffs):
        raise ValueError("状态列表不正确")
    challenges = payload.get("challenges", 0)
    if type(challenges) is not int or not 0 <= challenges <= 511:
        raise ValueError("挑战选项不正确")
    prefix = "com.shatteredpixel.shatteredpixeldungeon."
    statuses = []
    for kind in dict.fromkeys(buffs):
        relative = "items.armor.glyphs.Viscosity$DeferedDamage" if kind == "DeferedDamage" else "actors.buffs." + kind
        statuses.append({"__className": prefix + relative, **({"state": "BERSERK"} if kind == "Berserk" else {})})
    character = payload.get("character_scene")
    if character is not None:
        from .character_scene import validate_scene
        character = validate_scene(character)
        if character["base_strength"] != values["strength"]:
            raise ValueError("局势基础力量与共享角色条件不一致，请重新核对")
    return {"depth": values["depth"], "branch": values["branch"], "challenges": challenges, "PotionOfHealing_known": True,
            "hero": {"class": hero_class, "lvl": values["level"], "HP": values["hp"], "HT": values["ht"],
                     "STR": values["strength"], **({"character_scene": character} if character is not None else {}), "buffs": statuses
                     + ([{"__className": prefix + "actors.buffs.Hunger", "level": hunger}] if hunger is not None else []),
                     "inventory": ([{"__className": prefix + "items.potions.PotionOfHealing", "quantity": values["healing"], "kept_lost": True}]
                                   if values["healing"] else [])}}


class Session:
    def __init__(self, config_path=None, catalog=None):
        self.catalog = catalog or Catalog()
        self._rules = None
        self._knowledge = None
        self._play_preferences = None
        self.config_path = config_path or data_directory() / 'settings.json'
        self.lock = threading.RLock()
        # Long operations share this gate; published state never waits on it.
        self._backup_io_lock = threading.RLock()
        self._backup_busy = 0
        self._backup_health_cache = None
        self._refresh_serial = 0
        self._refresh_pending = False
        self._shutdown_requested = threading.Event()
        self.stop = threading.Event()
        self._shutdown_lock = threading.RLock()
        self._shutdown_done = threading.Event()
        self._shutdown_thread = None
        self._shutdown_deadline = None
        self._shutdown_result = None
        self._shutdown_capture_result = None
        self._shutdown_backup_result = None
        self._shutdown_receipt_thread = None
        self._shutdown_receipt_done = threading.Event()
        self._shutdown_receipt_error = ''
        self._shutdown_captured = []
        self._backup_shutdown_started = False
        self._consumed_stop_at = None
        from .session_exit import ExitCoordinator, ExitDraftStore, ExitRecoveryJournal
        self.exit_drafts = ExitDraftStore(self.config_path.parent / 'exit-drafts')
        self.exit_recovery = ExitRecoveryJournal(self.config_path.parent / 'exit-recovery', self.exit_drafts)
        self.exit_coordinator = ExitCoordinator(self.prepare_shutdown, self.save_exit_draft,
            on_finished=self._exit_finished, checkpoint=self.exit_recovery.checkpoint)
        self.settings = dict(DEFAULTS)
        self.settings_revision = uuid.uuid4().hex
        self.config_error = ""
        self.configuration_notice = ""
        try:
            count = len(self.exit_recovery.list())
            self.draft_recovery_notice = (f'找到 {count} 份之前或其他会话自动保留的未完成输入；'
                '请从未完成草稿列表核对、明确载入或归档。' if count else '')
        except (ValueError, OSError):
            self.draft_recovery_notice = '自动保留的草稿暂时无法读取，原件仍保留；请在未完成草稿列表核对。'
        try:
            receipt_path = self.config_path.parent / 'last-exit.json'
            with receipt_path.open('rb') as stream:
                receipt_raw = stream.read(32769)
            if len(receipt_raw) > 32768:
                raise ValueError('退出记录过大')
            receipt = json.loads(receipt_raw)
            if receipt.get('format') == 1 and receipt.get('backup', {}).get('ok') is False:
                self.configuration_notice = '上次结束时的最后一次备份未完成。已有备份与活动存档原件仍保留；请检查存档历史和备份状态。'
        except FileNotFoundError:
            pass
        except (OSError, ValueError, AttributeError, RecursionError):
            logging.warning('Last exit record could not be read; original retained')
        try:
            with (self.config_path.parent / 'migration.json').open('rb') as stream:
                migration_raw = stream.read(262145)
            if len(migration_raw) > 262144:
                raise ValueError('迁移记录过大')
            migration_report = json.loads(migration_raw)
            if not isinstance(migration_report, dict):
                raise ValueError('迁移记录格式不正确')
            unavailable = migration_report.get('unavailable_exit_drafts')
            if isinstance(unavailable, list) and unavailable:
                notice = '旧版有未完成草稿格式或版本不兼容，未计为可用迁移；原始副本已单独保留，请在旧版核对。'
                self.configuration_notice = ' '.join(filter(None, (self.configuration_notice, notice)))
            recovery_unavailable = migration_report.get('unavailable_exit_recovery')
            preserved_unavailable = migration_report.get('unavailable_preserved_recovery')
            if isinstance(recovery_unavailable, list) and recovery_unavailable:
                notice = '旧版有自动恢复原件无法核对；有界原始文件已复制到未完成草稿列表，可核对后明确保留归档；尚未载入或应用。'
                self.configuration_notice = ' '.join(filter(None, (self.configuration_notice, notice)))
            if isinstance(preserved_unavailable, list) and preserved_unavailable:
                notice = '旧版有已保留原始文件无法核对或配对不全；有界副本保存在 exit-recovery-preserved-unavailable，具体位置、字节数和摘要见迁移记录；尚未载入或应用。'
                self.configuration_notice = ' '.join(filter(None, (self.configuration_notice, notice)))
            if migration_report.get('source_recognition') == 'bounded-recovery-originals':
                notice = '旧版仅发现有界待核对原始文件，未发现可用的已验证草稿；本次只复制保留原件，未载入、计算或应用。'
                self.configuration_notice = ' '.join(filter(None, (self.configuration_notice, notice)))
        except FileNotFoundError:
            pass
        except (OSError, ValueError, RecursionError):
            logging.warning('Migration report could not be read; original retained')
            notice = '旧版迁移记录暂时无法读取，原件仍保留；请核对未完成草稿是否已带入。'
            self.configuration_notice = ' '.join(filter(None, (self.configuration_notice, notice)))
        try:
            # An offline/moved saved directory must never select another run.
            with self.config_path.open("rb") as stream:
                raw = stream.read(65537)
            if len(raw) > 65536:
                raise ValueError("设置文件过大")
            self.settings.update(validate_settings(json.loads(raw.decode("utf-8-sig")), require_existing_root=False))
        except FileNotFoundError:
            pass
        except (OSError, ValueError, RecursionError):
            self.config_error = "助手设置无法读取，已暂停自动读档。请在「连接设置」中确认存档目录和槽位后保存；原配置会先备份。"
        # Manual input belongs to one session; there is nothing to resume after exit.
        self.settings["mode"] = "save"
        # A previously finished session must not immediately close the next launch.
        if self.settings["stop_at"] and datetime.fromisoformat(self.settings["stop_at"]).timestamp() <= time.time():
            self.settings["stop_at"] = ""
        # Remember every observed root even after changing mode or selected slot.
        self._observed_progress_roots = set()
        self.data = None
        self.slots = []
        self.error = ""
        self.waiting_for_save = False
        self.warning = ""
        self.modified = 0
        self.active_slot = None
        self.last_valid_time = 0
        self._missing_active_since = None
        self.revision = 0
        self._fingerprint = None
        self._manual = None
        self._manual_modified = 0
        self._run_identity = None
        self._run_generation = 0
        self._run_duration = None
        self._history_state = None
        self.history = []
        self.start_time = time.time()
        from .backup_destination import manager_for
        self.backups = manager_for(self.config_path, self.settings['backup_root'])
        self.backup_context = uuid.uuid4().hex
        from .panel import PanelBridge
        self.panel = PanelBridge()
        self.manager_commands = Queue()
        self.manager_available = False
        self.ui_capabilities = {}
        self.log_path = self.config_path.parent / 'companion.log'

    def register_exit_surface(self, surface_id, *, kind='native', label='', notify=None):
        return self.exit_coordinator.register(surface_id, kind=kind, label=label, notify=notify)

    def report_exit_surface(self, surface_id, revision, dirty, *, draft=None, label=None, kind=None):
        if kind is None:
            kind = 'native' if surface_id.startswith('native') else 'web'
        return self.exit_coordinator.report(surface_id, revision, dirty, draft=draft, label=label, kind=kind)

    def request_exit(self, surface_id='native', reason='结束本次辅助'):
        return self.exit_coordinator.start(surface_id, reason)

    def acknowledge_exit(self, request_id, surface_id, decision, revision):
        return self.exit_coordinator.acknowledge(request_id, surface_id, decision, revision)

    def unregister_exit_surface(self, surface_id, revision, dirty, *, draft=None):
        return self.exit_coordinator.unregister(surface_id, revision, dirty, draft=draft)

    def exit_status(self):
        return self.exit_coordinator.status()

    def save_exit_draft(self, surface_id, kind, label, draft):
        return self.exit_drafts.save(surface_id, kind, label, draft)

    def list_exit_drafts(self, include_archived=False):
        rows = self.exit_drafts.list(include_archived=include_archived) + self.exit_recovery.list()
        if include_archived:
            rows += self.exit_recovery.list_preserved()
        count = sum(bool(row.get('recovery')) for row in rows)
        self.draft_recovery_notice = (f'找到 {count} 份之前或其他会话自动保留的未完成输入；'
            '请从未完成草稿列表核对、明确载入或归档。' if count else '')
        return sorted(rows, key=lambda row: row['saved'], reverse=True)

    def load_exit_draft(self, identity):
        if isinstance(identity, str) and identity.startswith('raw-'):
            raise ValueError('这是仅保留字节的原始文件，不能载入为表单；请核对或获取原始文件')
        if self.exit_recovery.contains(identity):
            return self.exit_recovery.load(identity)
        return self.exit_drafts.load(identity)

    def set_exit_draft_lifecycle(self, identity, state, expected_revision):
        if isinstance(identity, str) and identity.startswith('raw-'):
            raise ValueError('仅保留字节的原始文件不能恢复为表单；请核对或获取原始文件')
        if self.exit_recovery.contains(identity):
            if state != 'archived':
                raise ValueError('自动保留副本尚未归档；可明确载入或归档保留原始内容')
            return self.exit_recovery.archive(identity, expected_revision)
        return self.exit_drafts.set_lifecycle(identity, state, expected_revision)

    def exit_action(self, payload):
        if not isinstance(payload, dict):
            raise ValueError('退出请求格式不正确')
        action, surface = payload.get('action'), payload.get('surface_id')
        if action == 'report':
            if payload.get('kind', 'web') != 'web' or not isinstance(surface, str) or not surface.startswith('web-'):
                raise ValueError('网页窗口身份不正确')
            result = self.report_exit_surface(surface, payload.get('revision'), payload.get('dirty'),
                draft=payload.get('draft'), label=payload.get('label'), kind='web')
        elif action == 'request':
            result = self.request_exit(surface or 'web', payload.get('reason', '结束本次辅助'))
        elif action == 'ack':
            result = self.acknowledge_exit(payload.get('request_id'), surface, payload.get('decision'), payload.get('revision'))
        elif action == 'unregister':
            result = self.unregister_exit_surface(surface, payload.get('revision'), payload.get('dirty'), draft=payload.get('draft'))
        elif action == 'save-draft':
            return {'saved': self.save_exit_draft(surface, payload.get('kind', 'web-session'), payload.get('label', '未完成草稿'), payload.get('draft'))}
        elif action == 'draft-list':
            rows = self.list_exit_drafts(include_archived=True)
            include_archived = payload.get('include_archived', False)
            if type(include_archived) is not bool:
                raise ValueError('草稿归档筛选不正确')
            return {'drafts': rows if include_archived else [row for row in rows if row.get('state') != 'archived'],
                    'archived_count': sum(row.get('state') == 'archived' for row in rows)}
        elif action == 'draft-load':
            return {'draft': self.load_exit_draft(payload.get('id'))}
        elif action == 'draft-preserve-raw':
            return {'draft_state': self.exit_recovery.preserve_raw(payload.get('id'),
                payload.get('expected_revision'), payload.get('confirmed'))}
        elif action == 'draft-original-info':
            value, _ = self.exit_recovery.original(payload.get('id'), payload.get('expected_revision'))
            return {'original': value}
        elif action == 'draft-state':
            return {'draft_state': self.set_exit_draft_lifecycle(payload.get('id'), payload.get('state'),
                payload.get('expected_revision'))}
        elif action == 'resolve-offline':
            return self.exit_coordinator.resolve_offline(payload.get('request_id'), surface, payload.get('decision'), payload.get('revision'))
        else:
            raise ValueError('不支持的退出操作')
        return {'exit': result}

    def _default_save_wait_is_new(self, root):
        root = Path(root)
        return (self.settings['slot'] == 'auto' and self.active_slot is None
                and root.resolve() == Path(DEFAULTS['save_root']).resolve()
                and str(root.resolve()) not in self._observed_progress_roots
                and not root.exists())

    def _record_shutdown_capture(self, row):
        with self._shutdown_lock:
            if self._shutdown_backup_result is None and time.monotonic() < self._shutdown_deadline:
                self._shutdown_captured.append(copy.deepcopy(row))

    def _capture_for_shutdown(self, deadline):
        result = None
        try:
            if not self._backup_io_lock.acquire(timeout=max(0, deadline - time.monotonic())):
                return
            try:
                if not self.lock.acquire(timeout=max(0, deadline - time.monotonic())):
                    return
                try:
                    root, config_error, manager = self.settings['save_root'], self.config_error, self.backups
                    state = SimpleNamespace(settings=dict(self.settings), active_slot=self.active_slot,
                        _observed_progress_roots=set(self._observed_progress_roots))
                finally:
                    self.lock.release()
                allow_missing_default = Session._default_save_wait_is_new(state, root)
                result = ({'ok': False, 'state': 'configuration-error', 'captured': [],
                           'error': '最后一次备份未完成：连接设置尚未修复；已有原件仍保留。'}
                          if config_error else manager.final_capture(root, deadline,
                              allow_missing_default=allow_missing_default,
                              on_capture=self._record_shutdown_capture))
            finally:
                self._backup_io_lock.release()
        except Exception:
            logging.exception('Final backup capture failed')
            with self._shutdown_lock:
                captured = copy.deepcopy(self._shutdown_captured)
            result = {'ok': False, 'state': 'partial' if captured else 'failed', 'captured': captured,
                      'error': '最后一次备份未完成；已有备份与活动存档原件仍保留。'}
        finally:
            with self._shutdown_lock:
                if result is not None and self._shutdown_backup_result is None and time.monotonic() < deadline:
                    self._shutdown_capture_result = result
            self._shutdown_done.set()

    def _write_shutdown_receipt(self, result):
        from .backups import atomic_json, unlinked
        try:
            unlinked(self.config_path.parent).mkdir(parents=True, exist_ok=True)
            atomic_json(self.config_path.parent / 'last-exit.json',
                        {'format': 1, 'finished': time.time(), 'backup': result})
        except (OSError, ValueError):
            with self._shutdown_lock:
                self._shutdown_receipt_error = '退出检查记录无法写入；请查看本次运行日志。'
            logging.exception('Could not record last exit backup result')
        finally:
            self._shutdown_receipt_done.set()

    def prepare_shutdown(self, timeout=3):
        """Bound the waiting time even if a filesystem call cannot return promptly."""
        deadline = time.monotonic() + min(3, max(0, timeout))
        self._shutdown_requested.set()
        self._backup_shutdown_started = True
        with self._shutdown_lock:
            if self._shutdown_thread is None:
                self._shutdown_deadline = deadline
                self._shutdown_thread = threading.Thread(target=self._capture_for_shutdown,
                    args=(deadline,), name='last-save-capture', daemon=True)
                self._shutdown_thread.start()
            deadline = min(deadline, self._shutdown_deadline)
            if self._shutdown_result is not None:
                return copy.deepcopy(self._shutdown_result)
        self._shutdown_done.wait(max(0, deadline - time.monotonic()))
        with self._shutdown_lock:
            if self._shutdown_backup_result is None:
                captured = copy.deepcopy(self._shutdown_captured)
                self._shutdown_backup_result = self._shutdown_capture_result or {'ok': False, 'state': 'partial' if captured else 'timeout', 'captured': captured,
                    'error': '最后一次备份检查未能在结束前完成；其余槽位的结果尚未确认。已有备份与活动存档原件仍保留；下次启动助手后，请检查存档历史与备份状态。'}
            if self._shutdown_receipt_thread is None:
                self._shutdown_receipt_thread = threading.Thread(target=self._write_shutdown_receipt,
                    args=(copy.deepcopy(self._shutdown_backup_result),), name='last-exit-receipt', daemon=True)
                self._shutdown_receipt_thread.start()
        self._shutdown_receipt_done.wait(max(0, deadline - time.monotonic()))
        with self._shutdown_lock:
            if self._shutdown_result is None:
                result = copy.deepcopy(self._shutdown_backup_result)
                if not self._shutdown_receipt_done.is_set():
                    result['receipt_error'] = '退出检查记录尚未确认写入；已有原件仍保留，请在下次启动后核对备份状态。'
                elif self._shutdown_receipt_error:
                    result['receipt_error'] = self._shutdown_receipt_error
                self._shutdown_result = result
            return copy.deepcopy(self._shutdown_result)

    def _exit_finished(self, result):
        # Give live surfaces time to show the result; persisted receipt covers the next launch.
        self.stop.wait(.8)
        self.stop.set()

    @property
    def knowledge(self):
        from .knowledge import KnowledgeWorkspace
        with self.lock:
            if self._knowledge is None:
                self._knowledge = KnowledgeWorkspace(self.config_path.parent / 'knowledge.json', self)
            return self._knowledge

    @property
    def play_preferences(self):
        from .play_state import PlayPreferences
        with self.lock:
            preferences = self._play_preferences
        if preferences is None:
            candidate = PlayPreferences(self.config_path.parent)
            with self.lock:
                if self._play_preferences is None:
                    self._play_preferences = candidate
                preferences = self._play_preferences
        return preferences

    def workspace_status(self):
        from .workspace_service import workspace_status
        return workspace_status(self)

    def migration_status(self):
        from .migration import status
        with self._backup_io():
            return status(self)

    def migration_action(self, action, payload=None, raw=None):
        with self._backup_io():
            return self._migration_action(action, payload, raw)

    def _migration_action(self, action, payload=None, raw=None):
        from . import migration
        if action == 'status':
            return migration.status(self)
        if action == 'export-preview':
            return migration.export_preview(self, payload)
        if action == 'export':
            return migration.export_bundle(self, payload)
        if action == 'preview':
            return migration.import_preview(self, raw)
        if action == 'import':
            return migration.import_bundle(self, raw, payload)
        raise ValueError('不支持的搬机迁移操作')

    def workspace_action(self, payload):
        from .workspace_service import workspace_action
        return workspace_action(self, payload)

    def decisions(self, snapshot=None):
        from .decisions import context_actions
        return context_actions(self, snapshot if snapshot is not None else self.snapshot())

    def help_status(self):
        from .workspace_service import help_status
        return help_status(self)

    def support_action(self, payload):
        from .workspace_service import open_support_location
        return open_support_location(self, payload)

    def play_settings(self):
        from .workspace_service import play_status
        return play_status(self)

    def update_play_settings(self, payload):
        from .workspace_service import update_play
        return update_play(self, payload)

    def backup_health(self):
        with self._backup_operation() as context:
            health = context.backups.health_status(context.settings['save_root'], context.active_slot)
            with self.lock:
                if self._context_current(context):
                    self._backup_health_cache = (self._health_key(context), time.time(), copy.deepcopy(health))
                    return self._waiting_health(health, context.waiting_for_save)
                return self._cached_backup_health()

    @staticmethod
    def _waiting_health(health, waiting):
        health = copy.deepcopy(health)
        if waiting and health['state'] in ('blocked', 'protected', 'waiting') and not health['error']:
            health['state'] = 'waiting'
            health['saved'] = 0
            health['last_save_protected'] = False
        return health

    def _backup_context_state(self):
        return SimpleNamespace(config_path=self.config_path, settings=dict(self.settings),
            settings_revision=self.settings_revision, backup_context=self.backup_context,
            backups=self.backups, active_slot=self.active_slot, waiting_for_save=self.waiting_for_save,
            backup_enabled=self.backups.enabled, config_error=self.config_error)

    def _context_current(self, context):
        return (self.settings_revision == context.settings_revision and self.backups is context.backups
                and self.backup_context == context.backup_context
                and self.config_error == context.config_error
                and not self._shutdown_requested.is_set() and not self.stop.is_set())

    @staticmethod
    def _health_key(context):
        return (context.backups, context.settings['save_root'], context.backup_context, context.active_slot)

    def _cached_backup_health(self):
        context = self._backup_context_state()
        cached = self._backup_health_cache
        health = (copy.deepcopy(cached[2]) if cached and cached[0] == self._health_key(context) else
            {'state': 'unknown', 'error': '', 'last_success': 0, 'saved': 0, 'slot': self.active_slot,
             'last_save_protected': False, 'other_errors': ''})
        # These memory-only flags can retract protection, never establish it.
        enabled, health_root, error = self.backups.enabled, self.backups.health_root, self.backups.error
        if not enabled:
            health['state'], health['last_save_protected'] = 'paused', False
        elif error and health_root in (None, str(self.settings['save_root'])):
            health['state'], health['error'], health['last_save_protected'] = 'blocked', error, False
        elif health['state'] == 'unknown' and self.waiting_for_save:
            health['state'] = 'waiting'
        health = self._waiting_health(health, self.waiting_for_save)
        health['checked_at'] = cached[1] if cached and cached[0] == self._health_key(context) else None
        health['pending'] = bool(self._backup_busy or self._refresh_pending or self._shutdown_requested.is_set()
            or health['checked_at'] is not None and time.time() - health['checked_at'] > 15)
        if health['pending']:
            health['state'] = 'working'
            health['last_save_protected'] = False
        return health

    @contextmanager
    def _backup_io(self):
        # Never acquire this gate or a manager while holding the published-state lock.
        with self._backup_io_lock:
            with self.lock:
                self._backup_busy += 1
            try:
                yield
            finally:
                with self.lock:
                    self._backup_busy -= 1

    @contextmanager
    def _backup_operation(self, *, mutating=False):
        with self._backup_io():
            with self.lock:
                if mutating and (self._shutdown_requested.is_set() or self.stop.is_set()):
                    raise ValueError('助手正在结束，不能再修改设置或存档备份')
                context = self._backup_context_state()
            with context.backups.lock:
                context.backup_enabled = context.backups.enabled
                yield context

    def _check_settings_commit(self, context):
        with self.lock:
            if self._shutdown_requested.is_set() or self.stop.is_set():
                raise ValueError('助手正在结束，尚未发布本次设置或备份目的地切换')
            if not self._context_current(context):
                raise SettingsConflict('连接设置已变化，请重新载入已保存设置后预览')

    def _configuration_write_uncertain(self):
        message = '设置文件在提交或回滚期间被其他程序更改，或回滚尚未完成；未强制覆盖新字节，请重新载入连接设置并核对保留副本。'
        with self.lock:
            self.config_error = self.error = message
            self.data = None
            self._fingerprint = None
            self._backup_health_cache = None
            self._refresh_serial += 1
            self._refresh_pending = False
        return message

    def _persist_settings(self, updated, context, publish, *, recovery=False):
        """Prepare outside the state lock and roll back only bytes owned by this write."""
        from .backups import unlinked
        def read():
            try:
                with unlinked(self.config_path).open('rb') as stream:
                    raw = stream.read() if recovery else stream.read(65537)
                if not recovery and len(raw) > 65536:
                    raise SettingsConflict('设置文件过大或在保存期间变化，原件仍保留')
                return raw
            except FileNotFoundError:
                return None
        def retain(raw, kind):
            if raw is not None:
                target = self.config_path.with_name(f'{self.config_path.stem}.{kind}-{uuid.uuid4().hex}.json')
                with unlinked(target).open('xb') as stream:
                    stream.write(raw)
                return target
        def digest(raw):
            return hashlib.sha256(raw).digest() if raw is not None else None
        self._check_settings_commit(context)
        unlinked(self.config_path.parent).mkdir(exist_ok=True, parents=True)
        original = read()
        submitted = json.dumps(updated, ensure_ascii=False, indent=2).encode('utf-8')
        temporary = self.config_path.with_name(f'{self.config_path.name}.{uuid.uuid4().hex}.pending')
        with unlinked(temporary).open('xb') as stream:
            stream.write(submitted)
        try:
            backup = retain(original, 'recovery') if recovery else None
        except OSError as exc:
            raise ValueError('原配置备份失败，尚未覆盖。请检查设置目录的访问权限。') from exc
        self._check_settings_commit(context)
        if digest(read()) != digest(original):
            raise SettingsConflict('设置文件已被其他程序更改，尚未覆盖；请重新载入并核对原件')
        self._check_settings_commit(context)
        try:
            temporary.replace(self.config_path)
            if digest(read()) != digest(submitted):
                raise SettingsConflict('设置文件在提交期间被其他程序更改，尚未发布；原件仍保留')
            with self.lock:
                self._check_settings_commit(context)
                publish(backup)
        except Exception as exc:
            try:
                current = read()
                if digest(current) != digest(original) and digest(current) == digest(submitted):
                    retain(submitted, 'cancelled')
                    if original is None:
                        # This exact file was created by this cancelled operation.
                        if digest(read()) == digest(submitted):
                            unlinked(self.config_path).unlink()
                    else:
                        rollback = retain(original, 'rollback')
                        if digest(read()) == digest(submitted):
                            rollback.replace(self.config_path)
                uncertain = digest(read()) != digest(original)
                if uncertain:
                    retain(original, 'prior')
                    retain(submitted, 'cancelled')
            except (OSError, ValueError) as rollback_error:
                try:
                    retain(original, 'prior')
                    retain(submitted, 'cancelled')
                except (OSError, ValueError):
                    logging.exception('Could not preserve configuration transaction copies')
                raise SettingsConflict(self._configuration_write_uncertain()) from rollback_error
            if uncertain:
                raise SettingsConflict(self._configuration_write_uncertain()) from exc
            raise

    @property
    def rules(self):
        with self.lock:
            rules = self._rules
        if rules is None:
            candidate = NumericRules(self.catalog)
            with self.lock:
                if self._rules is None:
                    self._rules = candidate
                rules = self._rules
        return rules

    @property
    def values(self):
        from .values import PlayerValues
        return PlayerValues(self.rules)

    def check_backup_context(self, context):
        if not isinstance(context, str) or context != self.backup_context:
            raise ValueError('存档连接已变化或确认已过期，请重新打开存档历史并预览')

    def backup_destination_status(self):
        from .backup_destination import status
        with self._backup_operation() as context:
            return status(context)

    def backup_destination_action(self, payload):
        from . import backup_destination
        if not isinstance(payload, dict) or not isinstance(payload.get('action'), str) or payload['action'] not in ('preview', 'apply'):
            raise ValueError('备份目的地请求格式不正确')
        allowed = {'action', 'backup_root', 'expected_settings_revision', 'context'}
        if payload['action'] == 'apply':
            allowed |= {'expected', 'confirmed'}
        if (set(payload) - (allowed | {'start_new'}) or not allowed.issubset(payload)
                or type(payload.get('start_new', False)) is not bool):
            raise ValueError('备份目的地请求格式不正确')
        with self._backup_operation(mutating=payload['action'] == 'apply') as context:
            self.check_backup_context(payload['context'])
            if payload['expected_settings_revision'] != self.settings_revision:
                raise SettingsConflict('连接设置已变化，请重新载入已保存设置并预览备份目录')
            if self.config_error:
                raise ValueError('请先修复连接设置，再更换自动备份目的地')
            if self._backup_shutdown_started or self.stop.is_set():
                raise ValueError('助手正在结束，不能再切换备份目的地')
            with context.backups.lock:
                if payload['action'] == 'preview':
                    return backup_destination.plan(context, payload['backup_root'], start_new=payload.get('start_new', False))[0]
                if payload['confirmed'] is not True:
                    raise ValueError('请明确确认复制历史并切换自动备份目的地')
                def persist(root, manager):
                    updated = {**context.settings, 'backup_root': root}
                    def publish(_):
                        self.settings = updated
                        self.backups = manager
                        self.settings_revision = uuid.uuid4().hex
                        self.backup_context = uuid.uuid4().hex
                        self._backup_health_cache = None
                    self._persist_settings(updated, context, publish)
                result = backup_destination.apply(context, payload['backup_root'], payload['expected'], persist,
                    start_new=payload.get('start_new', False), check_current=lambda: self._check_settings_commit(context))
                return {**result, 'settings': dict(self.settings), 'settings_revision': self.settings_revision,
                        'context': self.backup_context, 'directory': str(self.backups.directory)}

    def backup_status(self, expected_context=None):
        with self._backup_operation() as context:
            if expected_context is not None:
                self.check_backup_context(expected_context)
            status = self.backups.snapshot(self.settings["save_root"])
            status.update(context=self.backup_context, save_root=self.settings['save_root'])
            if self.waiting_for_save and status['health'] in ('blocked', 'protected', 'waiting') and not status['error']:
                status['health'] = 'waiting'
                status['last_save_protected'] = False
            return status

    def backup_action(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("备份请求格式不正确")
        receipt = None
        with self._backup_operation(mutating=payload.get('action') not in ('repair_history_preview', 'recovery_preview')) as context:
            if self.config_error:
                raise ValueError("请先恢复连接设置，再操作存档备份")
            root = self.settings["save_root"]
            if payload.get('action') not in ('enable', 'capture'):
                self.check_backup_context(payload.get('context'))
            if payload.get('action') in ('recovery_preview', 'recovery_execute'):
                if payload.get('expected_settings_revision') != context.settings_revision:
                    raise SettingsConflict('连接设置已变化，请重新读取恢复关联并预览')
                binding = {'context': context.backup_context, 'save_root': root,
                           'settings_revision': context.settings_revision}
                if payload['action'] == 'recovery_preview':
                    return {'ok': True, **binding, 'preview': context.backups.recovery_preview(root, payload)}
                recovered = context.backups.recovery_execute(root, payload)
                receipt = {'ok': True, **binding, 'recovery': recovered, 'message': recovered['message']}
            if payload.get('action') in ('restore', 'undo') and 'expected_current' not in payload:
                phrase = '恢复' if payload['action'] == 'restore' else '撤回'
                raise ValueError(f'请先重新预览当前进度，再确认{phrase}')
            self.backups._storage_cache = None
            if payload.get('action') == 'recovery_execute':
                pass  # The exact preview and explicit choice were checked above.
            elif payload.get("action") == "enable":
                self.backups.set_enabled(payload.get("enabled"))
            elif payload.get("action") == "capture":
                self.backups.tick(root, force=True)
            elif payload.get("action") == "restore":
                self.backups.restore(root, payload)
            elif payload.get('action') == 'undo':
                self.backups.undo(root, payload)
            elif payload.get('action') == 'manage':
                receipt = {'ok': True, 'metadata': self.backups.manage(root, payload),
                           'context': self.backup_context, 'save_root': root}
            elif payload.get('action') == 'validate':
                self.backups.validate(root)
            elif payload.get('action') == 'rejoin':
                self.backups.rejoin(root, payload)
            elif payload.get('action') == 'remove':
                self.backups.remove(root, payload)
            elif payload.get('action') == 'repair_timeline':
                self.backups.repair_timeline(root, payload)
                with self.lock:
                    if self._context_current(context):
                        self.backup_context = uuid.uuid4().hex
            elif payload.get('action') == 'repair_history_preview':
                return {'ok': True, 'context': self.backup_context,
                        'preview': self.backups.history_repair_preview(root)}
            elif payload.get('action') == 'repair_history':
                result = self.backups.repair_history(root, payload)
                with self.lock:
                    if self._context_current(context):
                        self.backup_context = uuid.uuid4().hex
                receipt = {'ok': True, 'context': self.backup_context, 'repair': result}
            else:
                raise ValueError("不支持的备份操作")
            if payload.get('action') in ('restore', 'undo', 'remove'):
                scope = {'root': root, 'context': self.backup_context}
                operation = {'action': payload['action'], 'scope': scope, 'root': root,
                             'context': self.backup_context, 'slot': payload.get('slot'), 'id': payload.get('id')}
                receipt = {'ok': True, **operation, 'save_root': root,
                           'message': self.backups.notice_for(root), 'results': [{'ok': True, **operation}]}
            if payload.get('action') in ('restore', 'undo', 'recovery_execute'):
                with self.lock:
                    if self._context_current(context):
                        self._refresh_serial += 1
                        self._fingerprint = None
                        self.active_slot = None
                        self.last_valid_time = 0
                        self._history_state = None
                        self._run_identity = None
                        self.history = []
        self.refresh()
        return receipt

    def backup_transfer(self, action, payload, *, context=None):
        with self._backup_operation(mutating=action == 'import'):
            if self.config_error:
                raise ValueError('请先恢复连接设置，再操作存档备份')
            root = self.settings['save_root']
            self.check_backup_context(context if action == 'import' else payload.get('context'))
            if action == 'import':
                self.backups._storage_cache = None
                return self.backups.import_archive(root, payload)
            if action == 'export':
                return self.backups.export(root, payload)
            if action == 'preview':
                return {**self.backups.preview(root, payload), 'context': self.backup_context, 'save_root': root}
            if action == 'undo-preview':
                return {**self.backups.undo_preview(root, payload), 'context': self.backup_context, 'save_root': root}
            raise ValueError('不支持的备份操作')

    def backup_library_status(self, identity=None, expected_context=None):
        from . import backup_libraries
        with self._backup_operation():
            self.check_backup_context(expected_context)
            self.backups.ensure_storage()
            result = (backup_libraries.details(self.backups, identity, self.settings['save_root']) if identity
                      else backup_libraries.catalog(self.backups, self.settings['save_root']))
            return {**result, 'context': self.backup_context}

    def backup_library_action(self, payload):
        from . import backup_libraries
        if not isinstance(payload, dict) or not isinstance(payload.get('action'), str):
            raise ValueError('备份库请求格式不正确')
        with self._backup_operation(mutating=True):
            self.check_backup_context(payload.get('context'))
            self.backups.ensure_storage()
            action = payload['action']
            result = backup_libraries.operate(self.backups, payload.get('library_id'), self.settings['save_root'], action, payload)
            if action == 'batch-export':
                return result
            return {**result, 'context': self.backup_context}

    def backup_workflow(self, action, payload=None, *, raw=None, context=None):
        from . import backup_workflows as flows
        payload = {} if payload is None else payload
        if not isinstance(payload, dict):
            raise ValueError('备份工作流请求格式不正确')
        with self._backup_operation(mutating=action in ('stage-retry', 'batch-import', 'archive-retention', 'reclaim-execute')):
            if self.config_error:
                raise ValueError('请先恢复连接设置，再操作存档备份')
            self.check_backup_context(context if context is not None else payload.get('context'))
            root = self.settings['save_root']
            manager = self.backups
            if action == 'storage':
                result = flows.storage_inventory(manager, root)
            elif action == 'stage-inspect':
                result = flows.inspect_stage(manager, root, payload)
            elif action == 'stage-preview':
                result = flows.stage_preview(manager, root, payload)
            elif action == 'stage-retry':
                result = flows.retry_stage(manager, root, payload)
                manager._storage_cache = None
            elif action == 'open-storage':
                result = flows.open_storage(manager, root, payload)
            elif action == 'export-preview':
                result = flows.export_preview(manager, root, payload)
            elif action == 'batch-export':
                return flows.export_batch(manager, root, payload)
            elif action == 'batch-preview':
                result = flows.import_preview(manager, root, raw)
            elif action == 'batch-import':
                result = flows.import_batch(manager, root, raw, payload.get('expected'), payload.get('selected'), payload.get('confirmed'))
                manager._storage_cache = None
            elif action == 'retention-preview':
                result = flows.retention_preview(manager, root, payload)
            elif action == 'archive-retention':
                result = flows.archive_retention(manager, root, payload)
                manager._storage_cache = None
            elif action == 'reclaim-preview':
                result = flows.reclaim_preview(manager, root, payload)
            elif action == 'reclaim-export':
                result = flows.reclaim_export(manager, root, payload)
            elif action == 'reclaim-execute':
                result = flows.reclaim_execute(manager, root, payload)
                manager._storage_cache = None
            elif action == 'preserved-export':
                return flows.export_preserved(manager, root, payload)
            else:
                raise ValueError('不支持的备份工作流')
            return {**result, 'context': self.backup_context}

    def update_settings(self, patch, *, expected_revision=None, return_receipt=False):
        clean = validate_settings(patch)
        with self._backup_io():
            receipt = self._update_settings(clean, expected_revision=expected_revision)
        self.refresh()
        return receipt if return_receipt else receipt['settings_revision']

    def _update_settings(self, clean, *, expected_revision=None, manual=None):
        with self.lock:
            if expected_revision is not None and expected_revision != self.settings_revision:
                raise SettingsConflict('连接设置已在其他位置更新。草稿仍保留，请点击「重新载入已保存设置」后重新应用需要的修改。')
            if 'backup_root' in clean and clean['backup_root'] != self.settings.get('backup_root', ''):
                raise ValueError('请先预览备份目的地，再明确确认复制历史并切换')
            if self.config_error and not {"save_root", "slot"}.issubset(clean):
                raise ValueError("请先在「连接设置」中确认存档目录和槽位，再保存设置。")
            context = self._backup_context_state()
            recovery = bool(self.config_error)
            updated = {**context.settings, **clean}
        changed_root = updated['save_root'] != context.settings['save_root'] or recovery
        def publish(backup):
            if any(updated[k] != context.settings[k] for k in ('save_root', 'slot', 'mode')):
                self.active_slot = None
                self.last_valid_time = 0
                self._missing_active_since = None
                self.data = None
                self.modified = 0
                self.history = []
                self._run_identity = None
                self._run_duration = None
                self._history_state = None
            if changed_root:
                self.backup_context = uuid.uuid4().hex
            self.settings = updated
            self.settings_revision = uuid.uuid4().hex
            self._backup_health_cache = None
            self.config_error = ''
            if backup is not None:
                self.configuration_notice = f'原配置已保留为 {backup.name}。'
            self._fingerprint = None
            if manual is not None:
                self._manual, self._manual_modified = manual, time.time()
        self._persist_settings(updated, context, publish, recovery=recovery)
        if changed_root:
            # Notice clearing takes the manager lock, after releasing the state lock.
            context.backups.clear_notice()
        with self.lock:
            return {'ok': True, 'settings_revision': self.settings_revision, 'settings': dict(self.settings)}

    def update_manual(self, payload):
        game = manual_game(payload)
        with self._backup_io():
            self._update_settings({'mode': 'manual'}, manual=game)
        self.refresh()

    _REFRESH_FIELDS = ('waiting_for_save', 'data', 'slots', 'error', 'warning', 'modified',
        'active_slot', 'last_valid_time', '_missing_active_since', 'revision', '_fingerprint',
        '_run_identity', '_run_generation', '_run_duration', '_history_state', 'history',
        '_observed_progress_roots')

    def refresh(self):
        with self.lock:
            if self._shutdown_requested.is_set() or self.stop.is_set():
                return
            stop_at = self.settings['stop_at']
            expired = bool(stop_at and stop_at != self._consumed_stop_at
                and time.time() >= datetime.fromisoformat(stop_at).timestamp())
            if expired:
                self._consumed_stop_at = stop_at
            else:
                self._refresh_serial += 1
                serial = self._refresh_serial
                self._refresh_pending = True
                state = self._backup_context_state()
                for key in self._REFRESH_FIELDS:
                    setattr(state, key, copy.copy(getattr(self, key)))
                state.waiting_for_save = False
                state.catalog, state.config_error = self.catalog, self.config_error
                state._manual, state._manual_modified = self._manual, self._manual_modified
        if expired:
            self.request_exit('deadline', '已到达用户设置的结束时间')
            return
        try:
            self._read_refresh(state)
        except Exception:
            with self.lock:
                if serial == self._refresh_serial:
                    self._refresh_pending = False
                    if self._context_current(state):
                        self.data = None
                        self._fingerprint = None
                        self.error = '读取遇到异常，将自动重试。可在「帮助与排查」查看本次运行日志和排查摘要。'
            raise
        with self.lock:
            if serial == self._refresh_serial:
                self._refresh_pending = False
                if self._context_current(state) and state._manual_modified == self._manual_modified:
                    for key in self._REFRESH_FIELDS:
                        setattr(self, key, getattr(state, key))

    def _read_refresh(self, state):
        if state.config_error:
            state.data = None
            state.slots = []
            state.warning = ""
            state.error = state.config_error
            return
        if state.settings["mode"] == "manual":
            state.error = "" if state._manual else "填写当前局势后，点击「生成建议」"
            state.warning = ""
            fingerprint = ("manual", state._manual_modified)
            if fingerprint != state._fingerprint:
                state.data = analyze(state._manual, state.catalog) if state._manual else None
                state.modified = state._manual_modified
                state._fingerprint = fingerprint
                state.revision += 1
            return
        root = Path(state.settings["save_root"])
        if not root.is_dir():
            state.slots = []
            state.data = None
            state._fingerprint = None
            state.warning = ""
            try:
                protected = state.backups.has_protected_progress(root)
            except (OSError, ValueError):
                protected = True
            if Session._default_save_wait_is_new(state, root) and not protected:
                state.waiting_for_save = True
                state.error = ""
            else:
                state.error = f"存档目录暂时不可用：{root}。请恢复该目录或在连接设置中重新选择。"
            return
        state.slots = list_slots(root)
        valid = [row for row in state.slots if row["valid"]]
        if valid:
            state._observed_progress_roots.add(str(root.resolve()))
        requested = state.settings["slot"]
        if requested != "auto":
            state.active_slot = requested
            state._missing_active_since = None
        elif state.active_slot is not None and not any(row['id'] == state.active_slot for row in state.slots):
            # The game briefly deletes game.dat before moving the completed save into place.
            # Avoid following an older run during that gap; a genuinely removed run releases auto mode.
            now = time.monotonic()
            if state._missing_active_since is None:
                state._missing_active_since = now
            if now-state._missing_active_since < 2:
                state.data = None
                state._fingerprint = None
                state.warning = state.error = ''
                state.waiting_for_save = True
                return
            state.active_slot = None
            state.last_valid_time = 0
            state._missing_active_since = None
        else:
            state._missing_active_since = None
        if requested == 'auto' and valid:
            newest = max(valid, key=lambda row: row["modified"])
            if state.active_slot is None or newest["modified"] > state.last_valid_time:
                state.active_slot = newest["id"]
        if state.active_slot is None:
            state.data = None
            state._fingerprint = None
            state.warning = ""
            if state.slots:
                latest = max(state.slots, key=lambda row: row["modified"])
                state.error = (f"没有可读取的存档。最近更新的槽位 {latest['id']}：{latest['error']}。"
                              "请在游戏中保存，助手会自动重试。")
            else:
                state.waiting_for_save = True
                state.error = ""
            return
        try:
            game, level, modified, warning = read_slot(root, state.active_slot)
            # A game's hero file and depth file are written consecutively.
            # Hash both files: cloud copies can preserve timestamps, and a map
            # can arrive after the hero file without its timestamp changing.
            content_hash = hashlib.sha256(json.dumps([game, level], sort_keys=True).encode()).digest()
            fingerprint = (state.active_slot, modified, warning, content_hash, state.settings["reveal"])
            state.error, state.warning = "", warning
            if state._fingerprint != fingerprint:
                state.data = analyze(game, state.catalog, level, state.settings["reveal"])
                state.modified = modified
                state.last_valid_time = modified
                state._fingerprint = fingerprint
                state.revision += 1
                identity = (str(root.resolve()), state.active_slot, game.get("seed"), game["hero"].get("class"))
                duration = number(game.get("duration"), None)
                # A slot can hold a new run, including a replay of the same seed.
                restarted = duration is not None and state._run_duration is not None and duration < state._run_duration
                if identity != state._run_identity or restarted:
                    state._run_generation += 1
                    state.history = []
                    state._history_state = None
                Session._record(state, state._history_state, state.data)
                state._history_state = state.data
                state._run_identity, state._run_duration = identity, duration
            state.warning = " ".join(text for text in (warning, state.data["compatibility_warning"]) if text)
        except (SaveError, OSError, TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
            state.data = None
            state._fingerprint = None
            state.warning = ""
            state.error = f"槽位 {state.active_slot}：{exc}"

    def _record(self, previous, current):
        events = []
        if not previous:
            events.append(f"读入槽位 {self.active_slot} · {current['hero']['class']} · 第 {current['depth']} 层")
        else:
            if (previous["depth"], previous["branch"]) != (current["depth"], current["branch"]):
                old = f"{previous['depth']}" + (f"（支线 {previous['branch']}）" if previous["branch"] else "")
                new = f"{current['depth']}" + (f"（支线 {current['branch']}）" if current["branch"] else "")
                events.append(f"楼层 {old} → {new}")
            delta = current["hero"]["hp"] - previous["hero"]["hp"]
            if delta:
                events.append(f"生命 {delta:+g} → {current['hero']['hp']:g}")
        for text in events:
            self.history.insert(0, {"time": self.modified, "text": text})
        self.history = self.history[:40]

    def snapshot(self):
        exit_state = self.exit_status()
        with self.lock:
            age = max(0, time.time() - self.modified) if self.modified else None
            return copy.deepcopy({"data": self.data, "slots": self.slots, "settings": self.settings,
                                  "settings_revision": self.settings_revision,
                                  "error": self.error, "warning": self.warning, "modified": self.modified,
                                  "waiting_for_save": self.waiting_for_save,
                                  "configuration_notice": self.configuration_notice,
                                  "draft_recovery_notice": self.draft_recovery_notice,
                                  "age_seconds": age, "stale": age is None or age > 60 or self._refresh_pending,
                                  'refresh_pending': self._refresh_pending,
                                  "active_slot": self.active_slot, "revision": self.revision,
                                  "run_id": (hashlib.sha256(repr((self.start_time, self._run_generation,
                                                self._run_identity)).encode('utf-8')).hexdigest()[:24]
                                             if self._run_identity is not None else None),
                                  "now": time.time(), "started": self.start_time, "history": self.history,
                                  "catalog_version": self.catalog.data["version"], "catalog_count": len(self.catalog.entries),
                                  'panel_reuse': True,
                                  'manager_reuse': self.manager_available,
                                  'workspace_revision': self._knowledge.generation if self._knowledge is not None else 0,
                                  'play_revision': self._play_preferences.generation if self._play_preferences is not None else 0,
                                  'ui_capabilities': self.ui_capabilities,
                                  'backup_health': self._cached_backup_health(),
                                  'backup_context': self.backup_context,
                                  "exit": exit_state,
                                  "stopped": self.stop.is_set()})

    def run(self):
        while not self.stop.is_set():
            try:
                self.panel.tick()
            except Exception:
                logging.exception("Panel opening failed; save monitoring continues")
            try:
                with self.lock:
                    poll_context = self._backup_context_state()
                self.refresh()
                with self._backup_operation() as context:
                    if not self.config_error and not self._shutdown_requested.is_set():
                        context.backups.tick(context.settings['save_root'])
                        health = context.backups.health_status(context.settings['save_root'], context.active_slot)
                        with self.lock:
                            if self._context_current(context):
                                self._backup_health_cache = (self._health_key(context), time.time(), health)
            except Exception:
                logging.exception("Save polling failed")
                with self.lock:
                    if self._context_current(poll_context):
                        self.data = None
                        self._fingerprint = None
                        self.error = "读取遇到异常，将自动重试。可在「帮助与排查」查看本次运行日志和排查摘要。"
            self.stop.wait(2)
