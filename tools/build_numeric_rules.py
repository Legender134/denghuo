"""Index every executable numeric literal and its complete enclosing Java rule.

Comments and strings are masked without changing offsets. This is a source index,
not a Java interpreter: conditional bodies are preserved rather than guessed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / ".research/player-upstream-4.0.1"
PREFIX = "com.shatteredpixel.shatteredpixeldungeon."
COMMIT = "e9defd0444c96d2fce3de5ec297c3398be8b7c55"
VERSION = "4.0.1"
NUMBER = re.compile(r"(?<![\w$])(?:0[xX][0-9a-fA-F_]+(?:\.[0-9a-fA-F_]*)?(?:[pP][+-]?[0-9_]+)?[fFdDlL]?|0[bB][01_]+[lL]?|(?:\d[\d_]*(?:\.[\d_]*)?|\.[\d_]+)(?:[eE][+-]?[\d_]+)?[fFdDlL]?)(?![\w$])")
TYPES = re.compile(r"\b(class|interface|enum)\s+(\w+)([^;{}]*?)\{")
METHOD = re.compile(r"([\w$]+)\s*\(([^()]*)\)\s*(?:throws\s+[\w.,\s]+)?$")


def mask_java(text):
    """Remove comments, strings and chars, preserving every source position."""
    out = list(text)
    i = 0
    while i < len(text):
        start = i
        if text.startswith("//", i):
            end = text.find("\n", i)
            i = len(text) if end < 0 else end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                raise ValueError("Unclosed Java comment")
            i = end + 2
        elif text[i] in ('"', "'"):
            quote = text[i]
            if text.startswith('"""', i):
                end = text.find('"""', i + 3)
                if end < 0:
                    raise ValueError("Unclosed Java text block")
                i = end + 3
            else:
                i += 1
                while i < len(text):
                    if text[i] == "\\":
                        i += 2
                    elif text[i] == quote:
                        i += 1
                        break
                    else:
                        i += 1
        else:
            i += 1
            continue
        for k in range(start, min(i, len(text))):
            if text[k] not in "\r\n":
                out[k] = " "
    return "".join(out)


def brace_pairs(masked):
    stack, result = [], {}
    for i, char in enumerate(masked):
        if char == "{":
            stack.append(i)
        elif char == "}":
            if not stack:
                raise ValueError("Unexpected closing brace")
            result[stack.pop()] = i
    if stack:
        raise ValueError("Unclosed brace")
    return result


def category(relative):
    if relative.startswith("items/"):
        return "物品"
    if relative.startswith("actors/hero/"):
        return "角色与天赋"
    if relative.startswith("actors/mobs/"):
        return "敌人与角色"
    if relative.startswith(("actors/buffs/", "actors/blobs/")):
        return "状态与气体"
    if relative.startswith("plants/"):
        return "植物"
    if relative.startswith(("levels/", "mechanics/")):
        return "地形与机制"
    if relative.startswith(("ui/", "windows/", "sprites/", "effects/", "scenes/")):
        return "界面与表现"
    return "全局与基础机制"


def line_number(text, position):
    return text.count("\n", 0, position) + 1


