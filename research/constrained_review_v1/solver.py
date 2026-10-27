import math
from functools import lru_cache

from research.decision_review_v1.model import Posterior, boolean


class LazyStats(dict):
    def __init__(self, posterior):
        super().__init__()
        self.p = posterior

    def __missing__(self, h):
        matching = [(y,row) for y,row in self.p.grouped.items() if all(b<0 or b==y[a] for a,b in enumerate(h))]
        mass = sum(row[0] for _,row in matching)
        if mass<=0:
            raise KeyError(h)
        size = self.p.n+len(self.p.case['graph'])
        probabilities = [sum(row[1][k] for _,row in matching)/mass for k in range(size)]
        classes = {}
        for _,row in matching:
            for key,value in row[2].items():
                classes[key] = classes.get(key,0.)+value/mass
        entropy = -sum(p*math.log2(p) for p in classes.values() if p)
        self[h] = (mass,probabilities,entropy,1-sum(p*p for p in classes.values()))
        return self[h]


class LazyPosterior(Posterior):
    def __init__(self, case, law):
        self.case,self.law = case,law
        self.n,self.m = case['n'],len(case['facts'])
        self.root = (-1,)*self.m
        self.report_errors = [sum(q for q,t,y in law if y[a]!=t[case['facts'][a]]) for a in range(self.m)]
        self.grouped = {}
        size = self.n+len(case['graph'])
        for q,t,y in law:
            if y not in self.grouped:
                self.grouped[y] = [0.,[0.]*size,{}]
            row = self.grouped[y]
            target = tuple(t)+tuple(int(boolean(g,t)) for g in case['graph'])
            row[0] += q
            for k,z in enumerate(target):
                row[1][k] += q*z
            classes = target[self.n:]
            row[2][classes] = row[2].get(classes,0.)+q
        self.stats = LazyStats(self)

    def children(self,h,a):
        mass = self.stats[h][0]
        for b in (0,1):
            child = h[:a]+(b,)+h[a+1:]
            try:
                row = self.stats[child]
            except KeyError:
                continue
            yield row[0]/mass,child


class PricingPolicy:
    def __init__(self, models, budget, multipliers, depth=None, bound=False):
        self.models,self.p = tuple(models),models[0]
        self.budget,self.multipliers = budget,tuple(multipliers)
        self.depth,self.use_bound = depth,bound
        self.actions,self.labels = {},{}
        self.states,self.pruned = 0,0
        self.value = lru_cache(None)(self._value)
        self.terminal = lru_cache(None)(self._terminal)
        self.revelation = lru_cache(None)(self._revelation)

    def _terminal(self,h):
        c,p = self.p.case,self.p
        rows = [model.stats[h] for model in self.models]
        labels,total = [],0.
        for k in range(p.n+len(c['graph'])):
            weight = c['criterion_weight']/p.n if k<p.n else 1/len(c['graph'])
            candidates = []
            for label in (-1,0,1):
                if label<0:
                    value = -rows[0][0]*weight*c['abstention']
                else:
                    prob = rows[0][1][k]
                    reward = prob-(1-prob)*c['false_positive'] if label else (1-prob)-prob*c['false_negative']
                    value = rows[0][0]*weight*reward
                    if k>=p.n:
                        value -= sum(lam*row[0]*((1-row[1][k]) if label else row[1][k])/len(c['graph']) for lam,row in zip(self.multipliers,rows))
                candidates.append((value,-(label+1),label))
            value,_,label = max(candidates)
            labels.append(label)
            total += value
        self.labels[h] = tuple(labels)
        return total

    def _revelation(self,h):
        unreviewed = [a for a,b in enumerate(h) if b<0]
        if not unreviewed:
            return self.terminal(h)
        return sum(self.revelation(ch) for _,ch in self.p.children(h,unreviewed[0]))

    def _value(self,h,remaining):
        self.states += 1
        best,action = self.terminal(h),None
        if remaining==0:
            self.actions[h,remaining] = None
            return best
        mass = self.p.stats[h][0]
        available = self.p.available(h,self.budget)
        if self.use_bound and available:
            optimistic = self.revelation(h)-self.p.case['cost_penalty']*min(self.p.case['costs'][a] for a in available)*mass
            if optimistic <= best+1e-12:
                self.pruned += len(available)
                self.actions[h,remaining] = None
                return best
        for a in available:
            value = -self.p.case['cost_penalty']*self.p.case['costs'][a]*mass
            value += sum(self.value(ch,remaining-1) for _,ch in self.p.children(h,a))
            if value>best+1e-12:
                best,action = value,a
        self.actions[h,remaining] = action
        return best

    def choose(self,h):
        remaining = self.depth if self.depth is not None else sum(b<0 for b in h)
        self.value(h,remaining)
        return self.actions[h,remaining]

    def decode(self,h):
        self.terminal(h)
        return self.labels[h]

    def history(self,reports):
        h = self.p.root
        while True:
            a = self.choose(h)
            if a is None:
                return h
            h = h[:a]+(reports[a],)+h[a+1:]


