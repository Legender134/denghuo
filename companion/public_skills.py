"""Public learned spells from SPD 4.0.2, never spell readiness or tracker data.

Talent.restoreTalentsFromBundle, ClericSpell.getSpellList and cleric armor
abilities, pinned 57a4e06a4caf162446d1c28caa7983f0493fecf0.
GPL-3.0-or-later; Oleg Dolya 2012-2015; Evan Debenham 2014-2026.
"""
from .public_source_data import CLASS_TALENTS

PREFIX = 'com.shatteredpixel.shatteredpixeldungeon.'
SPELL_PREFIX = 'actors.hero.spells.'
CLASS_SPELLS = {
    'holyintuition': 'HOLY_INTUITION', 'shieldoflight': 'SHIELD_OF_LIGHT',
    'recallinscription': 'RECALL_INSCRIPTION', 'sunray': 'SUNRAY',
    'divinesense': 'DIVINE_SENSE', 'blessspell': 'BLESS', 'cleanse': 'CLEANSE',
}
SUBCLASS_TALENTS = {
    'PRIEST': ('HOLY_LANCE', 'HALLOWED_GROUND', 'MNEMONIC_PRAYER'),
    'PALADIN': ('LAY_ON_HANDS', 'AURA_OF_PROTECTION', 'WALL_OF_LIGHT'),
}
SUBCLASS_SPELLS = {
    'holylance': 'HOLY_LANCE', 'hallowedground': 'HALLOWED_GROUND',
    'mnemonicprayer': 'MNEMONIC_PRAYER', 'layonhands': 'LAY_ON_HANDS',
    'auraofprotection': 'AURA_OF_PROTECTION', 'walloflight': 'WALL_OF_LIGHT',
}
ARMOR_TALENTS = {
    'AscendedForm': ('DIVINE_INTERVENTION', 'JUDGEMENT', 'FLASH'),
    'Trinity': ('BODY_FORM', 'MIND_FORM', 'SPIRIT_FORM'),
    'PowerOfMany': ('BEAMING_RAY', 'LIFE_LINK', 'STASIS'),
    'Ratmogrify': ('RATSISTANCE', 'RATLOMACY', 'RATFORCEMENTS'),
}
ARMOR_SPELLS = {
    'divineintervention': 'DIVINE_INTERVENTION', 'judgement': 'JUDGEMENT', 'flash': 'FLASH',
    'bodyform': 'BODY_FORM', 'mindform': 'MIND_FORM', 'spiritform': 'SPIRIT_FORM',
    'beamingray': 'BEAMING_RAY', 'lifelinkspell': 'LIFE_LINK', 'stasis': 'STASIS',
}
TALENT_SPELLS = {**CLASS_SPELLS, **SUBCLASS_SPELLS, **ARMOR_SPELLS}
FREE_SPELLS = {'guidinglight': None, 'holyweapon': None, 'holyward': None,
               'radiance': 'PRIEST', 'smite': 'PALADIN'}
LIMITS = '已学技能参考；未确认圣典充能、冷却、目标和临时状态，不代表当前可施放。'


def _class_tiers(hero):
    """Apply the saved one-step original-to-final replacement, without chaining.

    Metamorphosis offers class talents at the same tier. Repeated changes store
    the original key with its final replacement; duplicate/conflicting maps do
    not establish a trustworthy learned rank.
    """
    replacements = hero.get('replacements', {})
    if not isinstance(replacements, dict):
        return None
    base = CLASS_TALENTS['CLERIC']
    originals = {name: tier for tier, names in base.items() for name in names}
    for original, replacement in replacements.items():
        tier = originals.get(original)
        choices = {name for tiers in CLASS_TALENTS.values() for name in tiers.get(tier, ())}
        if tier is None or not isinstance(replacement, str) or replacement not in choices:
            return None
    tiers = {tier: [replacements.get(name, name) for name in names] for tier, names in base.items()}
    if any(len(names) != len(set(names)) for names in tiers.values()):
        return None
    return tiers


