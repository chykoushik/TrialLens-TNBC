import math
import random
from collections import defaultdict
from functools import lru_cache
from itertools import product


def boolean(node, truth):
    if isinstance(node, int):
        return truth[node]
    op, *children = node
    values = [boolean(c, truth) for c in children]
    return (not values[0]) if op == 'NOT' else all(values) if op == 'AND' else any(values)


def mixture_bits(priors, rho):
    law = defaultdict(float)
    for bits in product((0, 1), repeat=len(priors)):
        law[bits] += (1-rho) * math.prod(p if b else 1-p for p, b in zip(priors, bits))
    cuts = sorted({0., 1., *priors})
    for a, b in zip(cuts, cuts[1:]):
        law[tuple(int((a+b)/2 < p) for p in priors)] += rho*(b-a)
    return dict(law)


def world_law(case, factor=1., independent=False, report_independent=False, truth_independent=False):
    priors = case['priors']
    truth_law = mixture_bits(priors, 0 if independent or truth_independent else case['truth_rho'])
    errors = [min(.49, max(.005, q*factor)) for q in case['errors']]
    error_law = mixture_bits(errors, 0 if independent or report_independent else case['rho'])
    law = defaultdict(float)
    for truth, p in truth_law.items():
        for noise, q in error_law.items():
            reports = tuple(truth[f] ^ e for f, e in zip(case['facts'], noise))
            law[truth, reports] += p*q
    return [(p, t, y) for (t, y), p in law.items() if p > 1e-18]


def generate(split, seed, family):
    rng = random.Random(f'decision-review-v1:{split}:{seed}:{family}')
    n = rng.choice((2, 3)) if split == 'development' else rng.choice((3, 4))
    facts = list(range(n)) + [rng.randrange(n) for _ in range(2)]
    rng.shuffle(facts)
    graph = [['AND', *range(n)], ['OR', 0, ['NOT', n-1]]]
    if split == 'final':
        graph = [['AND', ['OR', 0, 1], ['NOT', n-1]], ['OR', ['AND', 0, n-1], 1]]
        if family in ('overlap', 'stale'):
            graph.append(['AND', *range(1, n)])
    rho = rng.uniform(.55, .9) if family in ('shared', 'conflict') else rng.uniform(.05, .35)
    ages = [rng.choice((0, 7, 30, 90)) if family == 'stale' else 0 for _ in facts]
    primitive = [rng.uniform(.04, .24) for _ in facts]
    errors = [.5-(.5-q)*math.exp(-a/45) for q, a in zip(primitive, ages)]
    factor = .55 if family in ('miscalibrated', 'stale') else 1.
    return dict(id=f'{split}-{family}-{seed}', split=split, seed=seed, family=family,
                n=n, facts=facts, graph=graph, priors=[rng.uniform(.15, .85) for _ in range(n)],
                truth_rho=rng.uniform(.15, .65), rho=rho, errors=errors, ages=ages,
                costs=[rng.choice((1, 1, 2, 3)) for _ in facts], factor=factor,
                primitive_errors=primitive, false_positive=6. if family == 'asymmetric' else 3.,
                false_negative=2. if family == 'asymmetric' else 3., abstention=.2,
                cost_penalty=.04, criterion_weight=.5)