class ExistingPolicy:
    def __init__(self, policy):
        self.policy,self.p,self.budget = policy,policy.p,policy.budget

    def history(self,reports):
        return self.policy.history(reports)

    def decode(self,h):
        return self.p.decisions(h,self.policy.ensemble if self.policy.method=='robust_dp' else ())[0]


class AbstainPolicy:
    def __init__(self,p,budget):
        self.p,self.budget = p,budget

    def history(self,reports):
        return self.p.root

    def decode(self,h):
        labels = list(self.p.decisions(h)[0])
        labels[self.p.n:] = [-1]*len(self.p.case['graph'])
        return tuple(labels)


def measure(policy,actual):
    c,p = actual.case,policy.p
    names = ('utility','cost','criterion_correct','criterion_incorrect','criterion_abstention',
             'protocol_correct','protocol_incorrect','protocol_abstention','protocol_false_positive','brier','entropy_reduction')
    result = dict.fromkeys(names,0.)
    cache,terminals = {},{}
    for q,t,y in actual.law:
        if y not in cache:
            h = policy.history(y)
            cache[y] = (h,policy.decode(h))
        h,labels = cache[y]
        targets = tuple(t)+tuple(int(boolean(g,t)) for g in c['graph'])
        cost = sum(cost for cost,b in zip(c['costs'],h) if b>=0)
        assert cost<=policy.budget
        utility = -c['cost_penalty']*cost
        for k,(label,z) in enumerate(zip(labels,targets)):
            prefix = 'criterion' if k<p.n else 'protocol'
            status = 'abstention' if label<0 else 'correct' if label==z else 'incorrect'
            result[prefix+'_'+status] += q
            if prefix=='protocol' and label==1 and z==0:
                result['protocol_false_positive'] += q
            reward = -c['abstention'] if label<0 else 1 if label==z else -c['false_positive'] if label else -c['false_negative']
            utility += reward*(c['criterion_weight']/p.n if k<p.n else 1/len(c['graph']))
            result['brier'] += q*(p.stats[h][1][k]-z)**2/len(targets)
        result['utility'] += q*utility
        result['cost'] += q*cost
        result['entropy_reduction'] += q*(actual.stats[actual.root][2]-actual.stats[h][2])
        terminals[h] = terminals.get(h,0.)+q
    result['risk'] = result['protocol_incorrect']/len(c['graph'])
    asserted = result['protocol_correct']+result['protocol_incorrect']
    result['selective_error'] = result['protocol_incorrect']/asserted if asserted>1e-15 else None
    result['coverage'] = asserted/len(c['graph'])
    result['terminals'] = len(terminals)
    return result


def policy_column(policy,models):
    rows = [measure(policy,p) for p in models]
    return dict(policy=policy,utility=rows[0]['utility'],risks=tuple(r['risk'] for r in rows),rows=rows)


