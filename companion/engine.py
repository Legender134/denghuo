"""Explain saved, player-known state. Advice is deterministic and inspectable."""

from __future__ import annotations

import json
import math
from pathlib import Path
import re

from .public_item_levels import level_applies, scroll_upgradable, visible_level
from .public_item_state import project_item_state, cooked_fruit_name, project_equipment_state
from .character_scene import scene_from_game

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "com.shatteredpixel.shatteredpixeldungeon."
CLASSES = {"WARRIOR": "战士", "MAGE": "法师", "ROGUE": "盗贼", "HUNTRESS": "女猎手", "DUELIST": "决斗家", "CLERIC": "牧师"}
EQUIPMENT = {"weapon": "主武器", "armor": "护甲", "artifact": "神器", "misc": "饰品", "ring": "戒指", "second_wep": "副武器"}
CHALLENGES = {1: "饥饿游戏", 2: "信念护体", 4: "药水恐惧", 8: "荒芜之地", 16: "集群智慧", 32: "深入黑暗", 64: "禁忌符文", 128: "精英强敌", 256: "绝命头目"}


def short_class(obj: dict) -> str:
    return str(obj.get("__className", "")).rsplit(".", 1)[-1]


def number(value, default=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    try:
        return value if math.isfinite(value) else default
    except OverflowError:
        return default


def clean_text(text: str) -> str:
    text = text.replace("_", "")
    return re.sub(r"%(?:\d+\$)?[\d.]*[sdf]", "（随局势变化）", text).replace("%%", "%")


class Catalog:
    def __init__(self, path=None):
        self.data = json.loads((path or ROOT / "data/catalog.json").read_text(encoding="utf-8"))
        self.messages = self.data["messages"]
        self.tiers = self.data["tiers"]
        self.entries = [{**row, "description": clean_text(row["description"]), "name": clean_text(row["name"])} for row in self.data["entries"]]
        self.entry_index = {row['id']: row for row in self.entries}
        for row in self.entries:
            identity = row['id']
            row['type_label'] = ('牧师法术' if identity.startswith('actors.hero.spells.') else
                '角色天赋' if identity.startswith('actors.hero.talent.') else
                '职业技能' if identity.startswith('actors.hero.abilities.') else
                '武器技能' if identity.endswith('.ability') else
                '植物种子' if identity.startswith('plants.') and identity.endswith('$seed') else
                '状态效果' if '$' in identity or identity.startswith('actors.buffs.') else row['category'])

    def key(self, obj):
        return str(obj.get("__className", "")).removeprefix(PREFIX).lower()

    def name(self, obj, fallback="未知"):
        if short_class(obj) == "Berserk":
            state = {"NORMAL": "angered", "BERSERK": "berserk", "RECOVERING": "recovering"}.get(obj.get("state"))
            return clean_text(self.messages.get(self.key(obj) + "." + state, "狂战士状态")) if state else "狂战士状态"
        return clean_text(self.messages.get(self.key(obj) + ".name", short_class(obj) or fallback))

    def search(self, query="", category="全部", limit=80, offset=0):
        from .knowledge_search import search
        return search(self, query, category, limit, offset)

    def item(self, item, game, location="背包", reveal=False):
        kind, key = short_class(item), self.key(item)
        family = next((family for family, base in (("potions", "potion"), ("scrolls", "scroll"), ("rings", "ring"))
                       if key.startswith((f"items.{family}.{base}", f"items.{family}.exotic.{base}"))), "")
        base = {"potions": "potion", "scrolls": "scroll", "rings": "ring"}.get(family, "")
        regular = self.data.get("exotic_to_regular", {}).get(kind, kind)
        known = not family or bool(game.get(regular + "_known", False))
        visible = known or reveal
        name = self.name(item)
        description = clean_text(self.messages.get(key + ".desc", ""))
        if not visible:
            label = str(game.get(regular + "_label", ""))
            name = self.messages.get(f"items.{family}.{base}.{label}", f"未鉴定{ {'potions': '药剂', 'scrolls': '卷轴', 'rings': '戒指'}[family] }")
            if family == "scrolls" and label:
                name = f"{label} 卷轴"
            if regular != kind:
                name = "合剂 · " + name if family == "potions" else "秘卷 · " + name
            description = clean_text(self.messages.get(f"items.{family}.{base}.unknown_desc", "效果尚未鉴定"))
        level_known = bool(item.get("levelKnown")) or reveal
        cursed_known = bool(item.get("cursedKnown")) or reveal
        level = visible_level(item, game, known=level_known)
        tier = self.tiers.get(kind)
        if kind in self.data.get("class_armors", []):
            saved_tier = item.get("armortier")
            tier = saved_tier if type(saved_tier) is int and 1 <= saved_tier <= 5 else None
        requirement = None
        if tier is not None:
            # Greataxe deliberately requires two more strength than normal tier 5.
            req_tier = tier + 1 if kind == "Greataxe" else tier
            requirement = strength_requirement(req_tier, level if level is not None else 0, bool(item.get("mastery_potion_bonus")))
        if kind == "SpiritBow" and level is not None:
            requirement = strength_requirement(1, level)
        details = []
        artifact_cap = self.data.get("artifact_caps", {}).get(kind)
        display_level = math.floor(level * 10 / artifact_cap + .5) if artifact_cap and level is not None else level
        level_applicable = level_applies(key)
        upgradable = level_applicable
        if level_known and display_level is not None and upgradable:
            name += f" {display_level:+d}"
        elif upgradable:
            details.append("等级暂缺上下文" if level_known else "等级未知")
        if item.get("cursed") and cursed_known:
            details.append("已知诅咒")
        elif upgradable:
            details.append("已知无诅咒" if cursed_known else "诅咒未知")
        if tier:
            details.append(f"{tier} 阶 · 力量 {requirement}" + ("（+0参考）" if not level_known else ""))
        if "curCharges" in item and (item.get("curChargeKnown") or reveal):
            details.append(f"{item['curCharges']} 次充能")
        volume = item.get('volume') if kind == 'Waterskin' and type(item.get('volume')) is int and 0 <= item['volume'] <= 20 else None
        if kind == "Waterskin":
            details.append(f"露珠 {volume}/20" if volume is not None else '露珠量未知')
        if kind == "MagesStaff" and isinstance(item.get("wand"), dict):
            wand = item["wand"]
            details.append(self.name(wand) + (f" · {wand.get('curCharges', '?')} 次" if wand.get("curChargeKnown") or reveal else ""))
        public = {"name": name, "kind": kind if visible else "Unknown" + base.title(),
                "key": key if visible else f"items.{family}.{base}", "quantity": max(1, int(number(item.get("quantity"), 1))),
                "location": location, "known": known, "level_known": level_known,
                "level": display_level if level_known and level_applicable else None,
                "level_applicable": level_applicable, "is_upgradable": scroll_upgradable(key), "cursed": bool(item.get("cursed")) if cursed_known else None,
                "tier": tier, "strength_requirement": requirement, "details": details, "description": description,
                "mastery": bool(item.get('mastery_potion_bonus')) if visible else None,
                "augmentation": item.get('augment', 'NONE') if visible else None,
                "volume": volume}
        public["alchemy_state"] = project_item_state(item, game, public)
        equipment = project_equipment_state(item, key, cursed_known, self.entry_index)
        public['equipment_state'] = equipment
        public['related'] = []
        if equipment:
            effect_id = equipment['effect_id']
            label = equipment['effect_kind']
            if effect_id:
                template = self.messages.get(effect_id + '.name', '')
                effect_name = clean_text(template.replace('%s', '')).strip() or self.entry_index[effect_id]['name']
                public['name'] = clean_text(template.replace('%s', public['name'])) if '%s' in template else public['name']
                public['details'].append(effect_name + label)
                public['description'] += '\n\n' + effect_name + label + '：' + self.entry_index[effect_id]['description']
                public['related'].append({**self.entry_index[effect_id], 'name': effect_name + label + ' · ' + public['name'],
                    'conditions': '已知装备效果；数值未计奥术之戒、天赋、魔免或其他触发强度修正'})
            if equipment['hardened'] is True:
                public['details'].append(label + '已硬化')
            elif equipment['hardened'] is None:
                public['details'].append('硬化状态未确认')
            if public['is_upgradable']:
                branch = ('已硬化：先核对硬化保护损失分支' if equipment['hardened'] is True else
                          '诅咒效果：核对诅咒附魔 / 刻印移除分支' if effect_id and '.curses.' in effect_id else
                          '正常效果：核对普通附魔 / 刻印消失分支' if effect_id else
                          '当前无可见附魔 / 刻印；未鉴定诅咒仍需核对，不能直接套用无效果分支')
                public['related'].append({**self.entry_index['items.scrolls.scrollofupgrade'],
                    'name': '升级风险 · ' + public['name'], 'conditions': branch + '；填写升级前等级，各分支不相加'})
        fruit_name = cooked_fruit_name(public["alchemy_state"], self.messages)
        if fruit_name:
            public["name"] = clean_text(fruit_name)
            potion_id = public['alchemy_state']['potion_id']
            suffix = 'desc_throw' if potion_id.rsplit('.', 1)[-1] in ('potionoffrost', 'potionofliquidflame', 'potionoftoxicgas', 'potionofparalyticgas') else 'desc_eat'
            public['description'] = clean_text(self.messages.get('items.food.blandfruit.desc_cooked', '已烹煮果实') + '\n\n' + self.messages.get('items.food.blandfruit.' + suffix, ''))
            public['details'].append('已烹煮 · ' + self.entry_index[potion_id]['name'])
            public['related'].append({**self.entry_index[potion_id], 'name': public['name'] + ' · 药剂效果',
                'conditions': '果实进食会对英雄施加该药剂效果；投掷分支和挑战条件须另行核对'})
        elif public['alchemy_state'].get('cooked') == 'raw':
            public['details'].append('未烹煮，不能直接进食')
        elif public['alchemy_state'].get('cooked') == 'unknown':
            public['details'].append('烹煮效果未确认')
        return public


def strength_requirement(tier, level, mastery=False):
    tier, level = int(tier), max(0, int(level))
    return 8 + 2 * tier - (math.isqrt(8 * level + 1) - 1) // 2 - (2 if mastery else 0)


def walk_inventory(hero):
    def visit(items, location, depth=0):
        if depth > 12 or not isinstance(items, list):
            return
        for item in items[:1000]:
            if not isinstance(item, dict):
                continue
            yield item, location
            yield from visit(item.get("inventory", []), "收纳袋", depth + 1)
    for slot, label in EQUIPMENT.items():
        if isinstance(hero.get(slot), dict):
            yield hero[slot], label
    yield from visit(hero.get("inventory", []), "背包")


def known_map(level, hero_pos):
    if not isinstance(level, dict):
        return None
    width, height = level.get("width"), level.get("height")
    if not isinstance(width, int) or not isinstance(height, int) or not 1 <= width <= 128 or not 1 <= height <= 128:
        return None
    tiles = level.get("map", [])
    visited, mapped = level.get("visited", []), level.get("mapped", [])
    if not all(isinstance(v, list) and len(v) == width * height for v in (tiles, visited, mapped)):
        return None
    safe_tiles = []
    for i, tile in enumerate(tiles):
        if not (visited[i] or mapped[i]):
            safe_tiles.append(-1)
        else:
            # A visited secret door/trap still looks like wall/floor in the game.
            safe_tiles.append({16: 4, 17: 1}.get(tile, tile) if isinstance(tile, int) else -1)
    pos = hero_pos if isinstance(hero_pos, int) and 0 <= hero_pos < len(tiles) else None
    return {"width": width, "height": height, "tiles": safe_tiles, "hero": pos,
            "explored": sum(t != -1 for t in safe_tiles), "caption": "最近保存的已探索地形；不代表当前视野"}


def analyze(game, catalog: Catalog, level=None, reveal=False):
    hero = game.get("hero", {})
    hp, ht = number(hero.get("HP")), max(1, number(hero.get("HT"), 1))
    depth = int(number(game.get("depth"), 1))
    buffs = [b for b in hero.get("buffs", []) if isinstance(b, dict)]
    # Java nested buffs are serialized as Outer$Inner (e.g. Viscosity$DeferedDamage).
    buff_types = {short_class(b).rsplit("$", 1)[-1] for b in buffs}
    locks = {"Paralysis": "麻痹", "Frost": "冰冻", "MagicalSleep": "魔法睡眠", "TimeStasis": "时间静止"}
    blocked = any(kind in buff_types for kind in locks)
    lock_label = "、".join(label for kind, label in locks.items() if kind in buff_types)
    movement_limited = blocked or "Roots" in buff_types
    flying = "Levitation" in buff_types
    lost_inventory = "LostInventory" in buff_types
    hunger = next((number(b.get("level"), None) for b in buffs if short_class(b) == "Hunger"), None)
    items = []
    for source, place in walk_inventory(hero):
        row = catalog.item(source, game, place, reveal)
        mining_pickaxe = short_class(source) == "Pickaxe" and isinstance(level, dict) and short_class(level) == "MiningLevel"
        row["available"] = not lost_inventory or source.get("kept_lost") is True or mining_pickaxe
        if lost_inventory:
            row["details"].insert(0, "遗落行囊期间可用" if row["available"] else "遗落行囊：未确认可用")
        row["instance_key"] = "item-" + str(len(items))
        items.append(row)
    character = scene_from_game(game, catalog, items)
    total_strength = character["strength"]["effective"] if character["strength"]["usable"] else number(hero.get("STR"), 10)
    inventory_counts = {}
    for item in items:
        if item["available"] and (item["known"] or reveal):
            inventory_counts[item["kind"]] = inventory_counts.get(item["kind"], 0) + item["quantity"]
    challenge_mask = int(number(game.get("challenges")))
    tips = []

    def tip(key, severity, title, body, basis):
        tips.append({"id": key, "severity": severity, "title": title, "body": body, "basis": basis})

    if hp <= 0:
        if "Berserk" in buff_types:
            tip("berserk_zero", "critical", "零生命：核对狂暴与护盾", "狂暴期间可能依靠护盾继续行动，不能仅凭 0 生命判断已经倒下。对照游戏中的狂暴状态与剩余护盾；若仍能行动，优先评估安全恢复，护盾耗尽有倒下风险。", "所示局势生命值 ≤ 0，且存在狂战士状态")
        else:
            tip("zero_hp", "critical", "生命值为 0：先核对游戏状态", "先确认游戏中的复活界面或结算状态。普通行动建议已暂停；请在游戏复活或开始新一局后更新局势。", "所示局势生命值 ≤ 0")
    elif hp / ht <= .25:
        text = "先停止自动探索，检查敌人和逃生手段。"
        if blocked:
            text += f"你正处于{lock_label}中，暂时不能使用物品或移动；控制解除后再选择救命手段。"
        elif inventory_counts.get("PotionOfHealing") and not challenge_mask & 4:
            text += "背包中有已鉴定的治疗药剂；治疗需要回合，优先确认能否安全使用。"
        else:
            text += "考虑已确认可用的控制、隐身或传送手段；避免用未知药剂赌救命。"
        tip("critical_hp", "critical", "生命值很低，先保命", text, f"生命 {hp:g}/{ht:g}（≤25%）")
    elif hp / ht < .5 and not blocked:
        text = "把敌人引到门口或窄道逐个处理。"
        if hunger is None:
            text += "饱食状态未知，先检查游戏中的饥饿状态；确认周围安全、没有持续伤害且没有进入饥饿后，再考虑休息。"
        elif hunger >= 450:
            text += "已经饥饿，不能依靠普通休息回血；先处理威胁并核对可用补给。"
        else:
            text += "休息前确认周围安全、没有持续伤害且没有进入饥饿。"
        tip("low_hp", "warning", "先恢复，再扩大探索", text, f"生命 {hp:g}/{ht:g}（<50%）")
    if blocked:
        tip("paralysis", "critical", lock_label + "期间无法主动行动", "暂时不能移动或使用物品。避免预先连点行动；控制解除后重新检查血量、其他状态与周围威胁。", f"局势中存在「{lock_label}」")
    if "Burning" in buff_types:
        text = "接触水能灭火，但不保证免掉紧接着的一次伤害。"
        if flying:
            text += "你正在漂浮，经过水格不会接触水，不能据此灭火。"
        if movement_limited:
            text += "当前不能正常移动，不能把走进水格作为立即可用的办法。"
        if not flying and not movement_limited:
            text += "先确认路线安全；不要穿过高草把火带开。"
        tip("burning", "critical", "正在燃烧：核对灭火条件", text, "局势中存在「燃烧」")
    if "Ooze" in buff_types:
        text = "接触水可洗掉腐蚀淤泥，但不保证免掉紧接着的一次伤害。它与「酸蚀」是不同的状态。"
        if flying:
            text += "漂浮时经过水格不能清洗。"
        if movement_limited:
            text += "当前不能正常移动，先核对控制状态，不能立即走到水中。"
        tip("ooze", "warning", "酸性淤泥：核对用水清洗条件", text, "局势中存在「腐蚀淤泥」")
    if "Corrosion" in buff_types:
        text = ("目前无法正常移动，先检查控制状态；能够行动后再脱离持续施加酸蚀的区域。" if movement_limited
                else "先离开持续施加酸蚀的区域，检查恢复或解除负面效果的资源。")
        tip("corrosion", "critical", "酸蚀会逐渐加重", text + "踏入水地不能照搬淤泥的处理方法。", "局势中存在「酸蚀」")
    if buff_types & {"Poison", "Bleeding", "DeferedDamage", "DeferredDamage"}:
        tip("dot", "warning", "持续伤害仍在结算", "不要用长时间休息推进回合。先查看游戏中的状态说明和剩余伤害，再决定恢复或撤离。", "存在中毒、流血或延缓伤害")
    if "Roots" in buff_types:
        tip("roots", "warning", "被缠绕，不能依赖走路脱身", "准备远程、控制或可用的传送手段；先核对技能说明。", "局势中存在「缠绕」")
    if "Cripple" in buff_types:
        tip("cripple", "warning", "残废会降低移动速度", "走一格可能让敌人多行动，别把普通走位当成安全拉扯。", "局势中存在「残废」")
    if lost_inventory:
        tip("lost_inventory", "warning", "行囊遗落：先核对随身物品", "复活后多数物品暂时不可用。遗落物品不能当作救命资源；先核对游戏中保留的装备，再规划找回行囊的安全路线。", "局势中存在「遗落行囊」；按复活后保留标记筛选可用资源")
    if hunger is not None and hunger >= 450:
        food_note = "进食前确认食物确实随身保留，遗落物品暂不可用。" if lost_inventory else "可在安全位置补充食物；吃东西也消耗回合。"
        tip("starving", "warning", "已经饥饿，休息无法正常回血", "先处理眼前威胁。" + food_note, f"饥饿值 {hunger:g} ≥450")
    elif hunger is not None and hunger >= 300:
        tip("hungry", "info", "开始饥饿，规划下一份食物", "优先有目的地探索。根据血量、下一场战斗和食物储备决定进食时机。", f"饥饿值 {hunger:g} ≥300")
    for item in items:
        if not item["available"]:
            continue
        if item["location"] in EQUIPMENT.values() and item["cursed"]:
            text = "避免把战术建立在能随时卸下它的前提上。"
            text += ("背包里有已鉴定的祛邪卷轴，可在安全且能行动时查看其使用选项。"
                     if inventory_counts.get("ScrollOfRemoveCurse") else "查看是否有已确认的解咒方法。")
            tip("curse_" + item["location"], "warning", item["location"] + "带有已知诅咒", text, item["name"])
        req = item["strength_requirement"]
        if hp > 0 and item["location"] in ("主武器", "副武器", "护甲") and req is not None and req > total_strength:
            qualifier = "已知需求" if item["level_known"] else "+0 参考需求（实际等级未知）"
            if character["strength"]["usable"]:
                text = f"{item['name']} 的{qualifier}为 {req}，按已确认角色条件计算的总力量为 {total_strength:g}。"
            else:
                text = f"{item['name']} 的{qualifier}为 {req}，基础力量为 {number(hero.get('STR'), 10):g}。"
                text += "总力量条件尚未确认；请核对戒指、天赋和临时加成。"
            text += ("若总力量仍不足，护甲会降低移动速度和闪避。" if item["location"] == "护甲"
                     else "若总力量仍不足，武器的命中和攻击速度会受影响。")
            if not item["level_known"]:
                text += "此装备尚未鉴定，不能据此断定超重。"
            tip("strength_" + item["location"], "info", "核对" + item["location"] + "的力量需求", text,
                "按公开阶数和等级核对；角色条件区分基础力量、已确认加成与未知状态")
    if hp > 0 and not blocked:
        if inventory_counts.get("PotionOfStrength"):
            tip("strength_potion", "info", "有可规划的永久成长资源", "背包中有已鉴定的力量药剂，饮用可提升基础力量。先处理威胁，安全且能行动时再使用；之后重新核对装备需求。", f"已知力量药剂 ×{inventory_counts['PotionOfStrength']}")
        if inventory_counts.get("ScrollOfUpgrade"):
            tip("upgrade_scroll", "info", "升级卷轴可以纳入装备规划", "先确定近期要使用的装备，再分配升级卷轴。升级降低力量需求有档位，并非每次升级都降低；可用「局势推演」页的计算器预估普通装备。", f"已知升级卷轴 ×{inventory_counts['ScrollOfUpgrade']}")
    if challenge_mask & 4:
        tip("pharmacophobia", "warning", "药水恐惧挑战已开启", "普通治疗药剂在此挑战下会伤害你，不能用作救命治疗。", "挑战掩码包含 NO_HEALING")
    branch = int(number(game.get("branch")))
    if not lost_inventory and branch == 0 and depth in (4, 9, 14, 19, 24):
        tip("boss_next", "info", "下一层是首领层", "下楼前确认血量、主装备力量需求、控制和撤离资源。先读对应首领条目，再进入战斗。", f"当前第 {depth} 层")
    if any(item["available"] and not item["known"] for item in items):
        tip("unknown", "info", "背包里有未鉴定物品", "在安全环境下结合已获得线索鉴定。颜色和符文每局变化，不能沿用上一局的对应关系。", "存在未鉴定药剂、卷轴或戒指")
    hero_class = hero.get("class", "")
    class_tips = {
        "MAGE": ("法师：善用充能，谨慎灌注", "魔杖适合先手和处理高闪避目标。更换法杖灌注前，先看游戏显示的最终等级预览。"),
        "WARRIOR": ("战士：检查纹章和护甲", "把纹章的作用、护甲力量需求和升级资源放在一起考虑；力量不足会影响战斗节奏。"),
        "ROGUE": ("盗贼：给暗影斗篷留余量", "把隐身作为调整站位和脱离夹击的资源，避免在安全路段把充能耗尽。"),
        "HUNTRESS": ("女猎手：先创造射击距离", "利用地形与远程先手；敌人贴身后，先判断能否安全脱离再移动。"),
        "DUELIST": ("决斗家：核对武技回合成本", "武器技能用途不同；根据命中、控制和站位选择技能，别只比较武器等级。"),
        "CLERIC": ("牧师：法术效果以当前说明为准", "进入战斗前检查圣典充能和可用法术，把防御与恢复资源纳入下一回合计划。"),
    }
    if not lost_inventory and hero_class in class_tips:
        title, body = class_tips[hero_class]
        tip("class", "info", title, body, CLASSES.get(hero_class, hero_class) + "通用策略")
    if hp <= 0:
        tips = [row for row in tips if row["id"] in ("zero_hp", "berserk_zero")]
    elif blocked:
        tips = [row for row in tips if row["id"] in ("critical_hp", "paralysis", "burning", "ooze", "corrosion", "dot", "pharmacophobia", "lost_inventory")]
    tips.sort(key=lambda row: {"critical": 0, "warning": 1, "info": 2}[row["severity"]])
    version = game.get("version")
    compatibility = ""
    if isinstance(version, int) and version > 0 and version != catalog.data["version_code"]:
        compatibility = f"存档版本码 {version} 与参考版本不同；手册和规则按 {catalog.data['version']}，差异请以游戏说明为准。"
    return {"hero": {"class": CLASSES.get(hero_class, str(hero_class)), "class_id": hero_class,
                     "subclass": hero.get("subClass", "NONE"), "level": int(number(hero.get("lvl"), 1)),
                     "hp": hp, "ht": ht, "strength": number(hero.get("STR"), 10),
                     "strength_label": "基础力量", "hunger": hunger,
                     "hunger_label": "未知" if hunger is None else "饥饿" if hunger >= 450 else "饥肠辘辘" if hunger >= 300 else "尚未饥饿"},
            "character_scene": character,
            "depth": depth, "branch": branch, "gold": number(game.get("gold")),
            "compatibility_warning": compatibility,
            "energy": number(game.get("energy")), "version": game.get("version"),
            "challenges": [name for bit, name in CHALLENGES.items() if challenge_mask & bit],
            "buffs": [{"name": catalog.name(b), "kind": short_class(b).rsplit("$", 1)[-1],
                       "active": b.get("state") == "BERSERK" if short_class(b) == "Berserk" else True,
                       **({"current_shield": b["shielding"]} if catalog.key(b) == "actors.buffs.barrier"
                          and type(b.get("shielding")) is int and 0 <= b["shielding"] <= 10000 else {})}
                      for b in buffs if short_class(b) not in ("Regeneration", "Hunger")],
            "items": items, "tips": tips, "map": known_map(level, hero.get("pos")),
            "region": region(depth, branch), "reveal": reveal}


def region(depth, branch=0):
    if branch:
        return "任务支线"
    return "下水道" if depth <= 5 else "监狱" if depth <= 10 else "洞穴" if depth <= 15 else "矮人都市" if depth <= 20 else "恶魔大厅" if depth <= 25 else "地牢尽头"
