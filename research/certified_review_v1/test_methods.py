import itertools
import unittest
from fractions import Fraction as F

from research.compiled_review_v1.belief import CompiledPosterior, TruthPosterior
from research.synthetic import case
from research.constrained_review_v1.factorized import measure_tree
from research.constrained_review_v1.solver import ExistingPolicy
from research.decision_review_v1.model import Policy
from research.certified_review_v1.belief import ReusablePosterior
from research.certified_review_v1.certificate import RationalRisk, certify, coupling_upper, inverse, split


class PatternPolicy:
    def __init__(self):
        c = case(99001, 1, 3)
        c.update(priors=[0.], truth_rho=0., facts=[0, 0, 0], errors=[.2]*3, rho=.5,
                 graph=[0], costs=[1]*3)
        self.p = CompiledPosterior(c)
        self.budget = 3

    def choose(self, h):
        return next((i for i, b in enumerate(h) if b < 0), None)

    def decode(self, h):
        return (-1, 1 if h == (1, 0, 0) else -1)


class MethodsTest(unittest.TestCase):
    def test_reuse_exact(self):
        for groups, outcomes in itertools.product((1, 2), (2, 3)):
            c = case(881, 3, 4, groups, outcomes)
            old, new, ref = CompiledPosterior(c), ReusablePosterior(c), TruthPosterior(c)
            for h in itertools.product(range(-1, outcomes), repeat=4):
                rows = [p.stats[h] for p in (old, new, ref)]
                for row in rows[1:]:
                    self.assertAlmostEqual(rows[0][0], row[0], places=12)
                    for a, b in zip(rows[0][1], row[1]):
                        self.assertAlmostEqual(a, b, places=12)
            self.assertGreater(new.factors.cache_info().hits, 0)

    def test_rational_matches(self):
        for groups, outcomes in itertools.product((1, 2), (2, 3)):
            c = case(951, 3, 4, groups, outcomes)
            p = CompiledPosterior(c)
            policy = ExistingPolicy(Policy(p, 3, 'exact_dp'))
            risk = RationalRisk(c, [policy], [1])
            for factor in (.65, 1., 1.15, 1.8, 3.):
                actual = CompiledPosterior(c, factor)
                self.assertAlmostEqual(float(risk.evaluate(F(str(factor)))), measure_tree(policy, actual)['risk'], places=12)
            bound = certify(risk, subdivisions=16)
            self.assertLessEqual(bound['lower'], bound['upper'])
            for i in range(31):
                value = risk.evaluate(F('0.65')+F('1.15')*i/30)
                self.assertLessEqual(value, bound['upper'])
                self.assertLessEqual(value, coupling_upper(risk))

    def test_interior_counterexample(self):
        policy = PatternPolicy()
        risk = RationalRisk(policy.p.case, [policy], [1])
        epsilon = F('0.0739')
        self.assertTrue(all(risk.evaluate(F(str(t))) < epsilon for t in (.65, 1., 1.8)))
        self.assertEqual(risk.evaluate(F(5, 3)), F(2, 27))
        bound = certify(risk, subdivisions=128)
        self.assertLessEqual(bound['lower'], F(2, 27))
        self.assertGreaterEqual(bound['upper'], F(2, 27))
        self.assertLess(bound['upper']-bound['lower'], F('0.000001'))

    def test_clipping_and_zero_degree(self):
        policy = PatternPolicy()
        policy.p.case['errors'] = [.4, .3, .2]
        risk = RationalRisk(policy.p.case, [policy], [1])
        result = certify(risk)
        self.assertGreater(result['cells'], 1)
        for i in range(61):
            self.assertLessEqual(risk.evaluate(F('0.65')+F('1.15')*i/60), result['upper'])
        from research.constrained_review_v1.solver import AbstainPolicy
        safe = RationalRisk(policy.p.case, [AbstainPolicy(policy.p, 3)], [1])
        self.assertEqual(certify(safe)['upper'], 0)

    def test_split(self):
        self.assertEqual(split((F(0), F(1), F(0))), ((F(0), F(1, 2), F(1, 2)), (F(1, 2), F(1, 2), F(0))))
        self.assertEqual(inverse(0), ((F(1),),))

    def test_repair_and_limits(self):
        from research.certified_review_v1.policy import repair
        from research.constrained_review_v1.solver import AbstainPolicy
        policy = PatternPolicy()
        safe = AbstainPolicy(policy.p, 3)
        risk = RationalRisk(policy.p.case, [safe, policy], [0, 1])
        result = certify(risk)
        weights, scale = repair([None, None], [F(0), F(1)], result['upper']*2)
        repaired = RationalRisk(policy.p.case, [safe, policy], weights)
        self.assertLessEqual(certify(repaired)['upper'], F('0.08'))
        with self.assertRaises(ValueError):
            RationalRisk(policy.p.case, [policy], [-1])
        with self.assertRaises(ValueError):
            certify(risk, low=0)
        limited = certify(risk, subdivisions=0)
        self.assertGreaterEqual(limited['upper'], F(2, 27))


if __name__ == '__main__':
    unittest.main()
