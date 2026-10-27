import random

from research.decision_review_v1.model import Posterior, generate, world_law
from research.constrained_review_v1.solver import LazyPosterior

FACTORS = (1., .65, 1.8)


def tree(leaves,rng):
    if len(leaves)==1:
        return ['NOT',leaves[0]] if rng.random()<.3 else leaves[0]
    cut=rng.randrange(1,len(leaves))
    return [rng.choice(['AND','OR']),tree(leaves[:cut],rng),tree(leaves[cut:],rng)]


def scenario(split,seed,family):
    rng=random.Random(f'constrained-review-v1:{split}:{seed}:{family}')
    c=generate('development',seed,'shared')
    n=rng.choice((2,3)) if split=='development' else rng.choice((3,4)) if split=='final' else rng.choice((4,5))
    m=n+2
    graphs=[]
    for _ in range(rng.choice((2,3))):
        leaves=rng.sample(list(range(n)),rng.randrange(2,n+1))
        graphs.append(tree(leaves,rng))
    errors=[rng.uniform(.05,.2) for _ in range(m)]
    ages=[rng.choice((0,7,30,90)) if family=='stale' else 0 for _ in range(m)]
    if family=='stale':
        import math
        errors=[.5-(.5-q)*math.exp(-age/45) for q,age in zip(errors,ages)]
    facts=list(range(n))+[rng.randrange(n),rng.randrange(n)]
    costs=[rng.choice((1,1,2,3)) for _ in range(m)]
    if family=='conflicting':
        facts[-2:]=[0,0]
        errors[-2:]=[.32,.07]
        costs[-2:]=[1,2]
    c.update(id=f'{split}-{family}-{seed}',split=split,family=family,seed=seed,n=n,graph=graphs,
             facts=facts,costs=costs,errors=errors,ages=ages,priors=[rng.uniform(.15,.85) for _ in range(n)],
             rho=0. if family=='independent' else rng.uniform(.4,.8),
             truth_rho=0. if family=='independent' else rng.uniform(.15,.6),factor=1.,
             false_positive=8. if family=='asymmetric' else 3.,false_negative=2. if family=='asymmetric' else 3.,
             actual_factor=1.8 if family in ('overconfident','stale') else rng.choice(FACTORS))
    if split=='ood':
        c['actual_factor']=3.
        c['actual_rho']=.95
    return c


def posteriors(c,dense=False):
    cls=Posterior if dense else LazyPosterior
    models=[cls(c,world_law(c,f)) for f in FACTORS]
    actual_case=dict(c,rho=c.get('actual_rho',c['rho']))
    actual=cls(c,world_law(actual_case,c['actual_factor']))
    return models,actual


def case(seed,n,m,groups=1,outcomes=2,family='shared'):
    rng=random.Random(f'compiled-review-v1:{seed}:{n}:{m}:{groups}:{outcomes}:{family}')
    c=scenario('final',seed,'correlated')
    facts=[rng.randrange(n) for _ in range(m)]
    if m>=3:
        facts[:3]=[0,1,0]
    pairs=[['OR',i,min(i+1,n-1)] for i in range(0,n,2)]
    c.update(id=f'{family}-{seed}-n{n}-m{m}-g{groups}-r{outcomes}',n=n,facts=facts,
        costs=[1]*m,errors=[rng.uniform(.06,.23) for _ in range(m)],priors=[rng.uniform(.2,.8) for _ in range(n)],
        graph=[['AND',*pairs],['OR',['AND',0,['NOT',1]],['AND',1,min(2,n-1)]]],
        groups=[a%groups for a in range(m)],outcomes=outcomes,
        erasures=[.15]*m if outcomes==3 else [0.]*m,rho=.7,truth_rho=.3,
        false_positive=8. if family=='asymmetric' else 3.,false_negative=2. if family=='asymmetric' else 3.,
        actual_factor=1.8 if family in ('misspecified','stale') else rng.choice((1.,.65,1.8)))
    if family=='independent':
        c.update(rho=0.,truth_rho=0.)
    if family=='stale':
        c['errors']=[.4 if a%3==0 else q for a,q in enumerate(c['errors'])]
    if family=='conflict':
        c['facts'][-2:]=[0,0]
        c['errors'][-2:]=[.32,.08]
        c['groups'][-2:]=[0,0]
    return c
