"""Build normal enemy references from the pinned game's indexed original sources.

No Java is executed. Stateful/conditional combat rules require explicit reviewed
profiles; unsupported expressions fail the build instead of becoming zeroes.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from companion.rules import Formula, UnknownFormula, PREFIX, display

GAME_PATH = 'core/src/main/java/com/shatteredpixel/shatteredpixeldungeon/'
STAT_FIELDS = ('HP', 'HT', 'defenseSkill', 'EXP', 'maxLvl', 'baseSpeed', 'lootChance')


def statements(body):
    start = depth = 0
    for offset, char in enumerate(body):
        if char == '{': depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                yield body[start:offset+1], False
                start = offset+1
        elif char == ';' and depth == 0:
            yield body[start:offset], True
            start = offset+1


def build(index, catalog, upstream):
    classes = index['classes']
    expected = {row['path']: row['sha256'] for row in index['coverage']['files']}
    verified = {}

    def source(path):
        text = (upstream / path).read_text(encoding='utf-8')
        digest = hashlib.sha256(text.encode()).hexdigest()
        if digest != expected[path]:
            raise ValueError('Official source hash mismatch: '+path)
        verified[path] = digest
        return text

    def chain(key, verify=True):
        seen = set()
        while key in classes and key not in seen:
            seen.add(key)
            row = classes[key]
            if verify and row['path'] not in verified:
                source(row['path'])
            yield row
            key = row.get('base')

    def fields(key):
        result = {'false': False, 'true': True}
        for row in reversed(list(chain(key))):
            for rule in row['rules']:
                if rule['kind'] not in ('field', 'initializer'): continue
                for body, straight in statements(rule['body']):
                    for name in re.findall(r'\b(HP|HT|EXP|maxLvl|defenseSkill|baseSpeed|lootChance)\s*=(?!=)', body):
                        result.pop(name, None)
                    if not straight: continue
                    match = re.fullmatch(r'\s*(?:(?:public|protected|private|static|final|int|float|double)\s+)*(\w+)\s*=\s*((?:\w+\s*=\s*)*)(.+)\s*', body, re.S)
                    if not match: continue
                    expression = match[3].replace('Dungeon.isChallenged(Challenges.STRONGER_BOSSES)', 'false')
                    try:
                        value = Formula(result, attribute=lambda ref: {'Hero.MAX_LEVEL': 30, 'Dungeon.depth': 1, 'Dungeon.scalingDepth()': 1}[ref]).evaluate(expression)
                    except (UnknownFormula, KeyError): continue
                    for name in [match[1], *re.findall(r'(\w+)\s*=', match[2])]:
                        result[name] = value
        return result

    def method(key, name, arguments):
        for row in chain(key):
            rule = next((rule for rule in row['rules'] if rule['kind'] == 'method' and rule['name'] == name and len(rule.get('params', [])) == len(arguments)), None)
            if not rule: continue
            # Char.drRoll is only additional barkskin; normal unbuffed DR is 0.
            if row['name'] == 'Char' and name == 'drRoll': return 0
            match = re.fullmatch(r'return\s+([^;]+);', rule['body'].strip(), re.S)
            if not match: raise UnknownFormula()
            variables = {**fields(key), 'level': 1, **{param['name']: value for param, value in zip(rule['params'], arguments)}}
            def call(function, args):
                return method(row['base'] if function.startswith('super.') else key, function.removeprefix('super.'), args)
            return Formula(variables, call, attribute=lambda ref: {'Dungeon.depth': 1}[ref]).evaluate(match[1])
        raise UnknownFormula()

    bestiary_path = GAME_PATH+'journal/Bestiary.java'
    bestiary = source(bestiary_path)
    imports = {name.rsplit('.', 1)[-1]: name for name in re.findall(r'import ([\w.]+);', bestiary)}
    def resolve(raw):
        root, *nested = raw.split('.')
        return (imports[root]+''.join('$'+name for name in nested)).removeprefix(PREFIX).lower()

    groups = {}
    for match in re.finditer(r'(REGIONAL|BOSSES|UNIVERSAL|RARE|QUEST)\.addEntities\((.*?)\);', bestiary, re.S):
        groups[match[1]] = [resolve(raw) for raw in re.findall(r'([\w.]+)\.class', match[2])]
    roster = {key for group in groups.values() for key in group}
    conversions = {resolve(child): resolve(parent) for child, parent in re.findall(r'classConversions.put\(\s*([\w.]+)\.class,\s*([\w.]+)\.class\s*\)', bestiary) if resolve(parent) in roster}
    selected = roster | set(conversions)
    entries = {row['id']: row for row in catalog['entries']}
    for key in entries:
        if key.startswith('actors.mobs.') and '.npcs.' not in key and any(row['name'] == 'Mob' for row in chain(PREFIX+key, verify=False)):
            selected.add(key)
    names = {key: row['name'] for key, row in entries.items()}
    extra_entries = []
    monsters = {}
    for identity in sorted(selected):
        key = PREFIX+identity
        lineage = list(chain(key))
        if not lineage: raise ValueError('Missing indexed enemy: '+identity)
        name = identity.removeprefix('actors.mobs.')
        inherited = fields(key)
        stats = {field: inherited.get(field) for field in STAT_FIELDS}
        for field, args in [('damageRoll', []), ('attackSkill', [None]), ('drRoll', [])]:
            try: stats[field] = display(method(key, field, args))
            except (UnknownFormula, KeyError): stats[field] = None
        dynamic = None
        if name in ('mimic', 'goldenmimic', 'crystalmimic', 'ebonymimic'): dynamic = 'mimic'
        elif name in ('piranha', 'phantompiranha'): dynamic = 'piranha'
        elif name in ('statue', 'armoredstatue') or identity == 'levels.traps.guardiantrap$guardian': dynamic = 'statue'
        elif name in ('wraith', 'tormentedspirit') or identity == 'items.quest.corpsedust$dustwraith': dynamic = 'wraith'
        elif name == 'bee': dynamic = 'bee'
        elif identity == 'levels.rooms.special.sentryroom$sentry': dynamic = 'sentry'
        if dynamic:
            for field in ('HP', 'HT', 'defenseSkill', 'damageRoll', 'attackSkill', 'drRoll'):
                stats.pop(field, None)
        if name == 'goo': stats.update(damageRoll='1–8', attackSkill='10')
        if name == 'tengu': stats['attackSkill'] = '10（相邻）／20（远距）'
        if name in ('brute', 'armoredbrute'): stats['damageRoll'] = '5–25'
        if name == 'gnollguard': stats['damageRoll'] = '6–12（相邻）／16–22（远距）'
        if name.startswith('elemental$') or name.startswith('quest.vault.vaultelemental$'):
            newborn = name == 'elemental$newbornfireelemental'
            stats.update(damageRoll='10–12' if newborn else '20–25', attackSkill='15' if newborn else '25')
        if name == 'quest.vault.vaultbosselemental': stats['damageRoll'] = '15–20（冰霜形态）／20–25（其他形态）'
        if name.startswith('npcs.vault'):
            stats.update(HP='不可破坏', HT='不可破坏', defenseSkill='无敌', damageRoll='不使用普通攻击', attackSkill='不使用普通攻击', drRoll='免疫伤害')
        if name.startswith('dwarfking$dk'):
            # Summoning.act sets maxLvl after construction, before GameScene.add.
            stats['maxLvl'] = -2
        if name in ('pylon', 'crystalspire', 'fungalcore', 'demonspawner', 'necromancer', 'spectralnecromancer', 'yogdzewa'):
            stats['damageRoll'] = '不使用普通攻击'
        if any(value is None for value in stats.values()):
            raise ValueError('Unreviewed enemy values: '+identity+' '+str(stats))
        loot = None
        for member in reversed(lineage):
            for rule in member['rules']:
                if rule['kind'] in ('initializer', 'field'):
                    match = re.search(r'\bloot\s*=\s*([^;]+);', rule['body'])
                    if match: loot = match[1].strip()
        localized = names.get(identity) or catalog['messages'].get(identity+'.name')
        if not localized:
            parent = conversions.get(identity) or lineage[1]['id'].removeprefix(PREFIX)
            localized = names.get(parent) or catalog['messages'].get(parent+'.name')
            if not localized: raise ValueError('Missing enemy localization: '+identity)
            suffix = ('红色' if name.endswith('$redshaman') else '蓝色' if name.endswith('$blueshaman') else '紫色' if name.endswith('$purpleshaman') else '尸尘召唤' if identity.startswith('items.quest.') else '矮人国王召唤' if name.startswith('dwarfking$') else '古神召唤' if name.startswith('yogdzewa$') else '矮人宝库' if name.startswith('quest.vault.') else '变体')
            localized += ' · '+suffix
        if identity not in entries or entries[identity].get('monster_reference'):
            description = catalog['messages'].get(identity+'.desc', '')
            for ancestor in lineage:
                stem = ancestor['id'].removeprefix(PREFIX)
                if not description: description = catalog['messages'].get(stem+'.desc', '')
            if name == 'pylon':
                description = '\n\n'.join(catalog['messages'][identity+suffix] for suffix in ('.desc_inactive', '.desc_active'))
            extra_entries.append({'id': identity, 'name': localized, 'description': description, 'category': '敌人与角色', 'hint': '', 'monster_reference': True})
        chance = stats.pop('lootChance')
        monsters[identity] = {'name': localized, 'stats': stats, 'dynamic': dynamic, 'loot_expression': loot, 'base_loot_chance': chance,
                             'bestiary_alias': conversions.get(identity), 'sources': [{'path': row['path'], 'line': row['line'], 'sha256': verified[row['path']]} for row in lineage]}

    generator_path = GAME_PATH+'items/Generator.java'
    text = source(generator_path)
    generator = classes[PREFIX+'items.generator']
    categories = {}
    category_weights = {name: float(first)+float(second) for name, first, second in re.findall(r'\b([A-Z][A-Z_0-9]+)\s*\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*[\w.]+\.class\s*\)', text)}
    for match in re.finditer(r'\b(\w+)\.classes\s*=\s*new\s+Class<\?>\[\]\s*\{([^}]+)\}', text):
        category, raw_classes = match.groups()
        class_names = re.findall(r'([\w.]+)\.class', raw_classes)
        weights = []
        for suffix in ('defaultProbs', 'defaultProbs2'):
            found = re.search(r'\b'+category+r'\.'+suffix+r'\s*=\s*new\s+float\[\]\s*\{([^}]+)\}', text)
            if found:
                values = [float(value.strip().removesuffix('f')) for value in found[1].split(',')]
                if len(values) != len(class_names): raise ValueError('Generator weight count: '+category)
                weights = [a+b for a, b in zip(weights, values)] if weights else values
        if not weights:
            found = re.search(r'\b'+category+r'\.probs\s*=\s*new\s+float\[\]\s*\{([^}]+)\}', text)
            if found: weights = [float(value.strip().removesuffix('f')) for value in found[1].split(',')]
        if not weights: continue
        if len(weights) != len(class_names): raise ValueError('Generator weight count: '+category)
        items = []
        for classname, weight in zip(class_names, weights):
            root, *nested = classname.split('.')
            identity = (generator['imports'].get(root, generator['package']+'.'+root)+''.join('$'+name for name in nested)).removeprefix(PREFIX).lower()
            localized = names.get(identity) or catalog['messages'].get(identity+'.name')
            if not localized or '%' in localized: raise ValueError('Missing item localization: '+identity)
            items.append({'id': identity, 'name': localized, 'weight': weight, 'quantity': 2 if identity.endswith('.darts.dart') else 3 if identity.startswith('items.weapon.missiles.') else 1})
        categories[category] = items
    return {'format': 1, 'version': catalog['version'], 'commit': catalog['commit'], 'license': 'GPL-3.0-or-later',
            'scope': 'normal enemy reference without challenges, ascension, champions, equipment or status modifiers',
            'bestiary_groups': groups, 'bestiary_conversions': conversions, 'extra_catalog_entries': extra_entries,
            'monsters': monsters, 'categories': categories, 'category_weights': category_weights,
            'tier_weights': [[0,75,20,4,1], [0,25,50,20,5], [0,0,40,50,10], [0,0,20,40,40], [0,0,0,20,80]],
            'verified_source_files': dict(sorted(verified.items()))}


def main():
    from build_numeric_rules import UPSTREAM
    index = json.loads((ROOT/'data/numeric_rules.json').read_text(encoding='utf-8'))
    catalog = json.loads((ROOT/'data/catalog.json').read_text(encoding='utf-8'))
    data = build(index, catalog, UPSTREAM)
    (ROOT/'data/monster_reference.json').write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'))+'\n', encoding='utf-8', newline='\n')
    print('Monster reference:', len(data['monsters']), 'including all', sum(map(len, data['bestiary_groups'].values())), 'official enemy entries')


if __name__ == '__main__':
    main()
