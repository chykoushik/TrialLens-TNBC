from itertools import product

import pytest

from research.decision_review_v1.model import Posterior, Policy, generate, world_law
from research.constrained_review_v1.solver import (
    AbstainPolicy, ExistingPolicy, LazyPosterior, PricingPolicy, constrained,
    master, measure, policy_column,
)


def small():
    c=generate('development',50000,'shared')
    c.update(n=2,facts=[0,1],costs=[1,1],errors=[.1,.15],priors=[.4,.6],graph=[['AND',0,1],['OR',0,1]])
    return c


def test_lazy_matches_dense_all_histories():
    c=small()
    dense=Posterior(c,world_law(c))
    lazy=LazyPosterior(c,world_law(c))
    assert not lazy.stats
    for h in product((-1,0,1),repeat=2):
        assert lazy.stats[h][0]==pytest.approx(dense.stats[h][0])
        assert lazy.stats[h][1]==pytest.approx(dense.stats[h][1])
        assert lazy.stats[h][2:]==pytest.approx(dense.stats[h][2:])


def test_zero_price_matches_existing_reference():
    c=small()
    p=LazyPosterior(c,world_law(c))
    old=ExistingPolicy(Policy(p,2,'exact_dp'))
    new=PricingPolicy([p],2,[0.])
    assert measure(old,p)['utility']==pytest.approx(measure(new,p)['utility'])
    assert new.value(p.root,p.m)==pytest.approx(measure(new,p)['utility'])


@pytest.mark.parametrize('bound',[False,True])
def test_pricing_matches_exhaustive_action_and_label_enumeration(bound):
    c=small()
    models=[LazyPosterior(c,world_law(c,f)) for f in (1.,1.8)]
    multipliers=[.5,2.]
    oracle=PricingPolicy(models,2,multipliers,bound=bound)
    def brute(h):
        rows=[p.stats[h] for p in models]
        best=-float('inf')
        for labels in product((-1,0,1),repeat=4):
            value=0.
            for k,label in enumerate(labels):
                weight=c['criterion_weight']/2 if k<2 else .5
                prob=rows[0][1][k]
                reward=-c['abstention'] if label<0 else prob-(1-prob)*c['false_positive'] if label else 1-prob-prob*c['false_negative']
                value+=rows[0][0]*weight*reward
                if k>=2 and label>=0:
                    value-=sum(lam*r[0]*((1-r[1][k]) if label else r[1][k])*.5 for lam,r in zip(multipliers,rows))
            best=max(best,value)
        for a in models[0].available(h,2):
            value=-c['cost_penalty']*rows[0][0]+sum(brute(ch) for _,ch in models[0].children(h,a))
            best=max(best,value)
        return best
    expected=brute(models[0].root)
    assert oracle.value(oracle.p.root,oracle.p.m)==pytest.approx(expected)
    column=policy_column(oracle,models)
    assert column['utility']-sum(lam*r for lam,r in zip(multipliers,column['risks']))==pytest.approx(expected)


def test_master_randomization_and_dual():
    columns=[dict(utility=0.,risks=(0.,0.)),dict(utility=1.,risks=(.2,.1)),dict(utility=.8,risks=(.05,.2))]
    solution=master(columns,.1)
    assert solution['primal']==pytest.approx(4.6/7)
    assert solution['weights']==pytest.approx([2/7,3/7,2/7])
    assert solution['primal']==pytest.approx(solution['dual'])
    assert all(x>=0 for x in solution['multipliers'])


def test_constrained_certificate_and_feasibility():
    c=small()
    models=[LazyPosterior(c,world_law(c,f)) for f in (1.,.65,1.8)]
    result=constrained(models,2,.08)
    assert result['gap']<1e-8
    assert result['solution']['primal']<=result['upper']+1e-8
    for s in range(3):
        assert sum(w*col['risks'][s] for w,col in zip(result['solution']['weights'],result['columns']))<=.08+1e-8


def test_zero_budget_and_zero_risk_always_feasible():
    c=small()
    p=LazyPosterior(c,world_law(c))
    result=constrained([p],0,0.)
    assert result['gap']<1e-8
    assert sum(w*col['risks'][0] for w,col in zip(result['solution']['weights'],result['columns']))<1e-9
    assert measure(AbstainPolicy(p,0),p)['cost']==0
