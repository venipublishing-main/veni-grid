"""Executed synthetic O1 -> C2 -> real C1 placement proof, with negative cases.

No teacher/student identities here refer to a real school. C1 48 requests and
nine O1-constructed sections are small enough for a comprehensive joint test.
"""
from __future__ import annotations
import json
from pathlib import Path
from collections import Counter, defaultdict
from copy import deepcopy
from time import perf_counter

from scripts.build_benchmark_c1 import build as build_choice_c1
from scripts.build_benchmark_c0 import build as build_choice_c0
from veni_grid_contract.models import Day, TimeWindow
from veni_grid_contract.core_v1 import LocatedResource, Credential, Location
from veni_grid_contract.options_handoff import AcceptedOptions, LessonOccurrence
from veni_grid_contract.handoff_common import snapshot_ref, fingerprint
from veni_grid_contract.option_design import option_errors
from veni_grid_options import solve_options
from veni_grid_integration import C2Input, C2Target, C2FamilyTeaching, C2BlockWindow, solve_c2

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'c2-output'


def school_input(*, remove_lab=False, no_science_qualification=False,
                 teacher_science_blackout=False, too_few_rooms=False,
                 reduce_lab_capacity=False, wrong_teacher=False,
                 solve_o1=True):
    p=build_choice_c1(repeats=4)
    o1=solve_options(p,{'strategy':'AUTO','max_time_seconds':10})
    assert o1.status=='FEASIBLE' and o1.witness and not option_errors(p,o1.witness)
    accepted=AcceptedOptions(demand=p,plan=o1.witness)
    ref=snapshot_ref(accepted,organisation_id='org:synthetic',schedule_id='sched:option-source',
                     revision=1,origin='GRID',state='ACCEPTED')
    days=[Day(id='day:D1',label='Cycle Day 1',ordinal=1),Day(id='day:D2',label='Cycle Day 2',ordinal=2)]
    windows=[TimeWindow(id=f'window:D{day}P{period}',day_id=f'day:D{day}',bell_id='bell:main',
            sequence=period,start_minute=480+40*(period-1),end_minute=480+40*period)
            for day in (1,2) for period in range(1,7)]
    resources=[]
    for person in p.participant_ids:
        resources.append(LocatedResource(id=person,kind='PERSON',label='Invented learner',tags=['LEARNER']))
    for fid in 'ABCD':
        resources.append(LocatedResource(id=f'person:T{fid}',kind='PERSON',label=f'Invented subject {fid} teacher',
            tags=['TEACHER'],unavailable_window_ids=([w.id for w in windows if w.day_id=='day:D2']
                if teacher_science_blackout and fid=='D' else [])))
    for rid in ('space:R1','space:R2','space:LAB'):
        if remove_lab and rid=='space:LAB':continue
        if too_few_rooms and rid=='space:R2':continue
        capacity=2 if reduce_lab_capacity and rid=='space:LAB' else 6
        resources.append(LocatedResource(id=rid,kind='SPACE',label=f'Invented {rid}',
             tags=['CLASSROOM','LAB'] if rid=='space:LAB' else ['CLASSROOM'],
             capacity=capacity,location_id='loc:LAB' if rid=='space:LAB' else 'loc:MAIN'))
    credentials=[Credential(id=f'credential:{fid}',resource_id=f'person:T{fid}',
                   competency=f'competency:{fid}',source_ref='synthetic:staff-credential')
                 for fid in 'ABCD' if not (no_science_qualification and fid=='D')]
    specs=[]
    for fid in 'ABCD':
        rooms=['space:LAB'] if fid=='D' else ['space:R1','space:R2']
        if remove_lab and fid=='D':rooms=['space:R1']
        if too_few_rooms and fid!='D':rooms=['space:R1']
        teach=[f'person:T{fid}']
        if wrong_teacher and fid=='D':teach=['person:TA']
        specs.append(C2FamilyTeaching(family_id=f'family:{fid}',competency_code=f'competency:{fid}',
             teacher_ids=teach,room_ids=rooms,required_room_tags=['LAB'] if fid=='D' else ['CLASSROOM'],
             occurrences=[LessonOccurrence(key=f'occ:D{day}',duration={'unit':'WINDOWS','count':2 if fid=='D' else 1})
                          for day in (1,2)],
             same_teacher_across_occurrences=True,same_room_across_occurrences=False))
    blocks=sorted(o1.witness.block_ids)
    bindings=[C2BlockWindow(block_id=block,occurrence_key=f'occ:D{day}',
        allowed_day_ids=[f'day:D{day}'],
        candidate_start_ids=[f'window:D{day}P{period}' for period in (1,3,5)])
        for block in blocks for day in (1,2)]
    target=C2Target(organisation_id='org:synthetic',schedule_id='sched:C2:lessons',model_version=1,
        days=days,windows=windows,resources=resources,
        locations=[Location(id='loc:MAIN',label='Main building'),Location(id='loc:LAB',label='Science lab wing')],
        credentials=credentials,family_teaching=specs,block_windows=bindings)
    return C2Input(source_ref=ref,source=accepted,target=target)


