"""Public talents and selected armor ability, never action readiness.

Talent restore and armor talent lists, SPD 4.0.2,
57a4e06a4caf162446d1c28caa7983f0493fecf0, GPL-3.0-or-later.
Oleg Dolya 2012-2015; Evan Debenham 2014-2026.
"""
from .public_source_data import CLASS_TALENTS

PREFIX = 'com.shatteredpixel.shatteredpixeldungeon.'
TALENT_PREFIX = 'actors.hero.talent.'
ABILITY_PREFIX = 'actors.hero.abilities.'
SUBCLASSES = {
    'WARRIOR': ('BERSERKER', 'GLADIATOR'), 'MAGE': ('BATTLEMAGE', 'WARLOCK'),
    'ROGUE': ('ASSASSIN', 'FREERUNNER'), 'HUNTRESS': ('SNIPER', 'WARDEN'),
    'DUELIST': ('CHAMPION', 'MONK'), 'CLERIC': ('PRIEST', 'PALADIN'),
}
SUBCLASS_TALENTS = {
    'BERSERKER': ('ENDLESS_RAGE', 'DEATHLESS_FURY', 'ENRAGED_CATALYST'),
    'GLADIATOR': ('CLEAVE', 'LETHAL_DEFENSE', 'ENHANCED_COMBO'),
    'BATTLEMAGE': ('EMPOWERED_STRIKE', 'MYSTICAL_CHARGE', 'EXCESS_CHARGE'),
    'WARLOCK': ('SOUL_EATER', 'SOUL_SIPHON', 'NECROMANCERS_MINIONS'),
    'ASSASSIN': ('ENHANCED_LETHALITY', 'ASSASSINS_REACH', 'BOUNTY_HUNTER'),
    'FREERUNNER': ('EVASIVE_ARMOR', 'PROJECTILE_MOMENTUM', 'SPEEDY_STEALTH'),
    'SNIPER': ('FARSIGHT', 'SHARED_ENCHANTMENT', 'SHARED_UPGRADES'),
    'WARDEN': ('DURABLE_TIPS', 'BARKSKIN', 'SHIELDING_DEW'),
    'CHAMPION': ('VARIED_CHARGE', 'TWIN_UPGRADES', 'COMBINED_LETHALITY'),
    'MONK': ('UNENCUMBERED_SPIRIT', 'MONASTIC_VIGOR', 'COMBINED_ENERGY'),
    'PRIEST': ('HOLY_LANCE', 'HALLOWED_GROUND', 'MNEMONIC_PRAYER'),
    'PALADIN': ('LAY_ON_HANDS', 'AURA_OF_PROTECTION', 'WALL_OF_LIGHT'),
}
ARMOR_TALENTS = {
    'warrior.HeroicLeap': ('BODY_SLAM', 'IMPACT_WAVE', 'DOUBLE_JUMP'),
    'warrior.Shockwave': ('EXPANDING_WAVE', 'STRIKING_WAVE', 'SHOCK_FORCE'),
    'warrior.Endure': ('SUSTAINED_RETRIBUTION', 'SHRUG_IT_OFF', 'EVEN_THE_ODDS'),
    'mage.ElementalBlast': ('BLAST_RADIUS', 'ELEMENTAL_POWER', 'REACTIVE_BARRIER'),
    'mage.WildMagic': ('WILD_POWER', 'FIRE_EVERYTHING', 'CONSERVED_MAGIC'),
    'mage.WarpBeacon': ('TELEFRAG', 'REMOTE_BEACON', 'LONGRANGE_WARP'),
    'rogue.SmokeBomb': ('HASTY_RETREAT', 'BODY_REPLACEMENT', 'SHADOW_STEP'),
    'rogue.DeathMark': ('FEAR_THE_REAPER', 'DEATHLY_DURABILITY', 'DOUBLE_MARK'),
    'rogue.ShadowClone': ('SHADOW_BLADE', 'CLONED_ARMOR', 'PERFECT_COPY'),
    'huntress.SpectralBlades': ('FAN_OF_BLADES', 'PROJECTING_BLADES', 'SPIRIT_BLADES'),
    'huntress.NaturesPower': ('GROWING_POWER', 'NATURES_WRATH', 'WILD_MOMENTUM'),
    'huntress.SpiritHawk': ('EAGLE_EYE', 'GO_FOR_THE_EYES', 'SWIFT_SPIRIT'),
    'duelist.Challenge': ('CLOSE_THE_GAP', 'INVIGORATING_VICTORY', 'ELIMINATION_MATCH'),
    'duelist.ElementalStrike': ('ELEMENTAL_REACH', 'STRIKING_FORCE', 'DIRECTED_POWER'),
    'duelist.Feint': ('FEIGNED_RETREAT', 'EXPOSE_WEAKNESS', 'COUNTER_ABILITY'),
    'cleric.AscendedForm': ('DIVINE_INTERVENTION', 'JUDGEMENT', 'FLASH'),
    'cleric.Trinity': ('BODY_FORM', 'MIND_FORM', 'SPIRIT_FORM'),
    'cleric.PowerOfMany': ('BEAMING_RAY', 'LIFE_LINK', 'STASIS'),
    'Ratmogrify': ('RATSISTANCE', 'RATLOMACY', 'RATFORCEMENTS'),
}
LIMITS = '公开已投入点数；触发条件、充能、冷却和目标仍需核对，不代表当前可施放。'


