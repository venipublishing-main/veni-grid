"""Construct a 10-day synthetic school with a known independently checked witness.

Benchmark B is a *solvable-input fixture* with a proof witness, not a claim
that the solver scales to real schools. All IDs/persons are invented.
"""
from __future__ import annotations
from pathlib import Path
import json
from veni_grid_contract.core_v1 import CoreProblem, CoreWitness

ROOT = Path(__file__).resolve().parents[1]


def build():
    days=[{'id':f'day:{d:02}','label':f'Cycle {d}','ordinal':d} for d in range(1,11)]
    begins=[480,520,560,620,660,700,740]
    windows=[{'id':f'window:D{d:02}P{period}','day_id':f'day:{d:02}','bell_id':'bell:standard',
              'sequence':period,'start_minute':begin,'end_minute':begin+40,
              'tags':['FINAL'] if period==7 else []}
             for d in range(1,11) for period,begin in enumerate(begins,1)]
    locs=[{'id':'loc:WEST','label':'West block'},{'id':'loc:EAST','label':'East block'},
          {'id':'loc:LAB','label':'Science laboratories'}]
    resources=[]
    for group in range(8):
        members=[f'person:P{group:02}{i:02}' for i in range(15)]
        resources.extend({'id':rid,'kind':'PERSON','label':'Synthetic learner'} for rid in members)
        resources.append({'id':f'group:G{group:02}','kind':'GROUP','label':f'G{group:02}','member_ids':members})
        resources.append({'id':f'space:R{group:02}','kind':'SPACE','label':f'Room {group}',
                          'capacity':24,'location_id':'loc:WEST' if group<4 else 'loc:EAST'})
        resources.append({'id':f'person:LIFE{group:02}','kind':'PERSON','label':f'Life {group}',
            'unavailable_window_ids':[w['id'] for w in windows if int(w['day_id'][-2:])>2]})
    for pair in range(4):
        for subject in ('MATH','ENG','SCI','HIST'):
            resources.append({'id':f'person:{subject}{pair:02}','kind':'PERSON',
                              'label':f'{subject} educator pair {pair}'})
        resources.append({'id':f'space:LAB{pair:02}','kind':'SPACE',
                          'label':f'Laboratory {pair}','capacity':24,'location_id':'loc:LAB'})
    activities=[];events=[];rules=[];locks=[];witness=[]
    n_by_subject={'MATH':8,'ENG':8,'SCI':6,'HIST':6,'LIFE':2}
    for group in range(8):
        even=group%2==0;pair=group//2
        for subject,count in n_by_subject.items():
            activity=f'activity:G{group:02}:{subject}'
            lesson_units = count + (1 if subject=='SCI' else 0)
            activities.append({'id':activity,'label':f'G{group:02} {subject}',
                               'demand':{'basis':'GLOBAL','unit':'WINDOWS','amount':lesson_units}})
            rules.append({'id':f'rule:spread:G{group:02}:{subject}', 'kind':'ACTIVITY_SPREAD',
                          'strength':'HARD','source':'SYSTEM','activity_ids':[activity],
                          'minimum_distinct_days':count})
            for d in range(1,count+1):
                if subject=='MATH':period=1 if even else 2
                elif subject=='ENG':period=2 if even else 1
                elif subject=='SCI':period=(3 if even else 5) if d==1 else (3 if even else 4)
                elif subject=='HIST':period=(6 if even else 7) if d==1 else (4 if even else 3)
                else:period=(5 if even else 4) if d==1 else 5
                double = subject=='SCI' and d==1
                eid=f'event:G{group:02}:{subject}:D{d:02}'
                teacher=f'person:LIFE{group:02}' if subject=='LIFE' else f'person:{subject}{pair:02}'
                room=f'space:LAB{pair:02}' if subject=='SCI' else f'space:R{group:02}'
                req_t=f'req:{eid}:T';req_r=f'req:{eid}:R'
                start_id=f'window:D{d:02}P{period}'
                alternate_id=f'window:D{(d % 10)+1:02}P{period}'
                domain_starts=[start_id,alternate_id]
                if group==0 and subject=='MATH' and d==1:
                    domain_starts.append('window:D01P7')  # legal but visibly inferior under Q1
                events.append({'id':eid,'label':f'G{group:02} {subject} D{d:02}',
                    'activity_id':activity,'fixed_participant_ids':[f'group:G{group:02}'],
                    'duration':{'unit':'WINDOWS','count':2 if double else 1,
                                'max_gap_minutes':20 if double else 0},
                    'placement':{'start_window_ids':domain_starts},
                    'requirements':[
                        {'id':req_t,'role':'TEACHER','kind':'PERSON','quantity':1,'eligible_resource_ids':[teacher]},
                        {'id':req_r,'role':'ROOM','kind':'SPACE','quantity':1,'eligible_resource_ids':[room],
                         'minimum_capacity':15},
                    ]})
                witness.append({'event_id':eid,'start_window_id':start_id,'resource_allocations':[
                    {'requirement_id':req_t,'resource_ids':[teacher]},
                    {'requirement_id':req_r,'resource_ids':[room]},
                ]})
                if subject=='SCI' and d==1 and group in (0,1):
                    locks.append({'id':f'lock:{eid}','event_id':eid,'start_window_id':start_id})
    problem=CoreProblem.model_validate({
        'schema_version':'1.0.0-rc1','problem_id':'benchmark:B:synthetic',
        'model_version':1,'vertical_id':'SCHOOLS','days':days,'windows':windows,
        'resources':resources,'activities':activities,'events':events,'constraints':rules,
        'locations':locs,'locks':locks,'solve_config':{'mode':'FEASIBILITY','time_limit_seconds':30,
                                                      'random_seed':1,'deterministic':True},
    })
    candidate=CoreWitness.model_validate({'solution_id':'solution:B:known-valid',
        'problem_id':problem.problem_id,'model_version':1,'status':'FEASIBLE',
        'validation':'UNVALIDATED','event_assignments':witness})
    return problem,candidate


def main():
    p,w=build()
    out=ROOT/'fixtures_quality';out.mkdir(parents=True,exist_ok=True)
    (out/'benchmark-b-problem.json').write_text(p.model_dump_json(indent=2)+'\n',encoding='utf-8')
    (out/'benchmark-b-known-witness.json').write_text(w.model_dump_json(indent=2)+'\n',encoding='utf-8')
    print(f'Wrote synthetic Benchmark B: {len(p.events)} events, {len(p.resources)} resources, '
          f'{len(p.windows)} windows, {len(p.constraints)} rules')


if __name__=='__main__':main()
