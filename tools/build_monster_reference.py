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


def comma_terms(text):
    """Split the pinned enum's constructor arguments, retaining nested calls."""
    start = depth = 0
    for offset, char in enumerate(text):
        if char == '(': depth += 1
        elif char == ')': depth -= 1
        elif char == ',' and depth == 0:
            yield text[start:offset].strip()
            start = offset+1
    if depth != 0: raise ValueError('Unbalanced defense declaration')
    yield text[start:].strip()


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
            if row['name'] == 'Mob' and name == 'attackDelay': return 1
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

    def effect_id(raw, member):
        root, *nested = raw.split('.')
        if root in member['imports']:
            fullname = member['imports'][root]
        else:
            current = member
            while current:
                fullname = current['fullname']+'$'+root
                if fullname.lower() in classes: break
                current = classes.get(current.get('parent'))
            else:
                fullname = member['package']+'.'+root
        key = (fullname+''.join('$'+name for name in nested)).lower()
        if key not in classes: raise ValueError('Unresolved defense effect: '+raw)
        return key.removeprefix(PREFIX)

    property_owner = classes[PREFIX+'actors.char$property']
    source(property_owner['path'])
    declaration = next(rule['body'] for rule in property_owner['rules'] if rule['kind']=='field' and rule['body'].startswith('BOSS ('))
    property_effects = {}
    for term in comma_terms(declaration.rstrip(';')):
        match = re.fullmatch(r'(\w+)\s*(?:\((.*)\))?', term, re.S)
        if not match: raise ValueError('Unreviewed character property: '+term)
        effects = {'resistances':set(), 'immunities':set()}
        if match[2] is not None:
            args = list(comma_terms(match[2]))
            if len(args) != 2: raise ValueError('Unreviewed property effects: '+term)
            for kind, arg in zip(effects, args):
                group = re.fullmatch(r'new\s+HashSet<Class>\(\s*(?:Arrays\.asList\((.*?)\))?\s*\)',arg,re.S)
                if not group: raise ValueError('Unreviewed property set: '+arg)
                for raw in re.findall(r'([\w.]+)\.class',group[1] or ''):
                    effects[kind].add(effect_id(raw,property_owner))
        property_effects[match[1]] = effects
    if len(property_effects) != 14: raise ValueError('Character property roster changed')

    def defenses(key):
        properties = set()
        effects = {'resistances':set(), 'immunities':set()}
        extra_sources = []
        for member in reversed(list(chain(key))):
            for rule in member['rules']:
                if rule['kind'] not in ('initializer','field') and rule['name'] != member['name']: continue
                for body, straight in statements(rule['body']):
                    additions = re.findall(r'\b(properties|resistances|immunities)\.add\(\s*([\w.$]+)\s*\)',body)
                    if not additions: continue
                    if not straight:
                        # Piranha copies this exact environmental set, except electricity/freezing.
                        if member['name'] != 'Piranha' or re.sub(r'\s+','',body) != 'for(Classc:newBlobImmunity().immunities()){if(c!=Electricity.class&&c!=Freezing.class){immunities.add(c);}}':
                            raise ValueError('Unreviewed conditional defense: '+key+' '+body)
                        blob = classes[PREFIX+'actors.buffs.blobimmunity']
                        source(blob['path'])
                        extra_sources.append({'path':blob['path'],'line':blob['line'],'sha256':verified[blob['path']]})
                        for part in blob['rules']:
                            if part['kind'] == 'initializer':
                                for raw in re.findall(r'\bimmunities\.add\(\s*([\w.]+)\.class\s*\)',part['body']):
                                    if raw not in ('Electricity','Freezing'):
                                        effects['immunities'].add(effect_id(raw,blob))
                        continue
                    for kind, raw in additions:
                        if kind == 'properties':
                            name = raw.rsplit('.',1)[-1]
                            if name not in property_effects: raise ValueError('Unknown defense property: '+raw)
                            properties.add(name)
                        elif raw.endswith('.class'):
                            effects[kind].add(effect_id(raw.removesuffix('.class'),member))
                        else: raise ValueError('Unreviewed defense effect: '+raw)
        for prop in properties:
            for kind in effects: effects[kind].update(property_effects[prop][kind])
        return {'properties':sorted(properties), **{kind:sorted(ids) for kind,ids in effects.items()},'sources':extra_sources}

    extra_entries = []
    monsters = {}
    for identity in sorted(selected):
        key = PREFIX+identity
        lineage = list(chain(key))
        if not lineage: raise ValueError('Missing indexed enemy: '+identity)
        name = identity.removeprefix('actors.mobs.')
        inherited = fields(key)
        stats = {field: inherited.get(field) for field in STAT_FIELDS}
        for field, args in [('damageRoll', []), ('attackSkill', [None]), ('drRoll', []), ('attackDelay', [])]:
            try: stats[field] = display(method(key, field, args))
            except (UnknownFormula, KeyError): stats[field] = None
        dynamic = None
        if name in ('mimic', 'goldenmimic', 'crystalmimic', 'ebonymimic'): dynamic = 'mimic'
        elif name in ('piranha', 'phantompiranha'): dynamic = 'piranha'
        elif name in ('statue', 'armoredstatue') or identity == 'levels.traps.guardiantrap$guardian': dynamic = 'statue'
        elif name in ('wraith', 'tormentedspirit') or identity == 'items.quest.corpsedust$dustwraith': dynamic = 'wraith'
        elif name == 'bee': dynamic = 'bee'
        elif identity == 'levels.rooms.special.sentryroom$sentry': dynamic = 'sentry'
        if dynamic=='statue': stats['attackDelay']='所持武器的攻击耗时倍率'
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
        if name in ('pylon', 'crystalspire', 'fungalcore', 'demonspawner', 'necromancer', 'spectralnecromancer', 'yogdzewa', 'rotheart'):
            stats['damageRoll'] = '不使用普通攻击'
        if stats.get('damageRoll')=='不使用普通攻击' or dynamic=='sentry':
            stats['attackDelay']='不使用普通攻击'
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
                             'defenses': defenses(key),
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
    # Rotation slots are not independent spawn probabilities. Preserve the
    # original ordered slots, optional additions and conditional replacements.
    spawner = classes[PREFIX+'actors.mobs.mobspawner']
    source(spawner['path'])
    def spawner_method(name):
        return next(r['body'] for r in spawner['rules'] if r['kind']=='method' and r['name']==name)
    def mob_id(name):
        identity = 'actors.mobs.'+name.replace('.', '$').lower()
        if identity not in monsters: raise ValueError('Unknown rotation enemy: '+name)
        return identity
    rotations = {}
    for match in re.finditer(r'((?:(?:case\s+\d+|default)\s*:\s*)+)return new ArrayList<>\(Arrays.asList\((.*?)\)\);', spawner_method('standardMobRotation'), re.S):
        slots = [part.strip() for part in match[2].split(',')]
        if any(not re.fullmatch(r'\w+\.(?:class|random\(\))', part) for part in slots):
            raise ValueError('Unreviewed rotation expression')
        for depth in re.findall(r'case\s+(\d+)', match[1]):
            rotations[depth] = [part.removesuffix('.class') if part.endswith('.class') else part for part in slots]
    if set(rotations) != {str(n) for n in range(1,27)}: raise ValueError('Incomplete official rotations')
    rare = {depth: {'class':mob_id(name), 'chance':float(chance)} for depth,chance,name in re.findall(
        r'case\s+(\d+):\s*if \(Random.Float\(\) < ([\d.]+)f\) rotation.add\((\w+)\.class\);', spawner_method('addRareMobs'))}
    if len(rare)!=4: raise ValueError('Unreviewed rare additions')
    spawner_text = source(spawner['path'])
    alternative_pairs = re.findall(r'RARE_ALTS.put\((\w+)\.class,\s*([\w.]+)\.class\)',spawner_text)
    if ('Elemental','Elemental.ChaosElemental') not in alternative_pairs: raise ValueError('Unreviewed elemental alias')
    alternatives = {mob_id(a):mob_id(b) for a,b in alternative_pairs if a!='Elemental'}
    if len(alternatives)!=10 or '1 / 50f * RatSkull.exoticChanceMultiplier()' not in spawner_method('swapMobAlts'):
        raise ValueError('Unreviewed alternative chance')
    selectors = {}
    for owner, choices in (('Shaman',('RedShaman','BlueShaman','PurpleShaman')),
                           ('Elemental',('FireElemental','FrostElemental','ShockElemental'))):
        cls = classes[PREFIX+'actors.mobs.'+owner.lower()];source(cls['path'])
        body = next(r['body'] for r in cls['rules'] if r['kind']=='method' and r['name']=='random')
        if not re.search(r'roll < 0\.4f', body) or not re.search(r'roll < 0\.8f', body):
            raise ValueError('Unreviewed selector weights')
        if any('return '+name+'.class;' not in body for name in choices): raise ValueError('Unreviewed selector members')
        selectors[owner+'.random()'] = [{'id':mob_id(owner+'.'+name),'chance':chance} for name,chance in zip(choices,(.4,.4,.2))]
        if owner=='Elemental':
            if '1/50f * RatSkull.exoticChanceMultiplier()' not in body: raise ValueError('Unreviewed elemental alternative')
            selectors[owner+'.random()'].append({'id':mob_id('Elemental.ChaosElemental'),'alternative':True,'chance':.02})
    rotations = {depth:[slot if slot in selectors else mob_id(slot) for slot in slots] for depth,slots in rotations.items()}
    source(GAME_PATH+'Dungeon.java')
    source(GAME_PATH+'levels/MiningLevel.java')
    source(GAME_PATH+'levels/VaultLevel.java')
    # Floor condition profiles in companion.floor_guide also depend on these
    # version-bound room, quest and container rules, outside MobSpawner.
    condition_sources = [GAME_PATH+tail for tail in (
        'actors/mobs/npcs/Ghost.java','actors/mobs/npcs/Wandmaker.java','actors/mobs/npcs/Blacksmith.java',
        'actors/mobs/DwarfKing.java','actors/mobs/YogDzewa.java','actors/mobs/DemonSpawner.java',
        'actors/mobs/Piranha.java','actors/mobs/Statue.java','actors/mobs/Wraith.java',
        'levels/RegularLevel.java','levels/SewerLevel.java','levels/HallsLevel.java',
        'levels/rooms/special/PoolRoom.java','levels/rooms/special/StatueRoom.java','levels/rooms/special/SentryRoom.java','levels/rooms/special/CrystalVaultRoom.java',
        'levels/rooms/secret/SecretRoom.java','levels/rooms/secret/SecretHoneypotRoom.java',
        'levels/rooms/quest/MassGraveRoom.java','levels/rooms/quest/RotGardenRoom.java','levels/rooms/quest/RitualSiteRoom.java',
        'levels/rooms/quest/MineLargeRoom.java','levels/rooms/quest/MineGiantRoom.java',
        'items/Heap.java','items/quest/CorpseDust.java','items/quest/CeremonialCandle.java')]
    for path in condition_sources: source(path)
    # Player-facing special mechanisms and the ordinary loot modifier use
    # these state rules in addition to each enemy's own class hierarchy.
    for tail in ('actors/buffs/Bleeding.java','actors/buffs/Ooze.java','actors/buffs/Charm.java',
                 'actors/buffs/Barrier.java','actors/buffs/ShieldBuff.java','actors/buffs/Cripple.java',
                 'actors/buffs/Burning.java','actors/buffs/AscensionChallenge.java',
                 'actors/blobs/StenchGas.java','actors/blobs/ToxicGas.java',
                 'items/rings/Ring.java','items/rings/RingOfWealth.java'):
        source(GAME_PATH+tail)
    return {'format': 1, 'version': catalog['version'], 'commit': catalog['commit'], 'license': 'GPL-3.0-or-later',
            'scope': 'normal enemy reference without challenges, ascension, champions, equipment or status modifiers',
            'bestiary_groups': groups, 'bestiary_conversions': conversions, 'extra_catalog_entries': extra_entries,
            'monsters': monsters, 'categories': categories, 'category_weights': category_weights,
            'property_defenses':{prop:{kind:sorted(ids) for kind,ids in groups.items()} for prop,groups in property_effects.items()},
            'encounters':{'rotations':rotations,'rare_additions':rare,'alternatives':alternatives,'selectors':selectors,'condition_sources':condition_sources},
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
