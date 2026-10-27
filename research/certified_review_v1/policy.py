from fractions import Fraction as F

EPSILON = F('0.08')


def repair(columns, weights, upper):
    scale = min(F(1), EPSILON/upper) if upper > 0 else F(1)
    result = [w*scale for w in weights]
    result[0] += 1-scale
    return result, scale
