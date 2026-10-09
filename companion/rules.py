"""Offline numerical rule reference. Never execute Java or user expressions."""

from __future__ import annotations

import ast
from functools import lru_cache
import json
import math
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "com.shatteredpixel.shatteredpixeldungeon."
NUMBER = re.compile(r"(?<![\w$])(?:0[xX][\da-fA-F_]+|0[bB][01_]+|(?:\d[\d_]*(?:\.[\d_]*)?|\.\d[\d_]*)(?:[eE][+-]?[\d_]+)?)[fFdDlL]?(?![\w$])")
LABELS = {"min": "最低基础伤害", "max": "最高基础伤害", "damageMin": "最低基础伤害",
          "damageMax": "最高基础伤害", "damageRoll": "基础伤害范围", "attackSkill": "基础命中",
          "drRoll": "基础减伤范围", "defenseSkill": "闪避", "STRReq": "力量需求",
          "chargesPerCast": "每次施法充能消耗", "baseChargeUse": "基础技能充能消耗",
          "duration": "持续时间", "proc": "触发效果", "act": "每次更新的效果",
          "speedMultiplier": "移动速度倍率", "attackDelayMultiplier": "攻击耗时倍率",
          "accuracyMultiplier": "命中倍率", "evasionMultiplier": "闪避倍率",
          "damageMultiplier": "伤害倍率", "stealthBonus": "潜行加成",
          "wandChargeMultiplier": "法杖充能倍率", "artifactChargeMultiplier": "神器充能倍率",
          "HTMultiplier": "最大生命倍率", "strengthBonus": "力量加成"}
FIELD_LABELS = {"HP": "初始生命", "HT": "初始最大生命", "tier": "装备阶数",
                "EXP": "基础经验", "maxLvl": "经验等级上限", "lootChance": "基础掉落概率",
                "defenseSkill": "基础闪避", "baseSpeed": "基础速度倍率"}


class UnknownFormula(ValueError):
    """Expression requires game state or semantics outside the safe subset."""


@lru_cache(maxsize=2)
def _load(path, modified, size):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def key_for(row):
    return row["id"].removeprefix(PREFIX).replace("$", ".")


class Range:
    def __init__(self, low, high):
        self.low, self.high = min(low, high), max(low, high)

    def __add__(self, other):
        if isinstance(other, Range):
            return Range(self.low + other.low, self.high + other.high)
        return Range(self.low + other, self.high + other)

    __radd__ = __add__

    def __mul__(self, other):
        if not isinstance(other, (int, float)):
            raise UnknownFormula()
        return Range(self.low * other, self.high * other)

    __rmul__ = __mul__


def display(value):
    if isinstance(value, Range):
        return f"{display(value.low)}–{display(value.high)}"
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise UnknownFormula()
    return str(value) if type(value) is int else f"{value:.6g}"