def large_school_room_shortage_input():
    """C0 O1 generated 360 sections; fully qualified teachers but only 30 rooms.

    This is an actually generated choice plan, and C2 returns a *fixed-plan*
    structural room bottleneck without claiming a full 1,500-person solve.
    """
    p,_ = build_choice_c0()
    solved = solve_options(p, {'strategy':'AUTO','max_time_seconds':15})
    assert solved.status=='FEASIBLE' and solved.offering_count==360
    accepted = AcceptedOptions(demand=p,plan=solved.witness)
    ref = snapshot_ref(accepted,organisation_id='org:large-synthetic',
        schedule_id='sched:large-options',revision=1,origin='GRID',state='ACCEPTED')
    days=[Day(id='day:D1',label='Cycle Day 1',ordinal=1)]
    windows=[TimeWindow(id=f'window:D1P{period}',day_id='day:D1',bell_id='bell:standard',
         sequence=period,start_minute=480+40*(period-1),end_minute=480+40*period)
         for period in range(1,7)]
    learners=[LocatedResource(id=person,kind='PERSON',label='Fictitious learner',tags=['LEARNER'])
              for person in p.participant_ids]
    teacher_ids=[f'person:T{i:03d}' for i in range(360)]
    teachers=[LocatedResource(id=x,kind='PERSON',label='Fictitious qualified educator',tags=['TEACHER'])
              for x in teacher_ids]
    rooms=[LocatedResource(id=f'space:R{i:02d}',kind='SPACE',label=f'Room {i}',
           capacity=25,tags=['CLASSROOM'],location_id='loc:MAIN') for i in range(30)]
    credentials=[];specs=[]
    for family_index, f in enumerate(p.families):
        name=f.id.split(':')[-1]   # F000, F001, F002, F010 ...
        teacher_pool=teacher_ids[family_index*20:(family_index+1)*20]
        code=f'competency:{name}'
        for teacher in teacher_pool:
            credentials.append(Credential(id=f'credential:{name}:{teacher.rsplit(":",1)[-1]}',
                resource_id=teacher,competency=code,source_ref='synthetic:registry'))
        specs.append(C2FamilyTeaching(family_id=f.id,competency_code=code,
            teacher_ids=teacher_pool,room_ids=[r.id for r in rooms],
            required_room_tags=['CLASSROOM'],
            occurrences=[LessonOccurrence(key='occ:one',duration={'unit':'WINDOWS','count':1})]))
    block_windows=[C2BlockWindow(block_id=b,occurrence_key='occ:one',
           allowed_day_ids=['day:D1'],
           candidate_start_ids=[w.id for w in windows]) for b in solved.witness.block_ids]
    target=C2Target(organisation_id='org:large-synthetic',schedule_id='sched:large-lessons',
       model_version=1,days=days,windows=windows,resources=learners+teachers+rooms,
       locations=[Location(id='loc:MAIN',label='Main campus')],
       credentials=credentials,family_teaching=specs,block_windows=block_windows)
    return C2Input(source_ref=ref,source=accepted,target=target)


def large_school_teacher_shortage_input():
    """Another fixed O1 plan: 60 rooms, but at most 30 qualified teachers.

    Deliberately generous shared competency assertions are synthetic. The
    mathematical conclusion is only for the supplied fixed plan and teachers.
    """
    req=large_school_room_shortage_input()
    present={r.id for r in req.target.resources}
    for i in range(30,60):
        rid=f'space:R{i:02d}'
        if rid not in present:
            req.target.resources.append(LocatedResource(id=rid,kind='SPACE',label=f'Room {i}',
                capacity=25,tags=['CLASSROOM'],location_id='loc:MAIN'))
    available=[f'person:T{i:03d}' for i in range(30)]
    from veni_grid_contract.core_v1 import Credential as GridCredential
    req.target.credentials=[]
    for spec in req.target.family_teaching:
        spec.teacher_ids=available
        spec.room_ids=[f'space:R{i:02d}' for i in range(60)]
        for teacher in available:
            req.target.credentials.append(GridCredential(
                id=f'credential:{spec.competency_code.split(":")[-1]}:{teacher.split(":")[-1]}',
                resource_id=teacher,competency=spec.competency_code,
                source_ref='synthetic:multi-subject-registry'))
    return req


