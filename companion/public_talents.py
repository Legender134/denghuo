"""Public talent points using the pinned game's class/replacement restore rules."""
from .public_source_data import CLASS_TALENTS

PREFIX = 'com.shatteredpixel.shatteredpixeldungeon.'
MAXIMUM = {'STRONGMAN': 3, 'WAND_PRESERVATION': 2, 'SPIRIT_FORM': 4}


def talent_points(hero, name):
    """Absent points restore to zero; malformed or unsupported contexts stay unknown.

    Hero.pointsInTalent returns the first eligible talent. Class replacements are
    applied before saved tier values, and armor talents are not metamorphed.
    """
    cls = hero.get('class')
    if cls not in CLASS_TALENTS or name not in MAXIMUM:
        return None
    replacements = hero.get('replacements', {})
    if not isinstance(replacements, dict):
        return None
    for tier in range(1, 5):
        saved = hero.get('talents_tier_' + str(tier), {})
        if not isinstance(saved, dict):
            return None
        eligible = []
        if tier <= 3:
            for original in CLASS_TALENTS[cls][tier]:
                replacement = replacements.get(original, original)
                if not isinstance(replacement, str):
                    return None
                eligible.append(replacement)
        else:
            ability = hero.get('armorAbility')
            if ability is not None and not isinstance(ability, dict):
                return None
            if isinstance(ability, dict) and ability.get('__className') == PREFIX + 'actors.hero.abilities.cleric.Trinity':
                eligible = ['BODY_FORM', 'MIND_FORM', 'SPIRIT_FORM', 'HEROIC_ENERGY']
        if name in eligible:
            value = saved.get(name, 0)
            if type(value) is not int or value < 0:
                return None
            return min(value, MAXIMUM[name])
    return 0
