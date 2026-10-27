from itertools import product

import pytest

from research.synthetic import posteriors, scenario
from research.constrained_review_v1.factorized import ClosedFormPosterior, column_tree, measure_tree, solve_fast
from research.constrained_review_v1.solver import PricingPolicy, constrained, measure


def test_closed_form_matches_enumerated_joint_law():
    for family in ('independent','correlated','conflicting','stale'):
        c=scenario('development',53000,family)
        models,_=posteriors(c)
        analytic=ClosedFormPosterior(c,1.8)
        dense=models[2]
        for h in product((-1,0,1),repeat=analytic.m):
            assert analytic.stats[h][0]==pytest.approx(dense.stats[h][0],abs=1e-12)
            assert analytic.stats[h][1]==pytest.approx(dense.stats[h][1],abs=1e-10)
            assert analytic.stats[h][2:]==pytest.approx(dense.stats[h][2:],abs=1e-10)


def test_tree_expectations_and_certificate_match_enumeration():
    c=scenario('development',53001,'correlated')
    dense,_=posteriors(c)
    analytic=[ClosedFormPosterior(c,f) for f in (1.,.65,1.8)]
    oracle=PricingPolicy(analytic,3,[1.,.5,2.])
    direct=measure(oracle,dense[0])
    tree=measure_tree(oracle,analytic[0])
    for key,value in direct.items():
        assert tree[key]==pytest.approx(value) if value is not None else tree[key] is None
    old=constrained(dense,3,.08)
    fast=solve_fast(analytic,3,.08)
    assert fast['solution']['primal']==pytest.approx(old['solution']['primal'],abs=1e-8)
    assert fast['gap']<1e-8
