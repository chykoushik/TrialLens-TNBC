import itertools

import pytest

from research.compiled_review_v1.belief import CompiledPosterior, Diagram, ExplicitPosterior, TruthPosterior
from research.synthetic import scenario
from research.constrained_review_v1.factorized import ClosedFormPosterior, solve_fast


def example(outcomes=2):
    c=scenario('development',100001,'correlated')
    c.update(n=3,priors=[.3,.5,.7],facts=[0,1,0,2],costs=[1]*4,errors=[.1,.2,.3,.15],
        graph=[['OR',0,['AND',['NOT',0],1]],['AND',1,['NOT',2]]],
        groups=[0,0,1,1],group_rhos={'0':.7,'1':.4},outcomes=outcomes,
        erasures=[.12]*4 if outcomes==3 else [0.]*4)
    return c


@pytest.mark.parametrize('outcomes',[2,3])
def test_all_histories_against_two_independent_references(outcomes):
    c=example(outcomes)
    truth=TruthPosterior(c,1.8)
    explicit=ExplicitPosterior(c,1.8)
    compiled=CompiledPosterior(c,1.8)
    for h in itertools.product(range(-1,outcomes),repeat=4):
        a,b,d=truth.stats[h],explicit.stats[h],compiled.stats[h]
        assert d[0]==pytest.approx(a[0],abs=1e-12)
        assert d[0]==pytest.approx(b[0],abs=1e-12)
        assert d[1]==pytest.approx(a[1],abs=1e-10)
        assert d[1]==pytest.approx(b[1],abs=1e-10)
        assert d[2:]==pytest.approx(a[2:],abs=1e-10)
    assert sum(q for q,_ in compiled.children(compiled.root,0))==pytest.approx(1.)


def test_previous_binary_backend_equivalence():
    c=example()
    c['groups']=[0]*4
    c['group_rhos']={'0':c['rho']}
    old=ClosedFormPosterior(c)
    new=CompiledPosterior(c)
    for h in itertools.product((-1,0,1),repeat=4):
        assert new.stats[h][1]==pytest.approx(old.stats[h][1],abs=1e-10)


def test_risk_optimum_is_backend_invariant():
    c=example(3)
    results=[]
    for cls in (TruthPosterior,CompiledPosterior):
        result=solve_fast([cls(c,f) for f in (1.,.65,1.8)],3,.08)
        assert result['gap']<1e-8
        results.append(result['solution']['primal'])
    assert results[0]==pytest.approx(results[1],abs=1e-8)


def test_repeated_leaves_are_not_independent_operands():
    diagram=Diagram([['OR',0,['NOT',0]],['AND',0,0]],1)
    distribution=diagram.distribution([.3])
    assert distribution==pytest.approx({(1,0):.7,(1,1):.3})


def test_ordering_affects_size_not_function():
    graphs=[['AND',*[['OR',['AND',i,i+6],['AND',['NOT',i],['NOT',i+6]]] for i in range(6)]]]
    numeric=Diagram(graphs,12,'numeric')
    occurrence=Diagram(graphs,12,'occurrence')
    assert len(numeric.nodes)>len(occurrence.nodes)
    assert numeric.distribution([.5]*12)==pytest.approx(occurrence.distribution([.5]*12))
