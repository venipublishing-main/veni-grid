"""Construct illustrative accepted plans and witnesses. Not a scheduling search."""
from __future__ import annotations
import json
import sys
from pathlib import Path
from datetime import timezone
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from veni_grid_contract.models import (Day,TimeWindow,Resource,ResourceKind,WindowDuration,
    ResourceRequirement,EventAssignment,RequirementAllocation,EnrollmentAssignment)
from veni_grid_contract.primitives import CapacityResource
from veni_grid_contract.option_design import OptionDesignProblem,OptionDesignWitness
from veni_grid_contract.coverage import CoverageProblem,CoverageWitness
from veni_grid_contract.handoff_common import snapshot_ref
from veni_grid_contract.options_handoff import (AcceptedOptions,LessonOccurrence,LessonTemplate,
    BlockBinding,LessonTargetConfig,OptionsHandoff,build_lesson_handoff,lesson_handoff_errors)
from veni_grid_contract.placement_v04 import PlacementWitness,placement_witness_errors
from veni_grid_contract.exam_handoff import (ExamSnapshot,ExamRecord,SessionCoveragePolicy,
    CoverageBandPolicy,CoverageTargetConfig,ExamHandoff,build_exam_handoff,exam_handoff_errors,session_id)
from veni_grid_contract.handoff_changes import (CoverageState,StaffingReviewRequest,
    derive_changes,review_staffing_change)


def read(rel): return json.loads((ROOT/rel).read_text())
def save(folder,name,value):
    path=ROOT/'fixtures_v04'/folder/name;path.parent.mkdir(parents=True,exist_ok=True)
    if hasattr(value,'model_dump'): value=value.model_dump(mode='json')
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n')


def option_case():
    problem=OptionDesignProblem.model_validate(read('fixtures_v03/F2_option_design/problem.json'))
    plan=OptionDesignWitness.model_validate(read('fixtures_v03/F2_option_design/witness.json'))
    source=AcceptedOptions(demand=problem,plan=plan)
    resources=[Resource(id=pid,kind=ResourceKind.PERSON,label=pid) for pid in problem.participant_ids]
    for name in ('Physics','Accounting','Art'):
        resources.append(Resource(id='teacher:'+name,kind=ResourceKind.PERSON,label='Synthetic teacher '+name))
    for room in ('LAB','R101','R102'):
        resources.append(Resource(id='room:'+room,kind=ResourceKind.SPACE,label=room,capacity=40))
    days=[Day(id=f'day:D{d}',label=f'Day {d}',ordinal=d) for d in range(1,5)]
    windows=[TimeWindow(id=f'window:D{d}P{seq}',day_id=f'day:D{d}',bell_id='bell:main',sequence=seq,
        start_minute=start,end_minute=end) for d in range(1,5)
        for seq,start,end in ((1,480,525),(2,540,585),(3,585,630))]
    room={'Physics':'LAB','Accounting':'R102','Art':'R101'}
    templates=[LessonTemplate(family_id=f.id,unit='WINDOWS',required_units=3,
        occurrences=[LessonOccurrence(key='occ:single',duration=WindowDuration(count=1)),
                     LessonOccurrence(key='occ:double',duration=WindowDuration(count=2))],
        requirements=[ResourceRequirement(id='req:teacher',role='TEACHER',kind=ResourceKind.PERSON,
                          quantity=1,eligible_resource_ids=['teacher:'+f.label]),
                      ResourceRequirement(id='req:room',role='ROOM',kind=ResourceKind.SPACE,
                          quantity=1,eligible_resource_ids=['room:'+room[f.label]])]) for f in problem.families]
    bindings=[BlockBinding(block_id=bid,occurrence_key=key,
                 candidate_start_ids=[f'window:D{day}P{seq}',f'window:D{day+2}P{seq}'])
              for bid,day in [('block:one',1),('block:two',2)]
              for key,seq in [('occ:single',1),('occ:double',2)]]
    cfg=LessonTargetConfig(organisation_id='org:synthetic',schedule_id='schedule:lessons',model_version=1,
        days=days,windows=windows,resources=resources,templates=templates,bindings=bindings)
    request=OptionsHandoff(source_ref=snapshot_ref(source,organisation_id=cfg.organisation_id,
               schedule_id='schedule:options',revision=3),source=source,target=cfg)
    result=build_lesson_handoff(request)
    # Fixed construction simply chooses the first supplied domain entry/resources.
    w=PlacementWitness(solution_id='solution:lessons:illustrative',problem_id=result.problem.problem_id,
        model_version=result.problem.model_version,status='FEASIBLE',
        event_assignments=[EventAssignment(event_id=e.id,start_window_id=e.placement.start_window_ids[0],
              resource_allocations=[RequirementAllocation(requirement_id=q.id,
                       resource_ids=q.eligible_resource_ids[:q.quantity]) for q in e.requirements]) for e in result.problem.events],
        enrollment_assignments=[EnrollmentAssignment(request_id=r.id,offering_ids=r.eligible_offering_ids)
                                for r in result.problem.participation_requests])
    assert not lesson_handoff_errors(result),lesson_handoff_errors(result)
    assert not placement_witness_errors(result.problem,w),placement_witness_errors(result.problem,w)
    return request,result,w


