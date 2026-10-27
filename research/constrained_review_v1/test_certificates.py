import random
from itertools import combinations

import pytest

from research.constrained_review_v1.solver import master


def solve_linear(matrix,rhs):
    augmented=[list(row)+[value] for row,value in zip(matrix,rhs)]
    n=len(rhs)
    for j in range(n):
        pivot=max(range(j,n),key=lambda i:abs(augmented[i][j]))
        if abs(augmented[pivot][j])<1e-12:
            return None
        augmented[j],augmented[pivot]=augmented[pivot],augmented[j]
        factor=augmented[j][j]
        augmented[j]=[v/factor for v in augmented[j]]
        for i in range(n):
            if i!=j:
                factor=augmented[i][j]
                augmented[i]=[v-factor*u for v,u in zip(augmented[i],augmented[j])]
    return [row[-1] for row in augmented]


def test_master_against_independent_vertex_enumeration():
    rng=random.Random(38241)
    for _ in range(30):
        columns=[dict(utility=-.3,risks=(0.,0.))]+[dict(utility=rng.uniform(-.2,1.),risks=(rng.random()*.4,rng.random()*.4)) for _ in range(5)]
        best=-float('inf')
        for size in (1,2,3):
            for support in combinations(range(len(columns)),size):
                for active in combinations(range(2),size-1):
                    matrix=[[1.]*size]+[[columns[j]['risks'][s] for j in support] for s in active]
                    weights=solve_linear(matrix,[1.]+[.08]*(size-1))
                    if weights is None or min(weights)<-1e-9:
                        continue
                    if any(sum(w*columns[j]['risks'][s] for w,j in zip(weights,support))>.08+1e-9 for s in range(2)):
                        continue
                    best=max(best,sum(w*columns[j]['utility'] for w,j in zip(weights,support)))
        assert master(columns,.08)['primal']==pytest.approx(best,abs=1e-8)
