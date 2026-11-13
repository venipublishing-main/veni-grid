"""Q3: lexicographic optimisation for versioned Q1 and Q3 policy semantics.

This is an ADDITIVE experimental entrypoint. C1 stays an independent hard-
feasibility service and Q1 stays the independently evaluated source of truth.
Supported policies are compiled completely or rejected before any search.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from ortools.sat.python import cp_model

from veni_grid_contract.core_v1 import CoreProblem, CoreWitness, core_problem_errors
from veni_grid_contract.conformance import review_core
from veni_grid_contract.primitives import Finding
from veni_grid_solver.compiler import Compiler, UnsupportedInput

from .evaluate import digest
from .q3_score import Q3Score, score_v2, verify_q3_policy, ContextMissing
from .q3_policy import QualityPolicyV2, ProtectedIdle, TargetLoadDeviation
from .models import (QualityPolicy, QualityResult, ActivityPairs, ResourceIdle,
                     DailySpread, TaggedPlacement, LocationChanges, UnmetRequests)


class Q2Options(BaseModel):
    model_config = ConfigDict(extra='forbid')
    max_time_seconds: float = Field(default=30, ge=0, le=300)
    workers: int = Field(default=1, ge=1, le=8)


class StageResult(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tier: Literal[2, 3, 4]
    solver_status: str
    objective_value: int | None = None
    proven_optimal: bool = False
    wall_seconds: float


class Q3Result(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: Literal['0.2.0'] = '0.2.0'
    status: Literal['FEASIBLE', 'INFEASIBLE', 'UNKNOWN', 'INVALID_INPUT', 'UNSUPPORTED', 'ERROR']
    solver_status: str = 'NOT_RUN'
    candidate: CoreWitness | None = None
    quality: Q3Score | None = None
    independent_validation: Literal['NOT_RUN', 'PASSED', 'FAILED'] = 'NOT_RUN'
    quality_optimality: Literal['PROVEN', 'NOT_PROVEN', 'NOT_ASSESSED'] = 'NOT_ASSESSED'
    model_sha256: str | None = None
    policy_sha256: str | None = None
    stages: list[StageResult] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    total_ms: float = 0
    publication: Literal['NOT_GRANTED'] = 'NOT_GRANTED'


class Q2Unsupported(ValueError):
    pass


class ObjectiveCompiler:
    """Build objective expressions independently of the Q1 scoring algorithm."""
    def __init__(self, p: CoreProblem, policy: QualityPolicy, c: Compiler):
        self.p, self.policy, self.c = p, policy, c
        self.m = c.m
        self.by_event = {e.id:e for e in p.events}
        self.by_resource = {r.id:r for r in p.resources}
        self.by_window = {w.id:w for w in p.windows}
        self.metric_bounds: dict[str,int] = {}

    def _boolean(self, terms, name):
        return self.c.OR(terms, name)

    def _starts(self, rid: str, day: str):
        return [(e.id,d,self.c.presence[e.id,rid,d.window_id])
                for e in self.p.events for d in self.c.domains[e.id]
                if d.day == day and (e.id,rid,d.window_id) in self.c.presence]

    def _duration_bound(self, x):
        return sum(d.absolute_end-d.absolute_start for _,d,_ in x)

    def _person_idle(self, rid, day):
        x = self._starts(rid,day)
        if len(x)<2: return self.m.new_constant(0),0
        low = min(d.absolute_start for _,d,_ in x)
        high = max(d.absolute_end for _,d,_ in x)
        maximum = high-low
        if maximum<=0: return self.m.new_constant(0),0
        any_on=self._boolean((v for _,_,v in x),f'q2:any:{rid}:{day}')
        starts=[];ends=[]
        for ix,(_,d,v) in enumerate(x):
            s=self.m.new_int_var(low,high+1,f'q2:idle:start:{rid}:{day}:{ix}')
            e=self.m.new_int_var(low-1,high,f'q2:idle:end:{rid}:{day}:{ix}')
            self.m.add(s== d.absolute_start*v + (high+1)*(1-v))
            self.m.add(e== d.absolute_end*v + (low-1)*(1-v))
            starts.append(s);ends.append(e)
        first=self.m.new_int_var(low,high+1,f'q2:first:{rid}:{day}')
        last=self.m.new_int_var(low-1,high,f'q2:last:{rid}:{day}')
        self.m.add_min_equality(first, starts)
        self.m.add_max_equality(last, ends)
        penalty=self.m.new_int_var(0,maximum,f'q2:idle:{rid}:{day}')
        total_occupied=sum((d.absolute_end-d.absolute_start)*v for _,d,v in x)
        self.m.add(penalty==last-first-total_occupied).only_enforce_if(any_on)
        self.m.add(penalty==0).only_enforce_if(any_on.Not())
        return penalty,maximum

    def _staff_load(self, rid, day):
        terms=self._starts(rid,day)
        upper=sum(d.work for _,d,_ in terms)
        var=self.m.new_int_var(0,upper,f'q2:load:{rid}:{day}')
        self.m.add(var==sum(d.work*v for _,d,v in terms))
        return var,upper

    def _location_map(self,e):
        # A single selected ROOM and complete known locations are sufficient
        # for Q1's per-event location semantics; reject all ambiguous shapes.
        fixed=[self.by_resource[r] for r in e.fixed_participant_ids if self.by_resource[r].kind=='SPACE']
        spaces=[q for q in e.requirements if q.kind=='SPACE']
        if fixed or len(spaces)!=1 or spaces[0].quantity!=1:
            raise Q2Unsupported(f'LOCATION_CHANGES needs exactly one selected ROOM per event: {e.id}')
        q=spaces[0]
        if any(self.by_resource[r].location_id is None for r in q.eligible_resource_ids):
            raise Q2Unsupported(f'LOCATION_CHANGES lacks a room location: {e.id}')
        locs={}
        for r in q.eligible_resource_ids:
            loc=self.by_resource[r].location_id
            locs.setdefault(loc,[]).append(self.c.y[e.id,q.id,r])
        return {loc:self._boolean(v,f'q2:loc:{e.id}:{loc}') for loc,v in locs.items()}

    def _switches(self, rid, day):
        ids=[e.id for e in self.p.events if (e.id,rid) in self.c.used and
             any(d.day==day for d in self.c.domains[e.id])]
        if len(ids)<2: return self.m.new_constant(0),0
        if len(ids)>80:
            raise Q2Unsupported(f'LOCATION_CHANGES has over 80 events for {rid}/{day}')
        pres={eid:self.c.AND([self.c.used[eid,rid],self.c.on_day[eid,day]],'q2:staffday') for eid in ids}
        any_on=self._boolean(pres.values(),f'q2:any_switch:{rid}:{day}')
        edges=[(0,0,any_on.Not())]
        changed=[]
        for i,eid in enumerate(ids,1):
            edges.append((i,i,pres[eid].Not()))
            first=self.c.b('q2:first_edge');last=self.c.b('q2:last_edge')
            self.m.add(first<=pres[eid]);self.m.add(last<=pres[eid])
            edges.extend([(0,i,first),(i,0,last)])
        loc_by_e={eid:self._location_map(self.by_event[eid]) for eid in ids}
        for i,a in enumerate(ids,1):
            for j,b in enumerate(ids,1):
                if a==b: continue
                nxt=self.c.b('q2:next');edges.append((i,j,nxt))
                self.m.add(nxt<=pres[a]);self.m.add(nxt<=pres[b])
                self.m.add(self.c.ends[a]<=self.c.starts[b]).only_enforce_if(nxt)
                for la,va in loc_by_e[a].items():
                    for lb,vb in loc_by_e[b].items():
                        if la!=lb:
                            changed.append(self.c.AND([nxt,va,vb],'q2:location_switch'))
        self.m.add_circuit(edges)
        ub=max(0,len(ids)-1)
        penalty=self.m.new_int_var(0,ub,f'q2:switches:{rid}:{day}')
        self.m.add(penalty==sum(changed))
        return penalty,ub

    def metric_expression(self,metric):
        m=self.m
        if isinstance(metric, ActivityPairs):
            terms=[];limit=0
            for aid in metric.activity_ids:
                es=[e for e in self.p.events if e.activity_id==aid]
                for day in self.c.ds:
                    nmax=len(es)
                    if nmax<2: continue
                    n=m.new_int_var(0,nmax,f'q2:actcnt:{aid}:{day}')
                    m.add(n==sum(self.c.on_day[e.id,day] for e in es))
                    upper=nmax*(nmax-1)//2
                    pair=m.new_int_var(0,upper,f'q2:actpairs:{aid}:{day}')
                    m.add_element(n,[k*(k-1)//2 for k in range(nmax+1)],pair)
                    terms.append(pair);limit+=upper
            return sum(terms),limit
        if isinstance(metric,ResourceIdle):
            pieces=[self._person_idle(rid,day) for rid in metric.resource_ids for day in self.c.ds]
            return sum(x for x,_ in pieces),sum(u for _,u in pieces)
        if isinstance(metric,DailySpread):
            terms=[];limit=0
            for rid in metric.resource_ids:
                values=[self._staff_load(rid,day) for day in metric.day_ids]
                maxbound=max((ub for _,ub in values),default=0)
                if maxbound<=0:continue
                mx=m.new_int_var(0,maxbound,f'q2:spreadmax:{rid}')
                mn=m.new_int_var(0,maxbound,f'q2:spreadmin:{rid}')
                m.add_max_equality(mx,[v for v,_ in values]);m.add_min_equality(mn,[v for v,_ in values])
                spread=m.new_int_var(0,maxbound,f'q2:spread:{rid}')
                m.add(spread==mx-mn);terms.append(spread);limit+=maxbound
            return sum(terms),limit
        if isinstance(metric,TaggedPlacement):
            total=[]
            tagset=set(metric.tags)
            for eid in metric.event_ids:
                e=self.by_event[eid]
                for d in self.c.domains[eid]:
                    bell=self.by_window[d.window_id].bell_id
                    if any(w.day_id==d.day and w.bell_id==bell and tagset.intersection(w.tags) and
                           w.start_minute<d.end and d.start<w.end_minute for w in self.p.windows):
                        total.append(self.c.x[eid,d.window_id])
            return sum(total),len(metric.event_ids)
        if isinstance(metric,LocationChanges):
            pieces=[self._switches(rid,day) for rid in metric.resource_ids for day in self.c.ds]
            return sum(x for x,_ in pieces),sum(u for _,u in pieces)
        if isinstance(metric,UnmetRequests):
            by_request={q.id:q for q in self.p.participation_requests}
            parts=[];limit=0
            for req_id in metric.request_ids:
                req=by_request[req_id]
                missing=m.new_int_var(0,req.min_select,f'q2:unmet:{req_id}')
                enroll=sum(self.c.en[req.id,oid] for oid in req.eligible_offering_ids)
                m.add_max_equality(missing,[req.min_select-enroll,0])
                parts.append(missing);limit+=req.min_select
            return sum(parts),limit
        raise Q2Unsupported(f'Unimplemented quality metric: {metric.kind}')

    def build(self):
        tiers={2:[],3:[],4:[]}; bounds={2:0,3:0,4:0}
        for metric in self.policy.metrics:
            term,bound=self.metric_expression(metric)
            weighted_bound=bound*metric.weight
            bounds[metric.tier]+=weighted_bound
            if bounds[metric.tier]>=2**54:
                raise Q2Unsupported('Quality objective integer bound exceeds prototype safety limit')
            tiers[metric.tier].append(metric.weight*term)
        objectives={}
        for tier in (2,3,4):
            objectives[tier]=self.m.new_int_var(0,bounds[tier],f'q2:tier:{tier}')
            self.m.add(objectives[tier]==sum(tiers[tier]))
        return objectives




class ObjectiveCompilerV2(ObjectiveCompiler):
    """New Q3 semantics are compiled separately from the independent scorer."""

    def _protected_idle(self,rid,day,breaks):
        x=self._starts(rid,day)
        if len(x)<2:return self.m.new_constant(0),0
        low=min(d.absolute_start for _,d,_ in x)
        high=max(d.absolute_end for _,d,_ in x)
        if high<=low:return self.m.new_constant(0),0
        any_on=self._boolean((v for _,_,v in x),f'q3:any:{rid}:{day}')
        starts=[];ends=[]
        for ix,(_,d,v) in enumerate(x):
            s=self.m.new_int_var(low,high+1,f'q3:begin:{rid}:{day}:{ix}')
            e=self.m.new_int_var(low-1,high,f'q3:finish:{rid}:{day}:{ix}')
            self.m.add(s==d.absolute_start*v+(high+1)*(1-v))
            self.m.add(e==d.absolute_end*v+(low-1)*(1-v))
            starts.append(s);ends.append(e)
        first=self.m.new_int_var(low,high+1,f'q3:first:{rid}:{day}')
        last=self.m.new_int_var(low-1,high,f'q3:last:{rid}:{day}')
        self.m.add_min_equality(first,starts)
        self.m.add_max_equality(last,ends)
        gross=self.m.new_int_var(0,high-low,f'q3:grossidle:{rid}:{day}')
        busy=sum((d.absolute_end-d.absolute_start)*v for _,d,v in x)
        self.m.add(gross==last-first-busy).only_enforce_if(any_on)
        self.m.add(gross==0).only_enforce_if(any_on.Not())
        excluded=[]
        anchor=self.c.ds[day].ordinal*1440
        for idx,br in enumerate(breaks):
            a=anchor+br.start_minute;b=anchor+br.end_minute
            start_clamp=self.m.new_int_var(min(a,low),max(a,high+1),f'q3:brstart:{rid}:{day}:{idx}')
            end_clamp=self.m.new_int_var(min(b,low-1),max(b,high),f'q3:brend:{rid}:{day}:{idx}')
            self.m.add_max_equality(start_clamp,[first,a])
            self.m.add_min_equality(end_clamp,[last,b])
            within=self.m.new_int_var(0,b-a,f'q3:brspan:{rid}:{day}:{idx}')
            self.m.add_max_equality(within,[end_clamp-start_clamp,0])
            scheduled_overlap=sum(max(0,min(d.absolute_end,b)-max(d.absolute_start,a))*v for _,d,v in x)
            gap_part=self.m.new_int_var(0,b-a,f'q3:unoccupiedbreak:{rid}:{day}:{idx}')
            self.m.add(gap_part==within-scheduled_overlap)
            excluded.append(gap_part)
        penalty=self.m.new_int_var(0,high-low,f'q3:protected_idle:{rid}:{day}')
        self.m.add(penalty==gross-sum(excluded))
        return penalty,high-low

    def metric_expression(self,metric):
        if isinstance(metric,ProtectedIdle):
            per={}
            for b in metric.protected_breaks:
                per.setdefault((b.resource_id,b.day_id),[]).append(b)
            pieces=[self._protected_idle(rid,day,per.get((rid,day),[]))
                    for rid in metric.resource_ids for day in self.c.ds]
            return sum(x for x,_ in pieces),sum(b for _,b in pieces)
        if isinstance(metric,TargetLoadDeviation):
            pieces=[];bound=0
            for t in metric.targets:
                load,max_load=self._staff_load(t.resource_id,t.day_id)
                b=max(max_load,t.target_minutes)
                diff=self.m.new_int_var(0,b,f'q3:deviation:{t.resource_id}:{t.day_id}')
                self.m.add_abs_equality(diff,load-t.target_minutes)
                pieces.append(diff);bound+=b
            return sum(pieces),bound
        return super().metric_expression(metric)


def optimise_v2(problem: CoreProblem | dict, policy: QualityPolicyV2 | dict,
             options: Q2Options | dict | None = None) -> Q2Result:
    """Lexicographic Q2 minimisation. No schema edits, repair or publication."""
    t0=perf_counter();result=Q3Result(status='ERROR')
    def done():
        result.total_ms=round((perf_counter()-t0)*1000,3)
        return result
    try:
        p=CoreProblem.model_validate_json(json.dumps(problem.model_dump(mode='json') if isinstance(problem,CoreProblem) else problem,allow_nan=False),strict=True)
        pol=QualityPolicyV2.model_validate_json(json.dumps(policy.model_dump(mode='json') if isinstance(policy,QualityPolicyV2) else policy,allow_nan=False),strict=True)
        opts=Q2Options.model_validate_json(json.dumps(options.model_dump(mode='json') if isinstance(options,Q2Options) else (options or {})),strict=True)
        issues=core_problem_errors(p)
        if issues:
            result.status='INVALID_INPUT';result.findings=[f'{x.code}: {x.detail}' for x in issues];return done()
        result.model_sha256=digest(p);result.policy_sha256=digest(pol)
        if pol.model_sha256!=result.model_sha256:raise ValueError('Q1 policy snapshot does not match problem')
        verify_q3_policy(p,pol)
        if p.solve_config.mode!='FEASIBILITY' or p.baseline_solution_id:
            raise Q2Unsupported('Q3 requires a standalone C1 FEASIBILITY input, not a repair or joint solve')
        if p.solve_config.deterministic and opts.workers!=1:
            raise Q2Unsupported('Deterministic Q3 profile requires one worker')
        uncovered=[x.id for x in p.constraints if x.enabled and x.strength=='SOFT']
        uncovered+= [x.id for x in p.objectives]
        covered={rid for metric in pol.metrics if isinstance(metric,UnmetRequests) for rid in metric.request_ids}
        uncovered+=[x.id for x in p.participation_requests if x.strength=='SOFT' and x.id not in covered]
        if uncovered:raise Q2Unsupported('Unscored requirements: '+', '.join(uncovered))
        c=Compiler(p).compile()
        objective=ObjectiveCompilerV2(p,pol,c).build()
        error=c.m.validate()
        if error:result.findings=[f'COMPILED_MODEL_INVALID: {error}'];return done()
    except ContextMissing as exc:
        result.status='UNSUPPORTED';result.findings=[str(exc)];return done()
    except Q2Unsupported as exc:
        result.status='UNSUPPORTED';result.findings=[str(exc)];return done()
    except UnsupportedInput as exc:
        result.status='UNSUPPORTED';result.findings=[f'{exc.code}: {exc.detail}'];return done()
    except (ValidationError,ValueError,TypeError,KeyError) as exc:
        result.status='INVALID_INPUT';result.findings=[f'{type(exc).__name__}: {exc}'];return done()
    except Exception as exc:
        result.status='ERROR';result.findings=[f'COMPILATION_ERROR: {type(exc).__name__}: {exc}'];return done()
    last_quality=None
    try:
        for tier in (2,3,4):
            remaining=opts.max_time_seconds-(perf_counter()-t0)
            if remaining<=0:
                result.quality_optimality='NOT_PROVEN'
                result.status='FEASIBLE' if result.candidate else 'UNKNOWN'
                result.findings.append('Search time exhausted before completing all tiers')
                break
            c.m.minimize(objective[tier])
            engine=cp_model.CpSolver();engine.parameters.max_time_in_seconds=remaining
            engine.parameters.num_search_workers=opts.workers
            engine.parameters.random_seed=p.solve_config.random_seed
            before=perf_counter();status=engine.solve(c.m);elapsed=perf_counter()-before
            result.solver_status=engine.status_name(status)
            stage=StageResult(tier=tier,solver_status=result.solver_status,wall_seconds=round(elapsed,3))
            if status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
                candidate=c.extract(engine,result.model_sha256)
                checked=review_core(p,candidate)
                if checked.result!='CANDIDATE_HARD_VALIDATED':
                    result.status='ERROR';result.independent_validation='FAILED'
                    result.candidate=None;result.quality=None
                    result.findings.append('SOLVER_VALIDATOR_DISAGREEMENT; candidate withheld')
                    return done()
                qscore=score_v2(p,candidate,pol)
                if qscore.status!='SCORED' or qscore.hard_validation!='PASSED':
                    result.status='ERROR';result.candidate=None;result.quality=None
                    result.findings.append('Q1_INDEPENDENT_SCORE_UNAVAILABLE; candidate withheld')
                    return done()
                exact=int(round(engine.objective_value))
                if abs(engine.objective_value-exact)>1e-6 or qscore.tier_penalties[tier]!=exact:
                    result.status='ERROR';result.candidate=None;result.quality=None
                    result.findings.append(f'OBJECTIVE_SCORE_DISAGREEMENT: tier {tier} compiled {engine.objective_value}; Q1 {qscore.tier_penalties[tier]}')
                    return done()
                for previous in result.stages:
                    if previous.proven_optimal and qscore.tier_penalties[previous.tier]!=previous.objective_value:
                        result.status='ERROR';result.candidate=None;result.quality=None
                        result.findings.append('Earlier lexicographic tier changed despite bound; candidate withheld')
                        return done()
                result.status='FEASIBLE';result.candidate=candidate
                result.quality=qscore;result.independent_validation='PASSED'
                stage.objective_value=exact;stage.proven_optimal=status==cp_model.OPTIMAL
                result.stages.append(stage)
                if not stage.proven_optimal:
                    result.quality_optimality='NOT_PROVEN'
                    result.findings.append(f'Tier {tier} has a valid incumbent, but optimality is not proved')
                    break
                c.m.add(objective[tier]==exact)
                last_quality=qscore
            elif status==cp_model.INFEASIBLE:
                if result.candidate is None:
                    result.status='INFEASIBLE';result.findings.append('No feasible schedule exists for supported C1 hard rules')
                else:
                    result.status='ERROR';result.findings.append('Previously proved optimum rendered later tier infeasible')
                result.stages.append(stage);break
            elif status==cp_model.UNKNOWN:
                result.status='FEASIBLE' if result.candidate else 'UNKNOWN'
                result.quality_optimality='NOT_PROVEN'
                result.stages.append(stage);result.findings.append('Search unresolved within time budget')
                break
            else:
                result.status='ERROR';result.stages.append(stage)
                result.findings.append(f'Invalid or unexpected CP-SAT status in tier {tier}: {result.solver_status}')
                break
        else:
            result.quality_optimality='PROVEN'
    except Exception as exc:
        result.status='ERROR';result.findings.append(f'Q3_RUNTIME_ERROR: {type(exc).__name__}: {exc}')
        result.candidate=None;result.quality=None;result.independent_validation='NOT_RUN'
    return done()


# US spelling alias for callers
optimize_v2=optimise_v2
