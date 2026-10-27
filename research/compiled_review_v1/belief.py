import math
from functools import lru_cache
from itertools import product

from research.constrained_review_v1.solver import LazyPosterior
from research.decision_review_v1.model import boolean, mixture_bits


class Unsupported(ValueError):
    pass


def variables(node):
    if type(node) is int:
        return [node]
    return [v for child in node[1:] for v in variables(child)]


class Diagram:
    def __init__(self,graphs,n,order='occurrence',cap=50000):
        seen=list(dict.fromkeys(v for g in graphs for v in variables(g)))
        self.order=seen+[v for v in range(n) if v not in seen] if order=='occurrence' else list(range(n))
        self.rank={v:i for i,v in enumerate(self.order)}
        self.nodes=[None,None]
        self.unique={}
        self.cap=cap
        self.apply=lru_cache(None)(self._apply)
        self.negate=lru_cache(None)(self._negate)
        self.roots=tuple(self.compile(g) for g in graphs)
        self.joint={}
        self.joint_root=self.compile_joint(self.roots)

    def make(self,var,low,high):
        if low==high:
            return low
        key=(var,low,high)
        if key not in self.unique:
            if len(self.nodes)>=self.cap:
                raise Unsupported('diagram_node_cap')
            self.unique[key]=len(self.nodes)
            self.nodes.append(key)
        return self.unique[key]

    def _negate(self,node):
        if node<2:
            return 1-node
        var,low,high=self.nodes[node]
        return self.make(var,self.negate(low),self.negate(high))

    def _apply(self,op,a,b):
        if a<2 and b<2:
            return int(bool(a and b) if op=='AND' else bool(a or b))
        top=min((self.nodes[v][0] for v in (a,b) if v>=2),key=self.rank.get)
        a0,a1=self.nodes[a][1:] if a>=2 and self.nodes[a][0]==top else (a,a)
        b0,b1=self.nodes[b][1:] if b>=2 and self.nodes[b][0]==top else (b,b)
        return self.make(top,self.apply(op,a0,b0),self.apply(op,a1,b1))

    def compile(self,node):
        if type(node) is int:
            return self.make(node,0,1)
        op,*children=node
        if op=='NOT':
            return self.negate(self.compile(children[0]))
        result=1 if op=='AND' else 0
        for child in children:
            result=self.apply(op,result,self.compile(child))
        return result

    def compile_joint(self,roots):
        if roots in self.joint:
            return roots
        if len(self.joint)>=self.cap:
            raise Unsupported('joint_diagram_cap')
        if all(node<2 for node in roots):
            self.joint[roots]=None
        else:
            top=min((self.nodes[node][0] for node in roots if node>=2),key=self.rank.get)
            low=tuple(self.nodes[node][1] if node>=2 and self.nodes[node][0]==top else node for node in roots)
            high=tuple(self.nodes[node][2] if node>=2 and self.nodes[node][0]==top else node for node in roots)
            self.joint[roots]=(top,low,high)
            self.compile_joint(low)
            self.compile_joint(high)
        return roots

    def distribution(self,probabilities):
        @lru_cache(None)
        def visit(state):
            node=self.joint[state]
            if node is None:
                return {state:1.}
            var,low,high=node
            result={}
            for factor,child in ((1-probabilities[var],low),(probabilities[var],high)):
                if factor:
                    for key,p in visit(child).items():
                        result[key]=result.get(key,0.)+factor*p
            return result
        return visit(self.joint_root)


def errors_for(case,factor):
    return [min(.49,max(.005,q*factor)) for q in case['errors']]


def group_likelihood(case,errors,truth,h):
    value=1.
    for a,b in enumerate(h):
        if b>=0:
            erasure=case.get('erasures',[0.]*len(h))[a]
            value*=erasure if b==2 else 1-erasure
    for group in set(case.get('groups',[0]*len(h))):
        independent,low,high=1.,0.,1.
        for a,b in enumerate(h):
            if b not in (0,1) or case.get('groups',[0]*len(h))[a]!=group:
                continue
            noisy=b ^ truth[case['facts'][a]]
            independent*=errors[a] if noisy else 1-errors[a]
            if noisy:
                high=min(high,errors[a])
            else:
                low=max(low,errors[a])
        rho=case.get('group_rhos',{}).get(str(group),case['rho'])
        value*=(1-rho)*independent+rho*max(0.,high-low)
    return value


class GeneralPosterior(LazyPosterior):
    def children(self,h,a):
        mass=self.stats[h][0]
        for b in range(self.case.get('outcomes',2)):
            child=h[:a]+(b,)+h[a+1:]
            try:
                row=self.stats[child]
            except KeyError:
                continue
            yield row[0]/mass,child


class TruthStats(dict):
    def __init__(self,p):
        super().__init__()
        self.p=p

    def __missing__(self,h):
        p=self.p
        mass=0.
        sums=[0.]*(p.n+len(p.case['graph']))
        classes={}
        for truth,prior,target in p.truths:
            weight=prior*group_likelihood(p.case,p.errors,truth,h)
            mass+=weight
            for k,value in enumerate(target):
                sums[k]+=weight*value
            key=target[p.n:]
            classes[key]=classes.get(key,0.)+weight
        return finish(self,h,mass,sums,classes)


