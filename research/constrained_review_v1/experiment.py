import argparse
import hashlib
import json
import random
import time
from pathlib import Path

from research.decision_review_v1.model import Policy, Posterior, generate, world_law
from research.decision_review_v1.run import ROOT, inventory, table, write_json
from research.decision_review_v1.stress import tree
from research.constrained_review_v1.solver import (
    AbstainPolicy, ExistingPolicy, LazyPosterior, PricingPolicy, constrained,
    master, measure, mixture_metrics, policy_column,
)

FAMILIES=('independent','correlated','conflicting','stale','overconfident','asymmetric')
FACTORS=(1.,.65,1.8)
BASELINES=('voi','eig','ec2','lookahead1','lookahead2','exact_dp','fixed','replan','robust_dp')


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


def library(models,budget):
    columns=[policy_column(AbstainPolicy(models[0],budget),models)]
    names=['abstain_protocols']
    for method in BASELINES:
        wrapped=ExistingPolicy(Policy(models[0],budget,method,tuple(models[1:]) if method=='robust_dp' else ()))
        columns.append(policy_column(wrapped,models))
        names.append(method)
    for price in (.5,2.,8.,32.):
        wrapped=PricingPolicy(models,budget,[price/len(models)]*len(models))
        columns.append(policy_column(wrapped,models))
        names.append(f'penalty_grid_{price}')
    return columns,names


def safe_pair(columns,index,epsilon):
    return master([columns[0],columns[index]],epsilon)


def run_development(output):
    if (output/'development.csv').exists():
        raise ValueError('Development already saved')
    output.mkdir(parents=True,exist_ok=True)
    if not (output/'preservation_before.json').exists():
        write_json(output/'preservation_before.json',preservation())
    cases=[scenario('development',50000+s,f) for s in range(2) for f in FAMILIES]
    write_json(output/'development_cases.json',cases)
    rows,traces=[],[]
    for i,c in enumerate(cases):
        models,actual=posteriors(c)
        for budget in (2,4):
            columns,names=library(models,budget)
            base=master(columns,.08)
            row=mixture_metrics(columns,base['weights'],actual)
            rows.append(dict(case=c['id'],seed=c['seed'],family=c['family'],budget=budget,version='library_v0',nominal_utility=base['primal'],gap=None,seconds=0.,**row))
            for version,settings in [('depth2_v0',dict(depth=2)),('exact_v1',{}),('bounded_v2',dict(bound=True))]:
                start=time.perf_counter()
                result=constrained(models,budget,.08,columns,**settings)
                row=mixture_metrics(result['columns'],result['solution']['weights'],actual)
                rows.append(dict(case=c['id'],seed=c['seed'],family=c['family'],budget=budget,version=version,
                    nominal_utility=result['solution']['primal'],gap=result['gap'],seconds=time.perf_counter()-start,**row))
                traces.append(dict(case=c['id'],budget=budget,version=version,trace=result['trace']))
        if i%3==2:
            print(f'Developed {i+1} cases',flush=True)
    table(output/'development.csv',rows)
    write_json(output/'development_traces.json',traces)


