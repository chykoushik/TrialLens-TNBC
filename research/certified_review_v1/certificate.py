import heapq
import itertools
import math
from fractions import Fraction as F
from functools import lru_cache

from research.constrained_review_v1.factorized import action
from research.decision_review_v1.model import boolean


def rational(value):
    return value if isinstance(value, F) else F(str(value))


def terminals(policy):
    p = policy.p
    result = []

    def visit(h):
        a = action(policy, h)
        if a is None:
            result.append((h, tuple(policy.decode(h))))
        else:
            for b in range(p.case.get('outcomes', 2)):
                child = h[:a]+(b,)+h[a+1:]
                if b == 2 and p.case.get('erasures', [0.]*p.m)[a] == 0:
                    continue
                visit(child)
    visit(p.root)
    return result


class RationalRisk:
    def __init__(self, case, policies, weights):
        if case['n'] > 8:
            raise ValueError('rational_truth_cap')
        if len(policies) != len(weights) or not weights or any(rational(w) < 0 for w in weights) or sum(map(rational, weights)) <= 0:
            raise ValueError('invalid_mixture')
        if any(not 0 <= p <= 1 for p in case['priors']) or not 0 <= case['truth_rho'] <= 1:
            raise ValueError('invalid_prior')
        if any(q <= 0 for q in case['errors']):
            raise ValueError('positive_errors_required')
        if not 0 <= case['rho'] < 1 or any(not 0 <= r < 1 for r in case.get('group_rhos', {}).values()):
            raise ValueError('full_support_required')
        self.case = case
        total = sum(map(rational, weights))
        self.weights = [rational(w)/total for w in weights]
        self.leaves = [(w, terminals(p)) for w, p in zip(self.weights, policies) if w > 0]
        self.degree = max((sum(b in (0, 1) for b in h) for w, leaves in self.leaves for h, labels in leaves), default=0)
        self.priors = list(map(rational, case['priors']))
        tau = rational(case['truth_rho'])
        self.truths = []
        for truth in itertools.product((0, 1), repeat=case['n']):
            independent = math.prod(p if bit else 1-p for p, bit in zip(self.priors, truth))
            low = max([F(0)]+[p for p, bit in zip(self.priors, truth) if not bit])
            high = min([F(1)]+[p for p, bit in zip(self.priors, truth) if bit])
            prior = (1-tau)*independent+tau*max(F(0), high-low)
            targets = tuple(int(boolean(g, truth)) for g in case['graph'])
            if prior:
                self.truths.append((truth, prior, targets))
        self.evaluate = lru_cache(None)(self._evaluate)

    def likelihood(self, truth, h, errors):
        c = self.case
        value = F(1)
        groups = c.get('groups', [0]*len(h))
        for a, b in enumerate(h):
            if b >= 0:
                e = rational(c.get('erasures', [0.]*len(h))[a])
                value *= e if b == 2 else 1-e
        for group in set(groups):
            independent, low, high = F(1), F(0), F(1)
            for a, b in enumerate(h):
                if b not in (0, 1) or groups[a] != group:
                    continue
                noisy = b ^ truth[c['facts'][a]]
                independent *= errors[a] if noisy else 1-errors[a]
                if noisy:
                    high = min(high, errors[a])
                else:
                    low = max(low, errors[a])
            rho = rational(c.get('group_rhos', {}).get(str(group), c['rho']))
            value *= (1-rho)*independent+rho*max(F(0), high-low)
        return value

    def _evaluate(self, theta):
        c = self.case
        errors = [min(F('0.49'), max(F('0.005'), rational(q)*theta)) for q in c['errors']]
        risk = F(0)
        for weight, leaves in self.leaves:
            for h, labels in leaves:
                labels = labels[c['n']:]
                if all(label < 0 for label in labels):
                    continue
                for truth, prior, targets in self.truths:
                    error = F(sum(label >= 0 and label != target for label, target in zip(labels, targets)), len(targets))
                    if error:
                        risk += weight*prior*error*self.likelihood(truth, h, errors)
        return risk

    def knots(self, low, high):
        return sorted({low, high, *(k/rational(q) for q in self.case['errors'] for k in (F('0.005'), F('0.49')) if low < k/rational(q) < high)})