def parse_file(text, repository_path, relative):
    masked = mask_java(text)
    pairs = brace_pairs(masked)
    package = re.search(r"\bpackage\s+([\w.]+)\s*;", masked)
    package = package[1] if package else ""
    imports = {p.rsplit(".", 1)[-1]: p for p in re.findall(r"\bimport\s+(?!static\b)([\w.]+)\s*;", masked)}
    classes, spans = [], []
    for match in TYPES.finditer(masked):
        opening = match.end() - 1
        closing = pairs[opening]
        parent = next((r for r in reversed(classes) if r["start"] < match.start() < r["end"]), None)
        fullname = (parent["fullname"] + "$" if parent else package + ".") + match[2]
        ancestor = re.search(r"\bextends\s+([\w.$]+)", match[3])
        row = {"id": fullname.lower(), "fullname": fullname, "name": match[2], "kind": match[1],
               "base_name": ancestor[1] if ancestor else "", "parent": parent["id"] if parent else None,
               "package": package, "imports": imports, "path": repository_path,
               "group": category(relative), "start": match.start(), "open": opening, "end": closing,
               "line": line_number(text, match.start()), "rules": []}
        classes.append(row)
    for row in classes:
        start = row["open"] + 1
        i, parentheses = start, 0
        children = {child["start"]: child for child in classes if child["parent"] == row["id"]}
        while i < row["end"]:
            char = masked[i]
            if char == "(":
                parentheses += 1
            elif char == ")":
                parentheses -= 1
            if char == "{" and parentheses == 0:
                end = pairs[i] + 1
                header = masked[start:i].strip()
                child = next((child for position, child in children.items() if start <= position <= i), None)
                if child:
                    start, i = end, end
                    continue
                method = METHOD.search(header)
                # Braces in an array field remain part of the field through ';'.
                is_array = "=" in header and ("new " in header or header.endswith("="))
                if is_array:
                    i = end
                    continue
                name = method[1] if method else "初始化"
                params = []
                if method and method[2].strip():
                    for param in method[2].split(","):
                        bits = param.strip().split()
                        params.append({"type": " ".join(bits[:-1]), "name": bits[-1]})
                before = header[:method.start()].strip().split() if method else []
                return_type = before[-1] if before else ""
                record = {"name": name, "signature": re.sub(r"\s+", " ", header),
                          "kind": "method" if method else "initializer", "params": params,
                          "return_type": return_type, "start": start, "end": end,
                          "body": masked[i+1:end-1].strip(), "code": text[start:end].strip(),
                          "line": line_number(text, start)}
                row["rules"].append(record)
                spans.append((start, end))
                start, i = end, end
                continue
            if char == ";" and parentheses == 0:
                end = i + 1
                header = masked[start:end].strip()
                if header:
                    record = {"name": header.split("=", 1)[0].strip().split()[-1],
                              "signature": re.sub(r"\s+", " ", header), "kind": "field",
                              "params": [], "return_type": "", "start": start, "end": end,
                              "body": header, "code": text[start:end].strip(), "line": line_number(text, start)}
                    row["rules"].append(record)
                    spans.append((start, end))
                start = end
            i += 1
    literals = list(NUMBER.finditer(masked))
    uncovered = [match for match in literals if not any(a <= match.start() < b for a, b in spans)]
    if uncovered:
        # Preserve uncommon declarations or annotations as an explicit file rule.
        if not classes:
            raise ValueError(f"Numeric file without a type: {repository_path}")
        row = classes[0]
        row["rules"].append({"name": "其他声明", "signature": "其他声明与注解", "kind": "file",
                             "params": [], "return_type": "", "start": 0, "end": len(text),
                             "body": masked, "code": text[row["start"]:row["end"]+1], "line": row["line"]})
    covered = 0
    for row in classes:
        for index, rule in enumerate(row["rules"]):
            nums = list(NUMBER.finditer(masked, rule["start"], rule["end"]))
            rule["literals"] = len(nums)
            rule["id"] = f"{row['id']}:{index}"
            rule["numeric"] = bool(nums)
            covered += len(nums)
            rule["source_start"], rule["source_end"] = rule["start"], rule["end"]
            rule["line"] = line_number(text, rule["start"] + len(text[rule["start"]:rule["end"]]) - len(text[rule["start"]:rule["end"]].lstrip()))
            del rule["start"], rule["end"]
        for key in ("start", "open", "end"):
            del row[key]
    return classes, {"path": repository_path, "sha256": hashlib.sha256(text.encode()).hexdigest(),
                     "numeric_literals": len(literals), "uncovered_literals": 0,
                     "fallback_literals": len(uncovered), "indexed_occurrences": covered}


def resolve_bases(classes):
    by_full = {row["fullname"]: row["id"] for row in classes.values()}
    by_short = {}
    for row in classes.values():
        by_short.setdefault(row["name"], []).append(row["id"])
    for row in classes.values():
        name = row.pop("base_name")
        candidates = [name, row["package"] + "." + name, row["imports"].get(name)]
        parent = row.get("parent")
        while parent:
            outer = classes[parent]
            candidates.insert(0, outer["fullname"] + "$" + name)
            parent = outer.get("parent")
        base = next((by_full[value] for value in candidates if value in by_full), None)
        if not base and len(by_short.get(name, [])) == 1:
            base = by_short[name][0]
        row["base"] = base
        row["external_base"] = name if name and not base else ""


