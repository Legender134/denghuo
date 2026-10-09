"""Build a local Chinese reference catalog from the pinned upstream checkout."""

import json
from pathlib import Path
import re
from numeric_catalog import enrich
from build_numeric_rules import build, attach_catalog, UPSTREAM, COMMIT, VERSION, VERSION_CODE
from alchemy_catalog import attach as attach_alchemy

ROOT = Path(__file__).resolve().parents[1]
SRC = UPSTREAM / "core/src/main/java/com/shatteredpixel/shatteredpixeldungeon"


def properties(text):
    result = {}
    for line in text.splitlines():
        if not line or line.startswith(("#", "!")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.replace(r"\n", "\n").replace(r"\t", "\t")
    return result


def recipes(entries):
    """Read declarative SimpleRecipe arrays; never evaluate an arbitrary Java expression."""
    by_class={row['id'].rsplit('.',1)[-1]:row for row in entries if '$' not in row['id'] and not row['id'].endswith('.ability')}
    count=0
    pattern=r'inputs\s*=\s*new\s+Class\[\]\s*\{([^}]+)\};\s*inQuantity\s*=\s*new\s+int\[\]\s*\{([^}]+)\};\s*cost\s*=\s*(\d+)\s*;\s*output\s*=\s*(\w+)\.class\s*;\s*outQuantity\s*=\s*(\w+)\s*;'
    for path in SRC.rglob('*.java'):
        text=re.sub(r'/\*.*?\*/|//[^\n]*','',path.read_text(encoding='utf-8'),flags=re.S)
        for match in re.finditer(pattern,text,re.S):
            names=re.findall(r'(\w+)\.class',match[1]);amounts=match[2].split(',');output=by_class.get(match[4].lower())
            quantity=match[5]
            if not quantity.isdigit():
                value=re.search(r'\b'+re.escape(quantity)+r'\s*=\s*(\d+)\s*;',text)
                if not value:continue
                quantity=value[1]
            if not output or len(names)!=len(amounts) or any(not a.strip().isdigit() for a in amounts) or any(n.lower() not in by_class for n in names):continue
            output.setdefault('recipes',[]).append({'cost':int(match[3]),'quantity':int(quantity),'inputs':[{'name':by_class[n.lower()]['name'],'quantity':int(a)} for n,a in zip(names,amounts)]})
            count+=1
    return count


def main():
    messages = {}
    for group in ("items", "actors", "plants", "levels"):
        path = UPSTREAM / f"core/src/main/assets/messages/{group}/{group}_zh.properties"
        messages.update(properties(path.read_text(encoding="utf-8")))
    tiers = {}
    class_armors = []
    for folder in ("items/weapon/melee", "items/armor"):
        for path in (SRC / folder).glob("*.java"):
            text = path.read_text(encoding="utf-8")
            match = re.search(r"\btier\s*=\s*(\d+)\s*;", text)
            if not match and folder.endswith("armor"):
                match = re.search(r"super\(\s*(\d+)\s*\)", text)
            if match:
                tiers[path.stem] = int(match[1])
            if re.search(r"\bextends\s+ClassArmor\b", text):
                class_armors.append(path.stem)
    artifact_caps = {}
    for path in (SRC / "items/artifacts").glob("*.java"):
        match = re.search(r"\blevelCap\s*=\s*(\d+)\s*;", path.read_text(encoding="utf-8"))
        if match and int(match[1]) > 0:
            artifact_caps[path.stem] = int(match[1])
    terrain_text = (SRC / "levels/Terrain.java").read_text(encoding="utf-8")
    terrain = {int(number): name for name, number in re.findall(r"public static final int (\w+)\s*=\s*(\d+);", terrain_text)}
    exotic_to_regular = {}
    for relative in ("items/potions/exotic/ExoticPotion.java", "items/scrolls/exotic/ExoticScroll.java"):
        text = (SRC / relative).read_text(encoding="utf-8")
        for regular, exotic in re.findall(r"regToExo\.put\(\s*(\w+)\.class,\s*(\w+)\.class\s*\)", text):
            exotic_to_regular[exotic] = regular
    entries = []
    for key, name in messages.items():
        if not key.endswith(".name"):
            continue
        stem = key[:-5]
        desc = messages.get(stem + ".desc", "")
        modifier = any(part in stem for part in (".enchantments.", ".glyphs.", ".curses."))
        if not desc or ("%" in name and not modifier):
            continue
        if modifier:
            name = re.sub(r"%(?:\d+\$)?[\d.]*[sdf]", "", name).replace("_", "").strip().strip("之")
        category = "物品" if stem.startswith("items.") else "敌人与角色" if stem.startswith("actors.mobs.") else "状态" if stem.startswith("actors.buffs.") else "植物" if stem.startswith("plants.") else "地形与机关"
        if modifier:
            category = "附魔与刻印"
        elif stem.startswith("actors.hero."):
            category = "天赋与能力"
        elif stem.startswith("actors.blobs."):
            category = "状态"
        entries.append({"id": stem, "name": name, "description": desc,
                        "category": category, "hint": messages.get(stem + ".hint", "")})
    # Hunger names are selected dynamically in the game, rather than a .name key.
    hunger = "actors.buffs.hunger"
    if all(hunger+suffix in messages for suffix in (".hungry", ".starving", ".desc")):
        entries.append({"id":hunger, "name":messages[hunger+".hungry"]+" / "+messages[hunger+".starving"],
                        "description":"饥饿时："+messages[hunger+".desc_intro_hungry"]+"\n\n极度饥饿时："+messages[hunger+".desc_intro_starving"]+messages[hunger+".desc"],
                        "category":"状态", "hint":""})
    numeric_count = enrich(entries, SRC, messages, tiers)
    rules = build()
    attach_catalog(entries, messages, rules)
    recipe_count=recipes(entries)
    numeric_count = sum(bool(row.get("numbers")) for row in entries)
    data = {"version": VERSION, "version_code": VERSION_CODE, "numeric_count": numeric_count,
            "commit": COMMIT,
            "source": "https://github.com/00-Evan/shattered-pixel-dungeon",
            "license": "GPL-3.0-or-later", "messages": messages,
            "tiers": tiers, "terrain": terrain, "entries": entries, "exotic_to_regular": exotic_to_regular,
            "artifact_caps": artifact_caps, "class_armors": sorted(class_armors)}
    alchemy_count = attach_alchemy(data, UPSTREAM)
    # Alchemy adds canonical seed entries; attach every final entry to its source.
    attach_catalog(entries, messages, rules)
    (ROOT / "data/numeric_rules.json").write_text(json.dumps(rules, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    output = ROOT / "data/catalog.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Catalog: {len(entries)} entries, {len(messages)} messages, {len(tiers)} equipment tiers, {recipe_count} recipes, {alchemy_count} verified alchemy adapters")


if __name__ == "__main__":
    main()
