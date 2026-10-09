"""Conservative numeric reference extraction from the pinned official Java files."""

import re

COMMIT = "57a4e06a4caf162446d1c28caa7983f0493fecf0"
BASE = f"https://github.com/00-Evan/shattered-pixel-dungeon/blob/{COMMIT}/core/src/main/java/com/shatteredpixel/shatteredpixeldungeon/"
METHODS = {"min": "最低基础伤害", "max": "最高基础伤害", "damageRoll": "基础伤害随机范围",
           "attackSkill": "基础命中", "drRoll": "基础减伤随机范围", "damageMin": "最低基础伤害",
           "damageMax": "最高基础伤害", "baseChargeUse": "基础技能充能消耗", "chargesPerCast": "每次施法充能消耗"}
FIELDS = {"HP": "初始生命", "HT": "初始最大生命", "defenseSkill": "基础闪避", "EXP": "基础经验",
          "maxLvl": "获得经验的角色等级上限", "baseSpeed": "基础速度倍率", "lootChance": "基础掉落概率"}


def stripped(text):
    return re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)


def simple_methods(text):
    result = {}
    for match in re.finditer(r"(?:public|protected)\s+(?:static\s+|final\s+)*(?:int|float)\s+(\w+)\s*\(([^)]*)\)\s*\{", text):
        depth, end = 1, match.end()
        while end < len(text) and depth:
            depth += (text[end] == "{") - (text[end] == "}")
            end += 1
        body = text[match.end():end-1].strip()
        direct = re.fullmatch(r"return\s+([^;]+);", body, re.S)
        # Presence of an override blocks an inherited formula even if nontrivial.
        result[match[1]] = re.sub(r"\s+", " ", direct[1]).strip() if direct else None
    return result