def build(upstream=UPSTREAM):
    git = shutil.which("git") or "C:/Program Files/Git/cmd/git.exe"
    head = subprocess.check_output([git, "-C", str(upstream), "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output([git, "-C", str(upstream), "status", "--porcelain"], text=True).strip()
    if head != COMMIT or dirty:
        raise ValueError("资料生成要求完整且未修改的官方固定提交")
    roots = [(upstream / "core/src/main/java/com/shatteredpixel/shatteredpixeldungeon", "game"),
             (upstream / "SPD-classes/src/main/java/com/watabou", "engine")]
    classes, files = {}, []
    for root, _ in roots:
        for path in sorted(root.rglob("*.java")):
            text = path.read_text(encoding="utf-8")
            parsed, coverage = parse_file(text, path.relative_to(upstream).as_posix(), path.relative_to(root).as_posix())
            files.append(coverage)
            for row in parsed:
                if row["id"] in classes:
                    raise ValueError(f"Duplicate class identity: {row['id']}")
                classes[row["id"]] = row
    resolve_bases(classes)
    return {"format": 1, "version": VERSION, "commit": COMMIT, "classes": classes,
            "coverage": {"files": files, "file_count": len(files), "class_count": len(classes),
                         "numeric_literals": sum(r["numeric_literals"] for r in files),
                         "uncovered_literals": sum(r["uncovered_literals"] for r in files),
                         "fallback_literals": sum(r["fallback_literals"] for r in files)}}


def main():
    data = build()
    output = ROOT / "data/numeric_rules.json"
    output.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({k: v for k, v in data["coverage"].items() if k != "files"}, ensure_ascii=False))


def attach_catalog(entries, messages, data):
    """Map translations, nested types and enum effects to exact source rules."""
    classes = data["classes"]
    normalized = {key.removeprefix(PREFIX).replace("$", "."): key for key in classes}
    symbols = {}
    for key, row in classes.items():
        for rule in row["rules"]:
            for enum, symbol in re.findall(r"\b(Talent|HeroSubClass|HeroClass)\.([A-Z][A-Z_]+)\b", rule["body"]):
                symbols.setdefault((enum, symbol), []).append({"class": key, "rules": [rule["id"]]})
    existing = {row["id"] for row in entries}
    talent_id = (PREFIX + "actors.hero.Talent").lower()
    talent_header = " ".join(rule["body"] for rule in classes[talent_id]["rules"] if rule["kind"] == "field")
    caps = {symbol.lower(): int(cap or 2) for symbol, cap in re.findall(r"\b([A-Z][A-Z_]+)\s*\(\s*\d+\s*(?:,\s*(\d+)\s*)?\)", talent_header)}
    for key, row in classes.items():
        if not key.startswith(talent_id):
            continue
        for rule in row["rules"]:
            if rule["kind"] == "field":
                continue
            for symbol in set(re.findall(r"\b[A-Z][A-Z_]+\b", rule["body"])):
                if symbol.lower() in caps:
                    symbols.setdefault(("Talent", symbol), []).append({"class": key, "rules": [rule["id"]]})
    for key, name in messages.items():
        if key.startswith("actors.hero.talent.") and key.endswith(".title"):
            stem = key[:-6]
            description = messages.get(stem + ".desc")
            if description and stem not in existing:
                entries.append({"id": stem, "name": name, "description": description,
                                "category": "天赋与能力", "hint": "",
                                "numbers": ([{"label": "最大天赋点数", "value": str(caps[stem.rsplit('.', 1)[-1]])}]
                                            if stem.rsplit(".", 1)[-1] in caps else [])})
                existing.add(stem)
        if key.startswith("actors.hero.herosubclass.") and key.endswith("_desc"):
            stem = key[:-5]
            if stem in messages and stem not in existing:
                entries.append({"id": stem, "name": messages[stem], "description": name,
                                "category": "角色与机制", "hint": ""})
                existing.add(stem)
        if key.endswith(".ability_name"):
            stem = key[:-13]
            identity = stem + ".ability"
            if stem in normalized and identity not in existing:
                desc = messages.get(stem + ".ability_desc", messages.get(stem + ".typical_ability_desc", ""))
                if desc:
                    entries.append({"id": identity, "name": name, "description": desc,
                                    "category": "天赋与能力", "hint": "", "ability_owner": stem})
                    existing.add(identity)
    mechanics = {"strength": "items.weapon.melee.MeleeWeapon", "regeneration": "actors.buffs.Regeneration",
                 "accuracy": "actors.Char", "armor": "items.armor.Armor", "drops": "Dungeon", "saving": "Dungeon"}
    for entry in entries:
        key = entry["id"].replace("$", ".")
        refs = []
        if key in normalized:
            refs.append({"class": normalized[key]})
        elif entry.get("ability_owner") in normalized:
            owner = normalized[entry["ability_owner"]]
            wanted = [r["id"] for r in classes[owner]["rules"] if "ability" in r["name"].lower() or "charge" in r["name"].lower()]
            refs.append({"class": owner, "rules": wanted})
        elif key.startswith("actors.hero.talent."):
            symbol = key.rsplit(".", 1)[-1].upper()
            refs = symbols.get(("Talent", symbol), [])
        elif key.startswith("actors.hero.herosubclass."):
            symbol = key.rsplit(".", 1)[-1].upper()
            refs = symbols.get(("HeroSubClass", symbol), [])
        elif key.startswith("actors.hero.heroclass."):
            symbol = key.rsplit(".", 1)[-1].upper()
            refs = [{"class": (PREFIX + "actors.hero.Hero").lower()}] + symbols.get(("HeroClass", symbol), [])
        elif key.startswith("mechanics."):
            refs = [{"class": (PREFIX + mechanics[key[10:]]).lower()}]
        else:
            # Translated inner effects can use a parent's message namespace.
            parent = max((candidate for candidate in normalized if key.startswith(candidate + ".")), key=len, default=None)
            if parent:
                refs = [{"class": normalized[parent]}]
                entry["rule_scope_note"] = "该说明属于此类的内部效果，下面保留所属类的完整条件，不能把所有分支当作同时生效。"
        unique = {}
        for ref in refs:
            identity = (ref["class"], tuple(ref.get("rules", [])))
            unique[identity] = ref
        entry["numeric_refs"] = list(unique.values())
        entry["numeric_status"] = "indexed" if refs else "legacy"
        if not refs:
            entry["rule_scope_note"] = "此条目仅存在于旧版，当前版本不再提供。"
    data["entry_coverage"] = {"total": len(entries), "indexed": sum(bool(r["numeric_refs"]) for r in entries),
                              "legacy": [{"id": r["id"], "name": r["name"]} for r in entries if not r["numeric_refs"]]}


if __name__ == "__main__":
    main()
