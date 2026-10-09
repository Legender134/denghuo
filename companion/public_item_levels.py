"""Player-visible equipment grades, distinct from stored and combat buff levels.

Derived from Shattered Pixel Dungeon 4.0.2, GPL-3.0-or-later, commit
57a4e06a4caf162446d1c28caa7983f0493fecf0: Item.visiblyUpgraded,
Weapon.level, Armor.level, Wand.level, SpiritBow.level/STRReq.
"""


def level_applies(identity):
    if identity in ('items.trinkets.trinketcatalyst', 'items.trinkets.trinketcatalyst$randomtrinket'):
        return False
    return identity.startswith(('items.weapon.', 'items.armor.', 'items.rings.',
                                'items.wands.', 'items.artifacts.', 'items.trinkets.'))


def scroll_upgradable(identity):
    """Eligibility for ordinary scroll upgrades, not whether an item has a grade."""
    return identity.startswith(('items.weapon.', 'items.armor.', 'items.rings.', 'items.wands.')) \
        and identity != 'items.weapon.spiritbow' and not identity.startswith('items.weapon.missiles.darts.')


def visible_level(item, game, *, known):
    if not known:
        return None
    identity = str(item.get('__className', '')).removeprefix('com.shatteredpixel.shatteredpixeldungeon.').lower()
    level = item.get('level', 0)
    if type(level) is not int:
        return None
    if identity == 'items.weapon.spiritbow':
        hero = game.get('hero')
        hero_level = hero.get('lvl') if isinstance(hero, dict) else None
        if type(hero_level) is not int or hero_level < 1:
            return None
        level = hero_level // 5
    infusion = item.get('curse_infusion_bonus') is True
    if identity.startswith('items.wands.'):
        infusion = infusion and item.get('cursed') is True
    if infusion and identity.startswith(('items.weapon.', 'items.armor.', 'items.wands.')):
        quotient = abs(level) // 6 * (-1 if level < 0 else 1)
        level += 1 + quotient
    if identity.startswith('items.wands.'):
        resin = item.get('resin_bonus', 0)
        if type(resin) is not int or resin < 0:
            return None
        level += resin
    return level
