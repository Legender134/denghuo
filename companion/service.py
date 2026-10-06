"""Local session state and a read-only save polling service."""

from __future__ import annotations

import copy
from datetime import datetime, timezone, timedelta
import json
import hashlib
import logging
from pathlib import Path
import threading
import time

from .engine import Catalog, CLASSES, analyze, number
from .saves import SaveError, default_root, list_slots, read_slot
from .backups import BackupManager
from .rules import NumericRules
from .paths import ROOT, data_directory

CST = timezone(timedelta(hours=8))
DEFAULTS = {"save_root": str(default_root()), "slot": "auto", "mode": "save", "reveal": False,
            "always_on_top": True, "stop_at": ""}


def validate_settings(patch, *, require_existing_root=True):
    if not isinstance(patch, dict) or set(patch) - set(DEFAULTS):
        raise ValueError("包含不支持的设置")
    clean = {}
    for key, value in patch.items():
        if key == "save_root":
            if not isinstance(value, str) or not value.strip() or len(value) > 1000:
                raise ValueError("请输入存档目录")
            path = Path(value.strip()).expanduser()
            if require_existing_root and not path.is_dir():
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
    return {"depth": values["depth"], "branch": values["branch"], "challenges": challenges, "PotionOfHealing_known": True,
            "hero": {"class": hero_class, "lvl": values["level"], "HP": values["hp"], "HT": values["ht"],
                     "STR": values["strength"], "buffs": statuses
                     + ([{"__className": prefix + "actors.buffs.Hunger", "level": hunger}] if hunger is not None else []),
                     "inventory": ([{"__className": prefix + "items.potions.PotionOfHealing", "quantity": values["healing"], "kept_lost": True}]
                                   if values["healing"] else [])}}


class Session:
    def __init__(self, config_path=None, catalog=None):
        self.catalog = catalog or Catalog()
        self._rules = None
        self.config_path = config_path or data_directory() / 'settings.json'
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.settings = dict(DEFAULTS)
        self.config_error = ""
        self.configuration_notice = ""
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
        # A previously finished session must not immediately close the next launch.
        if self.settings["stop_at"] and datetime.fromisoformat(self.settings["stop_at"]).timestamp() <= time.time():
            self.settings["stop_at"] = ""
        self.data = None
        self.slots = []
        self.error = ""
        self.warning = ""
        self.modified = 0
        self.active_slot = None
        self.last_valid_time = 0
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
        self.backups = BackupManager(self.config_path.parent / "backups")
        from .panel import PanelBridge
        self.panel = PanelBridge()

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

    def backup_status(self):
        with self.lock:
            return self.backups.snapshot(self.settings["save_root"])

    def backup_action(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("备份请求格式不正确")
        with self.lock:
            if self.config_error:
                raise ValueError("请先恢复连接设置，再操作存档备份")
            root = self.settings["save_root"]
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
                self.backups.manage(root, payload)
            elif payload.get('action') == 'validate':
                self.backups.validate(root)
            elif payload.get('action') == 'rejoin':
                self.backups.rejoin(root, payload)
            elif payload.get('action') == 'remove':
                self.backups.remove(root, payload)
            else:
                raise ValueError("不支持的备份操作")
            if payload.get('action') in ('restore', 'undo'):
                self._fingerprint = None
                self.active_slot = None
                self.last_valid_time = 0
                self._history_state = None
                self._run_identity = None
                self.history = []
        self.refresh()

    def backup_transfer(self, action, payload):
        with self.lock:
            if self.config_error:
                raise ValueError('请先恢复连接设置，再操作存档备份')
            root = self.settings['save_root']
            if action == 'import':
                self.backups._storage_cache = None
                return self.backups.import_archive(root, payload)
            if action == 'export':
                return self.backups.export(root, payload)
            if action == 'preview':
                return self.backups.preview(root, payload)
            raise ValueError('不支持的备份操作')

    def update_settings(self, patch):
        clean = validate_settings(patch)
        with self.lock:
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
                self.data = None
                self.modified = 0
                self.history = []
                self._run_identity = None
                self._run_duration = None
                self._history_state = None
            self.settings = updated
            self.config_error = ""
            if backup is not None:
                self.configuration_notice = f"原配置已保留为 {backup.name}。"
            self._fingerprint = None
        self.refresh()

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
            stop_at = self.settings["stop_at"]
            if stop_at and time.time() >= datetime.fromisoformat(stop_at).timestamp():
                self.stop.set()
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
                self.error = f"存档目录暂时不可用：{root}。请恢复该目录或在连接设置中重新选择。"
                return
            self.slots = list_slots(root)
            valid = [row for row in self.slots if row["valid"]]
            requested = self.settings["slot"]
            if requested != "auto":
                self.active_slot = requested
            elif valid:
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
                    self.error = "尚未找到存档。开始一局游戏并保存，或切换到手动局势。"
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
                                  "error": self.error, "warning": self.warning, "modified": self.modified,
                                  "configuration_notice": self.configuration_notice,
                                  "age_seconds": age, "stale": age is None or age > 60,
                                  "active_slot": self.active_slot, "revision": self.revision,
                                  "run_id": (hashlib.sha256(repr((self.start_time, self._run_generation,
                                                self._run_identity)).encode('utf-8')).hexdigest()[:24]
                                             if self._run_identity is not None else None),
                                  "now": time.time(), "started": self.start_time, "history": self.history,
                                  "catalog_version": self.catalog.data["version"], "catalog_count": len(self.catalog.entries),
                                  'panel_reuse': True,
                                  'backup_health': self.backups.health_status(self.settings['save_root'], self.active_slot),
                                  "stopped": self.stop.is_set()})

    def run(self):
        while not self.stop.is_set():
            try:
                self.panel.tick()
                self.refresh()
                if not self.config_error:
                    self.backups.tick(self.settings["save_root"])
            except Exception:
                logging.exception("Save polling failed")
                with self.lock:
                    self.data = None
                    self._fingerprint = None
                    self.error = "读取遇到异常，将自动重试。详情见 .local/companion.log。"
            self.stop.wait(2)