def preservation():
    files=inventory()
    for folder in ('research/decision_review_v1','results/recomb/20261026-decision-review-v1','results/recomb/20261026-decision-review-v2'):
        for p in (ROOT/folder).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts:
                files[p.relative_to(ROOT).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
    return files


def refine(output):
    cases=[scenario('final',51000+s,f) for s in range(2) for f in FAMILIES]
    for c in cases:
        c['split']='development_refinement'
        c['id']=c['id'].replace('final','development_refinement')
    write_json(output/'refinement_cases.json',cases)
    rows=[]
    for c in cases:
        models,actual=posteriors(c)
        for budget in (3,5):
            columns,_=library(models,budget)
            for version,settings in [('depth2_v0',dict(depth=2)),('exact_v1',{}),('bounded_v2',dict(bound=True))]:
                start=time.perf_counter()
                result=constrained(models,budget,.08,columns,**settings)
                row=mixture_metrics(result['columns'],result['solution']['weights'],actual)
                rows.append(dict(case=c['id'],budget=budget,version=version,nominal_utility=result['solution']['primal'],
                    gap=result['gap'],iterations=len(result['trace']),states=sum(x['states'] for x in result['trace']),
                    pruned=sum(x['pruned'] for x in result['trace']),seconds=time.perf_counter()-start,**row))
    table(output/'development_refinement.csv',rows)
    efficiency=[]
    for n in range(2,7):
        c=scenario('development',52000+n,'correlated')
        c.update(n=n,facts=list(range(n))+[0,n-1],costs=[1]*(n+2),errors=[.15]*(n+2),priors=[.3+.3*(k%2) for k in range(n)],
                 graph=[['AND',*range(n)],['OR',*range(n)]])
        law=world_law(c)
        for budget in (1,3):
            for implementation in ('dense_old','lazy_old','lazy_pricing'):
                for repeat in range(3):
                    start=time.perf_counter()
                    p=(Posterior if implementation=='dense_old' else LazyPosterior)(c,law)
                    construction=time.perf_counter()-start
                    start=time.perf_counter()
                    if implementation=='lazy_pricing':
                        policy=PricingPolicy([p],budget,[0.])
                        value=policy.value(p.root,p.m)
                        states=policy.states
                    else:
                        old=Policy(p,budget,'exact_dp')
                        value=-old.solve(p.root,p.m)
                        states=old.solve.cache_info().currsize
                    efficiency.append(dict(n=n,m=n+2,budget=budget,implementation=implementation,repeat=repeat,
                        construction_seconds=construction,planning_seconds=time.perf_counter()-start,value=value,
                        states=states,posterior_histories=len(p.stats)))
    table(output/'efficiency_development.csv',efficiency)
    print('Refinement saved')


def freeze(output):
    if (output/'freeze.json').exists():
        raise ValueError('Freeze already exists')
    protocol=dict(version='constrained-review-v1',development_models=24,
        decision='Choose exact lazy pricing without revelation pruning: pruning slower in both development rounds; depth2 loses value and has no certificate.',
        final_seeds=list(range(60000,60012)),ood_seeds=list(range(70000,70004)),families=FAMILIES,
        budgets=[3,5],epsilon=.08,reliability_factors=FACTORS,max_iterations=30,tolerance=1e-8,
        primary='multi_cg minus library_hull actual utility; average budgets and six families within each seed bundle',
        secondary=['multi_cg minus safe_exact_dp','multi_cg minus safe_robust_dp','multi_cg minus depth2_cg','multi_cg minus nominal_cg'],
        bootstrap=5000,ood='separate descriptive panel, same frozen algorithms; actual reliability factor3 and rho .95 outside assumed finite set',
        risk='expected incorrect protocol fraction, not conditional error among assertions or per-path safety',
        clinical_subjects=0,paid_requests=0)
    source={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')}
    write_json(output/'freeze.json',dict(protocol=protocol,algorithm_sources=source))
    print('Methods frozen')


def finish_row(c,budget,name,columns,weights,models,actual,epsilon,**extra):
    row=mixture_metrics(columns,weights,actual)
    risks=[sum(w*measure(col['policy'],model)['risk'] for w,col in zip(weights,columns) if w>1e-12) for model in models]
    return dict(case=c['id'],split=c['split'],seed=c['seed'],family=c['family'],budget=budget,method=name,
        n=c['n'],protocols=len(c['graph']),epsilon=epsilon,actual_in_modelset=c['split']!='ood',
        max_model_risk=max(risks),model_violation=max(0.,max(risks)-epsilon),
        actual_violation=max(0.,row['risk']-epsilon),**row,**extra)


def serialize_solution(columns,weights):
    result=[]
    for column,weight in zip(columns,weights):
        if weight<1e-9:
            continue
        policy=column['policy']
        nodes={}
        def visit(h):
            if h in nodes:
                return
            if isinstance(policy,AbstainPolicy):
                action=None
            elif isinstance(policy,ExistingPolicy):
                action=policy.policy.choose(h)
            else:
                action=policy.choose(h)
            nodes[h]=dict(history=h,next_review=action,labels=policy.decode(h) if action is None else None)
            if action is not None:
                for _,child in policy.p.children(h,action):
                    visit(child)
        visit(policy.p.root)
        result.append(dict(weight=weight,nominal_utility=column['utility'],model_risks=column['risks'],nodes=list(nodes.values())))
    return result


def evaluate_frozen(output):
    freeze_data=json.loads((output/'freeze.json').read_text())
    for name,digest in freeze_data['algorithm_sources'].items():
        assert hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()==digest
    protocol=freeze_data['protocol']
    if (output/'final.csv').exists():
        raise ValueError('Final already exists')
    cases=[scenario(split,s,f) for split,seeds in [('final',protocol['final_seeds']),('ood',protocol['ood_seeds'])] for s in seeds for f in FAMILIES]
    write_json(output/'evaluation_cases.json',cases)
    rows,traces=[],[]
    with (output/'policies.jsonl').open('w',encoding='utf-8') as policy_file:
        for i,c in enumerate(cases):
            models,actual=posteriors(c)
            for budget in protocol['budgets']:
                columns,names=library(models,budget)
                for j,name in enumerate(names):
                    raw=[float(k==j) for k in range(len(columns))]
                    rows.append(finish_row(c,budget,'raw_'+name,columns,raw,models,actual,.08))
                    if j:
                        pair=[columns[0],columns[j]]
                        safe=master(pair,.08)
                        rows.append(finish_row(c,budget,'safe_'+name,pair,safe['weights'],models,actual,.08,nominal_utility=safe['primal']))
                hull=master(columns,.08)
                rows.append(finish_row(c,budget,'library_hull',columns,hull['weights'],models,actual,.08,nominal_utility=hull['primal']))
                for method,pricing_models,pricing_columns,settings in [
                    ('multi_cg',models,columns,{}),
                    ('depth2_cg',models,columns,dict(depth=2)),
                    ('nominal_cg',models[:1],[dict(col,risks=col['risks'][:1],rows=col['rows'][:1]) for col in columns],{})]:
                    start=time.perf_counter()
                    result=constrained(pricing_models,budget,.08,pricing_columns,**settings)
                    row=finish_row(c,budget,method,result['columns'],result['solution']['weights'],models,actual,.08,
                        nominal_utility=result['solution']['primal'],certificate_gap=result['gap'],upper=result['upper'],
                        iterations=len(result['trace']),solver_seconds=time.perf_counter()-start)
                    rows.append(row)
                    traces.append(dict(case=c['id'],budget=budget,method=method,trace=result['trace']))
                    if method=='multi_cg':
                        policy_file.write(json.dumps(dict(case=c['id'],budget=budget,method=method,
                            policy=serialize_solution(result['columns'],result['solution']['weights'])))+'\n')
            if i%6==5:
                print(f'Evaluated {i+1} cases',flush=True)
                table(output/'evaluation_checkpoint.csv',rows)
    table(output/'final.csv',rows)
    write_json(output/'solver_traces.json',traces)
    changes=[p for p,h in json.loads((output/'preservation_before.json').read_text()).items() if preservation().get(p)!=h]
    write_json(output/'preservation_check.json',dict(changes=changes))
    assert not changes
    print('Evaluation saved')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('stage',choices=['development','refine','freeze','evaluate'])
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    {'development':run_development,'refine':refine,'freeze':freeze,'evaluate':evaluate_frozen}[args.stage](ROOT/args.output)