class Posterior:
    def __init__(self, case, law):
        self.case, self.law = case, law
        self.n, self.m = case['n'], len(case['facts'])
        self.report_errors = [sum(q for q,t,y in law if y[a] != t[case['facts'][a]]) for a in range(self.m)]
        self.root = (-1,)*self.m
        self.stats = {}
        grouped = {}
        size = self.n+len(case['graph'])
        for p,t,y in law:
            if y not in grouped:
                grouped[y] = [0., [0.]*size, defaultdict(float)]
            row = grouped[y]
            target = tuple(t)+tuple(int(boolean(g,t)) for g in case['graph'])
            row[0] += p
            for k,b in enumerate(target):
                row[1][k] += p*b
            row[2][target[self.n:]] += p
        accumulated = {}
        masks = list(product((0,1),repeat=self.m))
        for y,(mass,probs,classes) in grouped.items():
            for mask in masks:
                h = tuple(b if keep else -1 for b,keep in zip(y,mask))
                if h not in accumulated:
                    accumulated[h] = [0., [0.]*size, defaultdict(float)]
                row = accumulated[h]
                row[0] += mass
                for k,value in enumerate(probs):
                    row[1][k] += value
                for key,value in classes.items():
                    row[2][key] += value
        for h,(mass,probs,classes) in accumulated.items():
            probs = [x/mass for x in probs]
            classes = {k:v/mass for k,v in classes.items()}
            entropy = -sum(p*math.log2(p) for p in classes.values() if p)
            self.stats[h] = (mass, probs, entropy, 1-sum(p*p for p in classes.values()))

    def children(self, h, a):
        for b in (0, 1):
            child = h[:a]+(b,)+h[a+1:]
            if child in self.stats:
                yield self.stats[child][0]/self.stats[h][0], child

    def available(self, h, budget):
        spent = sum(c for c,b in zip(self.case['costs'], h) if b >= 0)
        return [a for a,b in enumerate(h) if b < 0 and spent+self.case['costs'][a] <= budget]

    def losses(self, p):
        c = self.case
        return [p*c['false_negative']-(1-p), (1-p)*c['false_positive']-p, c['abstention']]

    @lru_cache(None)
    def decisions(self, h, ensemble=()):
        distributions = [self, *ensemble]
        labels, loss = [], 0.
        for k in range(self.n+len(self.case['graph'])):
            risks = [max(d.losses(d.stats[h][1][k])[label] for d in distributions) for label in range(3)]
            label = min(range(3), key=lambda x:(risks[x], -x))
            labels.append(label if label < 2 else -1)
            loss += risks[label]*(self.case['criterion_weight']/self.n if k < self.n else 1/len(self.case['graph']))
        return tuple(labels), loss


class Policy:
    def __init__(self, posterior, budget, method, ensemble=()):
        self.p, self.budget, self.method, self.ensemble = posterior, budget, method, ensemble
        self.actions = {}
        self.solve = lru_cache(None)(self._solve)
        self.fixed = lru_cache(None)(self._fixed)
        self.choose = lru_cache(None)(self.choose)

    def terminal(self, h):
        return self.p.decisions(h, self.ensemble if self.method == 'robust_dp' else ())[1]

    def _fixed(self, h, subset):
        if not subset:
            return self.terminal(h)
        a, *tail = subset
        return self.p.case['cost_penalty']*self.p.case['costs'][a] + sum(q*self.fixed(ch,tuple(tail)) for q,ch in self.p.children(h,a))

    def best_fixed(self, h):
        available = self.p.available(h, self.budget)
        remaining = self.budget-sum(c for c,b in zip(self.p.case['costs'],h) if b >= 0)
        candidates = []
        for bits in product((0,1), repeat=len(available)):
            subset = tuple(a for a,b in zip(available,bits) if b)
            if sum(self.p.case['costs'][a] for a in subset) <= remaining:
                candidates.append((self.fixed(h,subset),len(subset),subset))
        return min(candidates)[2]

    def _solve(self, h, depth):
        stop = self.terminal(h)
        best, chosen = stop, None
        if depth == 0:
            return best
        for a in self.p.available(h,self.budget):
            distributions = (self.p,*self.ensemble) if self.method == 'robust_dp' else (self.p,)
            future = max(sum(q*self.solve(ch,depth-1) for q,ch in d.children(h,a)) for d in distributions)
            value = self.p.case['cost_penalty']*self.p.case['costs'][a]+future
            if value < best-1e-12:
                best, chosen = value, a
        self.actions[h,depth] = chosen
        return best

    def choose(self, h):
        p, c, method = self.p, self.p.case, self.method
        available = p.available(h,self.budget)
        if not available:
            return None
        if method in ('exact_dp','robust_dp','lookahead2','lookahead1'):
            depth = 1 if method == 'lookahead1' else 2 if method == 'lookahead2' else p.m
            self.solve(h,depth)
            return self.actions.get((h,depth))
        if method in ('fixed','replan'):
            if method == 'replan':
                subset = self.best_fixed(h)
            else:
                if not hasattr(self,'subset'):
                    self.subset = self.best_fixed(p.root)
                subset = tuple(a for a in self.subset if h[a] < 0)
            return subset[0] if subset else None
        scores = []
        for a in available:
            children = list(p.children(h,a))
            cost = c['costs'][a]
            gain = self.terminal(h)-sum(q*self.terminal(ch) for q,ch in children)
            if method == 'eig':
                score = (p.stats[h][2]-sum(q*p.stats[ch][2] for q,ch in children))/cost
            elif method == 'ec2':
                score = (p.stats[h][3]-sum(q**3*p.stats[ch][3] for q,ch in children))/cost
            elif method == 'risk_proxy':
                score = (gain-3*p.report_errors[a])/cost
            elif method == 'cheapest':
                score = 1/cost
            elif method == 'random':
                score = random.Random(f"rank:{c['id']}:{h}:{a}").random()
            else:
                score = gain/cost-c['cost_penalty']
            scores.append((score,-a,a))
        score,_,a = max(scores)
        return a if score > 1e-12 else None

    def history(self, reports):
        h = self.p.root
        while True:
            a = self.choose(h)
            if a is None:
                return h
            assert h[a] == -1
            h = h[:a]+(reports[a],)+h[a+1:]


