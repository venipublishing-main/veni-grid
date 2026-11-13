"""Synthetic O1→C2 re-planning probe and readable C2 teaching timetable.

No real learners, no publishing, no accepted-source mutation. The C3 preview
shows one valid alternative to a proved laboratory shortage.
"""
from __future__ import annotations
from pathlib import Path
import json
from veni_grid_contract.models import Day,TimeWindow
from veni_grid_contract.core_v1 import LocatedResource,Credential,Location
from veni_grid_contract.handoff_common import snapshot_ref
from veni_grid_contract.options_handoff import AcceptedOptions,LessonOccurrence
from veni_grid_contract.option_design import OptionDesignProblem
from veni_grid_integration.c2 import C2Target,C2Input,C2FamilyTeaching,C2BlockWindow
from veni_grid_integration.c3_feedback import C3Input,propose_c3
from veni_grid_options import solve_options

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'c3-output'


def fixture(*,block_limit=2,room_bottleneck=True,teacher_bottleneck=False,allow_different_times=True):
    # Six invented learners have mutually exclusive single-subject selections.
    # O1 correctly puts both families into one block: nothing in learner choices
    # alone says they must be separated. C2 then catches a shared laboratory.
    persons=[f'person:S{i}' for i in range(1,7)]
    families=[{'id':f'family:{x}','label':f'Synthetic Subject {x}','min_members':3,'max_members':3,'max_sections':1} for x in 'AB']
    requests=[{'id':f'request:S{i}:{"A" if i<=3 else "B"}','participant_id':f'person:S{i}','family_id':f'family:{"A" if i<=3 else "B"}'} for i in range(1,7)]
    demand=OptionDesignProblem.model_validate({'problem_id':'c3:lab:scenario','model_version':1,
                'participant_ids':persons,'families':families,'requests':requests,'max_blocks':block_limit})
    original=solve_options(demand,{'strategy':'SINGLE_FAMILY_BLOCK','max_time_seconds':5})
    assert original.status=='FEASIBLE' and original.offering_count==2 and original.block_count==1
    source=AcceptedOptions(demand=demand,plan=original.witness)
    ref=snapshot_ref(source,organisation_id='org:c3-demo',schedule_id='sched:c3-option-source',revision=1,state='ACCEPTED')
    days=[Day(id='day:D1',label='Cycle day 1',ordinal=1)]
    windows=[TimeWindow(id=f'window:D1P{i}',day_id='day:D1',bell_id='bell:main',sequence=i,
              start_minute=480+(i-1)*40,end_minute=520+(i-1)*40) for i in range(1,4)]
    rs=[LocatedResource(id=p,kind='PERSON',label='Invented pupil',tags=['LEARNER']) for p in persons]
    if teacher_bottleneck:
        rs += [LocatedResource(id='person:T',kind='PERSON',label='Invented dual-subject teacher',tags=['TEACHER'])]
        teacher_by_family={'A':['person:T'],'B':['person:T']}
        credentials=[Credential(id=f'credential:T:{x}',resource_id='person:T',competency=f'competency:{x}',source_ref='synthetic:register') for x in 'AB']
    else:
        rs += [LocatedResource(id=f'person:T{x}',kind='PERSON',label=f'Invented teacher {x}',tags=['TEACHER']) for x in 'AB']
        teacher_by_family={x:[f'person:T{x}'] for x in 'AB'}
        credentials=[Credential(id=f'credential:T{x}',resource_id=f'person:T{x}',competency=f'competency:{x}',source_ref='synthetic:register') for x in 'AB']
    if room_bottleneck:
        room_ids=['space:LAB']
        rs.append(LocatedResource(id='space:LAB',kind='SPACE',label='One laboratory',capacity=6,tags=['LAB','CLASSROOM'],location_id='loc:LAB'))
    else:
        room_ids=['space:R1','space:R2']
        rs.extend([LocatedResource(id=rid,kind='SPACE',label=rid,capacity=6,tags=['CLASSROOM'],location_id='loc:LAB') for rid in room_ids])
    specs=[C2FamilyTeaching(family_id=f'family:{x}',competency_code=f'competency:{x}',
          teacher_ids=teacher_by_family[x],room_ids=room_ids,
          required_room_tags=['LAB'] if room_bottleneck else ['CLASSROOM'],
          occurrences=[LessonOccurrence(key='occ:day1',duration={'unit':'WINDOWS','count':1})]) for x in 'AB']
    # Only B00 is used in the ACCEPTED input. B01 is a separate EXPLICIT
    # proposal choice, not a magically inferred time domain.
    current=[C2BlockWindow(block_id='block:B00',occurrence_key='occ:day1',
        allowed_day_ids=['day:D1'],candidate_start_ids=['window:D1P1'])]
    extra=[C2BlockWindow(block_id='block:B01',occurrence_key='occ:day1',
        allowed_day_ids=['day:D1'],candidate_start_ids=['window:D1P3' if allow_different_times else 'window:D1P1'])]
    target=C2Target(organisation_id='org:c3-demo',schedule_id='sched:c3-academic-draft',model_version=1,
        days=days,windows=windows,resources=rs,
        locations=[Location(id='loc:LAB',label='Demonstration building')],
        credentials=credentials,family_teaching=specs,block_windows=current)
    return C3Input(current=C2Input(source_ref=ref,source=source,target=target),proposed_block_windows=current+(extra if block_limit>1 else []))


