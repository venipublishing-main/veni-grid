"""C4 research profile: flexible, multi-occurrence option replanning with true C2 confirmation.

No authoritative acceptance/persistence/publication. This module never modifies
an accepted source. The temporary ACCEPTED reference is solely an adapter
compatibility claim, deliberately NOT a real acceptance or permission.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from itertools import combinations
from math import ceil
from time import perf_counter
from typing import Literal

from ortools.sat.python import cp_model
from pydantic import Field, ValidationError

from veni_grid_contract.primitives import ContractModel
from veni_grid_contract.handoff_common import fingerprint, snapshot_ref, stable_id
from veni_grid_contract.option_design import (OptionDesignWitness, DesignedOffering,
    ChoiceAllocation, option_errors)
from veni_grid_contract.options_handoff import AcceptedOptions
from .c2 import C2Input, C2BlockWindow, C2Result, solve_c2


class C4Options(ContractModel):
    max_time_seconds: float = Field(default=30, ge=0, le=180)
    placement_seconds: float = Field(default=7, gt=0, le=60)
    max_candidates: int = Field(default=12, ge=1, le=40)
    max_requests: int = Field(default=120, ge=1, le=2000)
    max_families: int = Field(default=8, ge=1, le=20)
    max_sections: int = Field(default=32, ge=1, le=300)


class C4Input(ContractModel):
    version: Literal['0.1.0'] = '0.1.0'
    current: C2Input
    proposed_block_windows: list[C2BlockWindow] = Field(min_length=1)
    options: C4Options = Field(default_factory=C4Options)


class FamilyDiff(ContractModel):
    family_id: str
    subject: str
    before_blocks: list[str]
    after_blocks: list[str]
    before_sections: int
    after_sections: int
    changed_requests: int


class C4Review(ContractModel):
    version: Literal['0.1.0'] = '0.1.0'
    preview_id: str
    source_revision: int
    source_sha256: str
    proposed_o1_sha256: str
    proposed_c2_candidate_sha256: str
    changed_request_ids: list[str]
    before_section_count: int
    after_section_count: int
    after_teaching_events: int
    preserved_compulsory_requests: int
    changes: list[FamilyDiff]
    independent_o1: Literal['PASSED'] = 'PASSED'
    independent_c2: Literal['PASSED'] = 'PASSED'
    authority: Literal['SIMULATED_IN_MEMORY_ONLY'] = 'SIMULATED_IN_MEMORY_ONLY'
    approval: Literal['REQUIRES_AUTHENTICATED_REVIEW'] = 'REQUIRES_AUTHENTICATED_REVIEW'
    saved: Literal['NO'] = 'NO'
    publication: Literal['NOT_GRANTED'] = 'NOT_GRANTED'


class C4Result(ContractModel):
    version: Literal['0.1.0'] = '0.1.0'
    status: Literal['PROPOSED_VALIDATED', 'ALREADY_FEASIBLE', 'RESOURCE_RESTRICTED_INFEASIBLE',
                    'UNKNOWN', 'UNSUPPORTED', 'INVALID_INPUT', 'ERROR']
    proof_scope: Literal['NONE','RESTRICTED_C4_FLEXIBLE_TEACHING'] = 'NONE'
    old_c2_status: str = 'NOT_RUN'
    old_c2_findings: list[str] = Field(default_factory=list)
    source_sha256: str | None = None
    source_unchanged: bool = False
    proposed_o1: OptionDesignWitness | None = None
    preview_c2: C2Result | None = None
    review: C4Review | None = None
    candidate_attempts: int = 0
    findings: list[str] = Field(default_factory=list)
    acceptance: Literal['NOT_GRANTED'] = 'NOT_GRANTED'
    publication: Literal['NOT_GRANTED'] = 'NOT_GRANTED'
    other_schedules: Literal['NOT_READ_OR_CHANGED'] = 'NOT_READ_OR_CHANGED'


def _build_witness(demand, requests, x_choice: dict[str,str], section_choice: dict[tuple[str,str],int]):
    """Use original selected block IDs without renumbering explicit time slots."""
    by_pair = defaultdict(list)
    for rq in requests:
        by_pair[(rq.family_id, x_choice[rq.id])].append(rq)
    family = {f.id:f for f in demand.families}
    offerings=[]; alloc=[]; active=set()
    for (fid,block), chosen in sorted(by_pair.items()):
        n=len(chosen);count=section_choice[fid,block];f=family[fid]
        if not (count>0 and count*f.min_members<=n<=count*f.max_members):
            raise ValueError('C4 invalid section count extracted from solver')
        active.add(block)
        avg,extra=divmod(n,count)
        sizes=[avg+1]*extra+[avg]*(count-extra)
        ordered=sorted(chosen,key=lambda r:(r.participant_id,r.id))
        ix=0
        for j,size in enumerate(sizes):
            oid=stable_id('c4section',demand.problem_id,fid,block,str(j))
            offerings.append(DesignedOffering(id=oid,family_id=fid,block_id=block))
            for rq in ordered[ix:ix+size]:alloc.append(ChoiceAllocation(request_id=rq.id,offering_id=oid))
            ix+=size
    return OptionDesignWitness(problem_id=demand.problem_id,model_version=demand.model_version,
        block_ids=sorted(active),offerings=offerings,allocations=sorted(alloc,key=lambda a:a.request_id))


def _request_blocks(demand, witness):
    sections={o.id:o for o in witness.offerings}
    return {a.request_id:sections[a.offering_id].block_id for a in witness.allocations}


def _review(original, proposal, preview) -> C4Review:
    if preview.independent_hard_validation!='PASSED' or preview.candidate is None:
        raise ValueError('C4 review cannot certify an unchecked teaching plan')
    demand=original.source.demand
    oldblocks=_request_blocks(demand,original.source.plan)
    newblocks=_request_blocks(demand,proposal)
    if set(oldblocks)!=set(newblocks):raise ValueError('Choice requests were dropped or added')
    changed=sorted(rid for rid in oldblocks if oldblocks[rid]!=newblocks[rid])
    requests={r.id:r for r in demand.requests}
    fids={f.id:f.label for f in demand.families}
    oldof=defaultdict(list);newof=defaultdict(list)
    for o in original.source.plan.offerings:oldof[o.family_id].append(o.block_id)
    for o in proposal.offerings:newof[o.family_id].append(o.block_id)
    details=[]
    for fid in sorted(fids):
        details.append(FamilyDiff(family_id=fid,subject=fids[fid],
             before_blocks=sorted(set(oldof[fid])),after_blocks=sorted(set(newof[fid])),
             before_sections=len(oldof[fid]),after_sections=len(newof[fid]),
             changed_requests=sum(requests[rid].family_id==fid for rid in changed)))
    originalhash=fingerprint(original.source)
    outputhash=fingerprint(proposal)
    candidatehash=fingerprint(preview.candidate)
    return C4Review(preview_id=stable_id('c4preview', original.source_ref.schedule_id,
         str(original.source_ref.revision),originalhash,outputhash,candidatehash),
         source_revision=original.source_ref.revision,source_sha256=originalhash,
         proposed_o1_sha256=outputhash,proposed_c2_candidate_sha256=candidatehash,
         changed_request_ids=changed,before_section_count=len(original.source.plan.offerings),
         after_section_count=len(proposal.offerings),after_teaching_events=preview.event_count,
         preserved_compulsory_requests=len(newblocks),changes=details)


def review_errors(original: C2Input, proposal: OptionDesignWitness, preview: C2Result,
                  review: C4Review) -> list[str]:
    """Independent exact-content check. No role authority or persistent write."""
    findings=[]
    if option_errors(original.source.demand,proposal):findings.append('INVALID_OPTION_PLAN')
    if preview.independent_hard_validation!='PASSED' or preview.candidate is None:
        findings.append('UNVALIDATED_C2')
    else:
        from veni_grid_contract.conformance import review_core
        if preview.placement_problem is None or review_core(preview.placement_problem,preview.candidate).result!='CANDIDATE_HARD_VALIDATED':
            findings.append('INDEPENDENT_PLACEMENT_CHECK_FAILED')
    if findings:return findings
    expected=_review(original,proposal,preview)
    if expected!=review:findings.append('REVIEW_CONTENT_MISMATCH')
    if original.source_ref.content_sha256!=fingerprint(original.source):findings.append('SOURCE_STALE')
    return findings


def propose_c4(value: C4Input | dict) -> C4Result:
    result=C4Result(status='ERROR')
    try:
        inp=C4Input.model_validate(value.model_dump(mode='json') if isinstance(value,C4Input) else value)
        current=inp.current; demand=current.source.demand; opts=inp.options
        result.source_sha256=fingerprint(current.source)
        previous=solve_c2(current,time_limit_seconds=opts.placement_seconds)
        result.old_c2_status=previous.status
        result.old_c2_findings=list(previous.findings)
        if previous.status=='FEASIBLE':
            result.status='ALREADY_FEASIBLE';return result
        if previous.status!='INFEASIBLE' or previous.proof_scope!='FIXED_O1_C2':
            result.status='UNKNOWN' if previous.status=='UNKNOWN' else ('UNSUPPORTED' if previous.status=='UNSUPPORTED' else 'INVALID_INPUT')
            result.findings=['Original C2 must prove this fixed plan unteachable before exploring a replacement']
            return result
        problems=option_errors(demand,current.source.plan)
        if problems:
            result.status='INVALID_INPUT';result.findings=[f'{p.code}:{p.detail}' for p in problems];return result
        requests=sorted(demand.requests,key=lambda r:r.id)
        fams={f.id:f for f in demand.families};specs={f.family_id:f for f in current.target.family_teaching}
        if len(requests)>opts.max_requests or len(fams)>opts.max_families:
            result.status='UNSUPPORTED';result.findings=['C4 demand exceeds reviewed flexible search size'];return result
        if len(specs)!=len(current.target.family_teaching) or set(specs)!=set(fams):
            result.status='INVALID_INPUT';result.findings=['Missing/duplicate curriculum specification'];return result
        if any(c.valid_during is not None for c in current.target.credentials):
            result.status='UNSUPPORTED';result.findings=['C4 dated-qualification profile is not yet implemented'];return result
        # Candidate block identities correspond to explicit user-supplied domains, never invented slots.
        blocks=[f'block:B{i:02d}' for i in range(demand.max_blocks)]
        declared={(b.block_id,b.occurrence_key):b for b in inp.proposed_block_windows}
        if len(declared)!=len(inp.proposed_block_windows):
            result.status='INVALID_INPUT';result.findings=['Duplicate candidate block/occurrence domain'];return result
        wins={w.id:w for w in current.target.windows};days={d.id for d in current.target.days}
        for (block,key),binding in declared.items():
            if block not in blocks or not set(binding.candidate_start_ids)<=set(wins) or not set(binding.allowed_day_ids)<=days:
                result.status='INVALID_INPUT';result.findings=['Unknown proposed block, day or window'];return result
            if any(wins[w].day_id not in binding.allowed_day_ids for w in binding.candidate_start_ids):
                result.status='INVALID_INPUT';result.findings=['Candidate bell window lies outside permitted day'];return result
        original_blocks=_request_blocks(demand,current.source.plan)
        if set(original_blocks)!={r.id for r in requests}:
            result.status='INVALID_INPUT';result.findings=['Original allocations not complete'];return result
        resources={r.id:r for r in current.target.resources}
        credentials={(c.resource_id,c.competency) for c in current.target.credentials}
        allowed={};teachers={};rooms={};effmax={}
        for fid,f in fams.items():
            spec=specs[fid]
            keys=[o.key for o in spec.occurrences]
            if len(keys)!=len(set(keys)):
                result.status='INVALID_INPUT';result.findings=[f'Duplicate occurrence keys for {fid}'];return result
            allowed[fid]=[b for b in blocks if all((b,k) in declared for k in keys)]
            teachers[fid]={tid for tid in spec.teacher_ids if tid in resources and resources[tid].kind=='PERSON'
                           and 'TEACHER' in resources[tid].tags and (tid,spec.competency_code) in credentials}
            rooms[fid]={rid for rid in spec.room_ids if rid in resources and resources[rid].kind=='SPACE'
                        and resources[rid].sharing_mode=='EXCLUSIVE'
                        and set(spec.required_room_tags)<=set(resources[rid].tags)
                        and resources[rid].capacity is not None and resources[rid].capacity>=f.min_members}
            maxroom=max((resources[rid].capacity for rid in rooms[fid]),default=0)
            effmax[fid]=min(f.max_members,maxroom)
            if not allowed[fid]:
                result.status='UNSUPPORTED';result.findings=[f'No explicit complete occurrence windows for {fid}'];return result
            if not teachers[fid] or effmax[fid]<f.min_members:
                result.status='RESOURCE_RESTRICTED_INFEASIBLE'
                result.proof_scope='RESTRICTED_C4_FLEXIBLE_TEACHING'
                result.findings=[f'{fid}: no suitable qualified teacher or classroom under the supplied C4 resource set'];return result
        lower_bound_sections=sum(ceil(len([r for r in requests if r.family_id==fid])/effmax[fid]) for fid in fams)
        if lower_bound_sections>opts.max_sections:
            result.status='UNSUPPORTED'
            result.findings=[f'Minimum {lower_bound_sections} generated sections exceeds reviewed {opts.max_sections} section search guard']
            return result
        if opts.max_time_seconds==0:
            result.status='UNKNOWN';result.findings=['Zero planning time: no proof'];return result
        deadline=perf_counter()+opts.max_time_seconds
        model=cp_model.CpModel()
        x={(r.id,b):model.new_bool_var(f'choice:{ix}:{j}') for ix,r in enumerate(requests) for j,b in enumerate(blocks)}
        for r in requests:
            model.add(sum(x[r.id,b] for b in blocks)==1)
            for b in blocks:
                if b not in allowed[r.family_id]:model.add(x[r.id,b]==0)
        byperson=defaultdict(list);byfamily=defaultdict(list)
        for r in requests:
            byperson[r.participant_id].append(r.id)
            byfamily[r.family_id].append(r.id)
        for rid,ids in byperson.items():
            for b in blocks:model.add(sum(x[r,b] for r in ids)<=1)
        s={(fid,b):model.new_int_var(0,f.max_sections,f'sections:{fid}:{b}') for fid,f in fams.items() for b in blocks}
        for fid,f in fams.items():
            model.add(sum(s[fid,b] for b in blocks)<=f.max_sections)
            for b in blocks:
                count=sum(x[r,b] for r in byfamily[fid])
                model.add(f.min_members*s[fid,b]<=count)
                model.add(count<=effmax[fid]*s[fid,b])
                if b not in allowed[fid]:model.add(s[fid,b]==0)
        # Hall-type necessary section coverage for every subset of simultaneous subjects.
        # Fixed-supply feasibility is only a preflight: C2 still checks real dates and allocations.
        occs=sorted({o.key for spec in specs.values() for o in spec.occurrences})
        for b in blocks:
            for occ in occs:
                active=[fid for fid in sorted(fams) if occ in {o.key for o in specs[fid].occurrences} and b in allowed[fid]]
                for n in range(1,len(active)+1):
                    for subset in combinations(active,n):
                        ts=set().union(*(teachers[f] for f in subset))
                        rs=set().union(*(rooms[f] for f in subset))
                        model.add(sum(s[f,b] for f in subset)<=len(ts))
                        model.add(sum(s[f,b] for f in subset)<=len(rs))
        moves=sum(1-x[r.id,original_blocks[r.id]] for r in requests)
        max_total_sections=sum(f.max_sections for f in fams.values())
        model.minimize((max_total_sections+1)*moves+sum(s.values()))
        while result.candidate_attempts < opts.max_candidates:
            remaining=deadline-perf_counter()
            if remaining<=0:
                result.status='UNKNOWN';result.findings.append('Search budget exhausted before validated alternative');break
            engine=cp_model.CpSolver();engine.parameters.max_time_in_seconds=remaining
            engine.parameters.num_search_workers=1;engine.parameters.random_seed=7
            status=engine.solve(model)
            if status==cp_model.INFEASIBLE:
                result.status='RESOURCE_RESTRICTED_INFEASIBLE'
                result.proof_scope='RESTRICTED_C4_FLEXIBLE_TEACHING'
                result.findings.append('No more candidates within this bounded flexible-section model and C2-proved exclusions')
                break
            if status not in (cp_model.FEASIBLE,cp_model.OPTIMAL):
                result.status='UNKNOWN';result.findings.append('Option search unresolved; no impossibility proof');break
            choice={r.id:next(b for b in blocks if engine.value(x[r.id,b])) for r in requests}
            counts={(fid,b):engine.value(var) for (fid,b),var in s.items()}
            proposal=_build_witness(demand,requests,choice,counts)
            if len(proposal.offerings)>opts.max_sections:
                result.status='UNSUPPORTED'
                result.findings=[f'Candidate needs {len(proposal.offerings)} sections beyond reviewed {opts.max_sections} section cap']
                break
            errors=option_errors(demand,proposal)
            if errors:
                result.status='ERROR';result.findings=['INDEPENDENT_OPTION_CHECK_FAILED: '+', '.join(e.code for e in errors[:3])];break
            result.candidate_attempts+=1
            transient_source=AcceptedOptions(demand=demand,plan=proposal)
            # This required C2 adapter state is NOT trusted approval. It is in-memory only.
            transient_ref=snapshot_ref(transient_source,organisation_id=current.target.organisation_id,
                schedule_id=current.source_ref.schedule_id,revision=current.source_ref.revision+result.candidate_attempts,
                origin='GRID',state='ACCEPTED')
            tgt=current.target.model_copy(deep=True)
            needed={(o.block_id,occ.key) for o in proposal.offerings for occ in specs[o.family_id].occurrences}
            tgt.block_windows=[declared[k].model_copy(deep=True) for k in sorted(needed)]
            preview=solve_c2(C2Input(source_ref=transient_ref,source=transient_source,target=tgt),
                             time_limit_seconds=min(opts.placement_seconds,max(.001,deadline-perf_counter())))
            if preview.status=='FEASIBLE' and preview.independent_hard_validation=='PASSED':
                review=_review(current,proposal,preview)
                problems=review_errors(current,proposal,preview,review)
                if problems:
                    result.status='ERROR';result.findings=['REVIEW_VERIFICATION_FAILED: '+','.join(problems)];break
                result.status='PROPOSED_VALIDATED';result.proposed_o1=proposal
                result.preview_c2=preview;result.review=review
                result.findings=['Draft preview is independently validated, but not accepted, saved or publishable']
                break
            if preview.status!='INFEASIBLE' or preview.proof_scope!='FIXED_O1_C2':
                result.status='UNKNOWN' if preview.status=='UNKNOWN' else 'UNSUPPORTED'
                result.findings=[f'C2 preview {preview.status} is not a proved contradiction; proposal not discarded']
                break
            # No-good on the EXACT block allocations AND section counts, not just
            # the learner assignments (another sectioning could fix the shortage).
            literals=[x[r.id,choice[r.id]].Not() for r in requests]
            for (fid,b),var in s.items():
                neq=model.new_bool_var(f'change-section:{result.candidate_attempts}:{fid}:{b}')
                model.add(var!=counts[fid,b]).only_enforce_if(neq)
                model.add(var==counts[fid,b]).only_enforce_if(neq.Not())
                literals.append(neq)
            model.add_bool_or(literals)
            result.findings.append(f'Candidate {result.candidate_attempts} proved unteachable; excluded only its exact plan')
        else:
            result.status='UNKNOWN';result.findings.append('Candidate search limit reached; no exhaustive proof')
        return result
    except (ValidationError,TypeError,KeyError,ValueError,StopIteration) as e:
        result.status='INVALID_INPUT';result.findings=[f'{type(e).__name__}: {e}'];return result
    except Exception as e:
        result.status='ERROR';result.findings=[f'C4_SEARCH_ERROR: {type(e).__name__}: {e}'];return result
    finally:
        if 'inp' in locals() and result.source_sha256:
            result.source_unchanged=fingerprint(inp.current.source)==result.source_sha256
