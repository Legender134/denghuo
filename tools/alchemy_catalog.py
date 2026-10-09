"""Verify only explicitly supported recipe adapters against the pinned Java files."""
import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from companion.alchemy import COMMIT, VERSION, SOURCE, JAVA_ROOT, POTIONS, SCROLLS, definitions, item_id
from companion.alchemy_flow import BOMBS, DEFAULT_POTION_WEIGHTS, DYNAMIC, SEED_POTIONS, TRINKETS, WAND_TYPES, DART_TYPES
from build_numeric_rules import mask_java


def class_body(text, name):
    match = re.search(r'\bclass\s+' + re.escape(name) + r'\b[^\{]*\{', text)
    if not match:
        raise ValueError('Missing explicit recipe class: ' + name)
    start, depth = match.end(), 1
    for index in range(start, len(text)):
        depth += (text[index] == '{') - (text[index] == '}')
        if not depth:
            return text[start:index], text[:match.start()].count('\n') + 1
    raise ValueError('Unclosed recipe class')


def resolve_class(token, text, owner):
    """Resolve imported/package roots while retaining the Java nested identity."""
    parts = token.split('.')
    package = re.search(r'\bpackage\s+([\w.]+)\s*;', text)[1]
    imports = {full.rsplit('.', 1)[-1]: full for full in re.findall(r'\bimport\s+([\w.]+)\s*;', text)}
    root = owner if parts[0] == owner.rsplit('.', 1)[-1] else imports.get(parts[0], package + '.' + parts[0])
    return root + (('$' + '$'.join(parts[1:])) if len(parts) > 1 else '')


def verify(row, text):
    body, line = class_body(mask_java(text), row.get('recipe_class', 'Recipe') if row['adapter'] == 'SimpleRecipe' else row['adapter'])
    if row['adapter'] == 'SimpleRecipe':
        names = re.search(r'inputs\s*=\s*new\s+Class\[\]\s*\{([^}]+)\}', body)
        amounts = re.search(r'inQuantity\s*=\s*new\s+int\[\]\s*\{([^}]+)\}', body)
        cost = re.search(r'\bcost\s*=\s*(\d+)\s*;', body)
        output = re.search(r'\boutput\s*=\s*(\w+)\.class\s*;', body)
        quantity = re.search(r'\boutQuantity\s*=\s*(\w+)\s*;', body)
        if not all((names, amounts, cost, output, quantity)):
            raise ValueError('Explicit SimpleRecipe declaration changed: ' + row['id'])
        q = quantity[1]
        if not q.isdigit():
            constant = re.search(r'\b' + re.escape(q) + r'\s*=\s*(\d+)\s*;', body)
            if not constant:
                raise ValueError('Recipe output constant changed')
            q = constant[1]
        owner = 'com.shatteredpixel.shatteredpixeldungeon.' + row['path'].removeprefix(JAVA_ROOT).removesuffix('.java').replace('/', '.')
        actual = (re.findall(r'([\w.]+)\.class', names[1]), [int(n.strip()) for n in amounts[1].split(',')], int(cost[1]), output[1], int(q))
        expected = ([i['id'] for i in row['inputs']], [i['quantity'] for i in row['inputs']], row['cost'], row['output'], row['quantity'])
        prefix = 'com.shatteredpixel.shatteredpixeldungeon.'
        normalized = ([resolve_class(n, text, owner).removeprefix(prefix).lower() for n in actual[0]],
                      actual[1], actual[2], resolve_class(actual[3], text, owner).removeprefix(prefix).lower(), actual[4])
        if normalized != expected:
            raise ValueError(f'Explicit recipe differs from pinned source: {row["id"]}: {actual}')
    else:
        family = row['adapter']
        if not re.search(r'\bcost\([^)]*\)\s*\{\s*return\s+' + str(row['cost']) + r'\s*;', body):
            raise ValueError('Conversion cost changed')
        if family == 'PotionToExotic':
            pairs = re.findall(r'regToExo\.put\(\s*PotionOf(\w+)\.class,\s*PotionOf(\w+)\.class\s*\)', text)
            if pairs != list(POTIONS):
                raise ValueError('Potion conversion mapping changed')
        elif family == 'ScrollToExotic':
            pairs = re.findall(r'regToExo\.put\(\s*ScrollOf(\w+)\.class,\s*ScrollOf(\w+)\.class\s*\)', text)
            if pairs != [(a, b) for a, b, _ in SCROLLS]:
                raise ValueError('Scroll conversion mapping changed')
        else:
            actual = dict(re.findall(r'stones\.put\(\s*ScrollOf(\w+)\.class,\s*StoneOf(\w+)\.class\s*\)', body))
            if actual != {a: c for a, _, c in SCROLLS} or '.quantity(2)' not in body:
                raise ValueError('Runestone conversion mapping or output changed')
        compact = re.sub(r'\s+', '', body)
        if '.quantity()-1)' not in compact:
            raise ValueError('Conversion consumption changed')
        if family != 'ScrollToStone' and ('Reflection.newInstance(regToExo.get(' not in body or 'quantity(' in body.split('sampleOutput')[-1]):
            raise ValueError('Conversion output changed')
    return line


