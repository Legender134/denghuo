"""Official reference search with curated aliases and explicit intent queries."""
from difflib import SequenceMatcher
import json
import unicodedata

ALIASES = {
    'items.potions.potionofhealing': ('血瓶', '治疗药水', '补血药', '回血药'),
    'items.potions.potionofstrength': ('力量药水', '力量药'),
    'items.scrolls.scrollofupgrade': ('升级卷', '强化卷'),
    'items.scrolls.scrollofremovecurse': ('祛咒卷', '解咒卷', '驱邪卷'),
    'items.scrolls.scrollofidentify': ('鉴定卷',),
    'items.potions.exotic.potionofshielding': ('护盾药水',),
    'items.waterskin': ('露珠水袋',),
}
INTENTS = {
    '加血': ('items.potions.potionofhealing', 'items.waterskin'),
    '回血': ('items.potions.potionofhealing', 'items.waterskin'),
    '解咒': ('items.scrolls.scrollofremovecurse',),
    '鉴定': ('items.scrolls.scrollofidentify',),
    '升级': ('items.scrolls.scrollofupgrade',),
    '力量不足': ('mechanics.strength','items.potions.potionofstrength','items.scrolls.scrollofupgrade','items.potions.exotic.potionofmastery'),
    '怎么逃跑': ('items.potions.potionofinvisibility','items.stones.stoneofblink','items.scrolls.scrollofteleportation','actors.buffs.roots'),
    '脱离接触': ('items.potions.potionofinvisibility','items.stones.stoneofblink','items.scrolls.scrollofteleportation'),
    '怎么回血': ('items.potions.potionofhealing','items.waterskin','actors.buffs.healing'),
    '怎么解咒': ('items.scrolls.scrollofremovecurse',),
    '怎么鉴定': ('items.scrolls.scrollofidentify',),
    '怎么升级': ('items.scrolls.scrollofupgrade',),
    '怎么吃饭': ('items.food.food','actors.buffs.hunger','items.food.pasty'),
    '饿了怎么办': ('actors.buffs.hunger','items.food.food','items.food.pasty'),
}


def normalized(value):
    return unicodedata.normalize('NFKC', value).strip().casefold()


def search(catalog, query='', category='全部', limit=80, offset=0):
    query = normalized(query[:200])
    terms = query.split()
    aliases = {identity for identity, names in ALIASES.items()
               if query and any(query == normalized(name) for name in names)}
    intents = INTENTS.get(query, ())
    entries = []
    eligible = [row for row in catalog.entries if category == '全部' or row['category'] == category]
    for row in eligible:
        content = normalized(row['name'] + ' ' + row['id'] + ' ' + row['description']
                             + ' ' + json.dumps(row.get('numbers', []), ensure_ascii=False))
        if all(term in content for term in terms) or row['id'] in aliases or row['id'] in intents:
            entries.append(row)
    if query:
        def score(row):
            name = normalized(row['name'])
            priority = (0 if name == query else 1 if row['id'] in aliases else
                        2 if name.startswith(query) else 3 if row['id'] in intents else 4)
            return priority, intents.index(row['id']) if row['id'] in intents else 0, len(name), name
        entries.sort(key=score)
    suggestions = []
    if query and not entries:
        for row in eligible:
            names = (row['name'], *ALIASES.get(row['id'], ()))
            similarity = max(SequenceMatcher(None, query, normalized(name)).ratio() for name in names)
            if similarity >= .6:
                suggestions.append((similarity, row))
        suggestions.sort(key=lambda pair: (-pair[0], len(pair[1]['name']), pair[1]['name']))
    return {'total': len(entries), 'entries': entries[offset:offset + limit],
            'version': catalog.data['version'], 'offset': offset, 'limit': limit,
            'query_interpretation': '常用别称' if aliases else '需求查询' if intents else '官方名称/内容',
            'suggestions': [row for _, row in suggestions[:5]], 'knowledge_only': True}
