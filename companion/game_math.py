"""Small numeric operations matching the game's single precision arithmetic."""
import math
import struct


def float32(value):
    return struct.unpack('f', struct.pack('f', value))[0]


def augmented_damage(value, factor):
    # Weapon factors and multiplication are Java floats before Math.round.
    return math.floor(float32(float32(value) * float32(factor)) + .5)


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