def verify_dynamic(files):
    """Check finite variant tables independently from the Python adapter constants."""
    seed_text = files[JAVA_ROOT + 'items/potions/Potion.java'][0]
    seed_body, _ = class_body(mask_java(seed_text), 'SeedToPotion')
    actual_seeds = {'plants.' + plant.lower() + '$seed': item_id('potions/PotionOf' + potion)
                    for plant, potion in re.findall(r'types\.put\(\s*(\w+)\.Seed\.class,\s*PotionOf(\w+)\.class\s*\)', seed_body)}
    if actual_seeds != SEED_POTIONS:
        raise ValueError('Canonical seed to potion table differs from pinned source')
    bomb_text = files[JAVA_ROOT + 'items/bombs/Bomb.java'][0]
    bomb_body, _ = class_body(mask_java(bomb_text), 'EnhanceBomb')
    owner = 'com.shatteredpixel.shatteredpixeldungeon.items.bombs.Bomb'
    prefix = 'com.shatteredpixel.shatteredpixeldungeon.'
    costs = {name: int(cost) for name, cost in re.findall(r'bombCosts\.put\(\s*(\w+)\.class,\s*(\d+)\s*\)', bomb_body)}
    actual_bombs = [(resolve_class(ingredient, bomb_text, owner).removeprefix(prefix).lower(), output, costs[output])
                    for ingredient, output in re.findall(r'validIngredients\.put\(\s*(\w+)\.class,\s*(\w+)\.class\s*\)', bomb_body)]
    if actual_bombs != [(item_id(ingredient), output, cost) for ingredient, output, cost in BOMBS]:
        raise ValueError('Bomb material/output/cost variants differ from pinned source')
    generator = mask_java(files[JAVA_ROOT + 'items/Generator.java'][0])
    wand_classes = re.search(r'WAND\.classes\s*=\s*new\s+Class<\?>\[\]\s*\{([^}]+)\}', generator)
    if not wand_classes or tuple(re.findall(r'(\w+)\.class', wand_classes[1])) != WAND_TYPES:
        raise ValueError('Concrete inventory wand classes differ from pinned source')
    dart_text = mask_java(files[JAVA_ROOT + 'items/weapon/missiles/darts/Dart.java'][0])
    tipped_text = mask_java(files[JAVA_ROOT + 'items/weapon/missiles/darts/TippedDart.java'][0])
    if not re.search(r'public\s+class\s+Dart\s+extends\s+MissileWeapon', dart_text):
        raise ValueError('Concrete Dart inventory type differs from pinned source')
    if ('Dart', *re.findall(r'types\.put\(\s*\w+\.Seed\.class,\s*(\w+)\.class\s*\)', tipped_text)) != DART_TYPES:
        raise ValueError('Concrete tipped dart inventory types differ from pinned source')
    potion_decks = [re.search(r'POTION\.defaultProbs' + suffix + r'\s*=\s*new\s+float\[\]\s*\{([^}]+)\}', generator)
                    for suffix in ('', '2')]
    if not all(potion_decks) or tuple(sum(pair) for pair in zip(*[
            [int(value.strip()) for value in deck[1].split(',')] for deck in potion_decks])) != DEFAULT_POTION_WEIGHTS:
        raise ValueError('Default potion pool weights differ from pinned source')
    actual_trinkets = re.search(r'TRINKET\.classes\s*=\s*new\s+Class<\?>\[\]\s*\{([^}]+)\}', generator)
    if not actual_trinkets or tuple(re.findall(r'(\w+)\.class', actual_trinkets[1])) != TRINKETS:
        raise ValueError('The seventeen concrete trinket identities differ from pinned source')
    for recipe, _, family, path, _ in DYNAMIC:
        if recipe in ('enhance-bomb', 'trinket-upgrade', 'cook-meat'): continue
        body, _ = class_body(mask_java(files[JAVA_ROOT + 'items/' + path + '.java'][0]), family.split('.')[-1])
        expected_cost = {'resin': 5, 'liquid-metal': 3, 'trinket-catalyst': 6, 'cook-fruit': 2,
                         'unstable-brew': 1, 'unstable-spell': 1, 'alchemize': 2, 'seed-potion': 0, 'meat-pie': 6}[recipe]
        if not re.search(r'\bcost\([^)]*\)\s*\{\s*return\s+' + str(expected_cost) + r'\s*;', body):
            raise ValueError('Dynamic energy cost differs from pinned source: ' + recipe)
        if recipe == 'alchemize' and not re.search(r'OUT_QUANTITY\s*=\s*8\s*;', body):
            raise ValueError('Alchemize yield differs from pinned source')


