"""Construct synthetic witnesses, not schedules found by an optimiser."""
from pathlib import Path
import json, sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from veni_grid_contract.core_v1 import CoreProblem, CoreWitness, core_witness_errors
from veni_grid_contract.recurring_claims import RecurrenceConfig, project_claims
from veni_grid_contract.handoff_common import fingerprint
from veni_grid_contract.flexible_options import FlexibleOptionsRequest, build_flexible_handoff, flexible_handoff_errors

ROOT=Path(__file__).resolve().parents[1]
def save(path,obj):
    dest=ROOT/path;dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(obj.model_dump_json(indent=2) if hasattr(obj,'model_dump_json') else json.dumps(obj,indent=2),encoding='utf8')

def operational_pair():
    days=[dict(id=f'day:D{i}',label=f'Day {i}',ordinal=i) for i in range(1,11)]
    wins=[dict(id=f'win:D{i}P{j}',day_id=f'day:D{i}',bell_id='bell:main',sequence=j,start_minute=420+60*j,end_minute=460+60*j) for i in range(1,11) for j in range(1,4)]
    resources=[dict(id=r,kind='PERSON',label=r) for r in ['person:teacherA','person:teacherB','person:pupil1','person:pupil2']]
    resources += [dict(id='group:class',kind='GROUP',label='Synthetic class',member_ids=['person:pupil1','person:pupil2']),
                  dict(id='room:west',kind='SPACE',label='West classroom',capacity=4,location_id='loc:west'),
                  dict(id='room:east',kind='SPACE',label='East classroom',capacity=4,location_id='loc:east')]
    events=[];assign=[]
    for i in [1,2]:
        events.append(dict(id=f'event:E{i}',label=f'Maths occurrence {i}',activity_id='activity:maths',fixed_participant_ids=['group:class'],
            duration=dict(unit='WINDOWS',count=1),placement=dict(start_window_ids=[x['id'] for x in wins]),
            requirements=[dict(id=f'req:teacher{i}',role='TEACHER',kind='PERSON',quantity=1,eligible_resource_ids=['person:teacherA','person:teacherB']),
                          dict(id=f'req:room{i}',role='ROOM',kind='SPACE',quantity=1,eligible_resource_ids=['room:west','room:east'],minimum_capacity=2)]))
        assign.append(dict(event_id=f'event:E{i}',start_window_id=f'win:D1P{i}',resource_allocations=[dict(requirement_id=f'req:teacher{i}',resource_ids=['person:teacherA']),dict(requirement_id=f'req:room{i}',resource_ids=['room:west' if i==1 else 'room:east'])]))
    refs=[dict(event_id=f'event:E{i}',requirement_id=f'req:teacher{i}') for i in [1,2]]
    p=CoreProblem.model_validate(dict(problem_id='schedule:academic',model_version=1,vertical_id='SCHOOLS',days=days,windows=wins,resources=resources,
         activities=[dict(id='activity:maths',label='Maths',demand=dict(basis='GLOBAL',unit='WINDOWS',amount=2))],events=events,
         locations=[dict(id='loc:west',label='West wing'),dict(id='loc:east',label='East wing')],
         credentials=[dict(id=f'credential:{x}',resource_id=f'person:teacher{x}',competency='skill:maths',source_ref='SYNTHETIC-STAFF-REGISTER') for x in ['A','B']],
         travel_arcs=[dict(from_location='loc:west',to_location='loc:east',minutes=15),dict(from_location='loc:east',to_location='loc:west',minutes=25)],
         constraints=[dict(id='rule:qualification',kind='QUALIFICATION',source='USER',allocations=refs,all_of=['skill:maths']),
                      dict(id='rule:continuity',kind='RESOURCE_CONTINUITY',source='USER',allocations=refs),
                      dict(id='rule:travel',kind='TRAVEL_TIME',source='USER',resource_ids=['person:teacherA'])]))
    w=CoreWitness.model_validate(dict(solution_id='candidate:academic',problem_id=p.problem_id,model_version=1,status='FEASIBLE',event_assignments=assign))
    return p,w