def class_tiers(hero):
    cls = hero.get('class')
    if cls not in CLASS_TALENTS:
        return None
    replacements = hero.get('replacements', {})
    if not isinstance(replacements, dict):
        return None
    base = CLASS_TALENTS[cls]
    originals = {name: tier for tier, names in base.items() for name in names}
    for original, replacement in replacements.items():
        tier = originals.get(original)
        choices = {name for tiers in CLASS_TALENTS.values() for name in tiers.get(tier, ())}
        if tier is None or not isinstance(replacement, str) or replacement not in choices:
            return None
    tiers = {tier: [replacements.get(name, name) for name in names] for tier, names in base.items()}
    return None if any(len(names) != len(set(names)) for names in tiers.values()) else tiers


def armor_talents(hero):
    ability = hero.get('armorAbility')
    if ability is None:
        return '', ()
    if not isinstance(ability, dict) or not isinstance(ability.get('__className'), str):
        return None
    name = ability['__className']
    start = PREFIX + ABILITY_PREFIX
    if not name.startswith(start):
        return None
    relative = name[len(start):]
    if relative not in ARMOR_TALENTS or (relative != 'Ratmogrify' and relative.split('.')[0].upper() != hero.get('class')):
        return None
    return ABILITY_PREFIX + relative.lower(), (*ARMOR_TALENTS[relative], 'HEROIC_ENERGY')


def project_build(game, catalog):
    hero = game.get('hero') or {}
    result = {'state': 'unknown', 'talents': {}, 'ability': None,
              'conditions': '当前天赋与护甲能力来源未确认；百科点数为独立示例。'}
    if not isinstance(hero, dict) or type(game.get('version')) is not int or game['version'] != catalog.data['version_code']:
        return result
    cls, subclass = hero.get('class'), hero.get('subClass', 'NONE')
    tiers, armor = class_tiers(hero), armor_talents(hero)
    if tiers is None or subclass not in ('NONE', *SUBCLASSES[cls]) or armor is None:
        return result
    tiers[3].extend(SUBCLASS_TALENTS.get(subclass, ()))
    tiers[4] = armor[1]
    for tier, names in tiers.items():
        saved = hero.get('talents_tier_' + str(tier), {})
        for name in names:
            points = saved.get(name, 0) if isinstance(saved, dict) else None
            if type(points) is not int or points < 0:
                row = {'state': 'unknown', 'points': None, 'conditions': '此天赋保存点数未确认；百科点数为独立示例。'}
            else:
                points = min(points, 2 if tier < 3 else tier)
                row = {'state': 'learned' if points else 'not_learned', 'points': points,
                       'conditions': f'公开天赋已投入 {points} 点。' + LIMITS}
            result['talents'][TALENT_PREFIX + name.lower()] = {**row, 'tier': tier}
    result.update(state='known', conditions=LIMITS)
    if armor[0]:
        summary = []
        for name in armor[1]:
            identity = TALENT_PREFIX + name.lower()
            row = result['talents'][identity]
            title = catalog.entry_index.get(identity, {}).get('name', '相关天赋')
            summary.append(title + ' ' + (str(row['points']) + ' 点' if row['points'] is not None else '点数未确认'))
        result['ability'] = {'id': armor[0], 'state': 'selected',
                             'conditions': '已选择此护甲能力；' + '；'.join(summary) + '。' + LIMITS}
    return result


def build_context(snapshot, identity):
    from .decisions import source
    data = {} if snapshot.get('error') else snapshot.get('data') or {}
    build = data.get('hero', {}).get('build') or {}
    field = 'talent' if identity.startswith(TALENT_PREFIX) else 'shielding_dew'
    if identity.startswith(ABILITY_PREFIX):
        ability = build.get('ability')
        return {'params': {}, 'skill_state': 'selected', 'conditions': ability['conditions']} if ability and ability['id'] == identity else {
            'params': {}, 'skill_state': 'unknown', 'conditions': '未确认当前选择此护甲能力；以下为独立参考。'}
    if not identity.startswith(TALENT_PREFIX) and identity not in ('items.waterskin', 'items.dewdrop'):
        return {}
    talent = identity if field == 'talent' else TALENT_PREFIX + 'shielding_dew'
    row = build.get('talents', {}).get(talent)
    if row is None:
        row = ({'state': 'not_applicable', 'points': 0, 'conditions': '当前职业与转职不提供此天赋，按未投入 0 点参考。'}
               if build.get('state') == 'known' else {'state': 'unknown', 'points': None, 'conditions': '当前天赋点数未确认；请核对独立示例。'})
    points = row['points']
    known = type(points) is int and 0 <= points <= 4
    label = source(snapshot)['label'] + (f' · 此天赋已投入 {points} 点' if known else ' · 天赋点数未确认')
    params = {field: points} if known else {}
    if field == 'shielding_dew':
        from .decisions import public_context
        public = public_context(snapshot)
        if 'current_shield' in public:
            params['current_shield'] = public['current_shield']
        items = data.get('items', [])
        vials = [item for item in items if item.get('kind') == 'VialOfBlood']
        if not vials and build.get('state') == 'known':
            params['vial'] = -1
        elif len(vials) == 1 and vials[0].get('known') and vials[0].get('available') and vials[0].get('level_known') and type(vials[0].get('level')) is int and -1 <= vials[0]['level'] <= 3:
            params['vial'] = vials[0]['level']
        water = [item for item in items if item.get('key') == 'items.waterskin' and item.get('known') and item.get('available')]
        if identity == 'items.waterskin' and len(water) == 1 and type(water[0].get('volume')) is int:
            params['dew_volume'] = water[0]['volume']
    origins = {key: source(snapshot)['label'] for key in params}
    origins[field] = label
    return {'params': params, 'field_origins': origins,
            'skill_state': row['state'], 'conditions': row['conditions']}