def attach(data, upstream):
    upstream = Path(upstream)
    head = subprocess.check_output(['git', '-C', str(upstream), 'rev-parse', 'HEAD'], text=True).strip()
    if head != COMMIT or data.get('commit') != COMMIT or data.get('version') != VERSION:
        raise ValueError('Alchemy generation requires the exact verified official 4.0.2 commit')
    entries = {row['id']: row for row in data['entries']}
    recipe_rows, files = [], {}
    # Verify registration and underlying game integer fields, not just recipe arrays.
    for path in (JAVA_ROOT + 'items/Recipe.java', JAVA_ROOT + 'items/Item.java', JAVA_ROOT + 'Dungeon.java', 'LICENSE.txt'):
        raw = (upstream / path).read_bytes()
        if raw != subprocess.check_output(['git', '-C', str(upstream), 'show', COMMIT + ':' + path]):
            raise ValueError('Alchemy base source differs from fixed Git bytes: ' + path)
        files[path] = (raw.decode('utf-8'), hashlib.sha256(raw).hexdigest())
    if not re.search(r'\bint\s+quantity\s*=\s*1\s*;', files[JAVA_ROOT + 'items/Item.java'][0]) or not re.search(r'\bint\s+energy\s*;', files[JAVA_ROOT + 'Dungeon.java'][0]):
        raise ValueError('Game alchemy integer fields changed')
    for definition in definitions():
        path = definition['path']
        if path not in files:
            raw = (upstream / path).read_bytes()
            fixed = subprocess.check_output(['git', '-C', str(upstream), 'show', COMMIT + ':' + path])
            if raw != fixed:
                raise ValueError('Alchemy source differs from fixed Git bytes: ' + path)
            files[path] = (raw.decode('utf-8'), hashlib.sha256(raw).hexdigest())
        text, digest = files[path]
        owner = {'PotionToExotic': 'ExoticPotion.PotionToExotic', 'ScrollToExotic': 'ExoticScroll.ScrollToExotic',
                 'ScrollToStone': 'Scroll.ScrollToStone'}.get(definition['adapter'], path.rsplit('/', 1)[-1].removesuffix('.java') + '.' + definition.get('recipe_class', 'Recipe'))
        if not re.search(r'\bnew\s+' + re.escape(owner) + r'\s*\(', files[JAVA_ROOT + 'items/Recipe.java'][0]):
            raise ValueError('Explicit recipe is not registered in the official recipe table: ' + owner)
        line = verify(definition, text)
        row = dict(definition)
        row['name'] = entries[row['output']]['name']
        row['inputs'] = [{**i, 'name': entries[i['id']]['name']} for i in row['inputs']]
        row['source'] = {'version': VERSION, 'commit': COMMIT, 'license': 'GPL-3.0-or-later',
                         'path': path, 'line': line, 'sha256': digest,
                         'url': SOURCE + '/blob/' + COMMIT + '/' + path + '#L' + str(line)}
        row['family'] = owner
        recipe_rows.append(row)
    family_sources = {row['family']: row['source'] for row in recipe_rows}
    registry = mask_java(files[JAVA_ROOT + 'items/Recipe.java'][0])
    section = registry[registry.index('private static Recipe[] variableRecipes'):registry.index('public static ArrayList<Recipe> findRecipes')]
    registered = re.findall(r'\bnew\s+(\w+)\.(\w+)\s*\(', section)
    registered = {owner + '.' + inner for owner, inner in registered}
    if len(registered) != 39:
        raise ValueError('The fixed official registry must contain exactly 39 recipe families')
    for identity, name, family, relative, mode in DYNAMIC:
        if identity == 'cook-meat':
            continue  # This convenience adapter combines three registered fixed classes.
        path = JAVA_ROOT + 'items/' + relative + '.java'
        raw = (upstream / path).read_bytes()
        if raw != subprocess.check_output(['git', '-C', str(upstream), 'show', COMMIT + ':' + path]):
            raise ValueError('Dynamic source differs from pinned Git bytes: ' + path)
        text, digest = raw.decode('utf-8'), hashlib.sha256(raw).hexdigest()
        files[path] = (text, digest)
        _, line = class_body(mask_java(text), family.split('.')[-1])
        family_sources[family] = {'version': VERSION, 'commit': COMMIT, 'license': 'GPL-3.0-or-later',
                                 'path': path, 'line': line, 'sha256': digest,
                                 'url': SOURCE + '/blob/' + COMMIT + '/' + path + '#L' + str(line)}
    if set(family_sources) != registered:
        raise ValueError('Every registered family must have exactly one verified adapter')
    dependencies = [JAVA_ROOT + 'items/Generator.java', JAVA_ROOT + 'items/wands/Wand.java',
                    JAVA_ROOT + 'items/weapon/missiles/MissileWeapon.java', JAVA_ROOT + 'scenes/AlchemyScene.java',
                    JAVA_ROOT + 'items/weapon/missiles/darts/Dart.java', JAVA_ROOT + 'items/weapon/missiles/darts/TippedDart.java']
    dependencies += [JAVA_ROOT + 'items/trinkets/' + name + '.java' for name in TRINKETS]
    for path in dependencies:
        raw = (upstream / path).read_bytes()
        if raw != subprocess.check_output(['git', '-C', str(upstream), 'show', COMMIT + ':' + path]):
            raise ValueError('Dynamic dependency differs from pinned Git bytes: ' + path)
        files[path] = (raw.decode('utf-8'), hashlib.sha256(raw).hexdigest())
    verify_dynamic(files)
    for identity in SEED_POTIONS:
        if identity not in entries:
            plant = identity.split('$')[0]
            name = data['messages'].get(identity + '.name')
            if not name:
                raise ValueError('Canonical seed Chinese name is missing: ' + identity)
            entry = {'id': identity, 'name': name, 'description': data['messages'].get(identity + '.desc', data['messages'].get(plant + '.desc', '')),
                     'category': '植物', 'hint': ''}
            data['entries'].append(entry)
            entries[identity] = entry
    data['alchemy_families'] = [{'family': family, 'source': family_sources[family],
                                'mode': 'fixed' if family in {r['family'] for r in recipe_rows} else 'dynamic'}
                               for family in sorted(registered)]
    for entry in data['entries']:
        relevant = [row for row in recipe_rows if row['output'] == entry['id'] or any(i['id'] == entry['id'] for i in row['inputs'])]
        if relevant:
            entry['alchemy_recipe_ids'] = [row['id'] for row in relevant]
        outputs = [row for row in recipe_rows if row['output'] == entry['id']]
        if outputs:
            entry['recipes'] = [{'id': row['id'], 'cost': row['cost'], 'quantity': row['quantity'], 'inputs': row['inputs'], 'source': row['source']} for row in outputs]
    data['alchemy_recipes'] = recipe_rows
    data['alchemy_source_files'] = [{'path': path, 'sha256': digest, 'version': VERSION, 'commit': COMMIT}
                                    for path, (_, digest) in files.items()]
    return len(recipe_rows)