def _armor_talents(hero):
    ability = hero.get('armorAbility')
    if ability is None:
        return ()
    if not isinstance(ability, dict):
        return None
    name = ability.get('__className')
    if not isinstance(name, str):
        return None
    allowed = {PREFIX + 'actors.hero.abilities.cleric.' + key: value
               for key, value in ARMOR_TALENTS.items() if key != 'Ratmogrify'}
    allowed[PREFIX + 'actors.hero.abilities.Ratmogrify'] = ARMOR_TALENTS['Ratmogrify']
    return allowed.get(name)


def project_skills(game, version_code):
    """Project only source-confirmed spell identities, eligibility and point counts."""
    hero = game.get('hero')
    hero = hero if isinstance(hero, dict) else {}
    exact_version = type(game.get('version')) is int and game['version'] == version_code
    cls = hero.get('class')
    subclass = hero.get('subClass', 'NONE')
    tiers = _class_tiers(hero) if cls == 'CLERIC' else None
    armor = _armor_talents(hero) if cls == 'CLERIC' else None
    valid_subclass = subclass in ('NONE', 'PRIEST', 'PALADIN')
    if tiers is not None and valid_subclass:
        tiers[3].extend(SUBCLASS_TALENTS.get(subclass, ()))
        tiers[4] = list(armor) + ['HEROIC_ENERGY'] if armor is not None else None
    result = {}
    for spell, talent in {**TALENT_SPELLS, **FREE_SPELLS}.items():
        row = {'state': 'unknown', 'points': None, 'conditions': '当前已学技能条件未确认；百科点数为独立示例。'}
        if spell in TALENT_SPELLS:
            row['talent'] = talent
        if not exact_version or cls not in CLASS_TALENTS:
            pass
        elif cls != 'CLERIC':
            row.update(state='not_applicable', conditions='当前职业不适用牧师法术；百科点数为独立示例。')
        elif not valid_subclass or tiers is None:
            pass
        elif spell in FREE_SPELLS:
            if talent is None or talent == subclass:
                row.update(state='learned', points=0, conditions='此法术不依赖天赋投入。' + LIMITS)
            else:
                row.update(state='not_applicable', conditions='当前副职业不适用此法术；百科点数为独立示例。')
        else:
            tier = 1 if talent in CLASS_TALENTS['CLERIC'][1] else 2 if talent in CLASS_TALENTS['CLERIC'][2] else 4 if spell in ARMOR_SPELLS else 3
            eligible = tiers.get(tier)
            saved = hero.get('talents_tier_' + str(tier), {})
            if eligible is None or not isinstance(saved, dict):
                pass
            elif talent not in eligible:
                row.update(state='not_applicable', conditions='当前职业、变形替换、副职业或护甲能力未提供此法术；百科点数为独立示例。')
            else:
                points = saved.get(talent, 0)
                if type(points) is int and points >= 0:
                    points = min(points, 2 if tier <= 2 else tier)
                    row.update(state='learned' if points else 'not_learned', points=points,
                               conditions=(f'公开天赋已投入 {points} 点。' + LIMITS) if points else '当前此天赋未投入，尚未学会此法术；百科点数为独立示例。')
        result[SPELL_PREFIX + spell] = row
    return result


def skill_context(snapshot, identity):
    """Entry-specific fields only; projection metadata never becomes numeric args."""
    if not identity.startswith(SPELL_PREFIX) or '$' in identity:
        from .public_build import build_context
        return build_context(snapshot, identity)
    from .decisions import source
    data = {} if snapshot.get('error') else snapshot.get('data') or {}
    row = data.get('hero', {}).get('skills', {}).get(identity)
    row = row or {'state': 'unknown', 'points': None, 'conditions': '当前已学技能条件未确认；百科点数为独立示例。'}
    learned = row['state'] == 'learned' and type(row.get('points')) is int
    provenance = source(snapshot)
    prefix = '手动局势' if provenance['mode'] == 'manual' else '快照'
    label = (prefix + ' · ' + provenance['label'] + f' · 此技能已学 {row["points"]} 点'
             if learned else '示例 · ' + row['conditions'].split('；')[0])
    return {'params': {'talent': row['points']} if learned and row.get('talent') else {},
            'field_origins': {'talent': label} if row.get('talent') or not learned else {}, 'skill_state': row['state'],
            'conditions': row['conditions']}