def recurrence(p,w):
    return RecurrenceConfig.model_validate(dict(calendar_id='calendar:term',revision=1,problem_sha256=fingerprint(p),witness_sha256=fingerprint(w),
       anchor_date='2026-11-16',cycle_length=10,horizon_start='2026-11-16',horizon_end='2026-12-02',weekdays=[0,1,2,3,4],
       day_cycle=[dict(day_id=d.id,cycle_day=d.ordinal) for d in p.days],
       window_periods=[dict(window_id=x.id,period_key=f'period:P{x.sequence}') for x in p.windows],default_bell_id='bells:normal',
       bell_sets=[dict(id='bells:normal',periods=[dict(key=f'period:P{j}',start_minute=420+60*j,end_minute=460+60*j) for j in [1,2,3]]),
                  dict(id='bells:changed',periods=[dict(key='period:P1',start_minute=480,end_minute=530),dict(key='period:P2',start_minute=555,end_minute=595),dict(key='period:P3',start_minute=615,end_minute=655)])],
       exceptions=[dict(date='2026-11-17',kind='CLOSED',advance_cycle=False,reason='SYNTHETIC closure, not a public holiday'),
                   dict(date='2026-12-01',kind='REPLACE_BELLS',advance_cycle=True,replacement_bell_id='bells:changed',reason='SYNTHETIC special bells')]))

def flexible_request():
    raw=json.loads((ROOT/'fixtures_v04/H1_options_to_lessons/request.json').read_text())
    raw['schema_version']='1.0.0-rc1'; oldbindings={(b['block_id'],b['occurrence_key']):b for b in raw['target']['bindings']}
    for t in raw['target']['templates']:
        if t['family_id']=='family:Physics':
            t['required_units']=4;t['occurrences'].append(dict(key='occ:extra',duration=dict(unit='WINDOWS',count=1,max_gap_minutes=0)))
    bs=[];ts={t['family_id']:t for t in raw['target']['templates']}
    for section in raw['source']['plan']['offerings']:
        for occ in ts[section['family_id']]['occurrences']:
            key=occ['key'];block=section['block_id']
            bs.append(dict(section_id=section['id'],occurrence_key=key,
                           candidate_start_ids=['window:D3P1'] if key=='occ:extra' else oldbindings[(block,key)]['candidate_start_ids'],
                           sync_key=None if key=='occ:extra' else f'{block}:{key}'))
    raw['target']['bindings']=bs
    return FlexibleOptionsRequest.model_validate(raw)

def flexible_witness(result):
    p=result.problem; assigns=[]
    for e in p.events:
        assigns.append(dict(event_id=e.id,start_window_id=e.placement.start_window_ids[0],
                            resource_allocations=[dict(requirement_id=q.id,resource_ids=q.eligible_resource_ids[:q.quantity]) for q in e.requirements]))
    return CoreWitness.model_validate(dict(solution_id='candidate:flexible',problem_id=p.problem_id,model_version=p.model_version,status='FEASIBLE',
         event_assignments=assigns,enrollment_assignments=[dict(request_id=q.id,offering_ids=q.eligible_offering_ids) for q in p.participation_requests]))

if __name__=='__main__':
    p,w=operational_pair();assert not core_witness_errors(p,w),core_witness_errors(p,w)
    save('fixtures_rc/R1_operational/problem.json',p);save('fixtures_rc/R1_operational/witness.json',w)
    c=recurrence(p,w);out=project_claims(p,w,c)
    save('fixtures_rc/R2_recurring/config.json',c);save('fixtures_rc/R2_recurring/result.json',out)
    r=flexible_request();h=build_flexible_handoff(r);assert not flexible_handoff_errors(h),flexible_handoff_errors(h)
    fw=flexible_witness(h);assert not core_witness_errors(h.problem,fw),core_witness_errors(h.problem,fw)
    save('fixtures_rc/R3_flexible_options/request.json',r);save('fixtures_rc/R3_flexible_options/handoff.json',h);save('fixtures_rc/R3_flexible_options/witness.json',fw)
    print(json.dumps(dict(operational_events=len(w.event_assignments),projected_occurrences=len(out.occurrences),derived_claims=len(out.claims),flexible_events=len(fw.event_assignments),all_checks='PASS')))