class Formula:
    """Tiny arithmetic AST interpreter; unsupported operations always fail closed."""

    def __init__(self, variables=None, call=None, attribute=None):
        self.variables, self.call, self.attribute = variables or {}, call, attribute

    def evaluate(self, expression):
        # Casts change Java semantics. Only a leading cast can be evaluated safely.
        expression = expression.strip()
        cast = re.match(r"^\((int|float|double)\)\s*", expression)
        if cast:
            expression = expression[cast.end():]
        def literal(match):
            value = match[0].replace("_", "")
            if value.lower().startswith(("0x", "0b")):
                return str(int(value.rstrip("lL"), 0))
            if value[-1:] in ("f", "F", "d", "D"):
                return repr(float(value[:-1]))
            value = value.rstrip("lL")
            if re.fullmatch(r"0[0-7]+", value):
                return str(int(value, 8))
            return value
        expression = NUMBER.sub(literal, expression)
        expression = re.sub(r"\s+", " ", expression)
        expression = expression.replace("Math.", "math.")
        if len(expression) > 1500 or re.search(r"[{};]|\bnew\b", expression):
            raise UnknownFormula()
        try:
            expression = self._ternary(expression)
            tree = ast.parse(expression, mode="eval")
            if cast and isinstance(tree.body, ast.BinOp) and not (expression.startswith("(") and self._whole_parentheses(expression)):
                raise UnknownFormula()
            if sum(1 for _ in ast.walk(tree)) > 150:
                raise UnknownFormula()
            result = self._node(tree.body)
            if cast and cast[1] == "int":
                result = math.trunc(result)
            elif cast:
                result = float(result)
            display(result)
            return result
        except (SyntaxError, TypeError, OverflowError, ZeroDivisionError, KeyError, AttributeError) as exc:
            raise UnknownFormula() from exc

    @staticmethod
    def _whole_parentheses(expression):
        depth = 0
        for index, char in enumerate(expression):
            depth += (char == "(") - (char == ")")
            if depth == 0:
                return index == len(expression) - 1
        return False

    @classmethod
    def _ternary(cls, expression):
        """Translate only balanced Java conditional expressions, retaining branches."""
        out, index = [], 0
        while index < len(expression):
            if expression[index] == "(":
                depth, end = 1, index + 1
                while end < len(expression) and depth:
                    depth += (expression[end] == "(") - (expression[end] == ")")
                    end += 1
                if depth:
                    raise UnknownFormula()
                out.append("(" + cls._ternary(expression[index+1:end-1]) + ")")
                index = end
            else:
                out.append(expression[index]); index += 1
        expression = "".join(out)
        depth = 0
        question = None
        for index, char in enumerate(expression):
            depth += (char == "(") - (char == ")")
            if char == "?" and depth == 0:
                question = index; break
        if question is None:
            return expression
        depth, nested = 0, 0
        for index in range(question+1, len(expression)):
            char = expression[index]
            depth += (char == "(") - (char == ")")
            if depth == 0:
                if char == "?": nested += 1
                elif char == ":":
                    if nested: nested -= 1
                    else:
                        cond = expression[:question].strip()
                        yes = cls._ternary(expression[question+1:index].strip())
                        no = cls._ternary(expression[index+1:].strip())
                        return f"({yes} if {cond} else {no})"
        raise UnknownFormula()

    def _node(self, node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.Name):
            return self.variables[node.id]
        if isinstance(node, ast.Attribute) and self.attribute:
            return self.attribute(ast.unparse(node))
        if isinstance(node, ast.IfExp):
            condition = self._node(node.test)
            if type(condition) is not bool:
                raise UnknownFormula()
            return self._node(node.body if condition else node.orelse)
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            a, b = self._node(node.left), self._node(node.comparators[0])
            op = node.ops[0]
            if isinstance(op, ast.Eq): return a == b
            if isinstance(op, ast.NotEq): return a != b
            if isinstance(op, ast.Lt): return a < b
            if isinstance(op, ast.LtE): return a <= b
            if isinstance(op, ast.Gt): return a > b
            if isinstance(op, ast.GtE): return a >= b
        if isinstance(node, ast.UnaryOp):
            value = self._node(node.operand)
            if isinstance(node.op, ast.USub):
                return -value
            if isinstance(node.op, ast.UAdd):
                return value
        if isinstance(node, ast.BinOp):
            a, b = self._node(node.left), self._node(node.right)
            if isinstance(node.op, ast.Add):
                return a + b
            if isinstance(node.op, ast.Sub):
                return a - b
            if isinstance(node.op, ast.Mult):
                return a * b
            if isinstance(node.op, ast.Div):
                return math.trunc(a / b) if type(a) is int and type(b) is int else a / b
            if isinstance(node.op, ast.Mod):
                return a - math.trunc(a / b) * b
        if isinstance(node, ast.Call) and not node.keywords:
            name = ast.unparse(node.func)
            args = [self._node(x) for x in node.args]
            functions = {"math.pow": math.pow, "math.sqrt": math.sqrt, "math.floor": math.floor,
                         "math.ceil": math.ceil, "math.round": lambda x: math.floor(x + 0.5),
                         "math.max": max, "math.min": min, "math.abs": abs}
            if name in functions:
                return functions[name](*args)
            if name in ("Random.NormalIntRange", "Random.IntRange") and len(args) == 2:
                return Range(*args)
            if self.call and re.fullmatch(r"(?:super\.)?\w+", name):
                return self.call(name, args)
        raise UnknownFormula()


