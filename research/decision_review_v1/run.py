import argparse
import csv
import hashlib
import json
import platform
import shutil
import time
from collections import defaultdict
from pathlib import Path

from research.decision_review_v1.model import Posterior, Policy, evaluate, generate, world_law

ROOT = Path(__file__).resolve().parents[2]
FAMILIES = ('shared','conflict','overlap','miscalibrated','stale','asymmetric')
METHODS = ('voi','eig','ec2','risk_proxy','fixed','replan','lookahead2','exact_dp','robust_dp',
           'independent_voi','cheapest','random','no_review','forced_map')


def write_json(path, value):
    path.write_text(json.dumps(value,indent=2,allow_nan=False,default=str),encoding='utf-8')


def table(path, rows):
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with path.open('w',newline='',encoding='utf-8') as f:
        writer = csv.DictWriter(f,fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def inventory():
    files = []
    for folder in ('backend','data','docs','frontend/src','results/recomb/20261026-scientific-04c8030f','results/extraction','results/extraction-alignment','results/prioritization'):
        files.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    files.extend(ROOT/p for p in ('render.yaml','Dockerfile','README.md'))
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def run(output, final_seeds=12, development_seeds=3):
    output.mkdir(parents=True,exist_ok=False)
    before = inventory()
    write_json(output/'preservation_before.json',before)
    protocol = dict(version='decision-review-v1',development_seeds=list(range(development_seeds)),
                    final_seeds=list(range(10000,10000+final_seeds)),families=FAMILIES,
                    budgets=[2,4],methods=METHODS,bootstrap=4000,
                    primary='lookahead2 minus voi: mean utility, equal-weight budgets within seed, stratified families',
                    secondary=['lookahead2 minus eig','lookahead2 minus ec2','lookahead2 minus replan','robust_dp minus exact_dp','voi minus independent_voi'],
                    frozen_before_results=True,clinical_subjects=0,paid_requests=0,
                    rng='Python random.Random namespace decision-review-v1; finite integration, no simulated world sampling',
                    arithmetic='IEEE double; checks tolerance 1e-9; no rational exactness claim')
    write_json(output/'protocol.json',protocol)
    cases = [generate(split,seed,family) for split,seeds in [('development',range(development_seeds)),('final',range(10000,10000+final_seeds))] for seed in seeds for family in FAMILIES]
    write_json(output/'cases.json',cases)
    rows, gaps = [], []
    start = time.perf_counter()
    with (output/'policies.jsonl').open('w',encoding='utf-8') as policies:
        for index,c in enumerate(cases):
            actual = Posterior(c,world_law(c))
            nominal = actual if c['factor'] == 1 else Posterior(c,world_law(c,c['factor']))
            independent = Posterior(c,world_law(c,c['factor'],True))
            ensemble = tuple(Posterior(c,world_law(c,c['factor']*factor)) for factor in (.65,1.8))
            for budget in protocol['budgets']:
                cell = {}
                for method in METHODS:
                    t = time.perf_counter()
                    p = independent if method == 'independent_voi' else nominal
                    policy = Policy(p,budget,'voi' if method == 'independent_voi' else method,ensemble if method == 'robust_dp' else ())
                    if method == 'no_review':
                        policy.choose = lambda h: None
                    if method == 'forced_map':
                        modified = dict(c,abstention=100.)
                        p = Posterior(modified,nominal.law)
                        policy = Policy(p,budget,'voi')
                    metrics,histories = evaluate(policy,actual)
                    row = dict(case=c['id'],split=c['split'],seed=c['seed'],family=c['family'],budget=budget,method=method,
                               n=c['n'],m=len(c['facts']),protocols=len(c['graph']),rho=c['rho'],factor=c['factor'],seconds=time.perf_counter()-t,**metrics)
                    rows.append(row)
                    cell[method] = row
                    entries = []
                    for h,mass in sorted(histories.items()):
                        labels = policy.p.decisions(h,ensemble if method == 'robust_dp' else ())[0]
                        entries.append(dict(history=h,actual_probability=mass,labels=labels))
                    policies.write(json.dumps(dict(case=c['id'],budget=budget,method=method,terminals=entries))+'\n')
                gaps.append(dict(case=c['id'],budget=budget,nominal_gap=cell['exact_dp']['forecast_utility']-cell['lookahead2']['forecast_utility'],
                                 actual_gap=cell['exact_dp']['utility']-cell['lookahead2']['utility'],
                                 fixed_gap=cell['exact_dp']['forecast_utility']-cell['fixed']['forecast_utility']))
            table(output/'summary.csv',rows)
            write_json(output/'oracle_gaps.json',gaps)
            if index%6 == 5:
                print(f'Completed {index+1} cases',flush=True)
    write_json(output/'summary.json',rows)
    from backend.recomb_report import extraction_audit
    audit = extraction_audit()
    for source in audit['sources']:
        from backend.app.saved_trials import catalog
        from backend.app.extraction_source import load_source
        catalog_rows,_ = catalog(ROOT/'data/raw/trials')
        item = next(x for x in catalog_rows if x['nct_id']==source['nct_id'])
        section = load_source(Path('data/raw/trials')/item['snapshot'],source['nct_id'])
        source['eligibility_text_sha256'] = hashlib.sha256(section.text.encode('utf-8')).hexdigest()
        source['snapshot_sha256'] = source.pop('sha256')
    write_json(output/'human_audit.json',audit)
    after = inventory()
    changes = [p for p,h in before.items() if after.get(p)!=h]
    write_json(output/'verification.json',dict(historical_files_checked=len(before),historical_changes=changes,
               cases=len(cases),rows=len(rows),elapsed_seconds=time.perf_counter()-start,python=platform.python_version(),
               requests=0,credentials_accessed=False,production_changes=False))
    assert not changes
    source = output/'executed_source'
    source.mkdir()
    for name in ('model.py','run.py'):
        shutil.copyfile(Path(__file__).with_name(name),source/name)
    print('Research results saved',flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--final-seeds',type=int,default=12)
    parser.add_argument('--development-seeds',type=int,default=3)
    args = parser.parse_args()
    run(ROOT/args.output,args.final_seeds,args.development_seeds)