def write_readable_teaching_grid(problem, candidate):
    """Only the *actual* independently validated C1 candidate, never a mock UI."""
    events={e.id:e for e in problem.events}
    subjects={a.id:a.label for a in problem.activities}
    requirements={(e.id,q.id):q.role for e in problem.events for q in e.requirements}
    size=Counter(oid for enrol in candidate.enrollment_assignments for oid in enrol.offering_ids)
    slots=defaultdict(list)
    windows={w.id:w for w in problem.windows}
    for assignment in candidate.event_assignments:
        event=events[assignment.event_id]
        window=windows[assignment.start_window_id]
        selected={requirements[(event.id,a.requirement_id)]:a.resource_ids[0]
                  for a in assignment.resource_allocations}
        subject=subjects[event.activity_id].split()[-1]
        detail=f"{subject} · {event.label.split()[2]} · {size[event.offering_id]} pupils · {selected['TEACHER']} · {selected['ROOM']}"
        if event.duration.count>1:detail+=f" · double ({event.duration.count} periods)"
        slots[(window.day_id,window.sequence)].append(detail)
    lines=['# Veni Grid C2 — actual generated teacher/room timetable','',
        'This is extracted from the independently hard-validated CP-SAT C2 result; every person and room is synthetic.',
        'The section/learner choices originate from the O1 generated option plan. No other schedule was loaded.','',
        '| Day | Period start | Simultaneous classes and assigned teachers / rooms |',
        '|---|---:|---|']
    for (day,period),items in sorted(slots.items()):
        lines.append(f"| {day} | P{period} | {'; '.join(sorted(items))} |")
    lines+=['','Only two cycle days and a partial curriculum were tested. The classroom/teacher choices are not production allocations.','']
    (OUTPUT/'c2-generated-teaching-grid.md').write_text('\n'.join(lines),encoding='utf-8')


def run():
    OUTPUT.mkdir(exist_ok=True)
    cases={
      'C2_VALID_TEACHERS_ROOMS':school_input(),
      'C2_NO_QUALIFIED_SCIENCE_TEACHER':school_input(no_science_qualification=True),
      'C2_NO_SCIENCE_LAB':school_input(remove_lab=True),
      'C2_LAB_TOO_SMALL':school_input(reduce_lab_capacity=True),
      'C2_ONLY_TWO_ROOMS_FOR_THREE_CONCURRENT_CLASSES':school_input(too_few_rooms=True),
      'C2_SCIENCE_TEACHER_UNAVAILABLE_SECOND_DAY':school_input(teacher_science_blackout=True),
      'C2_SUBJECT_WRONG_TEACHER':school_input(wrong_teacher=True),
      'C2_1500_LEARNERS_30_ROOMS_FOR_60_SIMULTANEOUS_SECTIONS':large_school_room_shortage_input(),
      'C2_1500_LEARNERS_30_TEACHERS_FOR_60_SIMULTANEOUS_SECTIONS':large_school_teacher_shortage_input(),
    }
    results={}
    for name,request in cases.items():
        started=perf_counter()
        response=solve_c2(request,time_limit_seconds=20)
        record={k:v for k,v in response.model_dump(mode='json').items()
                if k not in ('placement_problem','candidate','teacher_assignments','room_assignments')}
        record['elapsed_wall_seconds_this_environment']=round(perf_counter()-started,3)
        record['staff_count']=len(set(response.teacher_assignments.values()))
        record['room_count']=len(set(response.room_assignments.values()))
        record['teacher_allocation_count']=len(response.teacher_assignments)
        record['room_allocation_count']=len(response.room_assignments)
        results[name]=record
        if name=='C2_VALID_TEACHERS_ROOMS' and response.candidate:
            (OUTPUT/'c2-generated-teaching-timetable.json').write_text(response.candidate.model_dump_json(indent=2)+'\n')
            (OUTPUT/'c2-placement-problem.json').write_text(response.placement_problem.model_dump_json(indent=2)+'\n')
            write_readable_teaching_grid(response.placement_problem,response.candidate)
        print(name, response.status, response.stage, record['elapsed_wall_seconds_this_environment'],
              response.findings[:2],flush=True)
    (OUTPUT/'c2-results.json').write_text(json.dumps(results,indent=2)+'\n')
    return results


if __name__=='__main__':run()
