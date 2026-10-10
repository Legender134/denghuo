"""Local session state and a read-only save polling service."""

from __future__ import annotations

import copy
from datetime import datetime, timezone, timedelta
import json
import hashlib
import logging
from pathlib import Path
from queue import Queue
import threading
import time
import uuid

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
        self.stop = threading.Event()
        self._shutdown_lock = threading.RLock()
        self._shutdown_done = threading.Event()
        self._shutdown_thread = None
        self._shutdown_deadline = None
        self._shutdown_result = None
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
            if self._shutdown_result is None:
                self._shutdown_captured.append(copy.deepcopy(row))

    def _capture_for_shutdown(self, root, deadline, config_error, manager):
        try:
            with self.lock:
                allow_missing_default = self._default_save_wait_is_new(root)
            result = ({'ok': False, 'state': 'configuration-error', 'captured': [],
                       'error': '最后一次备份未完成：连接设置尚未修复；已有原件仍保留。'}
                      if config_error else manager.final_capture(root, deadline,
                          allow_missing_default=allow_missing_default,
                          on_capture=self._record_shutdown_capture))
        except Exception:
            logging.exception('Final backup capture failed')
            with self._shutdown_lock:
                captured = copy.deepcopy(self._shutdown_captured)
            result = {'ok': False, 'state': 'partial' if captured else 'failed', 'captured': captured,
                      'error': '最后一次备份未完成；已有备份与活动存档原件仍保留。'}
        with self._shutdown_lock:
            if self._shutdown_result is None:
                self._shutdown_result = result
        self._shutdown_done.set()

    def prepare_shutdown(self, timeout=3):
        """Bound the waiting time even if a filesystem call cannot return promptly."""
        from .backups import atomic_json, unlinked
        with self._shutdown_lock:
            if self._shutdown_thread is None:
                with self.lock:
                    root, config_error = self.settings['save_root'], self.config_error
                    self._backup_shutdown_started = True
                    manager = self.backups
                self._shutdown_deadline = time.monotonic() + min(3, max(0, timeout))
                self._shutdown_thread = threading.Thread(target=self._capture_for_shutdown,
                    args=(root, self._shutdown_deadline, config_error, manager), name='last-save-capture', daemon=True)
                self._shutdown_thread.start()
            deadline = self._shutdown_deadline
        self._shutdown_done.wait(max(0, deadline - time.monotonic()))
        with self._shutdown_lock:
            if self._shutdown_result is None:
                captured = copy.deepcopy(self._shutdown_captured)
                self._shutdown_result = {'ok': False, 'state': 'partial' if captured else 'timeout', 'captured': captured,
                    'error': '最后一次备份检查未能在结束前完成；其余槽位的结果尚未确认。已有备份与活动存档原件仍保留；下次启动助手后，请检查存档历史与备份状态。'}
            result = copy.deepcopy(self._shutdown_result)
        try:
            unlinked(self.config_path.parent).mkdir(parents=True, exist_ok=True)
            atomic_json(self.config_path.parent / 'last-exit.json', {'format': 1, 'finished': time.time(), 'backup': result})
        except (OSError, ValueError):
            logging.exception('Could not record last exit backup result')
            result = {**result, 'receipt_error': '退出检查记录无法写入；请查看本次运行日志。'}
        if not result['ok']:
            logging.warning('%s', result['error'])
        return result

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
            if self._play_preferences is None:
                self._play_preferences = PlayPreferences(self.config_path.parent)
            return self._play_preferences

    def workspace_status(self):
        from .workspace_service import workspace_status
        return workspace_status(self)

    def migration_status(self):
        from .migration import status
        return status(self)

    def migration_action(self, action, payload=None, raw=None):
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
        health = self.backups.health_status(self.settings['save_root'], self.active_slot)
        if self.waiting_for_save and health['state'] in ('blocked', 'protected', 'waiting') and not health['error']:
            health['state'] = 'waiting'
            health['saved'] = 0
            health['last_save_protected'] = False
        return health

    @property
    def rules(self):
        with self.lock:
            if self._rules is None:
                self._rules = NumericRules(self.catalog)
            return self._rules

    @property
    def values(self):
        from .values import PlayerValues
        return PlayerValues(self.rules)

    def check_backup_context(self, context):
        if not isinstance(context, str) or context != self.backup_context:
            raise ValueError('存档连接已变化或确认已过期，请重新打开存档历史并预览')

    def backup_destination_status(self):
        from .backup_destination import status
        with self.lock:
            return status(self)

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
        with self.lock:
            self.check_backup_context(payload['context'])
            if payload['expected_settings_revision'] != self.settings_revision:
                raise SettingsConflict('连接设置已变化，请重新载入已保存设置并预览备份目录')
            if self.config_error:
                raise ValueError('请先修复连接设置，再更换自动备份目的地')
            if self._backup_shutdown_started or self.stop.is_set():
                raise ValueError('助手正在结束，不能再切换备份目的地')
            with self.backups.lock:
                if payload['action'] == 'preview':
                    return backup_destination.plan(self, payload['backup_root'], start_new=payload.get('start_new', False))[0]
                if payload['confirmed'] is not True:
                    raise ValueError('请明确确认复制历史并切换自动备份目的地')
                def persist(root, manager):
                    updated = {**self.settings, 'backup_root': root}
                    self.config_path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = self.config_path.with_suffix('.tmp')
                    temporary.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding='utf-8')
                    temporary.replace(self.config_path)
                    self.settings = updated
                    self.backups = manager
                    self.settings_revision = uuid.uuid4().hex
                    self.backup_context = uuid.uuid4().hex
                result = backup_destination.apply(self, payload['backup_root'], payload['expected'], persist,
                                                   start_new=payload.get('start_new', False))
                return {**result, 'settings': dict(self.settings), 'settings_revision': self.settings_revision,
                        'context': self.backup_context, 'directory': str(self.backups.directory)}

    def backup_status(self, expected_context=None):
        with self.lock:
            if expected_context is not None:
                self.check_backup_context(expected_context)
            status = self.backups.snapshot(self.settings["save_root"])
            status.update(context=self.backup_context, save_root=self.settings['save_root'])
            if self.waiting_for_save and status['health'] in ('blocked', 'protected', 'waiting') and not status['error']:
                status['health'] = self.backup_health()['state']
                status['last_save_protected'] = False
            return status

    def backup_action(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("备份请求格式不正确")
        receipt = None
        with self.lock:
            if self.config_error:
                raise ValueError("请先恢复连接设置，再操作存档备份")
            root = self.settings["save_root"]
            if payload.get('action') not in ('enable', 'capture'):
                self.check_backup_context(payload.get('context'))
            if payload.get('action') in ('restore', 'undo') and 'expected_current' not in payload:
                phrase = '恢复' if payload['action'] == 'restore' else '撤回'
                raise ValueError(f'请先重新预览当前进度，再确认{phrase}')
            self.backups._storage_cache = None
            if payload.get("action") == "enable":
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
                self.backup_context = uuid.uuid4().hex
            elif payload.get('action') == 'repair_history_preview':
                return {'ok': True, 'context': self.backup_context,
                        'preview': self.backups.history_repair_preview(root)}
            elif payload.get('action') == 'repair_history':
                result = self.backups.repair_history(root, payload)
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
            if payload.get('action') in ('restore', 'undo'):
                self._fingerprint = None
                self.active_slot = None
                self.last_valid_time = 0
                self._history_state = None
                self._run_identity = None
                self.history = []
        self.refresh()
        return receipt

    def backup_transfer(self, action, payload, *, context=None):
        with self.lock:
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
        with self.lock:
            self.check_backup_context(expected_context)
            self.backups.ensure_storage()
            result = (backup_libraries.details(self.backups, identity, self.settings['save_root']) if identity
                      else backup_libraries.catalog(self.backups, self.settings['save_root']))
            return {**result, 'context': self.backup_context}

    def backup_library_action(self, payload):
        from . import backup_libraries
        if not isinstance(payload, dict) or not isinstance(payload.get('action'), str):
            raise ValueError('备份库请求格式不正确')
        with self.lock:
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
        with self.lock:
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
        with self.lock:
            if expected_revision is not None and expected_revision != self.settings_revision:
                raise SettingsConflict('连接设置已在其他位置更新。草稿仍保留，请点击「重新载入已保存设置」后重新应用需要的修改。')
            if 'backup_root' in clean and clean['backup_root'] != self.settings.get('backup_root', ''):
                raise ValueError('请先预览备份目的地，再明确确认复制历史并切换')
            if self.config_error and not {"save_root", "slot"}.issubset(clean):
                raise ValueError("请先在「连接设置」中确认存档目录和槽位，再保存设置。")
            updated = {**self.settings, **clean}
            self.config_path.parent.mkdir(exist_ok=True, parents=True)
            temp = self.config_path.with_suffix(".tmp")
            temp.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
            backup = None
            if self.config_error and self.config_path.exists():
                backup = self.config_path.with_name(f"{self.config_path.stem}.recovery-{time.time_ns()}.json")
                try:
                    # Keep the exact original bytes before the user's confirmed replacement.
                    with self.config_path.open("rb") as source, backup.open("xb") as target:
                        while chunk := source.read(65536):
                            target.write(chunk)
                except OSError as exc:
                    raise ValueError("原配置备份失败，尚未覆盖。请检查设置目录的访问权限。") from exc
            temp.replace(self.config_path)
            if any(updated[k] != self.settings[k] for k in ("save_root", "slot", "mode")):
                self.active_slot = None
                self.last_valid_time = 0
                self._missing_active_since = None
                self.data = None
                self.modified = 0
                self.history = []
                self._run_identity = None
                self._run_duration = None
                self._history_state = None
            if updated['save_root'] != self.settings['save_root'] or self.config_error:
                self.backup_context = uuid.uuid4().hex
                self.backups.clear_notice()  # Old connection completion stays in its submitted receipt.
            self.settings = updated
            self.settings_revision = uuid.uuid4().hex
            revision = self.settings_revision
            receipt = {'ok': True, 'settings_revision': revision, 'settings': dict(updated)}
            self.config_error = ""
            if backup is not None:
                self.configuration_notice = f"原配置已保留为 {backup.name}。"
            self._fingerprint = None
        self.refresh()
        return receipt if return_receipt else revision

    def update_manual(self, payload):
        game = manual_game(payload)
        with self.lock:
            previous = self._manual, self._manual_modified
            self._manual = game
            self._manual_modified = time.time()
            try:
                self.update_settings({"mode": "manual"})
            except (ValueError, OSError):
                # A rejected save must not silently apply on the next poll.
                self._manual, self._manual_modified = previous
                raise

    def refresh(self):
        with self.lock:
            self.waiting_for_save = False
            stop_at = self.settings["stop_at"]
            if stop_at and stop_at != self._consumed_stop_at and time.time() >= datetime.fromisoformat(stop_at).timestamp():
                # Consume this deadline once; cancelling the request must resume
                # the session instead of reopening the same prompt on every poll.
                self._consumed_stop_at = stop_at
                self.request_exit("deadline", "已到达用户设置的结束时间")
                return
            if self.config_error:
                self.data = None
                self.slots = []
                self.warning = ""
                self.error = self.config_error
                return
            if self.settings["mode"] == "manual":
                self.error = "" if self._manual else "填写当前局势后，点击「生成建议」"
                self.warning = ""
                fingerprint = ("manual", self._manual_modified)
                if fingerprint != self._fingerprint:
                    self.data = analyze(self._manual, self.catalog) if self._manual else None
                    self.modified = self._manual_modified
                    self._fingerprint = fingerprint
                    self.revision += 1
                return
            root = Path(self.settings["save_root"])
            if not root.is_dir():
                self.slots = []
                self.data = None
                self._fingerprint = None
                self.warning = ""
                try:
                    protected = self.backups.has_protected_progress(root)
                except (OSError, ValueError):
                    protected = True
                if self._default_save_wait_is_new(root) and not protected:
                    self.waiting_for_save = True
                    self.error = ""
                else:
                    self.error = f"存档目录暂时不可用：{root}。请恢复该目录或在连接设置中重新选择。"
                return
            self.slots = list_slots(root)
            valid = [row for row in self.slots if row["valid"]]
            if valid:
                self._observed_progress_roots.add(str(root.resolve()))
            requested = self.settings["slot"]
            if requested != "auto":
                self.active_slot = requested
                self._missing_active_since = None
            elif self.active_slot is not None and not any(row['id'] == self.active_slot for row in self.slots):
                # The game briefly deletes game.dat before moving the completed save into place.
                # Avoid following an older run during that gap; a genuinely removed run releases auto mode.
                now = time.monotonic()
                if self._missing_active_since is None:
                    self._missing_active_since = now
                if now-self._missing_active_since < 2:
                    self.data = None
                    self._fingerprint = None
                    self.warning = self.error = ''
                    self.waiting_for_save = True
                    return
                self.active_slot = None
                self.last_valid_time = 0
                self._missing_active_since = None
            else:
                self._missing_active_since = None
            if requested == 'auto' and valid:
                newest = max(valid, key=lambda row: row["modified"])
                if self.active_slot is None or newest["modified"] > self.last_valid_time:
                    self.active_slot = newest["id"]
            if self.active_slot is None:
                self.data = None
                self._fingerprint = None
                self.warning = ""
                if self.slots:
                    latest = max(self.slots, key=lambda row: row["modified"])
                    self.error = (f"没有可读取的存档。最近更新的槽位 {latest['id']}：{latest['error']}。"
                                  "请在游戏中保存，助手会自动重试。")
                else:
                    self.waiting_for_save = True
                    self.error = ""
                return
            try:
                game, level, modified, warning = read_slot(root, self.active_slot)
                # A game's hero file and depth file are written consecutively.
                # Hash both files: cloud copies can preserve timestamps, and a map
                # can arrive after the hero file without its timestamp changing.
                content_hash = hashlib.sha256(json.dumps([game, level], sort_keys=True).encode()).digest()
                fingerprint = (self.active_slot, modified, warning, content_hash, self.settings["reveal"])
                self.error, self.warning = "", warning
                if self._fingerprint != fingerprint:
                    self.data = analyze(game, self.catalog, level, self.settings["reveal"])
                    self.modified = modified
                    self.last_valid_time = modified
                    self._fingerprint = fingerprint
                    self.revision += 1
                    identity = (str(root.resolve()), self.active_slot, game.get("seed"), game["hero"].get("class"))
                    duration = number(game.get("duration"), None)
                    # A slot can hold a new run, including a replay of the same seed.
                    restarted = duration is not None and self._run_duration is not None and duration < self._run_duration
                    if identity != self._run_identity or restarted:
                        self._run_generation += 1
                        self.history = []
                        self._history_state = None
                    self._record(self._history_state, self.data)
                    self._history_state = self.data
                    self._run_identity, self._run_duration = identity, duration
                self.warning = " ".join(text for text in (warning, self.data["compatibility_warning"]) if text)
            except (SaveError, OSError, TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
                self.data = None
                self._fingerprint = None
                self.warning = ""
                self.error = f"槽位 {self.active_slot}：{exc}"

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
        with self.lock:
            age = max(0, time.time() - self.modified) if self.modified else None
            return copy.deepcopy({"data": self.data, "slots": self.slots, "settings": self.settings,
                                  "settings_revision": self.settings_revision,
                                  "error": self.error, "warning": self.warning, "modified": self.modified,
                                  "waiting_for_save": self.waiting_for_save,
                                  "configuration_notice": self.configuration_notice,
                                  "draft_recovery_notice": self.draft_recovery_notice,
                                  "age_seconds": age, "stale": age is None or age > 60,
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
                                  'backup_health': self.backup_health(),
                                  'backup_context': self.backup_context,
                                  "exit": self.exit_status(),
                                  "stopped": self.stop.is_set()})

    def run(self):
        while not self.stop.is_set():
            try:
                self.panel.tick()
            except Exception:
                logging.exception("Panel opening failed; save monitoring continues")
            try:
                self.refresh()
                with self.lock:
                    if not self.config_error:
                        self.backups.tick(self.settings["save_root"])
            except Exception:
                logging.exception("Save polling failed")
                with self.lock:
                    self.data = None
                    self._fingerprint = None
                    self.error = "读取遇到异常，将自动重试。可在「帮助与排查」查看本次运行日志和排查摘要。"
            self.stop.wait(2)