def master(columns,epsilon,tolerance=1e-10):
    n,k = len(columns),len(columns[0]['risks'])
    assert max(columns[0]['risks'])<1e-12
    rows = [[1.]*n+[0.]*k+[1.]]
    rows += [[c['risks'][s] for c in columns]+[float(j==s) for j in range(k)]+[epsilon] for s in range(k)]
    basis = [0]+[n+s for s in range(k)]
    reduced = [c['utility']-columns[0]['utility'] for c in columns]+[0.]*k+[columns[0]['utility']]
    pivots = 0
    while True:
        entering = next((j for j in range(n+k) if j not in basis and reduced[j]>tolerance),None)
        if entering is None:
            break
        feasible = [(row[-1]/row[entering],basis[i],i) for i,row in enumerate(rows) if row[entering]>tolerance]
        if not feasible:
            raise ArithmeticError('Unbounded master')
        ratio,_,leaving = min(feasible)
        pivot = rows[leaving][entering]
        rows[leaving] = [v/pivot for v in rows[leaving]]
        for i,row in enumerate(rows):
            if i!=leaving:
                factor = row[entering]
                rows[i] = [v-factor*u for v,u in zip(row,rows[leaving])]
        factor = reduced[entering]
        value = reduced[-1]+factor*rows[leaving][-1]
        reduced = [v-factor*u for v,u in zip(reduced,rows[leaving])]
        reduced[-1] = value
        basis[leaving] = entering
        pivots += 1
        if pivots>10000:
            raise ArithmeticError('Master pivot limit')
    weights = [0.]*n
    for i,j in enumerate(basis):
        if j<n:
            weights[j] = max(0.,rows[i][-1])
    multipliers = [max(0.,-reduced[n+s]) for s in range(k)]
    primal = sum(w*c['utility'] for w,c in zip(weights,columns))
    t = max(c['utility']-sum(lam*r for lam,r in zip(multipliers,c['risks'])) for c in columns)
    dual = t+epsilon*sum(multipliers)
    assert abs(sum(weights)-1)<1e-7
    assert all(sum(w*c['risks'][s] for w,c in zip(weights,columns))<=epsilon+1e-7 for s in range(k))
    assert abs(primal-dual)<1e-7
    return dict(weights=weights,multipliers=multipliers,primal=primal,dual=dual,pivots=pivots)


def constrained(models,budget,epsilon,columns=None,max_iterations=30,bound=False,depth=None):
    columns = list(columns or [policy_column(AbstainPolicy(models[0],budget),models)])
    history = []
    upper = float('inf')
    for iteration in range(max_iterations):
        solution = master(columns,epsilon)
        pricing = PricingPolicy(models,budget,solution['multipliers'],depth=depth,bound=bound)
        value = pricing.value(pricing.p.root,pricing.p.m if depth is None else depth)
        column = policy_column(pricing,models)
        if depth is None:
            checked = column['utility']-sum(lam*r for lam,r in zip(solution['multipliers'],column['risks']))
            assert abs(value-checked)<1e-8
            upper = min(upper,value+epsilon*sum(solution['multipliers']))
        history.append(dict(iteration=iteration,primal=solution['primal'],upper=upper if math.isfinite(upper) else None,
                            states=pricing.states,pruned=pricing.pruned,columns=len(columns)))
        if depth is None and upper-solution['primal']<=1e-8:
            break
        duplicate = any(abs(c['utility']-column['utility'])<1e-10 and max(abs(a-b) for a,b in zip(c['risks'],column['risks']))<1e-10 for c in columns)
        if duplicate:
            break
        columns.append(column)
    solution = master(columns,epsilon)
    return dict(columns=columns,solution=solution,upper=upper if math.isfinite(upper) else None,
                gap=max(0.,upper-solution['primal']) if math.isfinite(upper) else None,trace=history)


def mixture_metrics(columns,weights,actual):
    metrics = [measure(c['policy'],actual) if w>1e-12 else {} for c,w in zip(columns,weights)]
    names = [k for k in metrics[next(i for i,w in enumerate(weights) if w>1e-12)] if k not in ('selective_error','terminals')]
    result = {k:sum(w*r.get(k,0.) for w,r in zip(weights,metrics)) for k in names}
    asserted = result['protocol_correct']+result['protocol_incorrect']
    result['selective_error'] = result['protocol_incorrect']/asserted if asserted>1e-15 else None
    result['mixture_support'] = sum(w>1e-9 for w in weights)
    return result
