import argparse
import ctypes
import hashlib
import json
import os
import platform
import random
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

from research.compiled_review_v1.belief import CompiledPosterior, Diagram, ExplicitPosterior, TruthPosterior, Unsupported
from research.constrained_review_v1.experiment import scenario
from research.constrained_review_v1.factorized import ClosedFormPosterior, solve_fast
from research.decision_review_v1.run import ROOT, table, write_json


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


def peak_rss():
    class Counters(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('faults',wintypes.DWORD)]+[(name,ctypes.c_size_t) for name in
            ('peak','working','quota_peak_paged','quota_paged','quota_peak_nonpaged','quota_nonpaged','pagefile','peak_pagefile')]
    counters=Counters()
    counters.cb=ctypes.sizeof(counters)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetCurrentProcess.restype=wintypes.HANDLE
    psapi=ctypes.WinDLL('psapi',use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype=wintypes.BOOL
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(counters),counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return counters.peak/1024**2


def make_posterior(c,backend,factor=1.,variant='final'):
    if backend=='compiled':
        return CompiledPosterior(c,factor,order='numeric' if variant=='numeric' else 'occurrence',merge=variant!='unmerged')
    if backend=='explicit':
        return ExplicitPosterior(c,factor)
    if backend=='legacy':
        if c['outcomes']!=2 or len(set(c['groups']))!=1:
            raise Unsupported('legacy_binary_single_group_only')
        if c['n']>16:
            raise Unsupported('legacy_truth_assignment_cap')
        return ClosedFormPosterior(c,factor)
    return TruthPosterior(c,factor)


def worker(job_path):
    job=json.loads(Path(job_path).read_text())
    if job['task']=='decision':
        from research.compiled_review_v1.decision import worker as decision_worker
        decision_worker(job)
        return
    c=job['case']
    before=peak_rss()
    started=time.perf_counter()
    try:
        p=make_posterior(c,job['backend'],variant=job.get('variant','final'))
        construction=time.perf_counter()-started
        if job['task']=='queries':
            values=[p.stats[tuple(h)] for h in job['queries']]
            result=dict(values=values)
        else:
            models=[p]+[make_posterior(c,job['backend'],f,job.get('variant','final')) for f in (.65,1.8)]
            solution=solve_fast(models,job['budget'],.08)
            result=dict(utility=solution['solution']['primal'],gap=solution['gap'],iterations=len(solution['trace']),
                        risks=[sum(w*col['risks'][s] for w,col in zip(solution['solution']['weights'],solution['columns'])) for s in range(3)])
        result.update(status='ok',construction_seconds=construction,total_seconds=time.perf_counter()-started,
            peak_rss_mib=peak_rss(),baseline_rss_mib=before,cached_histories=len(p.stats),
            bdd_nodes=len(p.diagram.nodes) if hasattr(p,'diagram') else None,
            joint_diagram_states=len(p.diagram.joint) if hasattr(p,'diagram') else None,
            max_components=getattr(p,'max_components',None))
    except Unsupported as e:
        result=dict(status='unsupported',reason=str(e),total_seconds=time.perf_counter()-started,peak_rss_mib=peak_rss(),baseline_rss_mib=before)
    write_json(Path(job['result']),result)


def execute(job,path,timeout=20):
    write_json(path,job)
    started=time.perf_counter()
    try:
        run=subprocess.run([sys.executable,'-m','research.compiled_review_v1.bench','worker',str(path)],cwd=ROOT,
                           capture_output=True,text=True,timeout=timeout)
        if run.returncode:
            Path(job['result']).with_suffix('.stderr.txt').write_text(run.stderr,encoding='utf-8')
            return dict(status='error',reason='worker_failed',wall_seconds=time.perf_counter()-started)
        return json.loads(Path(job['result']).read_text())
    except subprocess.TimeoutExpired:
        result=dict(status='timeout',reason=f'wall_cap_{timeout}s',wall_seconds=time.perf_counter()-started)
        write_json(Path(job['result']),result)
        return result


def queries(c,budget,seed,count=40):
    rng=random.Random(f'queries-v1:{seed}:{c["id"]}:{budget}')
    values=[[-1]*len(c['facts'])]
    for _ in range(count-1):
        h=[-1]*len(c['facts'])
        for a in rng.sample(range(len(h)),rng.randrange(1,min(budget,len(h))+1)):
            h[a]=rng.randrange(c['outcomes'])
        values.append(h)
    return values


def development(output):
    output.mkdir(parents=True,exist_ok=False)
    jobs=output/'jobs'
    jobs.mkdir()
    rows=[]
    for i,(n,m,g,r) in enumerate(((3,4,1,2),(4,5,2,3),(6,6,1,2),(8,8,3,3),(12,8,2,2),(16,8,1,2))):
        c=case(110000+i,n,m,g,r)
        for backend,variant in [('truth','final'),('compiled','numeric'),('compiled','unmerged'),('compiled','final')]:
            name=f'dev-{i}-{backend}-{variant}'
            job=dict(case=c,backend=backend,variant=variant,task='queries',queries=queries(c,3,i),budget=3,
                     result=str(jobs/(name+'.result.json')))
            result=execute(job,jobs/(name+'.job.json'),15)
            rows.append(dict(case=c['id'],backend=backend,variant=variant,n=n,m=m,**{k:v for k,v in result.items() if k!='values'}))
        table(output/'development.csv',rows)
        print(f'Developed {i+1} cases',flush=True)
    order_rows=[]
    for k in (4,6,8,10,12):
        graph=[['AND',*[['OR',['AND',i,i+k],['AND',['NOT',i],['NOT',i+k]]] for i in range(k)]]]
        for order in ('numeric','occurrence'):
            started=time.perf_counter()
            try:
                d=Diagram(graph,2*k,order)
                row=dict(k=k,order=order,status='ok',nodes=len(d.nodes),joint_states=len(d.joint))
            except Unsupported as e:
                row=dict(k=k,order=order,status='unsupported',reason=str(e))
            row['seconds']=time.perf_counter()-started
            order_rows.append(row)
    table(output/'ordering_counterexample.csv',order_rows)


def freeze(output):
    specifications=[(3,4,1,2,2),(4,6,2,3,3),(6,8,1,2,3),(8,8,3,3,3),
        (12,10,1,2,3),(16,12,3,3,3),(24,12,1,2,3),(32,16,4,2,3),(64,16,4,3,3),
        (8,6,1,2,1),(8,6,3,2,3),(8,6,3,3,5)]
    protocol=dict(source_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')},
        selection='occurrence ordering and exact duplicate component merging; no utility/model changes',
        benchmark_cases=[dict(seed=120000+i,n=n,m=m,groups=g,outcomes=r,budget=b) for i,(n,m,g,r,b) in enumerate(specifications)],
        repeats=3,query_count=40,query_timeout=15,solve_timeout=20,
        solve_indices=[0,1,2,3,4,6,9,10,11],backends=['explicit','truth','legacy','compiled'],
        final_seeds=list(range(130000,130008)),families=['independent','shared','conflict','stale','misspecified','asymmetric'],
        budgets=[1,3],risk=.08,decision_timeout=45,ood_seeds=list(range(140000,140004)),
        scope='Frozen after development; all new experiments synthetic; backend equivalence does not imply a new decision policy.')
    if (output/'freeze.json').exists():
        raise ValueError('Freeze exists')
    write_json(output/'freeze.json',protocol)


def benchmark(output):
    protocol=json.loads((output/'freeze.json').read_text())
    for name,digest in protocol['source_hashes'].items():
        assert hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()==digest
    rows=[]
    for i,spec in enumerate(protocol['benchmark_cases']):
        c=case(spec['seed'],spec['n'],spec['m'],spec['groups'],spec['outcomes'])
        for task in ('queries','solve'):
            if task=='solve' and i not in protocol['solve_indices']:
                continue
            for repeat in range(protocol['repeats']):
                ordering=list(protocol['backends'])
                random.Random(f'benchmark-order:{i}:{task}:{repeat}').shuffle(ordering)
                for backend in ordering:
                    name=f'bench-{i}-{task}-{repeat}-{backend}'
                    job=dict(case=c,backend=backend,task=task,budget=spec['budget'],queries=queries(c,spec['budget'],i,protocol['query_count']),
                        result=str(output/'jobs'/(name+'.result.json')))
                    result=execute(job,output/'jobs'/(name+'.job.json'),protocol['query_timeout'] if task=='queries' else protocol['solve_timeout'])
                    rows.append(dict(index=i,case=c['id'],n=c['n'],m=len(c['facts']),groups=spec['groups'],outcomes=c['outcomes'],
                        budget=spec['budget'],task=task,repeat=repeat,backend=backend,**{k:v for k,v in result.items() if k!='values'}))
                table(output/'benchmark.csv',rows)
            print(f'Benchmarked {i+1} cases',flush=True)
    write_json(output/'hardware.json',dict(python=platform.python_version(),processor=platform.processor(),platform=platform.platform(),
        logical_cpus=os.cpu_count(),process_isolation=True,parallel_benchmarking=False,memory='Windows process PeakWorkingSetSize; includes interpreter and imported code',
        runtime='perf_counter in worker; excludes process launch; no tracemalloc; backend order reproducibly shuffled'))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('stage',choices=['worker','development','freeze','benchmark'])
    parser.add_argument('path',type=Path)
    args=parser.parse_args()
    {'worker':worker,'development':development,'freeze':freeze,'benchmark':benchmark}[args.stage](args.path if args.stage=='worker' else ROOT/args.path)
