"""Only player-observable state needed by the pinned game's alchemy workflows.

Derived from SPD 4.0.2 commit 57a4e06a4caf162446d1c28caa7983f0493fecf0,
GPL-3.0-or-later. Exact missile durability is deliberately never projected.
"""
from .public_source_data import MISSILE_PUBLIC_TYPES
from .public_talents import talent_points

PREFIX = 'com.shatteredpixel.shatteredpixeldungeon.'
FRUIT_NAMES = dict(zip(
    ('healing', 'strength', 'paralyticgas', 'invisibility', 'liquidflame', 'frost',
     'mindvision', 'toxicgas', 'levitation', 'purity', 'experience', 'haste'),
    ('sunfruit', 'rotfruit', 'earthfruit', 'blindfruit', 'firefruit', 'icefruit',
     'fadefruit', 'sorrowfruit', 'stormfruit', 'dreamfruit', 'starfruit', 'swiftfruit')))


def identity(item):
    value = item.get('__className') if isinstance(item, dict) else None
    return value[len(PREFIX):].lower() if isinstance(value, str) and value.startswith(PREFIX) else None


def bounded_integer(value, lower=0, upper=2147483647):
    return value if type(value) is int and lower <= value <= upper else None


def project_item_state(item, game, public):
    key = public['key']
    if not public['known']:
        return {}
    if key == 'items.food.blandfruit':
        potion = item.get('potionattrib')
        if potion is None:
            return {'cooked': 'raw', 'potion_id': None}
        potion_id = identity(potion)
        if potion_id in {'items.potions.potionof' + name for name in FRUIT_NAMES}:
            return {'cooked': 'cooked', 'potion_id': potion_id}
        return {'cooked': 'unknown', 'potion_id': None}
    if key.startswith('items.wands.'):
        resin = bounded_integer(item.get('resin_bonus', 0))
        grade = public['level']
        base = grade - resin if (type(grade) is int and resin is not None and public['cursed'] is False) else None
        hero = game.get('hero') if isinstance(game.get('hero'), dict) else {}
        cls = hero.get('class')
        return {'public_level': grade, 'base_level': base, 'resin_bonus': resin,
                'hero_class': cls if cls in ('WARRIOR', 'MAGE', 'ROGUE', 'HUNTRESS', 'DUELIST', 'CLERIC') else None,
                'wand_preservation': talent_points(hero, 'WAND_PRESERVATION')}
    if key.startswith('items.weapon.missiles.'):
        tier, quantity = MISSILE_PUBLIC_TYPES.get(key, (None, None))
        if key.startswith('items.weapon.missiles.darts.'):
            tier, quantity = (1 if key.endswith('.dart') else 2), 2
        return {'level': public['level'], 'tier': tier, 'default_quantity': quantity,
                'is_upgradable': public['is_upgradable'], 'durability': None}
    if key == 'items.trinkets.trinketcatalyst':
        options = item.get('rolled_trinkets', [])
        if options == []:
            return {'catalyst_stage': 'unrolled', 'rolled_choices': None}
        ids = [identity(option) for option in options] if isinstance(options, list) else []
        if len(ids) == 4 and all(value and value.startswith('items.trinkets.') for value in ids):
            return {'catalyst_stage': 'awaiting_choice', 'rolled_choices': ids}
        return {'catalyst_stage': None, 'rolled_choices': None}
    if key.startswith('items.trinkets.'):
        return {'level': public['level']}
    return {}


def cooked_fruit_name(state, messages):
    if state.get('cooked') == 'cooked':
        suffix = state.get('potion_id', '').removeprefix('items.potions.potionof')
        key = FRUIT_NAMES.get(suffix)
        if key:
            return messages.get('items.food.blandfruit.' + key)
    return None
