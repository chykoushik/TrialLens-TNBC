import argparse
import json
import random
import time
from pathlib import Path

from research.compiled_review_v1.belief import CompiledPosterior, Diagram
from research.compiled_review_v1.bench import case, execute, peak_rss
from research.constrained_review_v1.factorized import column_tree, measure_tree, solve_fast
from research.constrained_review_v1.solver import AbstainPolicy, ExistingPolicy, PricingPolicy, master
from research.decision_review_v1.model import Policy
from research.decision_review_v1.run import ROOT, table, write_json

METHODS=('voi','eig','ec2','lookahead1','lookahead2','exact_dp','fixed','replan','robust_dp')


def library(models,budget):
    columns=[column_tree(AbstainPolicy(models[0],budget),models)]
    names=['abstain']
    for method in METHODS:
        p=ExistingPolicy(Policy(models[0],budget,method,tuple(models[1:]) if method=='robust_dp' else ()))
        columns.append(column_tree(p,models))
        names.append(method)
    for price in (.5,2.,8.,32.):
        columns.append(column_tree(PricingPolicy(models,budget,[price/len(models)]*len(models)),models))
        names.append('penalty_'+str(price))
    return columns,names


def approximate(models,budget,columns):
    columns=list(columns)
    for _ in range(30):
        solution=master(columns,.08)
        col=column_tree(PricingPolicy(models,budget,solution['multipliers'],depth=2),models)
        if any(abs(c['utility']-col['utility'])<1e-10 and max(abs(a-b) for a,b in zip(c['risks'],col['risks']))<1e-10 for c in columns):
            break
        columns.append(col)
    return dict(columns=columns,solution=master(columns,.08),gap=None,trace=[])


def score(columns,weights,models,actual):
    scored=[(weight,measure_tree(col['policy'],actual)) for col,weight in zip(columns,weights) if weight>1e-12]
    numeric=[k for k in scored[0][1] if k not in ('selective_error','terminals')]
    result={k:sum(w*row[k] for w,row in scored) for k in numeric}
    result['max_model_risk']=max(sum(w*measure_tree(col['policy'],model)['risk'] for col,w in zip(columns,weights) if w>1e-12) for model in models)
    result['actual_violation']=max(0.,result['risk']-.08)
    result['model_violation']=max(0.,result['max_model_risk']-.08)
    result['support']=sum(w>1e-9 for w in weights)
    asserted=result['protocol_correct']+result['protocol_incorrect']
    result['selective_error']=result['protocol_incorrect']/asserted if asserted>1e-12 else None
    return result


def worker(job):
    c=job['case']
    d=Diagram(c['graph'],c['n'])
    models=[CompiledPosterior(c,f,diagram=d) for f in (1.,.65,1.8)]
    actual_case=dict(c)
    if job['split']=='ood':
        actual_case.update(rho=.95)
    actual=CompiledPosterior(actual_case,3. if job['split']=='ood' else c['actual_factor'],diagram=d)
    rows,traces=[],[]
    started=time.perf_counter()
    for budget in job['budgets']:
        columns,names=library(models,budget)
        def add(name,cols,weights,**extras):
            rows.append(dict(case=c['id'],seed=job['seed'],split=job['split'],family=job['family'],n=c['n'],m=len(c['facts']),
                groups=len(set(c['groups'])),outcomes=c['outcomes'],protocols=len(c['graph']),budget=budget,method=name,
                **score(cols,weights,models,actual),**extras))
        for j,name in enumerate(names):
            if j==0:
                continue
            weights=[float(i==j) for i in range(len(columns))]
            add('raw_'+name,columns,weights)
            pair=[columns[0],columns[j]]
            safe=master(pair,.08)
            add('safe_'+name,pair,safe['weights'],nominal_utility=safe['primal'])
        hull=master(columns,.08)
        add('library_hull',columns,hull['weights'],nominal_utility=hull['primal'])
        for method,source_cols,source_models,depth in [
            ('multi_cg',columns,models,False),('depth2_cg',columns,models,True),
            ('nominal_cg',[dict(col,risks=col['risks'][:1],rows=col['rows'][:1]) for col in columns],models[:1],False)]:
            result=approximate(source_models,budget,source_cols) if depth else solve_fast(source_models,budget,.08,source_cols)
            add(method,result['columns'],result['solution']['weights'],gap=result['gap'],nominal_utility=result['solution']['primal'])
            traces.append(dict(budget=budget,method=method,trace=result['trace']))
        independent=dict(c,rho=0.)
        assumed=[CompiledPosterior(independent,f,diagram=d) for f in (1.,.65,1.8)]
        indep_columns,_=library(assumed,budget)
        result=solve_fast(assumed,budget,.08,indep_columns)
        add('report_independent_cg',result['columns'],result['solution']['weights'],gap=result['gap'],nominal_utility=result['solution']['primal'])
        oracle=solve_fast([actual],budget,.08)
        for row in rows:
            if row['budget']==budget:
                row['actual_oracle_utility']=oracle['solution']['primal']
                row['actual_oracle_gap']=oracle['gap']
                row['feasible_regret']=oracle['solution']['primal']-row['utility'] if row['risk']<=.08+1e-8 else None
    write_json(Path(job['result']),dict(status='ok',rows=rows,traces=traces,total_seconds=time.perf_counter()-started,
        peak_rss_mib=peak_rss(),bdd_nodes=len(d.nodes),joint_diagram_states=len(d.joint)))


def run(output):
    frozen=json.loads((output/'freeze.json').read_text())
    specifications=[]
    for split,seeds in [('final',frozen['final_seeds']),('ood',frozen['ood_seeds'])]:
        for seed in seeds:
            for family in frozen['families']:
                rng=random.Random(f'decision-spec:{split}:{seed}:{family}')
                n=rng.choice((4,8,12))
                m=rng.choice((6,8))
                g=1 if family in ('shared','conflict') else 3
                outcomes=rng.choice((2,3))
                c=case(seed,n,m,g,outcomes,family)
                specifications.append(dict(case=c,seed=seed,split=split,family=family))
    write_json(output/'decision_cases.json',specifications)
    rows,statuses,traces=[],[],[]
    for i,spec in enumerate(specifications):
        name=f'decision-{spec["split"]}-{spec["seed"]}-{spec["family"]}'
        job=dict(**spec,task='decision',budgets=frozen['budgets'],result=str(output/'jobs'/(name+'.result.json')))
        result=execute(job,output/'jobs'/(name+'.job.json'),frozen['decision_timeout'])
        rows.extend(result.get('rows',[]))
        traces.append(dict(case=spec['case']['id'],traces=result.get('traces',[])))
        statuses.append(dict(case=spec['case']['id'],split=spec['split'],status=result['status'],
            reason=result.get('reason'),seconds=result.get('total_seconds'),peak_rss_mib=result.get('peak_rss_mib')))
        table(output/'decision.csv',rows)
        table(output/'decision_status.csv',statuses)
        if i%6==5:
            print(f'Evaluated {i+1} cases',flush=True)
    write_json(output/'decision_traces.json',traces)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('output',type=Path)
    run(ROOT/parser.parse_args().output)