def finish(cache,h,mass,sums,classes):
    if mass<=0:
        raise KeyError(h)
    probabilities=[v/mass for v in sums]
    normalized=[v/mass for v in classes.values() if v>0]
    entropy=-sum(q*math.log2(q) for q in normalized)
    cache[h]=(mass,probabilities,entropy,1-sum(q*q for q in normalized))
    return cache[h]


class TruthPosterior(GeneralPosterior):
    def __init__(self,case,factor=1.,cap=65536):
        if 2**case['n']>cap:
            raise Unsupported('truth_assignment_cap')
        self.case=case
        self.n,self.m=case['n'],len(case['facts'])
        self.root=(-1,)*self.m
        self.errors=errors_for(case,factor)
        self.report_errors=self.errors
        self.truths=[(t,q,tuple(t)+tuple(int(boolean(g,t)) for g in case['graph']))
            for t,q in mixture_bits(case['priors'],case['truth_rho']).items() if q]
        self.stats=TruthStats(self)


class ExplicitPosterior(GeneralPosterior):
    def __init__(self,case,factor=1.,cap=131072):
        outcomes=case.get('outcomes',2)
        if 2**case['n']*outcomes**len(case['facts'])>cap:
            raise Unsupported('explicit_world_cap')
        truth=TruthPosterior(case,factor)
        law=[]
        for t,prior,_ in truth.truths:
            for y in product(range(outcomes),repeat=truth.m):
                weight=prior*group_likelihood(case,truth.errors,t,y)
                if weight:
                    law.append((weight,t,y))
        super().__init__(case,law)


class ProductStats(dict):
    def __init__(self,p):
        super().__init__()
        self.p=p

    def __missing__(self,h):
        p=self.p
        components=p.components(h)
        mass=sum(weight for weight,probs in components)
        sums=[0.]*(p.n+len(p.case['graph']))
        classes={}
        for weight,probs in components:
            for k,value in enumerate(probs):
                sums[k]+=weight*value
            for key,value in p.diagram.distribution(probs).items():
                classes[key]=classes.get(key,0.)+weight*value
                for j,bit in enumerate(key):
                    sums[p.n+j]+=weight*value*bit
        p.max_components=max(p.max_components,len(components))
        return finish(self,h,mass,sums,classes)


class CompiledPosterior(GeneralPosterior):
    def __init__(self,case,factor=1.,order='occurrence',merge=True,diagram=None):
        self.case=case
        self.n,self.m=case['n'],len(case['facts'])
        self.root=(-1,)*self.m
        self.errors=errors_for(case,factor)
        self.report_errors=self.errors
        self.merge=merge
        self.diagram=diagram or Diagram(case['graph'],self.n,order)
        self.max_components=0
        self.stats=ProductStats(self)

    def components(self,h):
        c=self.case
        priors=c['priors']
        base=[(1-c['truth_rho'],list(priors))] if c['truth_rho']<1 else []
        cuts=sorted({0.,1.,*priors})
        if c['truth_rho']:
            base += [(c['truth_rho']*(b-a),[float((a+b)/2<q) for q in priors]) for a,b in zip(cuts,cuts[1:])]
        erasure_mass=1.
        for a,b in enumerate(h):
            if b>=0:
                rate=c.get('erasures',[0.]*self.m)[a]
                erasure_mass*=rate if b==2 else 1-rate
        groups=c.get('groups',[0]*self.m)
        for group in sorted(set(groups)):
            observed=[a for a,b in enumerate(h) if b in (0,1) and groups[a]==group]
            if not observed:
                continue
            rho=c.get('group_rhos',{}).get(str(group),c['rho'])
            independent=[[1.,1.] for _ in range(self.n)]
            for a in observed:
                fact,q,b=c['facts'][a],self.errors[a],h[a]
                independent[fact][0]*=q if b else 1-q
                independent[fact][1]*=1-q if b else q
            if len(observed)==1 or rho==0:
                factors=[(1.,independent)]
            else:
                factors=[(1-rho,independent)] if rho<1 else []
                cuts=sorted({0.,1.,*(self.errors[a] for a in observed)})
                for low,high in zip(cuts,cuts[1:]):
                    constraints={}
                    consistent=True
                    for a in observed:
                        fact=c['facts'][a]
                        required=h[a] ^ int((low+high)/2<self.errors[a])
                        if fact in constraints and constraints[fact]!=required:
                            consistent=False
                            break
                        constraints[fact]=required
                    if consistent:
                        likelihood=[[1.,1.] for _ in range(self.n)]
                        for fact,bit in constraints.items():
                            likelihood[fact][1-bit]=0.
                        factors.append((rho*(high-low),likelihood))
            next_components=[]
            for weight,probs in base:
                for coefficient,likelihood in factors:
                    updated=[]
                    mass=weight*coefficient
                    for prob,(l0,l1) in zip(probs,likelihood):
                        z=(1-prob)*l0+prob*l1
                        if z<=0:
                            mass=0.
                            break
                        mass*=z
                        updated.append(prob*l1/z)
                    if mass>0:
                        next_components.append((mass,updated))
            if self.merge:
                merged={}
                for weight,probs in next_components:
                    key=tuple(probs)
                    merged[key]=merged.get(key,0.)+weight
                base=[(weight,list(key)) for key,weight in merged.items()]
            else:
                base=next_components
        return [(weight*erasure_mass,probs) for weight,probs in base if weight*erasure_mass>0]
