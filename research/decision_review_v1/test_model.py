import itertools
import math

import pytest

from research.decision_review_v1.model import Posterior, Policy, boolean, evaluate, generate, mixture_bits, world_law


def test_mixture_marginals_and_dependency():
    for rho in (0.,.4,1.):
        law = mixture_bits([.1,.3,.7],rho)
        assert sum(law.values()) == pytest.approx(1.)
        for k,p in enumerate((.1,.3,.7)):
            assert sum(q for bits,q in law.items() if bits[k]) == pytest.approx(p)
    assert mixture_bits([.2,.2],1.)[(1,1)] == pytest.approx(.2)


def test_posterior_matches_direct_enumeration():
    c = generate('final',10001,'shared')
    law = world_law(c)
    p = Posterior(c,law)
    for h in (p.root,(0,)+p.root[1:],(1,0)+p.root[2:]):
        matching = [(q,t,y) for q,t,y in law if all(b < 0 or y[a]==b for a,b in enumerate(h))]
        mass = sum(q for q,_,_ in matching)
        assert p.stats[h][0] == pytest.approx(mass)
        for k in range(c['n']):
            assert p.stats[h][1][k] == pytest.approx(sum(q*t[k] for q,t,_ in matching)/mass)
        for a in p.available(h,100):
            assert sum(q for q,_ in p.children(h,a)) == pytest.approx(1.)


@pytest.mark.parametrize('family',['shared','stale','asymmetric'])
def test_oracle_forecast_conservation_budget_and_gap(family):
    c = generate('development',1,family)
    p = Posterior(c,world_law(c))
    rows = {}
    for method in ('exact_dp','lookahead1','lookahead2','voi','fixed','replan','ec2','eig'):
        policy = Policy(p,3,method)
        row,histories = evaluate(policy,p)
        rows[method] = row
        assert sum(histories.values()) == pytest.approx(1.)
        for prefix,n in [('criterion',c['n']),('protocol',len(c['graph']))]:
            assert sum(row[prefix+'_'+suffix] for suffix in ('correct','incorrect','abstention')) == pytest.approx(n)
        assert row['cost'] <= 3+1e-9
        assert row['forecast_bias'] == pytest.approx(0,abs=1e-9)
    assert all(rows['exact_dp']['utility'] >= r['utility']-1e-9 for r in rows.values())


def test_exhaustive_two_action_policy_reference():
    c = generate('development',2,'shared')
    c.update(facts=[0,1],costs=[1,1],errors=[.08,.19])
    p = Posterior(c,world_law(c))
    def brute(h):
        candidates = [p.decisions(h)[1]]
        for a in p.available(h,2):
            candidates.append(c['cost_penalty']+sum(q*brute(ch) for q,ch in p.children(h,a)))
        return min(candidates)
    policy = Policy(p,2,'exact_dp')
    assert policy.solve(p.root,p.m) == pytest.approx(brute(p.root))


def test_robust_envelope_bounds_each_fixed_model():
    c = generate('development',1,'shared')
    p = Posterior(c,world_law(c))
    alternatives = tuple(Posterior(c,world_law(c,f)) for f in (.65,1.8))
    policy = Policy(p,3,'robust_dp',alternatives)
    bound = -policy.solve(p.root,p.m)
    for actual in (p,*alternatives):
        row,_ = evaluate(policy,actual)
        assert row['utility'] >= bound-1e-9


def test_complementarity_counterexample():
    c = generate('development',0,'shared')
    c.update(n=2,facts=[0,1],costs=[1,1],errors=[.005,.005],truth_rho=0.,rho=0.,
             priors=[.5,.5],graph=[['OR',['AND',0,['NOT',1]],['AND',['NOT',0],1]]],criterion_weight=0.)
    p = Posterior(c,[(.25,t,t) for t in itertools.product((0,1),repeat=2)])
    voi = Policy(p,2,'voi')
    look = Policy(p,2,'lookahead2')
    assert voi.choose(p.root) is None
    assert look.choose(p.root) is not None
    assert evaluate(look,p)[0]['utility'] > evaluate(voi,p)[0]['utility']
    assert boolean(c['graph'][0],(1,0))
    assert not boolean(c['graph'][0],(1,1))


def test_seed_and_family_separation():
    c = generate('final',10000,'shared')
    assert c == generate('final',10000,'shared')
    assert c['graph'] != generate('development',0,'shared')['graph']
    assert math.isclose(sum(q for q,_,_ in world_law(c)),1.)


def test_risk_proxy_uses_assumed_law_not_authored_error_field():
    c = generate('final',10000,'miscalibrated')
    law = world_law(c,c['factor'])
    p = Posterior(c,law)
    changed = dict(c,errors=[.49]*len(c['facts']))
    q = Posterior(changed,law)
    assert p.report_errors == q.report_errors
    assert Policy(p,4,'risk_proxy').choose(p.root) == Policy(q,4,'risk_proxy').choose(q.root)


def test_ec2_edge_formula_matches_explicit_pairs():
    c = generate('development',1,'shared')
    p = Posterior(c,world_law(c))
    a = 0
    classes = [tuple(boolean(g,t) for g in c['graph']) for _,t,_ in p.law]
    edge = sum(q*r for i,(q,_,y) in enumerate(p.law) for j,(r,_,z) in enumerate(p.law) if classes[i]!=classes[j])
    remaining = 0.
    for bit in (0,1):
        py = sum(q for q,_,y in p.law if y[a]==bit)
        remaining += py*sum(q*r for i,(q,_,y) in enumerate(p.law) for j,(r,_,z) in enumerate(p.law) if y[a]==z[a]==bit and classes[i]!=classes[j])
    fast = p.stats[p.root][3]-sum(q**3*p.stats[h][3] for q,h in p.children(p.root,a))
    assert fast == pytest.approx(edge-remaining)
