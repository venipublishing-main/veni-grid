"""O1: actual CP-SAT learner-option design from demand, not a supplied witness.

Two honest, independently verified solver profiles:
* SINGLE_FAMILY_BLOCK: a family is assigned to one common block; graph colouring
  decides that block. Sections are then constructed at mathematically minimum
  count for each family. Very scalable, but a profile restriction, not parity.
* FLEXIBLE_SECTIONS: each learner request chooses a block; a family may create
  sections in several blocks. CP-SAT decides family/block counts and assignments.
  Teacher/room/lesson timetabling is intentionally outside this O1 profile.

AUTO first searches the single-family-block profile and falls back to the
flexible profile if the restricted graph is proved infeasible. A fast candidate
is never called globally optimal for the more general flexible model.

This module never imports/changes school timetables or publishes a result.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from time import perf_counter
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from ortools.sat.python import cp_model

from veni_grid_contract.option_design import (
    OptionDesignProblem, OptionDesignWitness, DesignedOffering,
    ChoiceAllocation, option_errors,
)

class SolveOptions(BaseModel):
    model_config = ConfigDict(extra='forbid')
    strategy: Literal['AUTO', 'SINGLE_FAMILY_BLOCK', 'FLEXIBLE_SECTIONS'] = 'AUTO'
    max_time_seconds: float = Field(default=30, ge=0, le=300)
    max_flexible_requests: int = Field(default=2500, ge=1, le=50_000)
    random_seed: int = Field(default=1, ge=0, le=2**31-1)
    workers: int = Field(default=1, ge=1, le=8)
    minimise_sections: bool = True

class OptionSolveOptions(SolveOptions):
    pass

class OptionSolveResult(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: Literal['0.1.0'] = '0.1.0'
    status: Literal['FEASIBLE', 'INFEASIBLE', 'UNKNOWN', 'INVALID_INPUT', 'UNSUPPORTED', 'ERROR']
    profile: Literal['SINGLE_FAMILY_BLOCK', 'FLEXIBLE_SECTIONS', 'NONE'] = 'NONE'
    # Scope of an infeasibility proof is explicit.  A restricted-graph proof
    # must never be used to claim that the flexible O1 problem is impossible.
    proof_scope: Literal['FULL_O1', 'SINGLE_BLOCK_ONLY', 'NONE'] = 'NONE'
    block_optimality_scope: Literal['FULL_O1', 'SINGLE_BLOCK_ONLY', 'NONE'] = 'NONE'
    witness: OptionDesignWitness | None = None
    independent_validation: Literal['PASSED', 'FAILED', 'NOT_RUN'] = 'NOT_RUN'
    block_count: int | None = None
    offering_count: int | None = None
    request_count: int | None = None
    allocations: int | None = None
    min_block_count_proven: bool = False
    min_section_count_proven: bool = False
    solver_status: str = 'NOT_RUN'
    stages: list[dict] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    elapsed_ms: float = 0.0
    source_origin: Literal['DEMAND_ONLY'] = 'DEMAND_ONLY'
    generated_sections: bool = False
    staffing_and_rooms: Literal['NOT_MODELLED'] = 'NOT_MODELLED'
    lesson_placement: Literal['NOT_MODELLED'] = 'NOT_MODELLED'
    quality_optimality: Literal['NOT_CLAIMED'] = 'NOT_CLAIMED'
    publication: Literal['NOT_GRANTED'] = 'NOT_GRANTED'


def _cp_solver(options: SolveOptions, remaining: float) -> cp_model.CpSolver:
    engine = cp_model.CpSolver()
    engine.parameters.max_time_in_seconds = max(0.001, remaining)
    engine.parameters.num_search_workers = options.workers
    engine.parameters.random_seed = options.random_seed
    return engine


def _preflight(problem: OptionDesignProblem):
    errors = []
    participant_ids=set(problem.participant_ids)
    families={f.id:f for f in problem.families}
    if len(participant_ids)!=len(problem.participant_ids):errors.append('Duplicate participant IDs')
    if len(families)!=len(problem.families):errors.append('Duplicate family IDs')
    if len({r.id for r in problem.requests})!=len(problem.requests):errors.append('Duplicate request IDs')
    pairs=set();family_counts=Counter();per_learner=Counter()
    for r in problem.requests:
        if r.participant_id not in participant_ids:errors.append(f'Unknown participant for {r.id}')
        if r.family_id not in families:errors.append(f'Unknown subject family for {r.id}')
        key=(r.participant_id,r.family_id)
        if key in pairs:errors.append(f'Duplicate participant/family request {key}')
        pairs.add(key)
        family_counts[r.family_id]+=1
        per_learner[r.participant_id]+=1
    if any(n>problem.max_blocks for n in per_learner.values()):
        return errors, ['A learner requests more distinct subjects than available option blocks']
    imposs=[]
    for fid,n in family_counts.items():
        f=families.get(fid)
        if f is None:continue
        if not any(k*f.min_members<=n<=k*f.max_members for k in range(1,f.max_sections+1)):
            imposs.append(f'Family {fid} demand {n} cannot fit section sizes/count bounds')
    return errors,imposs


def _section_sizes(n:int, count:int, minimum:int,maximum:int) -> list[int]:
    if count<1 or not (minimum*count<=n<=maximum*count):
        raise ValueError(f'Cannot divide {n} learners into {count} sections of [{minimum},{maximum}]')
    low,extra=divmod(n,count)
    sizes=[low+1]*extra+[low]*(count-extra)
    if min(sizes)<minimum or max(sizes)>maximum:raise ValueError('Section balancing failed')
    return sizes


def _to_witness(p:OptionDesignProblem, assignment:dict[str,dict[int,list[str]]], section_counts:dict[tuple[str,int],int]) -> OptionDesignWitness:
    # Deterministic canonical block identifiers; no original C0 solution loaded.
    active=sorted({b for by_block in assignment.values() for b,reqs in by_block.items() if reqs})
    remap={original:i for i,original in enumerate(active)}
    block_ids=[f'block:B{i:02d}' for i in range(len(active))]
    requests={r.id:r for r in p.requests}
    catalog={f.id:f for f in p.families}
    offerings=[];allocs=[]
    for fid in sorted(assignment):
        fam=catalog[fid]
        for oldblock,req_ids in sorted(assignment[fid].items()):
            if not req_ids:continue
            count=section_counts[fid,oldblock]
            sizes=_section_sizes(len(req_ids),count,fam.min_members,fam.max_members)
            req_ids=sorted(req_ids,key=lambda rid:(requests[rid].participant_id,rid))
            cursor=0
            for ix,size in enumerate(sizes):
                oid=f'offering:F{sorted(catalog).index(fid):03d}B{remap[oldblock]:02d}S{ix:03d}'
                offerings.append(DesignedOffering(id=oid,family_id=fid,block_id=block_ids[remap[oldblock]]))
                for rid in req_ids[cursor:cursor+size]:
                    allocs.append(ChoiceAllocation(request_id=rid,offering_id=oid))
                cursor+=size
    allocs.sort(key=lambda a:a.request_id)
    return OptionDesignWitness(problem_id=p.problem_id,model_version=p.model_version,
                               block_ids=block_ids,offerings=offerings,allocations=allocs)


def _single(p:OptionDesignProblem,opts:SolveOptions,deadline:float,result:OptionSolveResult):
    fids=sorted({r.family_id for r in p.requests})
    counts=Counter(r.family_id for r in p.requests)
    byperson=defaultdict(set)
    for r in p.requests:byperson[r.participant_id].add(r.family_id)
    pairs=set()
    for fs in byperson.values():
        seq=sorted(fs)
        for i,a in enumerate(seq):
            for b in seq[i+1:]:pairs.add((a,b))
    m=cp_model.CpModel();nb=p.max_blocks
    color={(f,b):m.new_bool_var(f'colour:{i}:{b}') for i,f in enumerate(fids) for b in range(nb)}
    used=[m.new_bool_var(f'block-used:{b}') for b in range(nb)]
    for f in fids:m.add(sum(color[f,b] for b in range(nb))==1)
    for a,b in sorted(pairs):
        for block in range(nb):m.add(color[a,block]+color[b,block]<=1)
    for block in range(nb):
        placed=sum(color[f,block] for f in fids)
        m.add(placed>=used[block])
        m.add(placed<=len(fids)*used[block])
    for block in range(nb-1):m.add(used[block]>=used[block+1])
    # Permuting block IDs has no effect: canonicalise the first requested family.
    m.add(color[fids[0],0]==1)
    m.minimize(sum(used))
    remaining=deadline-perf_counter()
    if remaining<=0:return None,'UNKNOWN',False,None
    solver=_cp_solver(opts,remaining)
    status=solver.solve(m)
    name=solver.status_name(status)
    result.stages.append({'profile':'SINGLE_FAMILY_BLOCK','objective':'MIN_BLOCKS',
       'solver_status':name,'proven':status==cp_model.OPTIMAL})
    if status==cp_model.INFEASIBLE:return None,'INFEASIBLE',True,name
    if status not in (cp_model.FEASIBLE,cp_model.OPTIMAL):return None,'UNKNOWN',False,name
    allocation=defaultdict(lambda:defaultdict(list))
    for r in p.requests:
        for b in range(nb):
            if solver.value(color[r.family_id,b]):allocation[r.family_id][b].append(r.id);break
    section_counts={}
    for f,byblock in allocation.items():
        fam=next(x for x in p.families if x.id==f)
        for block,reqs in byblock.items():
            n=len(reqs)
            section_counts[f,block]=(n+fam.max_members-1)//fam.max_members
    return _to_witness(p,allocation,section_counts),'FEASIBLE',status==cp_model.OPTIMAL,name


def _flexible(p:OptionDesignProblem,opts:SolveOptions,deadline:float,result:OptionSolveResult):
    if len(p.requests)>opts.max_flexible_requests:
        return None,'UNSUPPORTED',False,False,'NOT_RUN',
        
    nblocks=p.max_blocks;m=cp_model.CpModel()
    requests=sorted(p.requests,key=lambda q:q.id)
    persons=defaultdict(list);famreq=defaultdict(list)
    for index,r in enumerate(requests):
        persons[r.participant_id].append(index)
        famreq[r.family_id].append(index)
    byfamily={f.id:f for f in p.families}
    x={(r,b):m.new_bool_var(f'req:{r}:b{b}') for r in range(len(requests)) for b in range(nblocks)}
    for r in range(len(requests)):m.add(sum(x[r,b] for b in range(nblocks))==1)
    used=[m.new_bool_var(f'used:b{b}') for b in range(nblocks)]
    for b in range(nblocks):
        for person,rids in persons.items():m.add(sum(x[r,b] for r in rids)<=1)
        total=sum(x[r,b] for r in range(len(requests)))
        m.add(total>=used[b]);m.add(total<=len(requests)*used[b])
    for b in range(nblocks-1):m.add(used[b]>=used[b+1])
    sec={}
    for fid,rids in famreq.items():
        f=byfamily[fid]
        for b in range(nblocks):
            var=m.new_int_var(0,f.max_sections,f'sections:{fid}:{b}')
            sec[fid,b]=var
            count=sum(x[i,b] for i in rids)
            m.add(f.min_members*var<=count)
            m.add(count<=f.max_members*var)
        m.add(sum(sec[fid,b] for b in range(nblocks))<=f.max_sections)
    results=[]
    def snapshot(solver):
        assignment=defaultdict(lambda:defaultdict(list))
        countmap={}
        for i,r in enumerate(requests):
            for b in range(nblocks):
                if solver.value(x[i,b]):assignment[r.family_id][b].append(r.id);break
        for f,bl in assignment.items():
            for b,rs in bl.items():countmap[f,b]=solver.value(sec[f,b])
        return _to_witness(p,assignment,countmap)
    remaining=deadline-perf_counter()
    if remaining<=0:return None,'UNKNOWN',False,False,'NOT_RUN'
    m.minimize(sum(used));s=_cp_solver(opts,remaining)
    status=s.solve(m);name=s.status_name(status)
    result.stages.append({'profile':'FLEXIBLE_SECTIONS','objective':'MIN_BLOCKS',
        'solver_status':name,'proven':status==cp_model.OPTIMAL})
    if status==cp_model.INFEASIBLE:return None,'INFEASIBLE',True,False,name
    if status not in (cp_model.OPTIMAL,cp_model.FEASIBLE):return None,'UNKNOWN',False,False,name
    w=snapshot(s);blockproof=status==cp_model.OPTIMAL
    if not blockproof or not opts.minimise_sections:
        return w,'FEASIBLE',blockproof,False,name
    m.add(sum(used)==int(round(s.objective_value)))
    m.minimize(sum(sec.values()))
    remaining=deadline-perf_counter()
    if remaining<=0:return w,'FEASIBLE',True,False,name
    t=_cp_solver(opts,remaining);tstatus=t.solve(m);tname=t.status_name(tstatus)
    result.stages.append({'profile':'FLEXIBLE_SECTIONS','objective':'MIN_SECTIONS',
        'solver_status':tname,'proven':tstatus==cp_model.OPTIMAL})
    if tstatus in (cp_model.FEASIBLE,cp_model.OPTIMAL):
        return snapshot(t),'FEASIBLE',True,tstatus==cp_model.OPTIMAL,tname
    return w,'FEASIBLE',True,False,name


def solve_options(problem:OptionDesignProblem|dict,options:OptionSolveOptions|dict|None=None)->OptionSolveResult:
    """Generate a complete option plan from requests; independent check is mandatory."""
    start=perf_counter();out=OptionSolveResult(status='ERROR')
    def finish():
        out.elapsed_ms=round((perf_counter()-start)*1000,3)
        return out
    try:
        p=OptionDesignProblem.model_validate(problem.model_dump(mode='json') if isinstance(problem,OptionDesignProblem) else problem)
        opts=OptionSolveOptions.model_validate(options.model_dump(mode='json') if isinstance(options,OptionSolveOptions) else options or {})
        errors,impossible=_preflight(p)
        if errors:
            out.status='INVALID_INPUT';out.findings=errors[:20];return finish()
        if impossible:
            out.status='INFEASIBLE';out.proof_scope='FULL_O1';out.findings=impossible;return finish()
        out.request_count=len(p.requests)
        if opts.max_time_seconds<=0:
            out.status='UNKNOWN';out.findings=['Search budget is zero; no proof or candidate'];return finish()
        deadline=start+opts.max_time_seconds
        if opts.strategy in ('SINGLE_FAMILY_BLOCK','AUTO'):
            w,status,proven,name=_single(p,opts,deadline,out)
            if w is not None:
                out.profile='SINGLE_FAMILY_BLOCK';out.status='FEASIBLE'
                out.min_block_count_proven=proven
                out.block_optimality_scope='SINGLE_BLOCK_ONLY' if proven else 'NONE'
                out.min_section_count_proven=True # counts are minimum for each fixed family
                out.solver_status=name or 'UNKNOWN'
            elif status=='INFEASIBLE' and opts.strategy=='SINGLE_FAMILY_BLOCK':
                out.status='INFEASIBLE';out.profile='SINGLE_FAMILY_BLOCK'
                out.proof_scope='SINGLE_BLOCK_ONLY';out.solver_status=name or status
                out.findings=['Single block per family impossible; flexible sections may still work']
                return finish()
            elif opts.strategy=='AUTO' and status=='INFEASIBLE':
                out.findings.append('Single-block family graph proved infeasible; trying multi-block section design')
            elif opts.strategy=='SINGLE_FAMILY_BLOCK':
                out.status='UNKNOWN';out.solver_status=name or status
                return finish()
        if out.witness is None and out.status!='FEASIBLE' and opts.strategy in ('FLEXIBLE_SECTIONS','AUTO'):
            w,status,blockproof,sectionsproof,name=_flexible(p,opts,deadline,out)
            if status=='UNSUPPORTED':
                out.status='UNSUPPORTED';out.findings.append(f'Flexible request limit {opts.max_flexible_requests} exceeded')
                return finish()
            if w is None:
                out.status=status;out.profile='FLEXIBLE_SECTIONS';out.solver_status=name or status
                if status=='INFEASIBLE':out.proof_scope='FULL_O1'
                return finish()
            out.status='FEASIBLE';out.profile='FLEXIBLE_SECTIONS'
            out.min_block_count_proven=blockproof;out.min_section_count_proven=sectionsproof
            out.block_optimality_scope='FULL_O1' if blockproof else 'NONE'
            out.solver_status=name or 'UNKNOWN'
        if w is None:
            out.status='UNKNOWN';out.findings.append('No candidate found within time limit')
            return finish()
        findings=option_errors(p,w)
        if findings:
            out.status='ERROR';out.independent_validation='FAILED';out.findings=[f'{x.code}: {x.detail}' for x in findings[:25]]
            return finish()
        out.witness=w;out.independent_validation='PASSED';out.generated_sections=True
        out.block_count=len(w.block_ids);out.offering_count=len(w.offerings)
        out.allocations=len(w.allocations)
        if out.profile=='SINGLE_FAMILY_BLOCK':
            out.findings.append('Single-block-per-family result; valid but global flexible block/section optimality NOT assessed')
        return finish()
    except (ValidationError,ValueError,TypeError) as e:
        out.status='INVALID_INPUT';out.findings=[f'{type(e).__name__}: {e}'];return finish()
    except Exception as e:
        out.status='ERROR';out.findings=[f'{type(e).__name__}: {e}'];return finish()
