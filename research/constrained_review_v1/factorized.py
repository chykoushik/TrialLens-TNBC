import math
from functools import lru_cache
from itertools import product

from research.decision_review_v1.model import boolean, mixture_bits
from research.constrained_review_v1.solver import (
    AbstainPolicy, ExistingPolicy, LazyPosterior, PricingPolicy, master,
)


class AnalyticStats(dict):
    def __init__(self,p):
        super().__init__()
        self.p=p

    def __missing__(self,h):
        p=self.p
        observations=[(p.case['facts'][a],p.errors[a],bit) for a,bit in enumerate(h) if bit>=0]
        mass=0.
        sums=[0.]*(p.n+len(p.case['graph']))
        classes={}
        for truth,prior,target in p.truths:
            independent,low,high=1.,0.,1.
            for fact,error,bit in observations:
                noisy=bit ^ truth[fact]
                independent*=error if noisy else 1-error
                if noisy:
                    high=min(high,error)
                else:
                    low=max(low,error)
            likelihood=(1-p.case['rho'])*independent+p.case['rho']*max(0.,high-low)
            weight=prior*likelihood
            mass+=weight
            for k,value in enumerate(target):
                sums[k]+=weight*value
            key=target[p.n:]
            classes[key]=classes.get(key,0.)+weight
        if mass<=0:
            raise KeyError(h)
        probabilities=[v/mass for v in sums]
        classes={key:v/mass for key,v in classes.items() if v}
        entropy=-sum(q*math.log2(q) for q in classes.values())
        self[h]=(mass,probabilities,entropy,1-sum(q*q for q in classes.values()))
        return self[h]


class ClosedFormPosterior(LazyPosterior):
    def __init__(self,case,factor=1.):
        self.case=case
        self.n,self.m=case['n'],len(case['facts'])
        self.root=(-1,)*self.m
        self.errors=[min(.49,max(.005,q*factor)) for q in case['errors']]
        self.report_errors=self.errors
        self.truths=[(truth,prior,tuple(truth)+tuple(int(boolean(g,truth)) for g in case['graph']))
                     for truth,prior in mixture_bits(case['priors'],case['truth_rho']).items() if prior]
        self.stats=AnalyticStats(self)


def action(policy,h):
    if isinstance(policy,AbstainPolicy):
        return None
    if isinstance(policy,ExistingPolicy):
        return policy.policy.choose(h)
    return policy.choose(h)


def measure_tree(policy,actual):
    p,c=policy.p,actual.case
    names=('utility','cost','criterion_correct','criterion_incorrect','criterion_abstention',
           'protocol_correct','protocol_incorrect','protocol_abstention','protocol_false_positive','brier','entropy_reduction',
           'calibration_bias')
    result=dict.fromkeys(names,0.)
    mass_total=0.
    terminals=0
    def visit(h,probability):
        nonlocal mass_total,terminals
        a=action(policy,h)
        if a is not None:
            for q,child in actual.children(h,a):
                visit(child,probability*q)
            return
        mass_total+=probability
        terminals+=1
        labels=policy.decode(h)
        truth_probs=actual.stats[h][1]
        forecast=p.stats[h][1]
        cost=sum(cost for cost,b in zip(c['costs'],h) if b>=0)
        assert cost<=policy.budget
        utility=-c['cost_penalty']*cost
        for k,(label,z) in enumerate(zip(labels,truth_probs)):
            prefix='criterion' if k<p.n else 'protocol'
            if label<0:
                result[prefix+'_abstention']+=probability
                reward=-c['abstention']
            else:
                correct=z if label else 1-z
                incorrect=1-correct
                result[prefix+'_correct']+=probability*correct
                result[prefix+'_incorrect']+=probability*incorrect
                if prefix=='protocol' and label:
                    result['protocol_false_positive']+=probability*incorrect
                reward=correct-incorrect*(c['false_positive'] if label else c['false_negative'])
            utility+=reward*(c['criterion_weight']/p.n if k<p.n else 1/len(c['graph']))
            result['brier']+=probability*(forecast[k]**2-2*forecast[k]*z+z)/len(labels)
            result['calibration_bias']+=probability*(forecast[k]-z)/len(labels)
        result['utility']+=probability*utility
        result['cost']+=probability*cost
        result['entropy_reduction']+=probability*(actual.stats[actual.root][2]-actual.stats[h][2])
    visit(p.root,1.)
    assert abs(mass_total-1)<1e-8
    result['risk']=result['protocol_incorrect']/len(c['graph'])
    asserted=result['protocol_correct']+result['protocol_incorrect']
    result['selective_error']=result['protocol_incorrect']/asserted if asserted>1e-15 else None
    result['coverage']=asserted/len(c['graph'])
    result['terminals']=terminals
    return result


def column_tree(policy,models):
    rows=[measure_tree(policy,p) for p in models]
    return dict(policy=policy,utility=rows[0]['utility'],risks=tuple(r['risk'] for r in rows),rows=rows)


def solve_fast(models,budget,epsilon,columns=None,max_iterations=30):
    columns=list(columns or [column_tree(AbstainPolicy(models[0],budget),models)])
    upper=float('inf')
    trace=[]
    for iteration in range(max_iterations):
        solution=master(columns,epsilon)
        policy=PricingPolicy(models,budget,solution['multipliers'])
        value=policy.value(policy.p.root,policy.p.m)
        column=column_tree(policy,models)
        evaluated=column['utility']-sum(lam*r for lam,r in zip(solution['multipliers'],column['risks']))
        assert abs(value-evaluated)<1e-8
        upper=min(upper,value+epsilon*sum(solution['multipliers']))
        trace.append(dict(iteration=iteration,primal=solution['primal'],upper=upper,states=policy.states))
        if upper-solution['primal']<=1e-8:
            break
        if any(abs(col['utility']-column['utility'])<1e-10 and max(abs(a-b) for a,b in zip(col['risks'],column['risks']))<1e-10 for col in columns):
            break
        columns.append(column)
    solution=master(columns,epsilon)
    return dict(columns=columns,solution=solution,upper=upper,gap=max(0.,upper-solution['primal']),trace=trace)
