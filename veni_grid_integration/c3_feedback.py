"""C3.0 restricted resource-aware O1/C2 feedback previews.

A new *draft proposal*, never a modified accepted plan or publication. From an
accepted, proved-un-teachable fixed O1 plan, select new family blocks (single
block per family only), explicitly matching qualified staff and exclusive
suitable rooms within each synchronous block. The proposal is not accepted
until independent O1 validation AND full C2 CP-SAT placement both pass.

This cannot yet re-section one family across several blocks, change staff
contracts, infer missing bell times, or produce full-school infeasibility proofs.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from math import ceil
from time import perf_counter
from typing import Literal
from pydantic import Field, ValidationError
from ortools.sat.python import cp_model

from veni_grid_contract.primitives import ContractModel
from veni_grid_contract.models import ID
from veni_grid_contract.handoff_common import fingerprint, snapshot_ref
from veni_grid_contract.option_design import OptionDesignWitness, option_errors
from veni_grid_contract.options_handoff import AcceptedOptions
from veni_grid_options.solver import _to_witness  # Existing O1 deterministic section constructor, then independently checked
from .c2 import C2Input, C2BlockWindow, C2Result, solve_c2


class FeedbackOptions(ContractModel):
    max_families: int = Field(default=12,ge=1,le=100)
    max_sections: int = Field(default=80,ge=1,le=2000)
    max_time_seconds: float = Field(default=20,ge=0,le=180)
    max_candidates: int = Field(default=6,ge=1,le=20)
    placement_seconds: float = Field(default=6,gt=0,le=60)


class C3Input(ContractModel):
    version: Literal['0.1.0'] = '0.1.0'
    current: C2Input
    # Full explicit planning-time catalogue, including optional *new* blocks.
    # No time domain is guessed for an added block.
    proposed_block_windows: list[C2BlockWindow] = Field(min_length=1)
    options: FeedbackOptions = Field(default_factory=FeedbackOptions)


class C3Result(ContractModel):
    version: Literal['0.1.0'] = '0.1.0'
    status: Literal['PROPOSED_VALIDATED','ALREADY_FEASIBLE','RESOURCE_RESTRICTED_INFEASIBLE',
        'UNKNOWN','UNSUPPORTED','INVALID_INPUT','ERROR']
    proof_scope: Literal['NONE','RESTRICTED_C3_SINGLE_FAMILY_TEACHING'] = 'NONE'
    previous_c2_status: str = 'NOT_RUN'
    previous_c2_findings: list[str] = Field(default_factory=list)
    original_o1_sha256: str | None = None
    original_still_unchanged: bool = False
    proposed_o1: OptionDesignWitness | None = None
    preview_c2: C2Result | None = None
    proposed_changes: list[str] = Field(default_factory=list)
    candidate_attempts: int = 0
    findings: list[str] = Field(default_factory=list)
    academic_scheduling: Literal['STANDALONE_PREVIEW_ONLY'] = 'STANDALONE_PREVIEW_ONLY'
    other_schedules: Literal['NOT_READ_OR_CHANGED'] = 'NOT_READ_OR_CHANGED'
    acceptance: Literal['NOT_GRANTED'] = 'NOT_GRANTED'
    publication: Literal['NOT_GRANTED'] = 'NOT_GRANTED'


def _prepare(data: C3Input):
    request=data.current
    p=request.source.demand
    family={f.id:f for f in p.families}
    specs={s.family_id:s for s in request.target.family_teaching}
    if set(specs)!=set(family):raise ValueError('Every family requires an explicit supplied teaching specification')
    original=defaultdict(set)
    for offer in request.source.plan.offerings:original[offer.family_id].add(offer.block_id)
    if any(len(values)!=1 for values in original.values()):
        raise NotImplementedError('Current C3 resource feedback supports ONE original block per family; flexible multi-block family feedback is a later profile')
    requested=Counter(r.family_id for r in p.requests)
    fids=sorted(requested)
    if len(fids)>data.options.max_families:
        raise NotImplementedError(f'Family count exceeds this C3 search limit ({data.options.max_families})')
    count={f:ceil(requested[f]/family[f].max_members) for f in fids}
    if any(count[f]>family[f].max_sections or count[f]*family[f].min_members>requested[f] for f in fids):
        raise ValueError('Demand cannot be divided into the minimum-size section counts in restricted C3 profile')
    total_sections=sum(count.values())
    resources={r.id:r for r in request.target.resources}
    available_rooms={r.id for r in request.target.resources if r.kind=='SPACE' and r.sharing_mode=='EXCLUSIVE'}
    all_teachers={r.id for r in request.target.resources if r.kind=='PERSON' and 'TEACHER' in r.tags}
    slots=[f'block:B{b:02d}' for b in range(p.max_blocks)]
    if not set().union(*original.values()) <= set(slots):
        raise NotImplementedError('Initial O1 block identities must be canonical block:B00... for this constrained revision profile')
    domains={(x.block_id,x.occurrence_key):x for x in data.proposed_block_windows}
    if len(domains)!=len(data.proposed_block_windows):raise ValueError('Duplicate candidate block/domain declarations')
    allowed_blocks={}
    for f in fids:
        occs=specs[f].occurrences
        allowed_blocks[f]=[i for i,b in enumerate(slots) if all((b,o.key) in domains for o in occs)]
        if not allowed_blocks[f]:raise NotImplementedError(f'No explicitly authorised candidate windows for {f}')
    for b in data.proposed_block_windows:
        if b.block_id not in slots:raise ValueError(f'Unknown proposed block slot: {b.block_id}')
        if any(wid not in {w.id for w in request.target.windows} for wid in b.candidate_start_ids):
            raise ValueError('Unknown candidate period; cannot infer new bells')
        windex={w.id:w for w in request.target.windows}
        if any(windex[wid].day_id not in b.allowed_day_ids for wid in b.candidate_start_ids):
            raise ValueError('Candidate period is not on the supplied permitted day')
    if len(set(request.target.family_teaching[i].family_id for i in range(len(request.target.family_teaching))))!=len(specs):
        raise ValueError('Duplicate family teaching specifications')
    # Current profile assumes every family offers the same occurrence keys.
    signatures={tuple(sorted(o.key for o in specs[f].occurrences)) for f in fids}
    if len(signatures)!=1 or len(next(iter(signatures)))!=1:raise NotImplementedError('C3 v0.1 preview supports exactly ONE shared occurrence per subject; repeating curricula and continuity need a separate verified model')
    if any(c.valid_during is not None for c in request.target.credentials):
        raise NotImplementedError('Dated credentials require separate date-aware resource feedback policy')
    competencies={(c.resource_id,c.competency) for c in request.target.credentials}
    teacher_candidates={f:sorted({tid for tid in specs[f].teacher_ids if tid in all_teachers and (tid,specs[f].competency_code) in competencies}) for f in fids}
    # Equal-size sections; the same O1 helper will later create exactly these sizes.
    sizes={}
    room_candidates={}
    for f in fids:
        base,extra=divmod(requested[f],count[f]);sizes[f]=[base+1]*extra+[base]*(count[f]-extra)
        if not teacher_candidates[f]:raise NotImplementedError(f'No verified qualified teacher available for {f}; reblocking cannot create one')
        for i,size in enumerate(sizes[f]):
            room_candidates[f,i]=sorted({rid for rid in specs[f].room_ids if rid in available_rooms and resources[rid].capacity is not None and resources[rid].capacity>=size and set(specs[f].required_room_tags)<=set(resources[rid].tags)})
            if not room_candidates[f,i]:raise NotImplementedError(f'No suitable room of size {size} exists for {f}; cannot fix by reblocking')
    return p,original,slots,domains,allowed_blocks,count,sizes,teacher_candidates,room_candidates,total_sections,all_teachers,available_rooms


def propose_c3(request: C3Input | dict) -> C3Result:
    response=C3Result(status='ERROR')
    try:
        data=C3Input.model_validate(request.model_dump(mode='json') if isinstance(request,C3Input) else request)
        original=data.current
        response.original_o1_sha256=fingerprint(original.source)
        before=solve_c2(original,time_limit_seconds=data.options.placement_seconds)
        response.previous_c2_status=before.status
        response.previous_c2_findings=list(before.findings)
        if before.status=='FEASIBLE':
            response.status='ALREADY_FEASIBLE';response.original_still_unchanged=fingerprint(original.source)==response.original_o1_sha256
            return response
        if before.status!='INFEASIBLE':
            response.status='UNKNOWN' if before.status=='UNKNOWN' else ('UNSUPPORTED' if before.status=='UNSUPPORTED' else 'INVALID_INPUT')
            response.findings.append('The existing plan must have a proved fixed-plan teaching failure before a feedback proposal is attempted')
            return response
        prepared=_prepare(data)
        p,original_blocks,slots,domains,allowed,section_count,sizes,teachers,rooms,total,teacher_pool,room_pool=prepared
        if total>p.max_blocks*len(room_pool) or total>p.max_blocks*len(teacher_pool):
            response.status='RESOURCE_RESTRICTED_INFEASIBLE'
            response.proof_scope='RESTRICTED_C3_SINGLE_FAMILY_TEACHING'
            min_room_blocks=ceil(total/max(len(room_pool),1))
            min_teacher_blocks=ceil(total/max(len(teacher_pool),1))
            response.findings.append(f'{total} section placements require at least {max(min_room_blocks,min_teacher_blocks)} blocks with this many exclusive rooms/qualified people; only {p.max_blocks} blocks are permitted. More staff, rooms, blocks or a different lesson pattern is needed.')
            response.original_still_unchanged=fingerprint(original.source)==response.original_o1_sha256
            return response
        if total>data.options.max_sections:
            response.status='UNSUPPORTED';response.findings=[f'{total} sections exceed reviewed C3 search cap ({data.options.max_sections}); no global impossibility conclusion']
            return response
        if data.options.max_time_seconds<=0:
            response.status='UNKNOWN';response.findings=['No search time available']
            return response
        deadline=perf_counter()+data.options.max_time_seconds
        model=cp_model.CpModel()
        fids=sorted(section_count)
        x={(f,b):model.new_bool_var(f'family:{f}:block{b}') for f in fids for b in range(len(slots))}
        used=[model.new_bool_var(f'block:{b}:used') for b in range(len(slots))]
        for f in fids:
            model.add(sum(x[f,b] for b in range(len(slots)))==1)
            for b in range(len(slots)):
                if b not in allowed[f]:model.add(x[f,b]==0)
        for b in range(len(slots)):
            model.add(sum(x[f,b] for f in fids)>=used[b])
            model.add(sum(x[f,b] for f in fids)<=len(fids)*used[b])
            if b: model.add(used[b-1]>=used[b])
        by_learner=defaultdict(set)
        for req in p.requests:by_learner[req.participant_id].add(req.family_id)
        pairs=set()
        for selections in by_learner.values():
            ordered=sorted(selections)
            pairs.update((a,c) for i,a in enumerate(ordered) for c in ordered[i+1:])
        for left,right in pairs:
            for b in range(len(slots)):model.add(x[left,b]+x[right,b]<=1)
        teacher_use=defaultdict(list);room_use=defaultdict(list)
        for f in fids:
            for ix,_ in enumerate(sizes[f]):
                for b in allowed[f]:
                    tt=[model.new_bool_var(f'teacher:{f}:{ix}:b{b}:{r}') for r in teachers[f]]
                    rr=[model.new_bool_var(f'room:{f}:{ix}:b{b}:{r}') for r in rooms[f,ix]]
                    model.add(sum(tt)==x[f,b]);model.add(sum(rr)==x[f,b])
                    for rid,v in zip(teachers[f],tt):teacher_use[b,rid].append(v)
                    for rid,v in zip(rooms[f,ix],rr):room_use[b,rid].append(v)
        for arr in (*teacher_use.values(),*room_use.values()):model.add(sum(arr)<=1)
        # Preserve original family locations as much as a *teachable* result permits.
        move=sum(1-x[f,slots.index(next(iter(original_blocks[f])))] for f in fids)
        model.minimize((len(slots)+1)*move+sum(used))
        while response.candidate_attempts<data.options.max_candidates:
            left=deadline-perf_counter()
            if left<=0:
                response.status='UNKNOWN';response.findings.append('Time exhausted; no approved replacement generated');break
            engine=cp_model.CpSolver();engine.parameters.max_time_in_seconds=left
            engine.parameters.num_search_workers=1;engine.parameters.random_seed=4
            status=engine.solve(model)
            if status==cp_model.INFEASIBLE:
                response.status='RESOURCE_RESTRICTED_INFEASIBLE';response.proof_scope='RESTRICTED_C3_SINGLE_FAMILY_TEACHING'
                response.findings.append('No remaining candidate in the restricted single-family/single-occurrence C3 model survived static matching and proved C2 checks. This does NOT rule out other O1 layouts, time models or new resources.')
                break
            if status not in (cp_model.OPTIMAL,cp_model.FEASIBLE):
                response.status='UNKNOWN';response.findings.append('Resource-aware option search unresolved within budget')
                break
            chosen={f:next(b for b in range(len(slots)) if engine.value(x[f,b])) for f in fids}
            assignment=defaultdict(lambda:defaultdict(list));section_counts={}
            for rq in p.requests:assignment[rq.family_id][chosen[rq.family_id]].append(rq.id)
            for f in fids:section_counts[f,chosen[f]]=section_count[f]
            proposal=_to_witness(p,assignment,section_counts)
            failures=option_errors(p,proposal)
            if failures:
                response.status='ERROR';response.findings.append('INDEPENDENT_OPTION_VALIDATION_FAILED: '+str(failures[:2]));break
            response.candidate_attempts+=1
            simulated=AcceptedOptions(demand=p,plan=proposal)
            # Internal ephemeral preview: this helper signs no actual approval.
            ref=snapshot_ref(simulated,organisation_id=original.target.organisation_id,
                    schedule_id=original.source_ref.schedule_id,
                    revision=original.source_ref.revision+response.candidate_attempts,
                    origin='GRID',state='ACCEPTED')
            target=original.target.model_copy(deep=True)
            required={(s.block_id,o.key) for s in proposal.offerings for o in next(spec for spec in target.family_teaching if spec.family_id==s.family_id).occurrences}
            target.block_windows=[domains[key].model_copy(deep=True) for key in sorted(required)]
            preview=solve_c2(C2Input(source_ref=ref,source=simulated,target=target),time_limit_seconds=min(data.options.placement_seconds,max(0.001,deadline-perf_counter())))
            if preview.status=='FEASIBLE' and preview.independent_hard_validation=='PASSED':
                response.status='PROPOSED_VALIDATED';response.proposed_o1=proposal;response.preview_c2=preview
                for f in fids:
                    old=next(iter(original_blocks[f]));new=slots[chosen[f]]
                    if old!=new:response.proposed_changes.append(f'{f}: {old} → {new}')
                response.proposed_changes.append(f'{len(proposal.offerings)} sections, {len(proposal.allocations)} learner requests preserved')
                response.findings.append('Preview only: generated plan is NOT accepted or published; user approval and trusted source/version checks still required')
                break
            # Never discard a plan on an unresolved C2 search. Only a proven
            # fixed-plan impossibility justifies a no-good cut.
            if preview.status!='INFEASIBLE' or preview.proof_scope!='FIXED_O1_C2':
                response.status='UNKNOWN' if preview.status=='UNKNOWN' else 'UNSUPPORTED'
                response.findings.append(f'Candidate preview {preview.status}: no proved time-placement contradiction; cannot discard the candidate')
                break
            # A statically promising plan may still have conflicting real time windows.
            # Forbid only this PROVED-unworkable layout. Never call it generally infeasible.
            model.add(sum(x[f,b] for f,b in chosen.items()) <= len(chosen)-1)
            response.findings.append(f'Candidate {response.candidate_attempts} failed actual C2 placement ({preview.status}); exploring another block arrangement')
            if response.candidate_attempts==data.options.max_candidates:
                response.status='UNKNOWN';response.findings.append('Reviewed candidate limit reached')
    except NotImplementedError as e:
        response.status='UNSUPPORTED';response.findings.append(str(e))
    except (ValueError,TypeError,ValidationError,KeyError,StopIteration) as e:
        response.status='INVALID_INPUT';response.findings.append(f'{type(e).__name__}: {e}')
    except Exception as e:
        response.status='ERROR';response.findings.append(f'C3_FEEDBACK_ERROR: {type(e).__name__}: {e}')
    try:
        if 'data' in locals():response.original_still_unchanged=fingerprint(data.current.source)==response.original_o1_sha256
    except Exception:pass
    return response
