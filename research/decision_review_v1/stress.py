import argparse
import json
import random
from pathlib import Path

from research.decision_review_v1.model import Posterior, Policy, evaluate, generate, world_law
from research.decision_review_v1.run import ROOT, table, write_json


def tree(leaves,rng):
    if len(leaves)==1:
        return ['NOT',leaves[0]] if rng.random()<.3 else leaves[0]
    cut=rng.randrange(1,len(leaves))
    return [rng.choice(['AND','OR']),tree(leaves[:cut],rng),tree(leaves[cut:],rng)]


def run(output):
    cases=[]
    for seed in range(30000,30024):
        rng=random.Random(f'structural-stress-v1:{seed}')
        family=('shared','miscalibrated','stale','asymmetric')[seed%4]
        c=generate('final',seed,family)
        n=rng.choice((3,4,5))
        graph=[]
        for _ in range(rng.choice((2,3,4))):
            leaves=rng.sample(list(range(n)),rng.randrange(2,n+1))
            graph.append(tree(leaves,rng))
        c.update(id=f'stress-{seed}',n=n,graph=graph,priors=[rng.uniform(.1,.9) for _ in range(n)],
                 facts=list(range(n))+[rng.randrange(n) for _ in range(2)],costs=[rng.choice((1,2,3)) for _ in range(n+2)],
                 errors=[rng.uniform(.05,.45 if family=='stale' else .25) for _ in range(n+2)])
        cases.append(c)
    write_json(output/'structural_stress_protocol.json',dict(status='exploratory independent post-primary stress test, no tuning',seed_namespace='structural-stress-v1',seeds=[c['seed'] for c in cases],budgets=[2,4],methods=['voi','eig','ec2','lookahead2','exact_dp','replan']))
    write_json(output/'structural_stress_cases.json',cases)
    rows=[]
    for c in cases:
        actual=Posterior(c,world_law(c))
        nominal=actual if c['factor']==1 else Posterior(c,world_law(c,c['factor']))
        for budget in (2,4):
            for method in ('voi','eig','ec2','lookahead2','exact_dp','replan'):
                metrics,_=evaluate(Policy(nominal,budget,method),actual)
                rows.append(dict(case=c['id'],family=c['family'],seed=c['seed'],budget=budget,method=method,n=c['n'],protocols=len(c['graph']),**metrics))
    table(output/'structural_stress.csv',rows)
    print('Structural stress saved')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('output',type=Path)
    run(ROOT/parser.parse_args().output)