@lru_cache(None)
def inverse(degree):
    if degree == 0:
        return ((F(1),),)
    a = []
    for i in range(degree+1):
        x = F(i, degree)
        a.append([F(math.comb(degree, j))*x**j*(1-x)**(degree-j) for j in range(degree+1)]+[F(i == j) for j in range(degree+1)])
    for i in range(degree+1):
        pivot = next(j for j in range(i, degree+1) if a[j][i])
        a[i], a[pivot] = a[pivot], a[i]
        scale = a[i][i]
        a[i] = [v/scale for v in a[i]]
        for j in range(degree+1):
            if j != i:
                scale = a[j][i]
                a[j] = [v-scale*u for v, u in zip(a[j], a[i])]
    return tuple(tuple(row[degree+1:]) for row in a)


def split(coefficients):
    row = list(coefficients)
    left, right = [row[0]], [row[-1]]
    while len(row) > 1:
        row = [(a+b)/2 for a, b in zip(row, row[1:])]
        left.append(row[0])
        right.append(row[-1])
    return tuple(left), tuple(reversed(right))


def certify(risk, low=F('0.65'), high=F('1.8'), tolerance=F('0.000001'), subdivisions=128):
    low, high = rational(low), rational(high)
    if low <= 0 or high <= low or tolerance < 0 or subdivisions < 0:
        raise ValueError('invalid_interval')
    d = risk.degree
    queue, best, witness, serial = [], F(-1), low, 0

    def add(a, b, coefficients):
        nonlocal best, witness, serial
        for x, value in ((a, coefficients[0]), (b, coefficients[-1]), ((a+b)/2, risk.evaluate((a+b)/2))):
            if value > best:
                best, witness = value, x
        heapq.heappush(queue, (-max(coefficients), serial, a, b, coefficients))
        serial += 1
    knots = risk.knots(low, high)
    for a, b in zip(knots, knots[1:]):
        values = [risk.evaluate(a+(b-a)*F(i, d)) for i in range(d+1)] if d else [risk.evaluate(a)]
        coefficients = tuple(sum(q*v for q, v in zip(row, values)) for row in inverse(d))
        add(a, b, coefficients)
    used = 0
    while -queue[0][0]-best > tolerance and used < subdivisions:
        upper, _, a, b, coefficients = heapq.heappop(queue)
        left, right = split(coefficients)
        add(a, (a+b)/2, left)
        add((a+b)/2, b, right)
        used += 1
    return dict(lower=best, upper=-queue[0][0], witness=witness, subdivisions=used, cells=len(knots)-1,
                evaluations=risk.evaluate.cache_info().currsize, degree=d)


def coupling_upper(risk, low=F('0.65'), high=F('1.8')):
    c = risk.case
    center = (low+high)/2
    total = F(0)
    for weight, leaves in risk.leaves:
        actions = {a for h, labels in leaves for a, b in enumerate(h) if b >= 0}
        group_bounds = []
        groups = c.get('groups', [0]*len(c['facts']))
        for group in set(groups):
            radii = []
            for a in actions:
                if groups[a] != group:
                    continue
                q = rational(c['errors'][a])
                clip = lambda x: min(F('0.49'), max(F('0.005'), q*x))
                r = max(abs(clip(low)-clip(center)), abs(clip(high)-clip(center)))
                radii.append((1-rational(c.get('erasures', [0.]*len(groups))[a]))*r)
            rho = rational(c.get('group_rhos', {}).get(str(group), c['rho']))
            group_bounds.append((1-rho)*(1-math.prod(1-r for r in radii))+rho*min(F(1), sum(radii)))
        total += weight*(1-math.prod(1-v for v in group_bounds))
    return min(F(1), risk.evaluate(center)+total)
