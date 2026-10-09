"""Public type constants from SPD 4.0.2, GPL-3.0-or-later.
Oleg Dolya 2012-2015; Evan Debenham 2014-2026.
Pinned commit 57a4e06a4caf162446d1c28caa7983f0493fecf0."""

CLASS_TALENTS = {
    'CLERIC': {1: ('SATIATED_SPELLS', 'HOLY_INTUITION', 'SEARING_LIGHT', 'SHIELD_OF_LIGHT'), 2: ('ENLIGHTENING_MEAL', 'RECALL_INSCRIPTION', 'SUNRAY', 'DIVINE_SENSE', 'BLESS'), 3: ('CLEANSE', 'LIGHT_READING')},
    'DUELIST': {1: ('STRENGTHENING_MEAL', 'ADVENTURERS_INTUITION', 'PATIENT_STRIKE', 'AGGRESSIVE_BARRIER'), 2: ('FOCUSED_MEAL', 'LIQUID_AGILITY', 'WEAPON_RECHARGING', 'LETHAL_HASTE', 'SWIFT_EQUIP'), 3: ('PRECISE_ASSAULT', 'DEADLY_FOLLOWUP')},
    'HUNTRESS': {1: ('NATURES_BOUNTY', 'SURVIVALISTS_INTUITION', 'FOLLOWUP_STRIKE', 'NATURES_AID'), 2: ('INVIGORATING_MEAL', 'LIQUID_NATURE', 'REJUVENATING_STEPS', 'HEIGHTENED_SENSES', 'DURABLE_PROJECTILES'), 3: ('POINT_BLANK', 'SEER_SHOT')},
    'MAGE': {1: ('EMPOWERING_MEAL', 'SCHOLARS_INTUITION', 'LINGERING_MAGIC', 'BACKUP_BARRIER'), 2: ('ENERGIZING_MEAL', 'INSCRIBED_POWER', 'WAND_PRESERVATION', 'ARCANE_VISION', 'SHIELD_BATTERY'), 3: ('DESPERATE_POWER', 'ALLY_WARP')},
    'ROGUE': {1: ('CACHED_RATIONS', 'THIEFS_INTUITION', 'SUCKER_PUNCH', 'PROTECTIVE_SHADOWS'), 2: ('MYSTICAL_MEAL', 'INSCRIBED_STEALTH', 'WIDE_SEARCH', 'SILENT_STEPS', 'ROGUES_FORESIGHT'), 3: ('ENHANCED_RINGS', 'LIGHT_CLOAK')},
    'WARRIOR': {1: ('HEARTY_MEAL', 'VETERANS_INTUITION', 'PROVOKED_ANGER', 'IRON_WILL'), 2: ('IRON_STOMACH', 'LIQUID_WILLPOWER', 'RUNIC_TRANSFERENCE', 'LETHAL_MOMENTUM', 'IMPROVISED_PROJECTILES'), 3: ('HOLD_FAST', 'STRONGMAN')},
}

MISSILE_PUBLIC_TYPES = {
    'items.weapon.missiles.bolas': (3, 3),
    'items.weapon.missiles.fishingspear': (2, 3),
    'items.weapon.missiles.forcecube': (5, 3),
    'items.weapon.missiles.heavyboomerang': (4, 3),
    'items.weapon.missiles.javelin': (4, 3),
    'items.weapon.missiles.kunai': (3, 3),
    'items.weapon.missiles.shuriken': (2, 3),
    'items.weapon.missiles.throwingclub': (2, 3),
    'items.weapon.missiles.throwinghammer': (5, 3),
    'items.weapon.missiles.throwingknife': (1, 3),
    'items.weapon.missiles.throwingspear': (3, 3),
    'items.weapon.missiles.throwingspike': (1, 3),
    'items.weapon.missiles.throwingstone': (1, 3),
    'items.weapon.missiles.tomahawk': (4, 3),
    'items.weapon.missiles.trident': (5, 3),
}
