from functools import lru_cache

from research.compiled_review_v1.belief import CompiledPosterior, Diagram


class CachedDiagram(Diagram):
    def __init__(self, graphs, n, capacity=512):
        super().__init__(graphs, n)
        self.evaluate = lru_cache(capacity)(super().distribution)

    def distribution(self, probabilities):
        return self.evaluate(tuple(probabilities))


class ReusablePosterior(CompiledPosterior):
    def __init__(self, case, factor=1., capacity=512, diagram=None):
        super().__init__(case, factor, diagram=diagram or CachedDiagram(case['graph'], case['n'], capacity))
        self.factors = lru_cache(capacity)(self._factors)
        self.groups = case.get('groups', [0]*self.m)
        self.prior = super().components(self.root)

    def _factors(self, group, observations):
        observed = [a for a, b in observations]
        independent = [[1., 1.] for _ in range(self.n)]
        for a, b in observations:
            fact, q = self.case['facts'][a], self.errors[a]
            independent[fact][0] *= q if b else 1-q
            independent[fact][1] *= 1-q if b else q
        rho = self.case.get('group_rhos', {}).get(str(group), self.case['rho'])
        if len(observed) <= 1 or rho == 0:
            return [(1., independent)]
        result = [(1-rho, independent)] if rho < 1 else []
        cuts = sorted({0., 1., *(self.errors[a] for a in observed)})
        for low, high in zip(cuts, cuts[1:]):
            constraints = {}
            for a, b in observations:
                fact = self.case['facts'][a]
                required = b ^ int((low+high)/2 < self.errors[a])
                if fact in constraints and constraints[fact] != required:
                    break
                constraints[fact] = required
            else:
                likelihood = [[1., 1.] for _ in range(self.n)]
                for fact, bit in constraints.items():
                    likelihood[fact][1-bit] = 0.
                result.append((rho*(high-low), likelihood))
        return result

    def components(self, h):
        if not hasattr(self, 'prior'):
            return super().components(h)
        base = self.prior
        erasure = 1.
        for a, b in enumerate(h):
            if b >= 0:
                q = self.case.get('erasures', [0.]*self.m)[a]
                erasure *= q if b == 2 else 1-q
        for group in sorted(set(self.groups)):
            observations = tuple((a, b) for a, b in enumerate(h) if b in (0, 1) and self.groups[a] == group)
            if not observations:
                continue
            merged = {}
            for weight, probs in base:
                for coefficient, likelihood in self.factors(group, observations):
                    updated = []
                    mass = weight*coefficient
                    for prob, (l0, l1) in zip(probs, likelihood):
                        z = (1-prob)*l0+prob*l1
                        if z <= 0:
                            mass = 0.
                            break
                        mass *= z
                        updated.append(prob*l1/z)
                    if mass > 0:
                        key = tuple(updated)
                        merged[key] = merged.get(key, 0.)+mass
            base = [(weight, key) for key, weight in merged.items()]
        return [(weight*erasure, probs) for weight, probs in base if weight*erasure > 0]