def run():
    OUT.mkdir(exist_ok=True)
    from veni_grid_contract.option_design import option_errors
    request=fixture()
    result=propose_c3(request)
    if not (result.status=='PROPOSED_VALIDATED' and result.preview_c2 and result.preview_c2.independent_hard_validation=='PASSED'):
        raise RuntimeError(f'C3 could not propose working alternative: {result.status}: {result.findings}')
    if option_errors(request.current.source.demand,result.proposed_o1):
        raise RuntimeError('Proposed O1 learner choices are invalid')
    if result.original_o1_sha256!=__import__('veni_grid_contract.handoff_common',fromlist=['fingerprint']).fingerprint(request.current.source):
        raise RuntimeError('C3 must not modify original source')
    (OUT/'c3-proposal.json').write_text(result.model_dump_json(indent=2)+'\n')
    before={o.family_id:o.block_id for o in request.current.source.plan.offerings}
    after={o.family_id:o.block_id for o in result.proposed_o1.offerings}
    report={
      'status':result.status,'first_plan_c2_status':result.previous_c2_status,
      'original_blocks':before,'proposed_blocks':after,'moved_subject_families':sum(before[f]!=after[f] for f in before),
      'compulsory_requests':len(request.current.source.demand.requests),
      'requests_fulfilled':len(result.proposed_o1.allocations),
      'original_unchanged':result.original_still_unchanged,
      'proposed_lessons_scheduled':result.preview_c2.event_count,
      'hard_validation':result.preview_c2.independent_hard_validation,
      'resource_assignments':{
        'teachers':result.preview_c2.teacher_assignments,
        'rooms':result.preview_c2.room_assignments},
      'human_readable':'First plan put two separate subject classes at the same time in one laboratory. The preview moves one subject into a later option block; both now reuse the lab at different times, without losing any learner requests.',
      'approval':'NOT_GRANTED','other_schedules':'NOT_READ_OR_CHANGED',
      'proof_scope':'RESOURCE_AWARE_SINGLE_FAMILY_ONLY',
      'real_school_claim':'NONE'}
    (OUT/'c3-summary.json').write_text(json.dumps(report,indent=2)+'\n')
    from scripts.render_c3_feedback import render_feedback
    render_feedback(report,request,OUT)
    print(json.dumps(report,indent=2))
    return report

if __name__=='__main__':run()