def exam_case(origin='GRID'):
    old=CoverageProblem.model_validate(read('fixtures_v03/F3_segmented_invigilation/problem.json'))
    oldw=CoverageWitness.model_validate(read('fixtures_v03/F3_segmented_invigilation/witness.json'))
    source=ExamSnapshot(venues=[CapacityResource(id='room:A',kind='SPACE',capacity=100,unit='SEATS'),
                                CapacityResource(id='room:B',kind='SPACE',capacity=60,unit='SEATS')],
        sessions=[ExamRecord(id=s.id,paper_id='paper:'+s.id.split(':')[-1],label='Synthetic exam '+s.id,
            venue_id=s.venue_id,supervision_interval=s.interval,candidate_count=60 if s.id=='exam:A' else 40) for s in old.sessions])
    policies=[]
    for s in old.sessions:
        bands=[]
        for d in old.demands:
            if d.session_id!=s.id: continue
            def mins(t):return int((t.astimezone(timezone.utc)-s.interval.start.astimezone(timezone.utc)).total_seconds()/60)
            bands.append(CoverageBandPolicy(key=d.id,start_offset_minutes=mins(d.interval.start),
                end_offset_minutes=mins(d.interval.end),role=d.role,minimum_staff=d.minimum_staff,
                eligible_staff_ids=[*d.eligible_staff_ids,'staff:I5']))
        policies.append(SessionCoveragePolicy(source_session_id=s.id,bands=bands))
    cfg=CoverageTargetConfig(organisation_id='org:synthetic',schedule_id='schedule:invigilation',model_version=1,
        selected_session_ids=[s.id for s in old.sessions],staff=[*[r for r in old.resources if r.kind=='PERSON'],
        CapacityResource(id='staff:I5',kind='PERSON')],policy_id='policy:synthetic-coverage',policy_revision=1,policies=policies)
    source_ref=snapshot_ref(source,organisation_id=cfg.organisation_id,
        schedule_id='schedule:exams' if origin=='GRID' else 'import:manual-exams',revision=7,origin=origin)
    request=ExamHandoff(source_ref=source_ref,source=source,target=cfg)
    result=build_exam_handoff(request)
    raw=oldw.model_dump(mode='json');raw['problem_id']=cfg.schedule_id
    for duty in raw['duties']: duty['session_id']=session_id(request,duty['session_id'])
    witness=CoverageWitness.model_validate(raw)
    assert not exam_handoff_errors(result),exam_handoff_errors(result)
    from veni_grid_contract.coverage import coverage_errors
    assert not coverage_errors(result.problem,witness),coverage_errors(result.problem,witness)
    return request,result,witness


def change_case():
    req,result,base=exam_case()
    raw=base.model_dump(mode='json')
    next(x for x in raw['duties'] if x['id']=='duty:3')['resource_id']='staff:I5'
    candidate=CoverageWitness.model_validate(raw)
    state=CoverageState(problem=result.problem,witness=base)
    base_ref=snapshot_ref(state,organisation_id='org:synthetic',schedule_id=result.problem.schedule_id,
                          revision=4,state='PUBLISHED')
    review=StaffingReviewRequest(job_id='job:staff-repair',handoff=result,baseline_ref=base_ref,
        baseline=base,candidate=candidate,mutable_duty_ids=['duty:3'],declared_changes=derive_changes(base,candidate))
    current=[req.source_ref,base_ref]
    output=review_staffing_change(review,current)
    assert output.status=='VALIDATED_PROPOSAL_NOT_APPLIED',output.findings
    return review,current,output


if __name__=='__main__':
    a,b,c=option_case()
    for n,v in [('request.json',a),('handoff.json',b),('placement-witness.json',c)]: save('H1_options_to_lessons',n,v)
    for origin,folder in [('GRID','H2_grid_exams_to_coverage'),('MANUAL','H3_manual_exams_to_coverage')]:
        a,b,c=exam_case(origin)
        for n,v in [('request.json',a),('handoff.json',b),('coverage-witness.json',c)]: save(folder,n,v)
    a,b,c=change_case()
    for n,v in [('review-request.json',a),('authoritative-current-refs.json',[x.model_dump(mode='json') for x in b]),
                ('review-result.json',c)]: save('H4_staffing_only_change',n,v)
    print('Built and checked four synthetic handoff/review examples. No solver run.')