class NumericRules:
    def __init__(self, catalog, path=None, data=None):
        if data is None:
            path = Path(path or ROOT / "data/numeric_rules.json")
            attrs = path.stat()
            data = _load(str(path), attrs.st_mtime_ns, attrs.st_size)
        self.data, self.classes, self.catalog = data, data["classes"], catalog
        self.entries = {row["id"]: row for row in catalog.entries}
        self.names = {PREFIX + row["id"]: row["name"] for row in catalog.entries}
        self.short_names = {}
        self._constants = {}
        for key, row in self.classes.items():
            self.short_names.setdefault(row["name"], []).append(key)
        self._search = {key: (row["fullname"] + " " + self.title(row) + " " + " ".join(
            r["body"] for r in row["rules"])).lower() for key, row in self.classes.items()}

    def title(self, row):
        key = key_for(row)
        if PREFIX + key in self.names:
            return self.names[PREFIX + key]
        message = self.catalog.messages.get(key + ".name", self.catalog.messages.get(key + ".title", ""))
        if message:
            name = re.sub(r"%(?:\d+\$)?[\d.]*[sdf]", "", message).replace("_", "").strip().strip("之")
            if name:
                return name + " · " + row["name"]
        return row["name"]

    def metadata(self):
        return {"version": self.data["version"], "commit": self.data["commit"],
                "coverage": {k: v for k, v in self.data["coverage"].items() if k != "files"},
                "entry_coverage": self.data.get("entry_coverage", {})}

    def search(self, query="", group="全部", offset=0, limit=40):
        terms = query.lower().split()
        rows = [r for key, r in self.classes.items() if (group == "全部" or group == r["group"])
                and all(term in self._search[key] for term in terms)]
        rows.sort(key=lambda r: (r["group"] == "界面与表现", query.lower() not in self.title(r).lower(),
                                 r.get("parent") is not None, self.title(r), r["id"]))
        return {**self.metadata(), "total": len(rows), "offset": offset, "limit": limit,
                "groups": sorted({r["group"] for r in self.classes.values()}),
                "entries": [{"id": r["id"], "name": self.title(r), "class_name": r["name"],
                             "category": r["group"], "path": r["path"],
                             "numeric_rules": sum(rule["numeric"] for rule in r["rules"])}
                            for r in rows[offset:offset + limit]]}

    def chain(self, identity):
        seen, rows = set(), []
        while identity and identity not in seen:
            seen.add(identity)
            row = self.classes[identity]
            rows.append(row)
            identity = row.get("base")
        return rows

    def source(self, row, line=None):
        return (f"https://github.com/00-Evan/shattered-pixel-dungeon/blob/{self.data['commit']}/"
                f"{row['path']}#L{line or row['line']}")

    def _rule(self, row, rule, inherited=False, overrides=()):
        literals = list(dict.fromkeys(m[0] for m in NUMBER.finditer(rule["body"])))
        signature = (rule["name"], tuple(p["type"] for p in rule["params"]))
        return {"id": rule["id"], "name": rule["name"], "label": LABELS.get(rule["name"], rule["name"]),
                "signature": rule["signature"], "kind": rule["kind"], "code": rule["code"],
                "line": rule["line"], "literals": literals, "numeric": rule["numeric"],
                "inherited": inherited, "overridden": inherited and signature in overrides,
                "source": self.source(row, rule["line"])}

    def detail(self, identity, level=0):
        entry = self.entries.get(identity)
        if entry:
            refs = entry.get("numeric_refs", [])
        elif identity in self.classes:
            refs = [{"class": identity}]
        else:
            raise KeyError(identity)
        sections, done = [], set()
        for ref in refs:
            owner = self.classes[ref["class"]]
            wanted = ref.get("rules")
            overrides = set()
            for depth, row in enumerate(self.chain(owner["id"])):
                if depth and wanted is not None:
                    break
                if (row["id"], tuple(wanted or [])) in done:
                    continue
                done.add((row["id"], tuple(wanted or [])))
                rules = [r for r in row["rules"] if wanted is None or r["id"] in wanted]
                sections.append({"id": row["id"], "name": self.title(row), "class_name": row["name"],
                                 "path": row["path"], "inherited": depth > 0,
                                 "source": self.source(row), "external_base": row.get("external_base", ""),
                                 "rules": [self._rule(row, r, depth > 0, overrides) for r in rules]})
                overrides.update((r["name"], tuple(p["type"] for p in r["params"]))
                                 for r in row["rules"] if r["kind"] == "method")
        examples = self.examples(refs[0]["class"], level) if refs and refs[0].get("rules") is None else []
        return {**self.metadata(), "id": identity, "name": entry["name"] if entry else self.title(owner),
                "status": entry.get("numeric_status", "indexed") if entry else "indexed",
                "note": entry.get("rule_scope_note", "") if entry else "",
                "examples": examples, "sections": sections, "level": level,
                "summary": entry.get("numbers", []) if entry else [],
                "summary_note": entry.get("numeric_note", "") if entry else ""}

    def _method(self, identity, name, count):
        for row in self.chain(identity):
            for rule in row["rules"]:
                if rule["kind"] == "method" and rule["name"] == name and len(rule["params"]) == count:
                    return row, rule
        raise UnknownFormula()

    def constants(self, identity, visited=None):
        top = visited is None
        visited = set(visited or ())
        if identity in visited or len(visited) > 12:
            raise UnknownFormula()
        if identity in self._constants:
            return self._constants[identity]
        visited.add(identity)
        values = {}
        for row in reversed(self.chain(identity)):
            for rule in row["rules"]:
                if rule["kind"] not in ("field", "initializer"):
                    continue
                body = rule["body"]
                assigned = re.findall(r"\b(\w+)\s*(?:[+*/-]?=(?!=)|\+\+|--)", body)
                for name in assigned:
                    values.pop(name, None)
                if re.search(r"\b(if|for|while|switch|new)\b|[{}?]", body):
                    continue
                for statement in body.split(";"):
                    # Only numeric declarations/assignments; chained HP=HT is supported.
                    match = re.search(r"\b(\w+)\s*=\s*((?:\w+\s*=\s*)*)(.+)$", statement.strip(), re.S)
                    if not match:
                        continue
                    if match[1] in ("image", "icon", "hitSoundPitch", "collisionProperties", "hitSound", "spriteClass", "defaultAction"):
                        continue
                    try:
                        value = Formula(values, attribute=lambda ref: self.constant_reference(row, ref, visited)).evaluate(match[3])
                        for name in [match[1], *re.findall(r"(\w+)\s*=", match[2])]:
                            values[name] = value
                    except UnknownFormula:
                        pass
        # Ordinary armor constructors assign tier through super(tier).
        row = self.classes[identity]
        tier = self.catalog.tiers.get(row["name"])
        if tier is not None and key_for(row).startswith("items.armor."):
            values["tier"] = tier
        if top:
            self._constants[identity] = values
        return values

    def constant_reference(self, row, reference, visited):
        owner, _, name = reference.rpartition(".")
        candidates = [owner.lower(), (row["package"] + "." + owner).lower(),
                      row["imports"].get(owner, "").lower()]
        candidates.extend(self.short_names.get(owner, []) if len(self.short_names.get(owner, [])) == 1 else [])
        identity = next((c for c in candidates if c in self.classes), None)
        if identity is None:
            raise UnknownFormula()
        try:
            return self.constants(identity, visited)[name]
        except KeyError as exc:
            raise UnknownFormula() from exc

    def calculate(self, identity, name, args, level=0, context=None, depth=0):
        if depth > 12:
            raise UnknownFormula()
        row, rule = self._method(identity, name, len(args))
        variables = {**self.constants(identity), **dict(zip((p["name"] for p in rule["params"]), args)),
                     **(context or {})}
        def call(method, params):
            if method in ("level", "buffedLvl") and not params:
                return level
            if method == "chargesPerCast" and not params and "charges" in variables:
                return variables["charges"]
            base = row["base"] if method.startswith("super.") else identity
            return self.calculate(base, method.removeprefix("super."), params, level, context, depth + 1)
        body = rule["body"].strip()
        # No condition, assignment or side effect is approximated as a direct formula.
        match = re.fullmatch(r"return\s+([^;]+);", body, re.S)
        if not match:
            raise UnknownFormula()
        result = Formula(variables, call).evaluate(match[1])
        if rule["return_type"] == "int" and not isinstance(result, Range):
            return math.trunc(result)
        return result

    def examples(self, identity, selected_level=0):
        row, result = self.classes[identity], []
        constants = self.constants(identity)
        short = key_for(row)
        chain = {key_for(r) for r in self.chain(identity)}
        levels = sorted(set([*range(11), selected_level]))
        fields = [{"label": label, "value": display(constants[name])} for name, label in FIELD_LABELS.items()
                  if name in constants and (short.startswith("actors.mobs.") or name == "tier")]
        if fields:
            result.append({"title": "基础属性", "note": "未计入挑战、精英、飞升、天赋或临时状态的修正。",
                           "values": fields})
        extra = []
        wanted = {"duration": "持续时间", "energy": "基础饱食恢复量", "TIME_TO_EAT": "基础进食时间",
                  "TIME_TO_DRINK": "饮用时间", "TIME_TO_READ": "阅读时间", "DURATION": "基础持续时间",
                  "HUNGRY": "进入饥饿的饱食值", "STARVING": "饥饿掉血的饱食值", "STEP": "基础更新间隔",
                  "TICK": "游戏时间单位", "MAX_LEVEL": "最高角色等级", "levelCap": "内部等级上限"}
        own_names = {m[0].strip() for r in row["rules"] if r["kind"] in ("field", "initializer")
                     for m in re.finditer(r"\b\w+\s*(?==)", r["body"])}
        for name, label in wanted.items():
            if name in constants and name in own_names:
                extra.append({"label": label, "value": display(constants[name])})
        if extra:
            result.append({"title": "基础时间与资源数值", "note": "来自属性与常量；特定挑战、天赋或状态可以改变实际效果。时间按游戏时间单位。", "values": extra})
        columns, values = [], []
        methods = ("min", "max") if "items.weapon.weapon" in chain or "items.wands.damagewand" in chain else ()
        for name in methods:
            try:
                calculated = [display(self.calculate(identity, name, [lvl], lvl)) for lvl in levels]
                columns.append(LABELS[name])
                values.append(calculated)
            except UnknownFormula:
                pass
        if columns:
            result.append({"title": "装备等级数值表", "note": "L 为有效等级；基础伤害，未加其他修正。范围端点不代表等概率。",
                           "columns": ["L", *columns],
                           "rows": [[str(lvl), *(v[index] for v in values)] for index, lvl in enumerate(levels)]})
        if short == "items.wands.wandoffireblast":
            result.append({"title": "焰浪法杖：按实际消耗充能分开计算", "note": "L 为有效等级；当前可用充能决定 C。未加天赋或目标抗性。",
                           "columns": ["L", "C=1 伤害", "C=2 伤害", "C=3 伤害"],
                           "rows": [[str(l), f"{1+l}–{2+2*l}", f"{2*(1+l)}–{2*(4+2*l)}", f"{3*(1+l)}–{3*(6+2*l)}"] for l in levels]})
        tier = constants.get("tier")
        from .engine import strength_requirement
        from .values_decisions import armor_ranges
        if "items.armor.armor" in chain and isinstance(tier, int) and "items.armor.classarmor" not in chain:
            result.append({"title": "护甲基础减伤", "note": "无强化符石及刻印修正；负等级按装备基础规则计算，力量需求按非负等级。信念护体列单独计算。力量未使用精通药剂。",
                           "columns": ["L", "常规减伤", "信念护体", "力量需求"],
                           "rows": [[str(l), f"{armor_ranges(tier,l)[0]}–{armor_ranges(tier,l)[1]}", f"0–{armor_ranges(tier,l)[2]}", str(strength_requirement(tier,l))] for l in levels]})
        if "items.weapon.melee.meleeweapon" in chain and isinstance(tier, int):
            strength_tier = 6 if short == "items.weapon.melee.greataxe" else tier
            result.append({"title": "力量需求", "note": "有效等级 L，未使用精通药剂；已使用时再减 2。巨斧有单独需求规则。",
                           "columns": ["L", "力量"], "rows": [[str(l), str(strength_requirement(strength_tier,l))] for l in levels]})
        if short.startswith("items.rings.ringof"):
            # Evaluate only direct expressions, explicitly under the solo uncursed assumption.
            ring_fields = []
            for rule in row["rules"]:
                match = re.fullmatch(r"return\s+([^;]+);", rule["body"].strip(), re.S)
                if not match or "getBuffedBonus(" not in match[1]:
                    continue
                expression = re.sub(r"getBuffedBonus\([^)]*\)", "B", match[1])
                try:
                    normal = [display(Formula({"B": l+1}).evaluate(expression)) for l in levels]
                    cursed = [display(Formula({"B": min(0, l-2)}).evaluate(expression)) for l in levels]
                    ring_fields.append((LABELS.get(rule["name"], rule["name"]), normal, cursed))
                except UnknownFormula:
                    continue
            if ring_fields:
                result.append({"title": "戒指效果表", "note": "仅一枚戒指，无天赋及其他等级加成。正常 B=L+1；诅咒 B=min(0,L−2)。同类多戒指和力量临时加成需按下面规则计算。",
                               "columns": ["L", *(label + suffix for label, _, _ in ring_fields for suffix in (" · 正常", " · 诅咒"))],
                               "rows": [[str(l), *(v[index] for _, normal, cursed in ring_fields for v in (normal, cursed))] for index, l in enumerate(levels)]})
        if short.startswith("actors.mobs."):
            stats = []
            for name, args in (("damageRoll", []), ("attackSkill", [None]), ("drRoll", [])):
                try:
                    stats.append({"label": LABELS[name], "value": display(self.calculate(identity, name, args))})
                except UnknownFormula:
                    pass
            if stats:
                result.append({"title": "基础战斗数值", "note": "随机范围端点；正态整数抽样偏向中间值。条件分支见完整规则。", "values": stats})
        return result