def evaluate(policy, actual):
    p, c = policy.p, actual.case
    metrics = defaultdict(float)
    for prefix in ('criterion','protocol'):
        for suffix in ('correct','incorrect','abstention'):
            metrics[prefix+'_'+suffix] = 0.
    histories = defaultdict(float)
    for probability,truth,reports in actual.law:
        h = policy.history(reports)
        labels,_ = p.decisions(h,policy.ensemble if policy.method == 'robust_dp' else ())
        target = tuple(truth)+tuple(int(boolean(g,truth)) for g in c['graph'])
        spent = sum(cost for cost,b in zip(c['costs'],h) if b >= 0)
        assert spent <= policy.budget
        utility = -c['cost_penalty']*spent
        for k,(label,t) in enumerate(zip(labels,target)):
            prefix = 'criterion' if k < p.n else 'protocol'
            name = 'abstention' if label == -1 else 'correct' if label == t else 'incorrect'
            metrics[prefix+'_'+name] += probability
            reward = -c['abstention'] if label == -1 else 1 if label == t else -c['false_positive'] if label else -c['false_negative']
            utility += reward*(c['criterion_weight']/p.n if k < p.n else 1/len(c['graph']))
        metrics['utility'] += probability*utility
        metrics['cost'] += probability*spent
        metrics['realized_entropy_reduction'] += probability*(actual.stats[actual.root][2]-actual.stats[h][2])
        metrics['forecast_entropy_reduction_actual_paths'] += probability*(p.stats[p.root][2]-p.stats[h][2])
        histories[h] += probability
        if len({reports[a] for a,f in enumerate(c['facts']) if f == c['facts'][0]}) > 1:
            metrics['conflicting_world_mass'] += probability
    forecast = forecast_value(policy)
    metrics['forecast_utility'] = -forecast
    metrics['forecast_bias'] = -forecast-metrics['utility']
    metrics['terminal_histories'] = len(histories)
    metrics['dp_states'] = policy.solve.cache_info().currsize
    return dict(metrics), histories


def forecast_value(policy):
    @lru_cache(None)
    def visit(h):
        a = policy.choose(h)
        if a is None:
            return policy.terminal(h)
        return policy.p.case['cost_penalty']*policy.p.case['costs'][a]+sum(q*visit(ch) for q,ch in policy.p.children(h,a))
    return visit(policy.p.root)
