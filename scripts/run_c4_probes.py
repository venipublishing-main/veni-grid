"""C4 synthetic flexible/multi-occurrence feedback and independently checked evidence."""
from __future__ import annotations
from collections import defaultdict
from pathlib import Path
from time import perf_counter
import json

from scripts.run_c2_probes import school_input
from veni_grid_contract.options_handoff import AcceptedOptions
from veni_grid_contract.handoff_common import fingerprint,snapshot_ref
from veni_grid_options.solver import _to_witness
from veni_grid_contract.option_design import option_errors
from veni_grid_integration.c2 import solve_c2
from veni_grid_integration.c4_flexible_feedback import C4Input, C4Options, propose_c4, review_errors

OUT=Path(__file__).resolve().parents[1]/'c4-output'


def crossed_multi_occurrence_fixture() -> C4Input:
    """16 people, 48 crossed requests, original D sections collide in one lab.

    Each section requires TWO teaching occurrences on different cycle days;
    Subject D has a double period each day and one qualified specialist teacher.
    The candidate search can split subject D across blocks while preserving
    the compulsory O1 learner requests. No source blocks are supplied to C4.
    """
    req=school_input()
    dem=req.source.demand
    assignment=defaultdict(lambda:defaultdict(list))
    for person in sorted(dem.participant_ids):
        rs=sorted([r for r in dem.requests if r.participant_id==person],key=lambda r:r.family_id)
        d=next((r for r in rs if r.family_id=='family:D'),None)
        if d:
            assignment[d.family_id][0].append(d.id)
            for block,r in enumerate([r for r in rs if r.family_id!='family:D'],1):
                assignment[r.family_id][block].append(r.id)
        else:
            for block,r in enumerate(rs):assignment[r.family_id][block].append(r.id)
    counts={(f,b):(len(choices)+5)//6 for f,byblock in assignment.items() for b,choices in byblock.items()}
    src=_to_witness(dem,assignment,counts)
    assert option_errors(dem,src)==[]
    req.source=AcceptedOptions(demand=dem,plan=src)
    req.source_ref=snapshot_ref(req.source,organisation_id=req.target.organisation_id,
        schedule_id=req.source_ref.schedule_id,revision=1,origin='GRID',state='ACCEPTED')
    # All three blocks have explicitly modelled occurrences on both days.
    return C4Input(current=req,proposed_block_windows=req.target.block_windows,
                   options=C4Options(max_time_seconds=35,placement_seconds=8,max_candidates=10))


def run():
    OUT.mkdir(exist_ok=True)
    req=crossed_multi_occurrence_fixture()
    before=fingerprint(req.current.source)
    old=solve_c2(req.current,time_limit_seconds=8)
    started=perf_counter()
    result=propose_c4(req)
    elapsed=round(perf_counter()-started,3)
    if old.status!='INFEASIBLE' or old.proof_scope!='FIXED_O1_C2':
        raise RuntimeError('Original synthetic plan should have a proved resource clash')
    if result.status!='PROPOSED_VALIDATED':
        raise RuntimeError(f'C4 generated no verified alternative: {result.status} {result.findings}')
    if review_errors(req.current,result.proposed_o1,result.preview_c2,result.review):
        raise RuntimeError('C4 review integrity verification failed')
    if before!=fingerprint(req.current.source) or result.review.preserved_compulsory_requests!=48:
        raise RuntimeError('C4 lost requests or modified original source')
    payload=result.model_dump(mode='json')
    (OUT/'c4-proposal-and-reviewed-validation.json').write_text(json.dumps(payload,indent=2)+'\n')
    # A concise evidence receipt avoids copying the entire solver candidate into prose.
    summary={'run':'synthetic C4 flexible multi-occurrence',
       'original_status':old.status,'original_issue':old.findings[:2],
       'status':result.status,'proof_scope':result.proof_scope,
       'learners':len(req.current.source.demand.participant_ids),
       'requests':len(req.current.source.demand.requests),
       'original_sections':len(req.current.source.plan.offerings),
       'proposed_sections':len(result.proposed_o1.offerings),
       'changed_learner_requests':len(result.review.changed_request_ids),
       'teaching_occurrences':result.preview_c2.event_count,
       'teacher_assignments':len(result.preview_c2.teacher_assignments),
       'room_assignments':len(result.preview_c2.room_assignments),
       'validation':result.preview_c2.independent_hard_validation,
       'candidate_attempts':result.candidate_attempts,
       'review_status':result.review.approval,'publication':result.publication,
       'original_unchanged':result.source_unchanged,
       'elapsed_seconds_on_this_machine':elapsed,
       'context':'Four synthetic subjects, 16 learners and two cycle-day teaching occurrences; not a full school, not an approved replacement'}
    (OUT/'c4-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    from scripts.render_c4_review import render
    render(req,result,OUT)
    print(json.dumps(summary,indent=2))
    return result

if __name__=='__main__':run()
