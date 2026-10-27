import pytest

from research.compiled_review_v1.belief import CompiledPosterior, Diagram, Unsupported
from research.compiled_review_v1.test_belief import example


def test_copy_agreement_does_not_multiply_independent_evidence():
    c=example()
    c.update(n=1,priors=[.5],facts=[0,0],costs=[1,1],errors=[.2,.2],graph=[['AND',0]],
        groups=[0,0],group_rhos={'0':1.},rho=1.,truth_rho=0.,erasures=[0.,0.])
    correlated=CompiledPosterior(c)
    independent=CompiledPosterior(dict(c,rho=0.,group_rhos={'0':0.}))
    assert correlated.stats[(1,1)][1][0]==pytest.approx(.8)
    assert correlated.stats[(1,-1)][1][0]==pytest.approx(.8)
    assert independent.stats[(1,1)][1][0]==pytest.approx(.64/.68)
    with pytest.raises(KeyError):
        correlated.stats[(1,0)]


def test_unavailable_report_is_not_a_negative_observation():
    c=example(3)
    p=CompiledPosterior(c)
    h=(2,-1,-1,-1)
    assert p.stats[h][0]==pytest.approx(.12)
    assert p.stats[h][1]==pytest.approx(p.stats[p.root][1])


def test_diagram_cap_is_explicit():
    graph=[['AND',*[['OR',['AND',i,i+5],['AND',['NOT',i],['NOT',i+5]]] for i in range(5)]]]
    with pytest.raises(Unsupported,match='diagram_node_cap'):
        Diagram(graph,10,'numeric',cap=30)
