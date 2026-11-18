"""Small numeric operations matching the game's single precision arithmetic."""
import math
import struct


def float32(value):
    return struct.unpack('f', struct.pack('f', value))[0]


def augmented_damage(value, factor):
    # Weapon factors and multiplication are Java floats before Math.round.
    return math.floor(float32(float32(value) * float32(factor)) + .5)


def challenge_healing(damage, points):
    # Challenge: .707f is widened to double by Math.pow, not kept as a float.
    return math.floor(damage * (1 - math.pow(float32(.707), points)) + .5) + 5 * points


RING_POWER_BASES = {
    'accuracy': float32(1.3), 'arcana': float32(1.175),
    'elements': .825, 'energy': 1.175, 'evasion': 1.125, 'furor': 1.09051,
    'haste': 1.15, 'might': 1.035, 'sharpshooting': 1.2, 'wealth': 1.2,
    'tenacity': .85,
}


def ring_multiplier(kind, bonus, maximum=1, current=1):
    # Only Accuracy and Arcana widen a float literal into Math.pow's double base.
    exponent = bonus
    if kind == 'tenacity':
        missing = float32((maximum-current)/float32(maximum))
        exponent = float32(float32(bonus)*missing)
    try:
        return float32(math.pow(RING_POWER_BASES[kind], exponent))
    except OverflowError as exc:
        raise ValueError('戒指效果超出游戏单精度有限数值范围') from exc


def potion_healing_pool(maximum):
    # PotionOfHealing: cast to int after float multiplication and addition.
    return int(float32(float32(float32(.8) * maximum) + 14))


def healing_pool_with_vial(amount, vial):
    return augmented_damage(amount, 1 + .125 * (vial + 1)) if vial >= 0 else amount


def healing_tick(left, percent, flat, vial, maximum):
    if left <= 0:
        return 0
    tick = min(left, max(1, augmented_damage(left, percent) + flat))
    if vial >= 0:
        base, factor = ((4, .15), (3, .10), (2, .07), (1, .05))[vial]
        tick = min(tick, base + augmented_damage(maximum, factor))
    return tick


def monk_empowered(energy, capacity, points):
    ratio=float32(float32(energy)/float32(capacity))
    threshold=float32(float32(1.2)-float32(float32(.2)*points))
    return ratio >= threshold


def stone_factor(accuracy, evasion, multiplier=1):
    accuracy=float32(accuracy)
    evasion=float32(float32(evasion)*float32(multiplier))
    if accuracy==0 and evasion==0:
        return None  # The game's zero/zero path is NaN, cast to zero damage.
    chance=float32(float32(accuracy/evasion)/2) if evasion>=accuracy else float32(1-float32(float32(evasion/accuracy)/2))
    return min(1,max(.25,float32(float32(1+float32(3*chance))/4)))