def enrich(entries, src, messages, tiers):
    sources = {}
    for path in sorted(src.rglob("*.java")):
        relative = path.relative_to(src).as_posix()
        key = relative[:-5].replace("/", ".").lower()
        text = stripped(path.read_text(encoding="utf-8"))
        sources[key] = (relative, text, simple_methods(text))
    melee = sources["items.weapon.melee.meleeweapon"][2]
    numeric_count = 0
    for entry in entries:
        key = entry["id"]
        source = sources.get(key)
        if not source:
            # A translated nested state may be defined in its enclosing file.
            candidate = max((k for k in sources if key.startswith(k + ".") or key.startswith(k + "$")), key=len, default=None)
            if candidate:
                entry["source"] = BASE + sources[candidate][0]
            continue
        relative, text, methods = source
        entry["source"] = BASE + relative
        rows = []
        def add(label, value):
            rows.append({"label": label, "value": str(value)})
        declaration = re.search(r"\bclass\s+\w+[^\{]*\{", text)
        start = declaration.end() if declaration else 0
        initial = text[start:]
        first_method = re.search(r"(?:public|protected|private)\s+(?:static\s+|final\s+)*[\w<>\[\]]+\s+\w+\s*\([^;]*?\)\s*\{", initial)
        initial = initial[:first_method.start()] if first_method else initial
        if key.startswith("actors.mobs."):
            for field, label in FIELDS.items():
                match = re.search(r"\b" + field + r"\s*=\s*(?:HT\s*=\s*)?(-?\d+(?:\.\d+)?)[fF]?\s*;", initial)
                if match:
                    add(label, match[1])
        tier = tiers.get(relative.rsplit("/", 1)[-1][:-5])
        if tier:
            add("装备阶数 T", tier)
        if key.startswith("items.weapon.melee.") and tier:
            combined = {**melee, **methods}
        else:
            combined = methods
        for method, label in METHODS.items():
            expression = combined.get(method)
            if expression and len(expression) < 190:
                expression = re.sub(r"\blvl\b|\blevel\b", "L", expression)
                expression = re.sub(r"\btier\b", str(tier) if tier else "T", expression)
                direct_range = re.fullmatch(r"Random.NormalIntRange\(\s*(\d+)\s*,\s*(\d+)\s*\)", expression)
                if direct_range:
                    expression = f"{direct_range[1]}–{direct_range[2]}（正态整数随机）"
                add(label, expression)
        for name, value in re.findall(r"(?:public|protected|private)\s+static\s+final\s+(?:int|float|double)\s+(\w+)\s*=\s*(-?\d+(?:\.\d+)?)[fFdD]?\s*;", initial):
            add("源码常量 " + name, value)
        if key.startswith("items.armor.") and tier and "classarmor" not in key:
            add("普通护甲基础减伤（L≥0，无强化符石/挑战）", f"L 至 {tier}×(2+L)；+0 为 0–{tier*2}")
        if key == "items.potions.potionofhealing":
            add("常规总治疗量（逐步恢复）", "向下取整(0.8×最大生命 + 14)，受最大生命上限限制；药水恐惧挑战会改为中毒")
        if key == "actors.buffs.hunger":
            add("进入饥饿", "300；进入饥饿掉血状态 450。通常每游戏时间单位增加 1，特殊状态/饰品可改变")
        if rows:
            numeric_count += 1
            entry["numbers"] = rows
            entry["numeric_note"] = "4.0.2 基础规则；L 为有效装备等级，T 为阶数。公式中的 Random 为随机函数，super 为父类规则。未计入天赋、强化、状态、精英、飞升及挑战等修正。源码常量按所属文件列出，具体适用条件见原文。"
    for hero in ("warrior", "mage", "rogue", "huntress", "duelist", "cleric"):
        stem = "actors.hero.heroclass." + hero
        entries.append({"id": stem, "name": messages[stem], "description": messages[stem + "_desc"],
                        "category": "角色与机制", "hint": messages[stem + "_unlock"],
                        "numbers": [{"label": "初始生命 / 基础力量", "value": "20 / 10"},
                                    {"label": "常规最大生命", "value": "20 + 5×(角色等级−1)，生命加成、戒指等另计"},
                                    {"label": "升至下一等级的经验", "value": "5 + 5×当前等级；最高等级 30"}],
                        "source": BASE + "actors/hero/Hero.java", "numeric_note": "普通初始角色基础值；职业特色和开局装备见说明。"})
    rules = [
        ("strength", "力量需求与升级", "选择装备阶数与等级即可查看力量需求。精通药剂可额外降低需求2点。巨斧的力量需求高于普通5阶武器。", "items/weapon/melee/MeleeWeapon.java"),
        ("regeneration", "自然恢复与饥饿", "普通自然恢复每 10 个游戏时间单位恢复 1 HP，需要未饥饿掉血且允许恢复。血之圣杯、盐块等会改变速度；锁定楼层有额外限制。现实秒数不等于游戏回合。", "actors/buffs/Regeneration.java"),
        ("accuracy", "命中与闪避的概率", "填入攻击者命中值与目标闪避值，查看普通物理攻击的命中概率。两者相等时为50%。伏击、祝福和其他特殊状态可以改变结果；无限闪避优先于必中。", "actors/Char.java"),
        ("armor", "护甲减伤与挑战", "选择护甲阶数与等级，查看普通护甲和信念护体挑战下的减伤范围。强化符石、刻印和临时状态会改变最终结果。命中之后才进行护甲减伤。", "items/armor/Armor.java"),
        ("drops", "每区域的成长资源", "常规主地牢每组 5 层安排 2 瓶力量药剂和 3 张升级卷轴，具体楼层随机；首领层通常不生成这类资源。挑战与特殊生成情形需单独核对。", "Dungeon.java"),
        ("saving", "游戏何时保存与回档边界", "游戏内保存后，灯火每10秒检查并备份已经稳定保存的局势。游戏尚未保存的动作不能被时光机记录。可在时光机页面选择历史节点回档。", "Dungeon.java"),
    ]
    for key, name, description, relative in rules:
        entries.append({"id": "mechanics." + key, "name": name, "description": description,
                        "category": "角色与机制", "hint": "", "source": BASE + relative,
                        "numbers": [{"label": "适用版本", "value": "4.0.2 / 版本码 922"}],
                        "numeric_note": "基础规则及边界见说明，行动前核对实际游戏状态。"})
    return numeric_count + 12
